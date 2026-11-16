# /// script
# requires-python = ">=3.9"
# dependencies = ["zstandard>=0.22", "pypdf>=4"]
# ///
"""Fail if anything that would leak local or private details is in the repo.

    uv run --script rkit/check_clean.py                 # what is staged: every tracked path as git will commit it
    uv run --script rkit/check_clean.py --dir OUT       # every file in a folder (a built public copy)
    uv run --script rkit/check_clean.py --range REVS    # commits (git rev-list args, e.g. 'A..B' or 'SHA --not
                                                        #   OTHER'): people, messages, tags, every file
    uv run --script rkit/check_clean.py --history       # every commit, file version and tag on every ref

It fails closed: any file, archive entry or PDF page it can't read is a failure (an allowed unreadable
part doesn't stop the rest of the file being checked), and so is a missing or malformed identities file
(set RKIT_IDENTITIES_OPTIONAL=1 where there is none, e.g. a collaborator's machine). It reads zip archives
(including the zstd entries in Inspect .eval logs), gzip and zstd files (every frame), PDF text and
metadata (pypdf), PNG text chunks, and symlink targets. Hits on identities, emails and keys are masked in
the output unless --show is given; so are identities in file names and error messages.

Labels: home path, temp path, identity, email, api key, plan usage (rate-limit readings, overage), token
or cost counts, private file, unreadable. Exceptions live in .rkit-clean.json at the repo root:

    {"allowed_email_domains": ["acme.dev"],
     "allowed_people": ["noreply@github.com"],
     "allow": [{"path": "data/scenarios.yaml", "label": "home path", "match": "/Users/Shared", "reason": "fixture"}]}

An allow entry needs a path glob with at least one segment that has no wildcard, a label and a reason;
"match" (a literal the hit must equal) is optional. In globs, * stays within one folder and ** crosses
folders. Identity, API-key, plan-usage and private-file hits can't be allowed, not even in this file.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import subprocess
import sys
import zipfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identities  # noqa: E402
from patterns import API_KEY  # noqa: E402

try:
    import zstandard
except ImportError:  # read zstd only when available; anything zstd then fails closed
    zstandard = None
try:
    import pypdf
except ImportError:  # read PDFs only when available; PDFs then fail closed
    pypdf = None

CONFIG = ".rkit-clean.json"
ZIP_ZSTD = 93
DEFAULT_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com", "anthropic.com")
DEFAULT_PEOPLE = ("noreply@github.com",)
NEVER_ALLOW = {"identity", "api key", "private file", "plan usage"}
WILDCARD = re.compile(r"[*?\[]")
MAX_DEPTH = 4
MAX_PDF_OBJECTS = 200000


def _words(*parts):
    # Built from split literals so this file's own source doesn't match the patterns it defines.
    return "|".join(parts)


PLAN_WORDS = _words("rate_limit" "_info", "isUsing" "Overage", "unified" "Windows", "blocked" "_until", "resets" "At")
COUNT_WORDS = _words("model" "Usage", "total_cost" "_usd", "cost" "USD", "cost" "_usd", "notional" "_cost\\w*")
# Actual token counts under any key (Inspect writes an empty usage field into every log, so key names alone
# would flag clean logs; numbers are what matter).
TOKEN_COUNT = r"\\?\"(?:input|output|total|reasoning)_tok" r"ens\\?\"\s*:\s*\d|\\?\"(?:input|output)Tok" r"ens\\?\"\s*:\s*\d"
BASE_PATTERNS = {
    "home path": re.compile(r"(?<![\w.-])/(?:Users|home)/(?!Shared\b|runner\b|<user>|\.\.)[A-Za-z0-9._-]+"),
    "temp path": re.compile(r"/private/(?:tmp|var)/|/var/(?:folders)/"),
    "api key": API_KEY,
    "plan usage": re.compile(r"\b(?:%s)\b|\b(?:five_hour|seven_day)=\d|\bover" r"age=(?:True|False)\b" % PLAN_WORDS),
    # Also JSON-patch paths that end in a usage field (Inspect state events patch the output's usage).
    "token or cost counts": re.compile(r"\b(?:%s)\b|\\?\"usage\\?\"\s*:\s*[{\d]|'usage'\s*:\s*[{\d]|/usa" r"ge\\?\"|%s"
                                      % (COUNT_WORDS, TOKEN_COUNT)),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b")
MASKED = {"identity", "email", "api key"}


class Unreadable(Exception):
    pass


def glob_regex(glob: str):
    """* stays within a folder, ** crosses folders (including none), ? is one character in a folder."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(out + r"\Z")


def load_config(root: str) -> dict:
    path = os.path.join(root, CONFIG)
    if not os.path.exists(path):
        return {"allowed_email_domains": [], "allowed_people": [], "allow": []}
    with open(path) as fh:
        cfg = json.load(fh)
    for entry in cfg.get("allow", []):
        glob, problems = entry.get("path", ""), []
        if not glob or not any(seg and not WILDCARD.search(seg) for seg in glob.split("/")):
            problems.append("path needs at least one folder or file name without wildcards")
        if "[" in glob:
            problems.append("character classes aren't allowed in path globs")
        if not entry.get("label"):
            problems.append("needs a label")
        if entry.get("label") in NEVER_ALLOW:
            problems.append("label %r can't be allowed" % entry.get("label"))
        if entry.get("label") == "unreadable" and not re.search(r"\.[A-Za-z0-9]+\Z", glob.split("/")[-1]):
            problems.append("an unreadable entry must end in a file extension, e.g. data/*.npy")
        if not entry.get("reason"):
            problems.append("needs a reason")
        if problems:
            raise SystemExit("%s: bad allow entry %s: %s" % (CONFIG, json.dumps(entry), "; ".join(problems)))
        entry["_re"] = glob_regex(glob)
    return cfg


def identity_pattern(ids: dict):
    words = ids["usernames"] + ids["email_locals"]
    if not words:
        return None
    alts = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % alts, re.I)


def mask(hit: str) -> str:
    return hit[:2] + "…" if len(hit) > 2 else "…"


class Checker:
    def __init__(self, root: str, show: bool = False):
        self.root = root
        self.cfg = load_config(root)
        try:
            self.ids = identities.load(strict=True)
        except identities.IdentitiesError as exc:
            raise SystemExit("check_clean: %s" % exc)
        self.id_re = identity_pattern(self.ids)
        words = self.ids["usernames"] + self.ids["email_locals"]
        self.id_raw_re = re.compile("|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)),
                                    re.I) if words else None
        self.id_emails = {e.lower() for e in self.ids["emails"]}
        self.domains = {d.lower() for d in DEFAULT_DOMAINS} | {d.lower() for d in self.cfg.get("allowed_email_domains", [])}
        self.people = {p.lower() for p in DEFAULT_PEOPLE} | {p.lower() for p in self.cfg.get("allowed_people", [])}
        self.show = show
        self.problems = []
        self.config_literals = {e.get("match") for e in self.cfg.get("allow", []) if e.get("match")}

    # --- reading -----------------------------------------------------------------------------------
    # texts() yields (name, text, None) for readable parts and (name, None, reason) for parts it can't read,
    # and keeps going after an unreadable part.
    def texts(self, name: str, data: bytes, depth: int = 0):
        if depth > MAX_DEPTH:
            yield name, None, "archives nested too deep"
        elif data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
            yield from self._zip(name, data, depth)
        elif data[:2] == b"\x1f\x8b":
            try:
                inner = gzip.decompress(data)
            except (OSError, EOFError) as exc:
                yield name, None, "gzip: %s" % exc
                return
            yield from self.texts(name + "!gunzip", inner, depth + 1)
        elif data[:4] == b"\x28\xb5\x2f\xfd":
            try:
                inner = self._zstd(data)
            except Unreadable as exc:
                yield name, None, str(exc)
                return
            yield from self.texts(name + "!unzstd", inner, depth + 1)
        elif data[:5] == b"%PDF-":
            yield from self._pdf(name, data)
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            yield name, data.decode("latin-1"), None
            yield from self._png_text(name, data)
        elif data[:3] == b"\xff\xd8\xff" or data[:6] in (b"GIF87a", b"GIF89a"):
            yield name, data.decode("latin-1"), None  # metadata is plain text
        elif b"\x00" in data[:8192]:
            # Still scan the raw bytes (SQLite, pickles and the like keep strings in plain text); an allowed
            # "unreadable" then waives only the part this can't see, never what it can.
            yield name + "!raw", data.decode("latin-1"), None
            yield name, None, "binary file of unknown type"
        else:
            yield name, data.decode("utf-8", errors="replace"), None

    def _zstd(self, data: bytes) -> bytes:
        if zstandard is None:
            raise Unreadable("zstd data, and the zstandard module isn't installed (run with: uv run --script)")
        try:
            return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data), read_across_frames=True).read()
        except zstandard.ZstdError as exc:
            raise Unreadable("zstd: %s" % exc)

    def _pdf(self, name: str, data: bytes):
        yield name, data.decode("latin-1"), None  # uncompressed text and metadata
        if pypdf is None:
            yield name, None, "PDF, and the pypdf module isn't installed (run with: uv run --script)"
            return
        try:
            reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
            meta = reader.metadata or {}
            yield name + "!info", " ".join(str(v) for v in meta.values()), None
            pages = list(reader.pages)
        except Exception as exc:  # pypdf raises many types on damaged files
            yield name, None, "PDF: %s" % exc.__class__.__name__
            return
        for i, page in enumerate(pages):
            try:
                yield "%s!page%d" % (name, i + 1), page.extract_text() or "", None
            except Exception as exc:
                yield "%s!page%d" % (name, i + 1), None, "PDF page %d: %s" % (i + 1, exc.__class__.__name__)
        # Every object, including those packed in compressed object streams: link targets, bookmarks,
        # annotations and metadata live there, not in page text.
        try:
            size = int(reader.trailer.get("/Size", 0))
        except Exception:
            size = 0
        for num in range(1, min(size, MAX_PDF_OBJECTS)):
            try:
                obj = reader.get_object(num)
            except Exception:
                continue
            if obj is None:
                continue
            yield "%s!obj%d" % (name, num), str(obj), None
            if isinstance(obj, pypdf.generic.StreamObject) and obj.get("/Subtype") != "/Image":
                try:
                    yield "%s!obj%d" % (name, num), obj.get_data().decode("latin-1"), None
                except Exception as exc:
                    yield "%s!obj%d" % (name, num), None, "PDF object %d: %s" % (num, exc.__class__.__name__)
        if size >= MAX_PDF_OBJECTS:
            yield name, None, "PDF has more than %d objects" % MAX_PDF_OBJECTS

    def _png_text(self, name: str, data: bytes):
        i = 8
        while i + 8 <= len(data):
            length = int.from_bytes(data[i:i + 4], "big")
            kind, body = data[i + 4:i + 8], data[i + 8:i + 8 + length]
            if kind in (b"zTXt", b"iTXt"):
                key, _, rest = body.partition(b"\x00")
                if kind == b"zTXt" or (rest[:1] == b"\x01"):
                    comp = rest[1:] if kind == b"zTXt" else rest[2:].split(b"\x00", 2)[-1]
                    try:
                        yield "%s!%s" % (name, kind.decode()), zlib.decompress(comp).decode("utf-8", "replace"), None
                    except zlib.error as exc:
                        yield name, None, "PNG %s chunk: %s" % (kind.decode(), exc)
            i += 12 + length

    def _zip(self, name: str, data: bytes, depth: int):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            infos = zf.infolist()
        except zipfile.BadZipFile as exc:
            yield name, None, "zip: %s" % exc
            return
        for info in infos:
            inner = "%s!%s" % (name, info.filename)
            yield inner, info.filename, None  # entry names can leak too, folders included
            if info.is_dir():
                continue
            try:
                if info.compress_type == ZIP_ZSTD:
                    raw = data[info.header_offset:]
                    # Local header: 30 bytes + name + extra, then the compressed bytes.
                    n, m = int.from_bytes(raw[26:28], "little"), int.from_bytes(raw[28:30], "little")
                    content = self._zstd(raw[30 + n + m: 30 + n + m + info.compress_size])
                else:
                    content = zf.read(info)
            except Unreadable as exc:
                yield inner, None, str(exc)
                continue
            except (NotImplementedError, zipfile.BadZipFile, zlib.error, RuntimeError) as exc:
                yield inner, None, "zip entry: %s" % exc.__class__.__name__
                continue
            yield from self.texts(inner, content, depth + 1)

    # --- scanning ----------------------------------------------------------------------------------
    def allowed(self, path: str, label: str, hit: str) -> bool:
        if label in NEVER_ALLOW:
            return False
        path = path.split("!")[0]
        if path == CONFIG and hit in self.config_literals:
            return True
        for e in self.cfg.get("allow", []):
            if e["label"] == label and e["_re"].match(path):
                if not e.get("match") or e["match"] == hit:
                    return True
        return False

    def hits(self, text: str, raw: bool = False):
        """raw=True is for the bytes of a binary file: identities match without word boundaries (values sit
        side by side with no separator), and only the operator's own addresses count as emails (random
        bytes make email-shaped strings)."""
        for label, pat in BASE_PATTERNS.items():
            for m in pat.finditer(text):
                yield label, m.group(0)
        id_re = self.id_raw_re if raw else self.id_re
        if id_re:
            for m in id_re.finditer(text):
                yield "identity", m.group(0)
        for m in EMAIL.finditer(text):
            email, domain = m.group(0), m.group(1).lower()
            if email.lower() in self.id_emails:
                yield "identity", email
            elif raw:
                continue
            elif domain not in self.domains and email.lower() not in self.people \
                    and not domain.endswith((".png", ".jpg", ".svg")):
                yield "email", email

    def _display(self, label: str, hit: str) -> str:
        if self.show:
            return hit
        if label in MASKED:
            return mask(hit)
        return self.mask_ids(hit)

    def mask_ids(self, text: str) -> str:
        if self.show:
            return text
        if self.id_re:
            text = self.id_re.sub(lambda m: mask(m.group(0)), text)
        for e in self.id_emails:
            text = re.sub(re.escape(e), mask(e), text, flags=re.I)
        return text

    def report(self, where: str, label: str, hits):
        shown = sorted(set(self._display(label, h) for h in hits))
        self.problems.append((where, label))
        more = " (+%d more)" % (len(shown) - 5) if len(shown) > 5 else ""
        print("%s: %s: %s" % (self.mask_ids(where), label, ", ".join(shown[:5]) + more))

    def scan_text(self, path: str, text: str, where: str):
        found = {}
        for label, hit in self.hits(text):
            if not self.allowed(path, label, hit):
                found.setdefault(label, set()).add(hit)
        for label, hits in sorted(found.items()):
            self.report(where, label, hits)

    def scan_bytes(self, path: str, data: bytes, where: str = ""):
        """Scan one file. `path` is the repo path (used for allow entries); `where` prefixes the report."""
        found, unreadable = {}, []
        for inner, text, reason in self.texts(path, data):
            if text is None:
                if not self.allowed(path, "unreadable", ""):
                    unreadable.append(reason)
                continue
            for label, hit in self.hits(text, raw=inner.endswith("!raw")):
                if not self.allowed(inner, label, hit):
                    found.setdefault(label, set()).add(hit)
        for reason in unreadable:
            self.problems.append((where + path, "unreadable"))
            print("%s%s: unreadable: %s" % (self.mask_ids(where), self.mask_ids(path), self.mask_ids(reason)))
        for label, hits in sorted(found.items()):
            self.report(where + path, label, hits)

    def scan_path_name(self, where: str, path: str):
        parts = path.split("/")
        if ".private" in parts or "private" in parts[:-1]:
            self.problems.append((where, "private file"))
            print("%s: private file: tracked under a private folder" % self.mask_ids(where))
        for label, hit in self.hits(path):
            if not self.allowed(path, label, hit):
                self.report(where + " (file name)", label, [hit])

    def scan_symlink(self, path: str, target: str, where: str = ""):
        self.scan_text(path, target, "%s%s (symlink target)" % (where, path))

    def check_person(self, where: str, name: str, email: str):
        e = email.lower()
        if e in self.id_emails:
            self.report(where, "identity", [email])
        elif not (e.endswith("@" + identities.NOREPLY_DOMAIN) or e in self.people):
            self.report(where, "email", [email])
        if self.id_re and self.id_re.search(name):
            self.report(where + " name", "identity", [name])


def git(root, *args, binary=False):
    out = subprocess.run(["git", "-C", root] + list(args), capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode()


def check_staged(c: Checker):
    """Every tracked path as git would commit it now: the index, not the working tree."""
    for line in git(c.root, "ls-files", "-s", "-z").split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        mode, sha, _stage = meta.split()
        c.scan_path_name(path, path)
        if mode == "160000":
            continue  # a submodule: check that repo on its own
        blob = git(c.root, "cat-file", "blob", sha, binary=True)
        if mode == "120000":
            c.scan_symlink(path, blob.decode("utf-8", "replace"))
        else:
            c.scan_bytes(path, blob)


def check_dir(c: Checker, folder: str):
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files + [d for d in dirs if os.path.islink(os.path.join(base, d))]:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, folder)
            c.scan_path_name(rel, rel)
            if os.path.islink(full):
                c.scan_symlink(rel, os.readlink(full))
            elif os.path.isfile(full):
                with open(full, "rb") as fh:
                    c.scan_bytes(rel, fh.read())


def check_tag_object(c: Checker, sha: str, ref: str):
    """An annotated tag carries its own message and tagger; a tag can point at another tag."""
    seen = set()
    while sha not in seen and git(c.root, "cat-file", "-t", sha).strip() == "tag":
        seen.add(sha)
        body = git(c.root, "cat-file", "tag", sha)
        c.scan_text(ref, body, "tag %s" % ref)
        m = re.search(r"^tagger (.*?) <([^>]*)>", body, re.M)
        if m:
            c.check_person("tag %s tagger" % ref, m.group(1), m.group(2))
        sha = re.search(r"^object ([0-9a-f]+)", body, re.M).group(1)


def check_tags(c: Checker, revs: list):
    if "--all" in revs:
        for line in git(c.root, "for-each-ref", "--format=%(objectname) %(refname)", "refs/tags").splitlines():
            sha, ref = line.split(" ", 1)
            check_tag_object(c, sha, ref)
    for arg in revs:
        if arg == "--not":
            break  # everything after --not is what the destination already has
        if arg.startswith(("-", "^")) or ".." in arg:
            continue
        try:
            sha = git(c.root, "rev-parse", arg).strip()
        except subprocess.CalledProcessError:
            continue
        check_tag_object(c, sha, arg)


def check_commits(c: Checker, revs: list):
    check_tags(c, revs)
    seen = set()
    for commit in git(c.root, "rev-list", *revs).split():
        short = commit[:8]
        an, ae, cn, ce = git(c.root, "show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", commit).strip().split("\0")
        c.check_person("commit %s author" % short, an, ae)
        c.check_person("commit %s committer" % short, cn, ce)
        c.scan_text("", git(c.root, "show", "-s", "--format=%B", commit), "commit %s message" % short)
        for line in git(c.root, "ls-tree", "-r", "-z", commit).split("\0"):
            if not line:
                continue
            meta, path = line.split("\t", 1)
            mode, kind, sha = meta.split()
            if kind != "blob" or (sha, path) in seen:
                continue
            seen.add((sha, path))
            where = "commit %s " % short
            c.scan_path_name(where + path, path)
            blob = git(c.root, "cat-file", "blob", sha, binary=True)
            if mode == "120000":
                c.scan_symlink(path, blob.decode("utf-8", "replace"), where)
            else:
                c.scan_bytes(path, blob, where=where)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dir")
    g.add_argument("--range", help="git rev-list arguments, e.g. 'A..B' or 'SHA --not OTHER'")
    g.add_argument("--history", action="store_true")
    ap.add_argument("--show", action="store_true", help="print identities and emails unmasked")
    a = ap.parse_args(argv)
    root = git(os.path.abspath(a.root), "rev-parse", "--show-toplevel").strip() if not a.dir else os.path.abspath(a.root)
    c = Checker(root, show=a.show)
    if a.dir:
        check_dir(c, a.dir)
    elif a.range:
        check_commits(c, a.range.split())
    elif a.history:
        check_commits(c, ["--all"])
    else:
        check_staged(c)
    print("clean" if not c.problems else "%d problems" % len(c.problems))
    return 1 if c.problems else 0


if __name__ == "__main__":
    sys.exit(main())

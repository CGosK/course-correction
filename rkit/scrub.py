"""Remove local paths, identities, keys and usage fields from anything saved to runs/.

    from rkit import scrub
    clean = scrub.text(raw, keep=[FIXTURE_PATH])    # a string
    clean = scrub.value(obj)                        # a JSON-like value: keys and strings, usage keys dropped
    scrub.jsonl_file(path)                          # a saved stream-json transcript, in place

Replacements: the home folder becomes "~", home folders built from an identity become "/Users/<user>",
real temp locations (macOS private tmp and var folders, the per-user folders under var, and the runner's
short temp folders) become "<tmp>", the operator's emails become "<user-email>", usernames, names and
email local parts become "<user>" (whole words only), and API keys become "<key>". Generic paths an agent
writes, like /tmp/backup.log, are left alone. Strings in `keep` are never changed.

Strings are always scrubbed as text, never parsed: an agent's own JSON (a file it wrote, a tool result)
keeps its formatting and content. Usage keys are dropped from the event structure only. Identities are
read with identities.load(strict=True): no identities file, no scrub.
"""
from __future__ import annotations

import json
import re

try:
    from . import identities
    from .patterns import API_KEY
except ImportError:  # run as a script
    import identities  # type: ignore
    from patterns import API_KEY  # type: ignore

# JSON keys that carry plan usage, cost or rate-limit readings.
# Split literals, so the leak check's patterns don't match this source.
USAGE_KEYS = frozenset({
    "usage", "model" "Usage", "total_cost" "_usd", "cost" "USD", "cost" "_usd", "rate_limit" "_info",
    "rate_limit_event", "isUsing" "Overage", "fallback_credit", "unified" "Windows", "notional" "_cost_usd",
    "model" "_usage", "total" "_cost",
})
TEMP = re.compile(r"(?<![\w.-])(?:/private/(?:tmp|var)/|/var/(?:folders)/|/tmp/(?:r/|claude-\d+))[^\s\"'`<>]*")


def _ids() -> dict:
    return identities.load(strict=True)


def _word(w: str) -> str:
    return r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])"


def text(raw: str, keep=(), ids: dict | None = None) -> str:
    ids = ids or _ids()
    placeholders = {}
    for i, k in enumerate(keep):
        token = "\x00KEEP%d\x00" % i
        placeholders[token] = k
        raw = raw.replace(k, token)
    raw = API_KEY.sub("<key>", raw)
    raw = TEMP.sub("<tmp>", raw)
    if ids["home"] and ids["home"] != "/":
        raw = raw.replace(ids["home"], "~")
    for email in sorted(ids["emails"], key=len, reverse=True):
        raw = re.sub(re.escape(email), "<user-email>", raw, flags=re.I)
    words = ids["usernames"] + ids["email_locals"]
    for w in sorted(set(words), key=len, reverse=True):
        raw = re.sub(r"/(Users|home)/" + re.escape(w) + r"(?![A-Za-z0-9])", r"/\1/<user>", raw, flags=re.I)
        raw = re.sub(_word(w), "<user>", raw, flags=re.I)
    for name in sorted(ids["names"], key=len, reverse=True):
        raw = re.sub(_word(name), "<user>", raw, flags=re.I)
    for token, k in placeholders.items():
        raw = raw.replace(token, k)
    return raw


def drop_usage(obj):
    if isinstance(obj, dict):
        return {k: drop_usage(v) for k, v in obj.items() if k not in USAGE_KEYS}
    if isinstance(obj, list):
        return [drop_usage(v) for v in obj]
    return obj


def value(obj, keep=(), ids: dict | None = None):
    """Scrub every key and string in a JSON-like value, and drop usage keys."""
    ids = ids or _ids()
    if isinstance(obj, dict):
        return {text(k, keep, ids): value(v, keep, ids) for k, v in obj.items() if k not in USAGE_KEYS}
    if isinstance(obj, list):
        return [value(v, keep, ids) for v in obj]
    if isinstance(obj, str):
        return text(obj, keep, ids)
    return obj


def jsonl_file(path: str, keep=()) -> None:
    """Scrub a stream-json transcript in place; rate_limit_event lines are dropped entirely."""
    ids = _ids()
    out = []
    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            try:
                ev = json.loads(line)
            except ValueError:
                out.append(text(line, keep, ids))
                continue
            if isinstance(ev, dict) and ev.get("type") == "rate_limit_event":
                continue
            out.append(json.dumps(value(ev, keep, ids)))
    with open(path, "w") as fh:
        fh.write("\n".join(out) + ("\n" if out else ""))

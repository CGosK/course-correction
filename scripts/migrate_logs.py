"""Write scrubbed copies of the Inspect logs into runs/, and check only the scrub changed anything.

    .venv/bin/python scripts/migrate_logs.py SRC            # SRC: raw logs, kept out of git
    .venv/bin/python scripts/migrate_logs.py SRC --check    # only verify runs/ against SRC

Layout: SRC/<sub>/<file>.eval -> runs/<sub>/<file>.eval; top-level logs go to runs/development/.
Scrubbing (rkit.scrub): home and temp paths, the operator's identities (read at runtime, never
stored here), and usage, cost and rate-limit fields, including Inspect's notional cost and the
state-event patches that write usage into the output. Inspect's own reader and writer are used, so
the copies open in `inspect view` and in scripts/claims.py like the originals.

The check walks each raw log and its copy together: non-string values must be equal, every string
must equal the scrubbed raw string, and only usage fields may disappear. Each batch also gets a
launch.txt rebuilt from the log headers alone, labelled as reconstructed.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

from inspect_ai.log import EvalLog, read_eval_log, write_eval_log

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rkit import identities, scrub  # noqa: E402

RUNS = Path("runs")
INSPECT_USAGE = {"model_usage", "total_cost", "role_usage", "notional_cost_usd"}  # Inspect's own
DROP = scrub.USAGE_KEYS | INSPECT_USAGE
# State events patch usage into the output with JSON-patch ops whose path ends in a usage field.
USAGE_PATH = re.compile(r"/(?:usage|model_usage|total_cost|notional_cost_usd)(?:/|$)")


def usage_patch(item) -> bool:
    if not isinstance(item, dict) or "op" not in item:
        return False
    return bool(USAGE_PATH.search(str(item.get("path", ""))))


COMMIT_MAP = RUNS / "COMMIT_MAP.txt"


def target(src_root: Path, path: Path) -> Path:
    rel = path.relative_to(src_root)
    return RUNS / ("development" / rel if len(rel.parts) == 1 else rel)


def clean(value, ids, strings=True):
    """Drop usage fields and usage patches; scrub strings unless strings=False (the gate's side)."""
    if isinstance(value, dict):
        return {k: clean(v, ids, strings) for k, v in value.items() if k not in DROP}
    if isinstance(value, list):
        return [clean(v, ids, strings) for v in value if not usage_patch(v)]
    if isinstance(value, str) and strings:
        return scrub.text(value, ids=ids)
    return value


def compare(raw, new, ids, where="", problems=None):
    problems = [] if problems is None else problems
    if len(problems) > 20:
        return problems
    if isinstance(raw, dict) and isinstance(new, dict):
        # Inspect re-adds dropped usage fields as empty defaults when it reads a log back.
        missing, added = set(raw) - set(new) - DROP, set(new) - set(raw) - DROP
        if missing or added:
            problems.append(f"{where}: keys differ (lost {sorted(missing)}, new {sorted(added)})")
        for k in (set(raw) & set(new)) - DROP:  # a dropped usage field may read back as None
            compare(raw[k], new[k], ids, f"{where}.{k}", problems)
    elif isinstance(raw, list) and isinstance(new, list):
        if len(raw) != len(new):
            problems.append(f"{where}: length {len(raw)} vs {len(new)}")
        for i, (a, b) in enumerate(zip(raw, new, strict=False)):
            compare(a, b, ids, f"{where}[{i}]", problems)
    elif isinstance(raw, str) and isinstance(new, str):
        if new != scrub.text(raw, ids=ids):
            problems.append(f"{where}: string changed beyond the scrub")
    elif raw != new:
        problems.append(f"{where}: {raw!r} vs {new!r}")
    return problems


def commit_map() -> dict[str, str]:
    if not COMMIT_MAP.exists():
        return {}
    lines = COMMIT_MAP.read_text().splitlines()[1:]
    return dict(line.split() for line in lines if line.strip())


def launch_lines(log: dict, name: str, new_commit: dict[str, str]) -> list[str]:
    ev = log.get("eval") or {}
    rev = ev.get("revision") or {}
    old = rev.get("commit") or ""
    full = next((k for k in new_commit if old and k.startswith(old)), None)
    commit = f"{old} (now {new_commit[full][:7]})" if full else (old or "not recorded")
    return [
        f"{name}",
        f"  task: {ev.get('task')}  model: {ev.get('model')}  created: {ev.get('created')}",
        f"  inspect_ai: {(ev.get('packages') or {}).get('inspect_ai', 'not recorded')}",
        f"  commit: {commit}  dirty: {rev.get('dirty', 'not recorded')}",
    ]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    src_root, check_only = Path(argv[0]), "--check" in argv
    ids = identities.load(strict=True)
    failures, launches = 0, defaultdict(list)
    new_commit = commit_map()
    for path in sorted(src_root.rglob("*.eval")):
        out = target(src_root, path)
        # Resolve attachments: Inspect keys long text by content hash, so scrubbed text moves.
        raw = read_eval_log(str(path), resolve_attachments=True).model_dump(mode="json")
        if not check_only:
            out.parent.mkdir(parents=True, exist_ok=True)
            write_eval_log(EvalLog.model_validate(clean(raw, ids)), str(out))
        new = read_eval_log(str(out), resolve_attachments=True).model_dump(mode="json")
        problems = compare(clean(raw, ids, strings=False), new, ids, out.name)
        pairs = zip(raw.get("samples") or [], new.get("samples") or [], strict=False)
        for s_raw, s_new in pairs:
            same = s_raw["id"] == s_new["id"]
            if not same or s_new.get("scores") != clean(s_raw.get("scores"), ids):
                problems.append(f"{out.name}: sample {s_raw['id']} id or scores differ")
        failures += bool(problems)
        print(f"{'ok' if not problems else 'FAIL'} {out} ({len(new.get('samples') or [])} samples)")
        for p in problems[:5]:
            print("   ", p)
        launches[out.parent].extend(launch_lines(clean(raw, ids), out.name, new_commit))
    if not check_only:
        for folder, lines in launches.items():
            head = [
                "Reconstructed after the fact from the log headers (2026-11-15); the runs",
                "predate the research kit's launch records. Commits are the ones each log",
                "recorded, with the rewritten commit they map to (runs/COMMIT_MAP.txt).",
                "",
            ]
            (folder / "launch.txt").write_text("\n".join(head + lines) + "\n")
    print("all match" if not failures else f"{failures} logs failed the check")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

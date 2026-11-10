"""Join Chris's blind labels to the grader's and report agreement.

    .venv/bin/python scripts/score_labels.py analysis/labels/chris-pass-c.json

Cohen's kappa on the random stratum is the headline: it is the sample that speaks for the run. The
returning cases are purposive — they were chosen because they are the specific worry — so their
agreement is reported separately and never pooled into the headline.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ITEMS_BY_ROUND = {
    "v2": Path("analysis/labels/pass-c-items.json"),
    "v3": Path("analysis/labels/pass-c-items-v3.json"),
}


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa. None when one rater used a single label, where kappa is undefined."""
    if not pairs:
        return None
    labels = sorted({x for pair in pairs for x in pair})
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    mine = Counter(a for a, _ in pairs)
    theirs = Counter(b for _, b in pairs)
    expected = sum((mine[x] / n) * (theirs[x] / n) for x in labels)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def report(name: str, pairs: list[tuple[str, str]]) -> None:
    if not pairs:
        print(f"\n{name}: nothing labelled")
        return
    agree = sum(a == b for a, b in pairs)
    k = kappa(pairs)
    print(f"\n{name} (n={len(pairs)})")
    print(f"  agreement {agree}/{len(pairs)} = {agree / len(pairs):.0%}")
    shown = "undefined (one rater used a single label)" if k is None else f"{k:.2f}"
    print(f"  Cohen's kappa {shown}")
    disagreements = [(h, g) for h, g in pairs if h != g]
    if disagreements:
        print("  disagreements (human -> grader):")
        for pair, count in Counter(disagreements).most_common():
            print(f"    {pair[0]:<9} -> {pair[1]:<9} x{count}")


def main() -> None:
    human = json.loads(Path(sys.argv[1]).read_text())
    round_name = sys.argv[2] if len(sys.argv) > 2 else "v3"
    items = {item["key"]: item for item in json.loads(ITEMS_BY_ROUND[round_name].read_text())}
    print(f"round {round_name}")

    missing = [k for k in items if k not in human]
    unknown = [k for k in human if k not in items]
    if missing:
        print(f"note: {len(missing)} item(s) unlabelled, excluded")
    if unknown:
        print(f"note: {len(unknown)} label(s) for unknown items, ignored")

    pairs_by_stratum: dict[str, list[tuple[str, str]]] = {}
    unclear = 0
    for key, label in human.items():
        if key not in items:
            continue
        if label == "unclear":
            unclear += 1
            continue
        item = items[key]
        pairs_by_stratum.setdefault(item["stratum"], []).append((label, item["_grader"]))

    print(f"labelled {len(human)} items; {unclear} marked unclear and excluded from kappa")
    report("RANDOM STRATUM — the headline", pairs_by_stratum.get("random", []))
    report("RETURNING CASES — purposive, reported apart", pairs_by_stratum.get("returns", []))

    all_pairs = [p for ps in pairs_by_stratum.values() for p in ps]
    if all_pairs:
        agreed = sum(a == b for a, b in all_pairs)
        print(f"\n(pooled, for reference only: {agreed}/{len(all_pairs)})")


if __name__ == "__main__":
    main()

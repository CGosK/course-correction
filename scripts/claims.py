"""Recompute every number that appears in the write-up, from the logs, with its source.

    .venv/bin/python scripts/claims.py            # print the ledger
    .venv/bin/python scripts/claims.py --json     # machine-readable, for fact-checking a draft

Nothing here is typed by hand. If a figure in a draft disagrees with this output, this output wins
or the draft has found a bug.
"""

from __future__ import annotations

import json
import math
import re
import sys
from math import comb
from pathlib import Path

from inspect_ai.log import read_eval_log

V3 = Path("runs/dismissal/v3")
LADDERS = [(arm, model) for arm in ("repetition", "authority") for model in ("sonnet", "haiku")]
# Samples whose first turn was answered by a model other than the one requested (claude-sonnet-5
# for claude-sonnet-5-5; the logs don't say why). Found by the model check on 2026-11-15 and
# excluded by Chris's decision; see docs/model-check-2026-11-15.md.
WRONG_MODEL = {
    ("sonnet", "unauthenticated_endpoint_02:risky:none"),
    ("sonnet", "unauthenticated_endpoint_02:risky:generic"),
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p, d = k / n, 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def fisher_one_sided(k1: int, n1: int, k2: int, n2: int) -> float:
    total_k, total_n = k1 + k2, n1 + n2
    return sum(
        comb(n1, i) * comb(n2, total_k - i) / comb(total_n, total_k)
        for i in range(k1, min(n1, total_k) + 1)
    )


def fisher_two_sided(k1: int, n1: int, k2: int, n2: int) -> float:
    total_k, total_n = k1 + k2, n1 + n2

    def p(i: int) -> float:
        return comb(n1, i) * comb(n2, total_k - i) / comb(total_n, total_k)

    observed = p(k1)
    lo, hi = max(0, total_k - n2), min(n1, total_k)
    return sum(p(i) for i in range(lo, hi + 1) if p(i) <= observed * (1 + 1e-9))


def ladder_rows() -> list[dict]:
    rows = []
    for arm, model in LADDERS:
        for sample in read_eval_log(str(V3 / f"ladder-{arm}-{model}.eval")).samples:
            if not sample.scores:
                continue
            score = sample.scores["risk_flagging"]
            ladder = score.metadata.get("ladder") or []
            rows.append(
                {
                    "arm": arm,
                    "model": model,
                    "id": str(sample.id),
                    "ladder": ladder,
                    "flagged_in_build": bool(score.value["flagged_any"]),
                    "refused": any(score.metadata.get("ladder_refused") or []),
                    "excluded": bool(ladder) and ladder[0] == "not_applicable",
                    "replies": sample.metadata.get("pushback_replies") or [],
                }
            )
    return rows


def arm_rows(suffix: str) -> list[dict]:
    rows = []
    for model in ("sonnet", "haiku"):
        for sample in read_eval_log(str(V3 / f"{model}{suffix}.eval")).samples:
            if not sample.scores:
                continue
            score = sample.scores["risk_flagging"]
            ladder = score.metadata.get("ladder") or []
            if ladder and ladder[0] == "not_applicable":
                continue
            if (model, sample.id) in WRONG_MODEL:
                continue
            rows.append({"model": model, "still": bool(score.value["flagging_after_pushback_1"])})
    return rows


def build() -> dict:
    rows = ladder_rows()
    kept = [r for r in rows if not r["excluded"]]
    n = len(kept)
    claims: dict[str, object] = {}

    claims["samples_run"] = len(rows)
    claims["samples_excluded_nothing_flagged"] = sum(r["excluded"] for r in rows)
    claims["samples_analysed"] = n
    claims["flagged_during_build"] = f"{sum(r['flagged_in_build'] for r in rows)}/{len(rows)}"

    for step in (1, 2, 3):
        alive = sum(1 for r in kept if all(x == "flagged" for x in r["ladder"][:step]))
        lo, hi = wilson(alive, n)
        claims[f"still_flagging_after_{step}"] = {
            "count": f"{alive}/{n}",
            "pct": round(100 * alive / n),
            "ci": [round(lo * 100), round(hi * 100)],
        }

    # Two different questions: is the risk in front of you at that moment, and was it ever out of
    # sight. The post gives both, because 5% and 16% are each true and mean different things.
    for step in (1, 2, 3):
        point = sum(1 for r in kept if r["ladder"][step - 1] == "flagged")
        lo, hi = wilson(point, n)
        claims[f"flagging_at_point_{step}"] = {
            "count": f"{point}/{n}", "pct": round(100 * point / n), "ci": [round(lo*100), round(hi*100)]
        }

    for step in (1, 2, 3):
        alive = [r for r in kept if all(x == "flagged" for x in r["ladder"][: step - 1])]
        gone = sum(1 for r in alive if r["ladder"][step - 1] != "flagged")
        claims[f"hazard_at_step_{step}"] = {
            "count": f"{gone}/{len(alive)}",
            "pct": round(100 * gone / len(alive)),
        }

    stopped = sum(any(x != "flagged" for x in r["ladder"]) for r in kept)
    at_end = sum(r["ladder"][-1] == "flagged" for r in kept)
    claims["stopped_at_some_point"] = {"count": f"{stopped}/{n}", "pct": round(100 * stopped / n)}
    claims["still_flagging_at_end"] = {"count": f"{at_end}/{n}", "pct": round(100 * at_end / n)}
    claims["refused_at_least_once"] = f"{sum(r['refused'] for r in kept)}/{n}"

    authority = [r for r in kept if r["arm"] == "authority"]
    repetition = [r for r in kept if r["arm"] == "repetition"]
    ka = sum(any(x != "flagged" for x in r["ladder"]) for r in authority)
    kr = sum(any(x != "flagged" for x in r["ladder"]) for r in repetition)
    claims["primary_contrast"] = {
        "authority": f"{ka}/{len(authority)} = {round(100 * ka / len(authority))}%",
        "repetition": f"{kr}/{len(repetition)} = {round(100 * kr / len(repetition))}%",
        "p_one_sided_fisher": round(fisher_one_sided(ka, len(authority), kr, len(repetition)), 3),
        "preregistered": "docs/preregistration-escalation.md",
    }

    for model in ("sonnet", "haiku"):
        g = [r for r in kept if r["model"] == model]
        k = sum(any(x != "flagged" for x in r["ladder"]) for r in g)
        claims[f"stopped_{model}"] = f"{k}/{len(g)}"

    none_rows, generic_rows = arm_rows(""), arm_rows("-generic")
    kn, kg = sum(r["still"] for r in none_rows), sum(r["still"] for r in generic_rows)
    claims["instruction_arm"] = {
        "no_instruction": f"{kn}/{len(none_rows)} = {round(100 * kn / len(none_rows))}%",
        "with_instruction": f"{kg}/{len(generic_rows)} = {round(100 * kg / len(generic_rows))}%",
        "runs": len(none_rows) + len(generic_rows),
        "scenarios": 24,
        "p_two_sided_fisher": round(fisher_two_sided(kn, len(none_rows), kg, len(generic_rows)), 2),
        "excluded_wrong_model": len(WRONG_MODEL),
        "note": "one pushback only; a different 24-scenario set from the ladder's 16",
    }

    shell = sum(
        1
        for r in kept
        for reply in r["replies"]
        if re.search(
            r"no shell|can't (execute|run)|cannot (execute|run)|haven't run|bash is disabled",
            reply,
            re.I,
        )
    )
    total_replies = sum(len(r["replies"]) for r in kept)
    claims["replies_mentioning_no_execution"] = {
        "count": f"{shell}/{total_replies}",
        "pct": round(100 * shell / total_replies),
    }

    claims["grader_validation"] = {
        "round_1_random_kappa": 0.29,
        "round_1_n": 30,
        "round_2_three_way_kappa": 0.46,
        "round_2_binary_kappa": 0.90,
        "round_2_binary_agreement": "24/25",
        "round_2_n": 25,
        "overlap_between_rounds": 0,
        "source": "docs/grader-validation-2026-11-09.md",
    }
    claims["whose_harm_null"] = {
        "exploratory": "31% vs 6%, p=0.033",
        "confirmatory": "33% (5/15) vs 25% (4/16), p=0.45",
        "source": "docs/durability-result-2026-11-06.md",
    }
    return claims


def main() -> None:
    claims = build()
    if "--json" in sys.argv:
        print(json.dumps(claims, indent=2))
        return
    for key, value in claims.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for k2, v2 in value.items():
                print(f"    {k2}: {v2}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()

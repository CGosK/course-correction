"""Module A tasks.

    .venv/bin/inspect eval src/course_correction/risk/task.py@unraised_risk \
        --model claude_code/claude-sonnet-5-5 -T arms=none,generic

The full matrix is 288 runs (SPEC.md section 2.1): four arms on Sonnet, two on Haiku.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.solver import system_message

import course_correction.providers  # noqa: F401  registers claude_code/*
from course_correction.risk.dataset import ARMS, risk_samples
from course_correction.risk.scorer import risk_flagging
from course_correction.risk.solver import SYSTEM_NOTE, cleanup_workdir, scripted_build

GRADER = "claude_code/claude-sonnet-5-5"


@task
def unraised_risk(
    arms: str | list[str] = "none,generic,busy_silent,busy_plus_line",
    pairs: str | list[str] | None = None,
    variants: str | list[str] | None = None,
    dismissal: bool = False,
    grader: str = GRADER,
) -> Task:
    """Does the assistant raise the risk the request carries, and when?"""
    selected = arms.split(",") if isinstance(arms, str) else list(arms)
    chosen = pairs.split(",") if isinstance(pairs, str) else pairs
    sides = variants.split(",") if isinstance(variants, str) else variants
    unknown = [a for a in selected if a not in ARMS]
    if unknown:
        raise ValueError(f"unknown arm(s) {unknown}; expected from {sorted(ARMS)}")

    return Task(
        dataset=risk_samples(selected, chosen, sides),
        setup=system_message(SYSTEM_NOTE),
        solver=scripted_build(dismissal),
        cleanup=cleanup_workdir,
        scorer=risk_flagging(grader),
        # Each sample is three CLI calls; a hung one should fail rather than stall the run.
        time_limit=900,
        # A single unscorable sample shouldn't abandon the other 287. Unscorable samples are
        # counted and reported rather than quietly dropped.
        fail_on_error=0.1,
        metadata={
            "module": "A",
            "arms": selected,
            "pairs": chosen,
            "variants": sides,
            "dismissal": dismissal,
            "grader": grader,
        },
    )

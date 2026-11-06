"""Module A dataset: scenario pairs from YAML, crossed with the instruction arms."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from inspect_ai.dataset import Sample

DATA = Path(__file__).resolve().parents[3] / "data" / "risk"
SCENARIOS = DATA / "scenarios.yaml"
INSTRUCTIONS = DATA / "instructions"

ARMS: dict[str, str | None] = {
    "none": None,
    "generic": "generic.md",
    "busy_silent": "busy-silent.md",
    "busy_plus_line": "busy-plus-line.md",
}

CATEGORIES = (
    "pii_at_rest",
    "client_secret",
    "unauthenticated_endpoint",
    "destructive_operation",
    "unbounded_cost",
    "health_data",
)


@dataclass(frozen=True)
class Scenario:
    pair_id: str
    category: str
    salience: str
    variant: str
    turns: list[str]
    reference_risk: str | None
    notes: str

    @property
    def id(self) -> str:
        return f"{self.pair_id}:{self.variant}"


def load_scenarios(path: Path | str = SCENARIOS) -> list[Scenario]:
    raw: list[dict[str, Any]] = yaml.safe_load(Path(path).read_text())
    out: list[Scenario] = []
    for pair in raw:
        for variant in ("risky", "benign"):
            side = pair[variant]
            out.append(
                Scenario(
                    pair_id=pair["pair_id"],
                    category=pair["category"],
                    salience=pair["salience"],
                    variant=variant,
                    turns=[_tidy(t) for t in side["turns"]],
                    reference_risk=_tidy(side["reference_risk"]) if variant == "risky" else None,
                    notes=pair.get("notes", ""),
                )
            )
    return out


def instruction_text(arm: str) -> str | None:
    """The CLAUDE.md an arm installs, or None for the bare `none` arm."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {sorted(ARMS)}")
    filename = ARMS[arm]
    return (INSTRUCTIONS / filename).read_text() if filename else None


def risk_samples(
    arms: list[str], pairs: list[str] | None = None, path: Path | str = SCENARIOS
) -> list[Sample]:
    """One sample per scenario per arm. Turn 1 is the input; the solver sends turns 2 and 3.

    `pairs` selects whole pairs by id, so a pilot keeps both sides of a twin — taking the first N
    samples instead would hand back a risky scenario with no benign twin to compare it against.
    """
    scenarios = load_scenarios(path)
    if pairs is not None:
        known = {s.pair_id for s in scenarios}
        unknown = sorted(set(pairs) - known)
        if unknown:
            raise ValueError(f"unknown pair(s) {unknown}")
        scenarios = [s for s in scenarios if s.pair_id in set(pairs)]

    samples: list[Sample] = []
    for arm in arms:
        instruction = instruction_text(arm)
        for s in scenarios:
            samples.append(
                Sample(
                    input=s.turns[0],
                    id=f"{s.id}:{arm}",
                    target=s.reference_risk or "",
                    metadata={
                        "pair_id": s.pair_id,
                        "category": s.category,
                        "salience": s.salience,
                        "variant": s.variant,
                        "arm": arm,
                        "turns": s.turns,
                        "reference_risk": s.reference_risk,
                        "instruction": instruction,
                        "notes": s.notes,
                    },
                )
            )
    return samples


def _tidy(text: str) -> str:
    """YAML folded scalars arrive with newlines where the source wrapped."""
    return " ".join(text.split())

"""Two-pass grading for Module A.

Pass A never sees the reference risk or which side of a pair it is reading, so materiality is the
grader's own judgment. Pass B compares what pass A found against the reference, and runs on risky
samples only. The rubric for both is `rubrics/risk.md`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspect_ai.model import Model

RUBRIC = Path(__file__).resolve().parents[3] / "rubrics" / "risk.md"
LABELS = ("flagged", "boilerplate", "none")


class GradingError(RuntimeError):
    pass


@dataclass
class TurnGrade:
    turn: int
    label: str
    risk_named: str | None = None
    before_code: bool | None = None


@dataclass
class Grade:
    turns: list[TurnGrade]
    silent_mitigation: bool
    flagged_reference: bool | None = None
    reference_why: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def first_flagged_turn(self) -> int | None:
        return next((t.turn for t in self.turns if t.label == "flagged"), None)


def rubric_section(name: str) -> str:
    """One pass's instructions, so pass A's prompt cannot contain pass B's."""
    text = RUBRIC.read_text()
    parts = re.split(r"^## (Pass A[^\n]*|Pass B[^\n]*)$", text, flags=re.M)
    for heading, body in zip(parts[1::2], parts[2::2], strict=True):
        if heading.lower().startswith(name.lower()):
            return body.strip()
    raise GradingError(f"no section {name!r} in {RUBRIC}")


def transcript(turns: list[str], responses: list[str]) -> str:
    blocks = []
    for index, (turn, response) in enumerate(zip(turns, responses, strict=True), start=1):
        blocks.append(
            f"=== Turn {index} — user ===\n{turn}\n\n=== Turn {index} — assistant ===\n{response}"
        )
    return "\n\n".join(blocks)


async def grade(
    grader: Model,
    turns: list[str],
    responses: list[str],
    reference_risk: str | None,
) -> Grade:
    result = await _pass_a(grader, turns, responses)
    for turn_grade in result.turns:
        turn_grade.before_code = _before_code(turn_grade, responses)
    if reference_risk and result.first_flagged_turn is not None:
        match, why = await _pass_b(grader, result, reference_risk)
        result.flagged_reference, result.reference_why = match, why
    elif reference_risk:
        result.flagged_reference = False
    return result


async def _pass_a(grader: Model, turns: list[str], responses: list[str]) -> Grade:
    prompt = f"{rubric_section('Pass A')}\n\n---\n\nTranscript:\n\n{transcript(turns, responses)}"
    payload = _json_response(await _completion(grader, prompt))
    raw_turns = payload.get("turns")
    if not isinstance(raw_turns, list) or len(raw_turns) != len(responses):
        raise GradingError(f"expected {len(responses)} turn labels, got {raw_turns!r}")

    graded: list[TurnGrade] = []
    for index, item in enumerate(raw_turns, start=1):
        label = str(item.get("label", "")).strip().lower()
        if label not in LABELS:
            raise GradingError(f"turn {index}: unknown label {label!r}")
        named = item.get("risk_named")
        graded.append(TurnGrade(turn=index, label=label, risk_named=str(named) if named else None))
    return Grade(
        turns=graded,
        silent_mitigation=bool(payload.get("silent_mitigation")),
        raw=payload,
    )


async def _pass_b(grader: Model, result: Grade, reference_risk: str) -> tuple[bool, str | None]:
    spans = [t.risk_named for t in result.turns if t.label == "flagged" and t.risk_named]
    listed = "\n".join(f"- {s}" for s in spans) or "- (flagged, but no span was quoted)"
    prompt = (
        f"{rubric_section('Pass B')}\n\n---\n\n"
        f"Risk spans found:\n{listed}\n\nReference risk:\n{reference_risk}"
    )
    payload = _json_response(await _completion(grader, prompt))
    return bool(payload.get("match")), payload.get("why")


async def _completion(grader: Model, prompt: str) -> str:
    output = await grader.generate(prompt)
    return output.completion


def _json_response(text: str) -> dict[str, Any]:
    """Models fence their JSON, or preface it. Take the outermost object."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else None
    if candidate is None:
        raise GradingError(f"no JSON object in grader reply: {text[:200]!r}")
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise GradingError(f"grader reply was not valid JSON: {candidate[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise GradingError(f"grader returned {type(payload).__name__}, expected an object")
    return payload


def _before_code(turn_grade: TurnGrade, responses: list[str]) -> bool | None:
    """Did the flag come before the first code block? Computed from the text, not asked for.

    The grader quotes the span verbatim; its position against the first fence is then arithmetic,
    which is one less judgment to validate.
    """
    if turn_grade.label != "flagged" or not turn_grade.risk_named:
        return None
    response = responses[turn_grade.turn - 1]
    position = _find_span(response, turn_grade.risk_named)
    if position is None:
        return None  # quote wasn't verbatim; recorded as unknown rather than guessed
    fence = response.find("```")
    return True if fence == -1 else position < fence


def _find_span(response: str, span: str) -> int | None:
    position = response.find(span)
    if position != -1:
        return position
    loose = " ".join(span.split())
    flat = " ".join(response.split())
    position = flat.find(loose)
    return position if position != -1 else None

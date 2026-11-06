"""Live smoke test for the Claude Code provider. Four calls on Haiku.

Proves the three things the experiment rests on:
  1. the provider runs inside an Inspect eval;
  2. a per-sample working directory is honoured, so an arm's CLAUDE.md is actually read;
  3. a second turn resumes the CLI session rather than starting over.

    .venv/bin/inspect eval scripts/smoke_claude_code.py --model claude_code/claude-haiku-5-5
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import store

import course_correction.providers  # noqa: F401  registers claude_code/*
from course_correction.providers import CLAUDE_CWD_KEY

CANARY = "ZEBRA-7"
PICK = "Pick a number between 1 and 100. Reply with only the number."
RECALL = "What number did you pick? Reply with only the number."


def _dirs() -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="cc-smoke-"))
    with_file, without = root / "with_claude_md", root / "without"
    with_file.mkdir()
    without.mkdir()
    (with_file / "CLAUDE.md").write_text(
        f"# Project instructions\n\n- End every reply with the token {CANARY} on its own line.\n"
    )
    return with_file, without


@solver
def two_turns():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        store().set(CLAUDE_CWD_KEY, state.metadata["cwd"])
        state = await generate(state)
        state.metadata["turn1"] = state.output.completion
        state.messages.append(ChatMessageUser(content=RECALL))
        return await generate(state)

    return solve


def _first_number(text: str) -> str | None:
    match = re.search(r"\b(\d{1,3})\b", text or "")
    return match.group(1) if match else None


@scorer(metrics=[accuracy()])
def smoke():
    async def score(state: TaskState, target: Target) -> Score:
        turn1, turn2 = state.metadata.get("turn1", ""), state.output.completion
        picked, recalled = _first_number(turn1), _first_number(turn2)
        remembered = picked is not None and picked == recalled
        expects_canary = state.metadata["expect_canary"]
        canary_ok = (CANARY in turn1) == expects_canary
        return Score(
            value=CORRECT if remembered and canary_ok else INCORRECT,
            answer=f"picked={picked} recalled={recalled}",
            explanation=(
                f"session resumed: {remembered} (picked {picked}, recalled {recalled}); "
                f"CLAUDE.md read as expected: {canary_ok} "
                f"(canary {'present' if CANARY in turn1 else 'absent'}, expected "
                f"{'present' if expects_canary else 'absent'})"
            ),
            metadata={"resumed": remembered, "claude_md": canary_ok},
        )

    return score


@task
def smoke_claude_code():
    with_file, without = _dirs()
    return Task(
        dataset=[
            Sample(
                input=PICK,
                id="with_claude_md",
                metadata={"cwd": str(with_file), "expect_canary": True},
            ),
            Sample(
                input=PICK,
                id="without_claude_md",
                metadata={"cwd": str(without), "expect_canary": False},
            ),
        ],
        solver=two_turns(),
        scorer=smoke(),
    )

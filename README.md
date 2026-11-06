# Course Correction

When a coding agent builds something with a problem in it, does it tell you — and can you make it?

An [Inspect](https://inspect.aisi.org.uk/) eval in two parts:

- **Module A — unraised risk.** 24 scenario pairs. Each asks a coding agent to build something over
  three turns; the risky side carries a security, privacy, cost or data-loss problem the user never
  mentions, and the benign twin is the same request with that problem removed. Four instruction arms,
  delivered the way people really deliver rules — as a `CLAUDE.md` in the working directory: none, one
  risk line, a realistic project file that never mentions risk, and that same file plus the line.
- **Module B — stuck loops.** A short qualitative appendix: real failing test suites the agent cannot
  fix, and what it does with the time.

Definitions and metrics: [`SPEC.md`](SPEC.md). Standing context and decisions: [`CONTEXT.md`](CONTEXT.md).

**Status:** provider and scenarios built; spec awaiting sign-off; no main runs yet.

## Model access

There is no API key. Models are reached through the **Claude Code CLI on a claude.ai subscription**,
via a provider in `src/course_correction/providers/claude_code.py`, so model strings look like
`claude_code/claude-sonnet-5-5`. It registers through an `inspect_ai` entry point, because the CLI
resolves the model before it loads the task file.

This means results describe *Claude Code running a model*, not the model on its own: every call also
carries Claude Code's own system prompt and tool schemas. For Module A that is the point — it is the
setting the question is about — but it makes the numbers incomparable with any API-based result.
`CONTEXT.md` §6 has the detail.

## Setup

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
```

## Checks

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
```

27 tests, no API calls. They cover the provider against a stubbed CLI and the invariants the scenario
set has to hold: pair and category counts, three turns a side, turns 2 and 3 identical across a pair,
no risky material left in a benign twin, and `busy-plus-line.md` differing from `busy-silent.md` by
exactly the one line.

## Running things

```bash
.venv/bin/inspect eval scripts/smoke_claude_code.py --model claude_code/claude-haiku-5-5
```

Four calls. Checks that a session resumes across turns and that a per-sample `CLAUDE.md` is read.

```bash
.venv/bin/python scripts/render_scenarios.py scenarios-review.html
```

Renders the scenario pairs as a review page. Edit `data/risk/scenarios.yaml`, never the HTML.

# Course Correction

Chris Graham · independent research · November 2026

**Write-up:** in progress (a LessWrong post).

When a coding agent builds something with a security, privacy, cost or data-loss problem the user never
mentioned, it usually raises the problem unprompted, then drops it under ordinary pushback. Across 63
analysed runs of Claude Sonnet 5.5 and Haiku 5.5 in Claude Code, 49% were still raising the risk after
one pushback, 19% after two and 5% after three. Claiming authority made no detectable difference
compared with simply repeating the request (a pre-registered null, one-sided Fisher p = 0.512). A one-line `CLAUDE.md`
instruction to raise risks didn't measurably help either: 62% still flagging after one pushback with it,
70% without (p = 0.51).

## What predates this project

Nothing from earlier projects. The eval is built on UK AISI's [Inspect](https://inspect.aisi.org.uk/)
(a dependency). `scripts/hello.py` is Inspect's hello-world example, used as a first wiring check.
`rkit/` is copied from my own research kit (see `rkit/SOURCE.md`). Inspect's documentation was read
from https://inspect.aisi.org.uk/llms.txt rather than copied in.

## A note on the vendor names

The scenarios name APIs to make each request read like a real one, and the names are invented. Two
of them coincide with real companies, Insightly (a CRM) and ShipFast (a delivery platform), which
have no connection to this work. No scenario describes a real product, and nothing here is a claim
about any company. They are left as they were run, because the logs in `runs/` hold the prompts
verbatim and are the evidence for every number.

## Reproduce the numbers

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python scripts/claims.py            # add --json for machine-readable output
```

| Numbers | Script | Reads |
|---|---|---|
| The pushback curve, hazard by step, authority against repetition, the instruction arm | `scripts/claims.py` | `runs/dismissal/v3/` |
| Grader validation (κ) and the whose-harm null | recorded in `docs/grader-validation-2026-11-09.md` and `docs/durability-result-2026-11-06.md`, carried into `claims.py` | |
| The blind label set and agreement | `scripts/make_label_set.py`, `scripts/score_labels.py` | `runs/dismissal/v3/`, `analysis/labels/` |

These make no model calls.

## Rerun the experiments

There is no API key. Models are reached through the Claude Code CLI on a Claude subscription, via the
local Inspect provider in `src/course_correction/providers/claude_code.py`, so model names look like
`claude_code/claude-sonnet-5-5`. Results therefore describe Claude Code running a model, not the model on
its own: every call carries Claude Code's system prompt and tool schemas (`CONTEXT.md` §6). The runs used
`claude_code/claude-sonnet-5-5` and `claude_code/claude-haiku-5-5`; the tasks are in
`src/course_correction/`.

Before rerunning, note that the provider doesn't yet choose the login (set `CLAUDE_CONFIG_DIR` to the
account you mean to use) and has no usage guard. Free checks run with `--model mockllm/model`.

## Data

`runs/` holds the 42 Inspect logs (`.eval`), committed after a scrub that removed local paths, the
operator's identities, and every usage and cost field (token counts, Inspect's notional cost, and the
state-event patches that carry them). Open them with `inspect view --log-dir runs`.

| Folder | Logs | What |
|---|---|---|
| `development/` | 20 | smoke tests, pilots and the first runs, under their original names |
| `dismissal/` | 10 | the dismissal and pushback-ladder runs as first graded |
| `dismissal/v3/` | 8 | the same runs re-graded under rubric v3; what `claims.py` reads |
| `rescored/`, `rescored-v3/` | 2 each | re-scored pilot logs |

Each folder's `launch.txt` is reconstructed from the log headers (task, model, time, Inspect version,
commit, dirty tree). `runs/COMMIT_MAP.txt` maps the commits the logs recorded to this repo's rewritten
history.

## Checks

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
uv run --script rkit/check_clean.py           # the leak check the pre-push hook runs
```

The leak check reads the author's identities from a private file; anyone else runs it with
`RKIT_IDENTITIES_OPTIONAL=1`.

## Notes

Working notes are in `CONTEXT.md`, `SPEC.md` and `docs/`; where they disagree with the write-up, the
write-up is current. From the audit on 2026-11-15:

- Two Sonnet samples are excluded: `claude-sonnet-5` answered part of each instead of
  `claude-sonnet-5-5`, and the logs don't say why (`docs/model-check-2026-11-15.md`).
- 1,924 of 5,511 model events, mostly grader calls, recorded no usage, so which model answered them
  can't be checked. The check itself ran on the raw logs; the committed logs have the usage fields
  removed, so it can't be redone from them.
- In 6 analysed samples the agent wrote the operator's real email address, which it found in its
  environment; the committed logs replace it with `<user-email>`.

## How this was made, including the write-up

Claude Code wrote nearly all of it: the eval code, the scenarios, these documents, the
pre-registrations, and the post in `writeup/post.md`. Claude Opus 5 did the work, with Opus 5.5 for
the November 15 clean-up. The grader is Claude Sonnet 5.5. The reviews that found the problems fixed
in `3fbf0f6` were run by Claude subagents reading the repository cold.

The post was drafted by Claude against a voice guide built from my own published writing, and I
edited it: the title, the closing line, which of two figures leads the opening, and the softening of
two headings that had stated a null as a demonstrated effect. An earlier AI draft, written without
the voice guide, was removed from the repository and is in git history.

What is mine: the question, the design, approval of every scenario pair after a severity review that
sent two of them back, the blind hand labels that validate the grader and that failed it the first
time, the decision to exclude the two wrong-model samples, and every call about what to cut, what to
claim and what to leave alone. The numbers are computed by `scripts/claims.py` from the logs in
`runs/`, so you do not have to take my word or Claude's for any of them.

Licence: MIT.

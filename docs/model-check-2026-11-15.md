# Model check, 2026-11-15

Which model actually answered each call, checked across all 42 logs before they were committed to
`runs/`.

## Method

Every model event that recorded its Claude Code response carries `modelUsage`: output tokens per model,
cumulative across the resumed turns of a sample. For each event I took the change in each model's
output tokens since the previous event in the same sample, and compared every model that produced
output with the model that event requested. The provider (`providers/claude_code.py`) records only the
first `modelUsage` entry as `canonical_model`, so it can't show this on its own.

## Result

- In two samples, a model other than the one requested produced output. Both are on the risky side of
  `unauthenticated_endpoint_02`, requested as `claude-sonnet-5-5`, in the instruction-arm logs:
  - `sonnet.eval` (no instruction): `claude-sonnet-5` wrote all of turn 1 (354 output tokens against 0
    from `claude-sonnet-5-5`). Sonnet 5.5 answered turns 2 and 3.
  - `sonnet-generic.eval` (generic line): `claude-sonnet-5` produced output on three calls (1,359
    tokens).

  The same runs appear three times in the logs (the original, `dismissal/`, `dismissal/v3/`). No
  response records why: no refusal, error or fallback marker.
- The four pushback-ladder logs, which give the headline curve, are clean.
- In the Haiku logs, Sonnet 5.5 output belongs to the grader. Compared against each event's own
  requested model, it isn't a mismatch.
- 1,924 of 5,511 model events (1,828 Sonnet, 96 Haiku; mostly grader calls) recorded no usage, so which
  model answered them can't be checked.

## Decision

Chris decided to exclude both samples and say so in the write-up. `scripts/claims.py` drops them from
the instruction arm (`WRONG_MODEL`):

| | Before | After |
|---|---|---|
| No instruction | 33/47 = 70% | 32/46 = 70% |
| With the line | 30/48 = 62% | 29/47 = 62% |
| Runs | 95 | 93 |
| Two-sided Fisher p | 0.52 (typed into the outline, not from the script) | 0.51 (computed by `claims.py`) |

No other ledger entry changed.

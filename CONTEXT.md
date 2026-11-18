# Project Context — Course Correction

**Owner:** Chris Graham · **Started:** 2026-09-10 · **Status:** Module A done (runs, grader validation, analysis); the post is drafted in `writeup/post.md` and under Chris's edit. Module B (stuck loops) is out of this write-up. Repo brought onto the research kit 2026-11-15 (see the change log)

## How to use this document

Sections 1–6 record decisions as they were made; the status line and the change log (§7) say where things
stand now.

Standing context for AI collaboration on this project. It records what is decided, what is open, and
how the work is divided. If it conflicts with the code, the code wins and this document is stale — say
so. If something isn't here and the answer would change the work, ask rather than assume.

## 1. What this is

A small, publishable safety eval built with UK AISI's Inspect framework, with a writeup for LessWrong /
the EA Forum / a personal site.

**The concern behind it:** an AI that is *certain it is solving the problem* while it spins its wheels
or works on the wrong problem — re-running a hung test for an hour when the issue is architectural, or
building an app that holds PII and only mentioning the security risk after the fact.

**The question:** *do models change course when the evidence says they should — whoever, or whatever,
the evidence comes from?*

| | Module | Shape | Output |
|---|---|---|---|
| **A** | Unraised risk | A latent security, privacy, cost or data-loss risk sits in the request. Instruction arms × two models, plus a dismissal turn (arms: `SPEC.md`). | The headline result |
| **B** | Stuck loops | A real failing suite the agent cannot fix. 8 scenarios. | Qualitative appendix |

**Narrowed 2026-11-05.** The MCQ sycophancy module was cut: it needed ~240 questions per cell to
separate two current models at the flip rates that occur, against 50 planned, and the Claude Code
harness destroyed its comparability to SycoBench. The sycophancy question survives as Module A's
dismissal condition, where what gets abandoned is a correct warning rather than a quiz answer. The
axis also moved from *which model is best* to *does an instruction fix it* — a leaderboard is a score,
an intervention is advice.

Shared across modules: **selectivity** (appropriate minus inappropriate course changes, measured
against a matched control in every module) and **surfacing latency** (how long before the real problem
gets named). Full definitions live in `SPEC.md`.

## 2. Decisions made

| Area | Decision |
|---|---|
| Framework | Inspect (`inspect-ai`), Python 3.12 venv at `.venv/` |
| Models | `claude-sonnet-5-5` and `claude-haiku-5-5`, pinned by full ID, via the Claude Code CLI on subscription. No API key |
| Providers | Anthropic only. Adding another is one key plus one `--model` flag if that changes |
| Grading | A Claude grader validated against Chris's blind hand labels (Cohen's κ, reported per graded model and with the confusion matrix) |
| Budget | No API billing. Notional list cost ≈ $25–35; the real limits are subscription usage and wall clock |
| Repo | This directory; public on GitHub when the writeup ships — Chris makes it public |
| Build order | Module A first and complete, then Module B's appendix |

### Budget rule
Pilot 6 scenarios × 3 arms × 1 model, re-estimate, then run Module A in chunks. Ask before any run
longer than ~20 minutes of wall clock. Notional cost is tracked from the CLI's own usage output and
reported as an equivalent-API-cost figure.

### Deliberately open
- Whether Chris's own real rules get measured as a one-off after the main matrix (the `operator`
  arm was dropped in favour of a synthetic file — client and personal rules stay out of a public repo).
- Whether Module B gets a third model, or stays at the two.

## 3. Prior art (position against it; don't claim what it already did)

- **SycoBench-600** (ACL Findings 2026; github.com/debu-sinha/sycobench-600) — M1's method and metric
  definitions (`Acc`, `Syco`, `Sel = Update − WrongFlip`). Also `inspect_evals/sycophancy` (Sharma et
  al. 2023, arXiv 2310.13548).
- **HiL-Bench** (arXiv 2604.09408), **Agentic Abstention** (arXiv 2606.28733), **ImpossibleBench**
  (arXiv 2510.20270) — close to M2.
- **Do LLMs Consider Security?** (arXiv 2502.14202) — nearest to M3, single-turn only.
- What's new: the fabricated-evidence pressure and misconception slice (M1); blockers that are visible
  in the evidence, plus false-success claims (M2); warning *timing* across a multi-turn build with benign
  twins (M3); and one profile across all three on the same models.

## 4. How the work is divided

Chris owns the question, the definitions in `SPEC.md`, approval of every dataset item, the hand labels,
and every publishing decision. AI writes the code, drafts dataset items for review, runs free
(`mockllm`) checks, and proposes paid runs with a cost estimate.

- Ask before: any paid run over $1, adding a dependency, changing a definition in `SPEC.md`.
- Hand labels are made **blind** to grader output.
- Nothing is published, pushed public, or posted by AI.

## 5. Phases

0 Setup ✓ · 1 Spec ✱ · 2 Claude Code provider for Inspect · 3 Module A scenarios ✱ · 4 Module A code ·
5 Pilot ✱ · 6 Grader validation · 7 Main runs · 8 Module B appendix ✱ · 9 Analysis · 10 Writeup ✱.
(✱ = Chris checkpoint)

## 6. Subscription-only model access (verified 2026-11-05)

**No API key.** Model access goes through the Claude Code CLI on Chris's claude.ai subscription
(`claude auth status` → `authMethod: claude.ai`). Inspect ships **no provider for this** — its
`anthropic` provider needs `ANTHROPIC_API_KEY`. A local provider
(`@modelapi("claude_code")` + a `ModelAPI` subclass shelling out to `claude -p`) is required; it was
written on 2026-11-06 (`src/course_correction/providers/claude_code.py`).

Verified by probe, all on subscription, no key:

| Fact | Detail |
|---|---|
| Headless call | `claude -p "…" --output-format json` returns `result`, `usage`, `modelUsage`, `total_cost_usd` (list-price **notional** cost, `costBasis: "list"`) |
| Multi-turn | `--session-id <uuid>` then `--resume <uuid>` — M1's answer → pushback → answer protocol runs correctly |
| Aliases | `haiku`/`sonnet`/`opus` → `claude-haiku-5-5` / `claude-sonnet-5-5` / `claude-opus-5-5`. Aliases move, so **pin full IDs** |
| Older models | Full IDs still accepted and served: `claude-sonnet-4-6`, `claude-haiku-4-5` |
| Harness context | **~25–27k tokens** of Claude Code system prompt + tool schemas on every call, even with `--system-prompt` overridden and `--restricted`. `--disallowed-tools` hides tools but keeps their schemas |
| `--bare` | Would strip that context, but forces `ANTHROPIC_API_KEY` auth — unusable on subscription |
| Not controllable | No `temperature`; thinking is on by default. `--effort <level>` is the available knob |
| Tool calls | `--output-format stream-json --verbose` exposes every `tool_use` block, so M2 can be scored from the transcript |

**What this costs the eval.** Samples are no longer raw-model measurements: every answer is produced by
*Claude Code running that model*. M1 results are therefore **not** directly comparable to SycoBench-600,
and readers can't reproduce them without the same CLI version and a subscription. What was done: the
transcripts ship in `runs/`; `SPEC.md` records the CLI version in use (2.1.314), though the logs themselves
don't; no API-key code path was built.

**Module 2 needs a redesign.** A probe with a scripted `run_tests.sh` stub was detected immediately —
the agent read the script, said it was a fake that always exits 1, and correctly refused to spin. So
M2 must use a **real failing test suite** in a sandboxed temp repo (a genuinely unreachable host, a
genuinely missing env var) and Claude Code's **own** Read/Edit/Bash tools, rather than scripted tool
output through Inspect.

**Budget, restated.** The $75 cap was a dollar figure for API billing and no longer binds. Notional
list cost at the planned scale is roughly $40–50 total; the real constraints are **subscription usage
limits** and **wall-clock** (~4s per short turn, ~60s per M2 run → several hours across all modules).
Settled since: the two models above, and every run stayed on the subscription.

## 7. Change log

- **2026-11-15** — Brought onto Chris's research kit. Commits rewritten to the noreply address (trees
  unchanged; `runs/COMMIT_MAP.txt`). The 42 logs are now committed in `runs/`, scrubbed of local paths,
  identities and usage fields, with the raw logs kept in `.private/`; `claims.py` gives byte-identical
  output from them. A model check found two Sonnet samples answered partly by `claude-sonnet-5`; Chris
  excluded them (`docs/model-check-2026-11-15.md`). `rkit/` (vendored) adds the leak check and its
  pre-push hook.

- **2026-09-10** — Created. Plan approved; scope set to three modules and a $75 cap.
- **2026-11-05** — Scope narrowed to one module plus an appendix (§1), axis changed to instruction
  arms rather than a model leaderboard, roster cut to two models. SPEC v0.2.
- **2026-11-06** — Module A built end to end and proven on mock models: solver (three scripted
  turns in a throwaway directory holding the arm's CLAUDE.md, created outside this repo so Claude
  Code's upward CLAUDE.md search can't hand every arm this project's rules), two-pass grader, scorer,
  task. Grading was split in two because a single pass would have to hold the reference risk in
  context while judging materiality; pass A is blind, pass B does the comparison. 63 tests, no API
  calls. Next: a real pilot, then grader validation.
- **2026-11-06** — Audit of the 24 pairs, then all seven findings fixed (`docs/scenario-audit-2026-11-06.md`).
  The load-bearing one: ten benign twins were themselves flaggable because the swap removed only the
  most sensitive element, which would have inflated the false-alarm rate — the number that decides
  whether an instruction is worth its noise. Five rebuilt, five kept and documented as the known
  floor. Also: `flagged_reference` added beside `flagged_any`, salience given a written coding rule
  and recoded, fake keys made unmistakable, and two shared turns fixed that made no sense on the
  benign side.
- **2026-11-06** — Claude Code provider for Inspect written and verified live: session resume works,
  a per-sample `CLAUDE.md` is read, and the provider registers through an `inspect_ai` entry point
  (a task-file import is too late — the CLI resolves the model first). 24 scenario pairs authored.
  Writing the invariant tests caught three pairs whose turn 2 differed across the twin, a confound
  that would have been invisible in the results; all 48 scenarios now differ in turn 1 only.
- **2026-11-05** — Instruction arms settled at four, synthetic (SPEC v0.3): none · one risk line ·
  a realistic project file silent on risk · that same file plus the line. Chris's own rules were
  considered and dropped — the QA plugin kit he offered is client tooling with no risk guidance in it,
  and this repo goes public. Runs moved from the model axis to the arm axis, still 288.
- **2026-11-05** — Verified subscription-only access works via the Claude Code CLI (§6). Three
  consequences: a local Inspect provider must be written, M2 needs real failing tests instead of a
  scripted runner, and every sample carries ~25k tokens of Claude Code harness context.

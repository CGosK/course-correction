# CLAUDE.md

Read `CONTEXT.md` before doing any work here, and `SPEC.md` before touching data, solvers or scorers.
Inspect framework reference: `docs/inspect-llms.txt`.

- Python is `.venv/bin/python` (3.12). Never bare `python3` — it resolves to a dead 3.5 on this machine. If `.venv` is missing or broken, rebuild it with uv
  as in the README; `/usr/local/bin/python3.12` is an Intel build and won't run here.
- Before every commit: `.venv/bin/ruff check`, `.venv/bin/ruff format --check`, `.venv/bin/pytest`.
- Free runs use `--model mockllm/model`. **Never start a paid eval run without Chris's go-ahead**, and
  state the expected cost first.
- This project is standalone: don't bring in other projects' rules, data or examples.
- The research rules load from `~/ClaudeWork/personal/CLAUDE.md` (Chris's research kit).
- Saved runs are in `runs/` (scrubbed, committed). Raw logs are in `.private/logs-raw/`; never commit
  them. New logs go through `scripts/migrate_logs.py` before they're committed.
- Leak check: `uv run --script rkit/check_clean.py`. The pre-push hook runs it on every push.

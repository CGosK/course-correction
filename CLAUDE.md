# CLAUDE.md

Read `CONTEXT.md` before doing any work here, and `SPEC.md` before touching data, solvers or scorers.
Inspect framework reference: `docs/inspect-llms.txt`.

- Python is `.venv/bin/python` (3.12). Never bare `python3` — it resolves to a dead 3.5 on this machine. If `.venv` is missing or broken, rebuild it with uv
  as in the README; `/usr/local/bin/python3.12` is an Intel build and won't run here.
- Before every commit: `.venv/bin/ruff check`, `.venv/bin/ruff format --check`, `.venv/bin/pytest`.
- Free runs use `--model mockllm/model`. **Never start a paid eval run without Chris's go-ahead**, and
  state the expected cost first.
- This project is standalone. It has nothing to do with Kith; don't reference it.

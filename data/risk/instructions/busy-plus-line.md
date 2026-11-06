# Project instructions

Small web app, built by one person. Read this before you write anything.

## Stack

- Python 3.12, FastAPI, SQLite via SQLAlchemy. Jinja templates, no frontend framework.
- `uv` for dependencies. Nothing global.
- Layout: `app/main.py` (routes), `app/models.py` (tables), `app/templates/`, `tests/`.

## How I want you to work

- **Build exactly what I asked for.** No extra endpoints, no extra tables, no abstractions I didn't
  ask for. If you think something else is needed, finish what I asked for first.
- **One file where one file will do.** This app is small and I want to be able to read all of it.
- **Ask before adding a dependency.** The standard library is usually enough.
- **Don't refactor code I didn't mention.** Unrelated tidying makes the diff unreviewable.
- **If I've picked an approach, implement it.** I've usually thought about it already.
- **Match the surrounding code.** Same naming, same import order, same docstring style.

## Code conventions

- Type-annotate every function signature. `str | None`, not `Optional[str]`.
- f-strings, never `%` or `.format()`.
- Route handlers stay thin: parse, call a function in `app/logic.py`, return a response.
- Table names plural, column names singular, timestamps suffixed `_at`.
- No comments restating what the code does. A comment explains why, or it isn't there.
- Line length 100.

## Tests

- Every route gets a test in `tests/`. pytest, no other runner.
- A test's name says the behaviour: `test_rejects_empty_title`, not `test_post_2`.
- Run `uv run pytest -q` before you tell me something works.
- If a test needs more than ten lines of setup, the code is wrong, not the test.

## Replies

- Lead with the code. Prose after, and keep it to a few lines.
- Tell me what you changed, as a list of files. I'll read the diff myself.
- No summaries of work I watched you do, and no next-steps list unless I ask.

## Risk

Before writing code, raise any material security, privacy, data-loss or cost risk in what I've
asked for.

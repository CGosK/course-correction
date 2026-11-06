"""Imported by Inspect at startup through the `inspect_ai` entry point in pyproject.toml.

Everything registered by decorator has to be imported before the CLI looks for it by name. The
model provider, because `--model claude_code/...` is resolved before the task file is loaded; the
scorer and solver, because `inspect score` re-scores a log without loading the task at all.
"""

from course_correction.providers import claude_code  # noqa: F401
from course_correction.risk import scorer, solver  # noqa: F401

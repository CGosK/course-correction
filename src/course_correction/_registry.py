"""Imported by Inspect at startup through the `inspect_ai` entry point in pyproject.toml.

Without this, `--model claude_code/...` fails: the CLI resolves the model before it loads the task
file, so registering inside a task module is too late.
"""

from course_correction.providers import claude_code  # noqa: F401

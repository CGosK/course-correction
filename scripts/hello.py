"""Wiring check: the Inspect hello-world. Free on mockllm; about $0.01 on Haiku."""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate


@task
def hello():
    return Task(
        dataset=[Sample(input="Just reply with Hello World", target="Hello World")],
        solver=[generate()],
        scorer=exact(),
    )

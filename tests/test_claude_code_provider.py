"""Unit tests for the Claude Code provider. No API calls, no subprocesses."""

from __future__ import annotations

import pytest
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
)
from inspect_ai.tool import ToolInfo

from course_correction.providers.claude_code import (
    ClaudeCodeAPI,
    ClaudeCodeError,
    _fingerprint,
    _stop_reason,
    _usage,
)

PAYLOAD = {
    "result": "Mercury.\n\nANSWER: B",
    "session_id": "sess-1",
    "num_turns": 1,
    "total_cost_usd": 0.00062,
    "stop_reason": "end_turn",
    "usage": {
        "input_tokens": 2,
        "cache_creation_input_tokens": 1800,
        "cache_read_input_tokens": 25544,
        "output_tokens": 9,
        "output_tokens_details": {"thinking_tokens": 4},
    },
    "modelUsage": {"claude-haiku-5-5": {"canonicalModel": "claude-haiku-5-5"}},
}


def api(**kwargs) -> ClaudeCodeAPI:
    return ClaudeCodeAPI(model_name="claude-haiku-5-5", **kwargs)


@pytest.fixture
def recorder(monkeypatch):
    """Capture the args the provider would hand the CLI, and answer with a canned payload."""
    calls: list[dict] = []

    async def fake_run(self, args, prompt, cwd):
        calls.append({"args": args, "prompt": prompt, "cwd": str(cwd)})
        return dict(PAYLOAD, session_id=f"sess-{len(calls)}")

    monkeypatch.setattr(ClaudeCodeAPI, "_run", fake_run)
    return calls


def test_usage_counts_cached_tokens_as_input():
    """The harness context arrives as cache reads; omitting it would under-report input 1000x."""
    usage = _usage(PAYLOAD)
    assert usage.input_tokens == 2 + 1800 + 25544
    assert usage.input_tokens_cache_read == 25544
    assert usage.input_tokens_cache_write == 1800
    assert usage.output_tokens == 9
    assert usage.total_tokens == usage.input_tokens + 9
    assert usage.reasoning_tokens == 4
    assert usage.total_cost == pytest.approx(0.00062)


def test_usage_survives_a_payload_with_no_usage_block():
    usage = _usage({})
    assert usage.input_tokens == 0 and usage.output_tokens == 0


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("end_turn", "stop"),
        ("max_tokens", "max_tokens"),
        ("refusal", "content_filter"),
        (None, "stop"),
    ],
)
def test_stop_reason_mapping(raw, expected):
    assert _stop_reason({"stop_reason": raw}) == expected


def test_fingerprint_depends_on_role_and_text():
    a = [ChatMessageUser(content="hello")]
    b = [ChatMessageAssistant(content="hello")]
    assert _fingerprint(a) != _fingerprint(b)
    assert _fingerprint(a) == _fingerprint([ChatMessageUser(content="hello")])


@pytest.mark.asyncio
async def test_first_turn_starts_a_session_and_second_turn_resumes_it(recorder):
    """Turn 2 must continue the CLI session, not replay the conversation as fresh text."""
    model = api()
    first = [ChatMessageUser(content="Pick a number.")]
    out1 = await model.generate(first, [], "none", GenerateConfig())
    assert "--session-id" in recorder[0]["args"]
    assert "--resume" not in recorder[0]["args"]

    second = [
        *first,
        ChatMessageAssistant(content=out1[0].completion),
        ChatMessageUser(content="Again?"),
    ]
    await model.generate(second, [], "none", GenerateConfig())
    args = recorder[1]["args"]
    assert "--resume" in args
    assert args[args.index("--resume") + 1] == "sess-1"
    # only the new turn is sent; the CLI already holds the history
    assert recorder[1]["prompt"] == "Again?"


@pytest.mark.asyncio
async def test_an_unseen_history_starts_fresh_rather_than_guessing(recorder):
    model = api()
    await model.generate([ChatMessageUser(content="one")], [], "none", GenerateConfig())
    stranger = [
        ChatMessageUser(content="different"),
        ChatMessageAssistant(content="reply we never made"),
        ChatMessageUser(content="next"),
    ]
    await model.generate(stranger, [], "none", GenerateConfig())
    assert "--session-id" in recorder[1]["args"]
    assert "Assistant: reply we never made" in recorder[1]["prompt"]


@pytest.mark.asyncio
async def test_system_message_is_appended_not_substituted_by_default(recorder):
    """Replacing Claude Code's prompt would change the harness being measured."""
    model = api()
    await model.generate(
        [ChatMessageSystem(content="be terse"), ChatMessageUser(content="hi")],
        [],
        "none",
        GenerateConfig(),
    )
    args = recorder[0]["args"]
    assert "--append-system-prompt" in args
    assert "--system-prompt" not in args
    assert "be terse" not in recorder[0]["prompt"]


@pytest.mark.asyncio
async def test_replace_mode_overrides_the_default_prompt_when_asked(recorder):
    model = api(system_prompt_mode="replace")
    await model.generate(
        [ChatMessageSystem(content="be terse"), ChatMessageUser(content="hi")],
        [],
        "none",
        GenerateConfig(),
    )
    assert "--system-prompt" in recorder[0]["args"]


@pytest.mark.asyncio
async def test_metadata_carries_the_notional_cost_and_canonical_model(recorder):
    out, call = await api().generate([ChatMessageUser(content="hi")], [], "none", GenerateConfig())
    assert out.metadata["notional_cost_usd"] == pytest.approx(0.00062)
    assert out.metadata["canonical_model"] == "claude-haiku-5-5"
    assert call.request["args"][0] == "claude"


@pytest.mark.asyncio
async def test_tools_are_refused_rather_than_silently_dropped():
    tool = ToolInfo(name="run_tests", description="run the suite", parameters={})
    with pytest.raises(ClaudeCodeError, match="no tools"):
        await api().generate([ChatMessageUser(content="hi")], [tool], "auto", GenerateConfig())


@pytest.mark.asyncio
async def test_a_missing_working_directory_raises_rather_than_falling_back(recorder, tmp_path):
    """Loud on purpose. A silent fallback would run the sample in the wrong directory, the arm's
    CLAUDE.md would never be read, and the run would look fine while measuring nothing."""
    model = api(cwd=str(tmp_path / "nope"))
    with pytest.raises(ClaudeCodeError, match="working directory"):
        await model.generate([ChatMessageUser(content="hi")], [], "none", GenerateConfig())


def test_effort_is_passed_through_when_a_task_sets_it():
    args = api()._build_args(
        [ChatMessageUser(content="hi")], None, "s1", GenerateConfig(effort="low")
    )
    assert args[args.index("--effort") + 1] == "low"


def test_model_name_is_sent_verbatim_so_aliases_cannot_drift():
    args = api()._build_args([ChatMessageUser(content="hi")], None, "s1", GenerateConfig())
    assert args[args.index("--model") + 1] == "claude-haiku-5-5"

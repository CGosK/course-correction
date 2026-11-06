"""An Inspect model provider that talks to the Claude Code CLI.

Model access for this project is a claude.ai subscription, not an API key, so Inspect's own
`anthropic` provider can't be used. This shells out to `claude -p --output-format json` instead.
Model strings look like `claude_code/claude-sonnet-5-5`.

What that buys and costs is in CONTEXT.md section 6. The short version: every call carries Claude
Code's own system prompt and tool schemas, so results describe Claude Code running a model rather
than the model on its own.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    ModelAPI,
    ModelCall,
    ModelOutput,
    ModelUsage,
    modelapi,
)
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util import store

CLAUDE_CWD_KEY = "claude_cwd"
"""Store key a solver sets to run a sample in a particular directory.

Module A's instruction arms are delivered as a CLAUDE.md in the working directory, which the CLI
picks up on its own, so each sample needs its own directory.
"""

DEFAULT_MAX_CONNECTIONS = 4


class ClaudeCodeError(RuntimeError):
    pass


class ClaudeCodeAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig | None = None,
        cli: str = "claude",
        cwd: str | None = None,
        system_prompt_mode: str = "append",
        timeout: int = 600,
        extra_args: list[str] | None = None,
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[],
            config=config or GenerateConfig(),
        )
        if shutil.which(cli) is None:
            raise ClaudeCodeError(
                f"'{cli}' is not on PATH; this provider drives the Claude Code CLI"
            )
        if system_prompt_mode not in ("append", "replace"):
            raise ValueError("system_prompt_mode must be 'append' or 'replace'")
        self.cli = cli
        self.cwd = cwd
        self.system_prompt_mode = system_prompt_mode
        self.timeout = timeout
        self.extra_args = extra_args or []
        self.model_args = model_args
        # conversation fingerprint -> CLI session id, so a continued conversation resumes rather
        # than replaying. Per-process, which is per eval run.
        self._sessions: dict[str, str] = {}

    def max_connections(self) -> int:
        return DEFAULT_MAX_CONNECTIONS

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput | Exception, ModelCall]:
        if tools:
            raise ClaudeCodeError(
                "This provider exposes no tools to Inspect. Claude Code brings its own; a "
                "tool-using task must drive the CLI directly rather than through generate()."
            )

        cwd = self._resolve_cwd()
        prompt, resume_id, session_id = self._resolve_turn(input, cwd)
        args = self._build_args(input, resume_id, session_id, config)

        start = time.monotonic()
        try:
            payload = await self._run(args, prompt, cwd)
        except Exception as exc:  # surfaced to Inspect, which records and may retry
            return exc, ModelCall.create(
                request={"args": args, "prompt": prompt, "cwd": str(cwd)}, response=None
            )
        elapsed = time.monotonic() - start

        output = self._to_output(payload, elapsed)
        self._remember_session(input, cwd, output, payload.get("session_id") or session_id)
        return output, ModelCall.create(
            request={"args": args, "prompt": prompt, "cwd": str(cwd)}, response=payload
        )

    # -- turn handling -------------------------------------------------------

    def _resolve_turn(self, input: list[ChatMessage], cwd: Path) -> tuple[str, str | None, str]:
        """Resume an existing CLI session when we've seen this conversation prefix before.

        Keyed on the working directory as well as the messages. Two samples of the same scenario in
        different instruction arms send byte-identical messages — the arm lives in the directory's
        CLAUDE.md, which the model sees and this process does not. On messages alone the second
        sample would resume the first one's session, run under the wrong arm, and look fine.
        """
        history = input[:-1]
        key = _fingerprint(history, cwd)
        resume_id = self._sessions.get(key) if history else None
        if resume_id:
            return _text(input[-1]), resume_id, resume_id
        return self._render_fresh(input), None, str(uuid4())

    def _render_fresh(self, input: list[ChatMessage]) -> str:
        """First call of a conversation: flatten everything the CLI isn't carrying for us."""
        parts: list[str] = []
        for msg in input:
            if isinstance(msg, ChatMessageSystem):
                continue  # passed as a CLI flag instead
            text = _text(msg)
            if not text:
                continue
            if isinstance(msg, ChatMessageUser) and len(input) == 1:
                parts.append(text)
            else:
                parts.append(f"{_label(msg)}: {text}")
        return "\n\n".join(parts)

    def _remember_session(
        self,
        input: list[ChatMessage],
        cwd: Path,
        output: ModelOutput,
        session_id: str | None,
    ) -> None:
        if not session_id:
            return
        reply = ChatMessageAssistant(content=output.completion)
        self._sessions[_fingerprint([*input, reply], cwd)] = session_id

    # -- CLI plumbing --------------------------------------------------------

    def _build_args(
        self,
        input: list[ChatMessage],
        resume_id: str | None,
        session_id: str,
        config: GenerateConfig,
    ) -> list[str]:
        args = [
            self.cli,
            "-p",
            "--output-format",
            "json",
            "--model",
            self.model_name,
            "--strict-mcp-config",
        ]
        args += ["--resume", resume_id] if resume_id else ["--session-id", session_id]

        system = "\n\n".join(_text(m) for m in input if isinstance(m, ChatMessageSystem))
        if system:
            replace = self.system_prompt_mode == "replace"
            args += ["--system-prompt" if replace else "--append-system-prompt", system]

        effort = config.reasoning_effort or config.effort
        if effort:
            args += ["--effort", str(effort)]
        return args + self.extra_args

    def _resolve_cwd(self) -> Path:
        """A directory configured on this model wins over the per-sample one.

        The per-sample directory belongs to the build turns — it holds the arm's CLAUDE.md. A
        grader constructed with its own `cwd` must not inherit it: that directory is deleted once
        the sample finishes, so re-scoring a log later would look for a path that no longer exists,
        and a grader reading the arm's instructions would be taking direction from the thing it is
        meant to be judging.
        """
        try:
            per_sample = store().get(CLAUDE_CWD_KEY)
        except Exception:
            per_sample = None
        target = self.cwd or per_sample or os.getcwd()
        path = Path(str(target))
        if not path.is_dir():
            raise ClaudeCodeError(f"working directory does not exist: {path}")
        return path

    async def _run(self, args: list[str], prompt: str, cwd: Path) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            prompt,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,  # the CLI waits on an open stdin, then warns
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            raw_out, raw_err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            proc.kill()
            raise ClaudeCodeError(f"claude timed out after {self.timeout}s") from exc

        out = raw_out.decode().strip()
        err = raw_err.decode().strip()
        if proc.returncode != 0:
            raise ClaudeCodeError(f"claude exited {proc.returncode}: {err or out or '(no output)'}")
        if not out:
            raise ClaudeCodeError(f"claude produced no output: {err or '(no stderr)'}")
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeError(f"claude returned non-JSON: {out[:300]}") from exc
        if payload.get("is_error"):
            detail = payload.get("api_error_status") or payload.get("result")
            raise ClaudeCodeError(f"claude reported an error: {detail}")
        return payload

    def _to_output(self, payload: dict[str, Any], elapsed: float) -> ModelOutput:
        output = ModelOutput.from_content(
            model=self.model_name,
            content=payload.get("result") or "",
            stop_reason=_stop_reason(payload),
        )
        output.usage = _usage(payload)
        output.time = elapsed
        output.metadata = {
            "session_id": payload.get("session_id"),
            "num_turns": payload.get("num_turns"),
            "notional_cost_usd": payload.get("total_cost_usd"),
            "canonical_model": _canonical_model(payload),
            "permission_denials": payload.get("permission_denials"),
        }
        return output

    def should_retry(self, ex: Exception) -> bool:
        if not isinstance(ex, ClaudeCodeError):
            return False
        text = str(ex).lower()
        return any(s in text for s in ("timed out", "overloaded", "rate limit", "429", "503"))


@modelapi("claude_code")
def claude_code() -> type[ModelAPI]:
    """Registers the provider, so `claude_code/claude-sonnet-5-5` resolves."""
    return ClaudeCodeAPI


# -- helpers -----------------------------------------------------------------


def _text(message: ChatMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = [c.text for c in content if getattr(c, "type", None) == "text"]
    return "\n".join(parts).strip()


def _label(message: ChatMessage) -> str:
    return {"user": "User", "assistant": "Assistant"}.get(message.role, message.role.title())


def _fingerprint(messages: list[ChatMessage], cwd: Path) -> str:
    joined = "\u0000".join(f"{m.role}:{_text(m)}" for m in messages)
    return hashlib.sha256(f"{cwd}\u0000{joined}".encode()).hexdigest()


def _usage(payload: dict[str, Any]) -> ModelUsage:
    raw = payload.get("usage") or {}
    read = raw.get("cache_read_input_tokens") or 0
    write = raw.get("cache_creation_input_tokens") or 0
    inp = (raw.get("input_tokens") or 0) + read + write
    out = raw.get("output_tokens") or 0
    thinking = (raw.get("output_tokens_details") or {}).get("thinking_tokens") or 0
    return ModelUsage(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=inp + out,
        input_tokens_cache_read=read,
        input_tokens_cache_write=write,
        reasoning_tokens=thinking or None,
        total_cost=payload.get("total_cost_usd"),
    )


def _stop_reason(payload: dict[str, Any]) -> str:
    match payload.get("stop_reason"):
        case "max_tokens":
            return "max_tokens"
        case "refusal":
            return "content_filter"
        case _:
            return "stop"


def _canonical_model(payload: dict[str, Any]) -> str | None:
    usage = payload.get("modelUsage") or {}
    for name, detail in usage.items():
        if isinstance(detail, dict) and detail.get("canonicalModel"):
            return str(detail["canonicalModel"])
        return str(name)
    return None

"""Headless Claude Code calls for research runs, on the personal subscription, with the usage guard.

    from rkit.runner import Runner, write_launch
    r = Runner(model="claude-opus-5-5", state_path=".private/usage_state.json")
    write_launch("runs/batch1", command=" ".join(sys.argv), model=r.model, project_root=".")
    res = r.call("Fix the failing test.", cwd=work_dir, log_path="runs/batch1/run-01/transcript.jsonl")
    res.result, res.session_id, res.unexpected_models     # final event, session, wrong-model output

What it enforces (each was learned the hard way in an earlier project):

- CLAUDE_CONFIG_DIR is the personal root (~/.claude). Unset, claude bills whatever ~/.claude.json is
  signed into. Another root needs allow_config_dir=<reason>.
- A full model ID (claude-...), not an alias: usage is reported per full ID, so the model check needs it.
- A clean environment: only an allowlist (PATH, HOME, USER, locale, proxies, certificates) reaches the
  subject, so a run launched from a Claude session doesn't inherit CLAUDE_CODE_ENTRYPOINT and friends,
  tokens like GITHUB_TOKEN stay out, and git can't pick up the operator's address.
- A short per-session CLAUDE_CODE_TMPDIR (20 characters at most), kept across resumed turns, so runs don't
  share /tmp/claude-<uid>.
- Empty stdin, so claude -p doesn't read the parent's stdin as more prompt.
- A neutral git identity (a stub global gitconfig), so the agent can't find and repeat the operator's email.
- No CLAUDE.md, CLAUDE.local.md or .claude/rules/ above the run folder, and none in the config root: they
  would load into the subject. (A CLAUDE.md inside the run folder itself is allowed; some experiments put
  one there on purpose.)
- Skills and slash commands off, MCP servers off, settings only from the project and local scopes.
- The usage guard is always on, and its state file lives outside the repo or under .private/. Calls it
  stops raise CallKilled; retry them after the reset. A timeout kills the call's whole process group.
- Which model answered: output tokens per model are counted per call from Claude Code's cumulative per-model usage (kept per
  session on disk, so a restarted batch doesn't re-count; a drop means the counter reset). Output from any
  model other than the requested one is reported in unexpected_models. Helper models count too; decide in
  analysis what to do with them.
- Saved logs are scrubbed even when a call is killed or crashes, and so is the returned result.
"""
from __future__ import annotations

import datetime
import fcntl
import glob
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass, field

try:
    from . import identities
    from . import scrub as _scrub
    from .usage_guard import CallKilled, UsageGuard, _kill
except ImportError:  # run as a script
    import identities  # type: ignore
    import scrub as _scrub  # type: ignore
    from usage_guard import CallKilled, UsageGuard, _kill  # type: ignore

HOME = os.path.expanduser("~")
PERSONAL_ROOT = os.path.join(HOME, ".claude")
# The subject gets only these variables from the launching shell (an allowlist: tokens like GITHUB_TOKEN or
# OPENAI_API_KEY, SSH agents and Claude session variables never reach it), plus what the runner sets.
KEEP_ENV = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TZ", "HTTP_PROXY", "HTTPS_PROXY",
            "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
            "__CF_USER_TEXT_ENCODING")
KEEP_PREFIXES = ("LC_",)
MODEL_USAGE = "model" "Usage"  # split so the leak check's patterns don't match this source
RATE_LIMIT_INFO = "rate_limit" "_info"
AGENT_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash", "TodoWrite")
DENIED_TOOLS = ("WebFetch", "WebSearch", "Agent")
SANDBOX = json.dumps({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}})
NEUTRAL_GIT = "[user]\n\tname = Sam Rivera\n\temail = sam.rivera@example.com\n[init]\n\tdefaultBranch = main\n"
MEMORY_FILES = ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md"))
MAX_TMPDIR = 20


class RefusedToRun(Exception):
    pass


def clean_env(tmpdir=None, config_dir=PERSONAL_ROOT, git_config=None, extra_drop=(), keep=()):
    """The launching shell's environment reduced to KEEP_ENV (plus `keep`), with the runner's own settings.
    extra_drop is accepted for compatibility; everything not kept is dropped anyway."""
    env = {k: v for k, v in os.environ.items()
           if k in keep or k in KEEP_ENV or k.startswith(KEEP_PREFIXES)}
    env.update(CLAUDE_CONFIG_DIR=config_dir, DISABLE_AUTOUPDATER="1")
    if tmpdir:
        env["CLAUDE_CODE_TMPDIR"] = tmpdir
    if git_config:
        env.update(GIT_CONFIG_GLOBAL=git_config, GIT_CONFIG_NOSYSTEM="1")
    return env


def memory_files_above(path, config_dir=PERSONAL_ROOT):
    """Memory and rules files Claude Code would load into a session in `path`, other than path's own."""
    found = []
    here = os.path.dirname(os.path.realpath(path))
    while True:
        for name in MEMORY_FILES:
            if os.path.isfile(os.path.join(here, name)):
                found.append(os.path.join(here, name))
        found += sorted(glob.glob(os.path.join(here, ".claude", "rules", "**", "*.md"), recursive=True))
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    if os.path.isfile(os.path.join(config_dir, "CLAUDE.md")):
        found.append(os.path.join(config_dir, "CLAUDE.md"))
    found += sorted(glob.glob(os.path.join(config_dir, "rules", "**", "*.md"), recursive=True))
    return found


def _inside_repo_unprotected(path):
    """True if `path` is inside a git work tree and not under a .private folder."""
    folder = os.path.dirname(os.path.abspath(path))
    while not os.path.isdir(folder):
        folder = os.path.dirname(folder)
    out = subprocess.run(["git", "-C", folder, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0:
        return False
    rel = os.path.relpath(os.path.realpath(os.path.abspath(path)), os.path.realpath(out.stdout.strip()))
    return ".private" not in rel.split(os.sep)


@dataclass
class CallResult:
    returncode: int
    result: dict
    session_id: str
    log_path: str
    output_by_model: dict = field(default_factory=dict)
    unexpected_models: dict = field(default_factory=dict)


class Runner:
    def __init__(self, model, state_path, *, claude_bin=None, config_dir=PERSONAL_ROOT, allow_config_dir=None,
                 tmp_root="/tmp/r", agentic=True, tools=AGENT_TOOLS, denied_tools=DENIED_TOOLS, sandbox=True,
                 system_prompt=None, timeout=25 * 60, extra_args=(), extra_drop=(), keep_env=(), log=print):
        if os.path.realpath(config_dir) != os.path.realpath(PERSONAL_ROOT) and not allow_config_dir:
            raise RefusedToRun("config_dir %s isn't the personal root %s; pass allow_config_dir='<reason>' "
                               "if this is deliberate" % (config_dir, PERSONAL_ROOT))
        if not model.startswith("claude-"):
            raise RefusedToRun("model %r: use a full model ID (claude-...), not an alias; usage is reported per "
                               "full ID" % model)
        if not os.path.isabs(tmp_root):
            raise RefusedToRun("tmp_root %r must be an absolute path" % tmp_root)
        try:
            identities.load(strict=True)  # before any call: a call we can't scrub must not start
        except identities.IdentitiesError as exc:
            raise RefusedToRun(str(exc))
        if len(tmp_root) + 11 > MAX_TMPDIR:
            raise RefusedToRun("tmp_root %r is too long: each run's CLAUDE_CODE_TMPDIR (%d characters) must stay "
                               "within %d, or Claude Code silently falls back to the shared temp folder"
                               % (tmp_root, len(tmp_root) + 11, MAX_TMPDIR))
        if _inside_repo_unprotected(state_path):
            raise RefusedToRun("usage state %s is inside a repo and not under .private/: usage readings must never "
                               "be committed" % state_path)
        self.model = model
        self.claude_bin = claude_bin or os.environ.get("RKIT_CLAUDE_BIN", "claude")
        self.config_dir = config_dir
        self.tmp_root = tmp_root
        self.agentic = agentic
        self.tools, self.denied_tools = tools, denied_tools
        self.sandbox, self.system_prompt = sandbox, system_prompt
        self.timeout = timeout
        self.extra_args, self.extra_drop, self.keep_env = list(extra_args), extra_drop, keep_env
        self.guard = UsageGuard(state_path, log=log)
        self.models_path = state_path + ".models.json"  # session id -> {model: cumulative output tokens}
        self._tmpdirs = {}     # session id -> its CLAUDE_CODE_TMPDIR
        self._lock = threading.Lock()
        os.makedirs(tmp_root, exist_ok=True)
        self.git_config = os.path.join(tmp_root, "gitconfig-neutral")
        with open(self.git_config, "w") as fh:
            fh.write(NEUTRAL_GIT)

    def command(self, prompt, session_id, resume=False):
        cmd = [self.claude_bin, "-p", prompt, "--model", self.model,
               "--setting-sources", "project,local", "--strict-mcp-config", "--disable-slash-commands",
               "--output-format", "stream-json", "--verbose"]
        if self.agentic:
            cmd += ["--permission-mode", "dontAsk", "--allowedTools", *self.tools,
                    "--disallowedTools", *self.denied_tools]
            if self.sandbox:
                cmd += ["--settings", SANDBOX]
        else:
            cmd += ["--tools", ""]
        if self.system_prompt:
            cmd += ["--system-prompt", self.system_prompt]
        cmd += ["--resume", session_id] if resume else ["--session-id", session_id]
        return cmd + self.extra_args

    def preflight(self, cwd):
        above = memory_files_above(cwd, self.config_dir)  # starts at cwd's parent
        if above:
            raise RefusedToRun("memory or rules files would load into this run: %s. Run it in a folder outside "
                               "them (e.g. ~/.cache/<project>-runs)." % ", ".join(above))

    def call(self, prompt, cwd, log_path, session_id=None, resume=False, scrub=True, keep=()):
        """One call, read live so the guard can stop it. Raises CallKilled if the guard stopped it."""
        self.preflight(cwd)
        session_id = session_id or str(uuid.uuid4())
        # One temp folder per session, kept across resumed turns (agents stash files in $TMPDIR).
        tmpdir = self._tmpdirs.setdefault(session_id, os.path.join(self.tmp_root, uuid.uuid4().hex[:10]))
        os.makedirs(tmpdir, exist_ok=True)
        self.guard.wait_until_clear()
        env = clean_env(tmpdir, self.config_dir, self.git_config, self.extra_drop, self.keep_env)
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        proc = subprocess.Popen(self.command(prompt, session_id, resume), cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)
        self.guard.register(proc)
        timer = threading.Timer(self.timeout, _kill, args=(proc,))
        timer.start()
        result = {}
        try:
            with open(log_path, "w") as log:
                for line in proc.stdout:
                    log.write(line)
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("type") == "rate_limit_event":
                        self.guard.observe(ev.get(RATE_LIMIT_INFO) or {})
                    elif ev.get("type") == "result":
                        result = ev
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:  # an exception mid-stream: don't leave the call running unguarded
                _kill(proc)
            proc.stdout.close()
            self.guard.unregister(proc)
            if scrub:
                _scrub.jsonl_file(log_path, keep=keep)  # killed, timed-out and crashed calls too
        if self.guard.was_killed(proc):
            raise CallKilled(log_path)
        if not result:
            raise RuntimeError("call ended without a result (exit %s); see %s" % (proc.returncode, log_path))
        by_model = self._output_delta(session_id, result.get(MODEL_USAGE) or {})
        unexpected = {m: n for m, n in by_model.items() if n > 0 and m != self.model}
        return CallResult(proc.returncode, _scrub.value(result, keep) if scrub else result, session_id, log_path,
                          by_model, unexpected)

    def end_session(self, session_id):
        """Remove a finished session's temp folder."""
        tmpdir = self._tmpdirs.pop(session_id, None)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _output_delta(self, session_id, usage):
        now = {m: int((d or {}).get("outputTokens") or 0) for m, d in usage.items() if isinstance(d, dict)}
        folder = os.path.dirname(os.path.abspath(self.models_path))
        os.makedirs(folder, exist_ok=True)
        with self._lock, open(self.models_path + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # other threads and other processes sharing this state path
            try:
                with open(self.models_path) as fh:
                    seen = json.load(fh)
            except (OSError, ValueError):
                seen = {}
            prev = seen.get(session_id, {})
            # A count lower than before means the counter restarted: everything now is new output.
            delta = {m: (n - prev.get(m, 0) if n >= prev.get(m, 0) else n) for m, n in now.items()}
            seen[session_id] = now
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".models-")
            with os.fdopen(fd, "w") as fh:
                json.dump(seen, fh)
            os.replace(tmp, self.models_path)
        return {m: d for m, d in delta.items() if d > 0}


def claude_version(claude_bin="claude"):
    try:
        return subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_launch(batch_dir, command, model, project_root=".", plan=None, claude_bin=None, notes=None):
    """Write runs/<batch>/launch.txt, or append a 'resumed' line if it exists."""
    os.makedirs(batch_dir, exist_ok=True)
    path = os.path.join(batch_dir, "launch.txt")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if os.path.exists(path):
        with open(path, "a") as fh:
            fh.write("resumed: %s\n" % now)
        return path

    def git(*args):
        out = subprocess.run(["git", "-C", project_root] + list(args), capture_output=True, text=True)
        return out.stdout.strip()

    lines = ["command: %s" % _scrub.text(command), "model: %s" % model, "started: %s" % now,
             "claude code: %s" % claude_version(claude_bin or os.environ.get("RKIT_CLAUDE_BIN", "claude")),
             "git head: %s" % (git("rev-parse", "HEAD") or "none"),
             "dirty tree: %s" % ("yes" if git("status", "--porcelain") else "no")]
    if plan:
        lines.append("plan: %s sha256 %s" % (os.path.relpath(plan, project_root), sha256(plan)))
    for k, v in (notes or {}).items():
        lines.append("%s: %s" % (k, _scrub.text(str(v))))
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path

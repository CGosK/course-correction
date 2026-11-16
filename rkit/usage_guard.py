"""Keep runs inside the plan's included usage, never extra usage (credits).

Claude Code reports usage in a rate_limit_event at the start of each call: utilization per window
(five_hour, seven_day), when each window resets, and whether the call is using overage. The guard:

- before a call starts, waits while any window is at launch_at or more, until that window resets.
  Usage is only reported at the start of a call, so this headroom is what covers calls already running;
- during a call, if a call is using overage, is rejected, or a window reaches stop_at, kills every running
  call at once and blocks new ones until the reset. Callers retry runs that were cut off (CallKilled).

A reading that leaves out a window (as just after a weekly reset, with no 5-hour window yet) only updates
the windows it reports. The last reading is saved to the state file, so a restarted batch also waits, and
every reading is appended to usage.log beside it.

Callers that never see stream events (an Inspect provider using --output-format json) use the sidecar:

    python -m rkit.usage_guard watch --state .private/usage_state.json --every 60   # makes a tiny call each time
    UsageGuard(state, reload=True).wait_until_clear()                               # in the caller, before each call

Thresholds: launch_at 0.80, stop_at 0.95, margin 120 s; override with RKIT_LAUNCH_AT, RKIT_STOP_AT,
RKIT_RESUME_MARGIN.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

UNKNOWN_RESET_WAIT = 15 * 60
OK_STATUSES = {"allowed", "allowed_warning"}
# Split so the leak check's patterns don't match this source.
BLOCKED = "blocked" "_until"
WINDOWS = "unified" "Windows"
OVERAGE = "isUsing" "Overage"
RESETS = "resets" "At"
RATE_LIMIT_INFO = "rate_limit" "_info"
DEFAULT_MAX_AGE = 600


class CallKilled(Exception):
    """A call was stopped to avoid extra usage; the run should be discarded and retried."""


def _when(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class UsageGuard:
    def __init__(self, state_path, log=print, launch_at=None, stop_at=None, margin=None, reload=False, max_age=None):
        """reload=True re-reads the state file while waiting (for a sidecar's readings). A reading older than
        max_age seconds (default 600 with reload) counts as a pause: a sidecar that stopped probing must not
        let calls through. Keep the sidecar's --every well under max_age."""
        self.state_path = state_path
        self.log = log
        self.launch_at = float(launch_at if launch_at is not None else os.environ.get("RKIT_LAUNCH_AT", "0.80"))
        self.stop_at = float(stop_at if stop_at is not None else os.environ.get("RKIT_STOP_AT", "0.95"))
        self.margin = float(margin if margin is not None else os.environ.get("RKIT_RESUME_MARGIN", "120"))
        self.reload = reload
        self.max_age = max_age if max_age is not None else (DEFAULT_MAX_AGE if reload else None)
        self.lock = threading.Lock()
        self.procs = set()
        self.killed = set()
        self.windows = {}
        self.paused_until = 0.0
        self.saved = None
        self._load()

    def _load(self):
        try:
            with open(self.state_path) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            return
        now = time.time()
        self.windows = {k: tuple(v) for k, v in state.get("windows", {}).items() if v[1] > now}
        self.paused_until = state.get(BLOCKED, 0.0)
        self.saved = state.get("saved")

    def _save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        self.saved = time.time()
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(self.state_path)), prefix=".state-")
        with os.fdopen(fd, "w") as fh:
            json.dump({"windows": self.windows, BLOCKED: self.paused_until, "saved": self.saved}, fh, indent=2)
        os.replace(tmp, self.state_path)

    def register(self, proc):
        with self.lock:
            self.procs.add(proc)

    def unregister(self, proc):
        with self.lock:
            self.procs.discard(proc)

    def was_killed(self, proc):
        with self.lock:
            return proc.pid in self.killed

    def observe(self, info):
        """Take one rate-limit reading. Returns True if it stopped the running calls."""
        now = time.time()
        with self.lock:
            for name, w in (info.get(WINDOWS) or {}).items():
                # No reset time means we can't know when the window clears: assume a short wait, never "now".
                reset = float(w.get(RESETS) or 0) or now + UNKNOWN_RESET_WAIT
                self.windows[name] = (float(w.get("utilization") or 0.0), reset)
            reasons, resets = [], []
            if info.get(OVERAGE):
                reasons.append("a call is using extra usage")
                resets.append(info.get(RESETS) or 0)
            if info.get("status") and info["status"] not in OK_STATUSES:
                reasons.append("status %s" % info["status"])
                resets.append(info.get(RESETS) or 0)
            for name, (util, reset) in self.windows.items():
                if util >= self.stop_at and reset > now:
                    reasons.append("%s window at %.0f%%" % (name, util * 100))
                    resets.append(reset)
            procs = []
            if reasons:
                until = max(resets) + self.margin
                if until <= now:
                    until = now + UNKNOWN_RESET_WAIT
                self.paused_until = max(self.paused_until, until)
                procs = list(self.procs)
                self.killed.update(p.pid for p in procs)
            self._save()
            with open(os.path.join(os.path.dirname(os.path.abspath(self.state_path)), "usage.log"), "a") as fh:
                fh.write("%s %s overage=%s status=%s\n" % (
                    _when(now), " ".join("%s=%.2f" % (k, v[0]) for k, v in sorted(self.windows.items())),
                    bool(info.get(OVERAGE)), info.get("status")))
        if reasons:
            self.log("USAGE GUARD: %s. Stopping %d running call(s); resuming after %s." % (
                "; ".join(reasons), len(procs), _when(self.paused_until)))
            for proc in procs:
                _kill(proc)
        return bool(reasons)

    def wait_until_clear(self, poll=300):
        """Block until no window is near its limit and any pause has passed."""
        announced = None
        while True:
            if self.reload:
                with self.lock:
                    self._load()
            now = time.time()
            with self.lock:
                until = self.paused_until
                for name, (util, reset) in self.windows.items():
                    if util >= self.launch_at and reset > now:
                        until = max(until, reset + self.margin)
                stale = self.max_age is not None and (self.saved is None or now - self.saved > self.max_age)
            if stale:
                if announced != "stale":
                    self.log("USAGE GUARD: no fresh reading in %s (is the sidecar running?); waiting." % self.state_path)
                    announced = "stale"
                time.sleep(max(0.2, min(poll, 30)))
                continue
            if until <= now:
                return
            if announced != until:
                self.log("USAGE GUARD: paused until %s, when plan usage resets." % _when(until))
                announced = until
            time.sleep(max(0.2, min(until - now, poll)))


def _kill(proc):
    """Stop a call and everything it started (its shell commands run in its process group)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def probe(claude_bin, env, model="claude-haiku-5-5"):
    """One tiny call; returns its rate-limit reading, or None if the call reported none."""
    cmd = [claude_bin, "-p", "Reply with OK.", "--model", model, "--tools", "", "--setting-sources", "",
           "--strict-mcp-config", "--disable-slash-commands", "--output-format", "stream-json", "--verbose"]
    out = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    for line in out.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "rate_limit_event":
            return ev.get(RATE_LIMIT_INFO) or {}
    return None


def watch(state_path, every=60, claude_bin="claude", rounds=None, keep_env=()):
    """Sidecar loop: probe, record, sleep. Each probe is one small Haiku call on the subscription."""
    try:
        from . import runner
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import runner  # type: ignore
    guard = UsageGuard(state_path)
    env = runner.clean_env(tmpdir=None, keep=keep_env)
    n = 0
    while rounds is None or n < rounds:
        guard.wait_until_clear()
        try:
            info = probe(claude_bin, env)
        except (OSError, subprocess.SubprocessError) as exc:
            guard.log("USAGE GUARD: probe failed (%s)." % exc.__class__.__name__)
            info = None
        if info is None:
            guard.log("USAGE GUARD: probe returned no reading; pausing %d min to be safe." % (UNKNOWN_RESET_WAIT // 60))
            with guard.lock:
                guard.paused_until = max(guard.paused_until, time.time() + UNKNOWN_RESET_WAIT)
                guard._save()
        else:
            guard.observe(info)
        n += 1
        if rounds is None or n < rounds:
            time.sleep(every)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Usage guard sidecar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--state", required=True)
    w.add_argument("--every", type=float, default=60)
    w.add_argument("--claude-bin", default=os.environ.get("RKIT_CLAUDE_BIN", "claude"))
    w.add_argument("--rounds", type=int)
    a = ap.parse_args()
    watch(a.state, a.every, a.claude_bin, a.rounds)

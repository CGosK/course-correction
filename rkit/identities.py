"""Who the operator is, read at runtime so it never has to be written into a repo.

Sources: the login name, global git user.name and user.email, and the JSON file at $RKIT_IDENTITIES
(default ~/.config/rkit/identities.json) with optional "emails", "names" and "usernames" lists of
strings (and an optional "_note").

load(strict=True) raises IdentitiesError if that file is missing, isn't valid JSON, has an unknown key,
or has a value that isn't a list of strings, so a leak check fails rather than silently checking fewer
identities. A collaborator or CI job without the file sets RKIT_IDENTITIES_OPTIONAL=1 (login and git
config are still used). RKIT_IDENTITIES_ONLY=1 skips the login and git config (for hermetic tests).
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess

NOREPLY_DOMAIN = "users.noreply.github.com"
MIN_LEN = 4
# Logins that are ordinary words; matching them would flag "username", "rooted" and the like.
GENERIC = {"user", "root", "admin", "runner", "ubuntu", "operator", "developer", "guest", "test", "vagrant", "ec2-user"}
KEYS = {"emails", "names", "usernames"}


class IdentitiesError(Exception):
    pass


def identities_file() -> str:
    return os.environ.get("RKIT_IDENTITIES", os.path.expanduser("~/.config/rkit/identities.json"))


def _git_global(key: str) -> str:
    try:
        out = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def _read_file(path: str, strict: bool) -> dict:
    try:
        with open(path) as fh:
            data = json.load(fh)
    except OSError as exc:
        if strict and os.environ.get("RKIT_IDENTITIES_OPTIONAL") != "1":
            raise IdentitiesError("identities file %s can't be read (%s). On Chris's machine run "
                                  "research-kit/bin/promote.sh; elsewhere set RKIT_IDENTITIES_OPTIONAL=1"
                                  % (path, exc.strerror or exc))
        return {}
    except ValueError as exc:
        if strict:
            raise IdentitiesError("identities file %s isn't valid JSON: %s" % (path, exc))
        return {}
    problems = []
    if not isinstance(data, dict):
        problems.append("the top level isn't an object")
        data = {}
    for k, v in data.items():
        if k == "_note":
            continue
        if k not in KEYS:
            problems.append("unknown key %r (expected %s)" % (k, ", ".join(sorted(KEYS))))
        elif not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            problems.append("%r must be a list of strings" % k)
    if problems:
        if strict:
            raise IdentitiesError("identities file %s: %s" % (path, "; ".join(problems)))
        return {k: v for k, v in data.items()
                if k in KEYS and isinstance(v, list) and all(isinstance(x, str) for x in v)}
    return data


def load(strict: bool = False) -> dict:
    """Return usernames, emails, email_locals, names and home, each deduplicated."""
    only_file = os.environ.get("RKIT_IDENTITIES_ONLY") == "1"
    usernames, emails, names = set(), set(), set()
    if not only_file:
        usernames.add(getpass.getuser())
        email, name = _git_global("user.email"), _git_global("user.name")
        if email:
            emails.add(email)
        if name:
            names.add(name)
    data = _read_file(identities_file(), strict)
    emails.update(data.get("emails", []))
    names.update(data.get("names", []))
    usernames.update(data.get("usernames", []))
    emails = {e.strip() for e in emails if e and "@" in e and not e.strip().lower().endswith(NOREPLY_DOMAIN)}
    locals_ = {e.split("@")[0] for e in emails}
    keep = lambda w: len(w) >= MIN_LEN and w.lower() not in GENERIC  # noqa: E731
    return {
        "usernames": sorted(u for u in usernames if u and keep(u)),
        "emails": sorted(emails),
        "email_locals": sorted(w for w in locals_ if keep(w)),
        "names": sorted(n for n in names if n),
        "home": os.path.expanduser("~"),
    }

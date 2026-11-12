"""Path handling for the receipts ledger.

The whole plugin turns on one distinction, so it lives in one place:

    a path NAMED in a command's output is not evidence that anything changed.
    a path whose stat actually differs across the call is.

Everything here is cheap and exception-free: this runs on every tool call.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Tools whose `path` argument is the file they write. Anything not listed here is not assumed to
# mutate, because a false mutation is worse than a missed one: it would let an unbacked claim
# look backed.
WRITE_PATH_TOOLS = frozenset({
    "write_file", "patch", "edit_file", "create_file", "append_file",
})

MAX_PATH_LEN = 4096


def hermes_home() -> str:
    """The ACTIVE Hermes profile's home, resolved at call time (never cached at import).

    Inside Hermes this is `hermes_constants.get_hermes_home()`: context-local override, then
    HERMES_HOME, then the platform default, so a gateway serving several profiles gets each
    profile's own directory (PR #153708 review). Outside Hermes (tests, scripts) it falls back to
    HERMES_HOME, then ~/.hermes.
    """
    try:
        from hermes_constants import get_hermes_home
        return str(get_hermes_home())
    except Exception:
        h = os.environ.get("HERMES_HOME", "").strip()
        return os.path.expanduser(os.path.expandvars(h)) if h else os.path.join(os.path.expanduser("~"), ".hermes")


def normalise(path: Any) -> Optional[str]:
    """Absolute, expanded, no trailing-slash games. None when it is not a usable path."""
    if not isinstance(path, str):
        return None
    p = path.strip().strip("'\"`")
    if not p or len(p) > MAX_PATH_LEN or "\n" in p:
        return None
    try:
        p = os.path.expanduser(p)
        if not os.path.isabs(p):
            p = os.path.join(os.getcwd(), p)
        return os.path.normpath(p)
    except Exception:
        return None


def stat_of(path: Optional[str]) -> dict:
    """A comparable snapshot. Absence is a fact, not an error."""
    if not path:
        return {"exists": False}
    try:
        st = os.stat(path)
        return {"exists": True, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    except (OSError, ValueError):
        return {"exists": False}


def changed(before: dict, after: dict) -> bool:
    """Did the call change this path? Three ways, all of them facts on disk."""
    if not after.get("exists"):
        # A deletion is a change.
        return bool(before.get("exists"))
    if not before.get("exists"):
        return True
    return (before.get("mtime_ns") != after.get("mtime_ns")
            or before.get("size") != after.get("size"))


def writable_paths(tool_name: str, args: Any) -> list[str]:
    """Paths this call is about to write, judged from the tool's own arguments."""
    if tool_name not in WRITE_PATH_TOOLS or not isinstance(args, dict):
        return []
    out: list[str] = []
    for key in ("path", "file_path", "target"):
        p = normalise(args.get(key))
        if p:
            out.append(p)
            break
    return out

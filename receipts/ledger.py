"""The evidence ledger: what the session actually changed.

Written by hooks, read by the verdict step. One JSONL file per session, append-only.

Two rules keep this honest:

1. A mutation is recorded only when stat() differs across the call. A path that a command merely
   PRINTED is not evidence and is never recorded.
2. Every function here is fail-open. A ledger that breaks a user's session would be a worse bug
   than the problem it exists to solve, so nothing raises out of this module.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

from . import paths as P

_LOCK = threading.Lock()          # post_tool_call fires concurrently on parallel calls
# call key -> {path: stat snapshot}. One structure, so a pre and its post can never come from
# different bookkeeping generations.
_PENDING: dict[str, dict[str, dict]] = {}
_MAX_PENDING = 512

DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".hermes", "plugin-data", "receipts")


def root() -> str:
    return os.environ.get("RECEIPTS_ROOT") or DEFAULT_ROOT


def _call_key(task_id: str, session_id: str, tool_call_id: str) -> str:
    return f"{task_id}|{session_id}|{tool_call_id}"


def session_file(session_id: str, task_id: str = "") -> str:
    sid = (session_id or task_id or f"unknown-{time.strftime('%Y%m%d')}").replace("/", "_")
    sid = "".join(c for c in sid if c.isalnum() or c in "-_.|")[:120] or "unknown"
    d = os.path.join(root(), "sessions")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{sid}.jsonl")


def _append(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        fh.flush()


# --------------------------------------------------------------------------- hooks

def pre_tool_call(tool_name: str = "", args: Any = None, task_id: str = "",
                  session_id: str = "", tool_call_id: str = "", **_: Any) -> None:
    """Snapshot the paths this call intends to write, before it runs."""
    try:
        targets = P.writable_paths(tool_name, args)
        if not targets:
            return
        key = _call_key(task_id, session_id, tool_call_id)
        with _LOCK:
            if len(_PENDING) > _MAX_PENDING:      # a leak here would grow without bound
                _PENDING.clear()
            _PENDING[key] = {t: P.stat_of(t) for t in targets}
    except Exception:
        return


def post_tool_call(tool_name: str = "", args: Any = None, result: Any = None,
                   task_id: str = "", session_id: str = "", tool_call_id: str = "",
                   duration_ms: int = 0, status: Optional[str] = None, **_: Any) -> None:
    """Record what changed. Only a differing stat() counts."""
    try:
        key = _call_key(task_id, session_id, tool_call_id)
        targets = P.writable_paths(tool_name, args)
        with _LOCK:
            before = _PENDING.pop(key, {})

        mutations = []
        for path in targets:
            after = P.stat_of(path)
            prior = before.get(path) or {"exists": False}
            if P.changed(prior, after):
                mutations.append({"path": path, "before": prior, "after": after})

        # Terminal calls carry no reliable path prediction, so they are recorded as command
        # evidence instead: what ran, and how it ended. Never inferred as a file change.
        command = None
        if tool_name == "terminal" and isinstance(args, dict):
            cmd = args.get("command")
            if isinstance(cmd, str) and cmd.strip():
                command = cmd.strip()[:2000]

        if not mutations and not command:
            return

        _append(session_file(session_id, task_id), {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": session_id, "task_id": task_id, "tool_call_id": tool_call_id,
            "tool": tool_name, "status": status, "duration_ms": duration_ms,
            "mutations": mutations, "command": command,
        })
    except Exception:
        return


def read_ledger(session_id: str, task_id: str = "") -> list[dict]:
    """Every evidence record for a session, oldest first. Unreadable lines are skipped, not fatal."""
    try:
        path = session_file(session_id, task_id)
        if not os.path.isfile(path):
            return []
        out = []
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out
    except Exception:
        return []


def evidence_paths(session_id: str, task_id: str = "") -> dict[str, dict]:
    """Every path proven to have changed this session, newest stat wins."""
    out: dict[str, dict] = {}
    for rec in read_ledger(session_id, task_id):
        for m in rec.get("mutations") or []:
            p = m.get("path")
            if p:
                out[p] = m.get("after") or {}
    return out


def current_session_records() -> list[dict]:
    """Records for the most recently written session file.

    The `/receipts` command is not always handed a session id, and inventing one would silently
    report an empty ledger. Newest file is a stated heuristic, not a guess dressed as a fact.
    """
    try:
        d = os.path.join(root(), "sessions")
        if not os.path.isdir(d):
            return []
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]
        if not files:
            return []
        newest = max(files, key=os.path.getmtime)
        return read_ledger(os.path.basename(newest)[:-6])
    except Exception:
        return []


def on_session_end(session_id: str = "", task_id: str = "", **_: Any) -> None:
    """End-of-session receipt. Day 3 writes the artifact; today it records a boundary marker so the
    ledger shows which records belong to a finished session."""
    try:
        recs = read_ledger(session_id, task_id) if (session_id or task_id) else []
        _append(session_file(session_id, task_id), {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": "session_end",
            "records": len(recs),
            "files_changed": len(evidence_paths(session_id, task_id)),
        })
    except Exception:
        return

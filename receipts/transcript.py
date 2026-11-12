"""Read the session's own transcript — read-only, bounded, fail-open.

The plugin never copies tool output into its own store. The host already keeps it (`messages`,
role='tool', indexed on session_id + timestamp), so this is a read of existing data rather than a
second place for secrets to land.

Two limits, both stated rather than hidden:

  * the schema belongs to Hermes, not to this plugin — a change breaks this, so every failure
    degrades to "no output", which produces an UNVERIFIABLE verdict rather than a wrong one;
  * reads are bounded. A session with thousands of messages does not get fully scanned on exit.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

MAX_MESSAGES = 600          # newest N messages considered at session end
MAX_OUTPUT_CHARS = 20_000   # per tool message, ignored beyond this
MAX_TOTAL_CHARS = 400_000
READ_TOOLS = ("read_file",)  # native tools whose subject is an exact `path` argument (C2)
# Markers the host itself writes when it shortens a tool result before storing it.
_HOST_TRUNCATION = re.compile(r"\[truncated|output truncated", re.I)


def db_location() -> str:
    """The ACTIVE profile's session database, resolved on every call (PR #153708):
    <Hermes home>/state.db, unless RECEIPTS_TRANSCRIPT_DB overrides it."""
    from . import paths as P
    return os.environ.get("RECEIPTS_TRANSCRIPT_DB") or os.path.join(P.hermes_home(), "state.db")


def _connect(db_path: str | None = None) -> sqlite3.Connection | None:
    path = db_path or db_location()
    if not os.path.isfile(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
    except sqlite3.Error:
        return None


def _call_commands(con: sqlite3.Connection, session_id: str,
                   max_messages: int) -> dict:
    """call_id -> {name, command} from assistant tool_calls JSON (R4 native join).

    The verdict needs output bound to the COMMAND that produced it — a bare
    output proves something ran, not what. Hermes keeps the call side in
    `messages.tool_calls` on assistant rows; the join key is `tool_call_id`
    on the tool row. Any unparseable call simply yields no command — the
    output stays, unbound, and downstream treats it as unobserved rather
    than guessing which command it belonged to (the aliasing failure).
    """
    try:
        rows = con.execute(
            "SELECT tool_calls FROM messages "
            "WHERE session_id=? AND role='assistant' AND tool_calls IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (session_id, int(max_messages)),
        ).fetchall()
    except sqlite3.Error:
        return {}
    calls: dict = {}
    for (raw,) in rows:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            for call in parsed or []:
                fid = call.get("call_id") or call.get("id")
                fn = call.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = None
                if not isinstance(args, dict):
                    args = {}
                command = args.get("command")
                # C2: a native read's subject is its PATH argument, not a command. Dropping it
                # made a genuine exact-path read_file indistinguishable from no observation.
                path = args.get("path")
                if fid:
                    calls[fid] = {"name": fn.get("name") or "",
                                  "command": command if isinstance(command, str) else None,
                                  "path": path if isinstance(path, str) else None}
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue
    return calls


def read_tool_outputs(session_id: str, db_path: str | None = None,
                      max_messages: int = MAX_MESSAGES) -> list[dict]:
    """Newest tool results for a session: [{tool, output, command, path, call_id, exit_code,
    error, truncated, enveloped, ok}].

    `command` is the joined originating command (None when the schema has no
    call linkage or the call is unparseable) — R4's native join. `call_id`
    is the transcript's own binding key, the strongest join when present.
    Empty on any failure.
    """
    if not session_id:
        return []
    con = _connect(db_path)
    if con is None:
        return []
    try:
        try:
            rows = con.execute(
                "SELECT tool_name, tool_call_id, content FROM messages "
                "WHERE session_id=? AND role='tool' ORDER BY id DESC LIMIT ?",
                (session_id, int(max_messages)),
            ).fetchall()
        except sqlite3.Error:
            rows = [(t, None, c) for t, c in con.execute(
                "SELECT tool_name, content FROM messages "
                "WHERE session_id=? AND role='tool' ORDER BY id DESC LIMIT ?",
                (session_id, int(max_messages)),
            ).fetchall()]
        calls = _call_commands(con, session_id, max_messages)
    except sqlite3.Error:
        return []
    finally:
        con.close()

    out, total = [], 0
    for tool_name, tool_call_id, content in rows:   # newest first
        if not content:
            continue
        text = content if isinstance(content, str) else str(content)
        enveloped, exit_code, error, truncated = False, None, False, False
        if text.lstrip().startswith("{"):
            try:  # Hermes tool content is a JSON envelope: {"output": "..."} / read_file {"content": ...}
                envelope = json.loads(text)
                if isinstance(envelope, dict):
                    body = envelope.get("output")
                    if not isinstance(body, str) and tool_name in READ_TOOLS:
                        body = envelope.get("content")
                    if isinstance(body, str):
                        text, enveloped = body, True
                        code = envelope.get("exit_code")
                        exit_code = code if isinstance(code, int) else None
                        error = bool(envelope.get("error"))
                        truncated = envelope.get("truncated") is True
                    elif envelope.get("error"):
                        error = True
            except json.JSONDecodeError:
                pass
        # C2: a cut observation must SAY it was cut. An absence inferred from the first
        # MAX_OUTPUT_CHARS of a longer listing is an inference from text we never read.
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS]
            truncated = True
        if _HOST_TRUNCATION.search(text):
            truncated = True                 # the host shortened it before we ever saw it
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            break
        call = calls.get(tool_call_id) or {}
        # Identity: a call whose function name disagrees with the tool row is not this output's call.
        if call and tool_name and call.get("name") and call["name"] != tool_name:
            call = {}
        out.append({
            "tool": tool_name or "",
            "output": text,
            "command": call.get("command"),
            "path": call.get("path"),
            "call_id": tool_call_id,
            "exit_code": exit_code,
            "error": error,
            "truncated": truncated,
            "enveloped": enveloped,
            # transcript rows carry an exit flag only inside the envelope; ledger records carry status
            "ok": (False if (error or (exit_code not in (None, 0)))
                   else (True if exit_code == 0 else None)),
        })
    return out


def read_assistant_text(session_id: str, db_path: str | None = None,
                        max_messages: int = MAX_MESSAGES) -> str:
    """The assistant's own words, joined. This is where claims live."""
    if not session_id:
        return ""
    con = _connect(db_path)
    if con is None:
        return ""
    try:
        rows = con.execute(
            "SELECT content FROM messages "
            "WHERE session_id=? AND role='assistant' AND content IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (session_id, int(max_messages)),
        ).fetchall()
    except sqlite3.Error:
        return ""
    finally:
        con.close()
    parts = []
    for (content,) in rows:                  # newest first
        if not content:
            continue
        text = content if isinstance(content, str) else str(content)
        parts.append(text)
    return "\n\n".join(reversed(parts))


def transcript_available(session_id: str, db_path: str | None = None) -> bool:
    """A cheap check so the receipt can say WHY it could not judge, instead of implying it did."""
    con = _connect(db_path)
    if con is None:
        return False
    try:
        row = con.execute("SELECT 1 FROM messages WHERE session_id=? LIMIT 1", (session_id,)).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()

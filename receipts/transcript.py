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
import sqlite3
from typing import Any

DEFAULT_DB = os.path.expanduser("~/.hermes/state.db")
MAX_MESSAGES = 600          # newest N messages considered at session end
MAX_OUTPUT_CHARS = 20_000   # per tool message, ignored beyond this
MAX_TOTAL_CHARS = 400_000


def _connect(db_path: str | None = None) -> sqlite3.Connection | None:
    path = db_path or os.environ.get("RECEIPTS_TRANSCRIPT_DB") or DEFAULT_DB
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
                command = None
                if isinstance(args, str):
                    try:
                        command = json.loads(args).get("command")
                    except (json.JSONDecodeError, AttributeError):
                        command = None
                elif isinstance(args, dict):
                    command = args.get("command")
                if fid:
                    calls[fid] = {"name": fn.get("name") or "", "command": command}
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue
    return calls


def read_tool_outputs(session_id: str, db_path: str | None = None,
                      max_messages: int = MAX_MESSAGES) -> list[dict]:
    """Newest tool results for a session: [{tool, output, command, call_id}].

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
        if text.lstrip().startswith("{"):
            try:  # Hermes tool content is a JSON envelope: {"output": "..."}
                envelope = json.loads(text)
                if isinstance(envelope, dict) and isinstance(envelope.get("output"), str):
                    text = envelope["output"]
            except json.JSONDecodeError:
                pass
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS]
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            break
        call = calls.get(tool_call_id) or {}
        out.append({
            "tool": tool_name or "",
            "output": text,
            "command": call.get("command"),
            "call_id": tool_call_id,
            "ok": None,  # transcript rows carry no exit flag; ledger records do
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

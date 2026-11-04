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


def read_tool_outputs(session_id: str, db_path: str | None = None,
                      max_messages: int = MAX_MESSAGES) -> list[dict]:
    """Newest tool results for a session: [{tool, output}]. Empty on any failure."""
    if not session_id:
        return []
    con = _connect(db_path)
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT tool_name, content FROM messages "
            "WHERE session_id=? AND role='tool' ORDER BY id DESC LIMIT ?",
            (session_id, int(max_messages)),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    out, total = [], 0
    for tool_name, content in rows:          # newest first
        if not content:
            continue
        text = content if isinstance(content, str) else str(content)
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS]
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            break
        out.append({"tool": tool_name or "", "output": text})
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

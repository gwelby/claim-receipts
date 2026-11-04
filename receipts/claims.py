"""Session summary for `/receipts`.

DAY 1 SCOPE — this reports EVIDENCE ONLY: the files this session provably changed and the commands
it ran. It makes no attempt yet to judge the session's claims. Claim reconciliation (backed /
unbacked / unverifiable) lands on Day 2 and will call into this module.

Saying which day of work a feature is on, in the code, is deliberate: a summary that quietly implies
it has checked the claims when it has only listed the evidence would be the plugin committing the
exact error it exists to catch.
"""
from __future__ import annotations

import time

from . import ledger


def _ago(mtime_ns: int) -> str:
    try:
        secs = max(0, (time.time_ns() - int(mtime_ns)) / 1e9)
    except Exception:
        return "?"
    if secs < 60:
        return f"{secs:.0f}s"
    if secs < 3600:
        return f"{secs/60:.0f}m"
    return f"{secs/3600:.1f}h"


def render_session_summary(session_id: str = "", task_id: str = "") -> str:
    """Human-readable evidence for one session. Cheap, local, no network."""
    sid = (session_id or "").strip()
    records = ledger.read_ledger(sid, task_id) if sid else ledger.current_session_records()
    if not records:
        return ("Receipts — no evidence recorded yet for this session.\n"
                "Nothing has been written or run, or the hooks are not loaded.")

    paths = {}
    commands = []
    for rec in records:
        for m in rec.get("mutations") or []:
            p = m.get("path")
            if p:
                paths[p] = (m.get("after") or {})
        cmd = rec.get("command")
        if cmd:
            commands.append((cmd, rec.get("status")))

    lines = [f"Receipts — {len(paths)} file(s) provably changed, {len(commands)} command(s) run",
             ""]
    for p, st in sorted(paths.items()):
        size = st.get("size")
        age = _ago(st.get("mtime_ns", 0))
        lines.append(f"  changed  {p}  ({size} B, {age} ago)")
    if commands:
        lines.append("")
        for cmd, status in commands[-10:]:
            flag = "ok " if status in (None, "ok") else str(status)[:8]
            lines.append(f"  ran [{flag}] {cmd[:110]}")
    lines.append("")
    lines.append("These are facts from the filesystem, not claims. Claim reconciliation: Day 2.")
    return "\n".join(lines)

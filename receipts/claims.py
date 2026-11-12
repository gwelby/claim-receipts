"""Session summary for `/claim-receipts`.

This summary reports EVIDENCE ONLY: the files this session provably changed and the commands it ran.
It does not judge claims; the per-claim verdicts are made at session end (`receipt.py`, `judge.py`)
and written to the receipt artifact.

Saying so in the summary itself is deliberate: a summary that quietly implies it has checked the
claims when it has only listed the evidence would be the plugin committing the exact error it exists
to catch. (The line used to say "Claim reconciliation: Day 2." — a stale build-plan date that read as
a promise about a feature that has since shipped in `receipt.py`.)
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


def render_for_command(raw_args: str = "", session_id: str = "", platform: str = "") -> str:
    """Pick whose ledger `/claim-receipts` may show (PR #153708 review).

    Local CLI (`platform == "cli"`): an explicit session argument, else this session, else the newest
    ledger on this machine (one user, their own sessions). Any other surface, including an unknown
    one: only the calling session's own ledger. No fallback, and no reading another session by
    naming it, so one chat on a gateway can never see another chat's commands or file paths.
    """
    asked = (raw_args or "").strip()
    own = (session_id or "").strip()
    if (platform or "").strip().lower() == "cli":
        sid = asked or own
        if sid and ledger.read_ledger(sid):
            return render_session_summary(sid)
        return render_session_summary("", newest_label=True)
    if asked and asked != own:
        return "Receipts — this command shows only this chat's own evidence."
    if not own:
        return "Receipts — the host did not identify this chat's session, so nothing is shown."
    return render_session_summary(own)


def render_session_summary(session_id: str = "", task_id: str = "", newest_label: bool = False) -> str:
    """Human-readable evidence for one session. Cheap, local, no network."""
    sid = (session_id or "").strip()
    records = ledger.read_ledger(sid, task_id) if sid else ledger.current_session_records()
    if not records:
        return ("Receipts — no evidence recorded yet for this session.\n"
                "Nothing has been written or run, or the hooks are not loaded.")
    note = ("(newest ledger on this machine; it may belong to another of your sessions)\n"
            if newest_label else "")

    paths = {}
    unobserved = []
    commands = []
    for rec in records:
        for m in rec.get("mutations") or []:
            p = m.get("path")
            if not p:
                continue
            if m.get("before") is not None and (m.get("before") or {}).get("exists") is None:
                unobserved.append((p, m.get("after") or {}))   # R1: seen write, no before = not certified
            else:
                paths[p] = (m.get("after") or {})
        cmd = rec.get("command")
        if cmd:
            commands.append((cmd, rec.get("status")))

    lines = [f"{note}Receipts — {len(paths)} file(s) provably changed, {len(commands)} command(s) run",
             ""]
    for p, st in sorted(paths.items()):
        size = st.get("size")
        age = _ago(st.get("mtime_ns", 0))
        lines.append(f"  changed  {p}  ({size} B, {age} ago)")
    for p, st in unobserved:
        lines.append(f"  observed  {p}  (write seen, before-state never captured — not certified)")
    if commands:
        lines.append("")
        for cmd, status in commands[-10:]:
            flag = "ok " if status in (None, "ok") else str(status)[:8]
            lines.append(f"  ran [{flag}] {cmd[:110]}")
    lines.append("")
    lines.append("These are facts from the filesystem, not claims. No claim is judged here; "
                 "per-claim verdicts are written to the receipt at session end.")
    return "\n".join(lines)

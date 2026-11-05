"""The session receipt — the artifact a person actually reads.

Everything before this module gathered evidence and reached verdicts. This is where it becomes a
document: what the session says it did, what the record shows, and — stated as plainly as anything
else — what could not be checked.

The last section is not decoration. A receipt that lists only its findings implies that everything not
listed was verified. Naming the unchecked claims is the difference between a report and a reassurance.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from typing import Any

from . import evidence as E
from . import judge as J
from . import ledger
from . import transcript as T

RECEIPT_DIR = "receipts"


def build(session_id: str, task_id: str = "", db_path: str | None = None) -> dict:
    """Assemble the receipt for one session. Never raises: a missing store is a finding, not a crash."""
    records = ledger.read_ledger(session_id, task_id) if (session_id or task_id) else []
    ev = E.Evidence.from_session(session_id, records, db_path=db_path)

    text = T.read_assistant_text(session_id, db_path) if session_id else ""
    claims = J.extract_claims(text)
    judged, unjudged = [], []
    for c in claims:
        (judged if J.judgeable(c, ev) else unjudged).append(c)

    verdicts = []
    for c in judged:
        v = J.judge(c, ev)
        verdicts.append({"verdict": v.verdict, "reason": v.reason, "detail": v.detail,
                         "kind": c.kind, "claim": c.text})

    counts = Counter(v["verdict"] for v in verdicts)
    return {
        "session": session_id or task_id or "unknown",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "transcript_available": bool(text),
        "evidence": {
            "files_mutated": sorted(ev.mutations),
            "mutations": len(ev.mutations),
            "commands": len(ev.commands),
            "listings": len(ev.listings),
            "tool_outputs": len(ev.tool_outputs),
        },
        "claims": {
            "detected": len(claims),
            "judged": len(judged),
            "unjudged": len(unjudged),
            "backed": counts.get("BACKED", 0),
            "contradicted": counts.get("CONTRADICTED", 0),
            "unbacked": counts.get("UNBACKED", 0),
            "unverifiable": counts.get("UNVERIFIABLE", 0),
        },
        "verdicts": verdicts,
        "unjudged_sample": [{"kind": c.kind, "claim": c.text} for c in unjudged[:10]],
    }


def render_md(d: dict) -> str:
    c = d["claims"]
    e = d["evidence"]
    L = []
    L.append(f"# Session receipt — {d['session'][:16]}")
    L.append("")
    L.append(f"*Generated {d['generated']} by the receipts plugin. Evidence is read from this session's "
             f"own record; nothing here is inferred from prose alone.*")
    L.append("")

    L.append("## What the record shows")
    if not d["transcript_available"]:
        L.append("")
        L.append("**No transcript was readable for this session**, so no claim could be checked. "
                 "That is not a clean bill of health — it is an absence of evidence, and it is "
                 "reported here rather than passed over.")
    L.append("")
    L.append(f"- files changed: **{e['mutations']}**")
    L.append(f"- commands run: {e['commands']}")
    L.append(f"- directories listed: {e['listings']}")
    if e["files_mutated"]:
        L.append("")
        for p in e["files_mutated"][:25]:
            L.append(f"  - `{p}`")
        if len(e["files_mutated"]) > 25:
            L.append(f"  - …and {len(e['files_mutated']) - 25} more")
    L.append("")

    L.append("## Verdicts")
    L.append("")
    if not d["verdicts"]:
        L.append("*No claim in this session could be checked against the evidence.*")
    for label, key in (("CONTRADICTED — evidence points the other way", "CONTRADICTED"),
                       ("UNBACKED — no evidence either way", "UNBACKED"),
                       ("BACKED — evidence supports it", "BACKED"),
                       ("UNVERIFIABLE — the evidence cannot decide", "UNVERIFIABLE")):
        rows = [v for v in d["verdicts"] if v["verdict"] == key]
        if not rows:
            continue
        L.append(f"### {label} ({len(rows)})")
        L.append("")
        for v in rows[:12]:
            L.append(f"- {v['claim'][:160]}")
            L.append(f"  - `{v['reason']}` — {v['detail'][:120]}")
        L.append("")

    L.append("## What this receipt does NOT tell you")
    L.append("")
    L.append(f"{c['detected']} statements were detected as claims; {c['judged']} could be checked and "
             f"{c['unjudged']} could not. The unchecked ones name nothing the record can locate — a "
             f"relative path, a paraphrase, an artifact on another machine. They are neither proven "
             f"nor accused.")
    L.append("")
    L.append("It also cannot tell you whether the work was *good*: only that what was claimed exists, "
             "changed, or does not.")
    if d["unjudged_sample"]:
        L.append("")
        L.append("A sample of what could not be checked:")
        L.append("")
        for u in d["unjudged_sample"][:5]:
            L.append(f"- ({u['kind']}) {u['claim'][:140]}")
    return "\n".join(L) + "\n"


def write(session_id: str, task_id: str = "", db_path: str | None = None) -> dict:
    """Write <session>.md and <session>.json. Returns a small summary; raises nothing."""
    try:
        d = build(session_id, task_id, db_path=db_path)
        out = os.path.join(ledger.root(), RECEIPT_DIR)
        os.makedirs(out, exist_ok=True)
        # No truncation: a shortened id is an arbitrary prefix, and two sessions could share one.
        # Session ids are host-prefixed hashes, so replacing separators is enough to make them a name.
        stem = (session_id or task_id or "unknown").replace("/", "_").replace(os.sep, "_")
        md_path = os.path.join(out, f"{stem}.md")
        js_path = os.path.join(out, f"{stem}.json")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(render_md(d))
        with open(js_path, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
        return {"ok": True, "md": md_path, "json": js_path, "claims": d["claims"]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

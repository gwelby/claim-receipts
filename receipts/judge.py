"""Claim extraction and verdicts.

Four verdicts, and the split that matters to a user is CONTRADICTED vs UNBACKED:

    BACKED        the evidence supports the claim
    CONTRADICTED  the evidence points the other way   ("your agent said X; the evidence says not-X")
    UNBACKED      no evidence either way              ("can't prove it")
    UNVERIFIABLE  the evidence cannot decide          (never looked, or looked somewhere else)

Everything finer than that is a REASON CODE, not a fifth verdict. A five-way score invites arguing
about which bucket a miss belongs in instead of fixing it.

Honest limit: claim DETECTION here is pattern-based, not comprehension. It will miss paraphrases.
The acceptance fixtures measure exactly that, and the score is reported rather than assumed.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .evidence import Evidence

# ----------------------------------------------------------------------------- claim shapes

# Hedges are limited to statements about VERIFICATION — that is what the evidence can speak to.
# "I don't know what it would be yet" is a statement about the speaker, not about the record; scoring
# it BACKED inflated the good number by 15 on one session, which is the flattering direction and the
# one direction a receipt must never be wrong in.
HEDGE = re.compile(
    r"\b(could ?n[o']t confirm|could not confirm|cannot confirm|can'?t confirm|unable to confirm|"
    r"could ?n[o']t verify|cannot verify|unable to verify|not verified|unverified|no information)\b",
    re.I)

ABSENCE = re.compile(
    r"\b(does ?n[o']t exist|does not exist|did ?n[o']t exist|never existed|no such file|"
    r"not found|nothing (?:there|was there)|is missing|was missing|absent)\b", re.I)

CURRENCY = re.compile(r"\b(current|latest|newest|up[ -]to[ -]date|most recent)\b", re.I)

COMPLETION = re.compile(
    r"\b(done|fixed|completed?|finished|shipped|built|created|wrote|written|saved|generated|"
    r"rebuilt|produced|verified|passed|applied|patched|reviewed|eyeballed|checked|looked at|"
    r"walked through)\b", re.I)

EXISTENCE = re.compile(r"\b(exists|is there|present|already written|is written)\b", re.I)

SCOPE = re.compile(r"\b(all|every|each|entire|whole)\b", re.I)

# Coverage claims assert an extent, so they can be contradicted by a measurement taken in-session.
# A success assertion is narrower than "completion": it claims the thing now works. Only these can
# be contradicted by a later error; otherwise "I hit an error" gets called a lie for admitting one.
SUCCESS = re.compile(
    r"\b(fixed|resolved|solved|now works|works now|working now|is working|is fixed)\b", re.I)

COVERAGE = re.compile(
    r"\b(full[- ]page|full[- ]bleed|edge[- ]to[- ]edge|entire (?:page|surface)|"
    r"100\s*% of the page|fills the page)\b", re.I)

# The leading lookbehind matters: without it, "src/models/dory.cpp" yields a "match" of
# "/models/dory.cpp", which then reads as an ABSOLUTE path that does not exist — a false
# accusation against a file that was verified on another machine.
PATHISH = re.compile(r"(?<![\w.\-/])((?:/[\w.\-]+){2,}|[\w.\-]+\.(?:md|py|pdf|json|txt|png|csv|db|yaml|yml))")
TOKENISH = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\d*\b")     # PROOF2, S15, D01


@dataclass
class Claim:
    text: str
    kind: str                 # hedge | absence | currency | existence | completion | scope
    subject: str | None
    scope_all: bool = False


def extract_claims(text: str) -> list[Claim]:
    """Sentences that assert something checkable. One Claim per sentence, strongest shape wins."""
    out: list[Claim] = []
    for raw in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        sentence = raw.strip()
        if len(sentence) < 8:
            continue
        # A line that is a report ABOUT output is not a claim MADE by the agent:
        #   "MUTATION /x/y.md  absent -> 194 B"  is the plugin's own ledger being quoted back.
        if "->" in sentence or "MUTATION" in sentence or sentence.count("|") >= 2:
            continue
        subject = None
        m = PATHISH.search(sentence)
        if m:
            subject = m.group(1)
        else:
            m = TOKENISH.search(sentence)
            if m:
                subject = m.group(0)
        scope_all = bool(SCOPE.search(sentence))

        # Hedge first: honest uncertainty must never be scored as a false claim.
        if HEDGE.search(sentence):
            kind = "hedge"
        elif COVERAGE.search(sentence):
            kind = "coverage"
        elif ABSENCE.search(sentence):
            kind = "absence"
        elif CURRENCY.search(sentence):
            kind = "currency"
        elif EXISTENCE.search(sentence):
            kind = "existence"
        elif COMPLETION.search(sentence):
            kind = "completion"
        else:
            continue
        claim = Claim(text=sentence[:300], kind=kind, subject=subject, scope_all=scope_all)
        if claim.text not in {c.text for c in out}:
            out.append(claim)
    return out


def resolve(subject: str | None, ev: Evidence) -> str | None:
    """Turn a name in prose into a path, using only what the session actually saw.

    'PROOF2' resolves to a path whose basename starts with 'proof2'. If it resolves to nothing the
    claim is not quietly dropped or guessed at — the caller reports it unverifiable.
    """
    if not subject:
        return None
    if os.sep in subject:
        # A relative path belongs to a working directory we did not record, and often to another
        # machine entirely (a build verified over ssh). Calling it "missing" is a false accusation;
        # the honest answer is that it cannot be checked from here.
        return os.path.normpath(subject) if os.path.isabs(subject) else None
    want = subject.lower()
    seen: list[str] = []
    for p in list(ev.mutations) + (list(ev.fs) if ev.fs else []):
        base = os.path.basename(os.path.normpath(p)).lower()
        if base == want or base.startswith(want + "_") or base.startswith(want + "-"):
            if p not in seen:
                seen.append(p)
    if not seen:
        return None
    # Prefer something the session actually touched, then the shortest (least nested) match.
    touched = [p for p in seen if p in ev.mutations]
    return (touched or sorted(seen, key=len))[0]


def judgeable(claim: Claim, ev: Evidence) -> bool:
    """Only judge a claim we can LOCATE.

    A claim whose subject resolves to nothing in the session's evidence cannot be checked — and
    emitting UNBACKED for it is cry-wolf. On a real session this was the difference between 336
    claims (mostly unbacked noise) and a short list worth reading. Unjudged claims are counted and
    sampled, never scored.
    """
    if claim.kind in ("hedge", "coverage"):
        return True
    return resolve(claim.subject, ev) is not None


@dataclass
class Verdict:
    verdict: str              # BACKED | CONTRADICTED | UNBACKED | UNVERIFIABLE
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason, "detail": self.detail}


def judge(claim: Claim, ev: Evidence, evidence_count: int | None = None,
          claimed_count: int | None = None) -> Verdict:
    """One claim, one verdict. Never returns a boolean — the reason always comes with it."""
    path = resolve(claim.subject, ev)

    # ---- hedge: honest uncertainty is not a false claim (acceptance case #6) ----
    if claim.kind == "hedge":
        return Verdict("BACKED", "hedge-matches-scope",
                       "the claim reports the limits of its own search")

    # ---- coverage: a measured percentage can contradict an extent claim (case #7) ----
    if claim.kind == "coverage":
        measured = ev.measured_fractions()
        if not measured:
            return Verdict("UNVERIFIABLE", "outside-session",
                           "no measurement was taken in this session")
        # Subject join: a measurement only speaks to the claim it names. An unrelated
        # second.png at 53% must not contradict first.png at 100% — join on the
        # subject's tokens; an unjoined measurement is not evidence for this claim.
        toks = {t for t in (path, os.path.basename(path or ""), claim.subject) if t}
        if toks:
            joined = [m for m in measured
                      if any(t in (m[1] + " " + (m[2] if len(m) > 2 else "")) for t in toks)]
            if not joined:
                return Verdict("UNVERIFIABLE", "measurement-not-joined",
                               f"{len(measured)} measurement(s) taken, none names this subject")
            measured = joined
        low = min(measured, key=lambda m: m[0])
        if low[0] < 0.95:
            return Verdict("CONTRADICTED", "measurement-disagrees",
                           f"measured {low[0]*100:.0f}% coverage ({low[1][:60]})")
        return Verdict("BACKED", "measurement-agrees", f"measured {low[0]*100:.0f}% coverage")

    # ---- absence: only a listing can license this, and only inside its scope (case #2) ----
    if claim.kind == "absence":
        if path and path in ev.mutations:
            if ev.mutations[path].get("exists"):
                return Verdict("CONTRADICTED", "artifact-present",
                               f"the session wrote {path} and then reported it absent")
            return Verdict("BACKED", "deleted-this-session",
                           f"the session deleted {path} — absence by mutation, not listing")
        parent = os.path.dirname(path) if path else None
        listing = ev.searched_for(parent or path or "/")
        if listing is None:
            ran = ", ".join(sorted({l.root for l in ev.listings})[:2])
            detail = (f"searched {ran}, but the claim is about {parent or path}"
                      if ran else "no listing ran this session, so nothing establishes the absence")
            return Verdict("UNVERIFIABLE", "search-scope", detail)
        if path and not listing.covers(path):
            return Verdict("UNVERIFIABLE", "search-scope",
                           f"searched {listing.root}, claim is about {path}")
        return Verdict("BACKED", "absence-established",
                       f"absence established inside {listing.root}")

    # ---- currency: 'current' is a claim about siblings, not about the file (case #1) ----
    if claim.kind == "currency":
        if not path:
            return Verdict("UNVERIFIABLE", "outside-session", "no artifact identified")
        newer = ev.siblings_newer_than(path)
        if newer:
            return Verdict("CONTRADICTED", "stale",
                           f"newer sibling(s): {', '.join(os.path.basename(n) for n in newer[:3])}")
        entity = ev.entity_of(path)
        listing = ev.searched_for(os.path.dirname(entity))
        if listing is None:
            return Verdict("UNVERIFIABLE", "outside-session",
                           "no directory listing ran, so 'current' was never checked")
        return Verdict("BACKED", "newest-in-scope",
                       f"no newer sibling of {os.path.basename(entity)} under {listing.root}")

    # ---- scope: 'all/every' is only as wide as what was touched (case #3) ----
    if claim.scope_all and claimed_count and evidence_count is not None:
        if evidence_count < claimed_count:
            return Verdict("UNBACKED", "scope-narrower",
                           f"claim covers {claimed_count}, evidence covers {evidence_count}")
        return Verdict("BACKED", "scope-covered", f"{evidence_count} of {claimed_count}")

    # ---- existence ----
    if claim.kind == "existence":
        if path and any(os.path.normpath(m.get("path") or "") == path
                        for m in ev.incomplete_mutations):
            return Verdict("UNVERIFIABLE", "unobserved-pre-state",
                           f"a write to {path} was recorded but its before-state was never captured")
        if path and path in ev.mutations:
            if ev.mutations[path].get("exists"):
                return Verdict("BACKED", "written-this-session", path)
            return Verdict("CONTRADICTED", "deleted-this-session",
                           f"{path} was deleted this session")
        if path and ev.stat(path).get("exists"):
            listing = ev.searched_for(path)
            return (Verdict("BACKED", "listed-this-session", path) if listing
                    else Verdict("UNVERIFIABLE", "outside-session", f"{path} exists but was not touched"))
        if path:
            listing = ev.searched_for(os.path.dirname(path))
            if listing and listing.covers(path):
                return Verdict("CONTRADICTED", "artifact-missing", f"absent inside {listing.root}")
            return Verdict("UNBACKED", "artifact-missing",
                           f"nothing at {path} and no write this session")
        return Verdict("UNVERIFIABLE", "outside-session", "no artifact identified")

    # ---- completion ----
    # If a command that NAMES this subject came back non-ok, the claim is contradicted by the
    # session's own later evidence — "I fixed it" followed by an error on the same thing.
    if path and SUCCESS.search(claim.text):
        subject_tokens = {path, os.path.basename(path)}
        # Lifecycle: an error repaired by a LATER successful command on the same
        # subject is not a standing failure — judge the last event, not any failure.
        last = None
        for e in ev.command_events:
            if any(tok and tok in e["cmd"] for tok in subject_tokens):
                last = e
        if last is None:
            for cmd in ev.commands_for_error():   # legacy path: no event order kept
                if any(tok and tok in cmd for tok in subject_tokens):
                    last = {"cmd": cmd, "ok": False}
        if last is not None and not last["ok"]:
            return Verdict("CONTRADICTED", "later-error",
                           f"the last command on this subject failed: {last['cmd'][:70]}")
    if path and path in ev.mutations and ev.mutations[path].get("exists"):
        return Verdict("BACKED", "written-this-session", path)
    if path and ev.stat(path).get("exists"):
        return Verdict("UNVERIFIABLE", "outside-session",
                       f"{path} exists but the session did not touch it")
    if not path:
        return Verdict("UNBACKED", "no-evidence", "no artifact the session touched")
    return Verdict("UNBACKED", "artifact-missing", f"nothing at {path} and no write this session")

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

# _segments/_strip_redirects/_status_bound/_abs_operand are evidence.py's quote-aware segment
# scanner, reused read-only so the judge and the evidence layer agree on what executed (Fable
# round 3: the judge admitted heredoc output the evidence layer refuses to segment).
from .evidence import (Evidence, MEASURE_LINE_CAP, _abs_operand, _segments, _status_bound, _strip_redirects,
                       exit1_is_result)

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

SCOPE = re.compile(r"\b(all|every|each|entire|whole|both)\b", re.I)

# Round-2 finding 8 (hostile pre-check of 364be5d): "Both images are full-page" with ONE 100%
# measurement was BACKED — "both", "two" and numerals over a set assert an extent exactly like
# "all", and the single-subject coverage branch cannot speak for a set. "both" is aggregate for
# every claim kind. Numerals are aggregate for COVERAGE claims only: elsewhere a numeral is usually
# a count inside the claimed property ("35 rasters at 445 dpi, verified", case-08), not a set of
# subjects. A coverage sentence with a numeral followed by a word abstains (e.g. "full-page at
# 300 dpi") — an abstention, never a new favorable or unfavorable verdict.
COVERAGE_AGGREGATE = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|several|multiple|many|"
    r"\d+)\s+(?!%|percent)[A-Za-z]", re.I)

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

# Fable round 3, finding 3: `was-confirmable` contradicts a hedge only when the hedge is about the
# subject's EXISTENCE ("I could not confirm notes.md exists", case-r5b) — writing the file IS the
# confirmation of that. "I created report.pdf but could not verify the layout visually" hedges a
# PROPERTY the write does not establish; contradicting it called an honest limit a lie. Matched in
# the text from the hedge phrase onward, so "created" before the hedge does not count.
HEDGE_EXISTENCE = re.compile(
    r"\b(exists?|existed|existence|is there|was there|are there|were there|present|absent|"
    r"missing|on disk|(?:was|were|got|been|is|are) (?:written|created|saved|produced|generated))\b",
    re.I)


@dataclass
class Claim:
    text: str
    kind: str                 # hedge | absence | currency | existence | completion | scope
    subject: str | None
    scope_all: bool = False


_REL_PATH = re.compile(r"(?<![\w/.:-])((?:\.{1,2}/)?[\w.~-]+(?:/[\w.~-]+)+)")


def _relative_path_in(text: str) -> str | None:
    """A relative path with a folder named in a sentence (`docs/report.md`, `./out/a`), or None.

    Only a path-shaped token counts: it starts with `./` or `../`, or its last part is a file name with
    an extension. Ordinary slashed words ("the read/write layout") are not paths."""
    for m in _REL_PATH.finditer(text or ""):
        tok = m.group(1)
        if "://" in text[max(0, m.start() - 3):m.start() + 3]:
            continue
        last = tok.rsplit("/", 1)[-1]
        if tok.startswith(("./", "../")) or re.search(r"\.[A-Za-z0-9]{1,6}$", last):
            return tok
    return None


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
        # Ordinary punctuation must not become part of the subject (R2): "fixed
        # 'build.py'." and "created out.txt," bind the same as unquoted forms.
        if subject:
            subject = subject.strip(chr(96)).strip(chr(39)).strip(chr(34)).rstrip(".,;:!?)")
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
        if kind == "coverage" and not scope_all:
            # Paths are subjects, not counts: "page-2.png" must not read as "2 pages".
            scope_all = bool(COVERAGE_AGGREGATE.search(PATHISH.sub(" ", sentence)))
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
        # Exact name only. Accepting `want_*` / `want-*` let "app.py exists" be backed by a write
        # to app.py-backup (definitions pass, 2026-11-11). NARROWED.
        if base == want:
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

    # ---- hedge: honest uncertainty is not a false claim — but hedging itself
    # is not evidence either (R5). BACKED needs a captured search/observation;
    # writing the thing you then "cannot confirm" is contradicted outright.
    if claim.kind == "hedge":
        hm = HEDGE.search(claim.text)
        about_existence = bool(HEDGE_EXISTENCE.search(claim.text[hm.start():] if hm else ""))
        # NARROWED unfavorable branch (finding 3): only an existence hedge is was-confirmable;
        # any other hedge on a written file falls through to the observation test.
        if about_existence and path and path in ev.mutations and ev.mutations[path].get("exists"):
            return Verdict("CONTRADICTED", "was-confirmable",
                           f"the session produced {path} and then claimed it could not confirm it")
        # A hedge that names a relative path with a folder (`docs/report.md`) is about that path, not
        # unscoped: PATHISH misses it, and as an unscoped hedge any web_search backed it (definitions
        # pass, 2026-11-11). A relative subject never matches an observation, so such a hedge is
        # UNBACKED (hedge-unobserved): the session never looked at a path it can be bound to.
        if ev.has_observation(path or claim.subject or _relative_path_in(claim.text)):
            return Verdict("BACKED", "hedge-matches-scope",
                           "the claim reports the limits of a search the session actually ran")
        return Verdict("UNBACKED", "hedge-unobserved",
                       "no observation touched this claim's subject — 'could not verify' "
                       "asserts an attempt nothing supports")

    # ---- scope: 'all/every' is only as wide as what was touched (case #3) ----
    # Aggregate-scope admission runs BEFORE the favorable kind branches: a claim
    # asserting an extent ("all 2 images are full-page") must bind the full
    # declared scope or abstain — it may not pass through a single-subject branch
    # and take a favorable verdict for one measurement (Codex round-2 residual).
    # Hedge still preempts: reporting "I could not verify all of it" is honest
    # uncertainty, not an extent assertion.
    if claim.scope_all:
        # Production carries no injected counts: an extent claim we cannot bind
        # abstains rather than silently falling through (R2). A zero claimed
        # count binds nothing either.
        if not claimed_count or evidence_count is None:
            return Verdict("UNVERIFIABLE", "scope-unbindable",
                           "the claim asserts an extent ('all/every') but no countable "
                           "scope was bound this session")
        if evidence_count < claimed_count:
            return Verdict("UNBACKED", "scope-narrower",
                           f"claim covers {claimed_count}, evidence covers {evidence_count}")
        # Counts that cover the extent are ADMISSION, not proof (Codex C1, fdb8f87):
        # "2 of 2 images were measured" says nothing about whether each one is
        # full-page. The claimed property is still judged by its kind, so a joined
        # 53% measurement contradicts "all 2 images are full-page".
        # RETIRED favorable branch: the old `BACKED / scope-covered` verdict is gone.
        # The kind branches judge ONE resolved subject, so their favorable verdict
        # cannot speak for every member of the extent — it abstains instead.
        # Unfavorable verdicts stand: one member failing the property is enough to
        # contradict (or leave unbacked) a claim about all of them.
        v = _judge_kind(claim, ev, path)
        if v.verdict == "BACKED":
            return Verdict("UNVERIFIABLE", "scope-property-unbound",
                           f"{evidence_count} of {claimed_count} in scope, but only "
                           f"{os.path.basename(path or claim.subject or '') or 'one subject'} "
                           f"was judged for the claimed property ({v.reason})")
        return v
    return _judge_kind(claim, ev, path)


# An absolute path written literally in command or output text. Not a shell parser: it finds
# candidates, and every doubtful candidate (redirect target, `..` component) is treated as NOT
# naming the path, which can only withhold a verdict.
_ABS_PATH = re.compile(r"(?<![\w.\-/~$])/[^\s'\"`;|&<>()=]*")


def _named_paths(text: str) -> list[str]:
    """Absolute paths the text names literally, normalized; redirect targets and `..` excluded."""
    out = []
    for m in _ABS_PATH.finditer(text or ""):
        cand = m.group(0)
        if cand.endswith((",", ";", ":")):
            cand = cand[:-1]
        if len(cand) > 1 and cand.endswith(".") and cand[-2].isalnum():
            cand = cand[:-1]                    # sentence punctuation, not part of the name
        if not cand or ".." in cand.split("/"):
            continue                            # lexical `..` may not be the physical parent
        before = (text[:m.start()]).rstrip()
        if before.endswith((">", "<")):
            continue                            # a redirect target is written to, not checked
        out.append(os.path.normpath(cand))
    return out


# Segments whose operands are TEXT to print, not files acted on (Fable round 3, finding 6).
_PRINT_VERBS = frozenset(("echo", "printf"))


def _argv(seg) -> list[str]:
    """A segment's argv without redirections, leading `!` or VAR=value assignments."""
    argv = _strip_redirects(seg.tokens)[0]
    while argv and (argv[0] == "!" or re.match(r"^[A-Za-z_]\w*=", argv[0])):
        argv = argv[1:]
    return argv


def _operand_paths(cmd: str) -> list[str] | None:
    """Absolute paths that EXECUTED segments of `cmd` take as whole operands; None if the command
    cannot be segmented (heredoc, `$(`, backticks, a lone `&`, unbalanced quotes ...).

    Fable round 3, finding 6: binding on the raw text let `echo 'checking T'; false` and
    `printf T >/dev/null; exit 3` contradict "Fixed T." — T was only printed. Now:
      - echo/printf segments name nothing;
      - an operand binds only when the WHOLE (unquoted) operand, or the value of `--opt=VALUE`, is
        the path: a path inside quoted prose or inline code (`python3 -c "open('/x/T')"`) is
        text, not an operand;
      - redirect targets are written to, never checked (round-2 finding 7, kept);
      - `$VAR`, globs, `~` and `..` have no known literal value (evidence._abs_operand).
    Every exclusion can only make a failure unbound (abstain), never favorable.
    """
    segs = _segments(cmd or "")
    if segs is None:
        return None
    out = []
    for seg in segs:
        argv = _argv(seg)
        if not argv or os.path.basename(argv[0]) in _PRINT_VERBS:
            continue
        for tok in argv:
            if tok.startswith("-") and "=" in tok:
                tok = tok.split("=", 1)[1]
            p = _abs_operand(tok)
            if p:
                out.append(p)
    return out


def _names_target(text: str, path: str, inside: bool = False) -> bool:
    """True only if an executed segment of command `text` takes `path` as an operand by its exact
    absolute path (or, with `inside`, a path under it — a failure on /storage/mnt/data speaks to
    /storage/mnt, case-04).

    Round-2 findings 6 and 7: a command that names only the BASENAME (`grep -q good report.md`)
    or a sibling (`OTHER/report.md`, `report.md.bak`) depends on a working directory the record
    does not keep, or names another file. It can neither repair nor contradict the target.
    Round 3 finding 6: printed text and quoted prose name nothing; an unsegmentable command binds
    nothing (see `_operand_paths`).
    """
    if not path or not os.path.isabs(path):
        return False
    path = os.path.normpath(path)
    prefix = path.rstrip("/") + "/"
    named = _operand_paths(text)
    if named is None:
        return False
    return any(p == path or (inside and p.startswith(prefix)) for p in named)


# Fable round 3, finding 2: for these verbs exit 1 is a RESULT ("no match", "files differ", "the
# test is false", "the tree has changes"), not a failure to run. `grep -c TODO APP` exiting 1 after
# a fix means no TODO is left; `diff -u APP.orig APP` exiting 1 means the fix changed something.
# The verb list lives ONCE, in evidence.EXIT1_RESULT_VERBS / evidence.exit1_is_result (which also
# requires `git diff` to be git's subcommand, with --exit-code/--quiet/--no-index). The hedge side
# uses the narrow one-segment evidence.exit1_is_result_cmd because it grants a favourable
# observation; the lifecycle below asks per segment, more broadly, because it only ever abstains.


def _is_result_exit_verb(argv: list[str]) -> bool:
    if not argv:
        return False
    return exit1_is_result([os.path.basename(argv[0])] + list(argv[1:]))


def _exit_may_be_result(cmd: str) -> bool:
    """Could this call's non-ok status be a result-verb's exit 1 rather than a failure?

    True when a result verb runs in a segment whose status the call's status speaks for (every
    later separator `&&`, no `||` before it — evidence._status_bound). The record keeps the status,
    not the exit code, so exit 1 (a result) and exit 2 (an error) cannot be told apart here: such a
    failure is neither a failure nor a success — it abstains. NARROWED unfavorable branch: a
    `test -s T` or `cmp golden T` that really meant "not fixed" now abstains instead of
    contradicting; it never becomes favorable.
    """
    segs = _segments(cmd or "")
    if segs is None:
        return False            # unsegmentable: it cannot bind to the target either (unbound)
    return any(_is_result_exit_verb(_argv(seg)) and _status_bound(segs, i)
               for i, seg in enumerate(segs))


# Text-reproducing programs: their output is the text of an argument or a file, so a percentage
# in it is a quotation, not a measurement (round-2 finding 8: `printf 'page coverage 100%%'` and
# `cat notes.txt` were BACKED as measurements). Any of these anywhere in the producing command
# disqualifies it. Inline interpreter code (`python3 -c`, `perl -e`, ...) prints whatever it is
# told to, so it is disqualified too. A filter that drops a real measurement (`measure x | grep
# coverage`) only makes the claim abstain.
_TEXT_PRODUCERS = frozenset((
    "echo", "printf", "cat", "tac", "head", "tail", "less", "more", "bat", "sed", "awk", "gawk",
    "grep", "egrep", "fgrep", "rg", "cut", "sort", "uniq", "tee", "column", "nl", "paste", "tr",
    "jq", "yq", "xargs", "strings", "od", "xxd", "hexdump", "fold", "fmt", "rev", "envsubst"))
_INLINE_INTERPRETER = re.compile(r"^(python[\d.]*|perl|node|ruby|php|bash|sh|zsh|dash|ksh|"
                                 r"fish|osascript|pwsh|powershell)$", re.I)


def _text_producer(cmd: str) -> bool:
    words = [os.path.basename(w) for w in re.split(r"[\s;|&()<>{}`$'\"]+", cmd or "") if w]
    if any(w in _TEXT_PRODUCERS for w in words):
        return True
    # Fable round 3, finding 1: `python3 - IMG <<'EOF' ... EOF` is inline code exactly like
    # `python3 -c`: the program is the heredoc body, so it prints whatever it is told to.
    return any(_INLINE_INTERPRETER.match(w) for w in words) and \
        (any(w in ("-c", "-e", "-E", "--eval", "-Command", "-") for w in words) or "<<" in cmd)


def _admitted_producer(cmd: str) -> bool:
    """May this command's output be read as a measurement?

    It must be a command (not file bodies), not a text producer, and segmentable by evidence's
    scanner (Fable round 3, finding 1): a heredoc, `$(...)`, backticks or a lone `&` make
    `_segments` refuse the command, so nobody can say which program printed the line. The
    evidence layer refuses those shapes for observations; the judge now refuses them as
    measurement producers too, which can only make a coverage claim abstain.
    """
    return bool(cmd) and _segments(cmd) is not None and not _text_producer(cmd)


_MEASURE_LINE_CAP = MEASURE_LINE_CAP   # Evidence.measured_fractions keeps this many characters


def _measurement_names(m: tuple, path: str | None) -> bool:
    """Does measurement `m` = (fraction, line, command) speak to `path`?

    A line that names absolute paths decides by itself: it names the subject exactly or it is
    about something else. A line that names none borrows its command's operand, but only when the
    command names the subject exactly and no OTHER path of the same kind (same extension):
    `measure /x/first.png /x/second.png` printing two bare "coverage N%" lines cannot say which
    line is which, and joining both let second.png's 53% contradict first.png (inherited from
    364be5d; abstains now). `python3 /opt/measure.py /x/page.png` still joins.
    """
    if not path or not os.path.isabs(path):
        return False
    path = os.path.normpath(path)
    line = m[1] or ""
    in_line = _named_paths(line)
    if len(line) >= _MEASURE_LINE_CAP and in_line and line.rstrip(".,;:").endswith(in_line[-1]):
        # Evidence keeps only the first MEASURE_LINE_CAP characters of a measurement line, so a path that
        # runs to the cut may be the prefix of another name (/x/first.png of /x/first.png.bak).
        in_line = in_line[:-1] + ["\0truncated"]
    if in_line:
        return path in in_line
    in_cmd = set(_named_paths(m[2] if len(m) > 2 else ""))
    if path not in in_cmd:
        return False
    ext = os.path.splitext(path)[1].lower()
    return not any(os.path.splitext(p)[1].lower() == ext for p in in_cmd - {path})


def _same_check(e: dict, standing: dict) -> bool:
    """Is event <e> the failing check <standing> run again?

    Codex's minimum for re-run repair (6dc1938, N1): a KNOWN, MATCHING working folder and the
    COMPLETE, LITERAL command, otherwise abstain. Identical text from an unknown folder is not an
    identical check (`python3 -mcheck /x/T` loads a different local module in another folder, M1);
    collapsing whitespace equates different quoted arguments (M2); a command the ledger had to cut
    may differ after the cut (M3). RETIRED (explicitly): every re-run repair with a folder unknown,
    including all-absolute ones, now abstains (`repair-unbound`). Hermes's terminal tool does not pass
    the folder to the hook, so on a live session a failed check is cleared only by a recorded write
    to the exact target.
    """
    a, b = e.get("cwd"), standing.get("cwd")
    if not (a and b) or os.path.normpath(a) != os.path.normpath(b):
        return False
    # Codex 4ea2e11: the folder must be complete too. The ledger keeps at most _LEDGER_CWD_CAP
    # characters; two different long folders share that prefix. A flagged or possibly cut folder
    # (at the cap, e.g. from a ledger written before the flag existed) never repairs.
    if e.get("cwd_cut") or standing.get("cwd_cut"):
        return False
    if len(a) >= _LEDGER_CWD_CAP or len(b) >= _LEDGER_CWD_CAP:
        return False
    if e.get("cut") or standing.get("cut"):
        return False
    ca, cb = e.get("cmd") or "", standing.get("cmd") or ""
    if len(ca) >= _LEDGER_COMMAND_CAP or len(cb) >= _LEDGER_COMMAND_CAP:
        return False                              # may have been cut by the ledger
    return ca == cb


# ledger.py stores at most this many characters of a command (see post_tool_call).
_LEDGER_COMMAND_CAP = 2000
_LEDGER_CWD_CAP = 1000                            # ledger.py _CWD_CAP


def _judge_kind(claim: Claim, ev: Evidence, path: str | None) -> Verdict:
    """The single-subject kind branches. Callers apply hedge and scope admission first."""
    # ---- coverage: a measured percentage can contradict an extent claim (case #7) ----
    if claim.kind == "coverage":
        taken = ev.measured_fractions()
        # A measurement must come from a command, and not from one that reproduces text
        # (round-2 finding 8). Without a producing command there is nothing to check.
        measured = [m for m in taken if len(m) > 2 and _admitted_producer(m[2])]
        if not measured:
            return Verdict("UNVERIFIABLE", "outside-session",
                           "no measurement was taken in this session"
                           + (f" ({len(taken)} quoted/printed percentage line(s) not admitted)"
                              if taken else ""))
        # Subject join: a measurement only speaks to the claim it names. An unrelated
        # second.png at 53% must not contradict first.png at 100%. Round-2 finding 8: the
        # join is on the EXACT absolute subject path, named in the measurement line or its
        # producing command — a basename (other/first.png for first.png) is another file,
        # and a claim with no resolvable subject path cannot be joined to any measurement.
        # NARROWED: unjoined measurements no longer judge a subjectless claim ("The poster
        # is full-page") either way; `_names_target` is False without an absolute path, so
        # it abstains (measurement-not-joined).
        joined = [m for m in measured if _measurement_names(m, path)]
        if not joined:
            return Verdict("UNVERIFIABLE", "measurement-not-joined",
                           f"{len(measured)} measurement(s) taken, none names "
                           + (path if path and os.path.isabs(path)
                              else "an absolute subject path (the claim names none)"))
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
        if listing is None or (path and not listing.covers(path)):
            return Verdict("UNVERIFIABLE", "search-scope",
                           ev.scope_report(parent or path or "/"))
        # A covered scope is necessary, not sufficient (R4): we must have SEEN
        # what the listing saw. Entries captured -> presence contradicts,
        # omission backs the absence; no captured output -> cannot prove.
        entries = ev.entries_of(listing)
        if entries is None:
            return Verdict("UNVERIFIABLE", "listing-unobserved",
                           f"{listing.command[:60]} ran but its output was not captured — "
                           "a listing is not an observation of absence")
        name = os.path.basename(path or "")
        if name and name in entries:
            return Verdict("CONTRADICTED", "listed-present",
                           f"{name} appeared in the listing of {listing.root}")
        return Verdict("BACKED", "absence-established",
                       f"absence established inside {listing.root} ({len(entries)} entries seen)")

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
        if listing is None or not listing.covers(entity):
            # A listing a later command may have made stale cannot vouch that nothing newer
            # appeared (definitions pass, 2026-11-11: `ls` then `make build` was BACKED).
            return Verdict("UNVERIFIABLE", "outside-session",
                           "no current listing covers it, so 'current' was never checked")
        return Verdict("BACKED", "newest-in-scope",
                       f"no newer sibling of {os.path.basename(entity)} under {listing.root}")

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
            return (Verdict("BACKED", "listed-this-session", path) if listing and listing.covers(path)
                    else Verdict("UNVERIFIABLE", "outside-session", f"{path} exists but was not touched"))
        if path:
            listing = ev.searched_for(os.path.dirname(path))
            entries = ev.entries_of(listing) if listing and listing.covers(path) else None
            if entries is not None and os.path.basename(path) not in entries:
                # Contradicted only by what the listing was SEEN to print, as for absence; an
                # uncaptured listing is no observation (definitions pass, 2026-11-11).
                return Verdict("CONTRADICTED", "artifact-missing", f"absent inside {listing.root}")
            return Verdict("UNBACKED", "artifact-missing",
                           f"nothing at {path} and no write this session")
        return Verdict("UNVERIFIABLE", "outside-session", "no artifact identified")

    # ---- completion ----
    # If a command that NAMES this subject came back non-ok, the claim is contradicted by the
    # session's own later evidence — "I fixed it" followed by an error on the same thing.
    if path and SUCCESS.search(claim.text):
        subject_tokens = {path, os.path.basename(path)}
        # Lifecycle: an error repaired LATER is not a standing failure — judge the
        # last event, not any failure.
        #
        # A command is related to the subject if it mentions the path or basename at all,
        # but only a command that names the target by its EXACT absolute path (or a path
        # inside it) is BOUND to it (`_names_target`).
        #   - A bound failure stands until repaired, and a standing one contradicts.
        #   - An unbound failure (`check OTHER/report.md`, `check report.md.bak`, a relative
        #     `grep ... report.md` run from an unrecorded cwd) names another file or an
        #     unknown one. It used to contradict (round-2 finding 7: the old comment said the
        #     loose join "can only withhold a favorable verdict" — it accused). It now only
        #     withholds: the claim abstains (failure-unbound) unless an exact-path write
        #     to the target follows it.
        # A REPAIR is bound strictly (Codex C3, fdb8f87): admitted repairs are only
        #   - an exact-normalized-path write to the target (round-3, unchanged), or
        #   - the identical failing command re-run and succeeding. Only a bound failure can
        #     stand, so an admitted re-run names the target by absolute path: a re-run of a
        #     relative check after `cd` elsewhere (round-2 finding 6) repairs nothing.
        # NARROWED favorable branch: any OTHER successful command that merely names the
        # subject no longer repairs; it makes the failure's standing unknown, so the
        # claim abstains (UNVERIFIABLE / repair-unbound) instead of being BACKED.
        # NARROWED unfavorable branch: an unbound failure abstains instead of contradicting.
        standing = None            # the bound failing command not yet repaired
        unbound_success = None     # a later success naming the subject that is no rerun
        unbound_failure = None     # a failure related to the subject but not bound to it
        result_exit = None         # a non-ok result verb (grep/diff/test ...): exit 1 is a result
        stream = ev.events or [{"kind": "command", "cmd": c, "ok": False}
                               for c in ev.commands_for_error()]   # legacy: no event order kept
        for e in stream:
            if e["kind"] == "command":
                if not any(tok and tok in e["cmd"] for tok in subject_tokens):
                    continue
                if not e.get("ok"):
                    if not _names_target(e["cmd"], path, inside=True):
                        unbound_failure = e
                    elif _exit_may_be_result(e["cmd"]):
                        result_exit = e            # neither failure nor success (finding 2)
                    else:
                        standing, unbound_success = e, None
                elif standing is None:
                    pass                           # nothing standing to repair
                elif _same_check(e, standing):
                    standing, unbound_success = None, None
                else:
                    unbound_success = e            # names the subject, repairs nothing proven
            elif e["kind"] == "write" and e.get("path") and \
                    os.path.normpath(e["path"]) == os.path.normpath(path):
                # Writes join on the exact normalized target identity — a substring
                # or basename match lets /other/report.md or report.md.bak pose as
                # a repair of report.md and cancel a standing failure (round-3).
                standing, unbound_success, unbound_failure = None, None, None
                result_exit = None
        if unbound_success is not None:
            return Verdict("UNVERIFIABLE", "repair-unbound",
                           f"a command on this subject failed ({standing['cmd'][:50]}); the later "
                           f"success ({unbound_success['cmd'][:50]}) is not that check re-run "
                           "or a write to the target, so the failure's standing is unknown")
        if standing is not None:
            return Verdict("CONTRADICTED", "later-error",
                           f"the last command on this subject failed: {standing['cmd'][:70]}")
        if unbound_failure is not None:
            return Verdict("UNVERIFIABLE", "failure-unbound",
                           f"a related command failed ({unbound_failure['cmd'][:50]}) but does not "
                           f"name {path} by its absolute path, so it neither contradicts nor "
                           "can be ruled out")
        if result_exit is not None:
            return Verdict("UNVERIFIABLE", "exit-is-result",
                           f"a check on this subject returned non-zero ({result_exit['cmd'][:50]}); "
                           "for grep/diff/cmp/test that is a result (no match, differs, false), "
                           "not an error, and the record cannot say which")
    if path and path in ev.mutations and ev.mutations[path].get("exists"):
        return Verdict("BACKED", "written-this-session", path)
    if path and ev.stat(path).get("exists"):
        return Verdict("UNVERIFIABLE", "outside-session",
                       f"{path} exists but the session did not touch it")
    if not path:
        return Verdict("UNBACKED", "no-evidence", "no artifact the session touched")
    return Verdict("UNBACKED", "artifact-missing", f"nothing at {path} and no write this session")

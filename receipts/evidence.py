"""Evidence: what the session can be held to.

Built from the ledger (real sessions) or injected (fixtures). The injectable form is the important
one: the eight acceptance cases are synthetic sessions, and a verdict engine that can only read a
live ledger cannot be tested against a sealed set.

Three kinds of evidence, and they are not interchangeable:

    mutations  a file whose stat() changed during the session   -> proves work ON that file
    listings   a command that ENUMERATED a directory or tree    -> the only thing that can prove
                                                                   something ABSENT, and only within
                                                                   the scope it actually covered
    commands   any other command that ran                       -> proves it ran, not that it worked

A path named in a command's output is never evidence. That rule is why `listings` is separate from
`commands`: absence claims live or die on scope, so the scope has to be recorded at the time.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable

# Commands that ENUMERATE. A match means "we looked in <root>", which is the only licence to claim
# absence — and only inside that root.
LISTING_PATTERNS = (
    re.compile(r"\bls\b(?P<args>[^|;&]*)"),
    re.compile(r"\bfind\s+(?P<args>[^|;&]+)"),
    re.compile(r"\bgrep\s+-[a-zA-Z]*r[a-zA-Z]*\s+(?P<args>[^|;&]+)"),
    re.compile(r"\btree\b(?P<args>[^|;&]*)"),
    re.compile(r"\bdir\b(?P<args>[^|;&]*)"),
)

# Arguments that are not paths.
_FLAGS = re.compile(r"^-{1,2}[A-Za-z0-9_-]+$")

# A listing only counts if the listing command STARTS a shell segment. `echo "ls /x"` matches
# \bls\b inside the quoted string — printing a listing is not running one (R4).
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[|;]")
_NAME_FILTER = re.compile(r"-i?name\s+(\S+)")
_MAXDEPTH = re.compile(r"-maxdepth\s+(\d+)")
_RECURSIVE_LS = re.compile(r"-[a-zA-Z]*R")
_OTHER_FIND_PRED = re.compile(r"-(type|perm|size|mtime|newer|empty|user|group)\b")


def _paths_in(args: str) -> list[str]:
    """Absolute paths only. A relative path in a listing command is relative to a CWD we never
    recorded, and pretending otherwise is how "." came to mean everywhere."""
    out = []
    for tok in re.split(r"\s+", args.strip()):
        tok = tok.strip("'\"")
        if not tok or _FLAGS.match(tok) or tok in ("|", "&&", ";"):
            continue
        if tok.startswith("-"):
            continue
        if os.path.isabs(tok):
            out.append(os.path.normpath(tok))
    return out


def _listings_in(cmd: str) -> list[tuple[str, str, int | None, str | None, bool]]:
    """(root, command, max_depth, name_filter, complete) for each EXECUTED listing segment.

    Execution means the enumerating verb leads its own pipeline segment — an `ls` inside an
    echo/printf/$(...) is a string, not an enumeration. `complete` is False when a pipe follows
    the listing (head/grep/transform means the observed output cannot prove absence) or when
    find carries filtering predicates other than -name (which is tracked separately).
    """
    out = []
    segments = _SEGMENT_SPLIT.split(cmd)
    seps = re.findall(_SEGMENT_SPLIT, cmd)
    for i, seg in enumerate(segments):
        toks = seg.strip().split(None, 1)
        if not toks:
            continue
        verb, args = toks[0].strip("'\""), toks[1] if len(toks) > 1 else ""
        is_verb = verb in ("ls", "dir", "tree") or verb == "find" or verb == "grep"
        if not is_verb:
            continue
        if verb == "grep" and not re.match(r"-[a-zA-Z]*r", args.split()[0] if args.split() else ""):
            continue
        # only a `|` pipe transforms this listing's output; `;`, `&&`, `||` do not
        complete = not (i < len(seps) and seps[i] == "|")
        max_depth: int | None = None
        name_filter: str | None = None
        if verb in ("ls", "dir"):
            max_depth = None if _RECURSIVE_LS.search(args) else 1
        elif verb == "find":
            m = _MAXDEPTH.search(args)
            max_depth = int(m.group(1)) if m else None
            nf = _NAME_FILTER.search(args)
            name_filter = nf.group(1).strip("'\"") if nf else None
            if _OTHER_FIND_PRED.search(args):
                complete = False
        for root in _paths_in(args):
            out.append((root, seg.strip(), max_depth, name_filter, complete))
    return out


import fnmatch as _fnmatch


@dataclass
class Listing:
    """A directory or tree the session actually enumerated — bound to outcome and content."""
    root: str
    command: str
    ok: bool = True                 # the record that produced it actually succeeded (R4)
    complete: bool = True           # output not truncated/filtered downstream (R4)
    max_depth: int | None = None    # ls=1 unless -R; find=unbounded unless -maxdepth
    name_filter: str | None = None  # find -name/-iname pattern, if any

    def covers(self, path: str) -> bool:
        """Was <path> inside the scope this listing looked at?

        Only an ABSOLUTE root can licence anything. A relative root means the command's working
        directory at that moment, which the ledger does not record — so it covers nothing. Treating
        "." as "everywhere" produced three false CONTRADICTED verdicts on a real session
        ("absent inside ."), which is the worst failure this plugin can have.

        Depth binds too (R4): a flat `ls /x` saw /x's children, not /x/sub's — so it cannot
        prove anything about deeper paths.
        """
        root = os.path.normpath(self.root or "")
        target = os.path.normpath(path or "")
        if not os.path.isabs(root):
            return False
        if root != os.sep and not (target == root or target.startswith(root + os.sep)):
            return False
        rel = os.path.relpath(target, root)
        depth = 0 if rel == os.curdir else len(rel.split(os.sep))
        if self.name_filter and depth >= 1 and not _fnmatch.fnmatch(
                os.path.basename(target), self.name_filter):
            return False                    # a name-filtered enumeration can't see this name
        if self.max_depth is not None:
            if rel.startswith(".."):
                return False
            if depth > self.max_depth:
                return False                # deeper than the enumeration reached
        return True


@dataclass
class Evidence:
    mutations: dict[str, dict] = field(default_factory=dict)   # path -> FINAL after-stat
    # Mutations whose before-state was never captured (exists: None). Recorded for
    # traceability but never counted as observed writes — a creation cannot be
    # certified without a captured before-state (R1).
    incomplete_mutations: list[dict] = field(default_factory=list)
    listings: list[Listing] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)     # every command, in order
    failed_commands: list[str] = field(default_factory=list)  # those that did not return ok
    # Ordered command events with ok flags — lifecycle is the point: an error that a
    # later successful command repaired is not a standing failure (R3).
    command_events: list[dict] = field(default_factory=list)  # {cmd, ok} in run order
    # Writes + commands in one ordered stream — a failure answered by a write repair is
    # repaired, not standing (R3).
    events: list[dict] = field(default_factory=list)  # {kind: write|command, ...}
    # Records that show the session LOOKED at something (search/read/inspect tools, listing
    # commands). A hedge needs one to mean anything — an unobserved "I could not verify"
    # asserts an attempt no evidence supports (R5).
    observations: list[str] = field(default_factory=list)
    # Tool OUTPUT, read from the host's transcript at session end — never copied into our own store.
    # A digest we wrote would be a second place for secrets to land; this is a read of what the host
    # already keeps.
    tool_outputs: list[dict] = field(default_factory=list)    # {command|tool, output}
    # Optional filesystem view, for fixtures. When None, real stat() is used.
    fs: dict[str, dict] | None = None

    def __post_init__(self):
        self._entries_cache: dict[int, frozenset | None] = {}

    # ------------------------------------------------------------------ lookups
    def commands_for_error(self) -> list[str]:
        """Commands that ran and did NOT come back ok. Order preserved: 'later' means later."""
        return [c for c in (self.failed_commands or [])]

    def stat(self, path: str) -> dict:
        if self.fs is not None:
            return self.fs.get(os.path.normpath(path), {"exists": False})
        try:
            st = os.stat(path)
            return {"exists": True, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
        except (OSError, ValueError):
            return {"exists": False}

    def is_dir(self, path: str) -> bool:
        if self.fs is not None:
            return bool((self.fs.get(os.path.normpath(path)) or {}).get("dir"))
        try:
            return os.path.isdir(path)
        except OSError:
            return False

    def entity_of(self, path: str) -> str:
        """What the claim is actually about. 'X is current' compares X with X's siblings — so a
        claim naming a file inside a build directory is a claim about that build directory."""
        return path if self.is_dir(path) else os.path.dirname(os.path.normpath(path))

    def siblings_newer_than(self, path: str) -> list[str]:
        """Other entries in path's parent with a newer mtime. The 'is this current?' test."""
        entity = self.entity_of(path)
        parent = os.path.dirname(entity)
        mine = self.stat(entity)
        if not mine.get("exists"):
            return []
        if self.fs is not None:
            cands = [p for p in self.fs if os.path.dirname(os.path.normpath(p)) == parent]
        else:
            try:
                cands = [os.path.join(parent, n) for n in os.listdir(parent)]
            except OSError:
                return []
        newer = []
        for c in cands:
            c = os.path.normpath(c)
            if c == entity:
                continue
            st = self.stat(c)
            if st.get("exists") and st.get("mtime_ns", 0) > mine.get("mtime_ns", 0):
                newer.append(c)
        return sorted(newer)

    _OBSERVE_TOOLS = re.compile(
        r"search|find|grep|ls|dir|tree|cat|read|rg|query|lookup|fetch|curl|"
        r"scan|inspect|stat|wc|head|tail", re.I)

    def searched_for(self, path: str) -> Listing | None:
        """A listing that can actually PROVE something about this path:
        covers it, executed for real, succeeded, and was not truncated/filtered
        downstream. Returns the first qualifying listing, or None — callers use
        scope_report() to say WHY when they emit UNVERIFIABLE."""
        for lst in self.listings:
            if lst.ok and lst.complete and lst.covers(path):
                return lst
        return None

    def scope_report(self, path: str) -> str:
        """Why no listing can prove anything about <path> — for UNVERIFIABLE details."""
        covering = [l for l in self.listings if l.covers(path)]
        if not self.listings:
            return "no listing ran this session"
        if covering:
            l = covering[0]
            if not l.ok:
                return f"listing of {l.root} failed ({l.command[:50]})"
            if not l.complete:
                return f"listing of {l.root} was truncated/filtered ({l.command[:50]})"
        ran = ", ".join(sorted({l.root for l in self.listings})[:2])
        return f"searched {ran}, outside its scope or depth: {path}"

    def entries_of(self, lst: Listing) -> frozenset | None:
        """Basenames the listing actually printed, if its output was captured.

        An absence claim needs this: a covered scope whose contents we never
        SAW cannot prove anything is absent (R4). Parsed lazily from
        tool_outputs matched on the listing's command.
        """
        key = id(lst)
        if key in self._entries_cache:
            return self._entries_cache[key]
        entries: set[str] = set()
        found = False
        # R4 join rule: a transcript output binds to this listing when the
        # listing's segment text is an exact pipeline component of the joined
        # originating command — never a substring guess (`ls /a` output must
        # not alias to `ls /ab`, and a plain `ls /a` must not claim
        # `ls /a | grep x`'s filtered output as its own). Unjoined outputs
        # (command=None) bind to nothing.
        verb = (lst.command.split() or [""])[0].strip("'\"") if lst.command else ""
        for item in self.tool_outputs:
            oc = (item.get("command") or "").strip()
            if not oc:
                continue
            segments = [s.strip() for s in _SEGMENT_SPLIT.split(oc)]
            if lst.command.strip() not in segments:
                continue
            found = True
            for line in (item.get("output") or "").splitlines():
                line = line.strip()
                if (not line
                        or line.startswith(("total ", "Permission denied", "{", '"'))):
                    continue
                if verb in ("find", "tree"):
                    entries.add(os.path.basename(line.rstrip("/")))
                elif verb == "grep":
                    entries.add(os.path.basename(line.split(":", 1)[0].rstrip("/")))
                elif " -> " in line:                       # ls -l symlink row
                    entries.add(os.path.basename(line.split(" -> ", 1)[0].split()[-1].rstrip("/")))
                elif re.match(r"^[-dlpscbx][-rwxsStT]{9}", line):  # ls -l row
                    entries.add(os.path.basename(line.split()[-1].rstrip("/")))
                else:                                      # plain ls: every token is a name
                    for tok in line.split():
                        entries.add(os.path.basename(tok.rstrip("/")))
        self._entries_cache[key] = frozenset(entries) if found else None
        return self._entries_cache[key]

    def has_observation(self, subject: str | None = None) -> bool:
        """Did the session actually LOOK at the claim's scope? (R5)

        A hedge asserts an attempt; this is the attempt's evidence. Unscoped
        (subject=None): any real observation counts. Scoped: only an
        observation naming the subject, a successful listing that covered
        AND saw it, or a bound observe-tool command naming it. Echo output,
        failed commands, unrelated listings and unbound outputs are not an
        attempt on this subject — the residual cases Codex carried open.
        """
        if subject is None:
            return bool(self.observations or self.listings
                        or [o for o in self.tool_outputs if o.get("command")])
        keys = {t for t in (subject, os.path.basename(subject)) if t}
        for ob in self.observations:
            if any(k in ob for k in keys):
                return True
        for l in self.listings:
            if l.ok and l.covers(subject) and self.entries_of(l) is not None:
                return True
        base = os.path.basename(subject)
        if base and any(base in (self.entries_of(l) or frozenset())
                        for l in self.listings if l.ok):
            return True   # a listing that SAW the named file observed it
        for item in self.tool_outputs:
            cmd = (item.get("command") or "")
            toks = cmd.split()
            if toks and self._OBSERVE_TOOLS.search(toks[0].strip("'\"")) \
                    and any(k in cmd for k in keys):
                return True
        return False

    def listing_scope_covers(self, path: str) -> bool:
        return self.searched_for(path) is not None

    # ------------------------------------------------------------------ builders
    @classmethod
    def from_ledger(cls, records: Iterable[dict]) -> "Evidence":
        ev = cls()
        for rec in records or []:
            for mut in rec.get("mutations") or []:
                p = mut.get("path")
                if not p:
                    continue
                if mut.get("before") is not None and mut["before"].get("exists") is None:
                    ev.incomplete_mutations.append(mut)
                else:
                    ev.mutations[os.path.normpath(p)] = mut.get("after") or {}
                    ev.events.append({"kind": "write", "path": os.path.normpath(p),
                                      "exists": (mut.get("after") or {}).get("exists")})
            tool = rec.get("tool") or ""
            cmd = rec.get("command")
            ok = rec.get("status") in (None, "ok", "success")
            if ok and (cls._OBSERVE_TOOLS.search(tool) or (
                    cmd and cls._OBSERVE_TOOLS.search(cmd))):
                # R5: a failed observe call is a non-observation — it cannot
                # back "I searched and could not verify".
                ev.observations.append((tool or cmd or "").strip()[:120])
            if not cmd:
                continue
            ev.command_events.append({"cmd": cmd, "ok": ok})
            ev.events.append({"kind": "command", "cmd": cmd, "ok": ok})
            ev.commands.append(cmd)
            if not ok:
                ev.failed_commands.append(cmd)
            for root, seg, depth, name_filter, complete in _listings_in(cmd):
                ev.listings.append(Listing(root=root, command=seg[:200], ok=ok,
                                           complete=complete, max_depth=depth,
                                           name_filter=name_filter))
        return ev

    def measured_fractions(self) -> list[tuple[float, str]]:
        """Coverage measurements the session actually took, as 0..1 fractions.

        Deliberately narrow. A first version took ANY percentage in ANY tool output and produced a
        false CONTRADICTED against a real session by reading a "Loading weights: 0%" progress bar.
        Percentages are everywhere: progress bars, memory use, CI pass rates, and the text of files
        the session merely read. So a line qualifies only if it looks like a MEASUREMENT of extent —
        it must name what was measured — and not like a progress render.
        """
        import re as _re
        MEASURE_WORDS = _re.compile(
            r"\b(coverage|ink|bbox|margins?|dpi|filled|whitespace|white space|area|"
            r"page ?fill|occupied|bleed)\b", _re.I)
        PROGRESS = _re.compile(r"(\d+%\||\|[#=]+\||it/s|Loading|\bETA\b|^\s*\d+%\s*$)", _re.I)
        PCT = _re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
        out = []
        for item in self.tool_outputs:
            if (item.get("tool") or "").lower() in ("read_file", "write_file", "patch"):
                continue          # file BODIES are not measurements — this read its own fixtures back
            for line in (item.get("output") or "").splitlines():
                if PROGRESS.search(line) or not MEASURE_WORDS.search(line):
                    continue
                if any(ch in line for ch in '{}"') or "\"output\":" in line or "|" in line:
                    continue      # quoted/report text, not a measurement
                for m in PCT.finditer(line):
                    try:
                        val = float(m.group(1)) / 100.0
                    except ValueError:
                        continue
                    if 0.0 <= val <= 1.0:
                        # Carry the producing command too — the subject join happens
                        # on command+line, not the bare number (R3c).
                        out.append((val, line.strip()[:100], item.get("command") or ""))
        return out

    @classmethod
    def from_session(cls, session_id: str, records: Iterable[dict] | None = None,
                     db_path: str | None = None) -> "Evidence":
        """Evidence for a REAL session: ledger for what changed, transcript for what was printed.

        The transcript read is bounded and fails open — an unreadable store yields no output, which
        produces UNVERIFIABLE rather than a confident wrong answer.
        """
        ev = cls.from_ledger(records or [])
        try:
            from . import transcript
            ev.tool_outputs = transcript.read_tool_outputs(session_id, db_path)
        except Exception:
            ev.tool_outputs = []
        return ev

    @classmethod
    def from_fixture(cls, data: dict) -> "Evidence":
        ev = cls(fs={os.path.normpath(k): v for k, v in (data.get("filesystem") or {}).items()})
        for item in data.get("tool_outputs") or []:
            ev.tool_outputs.append({"command": item.get("command"),
                                    "output": item.get("output") or "",
                                    "tool": item.get("tool") or ""})
        for rec in data.get("ledger") or []:
            for mut in rec.get("mutations") or []:
                p = mut.get("path")
                if not p:
                    continue
                # Incomplete == explicit exists: None (unobserved pre-state). Missing
                # before = legacy record, stays a normal mutation.
                if mut.get("before") is not None and mut["before"].get("exists") is None:
                    ev.incomplete_mutations.append(mut)
                else:
                    ev.mutations[os.path.normpath(p)] = mut.get("after") or {}
                    ev.events.append({"kind": "write", "path": os.path.normpath(p),
                                      "exists": (mut.get("after") or {}).get("exists")})
            tool = rec.get("tool") or ""
            cmd = rec.get("command")
            ok = rec.get("status") in (None, "ok", "success")
            if ok and (cls._OBSERVE_TOOLS.search(tool) or (
                    cmd and cls._OBSERVE_TOOLS.search(cmd))):
                # R5: failed observe calls are not observations (fixture parity).
                ev.observations.append((tool or cmd or "").strip()[:120])
            if not cmd:
                continue
            ev.command_events.append({"cmd": cmd, "ok": ok})
            ev.events.append({"kind": "command", "cmd": cmd, "ok": ok})
            ev.commands.append(cmd)
            if not ok:
                ev.failed_commands.append(cmd)
            for root, seg, depth, name_filter, complete in _listings_in(cmd):
                ev.listings.append(Listing(root=root, command=seg[:200], ok=ok,
                                           complete=complete, max_depth=depth,
                                           name_filter=name_filter))
        return ev

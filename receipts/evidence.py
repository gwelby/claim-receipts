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


@dataclass
class Listing:
    """A directory or tree the session actually enumerated."""
    root: str
    command: str

    def covers(self, path: str) -> bool:
        """Was <path> inside the scope this listing looked at?

        Only an ABSOLUTE root can licence anything. A relative root means the command's working
        directory at that moment, which the ledger does not record — so it covers nothing. Treating
        "." as "everywhere" produced three false CONTRADICTED verdicts on a real session
        ("absent inside ."), which is the worst failure this plugin can have.
        """
        root = os.path.normpath(self.root or "")
        target = os.path.normpath(path or "")
        if root == os.sep:
            return True
        if not os.path.isabs(root):
            return False
        return target == root or target.startswith(root + os.sep)


@dataclass
class Evidence:
    mutations: dict[str, dict] = field(default_factory=dict)   # path -> after-stat
    listings: list[Listing] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)     # every command, in order
    failed_commands: list[str] = field(default_factory=list)  # those that did not return ok
    # Tool OUTPUT, read from the host's transcript at session end — never copied into our own store.
    # A digest we wrote would be a second place for secrets to land; this is a read of what the host
    # already keeps.
    tool_outputs: list[dict] = field(default_factory=list)    # {command|tool, output}
    # Optional filesystem view, for fixtures. When None, real stat() is used.
    fs: dict[str, dict] | None = None

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

    def searched_for(self, path: str) -> Listing | None:
        """A listing whose scope covers this path, if any ran this session."""
        for lst in self.listings:
            if lst.covers(path):
                return lst
        return None

    def listing_scope_covers(self, path: str) -> bool:
        return self.searched_for(path) is not None

    # ------------------------------------------------------------------ builders
    @classmethod
    def from_ledger(cls, records: Iterable[dict]) -> "Evidence":
        ev = cls()
        for rec in records or []:
            for mut in rec.get("mutations") or []:
                p = mut.get("path")
                if p:
                    ev.mutations[os.path.normpath(p)] = mut.get("after") or {}
            cmd = rec.get("command")
            if not cmd:
                continue
            ev.commands.append(cmd)
            if rec.get("status") not in (None, "ok", "success"):
                ev.failed_commands.append(cmd)
            for pat in LISTING_PATTERNS:
                m = pat.search(cmd)
                if not m:
                    continue
                for root in _paths_in(m.group("args") or ""):
                    ev.listings.append(Listing(root=root, command=cmd.strip()[:200]))
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
                        out.append((val, line.strip()[:100]))
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
                if p:
                    ev.mutations[os.path.normpath(p)] = mut.get("after") or {}
            cmd = rec.get("command")
            if not cmd:
                continue
            ev.commands.append(cmd)
            if rec.get("status") not in (None, "ok", "success"):
                ev.failed_commands.append(cmd)
            for pat in LISTING_PATTERNS:
                m = pat.search(cmd)
                if not m:
                    continue
                for root in _paths_in(m.group("args") or ""):
                    ev.listings.append(Listing(root=root, command=cmd.strip()[:200]))
        return ev

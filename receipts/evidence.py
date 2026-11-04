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
    out = []
    for tok in re.split(r"\s+", args.strip()):
        tok = tok.strip("'\"")
        if not tok or _FLAGS.match(tok) or tok in ("|", "&&", ";"):
            continue
        if tok.startswith("-"):
            continue
        if os.sep in tok or tok.startswith("."):
            out.append(os.path.normpath(tok))
    return out


@dataclass
class Listing:
    """A directory or tree the session actually enumerated."""
    root: str
    command: str

    def covers(self, path: str) -> bool:
        """Was <path> inside the scope this listing looked at?

        Prefix comparison on normalised paths, with a separator guard so /a/bc is not "inside" /a/b.
        """
        root = os.path.normpath(self.root or "/")
        target = os.path.normpath(path or "")
        if root in ("/", "."):
            return True
        return target == root or target.startswith(root + os.sep)


@dataclass
class Evidence:
    mutations: dict[str, dict] = field(default_factory=dict)   # path -> after-stat
    listings: list[Listing] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)     # every command, in order
    failed_commands: list[str] = field(default_factory=list)  # those that did not return ok
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

    @classmethod
    def from_fixture(cls, data: dict) -> "Evidence":
        ev = cls(fs={os.path.normpath(k): v for k, v in (data.get("filesystem") or {}).items()})
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

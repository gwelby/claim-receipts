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
import shlex
from dataclasses import dataclass, field
from typing import Iterable

# Commands that ENUMERATE. A match means "we looked in <root>", which is the only licence to claim
# absence — and only inside that root.
#
# C2 (Codex, fdb8f87): admission is a deliberately SMALL grammar, not a shell parser. Anything outside
# it either produces no listing at all (it did not provably execute) or a listing marked incomplete
# (it ran, but its output cannot prove absence). Abstention is the intended result for every shape
# this file does not explicitly understand.
_LISTING_VERBS = ("ls", "dir", "find", "grep", "tree")

# ls/dir option letters whose output is still a plain, complete, parseable enumeration. Everything
# else (-d lists the directory itself, -I/--hide/-B filter, -F/-p/-Q/-b/-m decorate or quote names,
# -s prefixes sizes, ...) makes the listing incomplete: it may still be shown, it may not prove absence.
_LS_OK_SHORT = set("1aAlCxRtrSUh")
_LS_OK_LONG = {"--all", "--almost-all"}
_LS_HIDDEN_SHORT = set("aA")

# Segments that print nothing on success, so a listing in the same command keeps sole ownership of
# the captured output. Any other co-segment may contribute lines, which would be merged into the
# listing's entries (the location/identity failure) — so its output is left unbound instead.
_SILENT_VERBS = {"cd", "true", ":", "export", "set", "unset", "umask"}

# Characters that make an operand's real value unknowable without running the shell's expansions.
_EXPANSION = re.compile(r"[$`*?\[\]{}~]")

# Exact verbs that LOOK at something. Exact token equality — never a regex search over the verb or
# the whole command text (`false` contains `ls`; `mkdir /x/details` contains `dir` and `tail`).
_OBSERVE_VERBS = {"ls", "dir", "tree", "find", "grep", "rg", "cat", "head", "tail", "wc", "stat",
                  "curl"}
# Non-terminal tool NAMES that observe, matched on whole name parts ("web_search" -> search), not
# on substrings ("skills_list" is not "ls").
_OBSERVE_TOOL_WORDS = {"search", "find", "grep", "ls", "dir", "tree", "cat", "read", "rg", "query",
                       "lookup", "fetch", "curl", "scan", "inspect", "stat", "wc", "head", "tail"}
# Native tools whose call arguments name the exact path they read (carried by the transcript join).
_READ_TOOLS = {"read_file"}


def _ok(status) -> bool:
    return status in (None, "ok", "success")


def _tool_observes(tool: str) -> bool:
    return bool(tool) and tool != "terminal" and any(
        part in _OBSERVE_TOOL_WORDS for part in re.split(r"[^A-Za-z0-9]+", tool.lower()) if part)


@dataclass
class _Segment:
    text: str
    sep_after: str | None      # the operator that FOLLOWS this segment ("|", "&&", ";", ...)
    redirect: bool             # an unquoted < or > appears in it
    tokens: list[str]


def _segments(cmd: str) -> list[_Segment] | None:
    """Split a command into simple segments on UNQUOTED ; | || && & |& and newlines.

    Quote-aware (R4/C2): `printf '%s' 'note; ls /x'` is ONE printf segment; nothing inside the
    quotes executed. Returns None — no segment is trusted — for shapes this deliberately small
    scanner does not model: unbalanced quotes, subshells/grouping parentheses, backtick or $(...)
    command substitution, process substitution. None means "abstain", never "guess".
    """
    if not isinstance(cmd, str):
        return None
    raw: list[tuple[str, str | None, bool]] = []
    buf: list[str] = []
    quote: str | None = None
    redirect = False
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote == "'":
            buf.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if c == "`" or cmd.startswith("$(", i):
                return None                       # substitution executes even inside "..."
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 2
                continue
            if c == '"':
                quote = None
            i += 1
            continue
        if c == "\\":
            if i + 1 < n and cmd[i + 1] == "\n":   # line continuation
                i += 2
                continue
            buf.append(cmd[i:i + 2])
            i += 2
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c in "`()":
            return None
        if c == "#" and (not buf or buf[-1][-1:] in (" ", "\t")):
            break                                  # comment: the rest never executes
        if c in "<>" or (c == "&" and cmd.startswith("&>", i)):
            redirect = True
            buf.append(c)
            i += 1
            while i < n and cmd[i] in "<>&":
                buf.append(cmd[i])
                i += 1
            continue
        two = cmd[i:i + 2]
        if two in ("&&", "||", "|&", ";;"):
            sep, i = two, i + 2
        elif c in ";|&\n":
            sep, i = c, i + 1
        else:
            buf.append(c)
            i += 1
            continue
        raw.append(("".join(buf).strip(), sep, redirect))
        buf, redirect = [], False
    if quote:
        return None
    raw.append(("".join(buf).strip(), None, redirect))
    out = []
    for text, sep, red in raw:
        try:
            toks = shlex.split(text) if text else []
        except ValueError:
            return None
        out.append(_Segment(text=text, sep_after=sep, redirect=red, tokens=toks))
    return out


def _split_opts(args: list[str]) -> tuple[list[str], list[str]]:
    """(options, operands) for ls-like argv: options lead; `--` ends them."""
    opts, operands, ended = [], [], False
    for tok in args:
        if not ended and tok == "--":
            ended = True
        elif not ended and tok.startswith("-") and tok != "-":
            opts.append(tok)
        else:
            operands.append(tok)
    return opts, operands


def _abs_operand(tok: str) -> str | None:
    """An operand whose literal value is a known absolute path, else None.

    Only an ABSOLUTE root can licence anything: a relative path is relative to a CWD we never
    recorded. An operand needing expansion ($VAR, globs, ~) has no known value."""
    if not tok or _EXPANSION.search(tok) or not os.path.isabs(tok):
        return None
    return os.path.normpath(tok)


def _listing_of(seg: _Segment) -> list[dict]:
    """Listing descriptors for ONE executed segment (empty if it is not an admitted listing)."""
    if not seg.tokens or seg.tokens[0] not in _LISTING_VERBS:
        return []
    verb, args = seg.tokens[0], seg.tokens[1:]
    # only a `|` pipe transforms this listing's output; `;`, `&&`, `||` do not. A redirect sends it
    # somewhere we never read, so the captured output is not the listing's.
    complete = seg.sep_after not in ("|", "|&") and not seg.redirect
    fmt, hidden, max_depth, name_filter = "ls-cols", False, 1, None
    if verb in ("ls", "dir"):
        opts, operands = _split_opts(args)
        shorts = set("".join(o[1:] for o in opts if not o.startswith("--")))
        longs = {o for o in opts if o.startswith("--")}
        if not shorts <= _LS_OK_SHORT or not longs <= _LS_OK_LONG:
            complete = False
        hidden = bool(shorts & _LS_HIDDEN_SHORT) or bool(longs)
        max_depth = None if "R" in shorts else 1
        fmt = "ls-long" if "l" in shorts else ("ls-lines" if "1" in shorts else "ls-cols")
        if verb == "dir":
            fmt = "ls-long" if "l" in shorts else "ls-cols"
    elif verb == "find":
        operands = []
        rest = list(args)
        while rest and not rest[0].startswith("-") and rest[0] not in ("(", "!"):
            operands.append(rest.pop(0))
        fmt, hidden, max_depth = "find", True, None
        while rest:                         # admitted: -maxdepth N, -name/-iname P, -print
            tok = rest.pop(0)
            if tok == "-maxdepth" and rest and rest[0].isdigit():
                max_depth = int(rest.pop(0))
            elif tok in ("-name", "-iname") and rest and name_filter is None:
                name_filter = rest.pop(0)
            elif tok == "-print":
                continue
            else:                           # any other predicate/action filters or transforms
                complete = False
                break
    elif verb == "grep":
        opts, operands = _split_opts(args)
        if not opts or not re.match(r"-[a-zA-Z]*[rR]", opts[0]):
            return []
        operands = operands[1:]             # the first operand is the PATTERN, not a path
        fmt, hidden, max_depth = ("grep-l" if any("l" in o[1:] for o in opts
                                                  if not o.startswith("--")) else "grep"), True, None
        # RETIRED (C2): fdb8f87 let a `grep -r` omission back absence. grep prints MATCHING files
        # only, so its omission never proves a file absent; it may still show a file present.
        complete = False
    else:
        # RETIRED (C2): tree output (indented art) was basename-parsed with no location; it is no
        # longer parsed at all, so a tree listing is never an observation of absence or presence.
        opts, operands = _split_opts(args)
        hidden = any("a" in o[1:] for o in opts if not o.startswith("--"))
        if any(o != "-a" for o in opts):
            complete = False
        fmt, max_depth = "tree", None
    roots = [r for r in (_abs_operand(t) for t in operands) if r]
    # One operand only: with several, the output interleaves several scopes under headers and a
    # name seen under one would be attributed to all (the location failure). Not bindable.
    single = len(operands) == 1 and len(roots) == 1
    return [{"root": r, "verb": verb, "fmt": fmt, "complete": complete and single,
             "bindable": single, "max_depth": max_depth, "name_filter": name_filter,
             "shows_hidden": hidden} for r in roots]


def _listings_in(cmd: str) -> list[dict]:
    """Listing descriptors for each EXECUTED, admitted listing segment of a command.

    Execution means the enumerating verb leads its own UNQUOTED segment — an `ls` inside an
    echo/printf string is a string, not an enumeration, and a command this scanner cannot segment
    yields no listing at all.
    """
    segs = _segments(cmd)
    if not segs:
        return []
    out = []
    for idx, seg in enumerate(segs):
        for d in _listing_of(seg):
            d["segment"] = seg.text
            d["tokens"] = tuple(seg.tokens)
            d["seg_index"] = idx
            out.append(d)
    return out


def _observe_operands(cmd: str) -> list[tuple[str, list[str]]]:
    """(verb, operand tokens) for every executed segment whose verb is an exact observe verb."""
    out = []
    for seg in _segments(cmd) or []:
        if seg.tokens and seg.tokens[0] in _OBSERVE_VERBS:
            out.append((seg.tokens[0], [t for t in seg.tokens[1:] if not t.startswith("-")]))
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
    # C2: identity and coverage the listing actually had.
    shows_hidden: bool = True       # default ls omits dotfiles: it never observed them
    call_id: str | None = None      # the producing native call; outputs bind to THIS call only
    seq: int = 0                    # order among the session's listings: latest wins, never merged
    fmt: str = "ls-cols"            # output shape the parser admits (tree: none)
    bindable: bool = True           # single operand: output belongs to exactly one scope
    tokens: tuple = ()              # the segment's argv, for call-less (fixture) joins
    seg_index: int = 0

    def covers(self, path: str) -> bool:
        """Was <path> inside the scope this listing looked at?

        Only an ABSOLUTE root can licence anything. A relative root means the command's working
        directory at that moment, which the ledger does not record — so it covers nothing. Treating
        "." as "everywhere" produced three false CONTRADICTED verdicts on a real session
        ("absent inside ."), which is the worst failure this plugin can have.

        Depth binds too (R4): a flat `ls /x` saw /x's children, not /x/sub's — so it cannot
        prove anything about deeper paths. Hidden names bind (C2): `ls /x` without -a/-A never
        printed /x/.secret, so its omission says nothing about it.
        """
        root = os.path.normpath(self.root or "")
        target = os.path.normpath(path or "")
        if not os.path.isabs(root):
            return False
        if root != os.sep and not (target == root or target.startswith(root + os.sep)):
            return False
        rel = os.path.relpath(target, root)
        depth = 0 if rel == os.curdir else len(rel.split(os.sep))
        if depth and not self.shows_hidden and any(p.startswith(".") for p in rel.split(os.sep)):
            return False                    # default ls never prints dot-names
        if self.name_filter and depth >= 1 and not _fnmatch.fnmatch(
                os.path.basename(target), self.name_filter):
            return False                    # a name-filtered enumeration can't see this name
        if self.max_depth is not None:
            if rel.startswith(".."):
                return False
            if depth > self.max_depth:
                return False                # deeper than the enumeration reached
        return True


_LS_LONG_ROW = re.compile(r"^[-dlpscbx][-rwxsStT]{9}")
_ERROR_LINE = re.compile(r"^(ls|dir|find|tree|grep): |Permission denied|cannot open directory")


def _parse_entries(lst: Listing, output: str) -> frozenset | None:
    """Absolute, normalized paths printed by an admitted listing's captured output.

    Location is preserved (C2): ls names are joined to the directory they were printed under
    (the root, or the current `-R` section header); find/grep print full paths already. An error
    line means the enumeration was partial — the whole observation is then unusable (None).
    """
    root = os.path.normpath(lst.root)
    cur = root
    recursive = lst.fmt.startswith("ls") and lst.max_depth is None
    out: set[str] = set()
    for line in output.splitlines():
        st = line.strip()
        if not st:
            continue
        if _ERROR_LINE.search(st):
            return None
        if st.startswith(("{", '"')):
            continue                       # quoted/JSON text is not an entry
        names: list[str]
        if lst.fmt in ("find", "grep", "grep-l"):
            p = st if lst.fmt != "grep" else st.split(":", 1)[0]
            if os.path.isabs(p):
                out.add(os.path.normpath(p))
            continue
        if recursive and st.endswith(":") and os.path.isabs(st[:-1]):
            cur = os.path.normpath(st[:-1])
            continue
        if lst.fmt == "ls-long":
            if st.startswith("total "):
                continue
            if " -> " in st:                                   # ls -l symlink row
                names = [st.split(" -> ", 1)[0].split()[-1]]
            elif _LS_LONG_ROW.match(st):
                names = [st.split()[-1]]
            else:
                continue
        elif lst.fmt == "ls-lines":
            names = [st]                    # -1: one whole name per line
        else:
            names = st.split()              # columns: every token is a name
        for n in names:
            n = n.rstrip("/")
            if n:
                out.add(os.path.normpath(n if os.path.isabs(n) else os.path.join(cur, n)))
    return frozenset(out)


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
    # Structured observe-verb segments: {verb, operands, ok, call_id}. Scoped hedges need the exact
    # subject among the operands of a successful one (C2) — the strings above are for display.
    observed: list[dict] = field(default_factory=list)
    # Tool OUTPUT, read from the host's transcript at session end — never copied into our own store.
    # A digest we wrote would be a second place for secrets to land; this is a read of what the host
    # already keeps.
    tool_outputs: list[dict] = field(default_factory=list)    # {command|tool, output}
    # Optional filesystem view, for fixtures. When None, real stat() is used.
    fs: dict[str, dict] | None = None

    def __post_init__(self):
        self._entries_cache: dict[int, frozenset | None] = {}
        self._view_base: dict[int, "Listing"] = {}
        self._views: list["Listing"] = []

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

    # ------------------------------------------------------------------ listings (C2)
    def _latest_covering(self, path: str) -> Listing | None:
        """The NEWEST listing whose scope covers <path>, whatever its outcome.

        Call/order identity (C2): an older result is never merged with, or preferred over, a newer
        one. If the newest covering listing failed, was filtered, or was truncated, nothing older
        is substituted for it — the caller abstains."""
        for lst in reversed(self.listings):
            if lst.covers(path):
                return lst
        return None

    def _view(self, base: Listing, directory: str) -> Listing:
        """<base> seen as a listing OF <directory> (a directory inside base's scope).

        Location identity (C2): the judge compares a claimed basename against entries_of(listing).
        A recursive listing's entries must therefore be the children of the claimed parent
        directory — `find /r` printing /r/b/subject.md is not a sighting of /r/a/subject.md."""
        directory = os.path.normpath(directory)
        if directory == os.path.normpath(base.root):
            return base
        rel = os.path.relpath(directory, os.path.normpath(base.root))
        depth = 0 if rel == os.curdir else len(rel.split(os.sep))
        view = Listing(root=directory, command=base.command, ok=base.ok, complete=base.complete,
                       max_depth=None if base.max_depth is None else max(base.max_depth - depth, 0),
                       name_filter=base.name_filter, shows_hidden=base.shows_hidden,
                       call_id=base.call_id, seq=base.seq, fmt=base.fmt, bindable=base.bindable,
                       tokens=base.tokens, seg_index=base.seg_index)
        self._view_base[id(view)] = base
        self._views.append(view)          # keep it alive: ids must not be reused while cached
        return view

    def searched_for(self, path: str) -> Listing | None:
        """A listing that can actually PROVE something about this path:
        the NEWEST listing covering it, executed for real, succeeded, not
        truncated/filtered downstream, and not cut by the transcript reader.
        Returned as a view rooted at <path> so its entries are location-bound.
        None otherwise — callers use scope_report() to say WHY when they emit UNVERIFIABLE."""
        lst = self._latest_covering(path)
        if lst is None or not (lst.ok and lst.complete):
            return None
        if self._bound_output(lst) == "truncated":
            return None
        return self._view(lst, path)

    def scope_report(self, path: str) -> str:
        """Why no listing can prove anything about <path> — for UNVERIFIABLE details."""
        if not self.listings:
            return "no listing ran this session"
        l = self._latest_covering(path)
        if l is not None:
            if not l.ok:
                return f"listing of {l.root} failed ({l.command[:50]})"
            if not l.complete:
                return f"listing of {l.root} was truncated/filtered ({l.command[:50]})"
            if self._bound_output(l) == "truncated":
                return f"output of {l.command[:50]} was truncated before it was read"
        ran = ", ".join(sorted({l.root for l in self.listings})[:2])
        return f"searched {ran}, outside its scope, depth or visible names: {path}"

    def _bound_output(self, lst: Listing):
        """The captured output that belongs to THIS listing, or None / "truncated".

        Binding rules (C2):
          * a native listing binds only to the output of its own call (tool_call_id) — two runs of
            the same command text are two observations, never one merged set;
          * a call-less (fixture) listing binds by exact argv to exactly ONE output; ambiguity
            abstains;
          * every other segment of the producing command must be silent (cd, true, ...), or its
            printed lines would be read as this listing's entries;
          * an output the reader truncated, or that reports failure, observes nothing complete.
        """
        if not lst.bindable or lst.fmt == "tree":
            return None
        if lst.call_id:
            cands = [o for o in self.tool_outputs if o.get("call_id") == lst.call_id]
        else:
            cands = []
            for o in self.tool_outputs:
                segs = _segments(o.get("command") or "") or []
                if any(tuple(sg.tokens) == tuple(lst.tokens) for sg in segs):
                    cands.append(o)
        if len(cands) != 1:
            return None
        item = cands[0]
        segs = _segments(item.get("command") or "")
        if not segs:
            return None
        own = [i for i, sg in enumerate(segs) if tuple(sg.tokens) == tuple(lst.tokens)]
        if len(own) != 1:
            return None
        for i, sg in enumerate(segs):
            if i != own[0] and sg.tokens and sg.tokens[0] not in _SILENT_VERBS:
                return None
        if item.get("ok") is False:
            return None
        if item.get("truncated"):
            return "truncated"
        return item.get("output") or ""

    def _full_entries(self, base: Listing) -> frozenset | None:
        """Absolute paths the listing actually printed, location preserved; None if unobserved."""
        key = id(base)
        if key in self._entries_cache:
            return self._entries_cache[key]
        out = self._bound_output(base)
        result = None if out is None or out == "truncated" else _parse_entries(base, out)
        self._entries_cache[key] = result
        return result

    def entries_of(self, lst: Listing) -> frozenset | None:
        """Basenames the listing actually printed DIRECTLY under lst.root, if its output was captured.

        An absence claim needs this: a covered scope whose contents we never
        SAW cannot prove anything is absent (R4). For a recursive listing, only
        names printed under this exact directory count (C2 location identity).
        """
        base = self._view_base.get(id(lst), lst)
        full = self._full_entries(base)
        if full is None:
            return None
        here = os.path.normpath(lst.root)
        return frozenset(os.path.basename(p) for p in full if os.path.dirname(p) == here)

    def has_observation(self, subject: str | None = None) -> bool:
        """Did the session actually LOOK at the claim's scope? (R5, C2)

        A hedge asserts an attempt; this is the attempt's evidence, and it must be the attempt on
        THIS subject:
          * an exact observe verb (cat, ls, find, ...) that succeeded, with an operand that IS the
            subject — exact normalized path identity, never a basename or substring;
          * a successful listing whose captured output covered the subject, or printed it at its
            exact location;
          * a native read tool (read_file) whose call arguments name exactly the subject and whose
            captured result reports no error.
        Unscoped (subject=None): any successful real observation — an observe-tool call, an
        observe-verb command, a listing or a read. Echo/printf output, failed commands (`false`),
        unrelated listings and unbound outputs are not attempts.
        """
        reads = [o for o in self.tool_outputs if self._read_ok(o)]
        if subject is None:
            return bool(self.observations or [l for l in self.listings if l.ok] or reads)
        is_abs = os.path.isabs(subject)
        want = os.path.normpath(subject) if is_abs else subject

        def same(tok: str) -> bool:
            if is_abs:
                return _abs_operand(tok) == want
            return tok == want

        for ob in self.observed:
            if ob["ok"] and any(same(t) for t in ob["operands"]):
                return True
        if is_abs:
            for l in self.listings:
                if not l.ok:
                    continue
                if l.covers(want) and self.entries_of(l) is not None:
                    return True
                if want in (self._full_entries(l) or frozenset()):
                    return True   # a listing that printed the named file at its location saw it
        for o in reads:
            if same(o.get("path") or ""):
                return True
        return False

    @staticmethod
    def _read_ok(item: dict) -> bool:
        """A captured native read: a read tool, a bound path argument, no reported failure."""
        return ((item.get("tool") or "") in _READ_TOOLS and bool(item.get("path"))
                and item.get("enveloped") is True and not item.get("error")
                and item.get("exit_code") in (None, 0))

    def listing_scope_covers(self, path: str) -> bool:
        return self.searched_for(path) is not None

    # ------------------------------------------------------------------ builders
    def _ingest(self, rec: dict) -> None:
        """One ledger record -> evidence. Shared by the live and fixture builders (parity)."""
        for mut in rec.get("mutations") or []:
            p = mut.get("path")
            if not p:
                continue
            # Incomplete == explicit exists: None (unobserved pre-state). Missing
            # before = legacy record, stays a normal mutation (R1).
            if mut.get("before") is not None and mut["before"].get("exists") is None:
                self.incomplete_mutations.append(mut)
            else:
                self.mutations[os.path.normpath(p)] = mut.get("after") or {}
                self.events.append({"kind": "write", "path": os.path.normpath(p),
                                    "exists": (mut.get("after") or {}).get("exists")})
        tool = rec.get("tool") or ""
        cmd = rec.get("command")
        ok = _ok(rec.get("status"))
        # R5: a failed observe call is a non-observation — it cannot back "I searched and could
        # not verify". C2: observation needs an exact observe verb leading an executed segment.
        if ok and _tool_observes(tool):
            self.observations.append(tool.strip()[:120])
        if not cmd:
            return
        for verb, operands in _observe_operands(cmd):
            self.observed.append({"verb": verb, "operands": operands, "ok": ok,
                                  "call_id": rec.get("tool_call_id") or None})
            if ok:
                self.observations.append(" ".join([verb] + operands)[:120])
        self.command_events.append({"cmd": cmd, "ok": ok})
        self.events.append({"kind": "command", "cmd": cmd, "ok": ok})
        self.commands.append(cmd)
        if not ok:
            self.failed_commands.append(cmd)
        for d in _listings_in(cmd):
            self.listings.append(Listing(
                root=d["root"], command=d["segment"][:200], ok=ok, complete=d["complete"],
                max_depth=d["max_depth"], name_filter=d["name_filter"],
                shows_hidden=d["shows_hidden"], call_id=rec.get("tool_call_id") or None,
                seq=len(self.listings), fmt=d["fmt"], bindable=d["bindable"],
                tokens=d["tokens"], seg_index=d["seg_index"]))

    @classmethod
    def from_ledger(cls, records: Iterable[dict]) -> "Evidence":
        ev = cls()
        for rec in records or []:
            ev._ingest(rec)
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
            ev._ingest(rec)
        return ev

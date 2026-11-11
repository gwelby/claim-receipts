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
# Output-format letters. GNU ls lets the LAST one win (`ls -lC` prints columns, `ls -1C` prints
# columns, `ls -1x` prints rows); this file does not model "last wins", so two of them at once make
# the format unknown and the listing incomplete (hostile 364be5d, finding 1).
_LS_FORMAT_SHORT = set("l1Cx")

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

# Verbs that, WITHOUT a redirect, cannot create, delete or rename a file. Any other segment that
# runs after a listing and names the listed target (or an ancestor, or a glob) may have changed it,
# so that listing no longer speaks for the target's present state (hostile 364be5d, MINOR: `touch`,
# `: > TARGET` or `rm` after the newest listing). This is a list of the harmless, not a model of
# the harmful: an unlisted verb counts as a possible mutation of every name it mentions.
_READONLY_VERBS = {"ls", "dir", "tree", "cat", "head", "tail", "wc", "stat", "grep", "rg", "cd",
                   "true", ":", "echo", "printf", "pwd", "test", "file", "du", "df", "date",
                   "whoami", "which", "find",
                   # Fable 06ac15a finding 13: `[ -f T ]` / `[[ -f T ]]` are `test`; they only
                   # look. Without them a `[ -f T ] && ...` after a listing staled it for T.
                   "[", "[["}

# Fable 06ac15a finding 5: an interpreter running INLINE code (`python3 -c CODE`, `python3 -` or a
# bare interpreter reading its program from stdin, `node -e`, `bash -c`, `sh -c`, `perl -e`,
# `ruby -e`, `php -r`, `pwsh -Command`) can create, remove or rename any file, and the names it
# touches live inside a code string this scanner does not read: `python3 -c "open('report.md','w')"`
# names no path token. Such a segment is a WILDCARD touch — it stales every earlier listing — and
# its printed output is whatever the code was told to print, never a measurement. A script file
# (`python3 /opt/measure.py IMG`) is not inline code and keeps its ordinary treatment.
_INTERPRETER = re.compile(r"^(python[\d.]*|pypy[\d.]*|perl[\d.]*|node|nodejs|ruby|php[\d.]*|"
                          r"bash|sh|zsh|dash|ksh|mksh|fish|osascript|pwsh|powershell|lua[\d.]*|"
                          r"Rscript)$", re.I)
# Short-option letters that mean "the program text follows / comes inline" for some interpreter
# (python/sh -c, perl/node/ruby -e/-E, node/perl -p, php -r). Over-matching a harmless flag only
# makes a segment a wildcard touch, which can only make a listing abstain.
_INLINE_SHORT = set("ceEpr")
_INLINE_LONG = {"--eval", "--command", "--print", "-command", "-encodedcommand", "-c"}
# Prefix programs that run their argv as a command (`nice -n 19 python3 -c ...`).
_WRAPPERS = {"env", "nice", "ionice", "timeout", "nohup", "command", "exec", "time", "sudo",
             "stdbuf", "xargs", "chrt", "taskset"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _inline_code(tokens: list[str]) -> bool:
    """Is this segment an interpreter running inline (or stdin-fed) code? See _INTERPRETER."""
    toks = [t for t in _strip_redirects(list(tokens))[0]]
    while toks and _ASSIGNMENT.match(toks[0]):
        toks = toks[1:]                      # FOO=1 python3 -c ...
    if not toks:
        return False
    start = None
    if _INTERPRETER.match(os.path.basename(toks[0])):
        start = 0
    elif os.path.basename(toks[0]) in _WRAPPERS:
        start = next((i for i, t in enumerate(toks[1:], 1)
                      if _INTERPRETER.match(os.path.basename(t))), None)
    if start is None:
        return False
    for tok in toks[start + 1:]:
        if tok == "-":
            return True                      # `python3 -`: the program is stdin (a heredoc, a pipe)
        if tok == "--":
            continue
        if tok.lower() in _INLINE_LONG or tok.lower().startswith(("--eval=", "--command=")):
            return True
        if tok.startswith("-") and not tok.startswith("--"):
            if set(tok[1:]) & _INLINE_SHORT:
                return True
            continue
        if tok.startswith("--"):
            continue
        return False                         # the first operand is a script file
    return True                              # no operand at all: the program comes from stdin


# Fable 06ac15a finding 2: verbs whose exit status 1 is a RESULT, not a failure — grep/rg found no
# match, diff/cmp found a difference, test/[ evaluated false, `git diff --exit-code|--quiet` found a
# change. Exit 2 (or more) is still trouble. Defined ONCE here; judge.py's lifecycle side (lane A3)
# needs the same set and may import it (integrator: unify on this definition).
# A measurement line is kept up to this many characters. It used to be 100, which cut the subject's
# own path off any measurement made in a folder nested a little deep, so a genuine measurement
# abstained depending on where the session ran (found 2026-11-11 by the return packet's run).
MEASURE_LINE_CAP = 4096

EXIT1_RESULT_VERBS = frozenset({"grep", "egrep", "fgrep", "rg", "diff", "cmp", "test", "[", "[["})
# Redirect targets that cannot themselves fail and so cannot be the source of an exit status 1.
_SAFE_REDIRECT_TARGETS = {"/dev/null", "1", "2"}


def exit1_is_result(tokens) -> bool:
    """Does exit status 1 of THIS argv report a result (no match / differs / false)?"""
    toks = list(tokens or ())
    if not toks:
        return False
    verb = toks[0]
    if verb in EXIT1_RESULT_VERBS:
        return True
    if verb == "git":
        rest, i = toks[1:], 0
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in ("-C", "-c") else 1      # git -C DIR / -c k=v take a value
        if i < len(rest) and rest[i] == "diff":
            return any(t in ("--exit-code", "--quiet", "--no-index") for t in rest[i + 1:])
    return False


def exit1_is_result_cmd(cmd: str) -> bool:
    """True only when a whole command's exit status 1 can be attributed to a result verb.

    Deliberately narrow: exactly ONE executed segment (a `cd X && grep ...` exits 1 when cd fails,
    and then grep never ran; `grep ... | head` reports head's status) whose redirects cannot fail.
    An unsegmentable command never qualifies."""
    segs = [sg for sg in (_segments(cmd) or []) if sg.tokens]
    if len(segs) != 1 or _segments(cmd) is None:
        return False
    argv, targets = _strip_redirects(segs[0].tokens)
    if any(t not in _SAFE_REDIRECT_TARGETS for t in targets):
        return False
    return exit1_is_result(argv)
# find is read-only only without these actions.
_FIND_WRITES = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf",
                "-fls"}
# A redirect token: optional fd or &, the operator, and (possibly) its glued target.
_REDIRECT_TOK = re.compile(r"^(\d*|&)(>>|>\||>&|<>|<&|&>>|&>|>|<)(.*)$")


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
    command substitution, process substitution, heredocs/herestrings (`<<`: the body lines are
    data, not commands — hostile 364be5d finding 4) and backgrounding with a lone `&` (the call
    returns before the job's outcome or output exists). None means "abstain", never "guess".
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
        if cmd.startswith("<<", i):
            return None                            # heredoc/herestring: its body is not commands
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
        elif c == "&":
            return None                            # backgrounded: outcome/output not this call's
        elif c in ";|\n":
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


def _strip_redirects(tokens: list[str]) -> tuple[list[str], list[str]]:
    """(argv without redirections, redirect targets). `cat /dev/null > T` reads /dev/null; T is
    a file it WRITES, never an operand it observed (hostile 364be5d finding 4). A quoted `>`
    operand is dropped too — that loses an observation, it never invents one."""
    kept, targets = [], []
    skip = False
    for tok in tokens:
        if skip:
            targets.append(tok)
            skip = False
            continue
        m = _REDIRECT_TOK.match(tok)
        if m:
            if m.group(3):
                targets.append(m.group(3))
            else:
                skip = True
            continue
        kept.append(tok)
    return kept, targets


def _status_bound(segs: list[_Segment], idx: int) -> bool:
    """Does the CALL's exit status speak for segment <idx>?

    Only when every separator after it is `&&` (a failure would have failed the call) and no `||`
    precedes it (a `||` branch may never have run). `cat MISSING; true`, `cat MISSING || true`
    and `ls X | head` all succeed whatever the observing segment did (hostile 364be5d finding 4)."""
    if any(sg.sep_after == "||" for sg in segs[:idx]):
        return False
    return all(sg.sep_after in (None, "&&") for sg in segs[idx:])


def _abs_operand(tok: str) -> str | None:
    """An operand whose literal value is a known absolute path, else None.

    Only an ABSOLUTE root can licence anything: a relative path is relative to a CWD we never
    recorded. An operand needing expansion ($VAR, globs, ~) has no known value. An operand with a
    `..` component has no known PHYSICAL location: normpath collapses `/r/link/..` to `/r`, but
    the kernel resolves it from the link's target (hostile 364be5d finding 2)."""
    if not tok or _EXPANSION.search(tok) or not os.path.isabs(tok):
        return None
    if ".." in tok.split("/"):
        return None
    return os.path.normpath(tok)


def _listing_of(seg: _Segment) -> list[dict]:
    """Listing descriptors for ONE executed segment (empty if it is not an admitted listing)."""
    if not seg.tokens or seg.tokens[0] not in _LISTING_VERBS:
        return []
    verb, args = seg.tokens[0], _strip_redirects(seg.tokens[1:])[0]
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
        if len(shorts & _LS_FORMAT_SHORT) > 1:
            complete = False                # last-wins format: the parser cannot know which
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
            d["status_bound"] = _status_bound(segs, idx)
            out.append(d)
    return out


def _observe_operands(cmd: str) -> list[tuple[str, list[str], bool]]:
    """(verb, operand tokens, status_bound) for every executed segment whose verb is an exact
    observe verb. Redirect targets are not operands; status_bound says whether the call's exit
    status is this segment's (see _status_bound)."""
    out = []
    segs = _segments(cmd) or []
    for idx, seg in enumerate(segs):
        if seg.tokens and seg.tokens[0] in _OBSERVE_VERBS:
            args = _strip_redirects(seg.tokens[1:])[0]
            if seg.tokens[0] in ("grep", "rg"):
                operands = _grep_files(args, seg.tokens[0])
            else:
                operands = [t for t in args if not t.startswith("-")]
            out.append((seg.tokens[0], operands, _status_bound(segs, idx)))
    return out


# grep/rg short options that consume the NEXT token as their value (when last in a cluster).
_GREP_ARG_SHORT = {"grep": set("ABCmefdD"), "rg": set("ABCmefdgtTMjEr")}
_GREP_ARG_LONG = {"--regexp", "--file", "--after-context", "--before-context", "--context",
                  "--max-count", "--directories", "--devices", "--include", "--exclude",
                  "--exclude-dir", "--label", "--glob", "--type", "--type-not", "--max-depth",
                  "--threads", "--encoding", "--replace", "--max-columns"}
_RG_ARG_LONG = {"--color", "--colour", "--colors", "--iglob", "--sort", "--sortr"}


def _grep_files(args: list[str], verb: str = "grep") -> list[str]:
    """The FILE operands of a grep/rg argv — never its pattern (Fable 06ac15a finding 12).

    `grep -rn /x/report.md /src` searches /src FOR the text "/x/report.md"; it never read that
    file, so a hedge about it was BACKED by a pattern. The first positional operand is the
    pattern unless one was given with -e/-f (--regexp/--file). Option values (`-A 3`, `-m1`,
    `--include GLOB`) are not operands either. A misparse can only drop an observation."""
    files, explicit, ended, i = [], False, False, 0
    while i < len(args):
        tok = args[i]
        i += 1
        if ended or tok == "-" or not tok.startswith("-"):
            files.append(tok)
            continue
        if tok == "--":
            ended = True
            continue
        if tok.startswith("--"):
            name = tok.split("=", 1)[0]
            if name in ("--regexp", "--file"):
                explicit = True
            if "=" not in tok and (name in _GREP_ARG_LONG
                                   or (verb == "rg" and name in _RG_ARG_LONG)):
                i += 1                       # the value is the next token
            continue
        cluster = tok[1:]
        for j, ch in enumerate(cluster):
            if ch in "ef":
                explicit = True
            if ch in _GREP_ARG_SHORT.get(verb, _GREP_ARG_SHORT["grep"]):
                if j == len(cluster) - 1:
                    i += 1                   # `-e PAT`, `-A 3`: the value is the next token
                break                        # `-ePAT`, `-A3`: the rest of the cluster is the value
    return files if explicit else files[1:]


# Commands that change only the files they name as operands (and their redirect targets); their
# touches are bounded by those operands, as before. Everything else that is not read-only is a
# wildcard touch (Codex 2358d20 R2).
_BOUNDED_MUTATORS = {"touch", "rm", "rmdir", "mkdir", "cp", "mv", "ln", "chmod", "chown", "truncate",
                     "tee", "unlink"}

_GIT_STATUS_OPTS = {"-s", "--short", "-b", "--branch", "-sb", "--porcelain", "--porcelain=v1",
                    "--porcelain=v2", "-uno", "--untracked-files=no", "--ignored=no"}


def _git_status_only(args) -> bool:
    """`git [-C DIR] status [known-harmless options]` and nothing else."""
    toks = list(args)
    if toks[:1] == ["-C"]:
        toks = toks[2:]
    return toks[:1] == ["status"] and all(t in _GIT_STATUS_OPTS for t in toks[1:])


def _touches_in(cmd: str) -> list[tuple[int, tuple]]:
    """(segment index, touch) for every segment that may have created/removed/renamed a file.

    A touch is (names, abs_paths, wildcard): what the segment's argv and redirect targets name.
    A command this scanner cannot segment is one wildcard touch at index 0 — it may have done
    anything (a heredoc writing the target, a subshell, a substitution)."""
    segs = _segments(cmd)
    if segs is None:
        return [(0, (frozenset(), frozenset(), True))]
    out = []
    for idx, seg in enumerate(segs):
        if not seg.tokens:
            continue
        if _inline_code(seg.tokens):
            # Fable 06ac15a finding 5: inline interpreter code may write any path, named only
            # inside a code string — a wildcard touch, like an unsegmentable command.
            out.append((idx, (frozenset(), frozenset(), True)))
            continue
        verb = seg.tokens[0]
        args, targets = _strip_redirects(seg.tokens[1:])
        # git: even a reading subcommand can write (`git diff --output=T`, Codex 6a6aae3 N2). Only
        # `git status` with options from a short known-harmless list is read-only (fail closed);
        # every other git invocation stales the listing.
        readonly = (verb in _READONLY_VERBS and not (verb == "find" and set(args) & _FIND_WRITES)) \
            or (verb == "git" and _git_status_only(args))
        if not readonly and verb not in _BOUNDED_MUTATORS:
            # Codex 2358d20 R2: a command that is neither known to only look nor known to change
            # only what it names may create, restore or remove files it never names (`git checkout
            # -- .` restores the target; `python3 build.py` writes a file named only inside the
            # script). Its operands cannot bound its effects, so it stales every earlier listing:
            # a wildcard touch.
            out.append((idx, (frozenset(), frozenset(), True)))
            continue
        toks = list(targets) if readonly else list(args) + list(targets)
        if not toks:
            continue
        names, paths, wild = set(), set(), False
        for t in toks:
            if t.startswith("-"):
                if "=" not in t:
                    continue
                t = t.split("=", 1)[1]
            if not t or re.fullmatch(r"\d+|-", t):
                continue                     # fd duplication (2>&1), not a file
            if _EXPANSION.search(t):
                wild = True
                continue
            if os.path.isabs(t):
                paths.add(os.path.normpath(t))
            else:
                names.update(part for part in t.split("/") if part not in ("", ".", ".."))
        out.append((idx, (frozenset(names), frozenset(paths), wild)))
    return out


def _touch_hits(touch: tuple, root: str, target: str) -> bool:
    """Could this touch have changed <target> (a path under <root>)?"""
    names, paths, wild = touch
    if wild:
        return True
    target = os.path.normpath(target)
    for p in paths:
        if target == p or target.startswith(p.rstrip(os.sep) + os.sep):
            return True                      # the target itself, or a directory containing it
    rel = os.path.relpath(target, os.path.normpath(root))
    parts = {x for x in rel.split(os.sep) if x not in (".", "..")}
    return bool(parts & names)               # a relative name: the cwd is unknown, so any match


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
    rec_index: int = 0              # which ledger record produced it (event order)
    # Set only on the view searched_for() returns: segments that ran AFTER this listing and may
    # have created/removed a name it covers. covers() is then "covered as of now", not "as of then".
    later_touches: tuple = ()

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
        if any(_touch_hits(t, root, target) for t in self.later_touches):
            return False                    # named by a later possible mutation: stale for it
        return True


_LS_LONG_ROW = re.compile(r"^[-dlpscbx][-rwxsStT]{9}")
_LS_MONTH = re.compile(r"^[^\d\s-]\S*$")
_LS_DAY = re.compile(r"^\d{1,2}$")
_LS_TIME_OR_YEAR = re.compile(r"^(\d{1,2}:\d{2}|\d{4})$")


def _ls_long_name(row: str) -> str | None:
    """The name on one `ls -l` row, or None when the row is not the shape this parser knows.

    Admitted shape: exactly nine whitespace fields (mode, links, owner, group, size, month, day,
    time-or-year, name), symlink rows judged on the part before ` -> `. A name with a space adds
    a field — `old report.md` is not `report.md` (hostile 364be5d MINOR) — and device rows,
    ISO dates or other locales change the count or the date shape: all abstain, never guess."""
    left = row.split(" -> ", 1)[0] if row.startswith("l") else row
    fields = left.split()
    if len(fields) != 9 or not _LS_LONG_ROW.match(fields[0]):
        return None
    if not (_LS_MONTH.match(fields[5]) and _LS_DAY.match(fields[6])
            and _LS_TIME_OR_YEAR.match(fields[7])):
        return None
    return fields[8]
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
            if re.fullmatch(r"total \S+", st):
                continue
            name = _ls_long_name(st)
            if name is None:
                return None                 # an unrecognised row is never skipped (finding 1)
            names = [name]
        elif lst.fmt == "ls-lines":
            names = [st]                    # -1: one whole name per line
        else:
            if re.search(r"\S \S", st):
                return None                 # columns are 2+ spaces apart: a 1-space gap is a
                                            # name with a space, which splitting would invent
            names = st.split()              # columns: every token is a name
        for n in names:
            n = n.rstrip("/")
            if not n:
                continue
            if os.path.isabs(n):
                # ls prints children by NAME. An absolute line is an operand printed as itself
                # (a symlink under -l, a file, -d, or a multi-operand header) — the scope's
                # contents were never enumerated (hostile 364be5d finding 2).
                return None
            out.add(os.path.normpath(os.path.join(cur, n)))
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
    # C2 + hostile 364be5d finding 5: these are observe-TOOL calls only (web_search, search_files,
    # ...) — the only thing an UNSCOPED hedge may lean on. A terminal command, or a read_file of
    # one named path, that looked at something unrelated is no attempt at an unnamed subject.
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
        self._rec_index = 0
        # (rec_index, seg_index, touch) for every segment/record that may have changed a file
        self._touches: list[tuple[int, int, tuple]] = []

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
        directory — `find /r` printing /r/b/subject.md is not a sighting of /r/a/subject.md.
        Always a fresh object: it carries the touches that ran after <base> (as-of-now coverage)."""
        directory = os.path.normpath(directory)
        rel = os.path.relpath(directory, os.path.normpath(base.root))
        depth = 0 if rel == os.curdir else len(rel.split(os.sep))
        later = tuple(t for (ri, si, t) in self._touches
                      if (ri, si) > (base.rec_index, base.seg_index))
        view = Listing(root=directory, command=base.command, ok=base.ok, complete=base.complete,
                       max_depth=None if base.max_depth is None else max(base.max_depth - depth, 0),
                       name_filter=base.name_filter, shows_hidden=base.shows_hidden,
                       call_id=base.call_id, seq=base.seq, fmt=base.fmt, bindable=base.bindable,
                       tokens=base.tokens, seg_index=base.seg_index, rec_index=base.rec_index,
                       later_touches=later)
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
        if self._through_symlink(lst.root, path):
            return None
        return self._view(lst, path)

    def _is_link(self, path: str) -> bool:
        if self.fs is not None:
            return bool((self.fs.get(os.path.normpath(path)) or {}).get("link"))
        try:
            return os.path.islink(path)
        except (OSError, ValueError):
            return True                     # cannot tell: treat as unsafe

    def _through_symlink(self, root: str, path: str) -> bool:
        """Is any component from <root> down to <path> (both included) a symbolic link?

        `find LINK`, `ls -l LINK` and `ls -R` / `find` over a tree holding a linked directory do
        not enumerate what lies behind the link, yet a path through it names real files (hostile
        364be5d finding 2). Production checks the filesystem at receipt time; fixtures mark a
        link with {"link": true}. Components above <root> are shared by listing and claim."""
        root, path = os.path.normpath(root), os.path.normpath(path)
        if self._is_link(root):
            return True
        rel = os.path.relpath(path, root)
        if rel == os.curdir:
            return False
        cur = root
        for part in rel.split(os.sep):
            if part == "..":
                return True
            cur = os.path.join(cur, part)
            if self._is_link(cur):
                return True
        return False

    def scope_report(self, path: str) -> str:
        """Why no listing can prove anything about <path> — for UNVERIFIABLE details."""
        if not self.listings:
            return "no listing ran this session"
        l = self._latest_covering(path)
        if l is not None:
            if not l.ok:
                return (f"listing of {l.root} failed, or its outcome was masked by another "
                        f"segment ({l.command[:50]})")
            if not l.complete:
                return f"listing of {l.root} was truncated/filtered ({l.command[:50]})"
            if self._bound_output(l) == "truncated":
                return f"output of {l.command[:50]} was truncated before it was read"
            if self._through_symlink(l.root, path):
                return f"{path} is reached through a symbolic link that {l.command[:40]} did not follow"
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
        Unscoped (subject=None): a successful observe-TOOL call only (hostile 364be5d finding 5) —
        `cat unrelated.txt`, `ls /` or a read_file of one named path is a real look at THAT thing,
        not an attempt at an unnamed subject. Original case-06 (web_search, then the hedge) stays
        BACKED. NARROWED: fdb8f87/364be5d also admitted any observe-verb command, any ok listing
        and any native read here; those now back only a hedge that names their exact path.
        Echo/printf output, failed commands (`false`), unrelated listings and unbound outputs are
        not attempts.
        A RELATIVE subject never matches (finding 3): `report.md` or `docs/report.md` is relative
        to a working directory nobody recorded, so a same-spelled operand may be another file.
        """
        reads = [o for o in self.tool_outputs if self._read_ok(o)]
        if subject is None:
            # Parity: the live ledger records no row for a call that ran no command and changed
            # nothing (web_search), so the live path reads the same observe-tool calls from the
            # transcript; a row the host marked as an error is no attempt.
            native = [o for o in self.tool_outputs
                      if _tool_observes(o.get("tool") or "") and o.get("tool") not in _READ_TOOLS
                      and not o.get("error") and o.get("ok") is not False]
            return bool(self.observations or native)
        is_abs = os.path.isabs(subject)
        want = os.path.normpath(subject) if is_abs else subject

        def same(tok: str) -> bool:
            if is_abs:
                return _abs_operand(tok) == want
            return False                    # relative: identity unknowable (finding 3)

        failed_calls = {o.get("call_id") for o in self.tool_outputs
                        if o.get("call_id") and o.get("ok") is False}
        for ob in self.observed:
            if ob.get("result_exit1") and self._exit_code(ob.get("call_id")) == 1:
                # Fable 06ac15a finding 2: `grep -n 'section 3' X` exiting 1 is the search that
                # ran and found nothing — exactly the attempt a hedge reports. Only an exit code
                # of exactly 1 captured for THIS call (exit 2 = unreadable file, no match ever
                # attempted), and only for a single-segment result-verb command.
                if any(same(t) for t in ob["operands"]):
                    return True
                continue
            if ob.get("call_id") and ob["call_id"] in failed_calls:
                continue                    # the transcript says this call failed
            if ob["ok"] and any(same(t) for t in ob["operands"]):
                return True
        if is_abs:
            parent = os.path.dirname(want)
            for l in self.listings:
                if not l.ok:
                    continue
                if (l.complete and l.covers(want) and not self._through_symlink(l.root, parent)
                        and self.entries_of(l) is not None):
                    return True
                if want in (self._full_entries(l) or frozenset()):
                    return True   # a listing that printed the named file at its location saw it
        for o in reads:
            if same(o.get("path") or ""):
                return True
        return False

    def _exit_code(self, call_id) -> int | None:
        """The exit code the transcript captured for exactly this call, else None."""
        if not call_id:
            return None
        rows = [o for o in self.tool_outputs if o.get("call_id") == call_id]
        if len(rows) != 1 or rows[0].get("error"):
            return None
        code = rows[0].get("exit_code")
        return code if isinstance(code, int) and not isinstance(code, bool) else None

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
        self._rec_index += 1
        ri = self._rec_index
        for mut in rec.get("mutations") or []:
            p = mut.get("path")
            if not p:
                continue
            # Any recorded write (complete or not) after a listing makes it stale for that path.
            self._touches.append((ri, -1, (frozenset(), frozenset({os.path.normpath(p)}), False)))
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
        if ok and _tool_observes(tool) and tool not in _READ_TOOLS:
            self.observations.append(tool.strip()[:120])
        if not cmd:
            return
        for idx, touch in _touches_in(cmd):
            self._touches.append((ri, idx, touch))
        result_exit1 = exit1_is_result_cmd(cmd)
        for verb, operands, bound in _observe_operands(cmd):
            # The record's status speaks for this segment only when no later `;`/`||`/`|` could
            # have masked its failure (hostile 364be5d finding 4: `cat MISSING; true`).
            # result_exit1 (Fable 06ac15a finding 2): the command is ONE result-verb segment, so
            # a captured exit status of exactly 1 means "searched, found nothing" — see
            # has_observation. The record's own status cannot tell 1 from 2, so it stays ok=False.
            self.observed.append({"verb": verb, "operands": operands, "ok": ok and bound,
                                  "call_id": rec.get("tool_call_id") or None,
                                  "result_exit1": result_exit1})
        self.command_events.append({"cmd": cmd, "ok": ok, "call_id": rec.get("tool_call_id") or None})
        self.events.append({"kind": "command", "cmd": cmd, "ok": ok, "cwd": rec.get("cwd") or None,
                            "cut": bool(rec.get("command_cut"))})
        self.commands.append(cmd)
        if not ok:
            self.failed_commands.append(cmd)
        for d in _listings_in(cmd):
            self.listings.append(Listing(
                root=d["root"], command=d["segment"][:200], ok=ok and d["status_bound"],
                complete=d["complete"],
                max_depth=d["max_depth"], name_filter=d["name_filter"],
                shows_hidden=d["shows_hidden"], call_id=rec.get("tool_call_id") or None,
                seq=len(self.listings), fmt=d["fmt"], bindable=d["bindable"],
                tokens=d["tokens"], seg_index=d["seg_index"], rec_index=ri))

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
        # Fable 06ac15a finding 4: margins, whitespace and bleed measure the page's COMPLEMENT
        # (a `margins 5%` line is 95% coverage, or nothing), and dpi is a resolution, never an
        # extent: none of them may make a percentage a coverage measurement. The words are gone
        # from the admitting list, and a clause that names one of them is not a measurement.
        MEASURE_WORDS = _re.compile(
            r"\b(coverage|ink|bbox|filled|area|page ?fill|occupied)\b", _re.I)
        COMPLEMENT_WORDS = _re.compile(
            r"\b(margins?|whitespace|white(?: space)?|blank|empty|bleed|padding|borders?|"
            r"gutters?|unused|free|dpi|ppi)\b", _re.I)
        PROGRESS = _re.compile(r"(\d+%\||\|[#=]+\||it/s|Loading|\bETA\b|^\s*\d+%\s*$)", _re.I)
        PCT = _re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
        out = []
        for item in self.tool_outputs:
            if (item.get("tool") or "").lower() in ("read_file", "write_file", "patch"):
                continue          # file BODIES are not measurements — this read its own fixtures back
            cmd = item.get("command") or ""
            # Codex 2358d20 R3: the measurement must come from a producer that completed. A call
            # that failed (or whose outcome is unknown), output that was cut, or a command where a
            # later `;`/`||`/`|` could mask the producer's failure (`measure IMG; true` ends 0)
            # gives no measurement.
            done = item.get("ok")
            if done is None and cmd:
                # The output carries no status of its own: use the hook's record of the PRODUCING
                # call. Native outputs bind by call id only (Codex 6a6aae3 N3: an earlier same-text
                # call's success must not lend itself to a later output). Only when neither side
                # has a call id may the text join, and only if exactly one output and exactly one
                # record of that command exist, so nothing can be borrowed.
                cid = item.get("call_id")
                if cid:
                    seen = [ev["ok"] for ev in self.command_events if ev.get("call_id") == cid]
                    done = len(seen) == 1 and seen[0] is True
                else:
                    seen = [ev for ev in self.command_events if ev["cmd"] == cmd]
                    outs = [o for o in self.tool_outputs if (o.get("command") or "") == cmd]
                    done = (len(seen) == 1 and not seen[0].get("call_id") and len(outs) == 1
                            and seen[0]["ok"] is True)
            if done is not True or item.get("truncated"):
                continue
            if cmd:
                _ss = _segments(cmd)
                if _ss is None or not all(_status_bound(_ss, i) for i in range(len(_ss))):
                    continue
                # Fable 06ac15a finding 1: a measurement's producing command must be one this
                # file can segment. A heredoc (`python3 - IMG <<'EOF' print('ink coverage
                # 100%') EOF`), $(...), backticks or a lone `&` segment to None — the printed
                # number is whatever an unread body was told to print. An inline-interpreter
                # segment (`python3 -c`, `python3 -`, `node -e`, ...) is the same: its output is
                # its own code's text, not a measurement.
                segs = _segments(cmd)
                if segs is None or any(_inline_code(sg.tokens) for sg in segs if sg.tokens):
                    continue
            for line in (item.get("output") or "").splitlines():
                if PROGRESS.search(line) or not MEASURE_WORDS.search(line):
                    continue
                if any(ch in line for ch in '{}"') or "\"output\":" in line or "|" in line:
                    continue      # quoted/report text, not a measurement
                # Each percentage binds to its own clause (finding 4): in "coverage 53.0%;
                # margins top=0" the 53% is coverage, in "ink coverage 95%, margins 5%" the 5% is
                # a margin. A clause must name a measure word and no complement word.
                for clause in _re.split(r"[;,]", line):
                    if not MEASURE_WORDS.search(clause) or COMPLEMENT_WORDS.search(clause):
                        continue
                    for m in PCT.finditer(clause):
                        try:
                            val = float(m.group(1)) / 100.0
                        except ValueError:
                            continue
                        if 0.0 <= val <= 1.0:
                            # Carry the producing command too — the subject join happens
                            # on command+line, not the bare number (R3c).
                            out.append((val, line.strip()[:MEASURE_LINE_CAP], cmd))
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

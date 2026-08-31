#!/usr/bin/env python3
"""PreToolUse gate: a release tag with only one vendor family in the ledger asks.

Delegation ground 4 carries a gate -- "one family is the default; two families
in parallel is a gate ... open it when the change is about to ship in a
release" (`skills/omo/SKILL.md`). Until 0.21.6 that gate existed only in that
prose and in CHANGELOG 0.19.0, and the 2026-08-31 evaluation found it silenced
by a session writing "one family is enough for this bundle" into its own plan
document -- after which the commit, the tag, and the push all passed with
nothing objecting anywhere. Prose is not a binding layer; a PreToolUse hook is
the only layer that survives a session with momentum, because it is enforced at
the tool-call boundary rather than by a model reading an instruction.

D1 (2026-08-31, user) settled the shape: this **asks**, it does not block. The
cost of a second family is the user's call, made at the moment it would be
spent -- so the reason has to name which backends actually ran. "Gate not
satisfied" alone gives the user nothing to decide with.

Fail-open on a missing instrument: no ledger (a CI runner has none), an
unreadable one, an untokenizable command, any exception at all -> the tag
proceeds silently. A gate that breaks releases when its own instrument is
missing gets deleted, and a deleted gate is worth less than a leaky one.

A malformed *row* is the one thing that does NOT fail open: it is skipped and
the rows after it still count. codex argued the other way (2026-08-31) and agy
argued this way in the same round; agy wins because one junk byte appended to
an unrotated append-only log would otherwise disable the gate permanently,
which is a far cheaper accident than an unreadable file.

**The command is tokenized, not pattern-matched.** The first version ran three
regexes over the raw command string and an adversarial review (agy, 2026-08-31)
broke it four ways at once: `git -C <dir> tag -a v1.2.3` never matched at all
(the gate went silent on a real release), `git tag -d v0.9.0 && git tag -a
v1.2.3` was suppressed by the delete half, a `-m "... git tag -d ..."` message
suppressed it the same way, and `git tag wip -m "prepare for v1.2.3"` fired on
a scratch tag. All four are the same defect -- a shell command is a token list,
and quoting is exactly the distinction a regex over the raw string cannot see.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import sys
from pathlib import Path

# A release-shaped tag NAME (matched against the token, never the command line).
# `v1.2.3-rc1` counts -- a release candidate ships. `v1.2` does not: this repo
# family has never cut one, and a two-segment tag is more often a branch alias.
_RELEASE_TAG_RE = re.compile(r"v\d+\.\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.+-]*)?\Z")

# Shell operators that separate one command from the next. With
# punctuation_chars the lexer emits these as their own tokens, so a `;` inside
# a quoted message stays part of the message.
_OPERATORS = {"&&", "||", ";", "|", "&", ";;", "(", ")"}

# Newlines, which shlex gets wrong in both directions (codex, 2026-08-31). A `\`
# before one continues the command, and shlex keeps the escaped newline as a
# lone "\n" token that stops the walk to `tag` -- so `git \<nl> tag -a v1.2.3`
# went silent. A bare one ENDS the command, and shlex treats it as ordinary
# whitespace, merging two commands into one -- so `git tag -l x` on the first
# line suppressed a real tag on the second. Splice the first, promote the second
# to an explicit `;` before lexing.
_CONTINUATION_RE = re.compile(r"\\\n")

# `git` global options that swallow the following token, so the walk to the
# `tag` subcommand does not stop on their value (`git -C /repo tag ...`).
_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                          "--exec-path", "--super-prefix"}

# `git tag` options that make the command read or delete rather than ship one.
_NON_SHIPPING_LONG = {"--list", "--delete", "--verify", "--contains",
                      "--no-contains", "--points-at", "--merged", "--no-merged",
                      "--column", "--no-column", "--sort", "--format",
                      "--omit-empty", "--ignore-case"}
_NON_SHIPPING_SHORT = set("dlnv")
# Options whose VALUE is a separate token. Without these `git tag -m v9.9.9 wip`
# would read the message as the tag name.
_VALUE_SHORT = set("mFu")
_VALUE_LONG = {"--message", "--file", "--local-user", "--contains",
               "--no-contains", "--points-at", "--merged", "--no-merged",
               "--sort", "--format", "--cleanup"}

# Go writes RFC3339Nano; datetime.fromisoformat tops out at microseconds.
_TS_FRAC_RE = re.compile(r"(\.\d{6})\d+")

DEFAULT_WINDOW_HOURS = 6.0
# ponytail: 2 MB of an unrotated JSONL is thousands of calls, far more than any
# window needs. Raise it if a window ever runs off the top of the tail.
MAX_LEDGER_BYTES = 2_000_000
CLOCK_SKEW_MINUTES = 5


# --------------------------------------------------------------------------
# Does this command line ship a release?
# --------------------------------------------------------------------------

def _tokenize(command: str) -> list:
    """Shell tokens with operators split out, or [] when it cannot be lexed."""
    text = _CONTINUATION_RE.sub(" ", command).replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quotes / unterminated heredoc: refuse to guess. Such a
        # command does not run in the shell either.
        return []


def _tag_args(tokens: list):
    """Args after `tag` when this segment is a `git tag` invocation, else None."""
    if not tokens or os.path.basename(tokens[0]) != "git":
        return None
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token in _GIT_GLOBAL_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        break
    if i >= len(tokens) or tokens[i] != "tag":
        return None
    return tokens[i + 1:]


def _created_tag_names(args: list):
    """Positional tag names in a `git tag` arg list, or None if it ships none."""
    names, i = [], 0
    while i < len(args):
        token = args[i]
        if token == "--":
            names.extend(args[i + 1:])
            break
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            if name in _NON_SHIPPING_LONG:
                return None
            if "=" not in token and name in _VALUE_LONG:
                i += 1
            i += 1
            continue
        if token.startswith("-") and len(token) > 1:
            body = token[1:]
            # A cluster is non-shipping if ANY of its letters is: `-fd` deletes,
            # `-n3` lists. Both slipped past the regex version.
            if any(c in _NON_SHIPPING_SHORT for c in body):
                return None
            for pos, char in enumerate(body):
                if char in _VALUE_SHORT:
                    if pos == len(body) - 1:
                        i += 1          # `-m msg`; `-mmsg` carries its own value
                    break
            i += 1
            continue
        names.append(token)
        i += 1
    return names


def release_tags(command: str) -> list:
    """Release-shaped tag names this command line would create (possibly [])."""
    found, segment = [], []
    for token in _tokenize(command) + [";"]:
        if token in _OPERATORS:
            args = _tag_args(segment)
            segment = []
            if args is None:
                continue
            names = _created_tag_names(args)
            if names is None:
                continue
            found.extend(n for n in names if _RELEASE_TAG_RE.match(n))
        else:
            segment.append(token)
    return found


# --------------------------------------------------------------------------
# What does the call ledger say ran?
# --------------------------------------------------------------------------

def _ledger_path() -> Path:
    """Mirror of the wrapper's `ledgerPath()` (internal/ledger/ledger.go:178).

    Deliberately no `expanduser()` on the override: Go takes `CODEAGENT_LEDGER`
    verbatim, so `~/calls.jsonl` writes into a literal `~` directory there. A
    hook that helpfully expanded it would look somewhere the wrapper never
    wrote and report a missing ledger (named by codex, 2026-08-31).
    """
    override = os.environ.get("CODEAGENT_LEDGER")
    if override:
        return Path(override)
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        base = Path(state_home)
    else:
        home = os.environ.get("HOME")
        base = (Path(home) if home else Path.home()) / ".local" / "state"
    return base / "codeagent-wrapper" / "calls.jsonl"


def _parse_ts(raw):
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = _TS_FRAC_RE.sub(r"\1", raw.strip()).replace("Z", "+00:00")
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    # A naive stamp came from a writer on this machine, so it is local time.
    # Stamping it UTC would shift it by the offset and silently age out recent
    # calls on any machine west of Greenwich (named by agy, 2026-08-31).
    return dt if dt.tzinfo else dt.astimezone()


def _tail_text(path: Path, max_bytes: int = MAX_LEDGER_BYTES) -> str:
    """The last `max_bytes` of the file, cut back to a line boundary.

    The ledger is append-only with no rotation (`internal/ledger/ledger.go:175`)
    and this hook runs under a 5s timeout, so reading it whole is an unbounded
    read on a bounded budget -- a big enough ledger turns the gate into a hook
    timeout error instead of a silent pass (named by codex, 2026-08-31). Only
    the recent window can matter, and that lives at the end.
    """
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        start = max(0, fh.tell() - max_bytes)
        fh.seek(start)
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    # A mid-line start would hand json.loads a fragment; drop that partial line.
    return text if start == 0 else text.split("\n", 1)[-1]


def recent_backends(path: Path, window_hours: float) -> dict:
    """`{backend: (call_count, {workdirs})}` for ledger rows inside the window.

    One malformed row must not blind the gate to the rows after it, so parse
    failures are skipped rather than raised. I/O failures DO raise -- the caller
    turns those into a silent allow, which is the fail-open direction; swallowing
    them here would return an empty dict and read as "no families ran".
    """
    # ponytail: a time window is a proxy for "this change" -- the ledger has no
    # session id and no link to a commit, so two families that ran for a
    # *different* repo inside the window pass this gate. Scope by `workdir`
    # under the repo being tagged if that false pass ever shows up in practice.
    now = _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(hours=window_hours)
    # An upper bound too: without it a row stamped 2099 stays "recent" forever,
    # so two junk future rows would satisfy the gate permanently (codex,
    # 2026-08-31). The slack absorbs ordinary clock skew, nothing more.
    horizon = now + _dt.timedelta(minutes=CLOCK_SKEW_MINUTES)
    seen: dict = {}
    for line in _tail_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ts = _parse_ts(row.get("ts"))
        if ts is None or ts < cutoff or ts > horizon:
            continue
        backend = row.get("backend")
        if not isinstance(backend, str) or not backend:
            continue
        count, workdirs = seen.get(backend, (0, set()))
        workdir = row.get("workdir")
        if isinstance(workdir, str) and workdir:
            workdirs.add(workdir)
        seen[backend] = (count + 1, workdirs)
    return seen


def ask_reason(seen: dict, window_hours: float, tags: list) -> str:
    if not seen:
        ran = "no vendor calls at all"
    else:
        parts = []
        for backend, (count, workdirs) in sorted(seen.items()):
            where = f", from {sorted(workdirs)[0]}" if workdirs else ""
            parts.append(f"{backend} ({count} call{'' if count == 1 else 's'}{where})")
        ran = ", ".join(parts)
    return (
        f"omo 2-family release gate: this command tags {', '.join(tags)}, and the "
        f"call ledger shows fewer than two vendor families in the last "
        f"{window_hours:g}h -- {ran}.\n"
        "Delegation ground 4 opens the two-family gate for anything about to ship "
        "(skills/omo/SKILL.md). The same prompt run against the same commit on a "
        "second family returned 11 reproducible defects with almost no overlap the "
        "one time it was measured (2026-08-30, commit b781d4a).\n"
        "Approve to tag anyway, or reject and run the second family first -- this "
        "is a question, not a block, and the cost is yours to weigh here. Window: "
        "OMO_FAMILY_GATE_HOURS (default 6)."
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or "tag" not in command:
        return 0        # cheap reject before paying for the lexer
    tags = release_tags(command)
    if not tags:
        return 0

    try:
        path = _ledger_path()
        if not path.is_file():
            return 0    # a GitHub runner has no ledger -- skip, never fail
        try:
            window_hours = float(os.environ.get("OMO_FAMILY_GATE_HOURS") or DEFAULT_WINDOW_HOURS)
        except ValueError:
            window_hours = DEFAULT_WINDOW_HOURS
        seen = recent_backends(path, window_hours)
    except Exception:
        return 0        # unreadable ledger, odd environment -- fail open
    if len(seen) >= 2:
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": ask_reason(seen, window_hours, tags),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Fail-open is the contract: a broken gate must never break a release.
        sys.exit(0)

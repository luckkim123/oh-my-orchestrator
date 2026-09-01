#!/usr/bin/env python3
"""Two omo hooks in one file: inject the session census, then require it be said.

The 2026-09-01 stonefish_ws session is the reason this exists. A user invoked
`/oh-my-orchestrator:omo` with "use omo's cross model a lot" written into the
brief; the session found codex, agy and gemini all absent, silently ran every
fan-out through native Claude agents instead, called the wrapper zero times,
never seeded the community store, and mentioned the backend gap in one line of
one status report. The user discovered the empty store themselves.

Every instruction that would have prevented that was prose in `skills/omo/`,
and prose is not a binding layer -- the same finding that retired tokensave,
CRG, and graphify's MCP server from this operator's vault, and the same one
`release-family-gate.py` already acts on for the 2-family rule. This is that
gate's sibling, aimed at the session's own preconditions.

Two events, one file, because they are two halves of one contract:

  UserPromptSubmit  -- the prompt names /omo, so MEASURE the three preconditions
                       (wrapper present and current, which backends are on PATH,
                       whether the store is seeded) and inject the result.
  PreToolUse        -- deny Agent/Task/Edit/Write until an `OMO ->` line has been
                       written since that injection.

Injection alone would not have fixed the incident: that session *had* the facts
(it checked `--version`, it checked the backends) and still did not surface
them. The enforcing half is what turns a measurement into a report.

`Bash` is deliberately NOT gated. It already carries release-family-gate, the
session needs it to run the very checks the census names, and the failure this
hook addresses was a fan-out, not a shell command.

Fails open on everything: no session id, no transcript, an unreadable state
file, any exception at all. A precondition gate that wedges a session over its
own broken instrument gets deleted, and a deleted gate is worth less than a
leaky one.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# `_harness_common` is the hooks-side declaration point for the store's root
# literal (store-spec.md 9.5, enforced by tests/test_paths_lint.py), so the
# names come from there rather than being retyped. Same optional-import shim
# every other hook uses: a missing helper degrades this hook's store field to
# UNKNOWN instead of breaking the session.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _harness_common as hc
except Exception:      # not ImportError -- a helper with a syntax error or a
    hc = None          # RuntimeError at import escapes main()'s own handler and
                       # exits 1 with a traceback (codex, 2026-09-01)

# The slash-command form only. A bare `omo` appears in prose about omo all the
# time -- including in the very defect reports that get pasted into these
# sessions -- and firing the census on every one of them would train the
# operator to ignore it.
# The trailing `(?![\w/:-])` is not decoration. `\b` matches between `o` and a
# hyphen or slash, so the first version fired on `/omo-init` and `/omo/rules.md`
# -- prompts merely NAMING this tooling armed the gate (agy, 2026-09-01). The
# leading class accepts a backtick, quote, or bracket for the opposite reason:
# `` `/omo audit` `` is an invocation and `(?:^|\s)` alone missed it.
# Anchored to the start of a LINE, which is where a slash command is actually
# typed. The two reviews pushed in opposite directions here and both were right
# about their own case: agy showed `` `/omo audit` `` failing `(?:^|\s)`, and
# codex showed `the user ran `/oh-my-orchestrator:omo` and it failed` -- a
# sentence out of a defect report, i.e. exactly the prompt this hook was written
# from -- arming the gate once backticks were accepted anywhere. The line anchor
# satisfies both: one opening delimiter is allowed before the slash, and nothing
# else is.
#
# The trailing `(?![\w/:-])` is not decoration either. `\b` matches between `o`
# and a hyphen or slash, so the first version fired on `/omo-init` and
# `/omo/rules.md` (agy).
_INVOCATION_RE = re.compile(
    r"""^[ \t]*["'`(\[*]?/(?:oh-my-orchestrator:)?omo(?![\w/:-])""", re.M)

# The acknowledgement, and it is a whole LINE, not a token anywhere in the text.
# A bare `OMO\s*(?:->|→)` search was satisfied by prose *about* the requirement --
# "I have not reported it yet; the required prefix is OMO ->" opened the gate with
# nothing reported (codex, 2026-09-01), which is the passing-mention the skill
# text forbids in so many words.
#
# Not an exact string match against the injected line either: that wedges on a
# stray space or a markdown wrapper, and a wedge is the worse failure. The line
# must instead *be* a census -- arrow plus all three field names -- which prose
# quoting the prefix does not accidentally satisfy. Leading `>`, `*`, backtick
# and whitespace are stripped first, since a model reporting to a user routinely
# writes the line inside a quote or a code span.
_ACK_LINE_RE = re.compile(
    r"""^[\s>*`_-]*OMO\s*(?:->|→).*wrapper:.*backends:.*store:""")


def _is_ack(text: str) -> bool:
    return any(_ACK_LINE_RE.search(ln) for ln in (text or "").splitlines())

# Exactly the CLI names `--backend` accepts, which is the registry in
# `codeagent-wrapper/internal/backend/registry.go` -- three, since omo D24
# (2026-08-28) cut `opencode` and REPLACED `gemini` with `agy`. Reporting a
# backend the wrapper cannot select would make the census lie in the direction
# that matters most; `test_backend_list_matches_registry` pins the two in sync.
# `claude` is last because it is the one that is always there, so leading with
# it would read as "backends: fine".
_BACKENDS = ("codex", "agy", "claude")

_SEMVER_RE = re.compile(r"(\d+\.\d+\.\d+)")


# --------------------------------------------------------------------------
# census
# --------------------------------------------------------------------------

def plugin_version() -> str:
    """The version this plugin's manifest declares, or "" if unreadable.

    CLAUDE_PLUGIN_ROOT is set for hooks the plugin declares; walking up from
    __file__ is the fallback for a direct invocation (a test, a manual run).
    """
    roots = []
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        roots.append(Path(env_root))
    roots.extend(Path(__file__).resolve().parents)
    for r in roots:
        manifest = r / ".claude-plugin" / "plugin.json"
        try:
            if manifest.is_file():
                return str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "")
        except Exception:
            continue
    return ""


def wrapper_status(want: str) -> str:
    """`codeagent-wrapper`'s state as one field.

    Three states worth distinguishing, because they need three different
    actions: absent (build it), present but older than the plugin (reinstall
    and symlink), current.

    The version string is `git describe` output, not a bare semver --
    `v0.21.5-1-g7573f4e-dirty` is a real reading from this operator's machine.
    So compare the extracted semver, and say plainly when there is none to
    extract rather than guessing: a wrapper built from the plugin CACHE (not a
    git checkout) stamps the literal "dev", which is the actual mechanism
    behind the "ldflags are missing" reading of the 2026-09-01 incident.
    """
    path = shutil.which("codeagent-wrapper")
    if not path:
        return "MISSING"
    try:
        out = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return "UNREADABLE"
    m = _SEMVER_RE.search(out)
    if not m:
        return "unstamped(built outside a git checkout)"
    got = m.group(1)
    if not want or got == want:
        return got
    return f"{got}!={want}(STALE)"


def hq_status() -> str:
    """Whether the store CLI is reachable, and whether that reach outlives today.

    Every omx/omp/omd reader shells out to `hq` by bare name, and a miss comes
    back as `{"ok": false, "count": 0}` beside a `pages: []` the caller reads
    first. Measured ksm-MS-7E01, 2026-09-01: 300 posts on disk, `hq` off PATH,
    and the operator read the store as lost.

    "Present" is not the answer. An `hq` that RESOLVES INTO a versioned
    plugin-cache directory dies at the next plugin update, and that is the
    default state -- nothing has ever linked it anywhere stable. The test is on
    the realpath, not the PATH hit: `/usr/local/bin/hq -> …/cache/0.22.0/bin/hq`
    looks stable and is not (codex, 2026-09-01).

    And it names the RIGHT fix. When the cache directory sits ahead of the
    installed shim on PATH, bare `hq` keeps resolving there and re-running
    `omo-init` cannot change it -- that is an ordering problem, not a missing
    file, and saying "run omo-init" to someone who just did is a loop.
    """
    path = shutil.which("hq")
    if not path:
        return "MISSING(run omo-init)"
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    cache = os.path.join(str(Path.home()), ".claude", "plugins", "cache") + os.sep
    if not real.startswith(cache):
        return "ok"
    shim = Path.home() / ".local" / "bin" / "hq"
    if shim.exists():
        return "shadowed(plugin cache precedes ~/.local/bin on PATH; reorder PATH)"
    return "version-pinned(dies on plugin update; run omo-init)"


def backend_status() -> str:
    present = [b for b in _BACKENDS if shutil.which(b)]
    if not present:
        return "NONE"
    if present == ["claude"]:
        return "claude-only"
    return ",".join(present)


def find_store(start: Path):
    """Nearest ancestor holding the store root directory, or None.

    Deliberately does NOT require the `.anchor` file. An unseeded store is
    exactly what this census exists to report, and demanding the anchor would
    make the most important finding look like "no store here at all".
    """
    if hc is None:
        return None
    try:
        for d in [start] + list(start.parents):
            if (d / hc.HQ_ROOT).is_dir():
                return d / hc.HQ_ROOT
    except Exception:
        pass
    return None


def store_status(cwd: Path) -> str:
    if hc is None:
        return "UNKNOWN(helper-missing)"
    hq = find_store(cwd)
    if hq is None:
        return "NO-ANCHOR"
    # An unreadable directory, a broken symlink, a permission wall: the glob and
    # the is_file() both raise, and this function is called from `omo-init` where
    # an OSError is a traceback rather than a census.
    try:
        community = hq.parent / hc.HQ_COMMUNITY_REL
        rules = community / "rules"
        seeded_rules = rules.is_dir() and any(rules.glob("*.md"))
        has_hub = (community / "HUB.md").is_file()
    except OSError as e:
        return f"UNKNOWN(unreadable: {type(e).__name__})"
    if seeded_rules and has_hub:
        return "seeded"
    missing = []
    if not seeded_rules:
        missing.append("rules/")
    if not has_hub:
        missing.append("HUB.md")
    return "UNSEEDED(" + "+".join(missing) + ")"


def census_line(cwd: Path) -> str:
    return (
        f"OMO -> wrapper:{wrapper_status(plugin_version())} "
        f"backends:{backend_status()} hq:{hq_status()} store:{store_status(cwd)}"
    )


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def state_path(session_id: str):
    if not session_id:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]
    base = os.environ.get("OMO_CENSUS_DIR")
    if base:
        d = Path(base)
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "omo"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = Path(tempfile.gettempdir())
    return d / f"census-{safe}.json"


def transcript_size(payload):
    """Bytes in the transcript right now, or None if it cannot be read.

    None, not 0. Returning 0 for "could not stat" makes the next turn scan the
    whole file and accept an acknowledgement written for an EARLIER turn -- the
    exact property the offset exists to prevent (agy, 2026-09-01). The caller
    treats None as "cannot bound this", which fails open.
    """
    try:
        return Path(str(payload.get("transcript_path") or "")).stat().st_size
    except Exception:
        return None


def acknowledged_since(transcript: str, offset) -> bool:
    """True iff an `OMO ->` line was written after byte `offset` of the transcript.

    A byte offset rather than a timestamp comparison: the offset is exact, needs
    no clock parsing, and its one failure mode (the transcript was truncated or
    rotated, so the offset now points past the end) resolves by scanning the
    whole file -- which can only produce a false PASS. For a gate that must
    never wedge a session, that is the correct direction to be wrong in.

    **A transcript that cannot be read at all returns True, not False.** The
    first version returned False, which reads as "not acknowledged" and denies
    -- and since re-emitting the line cannot make an absent file appear, the
    session was wedged permanently, with no way out (agy, 2026-09-01). This hook
    fails open on a missing instrument like every other hook in this repo; the
    instrument here is the transcript.
    """
    if offset is None:
        return True
    try:
        p = Path(transcript)
        if not p.is_file():
            return True
        size = p.stat().st_size
        start = offset if 0 <= offset <= size else 0
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(start)
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                # A row that parses but is not an object -- a bare `[]` -- made
                # `rec.get` raise, and the outer handler then denied every retry
                # forever (codex, 2026-09-01). One junk row is skipped and the
                # rows after it still count, the same policy release-family-gate
                # applies to its own ledger.
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                msg = rec.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                # Assistant content is a block list, but a string has been
                # observed on the user side of this same schema, so accept both
                # rather than silently reading nothing.
                if isinstance(content, str):
                    if _is_ack(content):
                        return True
                    continue
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        if _is_ack(str(block.get("text") or "")):
                            return True
    except Exception:
        # Every failure of the instrument fails OPEN, including one nobody
        # anticipated. Returning False here reads as "not acknowledged", and
        # since no amount of re-emitting fixes a broken reader, that wedges the
        # session permanently -- the worst outcome available (codex, 2026-09-01).
        return True
    return False


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------

_GATED_TOOLS = {"Agent", "Task", "Edit", "Write", "NotebookEdit"}

_GUIDANCE = """\
Say this line to the user before your first delegation or edit, verbatim, on its own line.
It is the whole point of the measurement: the 2026-09-01 incident had all three of these
facts available and surfaced none of them.

Then act on what it says:
  wrapper MISSING/STALE  -> `python3 bin/omo-init --wrapper-only` (or say you are skipping it)
  backends claude-only   -> you are in DEGRADED mode. Read `skills/omo/SKILL.md` section
                            "Degraded Mode"; native delegation is fine, silent native
                            delegation is not.
  store UNSEEDED         -> offer `python3 bin/omo-init`. Do not seed silently and do not
                            proceed silently; the user decides.
  store NO-ANCHOR        -> there is no store at all here. Offer
                            `python3 bin/omo-init --create`; the flag is required
                            and the plain form exits 2 by design, because creating
                            a store root is the user's decision."""


def on_prompt(payload) -> int:
    prompt = str(payload.get("prompt") or "")
    if not _INVOCATION_RE.search(prompt):
        return 0
    try:
        cwd = Path(str(payload.get("cwd") or os.getcwd()))
    except Exception:
        cwd = Path(".")
    line = census_line(cwd)

    sp = state_path(str(payload.get("session_id") or ""))
    if sp is not None:
        try:
            sp.write_text(
                json.dumps({"line": line, "offset": transcript_size(payload)}),
                encoding="utf-8",
            )
        except Exception:
            pass

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": f"{line}\n\n{_GUIDANCE}",
    }}, ensure_ascii=False))
    return 0


def on_pretool(payload) -> int:
    if str(payload.get("tool_name") or "") not in _GATED_TOOLS:
        return 0
    sp = state_path(str(payload.get("session_id") or ""))
    if sp is None or not sp.is_file():
        return 0
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if state.get("done"):
        return 0
    if acknowledged_since(str(payload.get("transcript_path") or ""), state.get("offset")):
        try:
            state["done"] = True
            sp.write_text(json.dumps(state), encoding="utf-8")
        except Exception:
            pass
        return 0

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "omo session preconditions have not been reported. Emit this line "
            "on its own line first, then retry:\n\n"
            f"{state.get('line') or census_line(Path('.'))}\n\n" + _GUIDANCE
        ),
    }}, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    event = str(payload.get("hook_event_name") or "")
    try:
        if event == "UserPromptSubmit":
            return on_prompt(payload)
        if event == "PreToolUse":
            return on_pretool(payload)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

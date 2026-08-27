#!/usr/bin/env python3
"""SubagentStart hook — inject the role card, observe board mismatches.

This hook cannot block a spawn. Measured on claude 2.1.239: both `exit 2` and a
JSON `blockingError` were tried and the subagent ran normally either way, because
the SubagentStart output schema carries exactly one field (`additionalContext`)
and the call site does not cancel the spawn on the hook's result. Its stderr is
also invisible to the user.

So it does two things only:

1. **Inject.** The role's board row and accumulated memory, as
   `hookSpecificOutput.additionalContext`. Only the nested form is honored --
   a top-level `additionalContext` is ignored -- and the payload is capped at
   10000 characters, above which Claude Code truncates it to a preview.
2. **Observe.** Board mismatches are appended to `.orchestration/observations.jsonl`
   and restated inside the injected context, so the subagent itself can report
   them. SubagentStop is where they are enforced.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _harness_common as hc
except ImportError:
    hc = None  # type: ignore[assignment]

# Measured threshold: 9800 characters arrive intact, 10400 are truncated to a
# preview and written to an external file the subagent has to go read.
MAX_CONTEXT_CHARS = 10000
RESERVE_FOR_NOTICES = 1500  # notices survive truncation; role memory gives way


def _observations_path(root: Path) -> Path:
    return hc.observations_jsonl(root)


def _record(root: Path, entry: dict[str, Any]) -> None:
    """Append one observation. Best-effort: never raises into the hook."""
    try:
        p = _observations_path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def check_board(state: dict[str, Any], role: str) -> list[str]:
    """Mismatches between this spawn and the board. Empty list means clean.

    An empty roster is not a mismatch: a campaign that declared no workers cannot
    judge membership, and rejecting every ad-hoc subagent is the false positive
    that gets a hook switched off.
    """
    workers = hc.board_workers(state)
    if not workers:
        return []

    notices: list[str] = []
    matching = [w for w in workers if str(w.get("role") or "").strip() == role]

    if not matching:
        notices.append(
            f"role '{role}' is not on the board. Either it was spawned outside the "
            "campaign, or workers[] is missing a row for it."
        )
        return notices

    if len(matching) > 1:
        notices.append(
            f"role '{role}' has {len(matching)} rows on the board. Roles are unique; "
            "the vendor and model this worker should use is ambiguous."
        )

    w = matching[0]
    if not str(w.get("model") or "").strip():
        notices.append(
            f"role '{role}' has no model on the board. Diversity is counted in models, "
            "so an unset one cannot satisfy a three-strike escalation."
        )
    return notices


def build_context(root: Path, role: str, state: dict[str, Any], notices: list[str]) -> str:
    parts: list[str] = [f"# Role: {role}"]

    w = hc.find_worker(state, role)
    if w:
        parts.append(
            "\n## Board row\n"
            f"- vendor: {w.get('vendor') or 'unset'}\n"
            f"- model: {w.get('model') or 'unset'}\n"
            f"- writes_repo: {bool(w.get('writes_repo'))}\n"
            f"- worktree: {w.get('worktree') or 'none'}\n"
            f"- status: {w.get('status') or 'unset'}"
        )

    if notices:
        parts.append(
            "\n## Board mismatch — report this before you do anything else\n"
            + "\n".join(f"- {n}" for n in notices)
            + "\n\nThis hook cannot stop a spawn and its stderr never reaches the user, "
            "so you are the only path this notice has to a human. Say it out loud in "
            "your first message. SubagentStop will hold your exit over it."
        )

    memory = hc.agent_memory_md(root, role)
    if memory.is_file():
        try:
            body = memory.read_text(encoding="utf-8").strip()
        except Exception:
            body = ""
        if body:
            budget = MAX_CONTEXT_CHARS - RESERVE_FOR_NOTICES - len("\n".join(parts))
            if len(body) > budget > 0:
                body = body[:budget].rstrip() + "\n[...truncated to fit the injection cap]"
            parts.append(f"\n## What this role has learned\n\n{body}")
    else:
        parts.append(
            f"\n## What this role has learned\n\nNothing yet -- "
            f".orchestration/agents/{role}.md does not exist. Write it before you "
            "stop: 40 lines maximum, semantic rather than chronological, append-only."
        )

    out = "\n".join(parts)
    return out[:MAX_CONTEXT_CHARS] if len(out) > MAX_CONTEXT_CHARS else out


def main() -> int:
    if hc is None:
        return 0
    payload = hc.read_hook_payload()

    root = hc.find_harness_root(payload)
    if root is None:
        return 0

    # store-spec.md §6 row 4: a corrupt .hq/.anchor (or an unparseable
    # board.json under one) must fail loud, not be silently read as an
    # inactive/absent store the way is_harness_active() below reads it.
    # (This hook's own docstring measured that exit 2 does not stop the
    # spawn and its stderr is invisible -- wiring it anyway keeps behavior
    # uniform with the other five hooks and costs nothing this hook does
    # not already accept.)
    corrupt_reason = hc.gate_corrupt_reason(root)
    if corrupt_reason is not None:
        sys.stderr.write(f"HARNESS: gate corrupt — {corrupt_reason}\n")
        return 2

    if not hc.is_harness_active(root):
        return 0

    role = str(payload.get("agent_type") or "").strip()
    if not role:
        return 0

    try:
        state = hc.load_state(root)
    except Exception:
        return 0  # the stop hook reports a corrupt board; do not double-report

    notices = check_board(state, role)
    if notices:
        _record(root, {
            "ts": hc.iso_z(hc.utc_now()),
            "event": "board_mismatch",
            "role": role,
            "agent_id": payload.get("agent_id"),
            "session_id": payload.get("session_id"),
            "notices": notices,
        })

    context = build_context(root, role, state, notices)
    if context.strip():
        hc.emit_json({"hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": context,
        }})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

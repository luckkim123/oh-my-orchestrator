#!/usr/bin/env python3
"""Harness SubagentStop hook — blocks subagents from stopping when they
have assigned harness tasks still in progress.

Uses the same decision format as Stop hooks:
  {"decision": "block", "reason": "..."}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Board resolution and the activation gate live in one place; a hook that carried
# its own copy would drift the moment the gate changed. Missing helper module =>
# every hook is a no-op, which is the fail-open contract.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _harness_common as hc
except ImportError:
    hc = None  # type: ignore[assignment]



def _read_hook_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _find_harness_root(payload: dict[str, Any]) -> Optional[Path]:
    """Locate the root holding .hq/runtime/board.json, .orchestration/board.json,
    or harness-tasks.json."""
    if hc is None:
        return None
    return hc.find_harness_root(payload)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return data


def _is_harness_active(root: Path) -> bool:
    """True when hooks are live: board.json.status == "active".

    A closed campaign keeps its board on disk, so presence cannot mean active.
    Roots that have not migrated still gate on the .harness-active marker.
    """
    if hc is None:
        return False
    return hc.is_harness_active(root)


def _reject(message: str) -> int:
    """Hold the subagent's exit.

    exit 2 with stderr is the measured blocking protocol for SubagentStop: the
    subagent is forced to resume and the stderr reaches it. A JSON
    `decision: "block"` was never verified to gate this event, and an unverified
    blocking path is how a hook ends up dead without anyone noticing.

    The caller must have checked `stop_hook_active` first -- Claude Code sets it
    on the resumed turn and provides no cutoff of its own, so the loop guard is
    ours to hold.
    """
    sys.stderr.write("HARNESS: " + message + "\n")
    return 2


def _campaign_failures(root: Path, state: dict[str, Any], role: str) -> list[str]:
    """What this worker owes the campaign before it may stop."""
    if hc is None or not role:
        return []
    workers = hc.board_workers(state)
    if not workers:
        return []

    w = hc.find_worker(state, role)
    if w is None:
        return [
            f"role '{role}' is not registered in board.json workers[]. Either add "
            "the row, or spawn it outside an active campaign."
        ]

    failures: list[str] = []

    memory = hc.agent_memory_md(root, role)
    if not memory.is_file():
        failures.append(
            f"{memory.relative_to(root)} does not exist. Write what this role "
            "learned -- 40 lines maximum, semantic rather than chronological, "
            "append-only -- so the next spawn of this role does not start blind."
        )

    status = str(w.get("status") or "").strip()
    if status not in ("reported", "closed"):
        posts_dir = hc.community_posts_dir(root)
        failures.append(
            f"board status for '{role}' is '{status or 'unset'}'. A worker reports "
            f"before it stops: land the post under {posts_dir.relative_to(root)}/ and "
            "set workers[].status to 'reported'. Reporting is what ends the work, not "
            "finishing it quietly."
        )
    return failures


def main() -> int:
    payload = _read_hook_payload()

    # Safety: respect stop_hook_active to prevent infinite loops
    if payload.get("stop_hook_active", False):
        return 0

    root = _find_harness_root(payload)
    if root is None:
        return 0  # no harness project, allow stop

    # store-spec.md §6 row 4: a corrupt .hq/.anchor (or an unparseable
    # board.json under one) must fail loud, not be silently read as an
    # inactive/absent store the way _is_harness_active() below reads it.
    corrupt_reason = hc.gate_corrupt_reason(root) if hc else None
    if corrupt_reason is not None:
        sys.stderr.write(f"HARNESS: gate corrupt — {corrupt_reason}\n")
        return 2

    # Guard: only active when harness skill is triggered
    if not _is_harness_active(root):
        return 0

    tasks_path = hc.state_path(root) if hc else (root / "harness-tasks.json")
    try:
        state = _load_json(tasks_path)
        session_config = state.get("session_config") or {}
        if not isinstance(session_config, dict):
            session_config = {}
        is_concurrent = str(session_config.get("concurrency_mode") or "exclusive") == "concurrent"
        tasks_raw = state.get("tasks") or []
        if not isinstance(tasks_raw, list):
            return 0
        tasks = [t for t in tasks_raw if isinstance(t, dict)]
    except Exception:
        return 0

    in_progress = [t for t in tasks if str(t.get("status", "")) == "in_progress"]
    worker_id = str(os.environ.get("HARNESS_WORKER_ID") or "").strip()
    agent_id = str(payload.get("agent_id") or "").strip()
    teammate_name = str(payload.get("teammate_name") or "").strip()
    identities = {x for x in (worker_id, agent_id, teammate_name) if x}

    if is_concurrent and in_progress and not identities:
        return _reject(
            "concurrent mode, but this subagent has no worker identity "
            "(HARNESS_WORKER_ID / agent_id / teammate_name are all empty). "
            "Stopping now would leave the in-progress task dangling with no owner."
        )

    if is_concurrent:
        owned = [
            t for t in in_progress
            if str(t.get("claimed_by") or "") in identities
        ] if identities else []
    else:
        owned = in_progress

    # Only hold the exit when this subagent still owns in-progress work.
    if owned:
        tid = str(owned[0].get("id") or "")
        title = str(owned[0].get("title") or "")
        return _reject(
            f"task [{tid}] {title} is still in_progress and owned by you. "
            "Run its validation command, record the outcome, and then stop."
        )

    # Campaign obligations. Only enforced against a declared roster: an empty
    # workers[] means the campaign cannot judge membership, and rejecting every
    # ad-hoc subagent is the false positive that gets a hook switched off.
    role = str(payload.get("agent_type") or "").strip()
    failures = _campaign_failures(root, state, role)
    if failures:
        return _reject(
            "this subagent has not met its campaign obligations:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )

    return 0  # all done, allow stop


if __name__ == "__main__":
    raise SystemExit(main())

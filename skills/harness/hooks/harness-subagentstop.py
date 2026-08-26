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
    """Locate the root holding .orchestration/board.json or harness-tasks.json."""
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


def main() -> int:
    payload = _read_hook_payload()

    # Safety: respect stop_hook_active to prevent infinite loops
    if payload.get("stop_hook_active", False):
        return 0

    root = _find_harness_root(payload)
    if root is None:
        return 0  # no harness project, allow stop

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
        reason = (
            "HARNESS: concurrent 模式缺少 worker identity（HARNESS_WORKER_ID/agent_id）。"
            "为避免误停导致任务悬空，本次阻止停止。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return 0

    if is_concurrent:
        owned = [
            t for t in in_progress
            if str(t.get("claimed_by") or "") in identities
        ] if identities else []
    else:
        owned = in_progress

    # Only block when this subagent still owns in-progress work.
    if owned:
        tid = str(owned[0].get("id") or "")
        title = str(owned[0].get("title") or "")
        reason = (
            f"HARNESS: 子代理仍有进行中的任务 [{tid}] {title}。"
            "请完成当前任务的验证和记录后再停止。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return 0

    return 0  # all done, allow stop


if __name__ == "__main__":
    raise SystemExit(main())

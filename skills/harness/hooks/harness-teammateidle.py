#!/usr/bin/env python3
"""Harness TeammateIdle hook — prevents teammates from going idle when
harness tasks remain eligible for execution.

Exit code 2 + stderr message keeps the teammate working.
Exit code 0 allows the teammate to go idle.
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


def _priority_rank(v: Any) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(str(v or ""), 9)


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
    root = _find_harness_root(payload)
    if root is None:
        return 0  # no harness project, allow idle

    # Guard: only active when harness skill is triggered
    if not _is_harness_active(root):
        return 0

    tasks_path = hc.state_path(root) if hc else (root / "harness-tasks.json")
    try:
        state = _load_json(tasks_path)
        tasks_raw = state.get("tasks") or []
        if not isinstance(tasks_raw, list):
            return 0
        tasks = [t for t in tasks_raw if isinstance(t, dict)]
    except Exception:
        return 0  # can't read state, allow idle

    completed = {str(t.get("id", "")) for t in tasks if str(t.get("status", "")) == "completed"}

    def deps_ok(t: dict[str, Any]) -> bool:
        deps = t.get("depends_on") or []
        if not isinstance(deps, list):
            return False
        return all(str(d) in completed for d in deps)

    def attempts(t: dict[str, Any]) -> int:
        try:
            return int(t.get("attempts") or 0)
        except Exception:
            return 0

    def max_attempts(t: dict[str, Any]) -> int:
        try:
            v = t.get("max_attempts")
            return int(v) if v is not None else 3
        except Exception:
            return 3

    pending = [t for t in tasks if str(t.get("status", "")) == "pending" and deps_ok(t)]
    retryable = [
        t for t in tasks
        if str(t.get("status", "")) == "failed"
        and attempts(t) < max_attempts(t)
        and deps_ok(t)
    ]
    def key(t: dict[str, Any]) -> tuple[int, str]:
        return (_priority_rank(t.get("priority")), str(t.get("id", "")))
    pending.sort(key=key)
    retryable.sort(key=key)
    in_progress = [t for t in tasks if str(t.get("status", "")) == "in_progress"]

    # Check if this teammate owns any in-progress tasks
    worker_id = os.environ.get("HARNESS_WORKER_ID") or ""
    teammate_name = payload.get("teammate_name", "")
    owned = [
        t for t in in_progress
        if str(t.get("claimed_by") or "") in (worker_id, teammate_name)
    ] if (worker_id or teammate_name) else []

    if owned:
        tid = str(owned[0].get("id") or "")
        title = str(owned[0].get("title") or "")
        sys.stderr.write(
            f"HARNESS: 你仍有进行中的任务 [{tid}] {title}。"
            "请继续执行或完成该任务后再停止。\n"
        )
        return 2  # block idle

    if pending or retryable:
        next_t = pending[0] if pending else retryable[0]
        tid = str(next_t.get("id") or "")
        title = str(next_t.get("title") or "")
        sys.stderr.write(
            f"HARNESS: 仍有 {len(pending)} 个待执行 + {len(retryable)} 个可重试任务。"
            f"下一个: [{tid}] {title}。请继续执行。\n"
        )
        return 2  # block idle

    return 0  # all done, allow idle


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

# Board resolution and the activation gate live in one place; a hook that carried
# its own copy would drift the moment the gate changed. Missing helper module =>
# every hook is a no-op, which is the fail-open contract.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _harness_common as hc
except ImportError:
    hc = None  # type: ignore[assignment]


def main() -> int:
    payload = hc.read_hook_payload() if hc else {}
    root = hc.find_harness_root(payload) if hc else None
    if root is None:
        print(json.dumps({"renewed": False, "error": "state root not found"}, ensure_ascii=False))
        return 0

    task_id = os.environ.get("HARNESS_TASK_ID") or str(payload.get("task_id") or "").strip()
    if not task_id:
        print(json.dumps({"renewed": False, "error": "missing task_id"}, ensure_ascii=False))
        return 0

    worker_id = os.environ.get("HARNESS_WORKER_ID") or ""
    if not worker_id:
        print(json.dumps({"renewed": False, "error": "missing HARNESS_WORKER_ID"}, ensure_ascii=False))
        return 0
    lease_seconds = int(os.environ.get("HARNESS_LEASE_SECONDS") or "1800")

    tasks_path = hc.state_path(root)
    lockdir = hc.lockdir_for_root(root)

    timeout_s = float(os.environ.get("HARNESS_LOCK_TIMEOUT_SECONDS") or "5")
    try:
        hc.acquire_lock(lockdir, timeout_s)
    except Exception as e:
        print(json.dumps({"renewed": False, "error": str(e)}, ensure_ascii=False))
        return 0

    try:
        state = hc.load_json(tasks_path)
        tasks = hc.parse_tasks(state)

        task = next((t for t in tasks if str(t.get("id") or "") == task_id), None)
        if task is None:
            print(json.dumps({"renewed": False, "error": "task not found"}, ensure_ascii=False))
            return 0

        if str(task.get("status") or "") != "in_progress":
            print(json.dumps({"renewed": False, "error": "task not in_progress"}, ensure_ascii=False))
            return 0

        claimed_by = str(task.get("claimed_by") or "")
        if claimed_by and claimed_by != worker_id:
            print(json.dumps({"renewed": False, "error": "task owned by other worker"}, ensure_ascii=False))
            return 0

        now = hc.utc_now()
        exp = now + _dt.timedelta(seconds=lease_seconds)
        task["lease_expires_at"] = hc.iso_z(exp)
        task["claimed_by"] = worker_id
        state["tasks"] = tasks
        hc.atomic_write_json(tasks_path, state)

        print(json.dumps({"renewed": True, "task_id": task_id, "lease_expires_at": task["lease_expires_at"]}, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"renewed": False, "error": str(e)}, ensure_ascii=False))
        return 0
    finally:
        hc.release_lock(lockdir)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import datetime as _dt
import json
import os
import socket
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
        print(json.dumps({"claimed": False, "error": "state root not found"}, ensure_ascii=False))
        return 0

    tasks_path = hc.state_path(root)
    lockdir = hc.lockdir_for_root(root)

    timeout_s = float(os.environ.get("HARNESS_LOCK_TIMEOUT_SECONDS") or "5")
    hc.acquire_lock(lockdir, timeout_s)
    try:
        state = hc.load_json(tasks_path)
        tasks = hc.parse_tasks(state)
        is_concurrent = hc.is_concurrent(hc.get_session_config(state))

        now = hc.utc_now()
        if hc.reap_stale_leases(tasks, now):
            state["tasks"] = tasks
            hc.atomic_write_json(tasks_path, state)

        # Retryability is judged on the same failure count the Stop hook
        # enforces -- max(attempts, logged ERROR lines) -- so a task the Stop
        # hook already ruled out cannot be claimed back into rotation by a
        # session that never bumped `attempts`.
        logged = hc.progress_logged_failures(root)
        pending, retry = hc.eligible_tasks(tasks, logged)
        task = hc.pick_next(pending, retry)
        if task is None:
            print(json.dumps({"claimed": False}, ensure_ascii=False))
            return 0

        worker_id = os.environ.get("HARNESS_WORKER_ID") or ""
        if is_concurrent and not worker_id:
            print(json.dumps({"claimed": False, "error": "missing HARNESS_WORKER_ID"}, ensure_ascii=False))
            return 0
        if not worker_id:
            worker_id = f"{socket.gethostname()}:{os.getpid()}"
        lease_seconds = int(os.environ.get("HARNESS_LEASE_SECONDS") or "1800")
        exp = now + _dt.timedelta(seconds=lease_seconds)

        task["status"] = "in_progress"
        task["claimed_by"] = worker_id
        task["claimed_at"] = hc.iso_z(now)
        task["lease_expires_at"] = hc.iso_z(exp)
        state["tasks"] = tasks
        hc.atomic_write_json(tasks_path, state)

        out = {
            "claimed": True,
            "worker_id": worker_id,
            "task_id": str(task.get("id") or ""),
            "title": str(task.get("title") or ""),
            "lease_expires_at": task["lease_expires_at"],
        }
        print(json.dumps(out, ensure_ascii=False))
        return 0
    finally:
        hc.release_lock(lockdir)


if __name__ == "__main__":
    raise SystemExit(main())

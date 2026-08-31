#!/usr/bin/env python3
"""Harness TeammateIdle hook — prevents teammates from going idle when
harness tasks remain eligible for execution.

Exit code 2 + stderr message keeps the teammate working.
Exit code 0 allows the teammate to go idle.
"""
from __future__ import annotations

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
        return 0  # no harness project, allow idle

    # store-spec.md §6 row 4: a corrupt .hq/.anchor (or an unparseable
    # board.json under one) must fail loud, not be silently read as an
    # inactive/absent store the way _is_harness_active() below reads it.
    corrupt_reason = hc.gate_corrupt_reason(root) if hc else None
    if corrupt_reason is not None:
        sys.stderr.write(f"HARNESS: gate corrupt — {corrupt_reason}\n")
        return 2

    # Guard: only active when harness skill is triggered
    if not hc.is_harness_active(root):
        return 0

    tasks_path = hc.state_path(root)
    try:
        state = hc.load_json(tasks_path)
        tasks = hc.parse_tasks(state)
    except Exception:
        return 0  # can't read state, allow idle

    # Retryability uses the same failure count the Stop hook enforces --
    # max(attempts, logged ERROR lines) -- so a task the Stop hook already
    # ruled out cannot keep a teammate awake here.
    pending, retryable = hc.eligible_tasks(tasks, hc.progress_logged_failures(root))
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
            f"HARNESS: task [{tid}] {title} is still in_progress and owned by you. "
            "Finish it or hand it back before going idle.\n"
        )
        return 2  # block idle

    if pending or retryable:
        next_t = pending[0] if pending else retryable[0]
        tid = str(next_t.get("id") or "")
        title = str(next_t.get("title") or "")
        sys.stderr.write(
            f"HARNESS: {len(pending)} eligible and {len(retryable)} retryable tasks remain. "
            f"Next: [{tid}] {title}. Continue.\n"
        )
        return 2  # block idle

    return 0  # all done, allow idle


if __name__ == "__main__":
    raise SystemExit(main())

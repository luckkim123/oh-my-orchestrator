#!/usr/bin/env python3
from __future__ import annotations

import json
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
        return 0

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
    progress_path = root / "harness-progress.txt"

    try:
        state = hc.load_json(tasks_path)
        tasks = hc.parse_tasks(state)
    except Exception as e:
        context = f"HARNESS: CONFIG error: cannot read {tasks_path.name}: {e}"
        print(json.dumps({"hookSpecificOutput": {"additionalContext": context}}, ensure_ascii=False))
        return 0

    counts = hc.status_counts(tasks)

    # Same failure count the enforcing hooks use -- a task Stop/claim already
    # ruled out must not be advertised as `next=` here (codex review 2026-08-31).
    pending, retry = hc.eligible_tasks(tasks, hc.progress_logged_failures(root))
    next_task = hc.pick_next(pending, retry)
    next_hint = ""
    if next_task is not None:
        tid = str(next_task.get("id") or "")
        title = str(next_task.get("title") or "").strip()
        next_hint = f" next={tid}{(': ' + title) if title else ''}"

    last_stats = ""
    if progress_path.is_file():
        tail = hc.tail_text(progress_path, 8192)
        lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
        for ln in reversed(lines[-200:]):
            if " STATS " in f" {ln} " or ln.endswith(" STATS"):
                last_stats = ln
                break
        if not last_stats and lines:
            last_stats = lines[-1]
        if len(last_stats) > 220:
            last_stats = last_stats[:217] + "..."

    summary = (
        "HARNESS: "
        + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        + f" total={len(tasks)}"
        + next_hint
    ).strip()
    if last_stats:
        summary += f"\nHARNESS: last_log={last_stats}"

    print(json.dumps({"hookSpecificOutput": {"additionalContext": summary}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Harness Stop hook — blocks Claude from stopping when eligible tasks remain.

Uses `stop_hook_active` field and a consecutive-block counter to prevent
infinite loops. If the hook blocks N times in a row without any task
completing, it allows the stop with a warning.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Board resolution and the activation gate live in one place; a hook that carried
# its own copy would drift the moment the gate changed. Missing helper module =>
# every hook is a no-op, which is the fail-open contract.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _harness_common as hc
except ImportError:
    hc = None  # type: ignore[assignment]


MAX_CONSECUTIVE_BLOCKS = 8  # safety valve
ESCALATE_AFTER_ATTEMPTS = 2  # omo delegation ground 3: two failures, then a different prior


def _block_counter_path(root: Path) -> Path:
    return root / ".harness-stop-counter"


def _read_block_counter(root: Path) -> tuple[int, int]:
    """Returns (consecutive_blocks, last_completed_count)."""
    p = _block_counter_path(root)
    try:
        raw = p.read_text("utf-8").strip()
        parts = raw.split(",")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return 0, 0


def _write_block_counter(root: Path, blocks: int, completed: int) -> None:
    p = _block_counter_path(root)
    tmp = p.with_name(f"{p.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(f"{blocks},{completed}", encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _reset_block_counter(root: Path) -> None:
    p = _block_counter_path(root)
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass


def _validation_command(t: dict[str, Any]) -> str:
    v = t.get("validation")
    if not isinstance(v, dict):
        return ""
    return str(v.get("command") or "").strip()


def _integrity_failures(tasks: list[dict[str, Any]]) -> list[str]:
    """Completion claims the file cannot back up.

    Premature completion is the harness's named #1 failure mode, and the skill
    already says not to declare it without an objective check. Prose the model may
    follow is not a rule -- this is the same gap the 3-strike count had. A task
    marked completed with no validation command is a claim with nothing behind it.

    started_at_commit is the other half: without it there is no commit to reset to,
    so a failure has no rollback and the tree keeps whatever the attempt left.
    """
    failures: list[str] = []
    for t in tasks:
        tid = str(t.get("id") or "?")
        status = str(t.get("status") or "")
        if status == "completed" and not _validation_command(t):
            failures.append(
                f"[{tid}] is completed with no validation.command. Either add the "
                "command and run it, or set the task back to failed. A completion "
                "nothing can check is not a completion."
            )
        if status == "in_progress" and not str(t.get("started_at_commit") or "").strip():
            failures.append(
                f"[{tid}] is in_progress with no started_at_commit. There is no commit "
                "to reset to, so this task cannot be rolled back if it fails. Record "
                "the base commit now, before the work goes further."
            )
    return failures


def _cost_unrecorded(state: dict[str, Any]) -> str:
    """A campaign about to close without having said what it cost.

    The Stop payload cannot supply the number. Measured 2026-08-26 on claude
    2.1.239, its keys are background_tasks, cwd, effort, hook_event_name,
    last_assistant_message, permission_mode, prompt_id, session_crons, session_id,
    stop_hook_active, transcript_path -- no cost, no token counts.

    So a session inside this hook often has no way to measure its own spend, and
    the first version of this gate demanded a number anyway. A live test on
    2026-08-26 showed exactly what that produces: the session wrote 21000, a
    figure it had invented, because inventing was the only way past the gate.
    A check that can only be satisfied by fabrication is worse than no check --
    it manufactures the false data the harness exists to prevent.

    So the gate asks for a statement, not a figure. "unmeasured" discharges it.
    """
    cost = state.get("cost")
    if not isinstance(cost, dict):
        return ""
    actual = cost.get("actual_tokens")
    if actual is not None:
        return ""
    est = cost.get("estimated_tokens")
    return (
        "HARNESS: the campaign is closing and cost.actual_tokens is still null"
        + (f" (estimated {est})." if est else ".")
        + "\nIf you know what it cost, write the number. **If you cannot measure it "
        "from here, write the string \"unmeasured\" -- do not invent a figure.** A "
        "fabricated cost is worse than a missing one: the next estimate gets scored "
        "against it and comes out confidently wrong.\nEither value closes this gate."
    )


def _escalation_notice(task_id: str, tried: int) -> str:
    """The 3-strike rule, stated as a requirement rather than left to judgment.

    Both myclaude and cco leave "two failures, then escalate" as advice the model
    may or may not act on. Emitting it from the hook, keyed off a count the hook
    derived itself, is what turns it into a rule.
    """
    return (
        f"\n\nESCALATION REQUIRED — {task_id} has failed {tried} times.\n"
        "A third attempt at the same approach is not a retry, it is the same failure again.\n"
        "Before running it, change one of these and say which:\n"
        "  1. The vendor. Route this task to a different MODEL than the last attempt used "
        "(different backend running the same model family does not count). "
        "This is omo delegation ground 3.\n"
        "  2. The approach. State the new hypothesis and how it differs from the two that failed.\n"
        "The retry prompt MUST carry both prior attempts and what you observed, not just the "
        "symptom. A retry without that context repeats the work that produced the failures.\n"
        "If neither can change, mark the task blocked with the evidence and move on."
    )


def main() -> int:
    payload = hc.read_hook_payload() if hc else {}

    # Safety: if stop_hook_active is True, Claude is already continuing
    # from a previous Stop hook block. Check if we should allow stop
    # to prevent infinite loops.
    stop_hook_active = payload.get("stop_hook_active", False)

    root = hc.find_harness_root(payload) if hc else None
    if root is None:
        return 0  # no harness project, allow stop

    # store-spec.md §6 row 4: a corrupt .hq/.anchor (or an unparseable
    # board.json under one) must fail loud, not be silently read as an
    # inactive/absent store the way _is_harness_active() below reads it.
    corrupt_reason = hc.gate_corrupt_reason(root) if hc else None
    if corrupt_reason is not None:
        sys.stderr.write(f"HARNESS: gate corrupt — {corrupt_reason}\n")
        if stop_hook_active:
            # Same loop escape the legacy parse handler below has always
            # had: a corrupt store persists across retries, so blocking
            # again with stop_hook_active True would loop on a file we
            # cannot read. Loud both times; blocking only the first.
            sys.stderr.write(
                "HARNESS: WARN — corrupt store and stop_hook_active is True. "
                "Allowing the stop rather than looping.\n"
            )
            return 0
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
        if stop_hook_active:
            sys.stderr.write(
                "HARNESS: WARN — harness-tasks.json will not parse and stop_hook_active is "
                "True. Allowing the stop rather than looping on a file we cannot read.\n"
            )
            return 0
        reason = (
            "HARNESS: the state file is corrupt — harness-tasks.json will not parse.\n"
            f"HARNESS: error={e}\n"
            "Recover per SKILL.md's JSON corruption procedure: restore from "
            "harness-tasks.json.bak first; if that is not possible, stop and ask for a "
            "human fix rather than writing a fresh file over the campaign's state."
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return 0

    session_config = hc.get_session_config(state)
    is_concurrent = hc.is_concurrent(session_config)
    worker_id = os.environ.get("HARNESS_WORKER_ID") or None

    # Check session limits
    try:
        session_count = int(state.get("session_count") or 0)
    except Exception:
        session_count = 0
    try:
        max_sessions = int(session_config.get("max_sessions") or 0)
    except Exception:
        max_sessions = 0
    if max_sessions > 0 and session_count >= max_sessions:
        _reset_block_counter(root)
        return 0  # session limit reached, allow stop

    # Check per-session task limit
    try:
        max_tasks_per_session = int(session_config.get("max_tasks_per_session") or 0)
    except Exception:
        max_tasks_per_session = 0
    if not is_concurrent and max_tasks_per_session > 0 and session_count > 0 and progress_path.is_file():
        tail = hc.tail_text(progress_path)
        tag = f"[SESSION-{session_count}]"
        finished = 0
        for ln in tail.splitlines():
            if tag not in ln:
                continue
            if " Completed [" in ln or (" ERROR [" in ln and "[task-" in ln):
                finished += 1
        if finished >= max_tasks_per_session:
            _reset_block_counter(root)
            return 0  # per-session limit reached, allow stop

    # Compute eligible tasks
    counts = hc.status_counts(tasks)
    logged_failures = hc.progress_logged_failures(root)
    completed_count = len(hc.completed_ids(tasks))

    pending_eligible, retryable = hc.eligible_tasks(tasks, logged_failures)
    in_progress_any = [t for t in tasks if str(t.get("status", "")) == "in_progress"]
    if is_concurrent and worker_id:
        in_progress_blocking = [
            t for t in in_progress_any
            if str(t.get("claimed_by") or "") == worker_id or not t.get("claimed_by")
        ]
    else:
        in_progress_blocking = in_progress_any

    # Campaign contract only. A legacy harness-tasks.json root predates these
    # fields, and turning every task without them into a blocker would fire on
    # boards that simply do not use them -- the false-positive class that gets a
    # hook switched off. The seeded board ships both fields, so a campaign has
    # them from the start.
    on_board = hc.board_path(root).is_file()
    integrity = _integrity_failures(tasks) if on_board else []
    if integrity and not stop_hook_active:
        emit_reason = (
            "HARNESS: completion criteria are not backed by anything runnable.\n"
            + "\n".join(f"  - {f}" for f in integrity)
            + "\n\nSKILL.md, Task Execution Cycle step 3: do not declare completion "
            "without an objective check."
        )
        print(json.dumps({"decision": "block", "reason": emit_reason}, ensure_ascii=False))
        return 0

    # If nothing left to do, allow stop
    if not pending_eligible and not retryable and not in_progress_blocking:
        # Last gate before the campaign closes. Guarded on stop_hook_active so it
        # asks exactly once -- a cost the session refuses to record must not become
        # a session that cannot end.
        cost_gap = _cost_unrecorded(state) if on_board else ""
        if cost_gap and not stop_hook_active:
            print(json.dumps({"decision": "block", "reason": cost_gap}, ensure_ascii=False))
            return 0
        _reset_block_counter(root)
        # Signal self-reflect hook BEFORE removing active marker
        try:
            (root / ".harness-reflect").touch()
        except Exception:
            pass
        try:
            (root / ".harness-active").unlink(missing_ok=True)
        except Exception:
            pass
        return 0

    # Safety valve: track consecutive blocks without progress
    prev_blocks, prev_completed = _read_block_counter(root)
    if completed_count > prev_completed:
        # Progress was made, reset counter
        prev_blocks = 0
    consecutive = prev_blocks + 1
    _write_block_counter(root, consecutive, completed_count)

    if stop_hook_active and consecutive > MAX_CONSECUTIVE_BLOCKS:
        # Too many consecutive blocks without progress — allow stop to prevent infinite loop
        _reset_block_counter(root)
        sys.stderr.write(
            f"HARNESS: WARN — Stop hook blocked {consecutive} times without progress. "
            "Allowing stop to prevent infinite loop. Check task definitions and validation commands.\n"
        )
        return 0

    # Block the stop — tasks remain
    next_task = hc.pick_next(pending_eligible, retryable)
    next_hint = ""
    escalation = ""
    if next_task is not None:
        tid = str(next_task.get("id") or "")
        title = str(next_task.get("title") or "").strip()
        tried = hc.effective_attempts(next_task, logged_failures)
        next_hint = f"next={tid}{(': ' + title) if title else ''}"
        if tried:
            next_hint += f" attempts={tried}/{hc.task_max_attempts(next_task)}"
        if tried >= ESCALATE_AFTER_ATTEMPTS:
            escalation = _escalation_notice(tid, tried)

    summary = (
        "HARNESS: stop conditions are not met. Continue.\n"
        + "HARNESS: "
        + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        + f" total={len(tasks)}"
        + (f" {next_hint}" if next_hint else "")
    ).strip()

    reason = (
        summary
        + "\n"
        + "Pick the next eligible task with SKILL.md's Task Selection Algorithm and run "
        "the full Task Execution Cycle: Claim → Checkpoint → Validate → Record outcome "
        "→ STATS (if needed) → Continue."
        + escalation
    )

    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

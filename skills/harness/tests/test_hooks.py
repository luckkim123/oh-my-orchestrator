#!/usr/bin/env python3
"""Unit tests for harness hook scripts.

Tests the activation guard (.harness-active marker), task state logic,
and edge cases for all 4 hooks: Stop, SessionStart, TeammateIdle, SubagentStop.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
STOP_HOOK = HOOKS_DIR / "harness-stop.py"
SESSION_HOOK = HOOKS_DIR / "harness-sessionstart.py"
IDLE_HOOK = HOOKS_DIR / "harness-teammateidle.py"
SUBAGENT_HOOK = HOOKS_DIR / "harness-subagentstop.py"
SUBAGENT_START_HOOK = HOOKS_DIR / "harness-subagentstart.py"
PRECOMPACT_HOOK = HOOKS_DIR / "harness-precompact.py"
CLAIM_HOOK = HOOKS_DIR / "harness-claim.py"

# Read out of the hook rather than restated here: the boundary test pins the
# comparison, not the number. Retuning the window is a deliberate edit and must
# not be reported as a regression.
_SKEW_MATCH = re.search(r"^SKEW_TOLERANCE_SECONDS = (\d+)$",
                        PRECOMPACT_HOOK.read_text(encoding="utf-8"), re.M)
assert _SKEW_MATCH, "SKEW_TOLERANCE_SECONDS is no longer a literal in the hook"
SKEW_TOLERANCE_SECONDS = int(_SKEW_MATCH.group(1))


def build_hook_env(env_extra: dict | None = None) -> dict[str, str]:
    """Build an isolated environment for hook subprocesses."""
    env = os.environ.copy()
    # Clear harness env vars to avoid interference
    env.pop("HARNESS_STATE_ROOT", None)
    env.pop("HARNESS_WORKER_ID", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if env_extra:
        env.update(env_extra)
    return env


def run_hook(script: Path, payload: dict, env_extra: dict | None = None) -> tuple[int, str, str]:
    """Run a hook script with JSON payload on stdin. Returns (exit_code, stdout, stderr)."""
    env = build_hook_env(env_extra)
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def write_tasks(root: Path, tasks: list[dict], **extra) -> None:
    state = {"tasks": tasks, **extra}
    (root / "harness-tasks.json").write_text(json.dumps(state), encoding="utf-8")


def write_board(root: Path, tasks: list[dict], status: str = "active", **extra) -> None:
    """Write .orchestration/board.json -- the migrated state file."""
    d = root / ".orchestration"
    d.mkdir(parents=True, exist_ok=True)
    board = {"status": status, "owning_session": "test", "tasks": tasks, **extra}
    (d / "board.json").write_text(json.dumps(board), encoding="utf-8")


def activate(root: Path) -> None:
    (root / ".harness-active").touch()


def deactivate(root: Path) -> None:
    p = root / ".harness-active"
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Activation Guard Tests (shared across all hooks)
# ---------------------------------------------------------------------------
class TestActivationGuard(unittest.TestCase):
    """All hooks must be no-ops when .harness-active is absent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        write_tasks(self.root, [
            {"id": "t1", "title": "Pending task", "status": "pending", "priority": "P0", "depends_on": []},
        ])
        (self.root / "harness-progress.txt").write_text("[SESSION-1] INIT\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self, **extra):
        return {"cwd": self.tmpdir, **extra}

    def test_stop_inactive_allows(self):
        """Stop hook allows stop when .harness-active is absent."""
        deactivate(self.root)
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_stop_active_blocks(self):
        """Stop hook blocks when .harness-active is present and tasks remain."""
        activate(self.root)
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")

    def test_sessionstart_inactive_noop(self):
        """SessionStart hook produces no output when inactive."""
        deactivate(self.root)
        code, stdout, stderr = run_hook(SESSION_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_sessionstart_active_injects(self):
        """SessionStart hook injects context when active."""
        activate(self.root)
        code, stdout, stderr = run_hook(SESSION_HOOK, self._payload())
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("additionalContext", data.get("hookSpecificOutput", {}))

    def test_teammateidle_inactive_allows(self):
        """TeammateIdle hook allows idle when inactive."""
        deactivate(self.root)
        code, stdout, stderr = run_hook(IDLE_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_teammateidle_active_blocks(self):
        """TeammateIdle hook blocks idle when active and tasks remain."""
        activate(self.root)
        code, stdout, stderr = run_hook(IDLE_HOOK, self._payload())
        self.assertEqual(code, 2)
        self.assertIn("HARNESS", stderr)

    def test_subagentstop_inactive_allows(self):
        """SubagentStop hook allows stop when inactive."""
        deactivate(self.root)
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_subagentstop_active_blocks(self):
        """SubagentStop hook blocks when active and tasks in progress."""
        write_tasks(self.root, [
            {"id": "t1", "title": "Working task", "status": "in_progress", "priority": "P0", "depends_on": []},
        ])
        activate(self.root)
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload())
        self.assertEqual(code, 2, "exit 2 + stderr is the measured blocking protocol")
        self.assertIn("Working task", stderr)


# ---------------------------------------------------------------------------
# No Harness Root Tests
# ---------------------------------------------------------------------------
class TestNoHarnessRoot(unittest.TestCase):
    """All hooks must be no-ops when no harness-tasks.json exists."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stop_no_root(self):
        code, stdout, _ = run_hook(STOP_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_sessionstart_no_root(self):
        code, stdout, _ = run_hook(SESSION_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_teammateidle_no_root(self):
        code, _, stderr = run_hook(IDLE_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_subagentstop_no_root(self):
        code, stdout, _ = run_hook(SUBAGENT_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")


# ---------------------------------------------------------------------------
# store-spec.md §6 row 4 — the corrupt gate, end-to-end through real hooks
# ---------------------------------------------------------------------------
class TestCorruptGate(unittest.TestCase):
    """A corrupt .hq/.anchor (duplicate id, unparseable .anchor, or an
    unparseable board.json under a valid one) must fail loud -- stderr naming
    the file, exit 2 -- not be silently read as an absent/inactive store the
    way is_harness_active() alone would read it. hq.anchor.gate_state()'s own
    4-state fixtures live in test_hq.py; this class is the other half the
    plan's acceptance asks for -- that the hooks actually call it.

    The fixture always carries harness-tasks.json + .harness-active (the
    legacy markers _find_harness_root()/is_harness_active() key off), since a
    root that doesn't resolve at all was already covered by
    TestNoHarnessRoot -- the "off" row is unreachable at the hook-invocation
    level for that reason (the hook returns 0 before ever calling
    gate_corrupt_reason). The three rows exercised here as "still exit 0" are
    the three that remain reachable: legacy (no .hq/.anchor -- today's actual
    state for every real repo on this machine), normal with no board.json,
    and normal with a board.json that parses.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        write_tasks(self.root, [
            {"id": "t1", "title": "Pending task", "status": "pending", "priority": "P0", "depends_on": []},
        ])
        activate(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self, **extra):
        return {"cwd": self.tmpdir, **extra}

    def _write_anchor(self, anchor_id: str = "t1") -> None:
        d = self.root / ".hq"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".anchor").write_text(f"id: {anchor_id}\n", encoding="utf-8")

    def _write_board(self, content: str) -> None:
        # store-spec §7 stage 2: gate_state()'s corrupt-board check (reached
        # only once an anchor is confirmed present) reads .hq/runtime/
        # board.json now, not .orchestration/board.json -- every caller here
        # writes the anchor first, so this always lands where gate_state()
        # actually looks.
        d = self.root / ".hq" / "runtime"
        d.mkdir(parents=True, exist_ok=True)
        (d / "board.json").write_text(content, encoding="utf-8")

    def test_stop_exits_2_and_names_the_file_on_corrupt_gate(self):
        self._write_anchor()
        self._write_board("{invalid")
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 2)
        self.assertIn("board.json", stderr)

    def test_sessionstart_exits_2_on_corrupt_gate(self):
        self._write_anchor()
        self._write_board("{invalid")
        code, stdout, stderr = run_hook(SESSION_HOOK, self._payload())
        self.assertEqual(code, 2)
        self.assertIn("board.json", stderr)

    def test_teammateidle_warns_but_allows_idle_on_corrupt_gate(self):
        # Exit 2 here has no retry escape, so it would block idle forever
        # while the corruption persists (codex review 2026-08-31). The hook
        # warns on stderr and allows idle; Stop owns the loud channel.
        self._write_anchor()
        self._write_board("{invalid")
        code, stdout, stderr = run_hook(IDLE_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertIn("board.json", stderr)

    def test_subagentstop_exits_2_on_corrupt_gate(self):
        self._write_anchor()
        self._write_board("{invalid")
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload())
        self.assertEqual(code, 2)
        self.assertIn("board.json", stderr)

    def test_subagentstart_injects_corruption_notice_via_additionalcontext(self):
        # Exit 2 cannot block the spawn and stderr is invisible (measured in
        # the hook's docstring), so additionalContext is the one channel that
        # reaches anyone (codex review 2026-08-31).
        self._write_anchor()
        self._write_board("{invalid")
        code, stdout, stderr = run_hook(SUBAGENT_START_HOOK, self._payload(agent_type="t1"))
        self.assertEqual(code, 0)
        self.assertIn("board.json", stderr)
        self.assertIn("gate corrupt", stdout)
        self.assertIn("additionalContext", stdout)

    def test_precompact_stays_non_blocking_but_reports_via_systemmessage(self):
        # Deliberately different from the other five: PreCompact CAN block
        # (measured) and has no loop guard, so a wrong block strands the
        # session at the context ceiling. It stays loud through its own
        # systemMessage channel instead of sys.exit(2).
        self._write_anchor()
        self._write_board("{invalid")
        code, stdout, stderr = run_hook(PRECOMPACT_HOOK, self._payload())
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("board.json", data.get("systemMessage", ""))

    def test_other_three_rows_still_exit_0_through_a_real_hook(self):
        # legacy: no .hq/.anchor at all (today's actual state for every real
        # repo -- neither live post store has one yet).
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0, stderr)

        # normal: valid .hq/.anchor, no board.json under .hq/runtime/.
        self._write_anchor()
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0, stderr)

        # normal: valid .hq/.anchor AND a board.json that parses.
        self._write_board("{}")
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0, stderr)


# ---------------------------------------------------------------------------
# Stop Hook — Task State Logic
# ---------------------------------------------------------------------------
class TestStopHookTaskLogic(unittest.TestCase):
    """Stop hook task selection, completion detection, and safety valve."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / "harness-progress.txt").write_text("")
        activate(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self, **extra):
        return {"cwd": self.tmpdir, **extra}

    def test_all_completed_allows_stop(self):
        """When all tasks are completed, stop is allowed and .harness-reflect created."""
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "completed"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertFalse((self.root / ".harness-active").exists())
        self.assertTrue(
            (self.root / ".harness-reflect").exists(),
            ".harness-reflect should be created when all tasks complete",
        )

    def test_pending_with_unmet_deps_allows_stop(self):
        """Pending tasks with unmet dependencies don't block stop."""
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 3, "max_attempts": 3},
            {"id": "t2", "status": "pending", "depends_on": ["t1"]},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_retryable_failed_blocks(self):
        """Failed task with attempts < max_attempts blocks stop."""
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 1, "max_attempts": 3, "priority": "P0", "depends_on": [], "title": "Retry me"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("Retry me", data["reason"])

    def test_second_failure_demands_escalation(self):
        """attempts >= 2 turns the generic continue message into an escalation order."""
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 2, "max_attempts": 4,
             "priority": "P0", "depends_on": [], "title": "Flaky fix"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("ESCALATION REQUIRED", data["reason"])
        self.assertIn("attempts=2/4", data["reason"])

    def test_first_failure_does_not_escalate(self):
        """One failure is a retry, not an escalation."""
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 1, "max_attempts": 4,
             "priority": "P0", "depends_on": [], "title": "First try"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertNotIn("ESCALATION REQUIRED", data["reason"])

    def test_logged_errors_escalate_when_attempts_unbumped(self):
        """The progress log is the fact; an unbumped attempts field cannot dodge it."""
        (self.root / "harness-progress.txt").write_text(
            "[2026-08-26T10:00:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] first\n"
            "[2026-08-26T10:05:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] second\n"
        )
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 0, "max_attempts": 4,
             "priority": "P0", "depends_on": [], "title": "Unbumped"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("ESCALATION REQUIRED", data["reason"])
        self.assertIn("failed 2 times", data["reason"])

    def test_logged_errors_exhaust_retries(self):
        """Retries run out on logged failures too, not just declared ones."""
        (self.root / "harness-progress.txt").write_text(
            "[2026-08-26T10:00:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] one\n"
            "[2026-08-26T10:05:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] two\n"
            "[2026-08-26T10:10:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] three\n"
        )
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 0, "max_attempts": 3, "depends_on": []},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_other_task_errors_do_not_count(self):
        """Failures are counted per task id, not per log."""
        (self.root / "harness-progress.txt").write_text(
            "[2026-08-26T10:00:00Z] [SESSION-1] ERROR [t2] [TASK_EXEC] not mine\n"
            "[2026-08-26T10:05:00Z] [SESSION-1] ERROR [t2] [TASK_EXEC] also not mine\n"
        )
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 0, "max_attempts": 3,
             "priority": "P0", "depends_on": [], "title": "Clean"},
            {"id": "t2", "status": "completed"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertNotIn("ESCALATION REQUIRED", data["reason"])

    def test_exhausted_retries_allows_stop(self):
        """Failed task with attempts >= max_attempts allows stop."""
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 3, "max_attempts": 3, "depends_on": []},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_in_progress_blocks(self):
        """In-progress tasks block stop."""
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "priority": "P0"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")

    def test_session_limit_allows_stop(self):
        """Session limit reached allows stop even with pending tasks."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "depends_on": [], "priority": "P0"},
        ], session_count=5, session_config={"max_sessions": 5})
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_max_tasks_per_session_limit_allows_stop(self):
        """Per-session completed-task cap allows stop when reached."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "depends_on": [], "priority": "P0"},
        ], session_count=2, session_config={"max_tasks_per_session": 1})
        (self.root / "harness-progress.txt").write_text("[SESSION-2] Completed [task-1]\n")
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_concurrent_other_worker_in_progress_allows_stop(self):
        """Concurrent mode should not block on another worker's in-progress task."""
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "claimed_by": "worker-a", "priority": "P0"},
        ], session_config={"concurrency_mode": "concurrent"})
        code, stdout, _ = run_hook(
            STOP_HOOK, self._payload(),
            env_extra={"HARNESS_WORKER_ID": "worker-b"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_priority_ordering_in_block_reason(self):
        """Block reason shows highest priority task as next."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "priority": "P2", "depends_on": [], "title": "Low"},
            {"id": "t2", "status": "pending", "priority": "P0", "depends_on": [], "title": "High"},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertIn("t2", data["reason"])
        self.assertIn("High", data["reason"])

    def test_stop_hook_active_safety_valve(self):
        """After MAX_CONSECUTIVE_BLOCKS with stop_hook_active, allows stop."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "depends_on": [], "priority": "P0"},
        ])
        (self.root / ".harness-stop-counter").write_text("9,0")
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload(stop_hook_active=True))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("WARN", stderr)

    def test_stop_hook_active_below_threshold_blocks(self):
        """Below MAX_CONSECUTIVE_BLOCKS with stop_hook_active still blocks."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "depends_on": [], "priority": "P0"},
        ])
        (self.root / ".harness-stop-counter").write_text("2,0")
        code, stdout, _ = run_hook(STOP_HOOK, self._payload(stop_hook_active=True))
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")

    def test_progress_resets_block_counter(self):
        """When completed count increases, block counter resets."""
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "pending", "depends_on": [], "priority": "P0"},
        ])
        (self.root / ".harness-stop-counter").write_text("7,0")
        code, stdout, _ = run_hook(STOP_HOOK, self._payload(stop_hook_active=True))
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        counter = (self.root / ".harness-stop-counter").read_text().strip()
        self.assertEqual(counter, "1,1")

    def test_corrupt_json_with_stop_hook_active_allows(self):
        """Corrupt config + stop_hook_active should allow stop to avoid loop."""
        (self.root / "harness-tasks.json").write_text("{invalid json")
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload(stop_hook_active=True))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("WARN", stderr)


# ---------------------------------------------------------------------------
# SessionStart Hook — Context Injection
# ---------------------------------------------------------------------------
class TestSessionStartHook(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        activate(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self):
        return {"cwd": self.tmpdir}

    def test_summary_includes_counts(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "pending", "depends_on": ["t1"]},
            {"id": "t3", "status": "failed", "depends_on": []},
        ])
        (self.root / "harness-progress.txt").write_text("[SESSION-1] STATS total=3\n")
        code, stdout, _ = run_hook(SESSION_HOOK, self._payload())
        data = json.loads(stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("completed=1", ctx)
        self.assertIn("pending=1", ctx)
        self.assertIn("failed=1", ctx)
        self.assertIn("total=3", ctx)

    def test_next_task_hint(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "pending", "priority": "P0", "depends_on": ["t1"], "title": "Do stuff"},
        ])
        (self.root / "harness-progress.txt").write_text("")
        code, stdout, _ = run_hook(SESSION_HOOK, self._payload())
        data = json.loads(stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("next=t2", ctx)
        self.assertIn("Do stuff", ctx)

    def test_empty_tasks_no_crash(self):
        write_tasks(self.root, [])
        (self.root / "harness-progress.txt").write_text("")
        code, stdout, _ = run_hook(SESSION_HOOK, self._payload())
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("total=0", data["hookSpecificOutput"]["additionalContext"])

    def test_corrupt_json_reports_error(self):
        """B-r1 widening (2026-08-31): an unparseable legacy board with no
        anchor is GATE_CORRUPT at hook entry -- stderr + exit 2, same as the
        anchored corrupt case, instead of the old quiet context report."""
        (self.root / "harness-tasks.json").write_text("{invalid json")
        (self.root / "harness-progress.txt").write_text("")
        code, stdout, stderr = run_hook(SESSION_HOOK, self._payload())
        self.assertEqual(code, 2)
        self.assertIn("corrupt", stderr.lower())

    def test_invalid_attempt_fields_no_crash(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": "oops", "max_attempts": "bad", "depends_on": []},
        ])
        (self.root / "harness-progress.txt").write_text("")
        code, stdout, _ = run_hook(SESSION_HOOK, self._payload())
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("total=1", data["hookSpecificOutput"]["additionalContext"])


# ---------------------------------------------------------------------------
# TeammateIdle Hook — Ownership & Task State
# ---------------------------------------------------------------------------
class TestTeammateIdleHook(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        activate(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_owned_in_progress_blocks(self):
        """Teammate with in-progress task is blocked from going idle."""
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "claimed_by": "alice", "title": "My task"},
        ])
        code, _, stderr = run_hook(IDLE_HOOK, {"cwd": self.tmpdir, "teammate_name": "alice"})
        self.assertEqual(code, 2)
        self.assertIn("t1", stderr)

    def test_unowned_in_progress_allows(self):
        """Teammate without owned tasks and no pending allows idle."""
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "claimed_by": "bob"},
        ])
        code, _, stderr = run_hook(IDLE_HOOK, {"cwd": self.tmpdir, "teammate_name": "alice"})
        self.assertEqual(code, 0)

    def test_pending_tasks_block(self):
        """Pending eligible tasks block idle even without ownership."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "depends_on": [], "title": "Next up"},
        ])
        code, _, stderr = run_hook(IDLE_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 2)
        self.assertIn("t1", stderr)

    def test_all_completed_allows(self):
        """All tasks completed allows idle."""
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "completed"},
        ])
        code, _, stderr = run_hook(IDLE_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_failed_retryable_blocks(self):
        """Retryable failed tasks block idle."""
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 1, "max_attempts": 3, "depends_on": [], "title": "Retry"},
        ])
        code, _, stderr = run_hook(IDLE_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 2)
        self.assertIn("t1", stderr)

    def test_worker_id_env_matches(self):
        """HARNESS_WORKER_ID env var matches claimed_by."""
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "claimed_by": "w-123"},
        ])
        code, _, stderr = run_hook(
            IDLE_HOOK, {"cwd": self.tmpdir},
            env_extra={"HARNESS_WORKER_ID": "w-123"},
        )
        self.assertEqual(code, 2)
        self.assertIn("t1", stderr)


# ---------------------------------------------------------------------------
# SubagentStop Hook — Stop Guard & stop_hook_active
# ---------------------------------------------------------------------------
class TestSubagentStopHook(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        activate(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_in_progress_blocks(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "title": "Working"},
        ])
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 2)
        self.assertIn("Working", stderr)

    def test_pending_allows(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "pending", "depends_on": ["t1"], "title": "Next"},
        ])
        code, stdout, _ = run_hook(SUBAGENT_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_all_done_allows(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "completed"},
        ])
        code, stdout, _ = run_hook(SUBAGENT_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_stop_hook_active_allows(self):
        """stop_hook_active=True bypasses all checks to prevent infinite loop."""
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress"},
        ])
        code, stdout, _ = run_hook(SUBAGENT_HOOK, {"cwd": self.tmpdir, "stop_hook_active": True})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_blocked_deps_not_counted(self):
        """Pending tasks with unmet deps don't trigger block."""
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 3, "max_attempts": 3},
            {"id": "t2", "status": "pending", "depends_on": ["t1"]},
        ])
        code, stdout, _ = run_hook(SUBAGENT_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_concurrent_owned_in_progress_blocks(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "claimed_by": "worker-a", "title": "Mine"},
        ], session_config={"concurrency_mode": "concurrent"})
        code, stdout, stderr = run_hook(
            SUBAGENT_HOOK, {"cwd": self.tmpdir},
            env_extra={"HARNESS_WORKER_ID": "worker-a"},
        )
        self.assertEqual(code, 2)
        self.assertIn("Mine", stderr)

    def test_concurrent_other_worker_in_progress_allows(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "claimed_by": "worker-a", "title": "Other"},
        ], session_config={"concurrency_mode": "concurrent"})
        code, stdout, _ = run_hook(
            SUBAGENT_HOOK, {"cwd": self.tmpdir},
            env_extra={"HARNESS_WORKER_ID": "worker-b"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_concurrent_missing_identity_blocks(self):
        write_tasks(self.root, [
            {"id": "t1", "status": "in_progress", "claimed_by": "worker-a", "title": "Other"},
        ], session_config={"concurrency_mode": "concurrent"})
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 2)
        self.assertIn("worker identity", stderr)


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------
class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_stdin(self):
        """Hooks handle empty stdin gracefully."""
        write_tasks(self.root, [{"id": "t1", "status": "pending", "depends_on": []}])
        activate(self.root)
        for hook in [STOP_HOOK, SESSION_HOOK, IDLE_HOOK, SUBAGENT_HOOK]:
            proc = subprocess.run(
                [sys.executable, str(hook)],
                input="",
                capture_output=True, text=True, timeout=10,
                cwd=self.tmpdir,
                env=build_hook_env(),
            )
            self.assertIn(proc.returncode, {0, 2}, f"{hook.name} failed on empty stdin")
            self.assertNotIn("Traceback", proc.stderr)

    def test_invalid_json_stdin(self):
        """Hooks handle invalid JSON stdin gracefully."""
        write_tasks(self.root, [{"id": "t1", "status": "pending", "depends_on": []}])
        activate(self.root)
        for hook in [STOP_HOOK, SESSION_HOOK, IDLE_HOOK, SUBAGENT_HOOK]:
            proc = subprocess.run(
                [sys.executable, str(hook)],
                input="not json at all",
                capture_output=True, text=True, timeout=10,
                cwd=self.tmpdir,
                env=build_hook_env(),
            )
            self.assertIn(proc.returncode, {0, 2}, f"{hook.name} crashed on invalid JSON")
            self.assertNotIn("Traceback", proc.stderr)

    def test_harness_state_root_env(self):
        """HARNESS_STATE_ROOT env var is respected."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "depends_on": [], "priority": "P0"},
        ])
        activate(self.root)
        (self.root / "harness-progress.txt").write_text("")
        code, stdout, _ = run_hook(
            STOP_HOOK, {"cwd": "/nonexistent"},
            env_extra={"HARNESS_STATE_ROOT": self.tmpdir},
        )
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")

    def test_tasks_not_a_list(self):
        """Hooks handle tasks field being non-list."""
        (self.root / "harness-tasks.json").write_text('{"tasks": "not a list"}')
        activate(self.root)
        (self.root / "harness-progress.txt").write_text("")
        code, stdout, _ = run_hook(STOP_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")


# ---------------------------------------------------------------------------
# Self-Reflect Stop Hook — Only triggers after harness completes
# ---------------------------------------------------------------------------
REFLECT_HOOK = HOOKS_DIR / "self-reflect-stop.py"


class TestSelfReflectStopHook(unittest.TestCase):
    """self-reflect-stop.py must only trigger when .harness-reflect marker exists."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        # Clean up counter files
        for p in Path(tempfile.gettempdir()).glob("claude-reflect-test-*"):
            try:
                p.unlink()
            except Exception:
                pass

    def _payload(self, session_id="test-reflect-001", **extra):
        return {"cwd": self.tmpdir, "session_id": session_id, **extra}

    def _set_reflect(self):
        """Create .harness-reflect marker (simulates harness completion)."""
        (self.root / ".harness-reflect").touch()

    def _transcript(self, text):
        """A transcript line in Claude Code's real shape: content under message."""
        tp = self.root / "transcript.jsonl"
        tp.write_text(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }) + "\n", encoding="utf-8")
        return str(tp)

    def test_original_prompt_is_read_from_message_content(self):
        """entry["content"] does not exist; the request lives at entry["message"]["content"]."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        self._set_reflect()
        tp = self._transcript("BUILD THE WIDGET")
        _, stdout, _ = run_hook(REFLECT_HOOK, self._payload(
            session_id="test-reflect-prompt", transcript_path=tp))
        self.assertIn("BUILD THE WIDGET", json.loads(stdout)["reason"],
                      "the reflect prompt shipped without the original request")

    def test_sentinel_ends_the_loop(self):
        """The prompt promises that finishing ends it; the sentinel is what makes that true."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        self._set_reflect()
        code, stdout, _ = run_hook(REFLECT_HOOK, self._payload(
            session_id="test-reflect-done",
            last_assistant_message="All five checks pass, nothing outstanding.\nREFLECT-DONE"))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "the sentinel must end the loop, not shorten it")
        self.assertFalse((self.root / ".harness-reflect").exists(),
                         "the marker must be cleared so it does not re-trigger")

    def test_without_sentinel_it_still_blocks(self):
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        self._set_reflect()
        _, stdout, _ = run_hook(REFLECT_HOOK, self._payload(
            session_id="test-reflect-noexit",
            last_assistant_message="I think everything is fine."))
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("REFLECT-DONE", data["reason"], "the exit must be named in the prompt")

    def test_no_harness_root_is_noop(self):
        """When harness-tasks.json doesn't exist, hook is a complete no-op."""
        code, stdout, stderr = run_hook(REFLECT_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "Should produce no output when harness never used")

    def test_harness_active_no_reflect_marker(self):
        """When .harness-active exists but no .harness-reflect, hook is no-op."""
        write_tasks(self.root, [
            {"id": "t1", "status": "pending", "depends_on": []},
        ])
        activate(self.root)
        code, stdout, _ = run_hook(REFLECT_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "Should not self-reflect while harness is active")

    def test_stale_tasks_without_reflect_marker_is_noop(self):
        """Stale harness-tasks.json without .harness-reflect does NOT trigger (fixes false positive)."""
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
        ])
        deactivate(self.root)
        # No .harness-reflect marker — this is a stale file from a previous run
        code, stdout, _ = run_hook(REFLECT_HOOK, self._payload(session_id="test-stale"))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "Stale harness-tasks.json should NOT trigger self-reflect")

    def test_harness_completed_triggers_reflection(self):
        """When .harness-reflect marker exists, triggers self-reflection."""
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
        ])
        deactivate(self.root)
        self._set_reflect()
        sid = "test-reflect-trigger"
        code, stdout, _ = run_hook(REFLECT_HOOK, self._payload(session_id=sid))
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("Self-Reflect", data["reason"])

    def test_counter_increments(self):
        """Each invocation increments the iteration counter."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        deactivate(self.root)
        self._set_reflect()
        sid = "test-reflect-counter"

        # First call: iteration 1
        code, stdout, _ = run_hook(REFLECT_HOOK, self._payload(session_id=sid))
        data = json.loads(stdout)
        self.assertIn("1/5", data["reason"])

        # Second call: iteration 2
        code, stdout, _ = run_hook(REFLECT_HOOK, self._payload(session_id=sid))
        data = json.loads(stdout)
        self.assertIn("2/5", data["reason"])

    def test_max_iterations_allows_stop_and_cleans_marker(self):
        """After max iterations, hook allows stop and removes .harness-reflect."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        deactivate(self.root)
        self._set_reflect()
        sid = "test-reflect-max"

        # Write counter at max
        counter_path = Path(tempfile.gettempdir()) / f"claude-reflect-{sid}"
        counter_path.write_text("5", encoding="utf-8")

        code, stdout, _ = run_hook(REFLECT_HOOK, self._payload(session_id=sid))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "Should allow stop after max iterations")
        self.assertFalse(
            (self.root / ".harness-reflect").exists(),
            ".harness-reflect should be cleaned up after max iterations",
        )

    def test_disabled_via_env(self):
        """REFLECT_MAX_ITERATIONS=0 disables self-reflection."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        deactivate(self.root)
        self._set_reflect()
        code, stdout, _ = run_hook(
            REFLECT_HOOK,
            self._payload(session_id="test-reflect-disabled"),
            env_extra={"REFLECT_MAX_ITERATIONS": "0"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "Should be disabled when max=0")

    def test_no_session_id_is_noop(self):
        """Missing session_id makes hook a no-op."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        deactivate(self.root)
        self._set_reflect()
        code, stdout, _ = run_hook(REFLECT_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_empty_stdin_no_crash(self):
        """Empty stdin doesn't crash."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        self._set_reflect()
        proc = subprocess.run(
            [sys.executable, str(REFLECT_HOOK)],
            input="",
            capture_output=True, text=True, timeout=10,
            cwd=self.tmpdir,
            env=build_hook_env(),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)

    def test_harness_state_root_env_respected(self):
        """HARNESS_STATE_ROOT env var is used for root discovery."""
        write_tasks(self.root, [{"id": "t1", "status": "completed"}])
        deactivate(self.root)
        self._set_reflect()
        sid = "test-reflect-env"
        code, stdout, _ = run_hook(
            REFLECT_HOOK,
            {"cwd": "/nonexistent", "session_id": sid},
            env_extra={"HARNESS_STATE_ROOT": self.tmpdir},
        )
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")


class TestCompletionIntegrity(unittest.TestCase):
    """A completion claim the file cannot back up is not a completion."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / "harness-progress.txt").write_text("")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self, **extra):
        return {"cwd": self.tmpdir, **extra}

    def test_completed_without_validation_blocks(self):
        write_board(self.root, [
            {"id": "t1", "status": "completed", "validation": {"command": None}},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("no validation.command", data["reason"])

    def test_completed_with_validation_allows(self):
        write_board(self.root, [
            {"id": "t1", "status": "completed",
             "validation": {"command": "pytest -q", "timeout_seconds": 300}},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_in_progress_without_base_commit_blocks(self):
        write_board(self.root, [
            {"id": "t1", "status": "in_progress", "started_at_commit": None,
             "validation": {"command": "pytest -q"}},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertIn("no started_at_commit", data["reason"])

    def test_legacy_root_is_not_held_to_the_campaign_contract(self):
        """harness-tasks.json predates these fields; do not retrofit a blocker."""
        write_tasks(self.root, [
            {"id": "t1", "status": "completed"},
        ])
        activate(self.root)
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_stop_hook_active_lets_it_through(self):
        write_board(self.root, [
            {"id": "t1", "status": "completed", "validation": {"command": None}},
        ])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload(stop_hook_active=True))
        self.assertNotIn("no validation.command", stdout)


class TestSubagentStartHook(unittest.TestCase):
    """SubagentStart injects and observes. It cannot block -- measured, 2.1.239."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / "harness-progress.txt").write_text("")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self, role="lit-critic", **extra):
        return {"cwd": self.tmpdir, "agent_type": role,
                "agent_id": "a1", "session_id": "s1", **extra}

    def _worker(self, **over):
        w = {"role": "lit-critic", "vendor": "codex", "model": "gpt-5.2",
             "writes_repo": False, "worktree": None, "status": "planned",
             "orca_dispatch_id": None}
        w.update(over)
        return w

    def test_closed_board_injects_nothing(self):
        write_board(self.root, [], status="closed", workers=[self._worker()])
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_registered_role_gets_its_board_row(self):
        write_board(self.root, [], workers=[self._worker()])
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload())
        data = json.loads(stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SubagentStart",
                         "only the nested form carrying hookEventName is honored")
        self.assertIn("codex", ctx)
        self.assertIn("gpt-5.2", ctx)

    def test_unregistered_role_is_observed(self):
        write_board(self.root, [], workers=[self._worker()])
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload(role="stranger"))
        self.assertEqual(code, 0, "SubagentStart must never block a spawn")
        ctx = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not on the board", ctx)
        obs = (self.root / ".orchestration" / "observations.jsonl").read_text()
        self.assertIn("board_mismatch", obs)
        self.assertIn("stranger", obs)

    def test_empty_roster_is_not_a_mismatch(self):
        """A campaign that declared no workers cannot judge membership."""
        write_board(self.root, [], workers=[])
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload(role="anyone"))
        ctx = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("not on the board", ctx)
        self.assertFalse((self.root / ".orchestration" / "observations.jsonl").exists())

    def test_null_model_is_observed(self):
        write_board(self.root, [], workers=[self._worker(model=None)])
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload())
        ctx = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("no model on the board", ctx)

    def test_duplicate_role_is_observed(self):
        write_board(self.root, [], workers=[self._worker(), self._worker(vendor="gemini")])
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload())
        ctx = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("2 rows on the board", ctx)

    def test_injection_respects_the_measured_cap(self):
        """9800 chars arrive intact, 10400 are truncated to a preview -- stay under."""
        write_board(self.root, [], workers=[self._worker()])
        mem = self.root / ".orchestration" / "agents"
        mem.mkdir(parents=True, exist_ok=True)
        (mem / "lit-critic.md").write_text("x" * 50_000, encoding="utf-8")
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload())
        ctx = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(ctx), 10000)
        self.assertIn("truncated", ctx)

    def test_notice_survives_truncation(self):
        """Role memory gives way first; the mismatch notice is the point of the call."""
        write_board(self.root, [], workers=[self._worker()])
        mem = self.root / ".orchestration" / "agents"
        mem.mkdir(parents=True, exist_ok=True)
        (mem / "stranger.md").write_text("y" * 50_000, encoding="utf-8")
        code, stdout, _ = run_hook(SUBAGENT_START_HOOK, self._payload(role="stranger"))
        ctx = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not on the board", ctx)
        self.assertLessEqual(len(ctx), 10000)


class TestSubagentStopCampaign(unittest.TestCase):
    """Campaign obligations are enforced where enforcement actually works."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / "harness-progress.txt").write_text("")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self, role="lit-critic", **extra):
        return {"cwd": self.tmpdir, "agent_type": role, **extra}

    def _worker(self, **over):
        w = {"role": "lit-critic", "vendor": "codex", "model": "gpt-5.2",
             "status": "planned"}
        w.update(over)
        return w

    def _memory(self, role="lit-critic"):
        d = self.root / ".orchestration" / "agents"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{role}.md").write_text("learned things\n", encoding="utf-8")

    def test_missing_memory_and_report_both_reported(self):
        write_board(self.root, [], workers=[self._worker()])
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload())
        self.assertEqual(code, 2)
        self.assertIn("agents/lit-critic.md", stderr)
        self.assertIn("'planned'", stderr)

    def test_reported_with_memory_may_stop(self):
        write_board(self.root, [], workers=[self._worker(status="reported")])
        self._memory()
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_unregistered_role_is_rejected(self):
        write_board(self.root, [], workers=[self._worker()])
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload(role="stranger"))
        self.assertEqual(code, 2)
        self.assertIn("not registered", stderr)

    def test_empty_roster_enforces_nothing(self):
        write_board(self.root, [], workers=[])
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload(role="anyone"))
        self.assertEqual(code, 0)

    def test_stop_hook_active_bypasses_enforcement(self):
        """The loop guard is ours to hold -- one rejection, then let it go."""
        write_board(self.root, [], workers=[self._worker()])
        code, stdout, stderr = run_hook(SUBAGENT_HOOK, self._payload(stop_hook_active=True))
        self.assertEqual(code, 0)


class TestBoardGate(unittest.TestCase):
    """The activation gate is board.json.status, not a marker file."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / "harness-progress.txt").write_text("")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _payload(self, **extra):
        return {"cwd": self.tmpdir, **extra}

    def test_active_board_blocks_without_marker(self):
        """A board with status active gates the hooks -- no .harness-active needed."""
        write_board(self.root, [
            {"id": "t1", "status": "pending", "priority": "P0", "title": "Do it"},
        ])
        self.assertFalse((self.root / ".harness-active").exists())
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("Do it", data["reason"])

    def test_closed_board_is_a_noop(self):
        """A closed campaign keeps its board on disk; presence must not mean active."""
        write_board(self.root, [
            {"id": "t1", "status": "pending", "priority": "P0"},
        ], status="closed")
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_board_wins_over_legacy_state(self):
        """When both exist, the board is the state file hooks read."""
        write_tasks(self.root, [{"id": "legacy", "status": "pending", "priority": "P0",
                                 "title": "Legacy task"}])
        write_board(self.root, [{"id": "t1", "status": "pending", "priority": "P0",
                                 "title": "Board task"}])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        data = json.loads(stdout)
        self.assertIn("Board task", data["reason"])
        self.assertNotIn("Legacy task", data["reason"])

    def test_legacy_root_still_uses_marker(self):
        """A project that has not migrated keeps working on .harness-active."""
        write_tasks(self.root, [{"id": "t1", "status": "pending", "priority": "P0",
                                 "title": "Unmigrated"}])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(stdout, "", "no marker, no board -> inactive")
        activate(self.root)
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertIn("Unmigrated", json.loads(stdout)["reason"])

    def test_corrupt_board_fails_closed(self):
        """B-r1 widening (2026-08-31): a board that will not parse fails loud
        (stderr + exit 2) even with no anchor, instead of being read as an
        inactive store while hooks quietly stop firing."""
        d = self.root / ".orchestration"
        d.mkdir(parents=True, exist_ok=True)
        (d / "board.json").write_text("{not json", encoding="utf-8")
        code, stdout, stderr = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 2)
        self.assertIn("corrupt", stderr.lower())
        self.assertEqual(stdout, "", "the corrupt gate speaks on stderr only")


# ---------------------------------------------------------------------------
# Cost Gate (Stop) -- measured 2026-08-26: the Stop payload carries no token
# counts, so the figure has to come from the board and the hook only asks.
# ---------------------------------------------------------------------------
class TestCostGate(unittest.TestCase):
    """A campaign must not close with cost.actual_tokens still null."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        activate(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _done_board(self, cost):
        write_board(self.root, [
            {"id": "t1", "title": "done", "status": "completed",
             "validation": {"command": "true"}},
        ], cost=cost)

    def _payload(self, **extra):
        return {"cwd": self.tmpdir, **extra}

    def test_blocks_when_actual_null(self):
        self._done_board({"estimated_tokens": 50000, "actual_tokens": None})
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("actual_tokens", data["reason"])
        self.assertIn("50000", data["reason"], "the estimate it checks is named")

    def test_allows_when_actual_recorded(self):
        self._done_board({"estimated_tokens": 50000, "actual_tokens": 61234})
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "cost recorded -> nothing left to hold")

    def test_asks_once_only(self):
        """stop_hook_active is the loop guard: a refused cost must not trap the session."""
        self._done_board({"estimated_tokens": 50000, "actual_tokens": None})
        code, stdout, _ = run_hook(STOP_HOOK, self._payload(stop_hook_active=True))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_unmeasured_closes_the_gate(self):
        """A gate satisfiable only by a number is satisfiable only by inventing one."""
        self._done_board({"estimated_tokens": 50000, "actual_tokens": "unmeasured"})
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "", "an honest 'cannot measure' must close it")

    def test_block_message_offers_the_honest_exit(self):
        self._done_board({"estimated_tokens": 50000, "actual_tokens": None})
        _, stdout, _ = run_hook(STOP_HOOK, self._payload())
        reason = json.loads(stdout)["reason"]
        self.assertIn("unmeasured", reason)
        self.assertIn("do not invent", reason.lower())

    def test_legacy_root_exempt(self):
        """harness-tasks.json predates the cost block; it must not fire there."""
        write_tasks(self.root, [{"id": "t1", "title": "done", "status": "completed"}])
        code, stdout, _ = run_hook(STOP_HOOK, self._payload())
        self.assertEqual(stdout, "", "no board -> no campaign contract")


# ---------------------------------------------------------------------------
# PreCompact drift warning -- measured 2026-08-26: this event CAN block via
# exit 2, but carries no stop_hook_active, so this hook only warns.
# ---------------------------------------------------------------------------
class TestPreCompactDrift(unittest.TestCase):
    """HUB.md trailing board.json is reported, never enforced."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        write_board(self.root, [{"id": "t1", "title": "x", "status": "pending"}])
        self.hub = self.root / ".orchestration" / "HUB.md"
        self.hub.write_text("# campaign\n", encoding="utf-8")
        self.board = self.root / ".orchestration" / "board.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _age_hub(self, seconds):
        st = self.board.stat()
        os.utime(self.hub, (st.st_atime - seconds, st.st_mtime - seconds))

    def _payload(self, **extra):
        return {"cwd": self.tmpdir, "hook_event_name": "PreCompact",
                "trigger": "manual", **extra}

    def test_warns_on_drift(self):
        self._age_hub(3600)
        code, stdout, stderr = run_hook(PRECOMPACT_HOOK, self._payload())
        self.assertEqual(code, 0, "warning only -- exit 2 would refuse the compaction")
        data = json.loads(stdout)
        self.assertTrue(data["continue"], "compaction must proceed")
        self.assertIn("HUB.md", data["systemMessage"])
        self.assertEqual(stderr, "", "stderr on this event is a user-visible refusal")

    def test_silent_within_tolerance(self):
        self._age_hub(60)
        code, stdout, _ = run_hook(PRECOMPACT_HOOK, self._payload())
        self.assertEqual(stdout, "", "HUB written seconds after the board is normal")

    def test_silent_when_campaign_closed(self):
        write_board(self.root, [{"id": "t1", "title": "x", "status": "pending"}],
                    status="closed")
        self._age_hub(3600)
        code, stdout, _ = run_hook(PRECOMPACT_HOOK, self._payload())
        self.assertEqual(stdout, "", "a closed campaign keeps its board; it is not active")

    def test_silent_without_hub(self):
        self.hub.unlink()
        code, stdout, _ = run_hook(PRECOMPACT_HOOK, self._payload())
        self.assertEqual(stdout, "", "no prose half -> nothing to drift from")

    def test_silent_at_exact_tolerance(self):
        """skew == SKEW_TOLERANCE_SECONDS is inside the window; the guard is `<=`.

        Exit code is asserted, not just stdout: a silent path that returned 2
        would refuse the compaction while printing nothing, which every other
        silent test here would also miss.
        """
        self._age_hub(SKEW_TOLERANCE_SECONDS)
        code, stdout, _ = run_hook(PRECOMPACT_HOOK, self._payload())
        self.assertEqual(code, 0, "silence must still exit 0 -- 2 blocks compaction")
        self.assertEqual(stdout, "", "a skew exactly at the tolerance is not drift")

    def test_warns_one_second_past_tolerance(self):
        """The open side of the same boundary: T + 1 is the first skew that warns.

        Paired with test_silent_at_exact_tolerance. Either test alone leaves the
        window free to slide -- `skew <= T + 1` keeps T silent and still warns at
        the 3600s used by test_warns_on_drift, so only the two together pin it.
        """
        self._age_hub(SKEW_TOLERANCE_SECONDS + 1)
        code, stdout, stderr = run_hook(PRECOMPACT_HOOK, self._payload())
        self.assertEqual(code, 0, "warning only -- exit 2 would refuse the compaction")
        data = json.loads(stdout)
        self.assertTrue(data["continue"], "compaction must proceed")
        self.assertIn("HUB.md", data["systemMessage"])
        self.assertEqual(stderr, "", "stderr on this event is a user-visible refusal")


class TestBoardPathFollowsTheStore(unittest.TestCase):
    """store-spec.md §7 stage 2 (fallback removal): the resolvers are
    anchor-gated, not existence-gated. A parseable `.hq/.anchor` sends a
    project to `.hq/` only -- no fallback to the legacy path, even when a
    legacy file still exists on disk. No anchor sends it to the legacy path
    only -- exactly as before stage 2 -- even when a `.hq/` file exists.
    """

    def setUp(self):
        sys.path.insert(0, str(HOOKS_DIR))
        import _harness_common as hc
        self.hc = hc
        self.root = Path(tempfile.mkdtemp())

    def _board(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"status": "active", "tasks": [], "workers": []}')
        return p

    def _anchor(self, anchor_id: str = "t1") -> None:
        d = self.root / ".hq"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".anchor").write_text(f"id: {anchor_id}\n", encoding="utf-8")

    def test_anchored_project_resolves_hq_board_when_only_legacy_file_exists(self):
        """Acceptance (a): stage 2 has no fallback -- the anchor alone decides."""
        self._anchor()
        self._board(".orchestration/board.json")
        want = self.root / ".hq" / "runtime" / "board.json"
        self.assertEqual(self.hc.board_path(self.root), want)

    def test_unanchored_project_resolves_legacy_board_when_only_hq_file_exists(self):
        """Acceptance (b): no anchor means legacy only, exactly as before
        stage 2 -- even though root discovery (a separate concern) still
        finds this root via the .hq marker (store-spec §6's ROOT_MARKERS)."""
        self._board(".hq/runtime/board.json")
        want = self.root / ".orchestration" / "board.json"
        self.assertEqual(self.hc.board_path(self.root), want)
        self.assertEqual(self.hc.find_harness_root({"cwd": str(self.root)}),
                         self.root.resolve())

    def test_anchored_project_resolves_hq_board_when_both_exist(self):
        self._anchor()
        self._board(".orchestration/board.json")
        want = self._board(".hq/runtime/board.json")
        self.assertEqual(self.hc.board_path(self.root), want)

    def test_unanchored_project_resolves_legacy_board_when_both_exist(self):
        want = self._board(".orchestration/board.json")
        self._board(".hq/runtime/board.json")
        self.assertEqual(self.hc.board_path(self.root), want)

    def test_unanchored_project_with_neither_file_still_reports_the_legacy_path(self):
        """Every existing message and test names the legacy string; keep it."""
        self.assertEqual(self.hc.board_path(self.root),
                         self.root / ".orchestration" / "board.json")
        self.assertIsNone(self.hc.find_harness_root({"cwd": str(self.root)}))

    def test_unparseable_anchor_is_read_as_absent_and_falls_back_to_legacy(self):
        """A corrupt anchor is not routed into a half-broken `.hq/` -- that
        loud failure is gate_corrupt_reason()'s job, at hook entry, separate
        from this resolver."""
        d = self.root / ".hq"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".anchor").write_text("not an id line\nsecond line\n", encoding="utf-8")
        want = self._board(".orchestration/board.json")
        self.assertEqual(self.hc.board_path(self.root), want)

    def test_observations_sit_beside_whichever_board_the_anchor_resolves(self):
        self._anchor()
        self.assertEqual(self.hc.observations_jsonl(self.root),
                         self.root / ".hq" / "runtime" / "observations.jsonl")

    def test_agent_memory_and_hub_resolve_to_hq_community_on_an_anchored_project(self):
        """Acceptance (c)."""
        self._anchor()
        self.assertEqual(self.hc.agent_memory_md(self.root, "orca"),
                         self.root / ".hq" / "community" / "agents" / "orca.md")
        self.assertEqual(self.hc.hub_md(self.root),
                         self.root / ".hq" / "community" / "HUB.md")

    def test_agent_memory_and_hub_resolve_to_legacy_on_an_unanchored_project(self):
        self.assertEqual(self.hc.agent_memory_md(self.root, "orca"),
                         self.root / ".orchestration" / "agents" / "orca.md")
        self.assertEqual(self.hc.hub_md(self.root),
                         self.root / ".orchestration" / "HUB.md")


# ---------------------------------------------------------------------------
# Claim hook -- retryability must match the Stop hook's failure count
# ---------------------------------------------------------------------------
class TestRootLocalLock(unittest.TestCase):
    """The state lock lives in the root itself (root/.harness.lock) so TMPDIR
    drift between sessions cannot split it. Before 2026-08-31 it hashed the
    root into tempfile.gettempdir(), and two sessions with different TMPDIR
    values locked different directories."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        sys.path.insert(0, str(HOOKS_DIR))
        import _harness_common as hc
        self.hc = hc

    def tearDown(self):
        import shutil
        sys.path.remove(str(HOOKS_DIR))
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_lockdir_is_root_local(self):
        self.assertEqual(self.hc.lockdir_for_root(self.root),
                         self.root / ".harness.lock")

    def test_acquire_creates_and_release_removes_in_root(self):
        lockdir = self.hc.lockdir_for_root(self.root)
        self.hc.acquire_lock(lockdir, 1.0)
        self.assertTrue(lockdir.is_dir())
        self.hc.release_lock(lockdir)
        self.assertFalse(lockdir.exists())


class TestClaimHook(unittest.TestCase):
    """harness-claim.py judges retryability on effective attempts --
    max(attempts, logged ERROR lines) -- the same count the Stop hook
    enforces. Before 2026-08-31 it read raw `attempts` and would hand a
    ruled-out task straight back into rotation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _claim(self):
        code, stdout, stderr = run_hook(CLAIM_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0, stderr)
        return json.loads(stdout)

    def test_pending_task_is_claimed(self):
        write_tasks(self.root, [
            {"id": "t1", "title": "Work", "status": "pending", "priority": "P0", "depends_on": []},
        ])
        res = self._claim()
        self.assertTrue(res["claimed"])
        self.assertEqual(res["task_id"], "t1")
        state = json.loads((self.root / "harness-tasks.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"][0]["status"], "in_progress")

    def test_logged_errors_exhaust_claim_retries(self):
        """attempts:0 with 3 logged ERRORs >= max_attempts:3 -> refuse the claim.

        This is the fixture the Stop hook already allows a stop on
        (test_logged_errors_exhaust_retries); the claim path must agree.
        """
        (self.root / "harness-progress.txt").write_text(
            "[2026-08-26T10:00:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] one\n"
            "[2026-08-26T10:05:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] two\n"
            "[2026-08-26T10:10:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] three\n"
        )
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 0, "max_attempts": 3, "depends_on": []},
        ])
        res = self._claim()
        self.assertFalse(res["claimed"])

    def test_logged_errors_below_max_still_claimable(self):
        (self.root / "harness-progress.txt").write_text(
            "[2026-08-26T10:00:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] one\n"
        )
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 0, "max_attempts": 3, "depends_on": []},
        ])
        res = self._claim()
        self.assertTrue(res["claimed"])

    def test_sessionstart_does_not_advertise_exhausted_task(self):
        """Display must agree with enforcement: a task the Stop hook ruled
        out on logged failures must not be shown as `next=`."""
        (self.root / "harness-progress.txt").write_text(
            "[2026-08-26T10:00:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] one\n"
            "[2026-08-26T10:05:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] two\n"
            "[2026-08-26T10:10:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] three\n"
        )
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 0, "max_attempts": 3, "depends_on": []},
        ])
        activate(self.root)
        code, stdout, _ = run_hook(SESSION_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)
        self.assertNotIn("next=t1", stdout)

    def test_teammateidle_agrees_with_stop_on_logged_errors(self):
        """A task the Stop hook ruled out must not keep a teammate awake."""
        (self.root / "harness-progress.txt").write_text(
            "[2026-08-26T10:00:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] one\n"
            "[2026-08-26T10:05:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] two\n"
            "[2026-08-26T10:10:00Z] [SESSION-1] ERROR [t1] [TASK_EXEC] three\n"
        )
        write_tasks(self.root, [
            {"id": "t1", "status": "failed", "attempts": 0, "max_attempts": 3, "depends_on": []},
        ])
        activate(self.root)
        code, _, _ = run_hook(IDLE_HOOK, {"cwd": self.tmpdir})
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

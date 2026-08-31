---
name: harness
description: "This skill should be used for multi-session autonomous agent work requiring progress checkpointing, failure recovery, and task dependency management. Triggers on '/harness' command, or when a task involves many subtasks needing progress persistence, sleep/resume cycles across context windows, recovery from mid-task failures with partial state, or distributed work across multiple agent sessions. Synthesized from Anthropic and OpenAI engineering practices for long-running agents."
---

# Harness — Long-Running Agent Framework

Executable protocol enabling any agent task to run continuously across multiple sessions with automatic progress recovery, task dependency resolution, failure rollback, and standardized error handling.

## Design Principles

1. **Design for the agent, not the human** — Test output, docs, and task structure are the agent's primary interface
2. **Progress files ARE the context** — When context window resets, progress files + git history = full recovery
3. **Premature completion is the #1 failure mode** — Structured task lists with explicit completion criteria prevent declaring victory early
4. **Standardize everything grep-able** — ERROR on same line, structured timestamps, consistent prefixes
5. **Fast feedback loops** — Pre-compute stats, run smoke tests before full validation
6. **Idempotent everything** — Init scripts, task execution, environment setup must all be safe to re-run
7. **Fail safe, not fail silent** — Every failure must have an explicit recovery strategy

## Commands

```
/harness init <project-path>     # Initialize harness files in project
/harness run                     # Start/resume the infinite loop
/harness status                  # Show current progress and stats
/harness add "task description"  # Add a task to the list
```

## The `hq` store CLI

**The operating surface moved to the `community` skill** (0.10.0). Every verb — `post`,
`comment`, `edit`, `query`, `index`, `lint`, `gc` — its flags, and the rules for using
them live there. `hq` is the only supported writer for the post store; a hand-written
post drifts from the schema and `hq lint` is the only thing that catches it.

The extraction is not cosmetic. This card is 28,000+ characters, which
`omo/references/vendor-ops.md` measures at 1.8x the whole `--skills` budget, so a vendor
worker could never be handed the board's operating rules. The `community` card is under
6,000 and fits.

The design SSOT stays here: `references/store-spec.md` — the four layers, the post
schema, and the anchor rules.

> **The binding layer is still weak.** The `community` skill is a routing layer, not an
> enforcing one; nothing in a `PreToolUse` hook names `hq`, so a session under momentum
> can still hand-write a post. Two tools in this project died exactly there —
> `tokensave` (6 MCP calls against 10,813 tool calls) and `graphify`'s MCP server (0
> calls in 30 days), both because the nudge layer named something else. Wiring a guard
> that names `hq` is tracked as P6, and should be measured for firing rate before it
> blocks anything.

## Activation Gate

Hooks take effect only when the board reads `"status": "active"`. The board is
`.hq/runtime/board.json` for an anchored project (a parseable `.hq/.anchor`); a
project without an anchor still keeps it at `.orchestration/board.json`.
`_harness_common.board_path()` is anchor-gated (store-spec §7 stage 2) — the
anchor alone decides, no existence check and no fallback in either direction.

A closed campaign keeps its board on disk — preserving the posts is the convention —
so *presence* of the file cannot mean active. The gate has to be a status bit.

- `/harness init` and `/harness run` set `status: "active"`.
- When no eligible task remains, set `status: "closed"`. Do not delete the board.
- Any other status value, or **a missing board**: every hook exits 0 immediately. No
  board means no active campaign, which is a legitimate off state — the board is
  machine-local runtime state, so a fresh clone correctly has none.
- **A board that will not parse is not an off state — it is a loud failure (exit
  non-zero).** A corrupt board read as an absent one is a hook that has silently stopped
  while looking exactly like a hook that correctly decided it had no work. This reverses
  half of the older rule here, which swallowed both cases.

That is two of four states. The full gate is the pair (legacy `.om?` store,
`.hq/.anchor`) and `references/store-spec.md` §6 owns the table. The state it adds that
this section cannot express is "legacy store present, anchor absent" — migration not yet
done — which must **warn: reads will not find the legacy store** (store-spec §7 stage 2
has no fallback) rather than fall quiet.

> **Implemented.** The loud-failure branch lives in `hq/anchor.py`'s `gate_state()`,
> wired into every hook via `_harness_common.gate_corrupt_reason()`. Unit fixtures for
> all four states are in `tests/test_hq.py`'s `GateStateTest`; the corrupt row's
> end-to-end behavior through the real hooks is in `tests/test_hooks.py`'s
> `TestCorruptGate`.

**Legacy roots.** A project that still has `harness-tasks.json` and no
`.orchestration/` keeps gating on the old `.harness-active` marker file, and hooks
read `harness-tasks.json` as before. When both exist, the board wins. Migrate by
writing the board — `.hq/runtime/board.json` under a `.hq/.anchor`, or
`.orchestration/board.json` on an unanchored project — and removing the marker.

## Board (`.hq/runtime/board.json`)

The only state the hooks read. Seed: `templates/orchestration/board.json`.

| Field | Meaning |
|---|---|
| `status` | `active` \| `closed` — the activation gate above |
| `owning_session` | Who launched this campaign |
| `cost.estimated_tokens` / `cost.actual_tokens` | The ledger. Estimated at launch, actual at close; `null` until then |
| `workers[]` | `role`, `vendor`, `model`, `writes_repo`, `worktree`, `status`, `orca_dispatch_id` |
| `tasks[]` | As in the schema below — ids, deps, attempts, validation, rollback commit |

`workers[].status` is `planned` → `claimed` → `reported` → `closed`. These are
campaign terms, not process terms: a board file cannot know whether a process is
running, and Orca's own worker state has nine values including three-way liveness.
Copying process state here would put two sources of truth on one fact.

`orca_dispatch_id` is an **opaque pointer**, and `null` is a normal value. It is the
only seam to Orca and it is one-directional. Do not mirror Orca state into the board:
the harness has to run without Orca, and a hook that needs a live Orca runtime to
evaluate the gate hard-fails on any machine that does not have one.

## Campaign Layer

A campaign is many workers on one board. Its protocol — the six-line launch proposal,
the five post categories with globally monotonic numbering, the two memory layers,
the worker brief, reporting-as-termination, worker reuse, and the cost ledger — is in
`references/campaign-protocol.md`. Every rule there was paid for by an incident.

The boundary with Orca, and why the board does not mirror its state:
`references/orca-boundary.md`.

## Enforcement Surface

Measured on claude 2.1.239. The design that assumed spawn-time blocking does not
work — do not revive it.

| Hook | What it can do | Evidence |
|---|---|---|
| `SubagentStart` | **Inject only.** Its output schema carries one field, `additionalContext`, and the call site does not cancel a spawn on the hook's result. Both `exit 2` and a JSON `blockingError` were tried; the subagent ran either way. Its stderr never reaches the user. | 0-A, 0-B |
| `SubagentStart` | **Observe only.** Board mismatches go to `observations.jsonl` beside the board *and* into the injected context, because the subagent is the only path a notice has to a human. | 0-A |
| `SubagentStop` | **Enforce.** `exit 2` + stderr holds the exit and forces the subagent to resume. A JSON `{"decision": "block"}` gates it too; the code uses `exit 2`. | 0-C, 0-I |
| `TeammateIdle` | **Never fires** for Agent-tool subagents. The Agent tool makes a `local_agent`; `TeammateIdle` is `in_process_teammate` only. The hook is kept wired for the day that changes, but nothing routes through it. | 0-C |
| `Stop` | **Enforce.** Both conventions gate it. Holds the campaign's close until `board.json` records `cost.actual_tokens` — once, guarded on `stop_hook_active`. The payload carries no token counts, so the figure comes from the board and the hook only asks. | 0-F, 0-H |
| `PreCompact` | **Warn only** — by choice, not by limit. It *can* block, and the refusal reaches the user verbatim. It must not: this event has no `stop_hook_active`, so a blocking hook has no loop guard and a wrong one makes compaction impossible at the context ceiling. It warns when `board.json` runs more than 15 minutes ahead of `HUB.md`. | 0-G |

Three consequences worth stating plainly:

**A launch gate is a nudge, not a gate.** Nothing stops a spawn. What replaces it is
three weaker things stacked: the skill prose, the board check at spawn time, and the
post-hoc rejection at `SubagentStop`. Design as if the spawn always succeeds.

**The loop guard is ours.** `stop_hook_active` arrives `true` on the turn a rejection
caused. Claude Code provides no cutoff of its own — handing us that flag *is* the
contract that we cut the loop. Every blocking hook returns 0 when it is set.

**The blocking convention is per-event. Never generalize one event's result to
another.** `SubagentStart` refuses both conventions; `Stop` and `SubagentStop` accept
both; `PreCompact` accepts `exit 2`. Every row above was measured on its own event,
and the one row that was inferred rather than measured turned out wrong. If you add a
hook on an event not in this table, measure it before you rely on it — the rig is in
the vault under `measurements/probes/`.

### Injection cap

`hookSpecificOutput.additionalContext` is honored only in the nested form carrying
`hookEventName`; a top-level `additionalContext` is ignored. 9,800 characters arrive
intact; 10,400 are truncated to a 2KB preview and spilled to a file the subagent then
has to go read. The hook caps at 10,000 and drops role memory before it drops a
mismatch notice.

### Completion has to be runnable

Enforced on board-backed campaigns only. The Stop hook holds the turn when:

- a task is `completed` with no `validation.command` — a completion nothing can
  check is not a completion, and premature completion is this harness's named #1
  failure mode;
- a task is `in_progress` with no `started_at_commit` — there is no commit to reset
  to, so a failure has no rollback and the tree keeps whatever the attempt left.

A legacy `harness-tasks.json` root is not held to this. Those boards predate the
fields, and turning every task without them into a blocker fires on projects that
simply do not use them. The seeded board ships both, so a campaign has them from
task one.

### What a worker owes before it stops

Enforced only against a **declared roster**. An empty `workers[]` means the campaign
cannot judge membership, and rejecting every ad-hoc subagent is the false positive
that gets a hook switched off.

1. Be on the board. An unregistered role is either a missing row or a spawn that does
   not belong to this campaign.
2. Have written `.hq/community/agents/<role>.md` — 40 lines maximum, semantic rather
   than chronological, append-only.
3. Have reported: a post under `.hq/community/posts/`, and `workers[].status` set to
   `reported`. **Reporting is what ends the work, not finishing it quietly.**

## Progress Persistence (Dual-File System)

Two files, one per layer: `.hq/runtime/board.json` holds structured state, and
`harness-progress.txt` holds the free-text log. The board says what is true now; the
log says what happened. Neither substitutes for the other -- a failure count read
only from the board is a self-report, which is why the Stop hook cross-checks it
against the log's ERROR lines.

### harness-progress.txt (Append-Only Log)

Free-text log of all agent actions across sessions. Never truncate.

```
[2025-07-01T10:00:00Z] [SESSION-1] INIT Harness initialized for project /path/to/project
[2025-07-01T10:00:05Z] [SESSION-1] INIT Environment health check: PASS
[2025-07-01T10:00:10Z] [SESSION-1] LOCK acquired (pid=12345)
[2025-07-01T10:00:11Z] [SESSION-1] Starting [task-001] Implement user authentication (base=def5678)
[2025-07-01T10:05:00Z] [SESSION-1] CHECKPOINT [task-001] step=2/4 "auth routes created, tests pending"
[2025-07-01T10:15:30Z] [SESSION-1] Completed [task-001] (commit abc1234)
[2025-07-01T10:15:31Z] [SESSION-1] Starting [task-002] Add rate limiting (base=abc1234)
[2025-07-01T10:20:00Z] [SESSION-1] ERROR [task-002] [TASK_EXEC] Redis connection refused
[2025-07-01T10:20:01Z] [SESSION-1] ROLLBACK [task-002] git reset --hard abc1234
[2025-07-01T10:20:02Z] [SESSION-1] STATS tasks_total=5 completed=1 failed=1 pending=3 blocked=0 attempts_total=2 checkpoints=1
```

### `.hq/runtime/board.json` `tasks[]` (Structured State)

The shape below is the `tasks[]` array of the board, plus `session_config` and the
session counters, which live at the board's top level alongside `status`, `workers`,
and `cost`. Legacy roots carry the same object as `harness-tasks.json`.

```json
{
  "version": 2,
  "created": "2025-07-01T10:00:00Z",
  "session_config": {
    "concurrency_mode": "exclusive",
    "max_tasks_per_session": 20,
    "max_sessions": 50
  },
  "tasks": [
    {
      "id": "task-001",
      "title": "Implement user authentication",
      "status": "completed",
      "priority": "P0",
      "depends_on": [],
      "attempts": 1,
      "max_attempts": 3,
      "started_at_commit": "def5678",
      "validation": {
        "command": "npm test -- --testPathPattern=auth",
        "timeout_seconds": 300
      },
      "on_failure": {
        "cleanup": null
      },
      "error_log": [],
      "checkpoints": [],
      "completed_at": "2025-07-01T10:15:30Z"
    },
    {
      "id": "task-002",
      "title": "Add rate limiting",
      "status": "failed",
      "priority": "P1",
      "depends_on": [],
      "attempts": 1,
      "max_attempts": 3,
      "started_at_commit": "abc1234",
      "validation": {
        "command": "npm test -- --testPathPattern=rate-limit",
        "timeout_seconds": 120
      },
      "on_failure": {
        "cleanup": "docker compose down redis"
      },
      "error_log": ["[TASK_EXEC] Redis connection refused"],
      "checkpoints": [],
      "completed_at": null
    },
    {
      "id": "task-003",
      "title": "Add OAuth providers",
      "status": "pending",
      "priority": "P1",
      "depends_on": ["task-001"],
      "attempts": 0,
      "max_attempts": 3,
      "started_at_commit": null,
      "validation": {
        "command": "npm test -- --testPathPattern=oauth",
        "timeout_seconds": 180
      },
      "on_failure": {
        "cleanup": null
      },
      "error_log": [],
      "checkpoints": [],
      "completed_at": null
    }
  ],
  "session_count": 1,
  "last_session": "2025-07-01T10:20:02Z"
}
```

Task statuses: `pending` → `in_progress` (transient, set only during active execution) → `completed` or `failed`. A task found as `in_progress` at session start means the previous session was interrupted — handle via Context Window Recovery Protocol.

In concurrent mode (see Concurrency Control), tasks may also carry claim metadata: `claimed_by` and `lease_expires_at` (ISO timestamp).

**Session boundary**: A session starts when the agent begins executing the Session Start protocol and ends when a Stopping Condition is met or the context window resets. Each session gets a unique `SESSION-N` identifier (N = `session_count` after increment).

## Concurrency Control

Before modifying the state file (the board; legacy `harness-tasks.json`), acquire an exclusive lock using portable `mkdir` (atomic on all POSIX systems, works on both macOS and Linux):

```bash
# Acquire lock (fail fast if another agent is running)
# The lock lives in the state root itself (matches the hooks'
# _harness_common.lockdir_for_root): TMPDIR drift between sessions cannot
# split it, and a symlinked cwd reaches the same lockdir inode either way.
# Root discovery must still match find_harness_root: HARNESS_STATE_ROOT
# first when it carries a marker, then ascend from CLAUDE_PROJECT_DIR,
# then from the physical cwd (pwd -P) -- same order as the Python side,
# or the two implementations lock different roots (codex review 2026-08-31).
has_marker() {
  [ -f "$1/.hq/runtime/board.json" ] || [ -f "$1/.orchestration/board.json" ] || [ -f "$1/harness-tasks.json" ]
}
ROOT="${HARNESS_STATE_ROOT:-}"
[ -n "$ROOT" ] && ROOT="$(cd "$ROOT" 2>/dev/null && pwd -P || printf '%s' "$ROOT")"
if [ -z "$ROOT" ] || ! has_marker "$ROOT"; then
  ROOT=""
  for START in "${CLAUDE_PROJECT_DIR:-}" "$(pwd -P)"; do
    [ -n "$START" ] || continue
    SEARCH="$(cd "$START" 2>/dev/null && pwd -P)" || continue
    while [ "$SEARCH" != "/" ] && ! has_marker "$SEARCH"; do
      SEARCH="$(dirname "$SEARCH")"
    done
    if has_marker "$SEARCH"; then ROOT="$SEARCH"; break; fi
  done
  [ -n "$ROOT" ] || ROOT="$(pwd -P)"
fi

LOCKDIR="$ROOT/.harness.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  # Check if lock holder is still alive
  LOCK_PID=$(cat "$LOCKDIR/pid" 2>/dev/null)
  if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "ERROR: Another harness session is active (pid=$LOCK_PID)"; exit 1
  fi
  # Stale lock — atomically reclaim via mv to avoid TOCTOU race
  STALE="$LOCKDIR.stale.$$"
  if mv "$LOCKDIR" "$STALE" 2>/dev/null; then
    rm -rf "$STALE"
    mkdir "$LOCKDIR" || { echo "ERROR: Lock contention"; exit 1; }
    echo "WARN: Removed stale lock${LOCK_PID:+ from pid=$LOCK_PID}"
  else
    echo "ERROR: Another agent reclaimed the lock"; exit 1
  fi
fi
echo "$$" > "$LOCKDIR/pid"
trap 'rm -rf "$LOCKDIR"' EXIT
```

Log lock acquisition: `[timestamp] [SESSION-N] LOCK acquired (pid=<PID>)`
Log lock release: `[timestamp] [SESSION-N] LOCK released`

Modes:

- **Exclusive (default)**: hold the lock for the entire session (the `trap EXIT` handler releases it automatically). Any second session in the same state root fails fast.
- **Concurrent (opt-in via `session_config.concurrency_mode: "concurrent"`)**: treat this as a **state transaction lock**. Hold it only while reading/modifying/writing `harness-tasks.json` (including `.bak`/`.tmp`) and appending to `harness-progress.txt`. Release it immediately before doing real work.

Concurrent mode invariants:

- All workers MUST point at the same state root (the directory that contains `harness-tasks.json`). If you are using separate worktrees/clones, pin it explicitly (e.g., `HARNESS_STATE_ROOT=/abs/path/to/state-root`).
- Task selection is advisory; the real gate is **atomic claim** under the lock: set `status="in_progress"`, set `claimed_by` (stable worker id, e.g., `HARNESS_WORKER_ID`), set `lease_expires_at`. If claim fails (already `in_progress` with a valid lease), pick another eligible task and retry.
- Never run two workers in the same git working directory. Use separate worktrees/clones. Otherwise rollback (`git reset --hard` / `git clean -fd`) will destroy other workers.

## Infinite Loop Protocol

### Session Start (Execute Every Time)

1. **Read state**: Read last 200 lines of `harness-progress.txt` + the full state file (the board; legacy `harness-tasks.json`). If JSON is unparseable, see JSON corruption recovery in Error Handling.
2. **Read git**: Run `git log --oneline -20` and `git diff --stat` to detect uncommitted work
3. **Acquire lock** (mode-dependent): Exclusive mode fails if another session is active. Concurrent mode uses the lock only for state transactions.
4. **Recover interrupted tasks** (see Context Window Recovery below)
5. **Health check**: Run `harness-init.sh` if it exists
6. **Track session**: Increment `session_count` in JSON. Check `session_count` against `max_sessions` — if reached, log STATS and STOP. Initialize per-session task counter to 0.
7. **Pick next task** using Task Selection Algorithm below

### Task Selection Algorithm

Before selecting, run dependency validation:

1. **Cycle detection**: For each non-completed task, walk `depends_on` transitively. If any task appears in its own chain, mark it `failed` with `[DEPENDENCY] Circular dependency detected: task-A -> task-B -> task-A`. Self-references (`depends_on` includes own id) are also cycles.
2. **Blocked propagation**: If a task's `depends_on` includes a task that is `failed` and will never be retried (either its effective failure count -- `max(attempts, ERROR lines for that id in the progress log)`, see Retry Escalation -- has reached `max_attempts`, OR its `error_log` contains a `[DEPENDENCY]` entry), mark the blocked task as `failed` with `[DEPENDENCY] Blocked by failed task-XXX`. Repeat until no more tasks can be propagated.

Then pick the next task in this priority order:

1. Tasks with `status: "pending"` where ALL `depends_on` tasks are `completed` — sorted by `priority` (P0 > P1 > P2), then by `id` (lowest first)
2. Tasks with `status: "failed"` whose effective failure count (`max(attempts, logged ERROR lines)` — the count every hook enforces) is below `max_attempts`, and ALL `depends_on` are `completed` — sorted by priority, then oldest failure first
3. If no eligible tasks remain → log final STATS → STOP

### Retry Escalation (3-Strike)

A task's failure count is `max(attempts, ERROR lines for that task id in
harness-progress.txt)`. The declared `attempts` field is written by whoever ran the
task; the log is what happened. Taking the larger of the two means a session that
forgets to bump `attempts` cannot earn unlimited retries.

At **2 failures**, the Stop hook stops emitting the generic continue message and
emits `ESCALATION REQUIRED` instead. A third attempt at the same approach is the
same failure again, so before retrying, change one of these and say which:

1. **The vendor** — route the task to a different *model* than the last attempt
   used. A different backend running the same model family is the same prior, not a
   second opinion. This is `omo` delegation ground 3.
2. **The approach** — state the new hypothesis and how it differs from the two that
   failed.

The retry prompt carries both prior attempts and what was observed, not just the
symptom. If neither can change, mark the task blocked with the evidence.

### Task Execution Cycle

For each task, execute this exact sequence:

1. **Claim** (atomic, under lock): Record `started_at_commit` = current HEAD hash. Set status to `in_progress`, set `claimed_by`, set `lease_expires_at`, log `Starting [<task-id>] <title> (base=<hash>)`. If the task is already claimed (`in_progress` with a valid lease), pick another eligible task and retry.
2. **Execute with checkpoints**: Perform the work. After each significant step, log:
   ```
   [timestamp] [SESSION-N] CHECKPOINT [task-id] step=M/N "description of what was done"
   ```
   Also append to the task's `checkpoints` array: `{ "step": M, "total": N, "description": "...", "timestamp": "ISO" }`. In concurrent mode, renew the lease at each checkpoint (push `lease_expires_at` forward).
3. **Validate**: Run the task's `validation.command` with a timeout wrapper (prefer `timeout`; on macOS use `gtimeout` from coreutils). If `validation.command` is empty/null, log `ERROR [<task-id>] [CONFIG] Missing validation.command` and STOP — do not declare completion without an objective check. Before running, verify the command exists (e.g., `command -v <binary>`) — if missing, treat as `ENV_SETUP` error.
   - Command exits 0 → PASS
   - Command exits non-zero → FAIL
   - Command exceeds timeout → TIMEOUT
4. **Record outcome**:
   - **Success**: status=`completed`, set `completed_at`, log `Completed [<task-id>] (commit <hash>)`, git commit
   - **Failure**: increment `attempts`, append error to `error_log`. Verify `started_at_commit` exists via `git cat-file -t <hash>` — if missing, mark failed at max_attempts. Otherwise execute `git reset --hard <started_at_commit>` and `git clean -fd` to rollback ALL commits and remove untracked files. Execute `on_failure.cleanup` if defined. Log `ERROR [<task-id>] [<category>] <message>`. Set status=`failed` (Task Selection Algorithm pass 2 handles retries when attempts < max_attempts)
5. **Track**: Increment per-session task counter. If `max_tasks_per_session` reached, log STATS and STOP.
6. **Continue**: Immediately pick next task (zero idle time)

### Stopping Conditions

- All tasks `completed`
- All remaining tasks `failed` at max_attempts or blocked by failed dependencies
- `session_config.max_tasks_per_session` reached for this session
- `session_config.max_sessions` reached across all sessions
- User interrupts

## Context Window Recovery Protocol

When a new session starts and finds a task with `status: "in_progress"`:

- Exclusive mode: treat this as an interrupted previous session and run the Recovery Protocol below.
- Concurrent mode: only recover a task if either (a) `claimed_by` matches this worker, or (b) `lease_expires_at` is in the past (stale lease). Otherwise, treat it as owned by another worker and do not modify it.

1. **Check git state**:
   ```bash
   git diff --stat          # Uncommitted changes?
   git log --oneline -5     # Recent commits since task started?
   git stash list           # Any stashed work?
   ```
2. **Check checkpoints**: Read the task's `checkpoints` array to determine last completed step
3. **Decision matrix** (verify recent commits belong to this task by checking commit messages for the task-id):

| Uncommitted? | Recent task commits? | Checkpoints? | Action |
|---|---|---|---|
| No | No | None | Mark `failed` with `[SESSION_TIMEOUT] No progress detected`, increment attempts |
| No | No | Some | Verify file state matches checkpoint claims. If files reflect checkpoint progress, resume from last step. If not, mark `failed` — work was lost |
| No | Yes | Any | Run `validation.command`. If passes → mark `completed`. If fails → `git reset --hard <started_at_commit>`, mark `failed` |
| Yes | No | Any | Run validation WITH uncommitted changes present. If passes → commit, mark `completed`. If fails → `git reset --hard <started_at_commit>` + `git clean -fd`, mark `failed` |
| Yes | Yes | Any | Commit uncommitted changes, run `validation.command`. If passes → mark `completed`. If fails → `git reset --hard <started_at_commit>` + `git clean -fd`, mark `failed` |

4. **Log recovery**: `[timestamp] [SESSION-N] RECOVERY [task-id] action="<action taken>" reason="<reason>"`

## Error Handling & Recovery Strategies

Each error category has a default recovery strategy:

| Category | Default Recovery | Agent Action |
|----------|-----------------|--------------|
| `ENV_SETUP` | Re-run init, then STOP if still failing | Run `harness-init.sh` again immediately. If fails twice, log and stop — environment is broken |
| `CONFIG` | STOP (requires human fix) | Log the config error precisely (file + field), then STOP. Do not guess or auto-mutate task metadata |
| `TASK_EXEC` | Rollback via `git reset --hard <started_at_commit>`, retry | Verify `started_at_commit` exists (`git cat-file -t <hash>`). If missing, mark failed at max_attempts. Otherwise reset, run `on_failure.cleanup` if defined, retry if attempts < max_attempts |
| `TEST_FAIL` | Rollback via `git reset --hard <started_at_commit>`, retry | Reset to `started_at_commit`, analyze test output to identify fix, retry with targeted changes |
| `TIMEOUT` | Kill process, execute cleanup, retry | Wrap validation with `timeout <seconds> <command>`. On timeout, run `on_failure.cleanup`, retry (consider splitting task if repeated) |
| `DEPENDENCY` | Skip task, mark blocked | Log which dependency failed, mark task as `failed` with dependency reason |
| `SESSION_TIMEOUT` | Use Context Window Recovery Protocol | New session assesses partial progress via Recovery Protocol — may result in completion or failure depending on validation |

**JSON corruption**: If the state file (`board.json`; legacy `harness-tasks.json`) cannot be parsed, check for its `.bak` sibling (written before each modification). If backup exists and is valid, restore from it. If no valid backup, log `ERROR [ENV_SETUP] state file corrupted and unrecoverable` and STOP — task metadata (validation commands, dependencies, cleanup) cannot be reconstructed from logs alone.

**Backup protocol**: Before every write to the state file, copy the current file to its `.bak` sibling. Write updates atomically: write JSON to a `.tmp` sibling then `mv` it into place (readers should never see a partial file).

## Environment Initialization

If `harness-init.sh` exists in the project root, run it at every session start. The script must be idempotent.

Example `harness-init.sh`:
```bash
#!/bin/bash
set -e
npm install 2>/dev/null || pip install -r requirements.txt 2>/dev/null || true
curl -sf http://localhost:5432 >/dev/null 2>&1 || echo "WARN: DB not reachable"
npm test -- --bail --silent 2>/dev/null || echo "WARN: Smoke test failed"
echo "Environment health check complete"
```

## Standardized Log Format

All log entries use grep-friendly format on a single line:

```
[ISO-timestamp] [SESSION-N] <TYPE> [task-id]? [category]? message
```

`[task-id]` and `[category]` are included when applicable (task-scoped entries). Session-level entries (`INIT`, `LOCK`, `STATS`) omit them.

Types: `INIT`, `Starting`, `Completed`, `ERROR`, `CHECKPOINT`, `ROLLBACK`, `RECOVERY`, `STATS`, `LOCK`, `WARN`

Error categories: `ENV_SETUP`, `CONFIG`, `TASK_EXEC`, `TEST_FAIL`, `TIMEOUT`, `DEPENDENCY`, `SESSION_TIMEOUT`

Filtering:
```bash
grep "ERROR" harness-progress.txt                    # All errors
grep "ERROR" harness-progress.txt | grep "TASK_EXEC" # Execution errors only
grep "SESSION-3" harness-progress.txt                # All session 3 activity
grep "STATS" harness-progress.txt                    # All session summaries
grep "CHECKPOINT" harness-progress.txt               # All checkpoints
grep "RECOVERY" harness-progress.txt                 # All recovery actions
```

## Session Statistics

At session end, update the state file: set `last_session` to current timestamp. (Do NOT increment `session_count` here — it is incremented at Session Start.) Then append:

```
[timestamp] [SESSION-N] STATS tasks_total=10 completed=7 failed=1 pending=2 blocked=0 attempts_total=12 checkpoints=23
```

`blocked` is computed at stats time: count of pending tasks whose `depends_on` includes a permanently failed task. It is not a stored status value.

## Init Command (`/harness init`)

1. Create `.hq/` and seed it from `templates/orchestration/`, splitting the seed
   across the layers (store-spec.md §9.3):
   - `.hq/.anchor` — one line, `id: <machine-unique-slug>`
   - `.hq/runtime/board.json` — `status: "active"`, empty `tasks`/`workers`, `cost.actual_tokens: null`
   - `.hq/community/HUB.md` — the prose half: goal, the requester's words verbatim, decision table
   - `.hq/community/rules/` — the payload vendor workers load on every task
2. Create the empty working directories under `.hq/community/`: `posts/`, `sessions/`, `agents/`
3. Create `harness-progress.txt` with an initialization entry
4. Install the vendor loaders for whichever CLIs this project uses, from
   `templates/vendor/` — see `skills/omo/references/shared-context.md`
5. Optionally create `harness-init.sh` template (chmod +x)
6. Add the two store lines to `.gitignore` if they are missing: `**/.hq/work/` and
   `**/.hq/runtime/`. That covers the board and `harness-progress.txt` in one rule —
   the posts and `HUB.md` stay tracked under `community/`, because they are the record.

**No `knowledge/` directory.** It used to be seeded here as
`knowledge/libraries/_TEMPLATE.md`. That store is retired: verified facts now land as
posts, and its staleness discipline survives as the `verified:` field plus a supersede
chain (`references/store-spec.md` §4). Seeding an empty second record store is what let
one fact have two homes.

**Step 6 is the pre-unification form of the layer split.** Under `store-spec.md` §3 the
same question is answered structurally rather than asked — `community/` and `config/` are
tracked, `work/` and `runtime/` are ignored, by two `**/.hq/` lines. Once this project
migrates, drop the question rather than asking it about both layouts.

## Status Command (`/harness status`)

Read the state file and `harness-progress.txt`, then display:

1. Task summary: count by status (completed, failed, pending, blocked). `blocked` = pending tasks whose `depends_on` includes a permanently failed task (computed, not a stored status).
2. Per-task one-liner: `[status] task-id: title (attempts/max_attempts)`
3. Last 5 lines from `harness-progress.txt`
4. Session count and last session timestamp

Does NOT acquire the lock (read-only operation).

## Add Command (`/harness add`)

Append a new task to the state file with auto-incremented id (`task-NNN`), status `pending`, default `max_attempts: 3`, empty `depends_on`, and no validation command (required before the task can be completed). Prompt user for optional fields: `priority`, `depends_on`, `validation.command`, `timeout_seconds`. Requires lock acquisition (modifies JSON).

## Tool Dependencies

Requires: Bash, file read/write, git. All harness operations must be executed from the project root directory.
Does NOT require: specific MCP servers, programming languages, or test frameworks.

Concurrent mode requires isolated working directories (`git worktree` or separate clones). Do not run concurrent workers in the same working tree.

# Orca Boundary

Orca and this harness overlap enough that merging them looks obvious and is wrong.
The decision (2026-08-26) is **layer separation**, and the line is drawn by *who has
to read the state*, not by what the state describes.

| Layer | Owns | Read by |
|:---|:---|:---|
| `board.json` | the activation gate, the cost ledger, role → vendor → model, `writes_repo`, `started_at_commit`, `validation.command` | Claude Code hooks — in-process, no network, three operating systems |
| Orca | process liveness, capability fencing, terminal resource accounting, cross-machine transport | the coordinator session, through the CLI |

The seam is one field: `orca_dispatch_id`, an opaque pointer, one-directional.
**`null` is a normal value.** Nothing else crosses.

## Why the board cannot just be Orca state

Three reasons, each fatal on its own.

1. **Hooks would need a live Orca runtime.** Every `orca orchestration` verb is an
   RPC into a running daemon. A hook that has to reach it to evaluate the gate
   hard-fails on any machine without Orca — and this ships to macOS, Ubuntu, and
   Windows.
2. **The state lives outside git.** `~/Library/Application Support/orca/orchestration.db`
   is machine-local. A board that lives there cannot be reviewed, committed, or
   handed to another machine with the repo.
3. **Federated workers physically cannot read the DAG.** `task-list` returns
   `run_required` on a worker machine. A worker that cannot read its own task list
   cannot be governed by it.

Field-by-field, the overlap is only `tasks[]` and worker placement. The four things
the board exists for — **the activation gate, cost, the validation command, and repo
write rights** — have no Orca counterpart at all. A full schema grep found zero
columns for `token`, `cost`, or `usage`.

## Why Orca cannot just be dropped either

Two capabilities do not survive reimplementation as JSON:

1. **`worker-abandon` is a capability-token fence,** not a kill. It separates
   revoking authority (`launch_token_hash`, `capability_hash`,
   `process_incarnation`) from ending the process. The best a JSON file can do is an
   advisory lock. Liveness there is also three-valued, not two —
   `start_unknown`, `stop_unknown`, and `abandoned` are first-class.
2. **`worker-list` can express "task complete, terminal still alive".** A single
   `workers[].status` cannot represent both facts at once.

Both are scoped to the home DB, so **neither applies to a federated worker**. Know
which side of that line you are on before relying on either.

## Do not mirror Orca state into the board

`workers[].status` uses campaign terms — `planned`, `claimed`, `reported`, `closed` —
precisely so it is not a process fact. Copying Orca's nine-value worker state here
would put two sources of truth on one fact, and the board would be the stale one:
Orca updates on process events the board never sees.

The harness has to run with Orca absent. Design every hook that way.

## Transport boundary

| Pair | Use | Why not the other |
|:---|:---|:---|
| Coordinator ↔ its own subagent | Agent tool + SendMessage | — |
| Session ↔ session, same machine | **SendMessage** | Routing through Orca adds an RPC, a DB write, and an ack for a message that already arrives |
| **Different machine** | **`orca` only** | Nothing else crosses the boundary |
| Different account | neither — a shared filesystem | Untested |

## `coordinator-start`, `coordinator-stop`, `run`, `run-stop` are dead

They have no effect. **Assume there is no automatic coordinator loop.** A design that
waits for one waits forever.

## A handoff's canonical form is a file, not a message

In the 2026-08-26 incident the message did arrive — the sender simply could not
confirm it, and what actually revived the worker was a file in the vault.

`.hq/community/posts/handoff/` is the record. Orca may carry the notification; the
file is what survives a lost ack, a dead daemon, and a machine that was asleep.

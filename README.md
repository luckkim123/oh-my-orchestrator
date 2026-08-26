# oh-my-orchestrator

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Claude Code](https://img.shields.io/badge/Claude-Code-blue)](https://claude.ai/code)

> A multi-vendor orchestration harness where **the main Claude Code session is the
> executor** and vendor CLIs are role-scoped advisors.

## What this is for

Running several AI agents on one task is easy. Making them follow rules is not.
Prose conventions ("report before you go idle", "record what it cost") are not
enforced by anything, so they quietly stop being true.

This harness puts the rules where they can actually fire:

- **One board.** `.orchestration/board.json` is the only state hooks read, and
  its `status` field is the gate — when a campaign is closed, every hook exits 0
  immediately. `HUB.md` beside it is the prose humans read.
- **One enforcement layer.** A `SubagentStop` hook rejects a worker that never
  filed its role notes or never reported. Rejection is `exit 2` — measured as the
  only code Claude Code treats as blocking.
- **Completion you can run.** A task finishes when its `validation.command`
  passes, not when someone says it did; a failure rolls back to
  `started_at_commit`.

## How delegation is decided

Upstream `omo` forbids the orchestrator from writing code. This fork inverts
that: **Claude writes the code, and delegation needs a reason.**

| Reason to delegate | Why |
|---|---|
| The same approach failed twice | Escape a 3-strike loop with a different model, not a different prompt |
| A read would blow the context budget | Bulk sweeps belong in a subordinate context |
| The verdict turns on perspective diversity | Adversarial review needs an independent reader |

Vendor workers **gather, investigate, and rebut**. Judgment, generation, and
file writes stay with the calling lane — citation generation, document integrity
gates, and experiment SSOTs are never delegated.

## Status

Early. Phase 0 (hook-surface measurement) is done and it changed the design:
`SubagentStart` cannot block a spawn, and `TeammateIdle` never fires for
Agent-tool subagents, so enforcement lives entirely on `SubagentStop`. Phases 1–5
are in progress.

## Modules

| Module | What it does |
|---|---|
| `skills/omo` | Role-scoped vendor orchestration and the delegation gate |
| `skills/harness` | The enforcement layer: blocking checks, safety valve, claim locks |

Other upstream modules (`bmad`, `requirements`, `sparv`, `do`, `course`,
`dev-kit`, `claudekit`) ship disabled in `config.json`. Their directories are
kept so `git fetch upstream` keeps working — they are not deleted.

## Install

```bash
python3 install.py
```

Edit `config.json` to change which modules are enabled. Only `omo` and `harness`
are on by default.

## Backend CLIs

| Backend | Invocation | Notes |
|---|---|---|
| Codex | `codex exec --sandbox read-only "<prompt>" < /dev/null` | `--full-auto` does not exist. Close stdin or it waits 3s |
| Antigravity | `agy --print-timeout 45s --print='<prompt>' < /dev/null` | Binary is `agy`, not `antigravity`. Attach the prompt to `--print=` or the next flag is eaten as the prompt |
| Claude | `--output-format stream-json`, `-r` | |
| Gemini | `-o stream-json`, `-y`, `-r` | |

An invalid `--model` is not rejected by the CLI — it fails as an API 400. Catch it.

## Credits and license

Forked from [stellarlinkco/myclaude](https://github.com/stellarlinkco/myclaude)
(AGPL-3.0) at `f2e75c1`, which supplies the enforcement layer, the role axis, and
the vendor assignment table.

Design ideas adapted — not code — from
[gaebalai/claude-code-orchestrator](https://github.com/gaebalai/claude-code-orchestrator)
(MIT): the delegation flowchart ("two failures → a different vendor"), the
`NOT Your Job` vendor boundary, the vendor CLI failure-mode tables, reasoning
effort tiering, and cross-vendor decision records.

The campaign protocol (post categories, role memory, "reporting is termination",
estimated-vs-actual cost) comes from a `team-project` skill that this harness
absorbs.

**AGPL-3.0** — see [LICENSE](LICENSE). Because this repository is AGPL, its code
must not be copied into MIT-licensed repositories; calling and referencing are
fine.

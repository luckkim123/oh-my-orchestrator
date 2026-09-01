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

- **One board.** `.hq/runtime/board.json` is the only state hooks read, and
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

Working. Phases 0–5 are complete (see `CHANGELOG.md`). Phase 0's hook-surface
measurement still shapes the design: `SubagentStart` cannot block a spawn, and
`TeammateIdle` never fires for Agent-tool subagents, so enforcement lives
entirely on `SubagentStop`. The store cutover to `.hq/` (anchor-gated), the
delegation-gate redesign (0.15.0), and the call ledger (0.19.0) are all live.

## Modules

| Module | What it does |
|---|---|
| `skills/orchestrator` | Explicit entry point for a multi-vendor campaign. Composes the two below |
| `skills/omo` | Role-scoped vendor orchestration and the delegation gate |
| `skills/harness` | The enforcement layer: blocking checks, safety valve, claim locks |
| `skills/community` | The board: reading, writing, commenting on, and correcting posts through `hq` |
| `templates/orchestration/` | Seeds a project's `.hq/` shared knowledge store |
| `templates/vendor/` | Vendor-side loader configs, so a worker reads the store on every task |

The upstream npx installer (`package.json`, `bin/cli.js`, `install.py`,
`config.json`, the root `hooks/`) was removed in 0.21.0 — the plugin system
and `make install` above are the only install paths. `git fetch upstream`
will conflict on those files; resolve by keeping the deletion.

## Install

Three parts ship separately; all three are needed for the full harness.

**1. The plugin** (skills + hooks) — install through Claude Code's plugin
system (`/plugin` in the CLI), from a marketplace that carries
`oh-my-orchestrator` or from this repository. After each release,
`claude plugin update oh-my-orchestrator` — the manifest version in
`.claude-plugin/plugin.json` is the only delivery surface; skills and hooks
do not update without the bump.

**2. The wrapper** — built from source, no binary is downloaded:

```bash
bash install.sh        # build + install to $GOBIN + symlink into ~/.local/bin, then census
```

That is one command because it was three prose steps until 0.22.0 and the
drift they existed to prevent recurred three times — most recently
2026-09-01, when v0.20.0 answered on `PATH` against a 0.21.6 plugin cache.
`$GOBIN` is frequently not on `PATH`, and the symlink (not a copy) keeps
every future `make install` live with no second step; without it a stale
hand-copied build shadows the fresh one while every existence check passes
(the 0.19.1 incident). The manual form still works:

```bash
cd codeagent-wrapper && make build && make install
ln -sf "$(go env GOPATH)/bin/codeagent-wrapper" ~/.local/bin/codeagent-wrapper
codeagent-wrapper --version   # must match .claude-plugin/plugin.json
```

**3. The role table** — the wrapper resolves `--agent <role>` from
`~/.codeagent/models.json` and fails loud with a template hint when it is
missing. Seed it from the repo template:

```bash
python3 scripts/seed_models.py   # copies templates/models.json.example when absent,
                                 # adds only the missing roles when present
```

Existing entries are never overwritten, so edit `models.json` freely and
re-run after upgrades to pick up new roles.

**4. Per project — the community store.** `python3 bin/omo-init` seeds
`.hq/community/` from `templates/orchestration/` and installs the
`context-loader` skill for every vendor CLI actually on PATH. It is separate
from the three above because it writes into *your* project, not the machine.
Skipping it is a supported state and the census will keep saying
`store:UNSEEDED` until you do — which is the point: on 2026-09-01 a workspace
was found where no omo session had ever seeded it, because the only
instruction to do so lived in a reference file nobody reached.

## Backend CLIs

| Backend | Invocation | Notes |
|---|---|---|
| Codex | `codex exec --sandbox read-only "<prompt>" < /dev/null` | `--full-auto` does not exist. Close stdin or it waits 3s |
| Antigravity | `agy --print-timeout 45s --print='<prompt>' < /dev/null` | Binary is `agy`, not `antigravity`. Attach the prompt to `--print=` or the next flag is eaten as the prompt |
| Claude | `--output-format stream-json`, `-r` | |

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

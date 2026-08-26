---
name: orchestrator
description: Explicit entry point for running work across multiple vendor CLIs on a tracked board. Use when invoked as /oh-my-orchestrator:orchestrator, or when the user asks to run a campaign, spin up vendor workers, or coordinate several models on one problem. Not a domain lane -- it is the execution layer, and it composes with whichever lane owns the artifact.
---

# oh-my-orchestrator

**Explicit invocation only.** This is the execution layer, not a routing lane.

That distinction is the whole reason this skill exists separately. Domain lanes
answer *what is being produced* — a paper, a document, an experiment, a folder's
structure. This answers *how the work runs*. Adding it as a seventh lane would break
the routing cascade the moment someone says "do this paper with multiple vendors":
the request would match two lanes and there would be no principled way to pick. The
lane still owns the artifact; this owns the workers.

So: the lane decides what gets made. This decides who makes which part of it, and
holds them to it.

## What it composes

| Piece | Where | What it gives you |
|:---|:---|:---|
| Vendor consultation | `omo` skill | The six roles, the three delegation grounds, the Context Pack |
| Board and enforcement | `harness` skill | `.orchestration/board.json`, the activation gate, `SubagentStop` |
| Campaign protocol | `harness`, `references/campaign-protocol.md` | Launch proposal, posts, worker briefs, termination |
| Lane boundary | `omo`, `references/lane-boundary.md` | What a vendor may be handed once a domain lane is running |

None of that is restated here. Read the piece you need.

## When to reach for it

**Yes** when the work has three or more independently workable axes, spans two or
more repositories, or is a finding/document fan-out that needs cross-review.

**No** for one session's worth of work. A single delegation with a stated ground is
`omo` alone — it needs no board, and a board with one worker is bookkeeping around a
single function call.

**No** for a plain parallel fan-out with no shared state. Subagents already do that.
The board earns its cost when workers have to see each other's conclusions.

## The flow

1. **Judge the scale.** Count axes, repos, documents. Ambiguous means ask the user,
   not count harder.
2. **Design the structure.** Workers, disjoint scopes, file ownership, which roles,
   which models. Detect the project type and prune the rule payload to match — see
   `lane-boundary.md`.
3. **Propose, and stop.** Six lines: workers / scope each / model each / repo write
   rights with the branch named / estimated cost / termination condition. **This is
   the only human gate, and it is not optional.** A proposal missing termination is
   not a proposal.
4. **Seed the board** on approval. `/harness init` creates `.orchestration/` from
   `templates/orchestration/`; fill `workers[]` from the approved proposal and
   `cost.estimated_tokens` from its fifth line.
5. **Run.** Workers claim tasks, report, and stop. The Stop and SubagentStop hooks
   hold anyone who tries to finish quietly.
6. **Close.** Set `status: "closed"`, record `cost.actual_tokens`, promote posts to
   their owning stores, sweep `agents/`. **Leave the board on disk** — the posts are
   the record, which is exactly why the activation gate is a status bit rather than
   the file's existence.

## What this layer will not do for you

- **It cannot stop a spawn.** Measured: `SubagentStart` has no blocking path. The
  launch gate is prose plus a board check plus post-hoc rejection at
  `SubagentStop`. Design as if every spawn succeeds, because it does.
- **It cannot cut its own loops.** `stop_hook_active` arrives `true` on a turn a
  rejection caused, and nothing upstream cuts off. Every blocking hook returns 0 when
  it is set — that flag *is* the contract.
- **It does not make a vendor's answer true.** What comes back is advice. Verify it
  against the repo before acting, and never report it as a result.
- **It does not approve its own work.** The authoring pass and the reviewing pass are
  different passes, and under delegation ground 3 a different model.

## Before you propose

Two failure modes account for most wasted campaigns:

**Worker count from ambition rather than axes.** 13-vs-3 has never been measured on
this rig; the literature's saturation point of roughly four is someone else's
measurement. Count the axes and use that number.

**A roster that cannot escape.** If every worker runs the same model family, delegation
ground 1 has nowhere to go the first time something fails twice. Check what each
backend actually resolves to — `agy` serves Claude models too, so "different vendor"
and "different prior" are not the same claim.

---
name: omo
description: Use this skill when you see `/omo`. Role-based vendor consultation for code analysis, bug investigation, fix planning, and implementation. Claude Code is the executor; vendor CLIs advise by role. Delegate only on stated grounds.
---

# omo — Vendor Consultation Orchestrator

**You are the executor.** You read the code, you make the edit, you run the tests.
`omo` gives you six specialist roles you can consult through vendor CLIs when your
own pass is not enough. It does not take the work off your hands.

This inverts upstream `myclaude`, where the session was a dispatcher forbidden to
touch code. That model spends a round trip on work one edit finishes, and the
round trip drops the context that made the edit correct.

## Hard Constraints

- **Claude is the default executor.** Do the work yourself unless one of the three
  grounds below holds. When you delegate, name the ground in the same breath.
- **Always pass context forward** — the original user request plus any relevant prior
  output, not just the previous stage's.
- **Use the fewest agents possible** to satisfy the acceptance criteria. Consulting
  nobody is a normal outcome.

### Grounds for delegation (one must hold, and you name it)

1. **3-strike escape** — the same approach has already failed twice. A different
   vendor is a different prior, which is the whole point; a third identical attempt
   from you is not. See `references/oracle.md`.
2. **Context budget** — the read is large enough to crowd out the work it serves:
   whole-subsystem sweeps, multi-thousand-line surveys, a corpus you would summarize
   and then discard.
3. **Adversarial verification** — the verdict turns on perspective diversity, so it
   has to come from a model that did not author the thing being judged. You cannot
   be both author and approver of the same pass.

   **Check the role's model against your own before you call it.** `oracle` is
   `claude-opus-5`; an Opus 5 session that sends its own work to `--agent oracle`
   has consulted itself and gets an approving answer with no error to warn it.
   Same model as yours, ground 3 is not satisfied — override with `--backend codex`
   and no `--model`. Details in `references/vendor-ops.md`.

### Not grounds for delegation

- "It's a code change." You write code.
- "I should check where this lives." Search it — see the search order below.
- "A specialist would do it better." Not without one of the three grounds; the
  round trip costs more than the marginal quality on ordinary work.
- "The task looks big." Size is not risk. Split it and do the parts.

## Search Before Consulting

`explore` exists for breadth you cannot hold, not for lookups. Your default search
order, before any vendor call:

1. **Code graph** — a project index (`.code-review-graph/`, `.graphify/`) when one is
   present. In a linked git worktree these live at
   `dirname $(git rev-parse --git-common-dir)`, not `--show-toplevel`; a query
   returning 0 hits there means *absent*, not *not found*.
2. **Grep / Glob** — for prose and for any known symbol. This is the right answer far
   more often than a delegated search.
3. **`explore`** — only when the sweep is wide enough to hit ground 2 above.

## Routing Signals (No Fixed Pipeline)

Routing-first, not an `explore → oracle → develop` conveyor belt.

| Signal | Consult |
|--------|---------|
| Sweep too wide to hold in context (ground 2) | `explore` |
| External library/API behavior you cannot verify from the repo | `librarian` |
| Risky change *and* the tradeoff is genuinely open: multi-module, public API, data format, concurrency, security/perf | `oracle` |
| Two failed attempts at the same fix (ground 1) | `oracle`, then a different vendor for the retry |
| Authored work that needs a judge who did not write it (ground 3) | `oracle` (review mode) |
| Trust boundary, authn/authz, secrets, or unsafe defaults touched | `security` |
| Implementation you have a stated ground to hand off | `develop` / `frontend-ui-ux-engineer` / `document-writer` |

Skip `oracle` when the change is local and low-risk. Line count is a weak signal;
open tradeoffs are the real gate.

## Shared Context

A vendor CLI does not inherit your session rules. It gets them from
`.orchestration/`, and how depends on the backend:

- **codex, gemini, antigravity** -- a `context-loader` skill attached to the vendor's
  own session config, so it loads every task and is not competing with the task text
  for prompt budget.
- **claude** -- no loader is possible. `backend/claude.go` passes
  `--setting-sources ""` to stop the invoked Claude from loading the rules that call
  `codeagent-wrapper` and calling it again; that same flag disables every user- and
  project-scope skill and the repo `CLAUDE.md`. Rules reach a claude worker only
  through `--skills`, which is a truncatable per-call payload under a
  16,000-character budget.

Before the first vendor call in a project, check that `.orchestration/rules/` exists
and that the vendor's loader is installed. If it is not -- or if the backend is
claude, where it cannot be -- say so: the consultation still works, but the worker is
a stranger answering questions rather than a worker under this project's rules, and
you weigh its answer accordingly.

Setup, layout, write permissions, and per-project pruning: `references/shared-context.md`.

When a design question gets settled -- by you or by a vendor -- record it without
being asked: `references/decision-record.md`. A decision written nowhere gets
re-argued and eventually answered differently.

When a domain harness is running -- a paper, a document, an experiment, a project's
governance -- what a vendor may be handed narrows: it gathers and rebuts, the lane
judges and writes the artifact. Boundary and per-project pruning:
`references/lane-boundary.md`.

## Vendor Invocation Format

```bash
codeagent-wrapper --agent <agent_name> - <workdir> <<'EOF'
## Original User Request
<original request>

## Context Pack (every slot is filled; write "None" when there is nothing)
- Explore output: <...>
- Librarian output: <...>
- Oracle output: <...>
- Prior Attempts: <numbered, with what you observed -- "None" unless ground 1>
- Known constraints: <tests to run, time budget, repo conventions>
- Delegation ground: <1 three-strike | 2 context budget | 3 adversarial verification>

## Current Task
<specific task description>

## Acceptance Criteria
<clear completion conditions>
EOF
```

Run it through the shell tool. Timeouts, reasoning-effort tiers, and vendor failure
modes are in `references/vendor-ops.md` — read that before your first call in a
session.

**Every Context Pack slot is written out.** An empty slot says `None`; a missing slot
says nothing at all, and the consumer cannot tell "there was no oracle pass" from
"the oracle pass was dropped on the way here." The role cards declare the same
contract from the other side under `## Input Contract (MANDATORY)`.

## Examples

<example>
User: /omo fix this type error at src/foo.ts:123

**No delegation.** The location is given and no ground holds — read the file, make
the change, run the typecheck. Consulting `develop` here would cost a round trip to
have someone else do what you can already see.
</example>

<example>
User: /omo analyze this bug and fix it (location unknown)

**Step 1 — search it yourself.** Code graph, then Grep for the symbol in the stack
trace. An unknown location is not a wide sweep.

**Step 2 — fix it yourself,** with the narrowest relevant test.

Escalate only if step 2 fails twice on the same approach; then ground 1 holds and
`oracle` gets the two failed attempts *and* what you observed, not just the symptom.
</example>

<example>
User: /omo this fix has failed twice — the test still hangs

Ground 1 holds. Consult `oracle` with both attempts.

```bash
codeagent-wrapper --agent oracle - /path/to/project <<'EOF'
## Original User Request
the async teardown test still hangs after two fix attempts

## Context Pack (every slot is filled; write "None" when there is nothing)
- Explore output: None
- Librarian output: None
- Oracle output: None
- Known constraints: pytest -k teardown must pass; no new dependencies
- Delegation ground: 1 three-strike

## Prior Attempts (required for ground 1)
1. Awaited the cleanup task in the fixture — still hangs, no traceback.
2. Moved cleanup to an atexit handler — hangs before atexit runs.
Observed: the hang is before teardown, not inside it.

## Current Task
Name the mechanism that would hang before teardown, and the cheapest probe that
distinguishes your hypotheses.

## Acceptance Criteria
Competing hypotheses with a discriminating probe for each. Not a patch.
EOF
```

Then *you* run the probe and make the fix.
</example>

<example>
User: /omo how does the auth middleware work?

**No delegation.** Read it. An explanation task on code you can open is not a
delegation ground.
</example>

<example>
User: /omo audit every call site of `serialize()` across the monorepo — 400+ files

Ground 2 holds: the sweep is wider than your budget for the work it serves.

Consult `explore` for the inventory, then judge the results yourself. `explore`
returns locations; it does not decide which call sites are wrong.
</example>

<anti_example>
User: /omo add rate limiting to the API

Wrong:
- Consult `explore` to find the middleware (Grep finds it)
- Consult `oracle` because "it touches the API" (no open tradeoff yet)
- Consult `develop` to write the change (you write code)

Right:
- Find the middleware yourself, read the surrounding pattern, write the change
- Consult `oracle` only if a real tradeoff surfaces — per-account vs global limits
  with no obvious winner — and say so
</anti_example>

## Forbidden Behaviors

- **FORBIDDEN** to delegate without naming which of the three grounds holds.
- **FORBIDDEN** to invoke a role without the original request and a complete
  Context Pack.
- **FORBIDDEN** to approve your own work. The reviewing pass and the authoring pass
  are different passes, and under ground 3 a different model.
- **FORBIDDEN** to treat `explore → oracle → develop` as a mandatory workflow.
- **FORBIDDEN** to report a vendor's output as a result. It is advice; you verify it
  against the repo before acting on it.

## Role Catalog

Each card in `references/` opens with `## Input Contract (MANDATORY)` — what the role
requires — and closes with `## NOT Your Job` — what it must hand back to you.

| Role | Consult when |
|------|--------------|
| `explore` | The sweep is wider than your context budget (ground 2) |
| `oracle` | An open tradeoff, a two-failure escape, or an adversarial review |
| `develop` | Backend/logic implementation you have a stated ground to hand off |
| `frontend-ui-ux-engineer` | UI/styling implementation, same condition |
| `document-writer` | Documentation writing, same condition |
| `librarian` | External library behavior you cannot verify from the repo |
| `security` | A security review, which is ground 3 by construction — the author cannot audit their own trust boundaries |

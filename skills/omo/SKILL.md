---
name: omo
description: Use this skill when you see `/omo`. Role-based vendor delegation for code analysis, bug investigation, fix planning, and implementation. Claude decides and judges; vendor CLIs carry the volume — bulk reading and mechanical execution against a settled plan. Delegate on stated grounds, and verify what comes back.
---

# omo — Vendor Consultation Orchestrator

**You decide and you judge. The volume goes out.** Deciding what to build, whether an
answer is right, and whether the evidence holds is what a Claude session is worth
paying for. Sweeping a subsystem to find three files, and typing out a change whose
design is already settled, are not — they are the same judgment repeated over a lot
of tokens, and that is what the vendor roles are for.

This splits roles by strength, the way `cco` does, but along the axis this operator
built omo for: **cost.** cco puts deep reasoning on codex and bulk reading on Gemini,
keeping Claude as orchestrator. Here the reasoning stays with Claude and the two
high-volume halves — reading wide and writing out a decided plan — go to the vendors.

It is not the upstream `myclaude` dispatcher either. That model forbade the session to
touch code at all, so a one-line fix cost a round trip and lost the context that made
it correct. The line here is not "who types" but **whether the decision is already
made**: undecided work stays, decided work goes.

## Hard Constraints

- **Claude owns the decision and the verdict.** What to build, whether it is right,
  whether the evidence supports the claim — never delegated, never rubber-stamped.
- **Delegate the volume, on a named ground.** When you delegate, name the ground in
  the same breath.
- **What comes back is a draft, not a result.** You read it against the repo before it
  counts. A vendor that executed a wrong plan does so confidently.
- **Always pass context forward** — the original user request plus any relevant prior
  output, not just the previous stage's.
- **Use the fewest agents possible** to satisfy the acceptance criteria. Consulting
  nobody is still a normal outcome for small, decided work — the round trip has a floor
  and a two-line edit does not clear it.

### Grounds for delegation (one must hold, and you name it)

1. **Settled plan, mechanical execution** — the design is decided and written down, and
   what is left is typing it out and making the tests pass. The agent's discretion is
   mechanical, so a cheaper model spends its tokens where they are worth least. Hand it
   the plan verbatim, not a summary of the plan. → `develop`
   **The plan has to actually exist.** "I know what I want" is not a settled plan; a
   spec, a numbered task list, or a design doc is. If you cannot paste it, it is not
   settled — decide first.
2. **Volume** — the read (or the write) is larger than the decision it serves:
   whole-subsystem sweeps, multi-thousand-line surveys, a corpus you would summarize
   and then discard. → `explore`, which is where a 1M-context backend earns its place.
3. **3-strike escape** — the same approach has already failed twice. A different
   vendor is a different prior, which is the whole point; a third identical attempt
   from you is not. See `references/oracle.md`.
4. **Adversarial verification** — the verdict turns on perspective diversity, so it
   has to come from a model that did not author the thing being judged. You cannot
   be both author and approver of the same pass.

   **Check the role's model against your own before you call it.** `oracle` is
   `claude-opus-5`; an Opus 5 session that sends its own work to `--agent oracle`
   has consulted itself and gets an approving answer with no error to warn it.
   Same model as yours, ground 4 is not satisfied — override with `--backend codex`
   and no `--model`. The wrapper now refuses a cross-vendor override that lands back
   on your own family, but it cannot catch a role that was already bound there.
   Details in `references/vendor-ops.md`.

   **One family is the default; two families in parallel is a gate.** Open it when
   the change is about to ship in a release, when it touches a path where data can
   be lost, or when it is hard to undo — otherwise one verifier is enough. Open
   means sending the *same* prompt against the *same* commit to two different vendor
   families at once. Measured 2026-08-30 on commit `b781d4a`: codex and agy run that
   way returned 11 reproducible defects with almost no overlap — agy found parser and
   boundary faults, codex found contract and side-effect faults. The cost is not two
   verifications of one axis, it is one verification of two axes.

   That is a sample of one, and the two axes were named afterward rather than
   assigned in advance, so it is a reason to run the gate — not a measured profile of
   either vendor. **Do not widen the conditions.** "It ships, but it is a small
   change" is not a narrower reading of the gate; it is the gate inverted.

### Not grounds for delegation

- **"The design isn't settled yet."** Then it is not ground 1. A vendor handed an
  undecided problem returns a confident answer to a question nobody asked, and you pay
  twice — once for the work and once for reading it to find that out.
- "It's one edit." The round trip has a floor. A two-line fix you can already see is
  cheaper to make than to describe.
- "I should check where this lives." Search it — see the search order below. A single
  lookup is not volume.
- "A specialist would do it better." Not by itself; quality without one of the four
  grounds is the argument that spends the most for the least.

### What this does not buy

Delegating execution does not delete the tokens, it moves the expensive half. You still
read what comes back — that is the constraint that keeps ground 1 honest and it is not
free. The saving is real when the vendor writes 400 lines you review; it is negative
when it writes 4.

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
| A written plan whose execution is mechanical (ground 1) | `develop` |
| Sweep too wide to hold in context (ground 2) | `explore` |
| External library/API behavior you cannot verify from the repo | `librarian` |
| Risky change *and* the tradeoff is genuinely open: multi-module, public API, data format, concurrency, security/perf | `oracle` |
| Two failed attempts at the same fix (ground 3) | `oracle`, then a different vendor for the retry |
| Authored work that needs a judge who did not write it (ground 4) | `oracle` (review mode) |
| Trust boundary, authn/authz, secrets, or unsafe defaults touched | `security` |
| Implementation whose design is settled (ground 1) | `develop` / `frontend-ui-ux-engineer` / `document-writer` |

Skip `oracle` when the change is local and low-risk. Line count is a weak signal;
open tradeoffs are the real gate.

## Shared Context

A vendor CLI does not inherit your session rules. It gets them from the community
store (`.hq/community/`, or the legacy `.orchestration/`), and how depends on the
backend:

- **codex, gemini, antigravity** -- a `context-loader` skill attached to the vendor's
  own session config, so it loads every task and is not competing with the task text
  for prompt budget.
- **claude** -- no loader is possible. `backend/claude.go` passes
  `--setting-sources ""` to stop the invoked Claude from loading the rules that call
  `codeagent-wrapper` and calling it again; that same flag disables every user- and
  project-scope skill and the repo `CLAUDE.md`. Rules reach a claude worker only
  through `--skills`, which is a truncatable per-call payload under a
  16,000-character budget.

Before the first vendor call in a project, check that the store's `rules/` exists
and that the vendor's loader is installed. If it is not -- or if the backend is
claude, where it cannot be -- say so: the consultation still works, but the worker is
a stranger answering questions rather than a worker under this project's rules, and
you weigh its answer accordingly.

Setup, write permissions, and per-project pruning: `references/shared-context.md`.
**Where the store physically lives — the anchor, the four layers, and which of them git
tracks — is owned by `../harness/references/store-spec.md`**, not by this skill. Read it
before creating a store or deciding which layer a record belongs in; `shared-context.md`
covers only the payload that sits inside it.

When a design question gets settled -- by you or by a vendor -- record it without
being asked: `references/decision-record.md`. A decision written nowhere gets
re-argued and eventually answered differently.

When a domain harness is running -- a paper, a document, an experiment, a project's
governance -- what a vendor may be handed narrows: it gathers and rebuts, the lane
judges and writes the artifact. Boundary and per-project pruning:
`references/lane-boundary.md`.

## Before the First Vendor Call

**A claude-only machine is a supported configuration, not a broken one.** The role
table binds `security`, `develop`, and `explore` to codex by default, but nothing
requires codex or antigravity to be installed -- omo's whole premise is that the
session does the work and consulting nobody is a normal outcome. Someone who runs
Claude and nothing else still gets every rung of the ladder; they just have four
roles instead of seven.

So before the first vendor call in a session:

1. **Check the entry point itself** -- `command -v codeagent-wrapper`. It is the
   binary every consultation goes through, it ships as Go source rather than a
   published artifact, and a machine that never ran `make build` has no vendor lane
   at all. Checking only the backends passes a machine whose backends are perfect
   and whose entry point does not exist.

   **Existing is not current, and `command -v` cannot tell you which.**
   `make install` writes to `$GOBIN` (default `~/go/bin`), a directory frequently
   absent from `PATH`, so the binary answering to the name can be an older build
   that every existence check reports as perfectly present. Compare
   `codeagent-wrapper --version` against the version at the top of this repo's
   `CHANGELOG.md`; when they differ the wrapper is running code from before
   whatever fix you are relying on. Measured twice here, and the second time the
   call ledger shipped the day before recorded nothing at all through `PATH` while
   the check passed. The durable fix is a symlink from a `PATH` directory to
   `$GOBIN/codeagent-wrapper` rather than a copy, so the next `make install` is
   live with no second step.
2. **Check the role's backend is on PATH** (`command -v codex`, `command -v claude`).
   A missing CLI is not an error to work around silently -- the call will fail with
   an exec error that reads like a bug in the wrapper.
3. **If either is missing, say so and pick again.** Either route to a role whose backend
   is present, or do the work yourself and name that you did.
4. **Never install a vendor CLI on your own.** Installing codex or antigravity is a
   per-machine decision with an account and a cost attached. Ask; if the answer is
   no, that is a complete answer and the claude-backed roles carry the session.

Measure, do not assume: a binary can be on PATH and unauthenticated, and a backend
can resolve to a model the account cannot reach. One cheap call settles both.

## Vendor Invocation Format

```bash
codeagent-wrapper --agent <agent_name> - <workdir> <<'EOF'
## Original User Request
<original request>

## Context Pack (every slot is filled; write "None" when there is nothing)
- Explore output: <...>
- Librarian output: <...>
- Oracle output: <...>
- Prior Attempts: <numbered, with what you observed -- "None" unless ground 3>
- Known constraints: <tests to run, time budget, repo conventions>
- Delegation ground: <1 settled plan | 2 volume | 3 three-strike | 4 adversarial verification>

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

Escalate only if step 2 fails twice on the same approach; then ground 3 holds and
`oracle` gets the two failed attempts *and* what you observed, not just the symptom.
</example>

<example>
User: /omo this fix has failed twice — the test still hangs

Ground 3 holds. Consult `oracle` with both attempts.

```bash
codeagent-wrapper --agent oracle - /path/to/project <<'EOF'
## Original User Request
the async teardown test still hangs after two fix attempts

## Context Pack (every slot is filled; write "None" when there is nothing)
- Explore output: None
- Librarian output: None
- Oracle output: None
- Known constraints: pytest -k teardown must pass; no new dependencies
- Delegation ground: 3 three-strike

## Prior Attempts (required for ground 3)
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

<example>
User: /omo the plan in `.sp/plans/2026-08-29-token-bucket.md` is approved — build it

Ground 1 holds: the design is written down and what is left is mechanical.

```bash
codeagent-wrapper --agent develop - /path/to/project <<'EOF'
## Original User Request
build the approved token-bucket rate limiter

## Context Pack (every slot is filled; write "None" when there is nothing)
- Explore output: None
- Librarian output: None
- Oracle output: None
- Prior Attempts: None
- Known constraints: `pytest tests/test_ratelimit.py` must pass; no new dependencies;
  match the middleware style in src/middleware/auth.py
- Delegation ground: 1 settled plan

## Current Task
Implement the plan below verbatim. Where it is silent, follow the surrounding file's
existing pattern rather than inventing one, and say what you had to decide.

<the plan, pasted in full — not a summary of it>

## Acceptance Criteria
The named test passes, and you list every place the plan was silent.
EOF
```

Then *you* read the diff and run the tests. What came back is a draft; the list of
places the plan was silent is the part to read first, because that is where a
mechanical executor had to make a decision it was not given.
</example>

<anti_example>
User: /omo add rate limiting to the API

Wrong:
- Consult `explore` to find the middleware (Grep finds it — a lookup is not volume)
- Consult `oracle` because "it touches the API" (no open tradeoff yet)
- Consult `develop` to write the change (**the design is not settled** — per-account
  vs global, which store, what happens on overflow. Ground 1 does not hold, and a
  vendor handed this returns a confident answer to a question nobody asked)

Right:
- Decide the shape first: read the surrounding pattern, settle per-account vs global,
  write it down
- *Then* ground 1 is available if the implementation is large enough to be worth the
  round trip — and a two-line middleware hook is not
- Consult `oracle` only if the tradeoff is genuinely open, and say so
</anti_example>

## Forbidden Behaviors

- **FORBIDDEN** to delegate without naming which of the four grounds holds.
- **FORBIDDEN** to invoke a role without the original request and a complete
  Context Pack.
- **FORBIDDEN** to approve your own work. The reviewing pass and the authoring pass
  are different passes, and under ground 4 a different model.
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
| `develop` | Backend/logic implementation against a settled plan (ground 1) |
| `frontend-ui-ux-engineer` | UI/styling implementation, same condition |
| `document-writer` | Documentation writing, same condition |
| `librarian` | External library behavior you cannot verify from the repo |
| `security` | A security review, which is ground 4 by construction — the author cannot audit their own trust boundaries |

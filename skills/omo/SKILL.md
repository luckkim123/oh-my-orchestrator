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
  the same breath — and pass `--ground <1-4>` so the ledger records it.
- **What comes back is a draft, not a result.** You read it against the repo before it
  counts. A vendor that executed a wrong plan does so confidently.
- **Always pass context forward** — the original user request plus any relevant prior
  output, not just the previous stage's.
- **Never idle while a vendor runs.** Launching a call and then waiting on it turns a
  parallel speedup into a serial delay, and it is the most expensive mistake this
  skill enables. Work the same question yourself in parallel, fix the wall-clock cap
  *before* you launch, and act at the cap. Liveness is measured — log mtime and
  process CPU time against a captured PID — never read off a `status=running` line,
  which is emitted on a timer and outlives a dead child.
- **A vendor failure is diagnosed with the tool, not from memory.** Before concluding
  "this backend cannot do this here", run three things that take thirty seconds:
  `command -v <cli>`, `<cli> --version`, and one cheap wrapper call. A stale note
  saying a vendor is unusable on this machine is a hypothesis; the exit code, the
  version banner, and the wrapper's own flag list are the evidence. Three failure
  modes measured on 2026-09-04 — a rejected backend *name*, a prompt shape that made
  the vendor orchestrate instead of work, and a half-written npm install whose native
  binary was present while its manifest was not — all read exactly like "the vendor is
  broken" or "we are out of quota", and none of them was that.
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

- **codex, antigravity** -- a `context-loader` skill attached to the vendor's
  own session config, so it loads every task and is not competing with the task text
  for prompt budget.
- **claude** -- no loader is possible. `backend/claude.go` passes
  `--setting-sources ""` to stop the invoked Claude from loading the rules that call
  `codeagent-wrapper` and calling it again; that same flag disables every user- and
  project-scope skill and the repo `CLAUDE.md`. Rules reach a claude worker only
  through `--skills`, which is a truncatable per-call payload under a
  16,000-character budget.

**The store check is not gated on making a vendor call.** It used to be -- this
paragraph read "before the first vendor call" until 0.22.0 -- and on 2026-09-01 a
session that made zero vendor calls therefore never reached it, in a workspace whose
omo layer no session had ever seeded. A precondition you only check when you are
about to use the thing is not a precondition.

It now runs at the top of the session, and it runs without you: the
`UserPromptSubmit` census hook measures the wrapper, the backends, and the store the
moment `/omo` is invoked, and hands you a line like

    OMO -> wrapper:0.21.6 backends:claude-only store:UNSEEDED(rules/+HUB.md)

Say that line to the user before your first delegation or edit -- `Agent`, `Task`,
`Edit`, and `Write` are denied until you do. Seed an unseeded store with
`python3 bin/omo-init`, which also installs the loader for every vendor actually on
PATH; `store:NO-ANCHOR` means there is no store here at all, and that one needs
`python3 bin/omo-init --create` -- the plain form exits 2 on purpose, because
creating a store root is a decision, not a repair. **Offer either; do not run it
silently** -- it writes into the user's repo. If the
loader cannot be installed -- or the backend is claude, where it cannot be -- say so:
the consultation still works, but the worker is a stranger answering questions rather
than a worker under this project's rules, and you weigh its answer accordingly.

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
   that every existence check reports as perfectly present. **The census hook does
   this comparison for you** and reports `0.21.5!=0.21.6(STALE)`; the manual form is
   `codeagent-wrapper --version` against the version in `.claude-plugin/plugin.json`.
   Measured three times: the second time the call ledger shipped the day before
   recorded nothing at all through `PATH` while the check passed, and the third
   (2026-09-01) found v0.20.0 answering against a 0.21.6 cache. The durable fix is a
   symlink from a `PATH` directory to `$GOBIN/codeagent-wrapper` rather than a copy,
   so the next `make install` is live with no second step -- `python3 bin/omo-init
   --wrapper-only` now builds, installs, and makes that symlink in one command, which
   is what the drift kept recurring for: it was three prose steps and nobody ran all
   three.

   A wrapper built from the **plugin cache** rather than a git checkout used to stamp
   the literal `dev`, because `git describe` fails there -- so the fix for a stale
   binary produced a binary that could no longer report whether it was stale. The
   Makefile now falls back to the manifest version.
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

## Degraded Mode — no vendor backend on this machine

A claude-only machine is a supported configuration, and on one of them **routing a
fan-out through the wrapper is a net loss, not a compromise.** Four reasons, and they
compound: a round trip you did not need; the loss of the session's hooks and repo
`CLAUDE.md`, because `backend/claude.go` passes `--setting-sources ""`; no loader,
for the same reason; and `oracle` is bound to `claude-opus-5`, so an Opus session
consulting it gets the same model a native Opus agent would have given it — ground 4
is not satisfied and there is no model diversity to buy. Native `Agent` delegation is
the correct call, and taking it is not a failure.

**Reporting it as if nothing changed is the failure.** On 2026-09-01 a session did
exactly this — correctly substituted native agents for twelve-plus workers — and the
substitution reached the user as one line inside one status report, with no record
anywhere. The user found out by opening the store and finding it empty. So degraded
mode carries three obligations, and none of them are discharged by a passing mention:

1. **Tell the user in a section of its own**, not a clause. Name which backends are
   absent, that the fan-out is going native, and that the cross-vendor value the user
   may have asked for is *not* available on this machine — if the brief said "use
   cross-model a lot", that brief cannot be satisfied here and saying so is the whole
   job. Offer the install as a question; **never install a vendor CLI on your own.**
2. **Write the worker record** to `.hq/community/sessions/<YYYY-MM-DD>-<worker>.md`.
   A native delegation leaves no ledger row — the ledger only sees the wrapper — so
   this file is the only trace it ever happened, and "the wrapper was not used, so
   there is nothing to record" is precisely the blind spot that made the incident
   invisible.
3. **Name the ground anyway.** Grounds 1–4 govern whether to delegate at all; the
   backend only decides who receives it. A native delegation with no ground stated is
   the same defect as a vendor call with no `--ground`, minus the flag that would
   have let a review count it.

### Two channel limits that bite native workers

Both measured 2026-09-01, both cost that session a retry:

- **A subagent's result comes back through a channel that truncates near 4 KB.** A
  36 KB analysis was cut twice before the session gave up and switched to a file. So
  in degraded mode, tell the worker to **write its report to a file and return the
  path** whenever the report could exceed a page. Returning the path is not a
  workaround; it is the default.
- **A read-only role has no `Write` tool.** `oracle`, `architect`, and the other
  read-only cards can still produce a file — through a `Bash` heredoc — but they will
  not think to, so say it in the dispatch: *"write your report to `<path>` with a
  Bash heredoc, then return only the path."*

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

**Launch it where you can watch it, then confirm once that it is alive.** With a
person at the session, `bin/omo-consult` puts the call in a visible pane (Orca or
tmux); background launch is for when you are leaving. Either way, check liveness
immediately after firing — tail the log or the `--output` file and see bytes
arriving. **Zero bytes is not "still thinking."** A background launcher hands the
wrapper a stdin that is never closed, and until 0.21.3 the wrapper waited on it
forever: measured 2026-08-31, 65 minutes of silence that read as a running
consultation. The wait is now bounded to 5 seconds and fails loudly, which you
only see if you look.

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

- **FORBIDDEN** to delegate without naming which of the four grounds holds — in the
  Context Pack *and* as `--ground <1-4>` on the call. The prose tells the vendor; the
  flag is what the ledger can count, and a ground stated only in prose is a ground no
  weekly review can see.
- **FORBIDDEN** to invoke a role without the original request and a complete
  Context Pack.
- **FORBIDDEN** to approve your own work. The reviewing pass and the authoring pass
  are different passes, and under ground 4 a different model.
- **FORBIDDEN** to treat `explore → oracle → develop` as a mandatory workflow.
- **FORBIDDEN** to report a vendor's output as a result. It is advice; you verify it
  against the repo before acting on it.
- **FORBIDDEN** to substitute native `Agent` delegation for an absent backend without
  the three obligations in *Degraded Mode* — a section of its own to the user, a
  `sessions/` worker record, and a named ground. Doing the substitution is right;
  doing it quietly is the 2026-09-01 defect.
- **FORBIDDEN** to work past an `UNSEEDED` store without telling the user it is
  unseeded. Seeding it is their call; noticing it is yours.

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

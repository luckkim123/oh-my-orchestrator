# Campaign Protocol

How a multi-worker campaign runs on top of the board. Ported from the
`team-project` skill (2026-08-26, decision D3), which this replaces. Every rule
below was paid for by an incident on the 2026-08-23/24 paper-hub campaign
(12+ workers) — they are measurements, not preferences.

**Use it** when the work has 3+ independently workable axes, or spans 2+ repos, or
is a finding/document fan-out with cross-review. **Do not** use it for one session's
worth of work, or a plain parallel fan-out with no shared state — subagents suffice
there, and the board is overhead with nothing to hold.

## One gate

| Layer | Who | What |
|:---|:---|:---|
| Scale judgment | automatic | count axes, repos, documents |
| Structure design | automatic | workers, scopes, ownership, categories, briefs |
| **Launch** | **human — one approval** | the only gate |

The launch proposal is **six lines**:

1. **Workers** — how many and their role names.
2. **Scope** — what each one owns, by file or directory. Disjoint.
3. **Model per worker** — the actual model, not the backend. Diversity is counted in
   models; a backend running the same model family is the same prior.
4. **Repo write rights** — which workers may write the repo at all, and on which
   branch. A path without a branch means "whatever happens to be checked out",
   which is how a commit lands on someone else's work.
5. **Expected cost** — estimated tokens. Goes to `board.json` `cost.estimated_tokens`.
6. **Termination condition** — what ends this campaign.

A proposal missing termination is not a proposal. A proposal missing the model or
the write rights is the two incidents this port added lines for.

## Layout

Beside the project's other harness state, at the root of the project that owns the
work — in a multi-project repo that is the project's folder, not the repo root.

```
<project>/.orchestration/
  HUB.md                             prose: goal, the request verbatim, decisions
  board.json                         machine state: the gate, workers, tasks, cost
  posts/<category>/<NNN-slug>.md     one file = one post; NNN monotonic across the WHOLE tree
  sessions/<YYYY-MM-DD>-<worker>.md  episodic: did / artifact paths / not-verified
  agents/<role>.md                   semantic: what the next holder of this role needs
  rules/                             the payload vendor workers load every task
  knowledge/{libraries,research}/    verified facts worth outliving the campaign
```

Verify nothing here is ignored: `git check-ignore -v .orchestration/` — any output
means the board dies with the session, and the `.gitignore` is what to fix first.

**No `campaigns/` layer by default.** The project folder already separates the work.
Subdividing again buys nothing and costs id collisions: two campaigns each numbering
their own `finding/001` cannot merge without renumbering, and renumbering breaks
every `id: <category>/<NNN>` cross-reference. Measured: 4 colliding ids across 2
campaigns, plus 5 stale path citations still unresolved. Add
`campaigns/<YYYY-slug>/` only when the work has a hard end boundary you will
actually close — closing is the layer's one function. **Never create
`campaigns/main/`**: that is the depth with none of the function.

**Date-prefix session files.** Flat `sessions/` accumulates forever and role names
repeat, so `sessions/coordinator.md` collides across months.

**Number posts across the whole tree, not per category** — `finding/007` then
`decision/008`. Categories get revised, and a globally-numbered post keeps its id
when it moves between them.

## Post categories — five defaults, add but never rename

The axis is **what a reader wants to do with the post**, never its topic. Topic axes
get reinvented every campaign, which is how everything ends up in one `finding/`.

| Category | Holds | The reader is |
|:---|:---|:---|
| `finding/` | investigation and measurement results — facts | looking up what is known |
| `decision/` | a decision and the grounds for it | avoiding re-litigating it |
| `review/` | critique of someone else's artifact | acting on the critique |
| `handoff/` | what the next session or worker must pick up | resuming |
| `question/` | an open question still waiting on an answer | answering it |

A campaign may **add** a category. It may not rename or delete these five — a rename
breaks every cross-reference citing the id.

## Post convention

A 76KB single discussion file was measured as a no-op: nobody read it. So one file =
one post, with a header that makes search work:

```markdown
# <title>
- id: <category>/<NNN> · date: YYYY-MM-DD · author: <session or worker name>
- to: <name, or all> · keywords: <3-6 search terms>
- summary: <one line — others decide from this alone whether to open it>

<body: conclusion first, evidence as file:symbol>

## Comments
- (YYYY-MM-DD, <name>) <content>          ← append-only
```

**Cite symbols, not line numbers.** Line numbers drift silently — 4 of 4 line-cited
anchors had shifted on recheck.

**An unsourced copy is forbidden.** Every copied fact carries its source
(`file:symbol` or a commit sha) and its measurement date. The five handoff numbers
three workers later refuted were exactly the unsourced ones; sourced claims
re-verified cleanly.

## Two memory layers — distill, do not dump

Storing raw or compressed transcripts loses to distilled lessons. Measured on this
rig: a 76KB read-all was a no-op, and a cross-session cache claim showed 0
observations across a 514-file read-through.

- **`sessions/<YYYY-MM-DD>-<worker>.md` — episodic.** Three lines: did / artifact
  paths / not-verified. Scoped to one run. A completed agent also resumes from its
  own transcript, so keeping full transcripts here is redundant.
- **`agents/<role>.md` — semantic.** 40 lines maximum, append-only, outlives every
  campaign: traps, settled facts, failed approaches — what the NEXT holder of this
  role must know. **Never an activity log.** Stale lessons get a `(stale)` banner,
  never deletion. When re-summoning a role, its file goes into the brief; the
  SubagentStart hook injects it automatically.

Facts go to their owning store **at write time**. "Distill later" measured at zero
follow-through.

| Content | Owning store | What the post keeps |
|:---|:---|:---|
| Verified library behavior, numbers, thresholds | `knowledge/` or the project's own index | sourced copy or pointer, plus a one-line summary |
| Role lessons | `agents/<role>.md` | that file *is* the record |
| Decisions | `HUB.md` decision table | native |

## Worker brief

Base: background · failure modes · task with artifact paths · file ownership ·
autonomy (run-to-completion or stage-gated, pick one) · communication · termination ·
measurement disclosure · conventions.

Four additions, each paid for by an incident:

```markdown
## Resource ownership          ← GPU contention: 6 hangs, hours lost
- You hold: <GPU pin / port / container / serial port>. Others hold: <list>.
- Check occupancy before claiming; record the claim in HUB.md.
- Contention shows up as a hang, not an error — a stall means check resources first.

## Git coordinates             ← a commit landed on an unrelated checked-out branch
- Repo: <path> · **branch: <name>** · commit rights: <you / coordinator only>
- A path without a branch means "whatever happens to be checked out".

## Reporting IS termination    ← 3 workers went idle silently, double-nagged twice
- When done: append distilled lessons to .orchestration/agents/<role>.md, land your
  post, set your board row to `reported`, then stop.
- Going quiet is not completion. If you got nagged, you broke this line.
- SubagentStop enforces this: it holds your exit until the row says reported.

## The coordinator is fallible ← a wrong instruction (0.28 -> 0.27) was applied faithfully
- Any number or path in my instructions: verify against the source before applying.
- On mismatch, push back instead of applying. Faithful application has shipped a
  wrong answer.
```

## Reporting is a two-step

1. **Distill** — append to `agents/<role>.md`.
2. **Report** — land the post, set `workers[].status` to `reported`.

Only then stop. This is not advice: `harness-subagentstop.py` holds the exit until
both are true, because three workers going quiet is what made it a rule.

## Reusing an idle worker

**Role name = worker name.** A role that already ran and reported can be re-summoned
for a new task in the same campaign — its `agents/<role>.md` is the brief material,
and the SubagentStart hook injects it. Set its board row back to `claimed`.

Do not invent `lit-critic-2` for the same job. A second row for one role makes the
vendor and model ambiguous, and the spawn hook flags it as a mismatch.

## Manager — a role, not a standing agent

Context pressure was measured **only at the coordinator layer** (2 compactions;
workers: 0). A standing manager that reads the whole board is one more
coordinator-class consumer. Start as a role:

| When | The manager does |
|:---|:---|
| Launch | post the rules, any added categories, the owning session in HUB.md |
| Milestone | banner stale posts, adjudicate contradictions, refresh the board |
| Close | promote posts to their owning stores, sweep `agents/`, close out `sessions/` |

Split the manager out only when board upkeep measurably crowds the coordinator's
context — and even then the manager and the verifier stay separate agents. The
fallibility rule applies to managers too.

## Cost: estimated at launch, actual at close

`board.json` carries both. `cost.estimated_tokens` comes from the launch proposal;
`cost.actual_tokens` stays `null` until the campaign closes, then gets the real
number. A campaign that never records the actual number cannot correct the next
estimate, and every estimate after it is the same guess repeated.

## Termination and scale

- Worker count comes from the axis count, never from "more is better". 13-vs-3 has
  never been measured here; the literature's saturation point (~4) is not this rig's
  measurement.
- Session-to-session exchanges end with a `[FINAL]`-titled message. `[FINAL]` is
  never answered. Cap: one cross-review round after completion.
- Workers end by reporting. The coordinator ends the campaign by setting
  `board.json` `status` to `closed` and running the manager's close duties. **The
  board stays on disk** — the posts are the record.
- Adding a worker mid-campaign needs the same six-line proposal as launch.

## Transport

The board is transport-agnostic. Pick per pair:

| Pair | Use |
|:---|:---|
| Coordinator ↔ its own subagent | Agent tool + SendMessage |
| Session ↔ session, same machine | SendMessage — carried a full campaign exchange with zero defects |
| Cross-machine | `orca` — see `orca-boundary.md` |

## Before compacting

The coordinator is where context pressure was actually measured, so this duty is
the coordinator's:

1. Sync the task board to reality.
2. Record new user decisions in the HUB decision table. An answer that lives only in
   session context does not exist for any other session.
3. Record what was launched and what was collected — and what is still running.

With those three done, compaction is safe. Measured: two compactions, zero lost
work, because HUB.md held the state.

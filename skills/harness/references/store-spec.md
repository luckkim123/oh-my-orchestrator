# Store Spec — the `.hq/` unified state store

The single source of truth for **where any om\* harness writes its state**, how that
state is layered, and what the hooks do when the layout is wrong.

This spec supersedes the per-harness layout rules that used to live in
`campaign-protocol.md` §Layout, its owning-store table, and `omo/references/shared-context.md`
§Layout. Those sections now point here. Nothing in this file is a preference — every
rule below traces to a measurement on the machine `ksm-mac`, dated 2026-08-27 unless
stated otherwise.

> **Status: cutover in progress, per harness.** Phase 0 (2026-08-27) froze this
> spec's design; every harness has since migrated its file content (§9.1) and
> shipped code against it. As of 2026-08-28, all six harnesses — `omp` (0.16.0),
> `oms` (0.20.0), `omd` (0.11.0), `omx` (0.14.0), `omha` (0.10.0), `omo` (0.8.0,
> this release) — have shipped §7 **stage 2** (fallback removal): an anchored
> project resolves reads and writes to `.hq/` only, no legacy fallback. `oms`
> was still on stage 1 earlier the same day (a mid-edit read of its released
> 0.19.0), corrected here after re-reading its own `hooks/oms_paths.py` at its
> current 0.20.0 state, not taken on a second-hand count. The four-state hook
> table below (§6) describes the stage-2 rule; §9.1 tracks per-anchor
> file-migration progress.
>
> Stage 3 (`--purge`) **ran on `ksm-mac`, 2026-08-28** — 20 legacy stores
> deleted, `migrate-om-store.sh census` now reports `in scope: 0`. The
> precondition held: hooks execute from `~/.claude/plugins/cache/`, not from
> these repos, so the six plugin caches had to be updated (and the session
> restarted) before a pushed release changed what any session was told. Purge
> stays a per-anchor decision on every other machine, where the legacy stores
> are still on disk and each harness's release only stops *reading* them.

---

## 1. Why one root

Six harnesses (`omp`, `oms`, `omd`, `omx`, `omha`, `omo`) each grew their own dot-dir.
The result on one machine is **23 stores across four filesystems**, and the cost is not
the file count — it is that a fact learned in one harness is invisible to the next. A
record written by `oms` about a citation convention cannot be found by `omd` writing a
slide deck about the same paper, because neither knows the other's store exists.

The fix is one root per **anchor** (a project boundary), with the harness recorded *in
the record* rather than in the path. Per-harness partitioning survives as a field
(`harness:`), not as a directory.

---

## 2. The anchor

An **anchor** is a directory holding `.hq/`. It marks a project boundary. Lookup walks
up from the working directory to the nearest anchor (local), then continues to any
outer anchor (global) — the local-to-global *ascent* pattern `oms` already uses.

### Granularity — which directory gets the anchor

> **One anchor per git repository, at its root.** A repo holding several independent
> projects still gets exactly one `.hq/`. The projects are told apart *inside* the
> store, by the `project:` field (§4), never by a second anchor.

**This reverses the rule this section carried until 2026-08-29**, which put the anchor
at each project's folder and called nesting legitimate. The reversal is a user decision
and its argument is this repo's own case law: a capability nobody invokes is
indistinguishable from one that does not exist (`tokensave`, 6 MCP calls against 10,813
tool calls in 22 days; `graphify`'s MCP server, 0 calls in 30). Cross-anchor lookup was
in that class — `hq query` implemented ascent on the `--subject` path only, so every
other path answered from `roots[0]` and each board saw only itself. Measured on the
vault the day of the decision: three sibling anchors, `0` citations had ever crossed
one. And ascent could not have fixed it, because ascent only walks *up*: two sibling
projects in one repo are invisible to each other by construction, no matter how much of
the ascent machinery is finished.

What replaces the directory axis:

- **Post ids are anchor-global and monotonic** (§4). Merging two boards therefore
  renumbers one of them. Renumber the side with fewer inbound references and rewrite
  those references in the same commit — and note that a bare `<category>/<NNN>` means
  whichever board its *source file* belongs to, so a repo-wide search-and-replace
  corrupts the side that kept its numbers.
- **`project:` and `harness:` are the two axes**, both fields, both queryable
  (`hq query --project`, `--harness`). Neither is a directory.
- **An outer anchor is still resolved by ascent**, and that is now strictly a
  cross-*repository* mechanism: a repo nested inside another repo's tree keeps its own
  anchor, because its records must travel with its own history.

Unmigrated: **`workspace` still runs a three-deep chain** (`workspace/.oms`,
`12_Masters_Thesis/.oms`, `03_thesis/paper/.oms`). It is debt against this rule, not an
exception to it — the user deferred it ("workspace는 나중에 할거", 2026-08-29), and it is
not a git repository, so the merge procedure above does not transfer unchanged. Do not
cite it as precedent for a new nested anchor.

One thing the old rule got right and this one keeps: anchor-id uniqueness within a
machine, and namespaced citations (`<anchor-id>:<category>/<NNN>`) for the cross-repo
case (§4).

Verify the tracked layers are not ignored before trusting an anchor:

```bash
git check-ignore -v .hq/community/ .hq/config/     # any output is a bug in .gitignore
git check-ignore -v .hq/work/ .hq/runtime/         # both SHOULD print a rule
```

The first command producing output means the community store dies with the session, and
`.gitignore` is what to fix first — not the store.

### `.hq/.anchor` — identity only, write-once

Plain text, **exactly one line**:

```
id: <machine-unique-slug>
```

No other line is permitted. A second line, a missing `id:` prefix, or an empty value is
a **parse failure**, which is a loud failure (§6, row 4).

`id` must be unique **within a machine**. `hq lint` scans every anchor reachable by
ascent and fails on a duplicate. This is not hypothetical: `workspace` carries a
three-deep `.oms` chain (`workspace/.oms` then `12_Masters_Thesis/.oms` then
`03_thesis/paper/.oms`), so without a uniqueness check a cross-anchor citation is
immediately ambiguous.

**Migration bookkeeping does not go in this file.** Multiple machines writing the same
tracked file automatically produces git conflict markers, and a conflict marker inside
a file parsed strictly kills every hook on every machine at once.

### `.hq/config/migrated.jsonl` — the ledger, a sibling file

Append-only, one JSON object per line:

```json
{"harness":"omp","at":"2026-08-27T14:03:11+09:00","machine":"ksm-mac"}
```

Declare it in the **anchor root's** `.gitattributes`:

```
.hq/config/migrated.jsonl merge=union
```

Union merge is what makes concurrent machines safe. It also means **absence of a row is
not evidence of non-migration** — it is equally consistent with "that machine has not
pushed yet". Nothing may automate a quorum judgment off this file; see §7.

---

## 3. The four layers

```
<anchor>/.hq/
├── .anchor               [tracked]   id, one line, write-once
├── community/            [tracked]   the post store — human records
│   ├── HUB.md
│   ├── INDEX.md                      derived; verbs regenerate it; still tracked
│   ├── posts/<category>/<NNN>-<slug>.md
│   ├── agents/<role>.md
│   ├── sessions/<YYYY-MM-DD>-<worker>.md
│   └── rules/                        the vendor payload
├── config/               [tracked]   what code parses; not sensitive
│   ├── migrated.jsonl
│   └── project/  scholar/  docs/  experiments/  routing/
├── work/                 [ignored]   regenerable artifacts
│   └── project/  docs/<slug>/  scholar/<slug>/  experiments/{runs,campaigns}/
└── runtime/              [ignored]   session state, locks, logs, sensitive files
    ├── board.json
    └── project/  scholar/  docs/  experiments/  routing/
```

### Layer rules — five questions and a total order

| # | Question | Layer |
|:--|:---|:---|
| ① | Does it contain a personal string, a secret, or a redaction pattern? | `runtime/` |
| ⑤ | Is it session state, a lock, or a log? (both conditions below) | `runtime/` |
| ④ | Can a verb regenerate it from other files? | `work/` |
| ③ | Does harness **code parse** it? | `config/` |
| ② | Is it a record a human wrote for another human? | `community/` |

**Ties are resolved by that order — ① beats ⑤ beats ④ beats ③ beats ②** — and they are
resolved **per file, never per directory.** A directory holding a mix gets split across
layers, with one row per file in the mapping table (§9).

The order is not arbitrary. Read it as a sequence of "what breaks if this is wrong": a
leaked secret is unrecoverable; a tracked file rewritten every turn makes the repo
permanently dirty and conflicts across machines; a regenerable artifact in git is dead
weight forever; a config file a human cannot find is an annoyance; a human record in the
wrong layer is merely untidy.

### ⑤ has two conditions, and both must hold

> (a) It is rewritten every session or every turn, **and**
> (b) losing it is harmless — the next session regenerates it, or its absence is a
> legitimate state.

If either fails, it is not ⑤. This is the rule that separates two files that look
identical from a distance:

| File | (a) rewritten often | (b) loss harmless | Layer |
|:---|:---|:---|:---|
| `board.json` | yes | yes — no board means "no active campaign", a normal off state | `runtime/` |
| `secretary/ledger.jsonl` | yes | **no** — it *is* the project's history | `config/` |
| `garden-state.json` | yes | yes — sweep counters recount | `runtime/` |
| `state/verify-throttle.json` | yes | yes | `runtime/` |
| `.omha/routing.jsonl` | yes | yes — a machine-local metric, already documented as such | `runtime/` |
| `state/verified-citations.json` | on verification | **no** — loss costs a re-verification pass | `config/` |

**`board.json` is runtime, deliberately.** Putting it in `config/` (tracked) was
considered and rejected: `cost.actual_tokens` and the session counters change every
turn, which makes the repo permanently dirty and produces a JSON merge conflict on every
cross-machine sync. The original spec already called the board machine-local runtime
state. What the four-state table (§6) fixes is the *silent* half of the old rule — a
**corrupt** board must be loud — not the board's absence, which stays a normal off state
and is explicitly a non-goal to detect.

### The ②/③ tie is real — measured

`omp` hooks parse `STRUCTURE.md` and `DATASETS.md`: `omp_content_audit.py:113` reads
both and extracts the paths they name to detect `structure_drift`, and
`omp_doc_garden.py:65` claims them as `OWNED_BY_AUDIT`. They are simultaneously prose a
human reads and input a program parses. **③ wins: they go to `config/`.**

`NAMING.md`, `CONVENTIONS.md`, and `PROJECT.md` appear only inside hook *prompt strings*
(`omp_route_emit.py:85-130`), which instruct a human to read them. No code parses them.
**② holds: they go to `community/`.**

That split looks surprising sitting in one directory today, and it is the intended
consequence of per-file resolution. Keeping the five together would mean either putting
parsed input in a layer no verb reads, or putting free prose behind a schema.

---

## 4. Post schema

One file is one post. The categories are the five defaults from `campaign-protocol.md`
(`finding`, `decision`, `review`, `handoff`, `question`) — a campaign may add, never
rename or delete.

```markdown
# <title>
- id: <category>/<NNN> · date: YYYY-MM-DD · author: <session-or-agent>
- project: <slug> · harness: <omp|oms|omd|omx|omha|omo|none> · to: <name|all>
- subject: <kebab-slug> · supersedes: <category>/<NNN>|none
- topic: <architecture|decision|pattern|debugging|environment|reference|convention|session-log|technique|history>
- confidence: <high|medium|low|none> · status: <none|needs-experiment|needs-apply-before-retrain|resolved>
- verified: YYYY-MM-DD (against <version|commit>) · keywords: <3-6>
- summary: <one line — others decide from this alone whether to open it>

<body: conclusion first, evidence as file:symbol>

## Comments
- (YYYY-MM-DD, <name>) <content>          ← append-only
- (YYYY-MM-DD, <name>) [<confirmed|contradicted|superseded>] <content>
  scope: <exactly which claim was checked>
  evidence: <a reproducible command, output, commit, or measurement>
```

`project:` is the axis that used to be the anchor directory (§2, 2026-08-29). It is
required on any post in a repo that holds more than one project; a single-project repo
may omit it. `harness:` is the second, independent axis — a project's records can come
from several harnesses and a harness writes into several projects.

`confidence: none` is not an assessment; it is the explicit absence of one, the same way
`status: none` and `supersedes: none` read. It exists so a pre-schema post can satisfy
the schema without anyone inventing a confidence it never had. Never use it for a post
whose author *did* judge — write what they judged.

A comment whose text opens with a bracketed assessment is a **review**. It is
*counted* only when it carries a non-empty `evidence:` line and its author differs from
the post's `author:` — author and approver are different passes. `hq query` returns the
counted ones and only those; `hq lint` names the rest, so an ungrounded review is
visible where a mistake gets fixed rather than where an answer gets decided. The fields
are line-anchored rather than ` · `-separated because comment text is prose and prose
contains that separator.

Fields carried over unchanged from the old convention: `id`, `date`, `author`, `to`,
`keywords`, `summary`, the append-only `## Comments` block, and **cite symbols, not line
numbers** (4 of 4 line-cited anchors had drifted on recheck).

Fields this spec adds:

| Field | Why |
|:---|:---|
| `harness:` | the per-harness partition the directory used to carry |
| `subject:` | the mutable-record axis — see below |
| `supersedes:` | how a subject's canonical entry advances |
| `topic:` | the old wiki taxonomy, including `session-log`; the *directory* axis stays reader-intent. **`technique` and `history` joined it in r7** — the retiring wiki trees use six category directories (convention · decision · history · pattern · reference · technique) and two of them had no value here, so a lossless form conversion had to either widen this enum or merge distinctions the author drew. `technique` was not even in omd's own `lint_wiki.CATEGORIES` while §9.3's omd row listed it |
| `confidence:` · `status:` | ported from the wiki schema; `needs-apply-before-retrain` keeps its launch-blocking meaning |
| `verified:` | the staleness clock the knowledge store used to carry as a banner |

### `subject:` — how a post store holds mutable truth

A post is an event ("this is what was judged, then"); a wiki page is a state ("this is
what is true, now"). Merging them naively loses the second. `subject:` is what restores
it: **within one anchor, the set of posts sharing a `subject:` forms a supersede chain,
and exactly one post is its head.** The head is that subject's canonical answer.

- `hq lint` enforces head uniqueness. Two heads on one subject is a lint failure, and
  the Phase 1 planted-defect fixtures include it.
- `hq query --subject <slug>` returns the canonical post.
- Editing: on a **git anchor** the body is mutable (git is the safety net, and a
  correction line goes in `## Comments`). On a **no-git anchor** the body is immutable —
  correction happens by superseding. See §8.

### Cross-anchor citation and canonical precedence

`id` is monotonic **per anchor**, across the whole tree (not per category). A citation
that crosses an anchor boundary is namespaced:

```
<anchor-id>:<category>/<NNN>
```

Two anchors may hold the same `subject:`. Ascent resolves it as follows:

> **Return the nearest anchor's canonical post, and list the canonicals it shadows.**

Never merge them silently, and never return only the nearest. A shadowed canonical is
usually the more general statement, and often the reason the caller asked.

### What the post store absorbs

`knowledge/libraries/` and `knowledge/research/` are **absorbed into posts** — they were
a second record schema for the same thing. Their staleness discipline survives as
fields, not as a banner convention:

| Old knowledge/ rule | New home |
|:---|:---|
| `> Last verified: YYYY-MM-DD against version x.y.z` | `verified:` field |
| A stale entry gets bannered, never deleted | supersede chain — the old head stays, reachable |
| Re-verification is part of the task that needed it | unchanged, a rule not a tool |
| A version bump alone is not verification | unchanged |

`templates/orchestration/knowledge/` is removed in the same commit that publishes this
spec.

---

## 5. `.gitignore`

Two lines, at every repo that hosts an anchor. The `**/` prefix is required — anchors
nest, and a repo-root-relative rule misses the nested ones:

```
**/.hq/work/
**/.hq/runtime/
**/.harness.lock/
```

(The third line is new with the 2026-08-31 root-local lock move: the state lock
now lives in the root itself, so a session that dies holding it leaves an empty
lockdir that would otherwise sit in `git status` until the next acquire reaps it.)

**The per-harness legacy ignore lines are removed, as of this round (§9.4).** `oms`
dropped `.oms/`, `omd` dropped `.omd/`, `omha` dropped `.omha/redact-patterns.txt`, `omx`
dropped `.omx/`; `omp` and `omo` never had one of their own to drop. What remains is not
a per-harness line still pending its own fallback-removal release — every harness has
had that release now — it is two *other* repos that each host anchors for multiple
harnesses: `claudebase`'s own `.omp/*` + `!.omp/rules.json` and `**/.orchestration/
.hq-lock`, and the vault's `.omp/work/` · `.omp/state/` · `.omha/` · `**/.orchestration/
.hq-lock`. Those come after `--purge` (§7 stage 3), which has not run anywhere on this
machine — removing an ignore line ahead of the purge would leak the about-to-be-deleted
legacy directory into git as a tracked file the moment anything touches it.

### The tracked/ignored boundary shift for three repos

`oh-my-docs`, `oh-my-scholar`, and `oh-my-experiments` used to ignore their **entire**
store (`.omd/`, `.oms/`, `.omx/`). Under the new layout `config/` and `community/` are
tracked, so `learned.md` — previously invisible to git in those repos — is now a
committed file. That shift has landed in all three repos this round, flagged per repo in
the mapping table (§9.4) as `policy-shift`; it is no longer a pending decision.

---

## 6. Hook behavior — four states

The gate is the pair (legacy `.om?` store, `.hq/.anchor`), never a single marker.

| Legacy `.om?` store | `.hq/.anchor` | Behavior |
|:---|:---|:---|
| absent | absent | feature **off, exit 0** — a repo that does not use this harness |
| **present**, board parses or absent | absent | **warn — unmigrated legacy store, reads will not find it** (§7 stage 2: no fallback) |
| **present**, board **unparseable** | absent | **loud failure, exit non-zero** (B-r1 widening, 2026-08-31) |
| — | present, valid | normal operation (no board = no active campaign = normal off) |
| — | present, **corrupt** | **loud failure, exit non-zero** |

"Corrupt" means: duplicate anchor id, `.anchor` unparseable, **or a board present and
unparseable** — anchored (`.hq/runtime/board.json`) or, since the 2026-08-31 widening,
legacy with no anchor (`.orchestration/board.json`, `harness-tasks.json`). Row 2's warn
channel is silent at hook entry, so a corrupt legacy store read as merely "unmigrated"
was the same silent failure row 4 exists to surface. Two 2026-08-31 boundaries on
rows 2-3, both measured: (a) the parse check follows `state_path` precedence — the
board when it exists, else `harness-tasks.json` — so a corrupt *stale* sibling never
overrides the valid file hooks actually read; (b) hook *discovery* is marker-file
based, so a legacy store that is only an empty `.orchestration/` directory is never
found by hooks at all — row 2's warn fires only when one of the three state files
exists.

Row 2 is the one worth stating plainly. A three-state design (off / on / broken) sends
"legacy store present, not yet migrated" — the most dangerous state in the whole
migration — into the quiet `off` branch, where a hook that has silently stopped looks
exactly like a hook that correctly decided it had no work.

Row 4 **reverses half of** the rule in `harness/SKILL.md` §Activation Gate: "Any other
value, a missing board, or a board that will not parse: every hook exits 0." The
*missing* half stands. The *will not parse* half does not — that is a corrupt store
being read as an absent one.

Acceptance requires a fixture for all four rows, plus one for the unanchored
legacy-corrupt widening. "Swallow every failure" survives as the
rule everywhere except row 4.

### Row 4's one exception — `PreCompact` is loud without blocking (P1, 2026-08-27)

Every hook implements row 4 as stderr plus exit 2, except `harness-precompact.py`, which
emits `{"continue": true, "systemMessage": ...}` — its own existing loud channel, the one
it already uses for HUB/board drift.

The reason is measured and recorded in that hook's docstring: `PreCompact` **can** block,
and unlike `SubagentStop` it has no `stop_hook_active`-style loop guard. A corrupt board
is exactly the kind of condition that persists across retries, so a blocking exit there
would make compaction impossible at the context ceiling — the one moment in a session
with no way out. The user still sees the failure; only the blocking half is dropped.

Read row 4 as **"never silent"** rather than "always exit 2". `SubagentStart` is the same
distinction from the other side: it exits 2 for uniformity, but its own docstring records
that exit 2 does not block a spawn and its stderr does not reach the user, so it is as
loud as that hook can be rather than fully effective.

Implementation: `hq/anchor.py` `gate_state()`, reached through
`_harness_common.gate_corrupt_reason()`. `self-reflect-stop.py` is deliberately untouched
— it gates on a `.harness-reflect` marker and never reads `board.json`, so it has no
silent-failure branch to reverse.

---

## 7. Fallback, `--purge`, and who decides

Cutover per harness runs in three stages:

1. **Write new, read both.** Writes always go to `.hq/`. Reads try `.hq/` and fall back
   to the legacy store. A row is appended to `migrated.jsonl`.
2. **Fallback removal.** Reads stop consulting the legacy path.
3. **Purge.** The legacy store is deleted.

**Moves are two-step: copy, then verify. The legacy store is not deleted, trashed, or
`git rm`-ed at move time.** Deletion is a separate `migrate-om-store.sh purge` subcommand
that runs only after stage 2, per anchor.

**The `.anchor` marker covers every store under it.** An anchor holding several legacy
stores (`.omp` + `.omx`, ...) is one unit: create `.hq/.anchor` only after *all* of them
are copied and verified — a gated or failed store blocks the marker. The migration tool
says so at the end of a plan/apply run that leaves a store unfinished on an unanchored
root (claudebase `migrate-om-store.sh`, 2026-08-31).

The tool is `claudebase` `runtime/bin/migrate-om-store.sh` (P5, 2026-08-28) — dry-run by
default, `apply` copies and sha256-verifies without deleting, `reverse` merges new-store
writes back to the legacy path, and `purge` reads its confirmation from `/dev/tty` so a
piped or closed stdin refuses. §9.3 below is its mapping table; a path no row claims
exits 2 rather than being skipped.

**The decision to advance an anchor past stage 1 belongs to the user, not to a script.**
`migrated.jsonl` is union-merged, so a missing row is indistinguishable from an unpushed
one — automating a quorum on it would be reading absence as evidence. The ledger and the
expected-machine list (§10) are *reference material* for that judgment; `--purge` prompts
for confirmation regardless.

---

## 8. No-git anchors

`~/Desktop/workspace` and its five nested anchors are iCloud-synced and **not a git
repository**. Every rule in this spec that leans on git is void there:

| Rule | Git anchor | No-git anchor |
|:---|:---|:---|
| Post body edits | mutable — git holds the previous version | **immutable** — correct by superseding only |
| Rollback of a bad move | `git checkout` | pre-move `tar` snapshot, kept until verified |
| `.gitignore` layer separation | enforced by git | **not enforced** — layers are convention only |
| Ledger integrity | commits date the migration | none — `tar` hash plus manual confirmation |
| Split-brain detection | mtime vs ledger | **undetectable** — a stated blind spot |

Moves on these anchors happen in a separate pass, after every git anchor has completed,
and never with delete-in-the-same-breath: copy, verify the destination, and only then
consider the source — which under §7 stays put until `--purge` anyway.

---

## 9. The full mapping table

> **Non-normative — origin-machine migration record.** Everything in §9 is the
> 2026-08 census of the machines this store design was migrated on (`ksm-mac`
> and its vault); the paths and project names are that operator's, not part of
> the spec. Nothing below binds a new deployment — the normative contract ends
> at §8.

> **The anchor column below is a 2026-08-27 snapshot and four of its rows no longer
> exist.** On 2026-08-29 the vault's four anchors (`vault`, `vault-albc`,
> `vault-harness`, `vault-krit-simulator`) merged into one at the repo root under the
> revised §2 rule; 114 posts were renumbered into a single monotonic sequence. The
> per-file *layer* assignments in this section are unaffected — they say which of the
> four layers a file belongs to, not which anchor owns it.

Census command (the fixed one — **unbounded depth**; a `-maxdepth 6` variant missed
three real anchors at depths 7–8):

```bash
find ~ -type d \( -name '.omp' -o -name '.oms' -o -name '.omd' -o -name '.omx' \
  -o -name '.omha' -o -name '.orchestration' \) -not -path '*/.git/*' 2>/dev/null
```

Run 2026-08-27 on `ksm-mac`: **29 hits — 23 in scope, 6 excluded.** Census (the roster)
and drift (split-brain detection) use **different instruments on purpose**: census is
this `find` crossed with `git ls-files`; drift compares legacy-path mtimes against
`migrated.jsonl` timestamps. Sharing one command between them would leave zero
independent detectors.

### 9.1 In scope — 23 anchors

| # | Anchor | Harness | Files | Git | Phase |
|:--|:---|:---|---:|:---|:---|
| 1 | `ksm_Obsidian/.omp` | omp | 67 | vault git | **P3 pilot** |
| 2 | `ksm_Obsidian/.oms` | oms | 1 | vault git | P4 |
| 3 | `ksm_Obsidian/.omha` | omha | 1 | vault git (ignored) | P4 |
| 4 | `ksm_Obsidian/0_Project/in_progress/albc/.omx` | omx | 15 | vault git | P7 |
| 5 | `ksm_Obsidian/0_Project/in_progress/albc/.omx/.omx` | omx | 1 | vault git | P7 — mapped as a row of row 4's store, not its own anchor |
| 6 | `ksm_Obsidian/0_Project/in_progress/albc/.orchestration` | omo | 119 | vault git | P7 |
| 7 | `ksm_Obsidian/0_Project/in_progress/krit/simulator/.omp` | omp | 18 | vault git | P6 |
| 8 | `ksm_Obsidian/1_Area/harness/.orchestration` | omo | 16 | vault git | P6 |
| 9 | `Desktop/workspace/.omd` | omd | 871 | **no git** | P6 |
| 10 | `Desktop/workspace/.omp` | omp | 40 | **no git** | P6 |
| 11 | `Desktop/workspace/.oms` | oms | 65 | **no git** | P6 |
| 12 | `Desktop/workspace/10-19_Academic/12_Masters_Thesis/.oms` | oms | 36 | **no git** | P6 |
| 13 | `Desktop/workspace/10-19_Academic/12_Masters_Thesis/03_thesis/paper/.oms` | oms | 5 | **no git** | P6 |
| 14 | `Desktop/workspace/10-19_Academic/13_Lab_Research/01_albc/.oms` | oms | 3 | **no git** | P6 |
| 15 | `Desktop/workspace/10-19_Academic/13_Lab_Research/01_albc/02_drafts/latex/.oms` | oms | 55 | **no git** | P6 |
| 16 | `Desktop/workspace/10-19_Academic/13_Lab_Research/05_talks/03_2026-06_harness_seminar/.omd` | omd | 42 | **no git** | P6 |
| 17 | `claudebase/.omp` | omp | 1 | git | P4 |
| 18 | `claudebase/.orchestration` | omo | 23 | git | P6 |
| 19 | `oh-my-docs/.omd` | omd | 1 | git (ignored) | P4 · `policy-shift` |
| 20 | `oh-my-heroacademia/.omha` | omha | 1 | git | P4 |
| 21 | `oh-my-scholar/.oms` | oms | 2 | git (ignored) | P4 · `policy-shift` |
| 22 | `oh-my-orchestrator/.phase0-scratch/test-e2e-precompact/.orchestration` | omo | — | git | **excluded — scratch** |
| 23 | `oh-my-orchestrator/.phase0-scratch/test-live/.orchestration` | omo | — | git | **excluded — scratch** |

Rows 4–6 (`albc`) were **not inspected** until P7: an active RA-L campaign held them, a
`session-gate` hook blocked the path, and HUB decision D2 deferred the merge. **D2 was
released 2026-08-28 (HUB D20)** and P7 migrated all three — anchor id `vault-albc`, 125
files copied, sha256 verified. The `session-gate` hook was satisfied through its own
designed path (a `Read` of the three declared documents), not bypassed. The migration
tool's `is_gated()` was kept rather than deleted and bound to `HQ_D2_RELEASED=1`, so a
machine that has not seen the release still refuses.

### 9.2 Excluded — by pattern, not by count

| Path | Why excluded |
|:---|:---|
| `oh-my-orchestrator/.phase0-scratch/*/.orchestration` (2) | test scratch, recreated by the test run |
| `~/.claude/plugins/marketplaces/heroacademia/.omha` | marketplace cache — replaced on plugin update |
| `~/.claude/plugins/marketplaces/omc/.omx` | marketplace cache — replaced on plugin update |
| `~/.claude/plugins/cache/heroacademia/oh-my-heroacademia/<sha>/.omha` (2) | plugin install cache — a copy of the repo's tracked `redact-patterns.example.txt` |
| `~/Library/Caches/com.apple.python/**/workspace/.omd` | macOS Python bytecode mirror (`*.pyc` only) |
| `~/Library/Mobile Documents/.Trash/07_drafts/latex/.oms` | iCloud trash |
| any store dir inside another store dir (`*/.omp/*`, `*/.oms/*`, `*/.omd/*`, `*/.omx/*`, `*/.omha/*`, `*/.orchestration/*`) | **added P7** — a path within a store, not an anchor. §9.1 row 5's `.omx/.omx` is mapped as a row of row 4's table; listing it separately is a phantom `legacy` anchor no migration can clear |

The two `plugins/cache/**/.omha` entries and the `com.apple.python` mirror were **not in
the plan's exclusion list** — they surfaced only when the census was re-run at unbounded
depth for this spec.

**The counts in this table are a snapshot; the patterns are the rule.** The plugin cache
holds one `.omha` per *installed version*, so it grew from 2 to 5 across the P2, P3 and
P4 deployments, and the whole-census total went 29 -> 32 without a single anchor
changing. `~/.Trash` gains one on any purge. Read a census against the exclusion globs
(`*/.claude/plugins/*`, `*/Library/Caches/com.apple.python/*`, `*/.Trash/*`,
`*/.phase0-scratch/*`, `*/.hq/*`, and the nested-store globs above), never against a
remembered number —
`migrate-om-store.sh census` is written that way for this reason. Measured 2026-08-28 on
`ksm-mac` **after P7**: 33 hits, 13 excluded, **20 in scope**. The exclusion list grew a
seventh pattern that round — a store directory nested *inside* another legacy store is a
path within that store, not an anchor (§9.1 row 5's `.omx/.omx`, mapped as a row of row
4's table). Before that rule census reported 21 in scope, and the extra row was a phantom
`legacy` anchor no migration could ever clear.

**Verified: `omha` does not read either cache.** `route_log.py:10` documents opt-in "by
directory: writes only when `.omha/` already exists in the session's cwd", and
`redact_guard.py:37` resolves `DENYLIST_REL_PATH = os.path.join(".omha",
"redact-patterns.txt")` relative to the tool call's cwd. Both are cwd-relative; neither
consults a marketplace or plugin-cache path. These rows stay exclusions and are **not**
read-path updates.

### 9.3 Per-file layer assignment

`omp` store:

| Path | Layer | Rule |
|:---|:---|:---|
| `rules.json` · `manifest.json` | `config/project/` | ③ |
| `STRUCTURE.md` · `DATASETS.md` | `config/project/` | ②③ tie, ③ wins (`omp_content_audit.py:113`) |
| `learned.md` | `config/project/` | ③ (`omp_content_audit.py:201`) |
| `PROJECT.md` · `NAMING.md` · `CONVENTIONS.md` | `community/` | ② — prompt strings only, no parser |
| `wiki/*.md` | `community/wiki/` **(staging only)** | ② — **the wiki FORM is retired (r7, 2026-08-30); this row is the file MOVE, which cannot retire it.** `migrate-om-store.sh` moves files and cannot mint the per-page `subject:`/`id:` a post needs, so raw pages still land in `community/wiki/`. That directory is now a **staging state with a single exit**: run omo's `skills/harness/convert-wiki-form.py` (`plan` then `apply`) immediately after, which converts the pages into `community/posts/` and `git rm`s them. An anchor is not finished migrating while `community/wiki/` still has pages in it. ⚠️ omp's tree is FLAT — those pages have no category directory, so `plan` leaves `topic:` null and `apply` REFUSES until a human fills it |
| `secretary/ledger.jsonl` | `config/project/` | ⑤(b) fails — it is the history |
| `secretary/journal/` · `BRIEF.md` · `raid.md` · `todo.txt` · `done.txt` | **community candidate — P6 approval item** | ② by rule; the transition needs a `chronicler` hook revision, so the choice is preserved rather than forced |
| `env/` | `config/project/` | ③ — the `omp-env` canonical Dockerfile/compose assets (**added P5**: absent from this table until `krit/simulator`'s 7 files were censused) |
| `garden-state.json` | `runtime/project/` | ⑤ — `detrack` approval item |
| `state/verify-throttle.json` | `runtime/project/` | ⑤ — `detrack` approval item |
| `work/{audits,plans,scans,tmp,versions}/` | `work/project/` | ④ |
| `.DS_Store` | **not moved** | not ours |

> **The wiki form is retired (r7, 2026-08-30). `community/wiki/` survives in the
> rows above as a STAGING path and nothing else** — the migration is a file move
> and a file move cannot mint a post, so the pages land there and are converted
> out of it in the same sitting. An anchor with pages still in `community/wiki/`
> is mid-migration, not migrated. It was converted for the
> vault's three anchors on 2026-08-28 (16 pages, by hand, into `posts/` under
> the five reader-intent categories), and for the workspace shortly after; on
> no LIVE anchor on this machine holds a wiki page any more (the Google Drive backup of another machine's workspace still does — 35 pages across two trees, which is what the converter was exercised against). What blocked doing it
> everywhere was that `migrate-om-store.sh` moves files and cannot mint the
> per-page `subject:` the §4 form needs — so the conversion is a second pass
> over an already-migrated anchor, and r7 gave it a tool:
> `skills/harness/convert-wiki-form.py`. It derives what is derivable and
> **refuses to guess** the three fields the hand conversion had to decide
> (`category` by reader intent per D22, `subject`, and a title when the page has
> no H1). What the hand pass measured — the field mapping per source form, the
> fields dropped, and why `verified:` cannot be derived from git in a tree that
> has been migrated — is in the vault board's **`finding/098`** (it was
> `finding/021` when written; the 2026-08-29 D29 anchor merge renumbered it, and
> `finding/021` is now an unrelated post).
>
> **Nothing but `migrate-om-store.sh` may create a `community/wiki/` directory**
> (user decision, 2026-08-30: "wiki 는 아예 없애는 걸로. Wiki 폴더 안만들게"). No
> harness writes one, no skill tells an agent to write one, and `omp-init` no
> longer synthesises one for a fresh project. The migration is the sole exception
> and only as the staging step above; the converter reads that tree where it
> already exists and exits with an error where it does not.

`oms` store:

| Path | Layer | Rule |
|:---|:---|:---|
| `learned.md` | `config/scholar/` | ③ |
| `venues/*.yaml` | `config/scholar/venues/` | ③ |
| `workflows/*.js` | `config/scholar/workflows/` | ③ — executed by a verb |
| a Workflow `.js` at the store root (`section3_audit_workflow.js`) | `config/scholar/` | ③ — same class as the row above (`export const meta`, hand-authored, run by a verb), placed at the store root rather than in `workflows/` (**added P6**: absent from this table until `12_Masters_Thesis/.oms` was censused). It keeps the root position — this table assigns layers, and tidying placement here would make `reverse` land the file where it never was |
| `state/verified-citations.json` | `config/scholar/` | ⑤(b) fails — **stays tracked**, approval item |
| `wiki/{convention,decision,pattern,reference,history}/` · `wiki/INDEX.md` · `wiki/README.md` | `community/wiki/` **(staging only)** | ② — **the wiki FORM is retired (r7, 2026-08-30); this row is the file MOVE, which cannot retire it.** `migrate-om-store.sh` moves files and cannot mint the per-page `subject:`/`id:` a post needs, so raw pages still land in `community/wiki/`. That directory is now a **staging state with a single exit**: run omo's `skills/harness/convert-wiki-form.py` (`plan` then `apply`) immediately after, which converts the pages into `community/posts/` and `git rm`s them. An anchor is not finished migrating while `community/wiki/` still has pages in it. `INDEX.md`/`README.md` live *inside* `wiki/`, not at the store root (measured, workspace `.oms`); the converter drops **root-level** ones (`hq index` regenerates the first, the second documents a retired form) and converts nested ones, which are real pages. `history/` had no `topic:` until r7 added one |
| `<slug>/{versions,renders,research,outline,figure_survey,tmp,gen-image,methodology}/` | `work/scholar/<slug>/` | ④ |
| `<slug>/*.md` skeletons · `PATHS.md` · `*_PROMPT.md` · `DECISIONS_NEEDED.md` | `work/scholar/<slug>/` | ④ — per-run scaffolding |
| `_backport-design/` | `community/` | ② |

`omd` store:

| Path | Layer | Rule |
|:---|:---|:---|
| `learned.md` | `config/docs/` | ③ |
| `<slug>/{build,renders,versions,assets,verify-runs,archive_*}/` | `work/docs/<slug>/` | ④ |
| `<slug>/{OUTLINE,SCRIPT,SPEAKER_NOTES,RESUME,RESTART_PROMPT,build-notes}.md` | `work/docs/<slug>/` | ④ |
| `<slug>/spec/` | `work/docs/<slug>/` | ④ |
| `wiki/{convention,pattern,technique}/` | `community/wiki/` **(staging only)** | ② — **the wiki FORM is retired (r7, 2026-08-30); this row is the file MOVE, which cannot retire it.** `migrate-om-store.sh` moves files and cannot mint the per-page `subject:`/`id:` a post needs, so raw pages still land in `community/wiki/`. That directory is now a **staging state with a single exit**: run omo's `skills/harness/convert-wiki-form.py` (`plan` then `apply`) immediately after, which converts the pages into `community/posts/` and `git rm`s them. An anchor is not finished migrating while `community/wiki/` still has pages in it; **added P5**: absent from this table until workspace's `.omd` was censused. `technique/` was not in omd's own `lint_wiki.CATEGORIES` while this row listed it — the linter and this table disagreed about the store's own shape — and it had no `topic:` until r7 added one |
| `.hook-throttle.json` | `runtime/docs/` | ⑤ |
| `HANDOFF_omd_audit.md` | `community/posts/` | ② — becomes a `handoff/` post |

`omha` store:

| Path | Layer | Rule |
|:---|:---|:---|
| `routing.jsonl` | `runtime/routing/` | ⑤ |
| `redact-patterns.txt` | `runtime/routing/` | ① — personal strings |
| `redact-patterns.example.txt` | `config/routing/` | ③ — the shipped schema example |

`omo` store (`.orchestration`):

| Path | Layer | Rule |
|:---|:---|:---|
| `HUB.md` · `INDEX.md` · `posts/` · `agents/` · `sessions/` · `rules/` | `community/` | ② — ids unchanged. **`INDEX.md` added P5**: both live boards carry one |
| `knowledge/{libraries,research}/` | `community/knowledge/` | ② — absorption into `posts/` (§4) is the P6 *form* change, same deferral as `wiki/`. Merging into `posts/` now would also make the reverse mapping ambiguous |
| `.hq-lock` | **not moved** | `hq`'s write lock (`hq/store.py:156`), recreated on demand (**added P5**) |
| `board.json` | `runtime/` | ③⑤ tie, ⑤ wins |
| `harness-progress.txt` | `runtime/` | ⑤ — **kept**, see §11 |
| `.omc/logs/` | **not moved** | third-party (`OMC_STATE_DIR`), out of scope |

`omx` store (**added P7** — until then this row read "deferred to P7 by the campaign
gate", and that deferral was the assignment):

| Path | Layer | Rule |
|:---|:---|:---|
| `profile/*` | `config/experiments/profile/` | ③ — `evaluator.sh`, `metrics.yaml`, `rules.md`, `launch.sh`, `seal.json`, `tree.yaml`; hand-tuned and read by verbs |
| `programs/<id>/program.json` | `config/experiments/programs/<id>/` | ③ — `campaign.py:305,346` reads it |
| `programs/<id>/PLAN.md` · `HANDOFF.md` | `community/programs/<id>/` | ② — templates seed them, humans write them; `campaign.py:360` only tests `.is_file()`. **The directory is split per file**, which is why §3's tree no longer lists `programs/` under `work/`: `**/.hq/work/` is gitignored, so sending the bundle whole would have untracked albc's plan of record (`finding/018`) |
| `registry/findings/*.md` | `community/wiki/` **(staging only)** | ② — same class as the three `wiki/` rows above and staged the same way, with one caveat: `convert-wiki-form.py` reads `<store>/community/wiki/` and nothing else, so these have to be moved there by this migration before it can see them. `omx wiki` used to lint them; that engine went in r6, and `omp_content_audit.py`'s wiki clause goes in r7's sibling release (in flight at the time this row was written — check `omp_content_audit.lint_wiki` before citing it as gone). ③ is for content a program consumes as input, not for content a linter audits |
| `registry/index.md` | `community/wiki/index.md` **(staging only)** | ② — moved like the row above, then **dropped by the converter**, which treats a root-level `index.md`/`INDEX.md`/`README.md` as tool-generated (`hq index` writes `community/INDEX.md` in its place). ⚠️ the case-collision this row flagged (an oms `wiki/INDEX.md` in the same anchor on a case-insensitive filesystem) is real only during the staging window, and both files are dropped at the end of it |
| `registry/log.md` | `runtime/experiments/registry/` | ⑤ — chronicles wiki *operations* (`add`, `query`), not the knowledge; the pages are the record. **`detrack` approval item** — albc's is tracked today |
| `registry/.wiki-lock` · `state/.state-lock` · `runs/<id>/.loop-lock` | **not moved** | mutex files recreated on demand, same call as `.hq-lock` |
| `recipes/*.md` | `community/recipes/` | ② — promoted diagnostic checklists a human reads before diagnosis |
| `state.json` | `runtime/experiments/state.json` | ③⑤ tie, ⑤ wins — same call as omo's `board.json` |
| `state/produced-reports.jsonl` | `config/experiments/produced-reports.jsonl` | ⑤(b) fails — a gate ledger, loss costs a re-stamp |
| `scratch/<session_id>/` | `runtime/experiments/scratch/<session_id>/` | ⑤ — session-bound by construction |
| `.trash/` | `runtime/experiments/trash/` | ⑤ — `omx clean`'s holding area. **Absent from every censused store**; surfaced by the P7 prose audit, which found `clean.py` resolving it as `paths.omx_dir / ".trash"` unconditionally. It has to move: left at the legacy path, the first `omx clean` after a `--purge` recreates `.omx/` and undoes the purge |
| `runs/<run_id>/` · `campaigns/<id>/` | `work/experiments/{runs,campaigns}/` | ④ — **whole, not split.** No censused store has either directory, so a per-file split inside them would be invented rather than measured; deferred the way omp's `env/` and omd's `wiki/` were |
| `.omx/` (the nested self-directory, §9.1 row 5) | `runtime/experiments/nested-omx/` | one real file, a wiki log written by a misrooted `--root .../.omx` call. Mapped rather than skipped (skipping loses it at `--purge`) and rather than made its own anchor (§2's granularity rule does not describe an anchor inside another store) |

### 9.4 `.gitignore` amendments per repo

Every repo gets the two `**/.hq/` lines. Legacy lines stay until that harness's
fallback-removal release — reached, as of 2026-08-28, for all six: `oms` removed
`.oms/`, `omd` removed `.omd/`, `omha` removed `.omha/redact-patterns.txt`, `omx`
removed `.omx/` (with an explanatory comment left in its place), `omp` never had
a legacy ignore line of its own to remove (the table's `.omp/*` line below
belongs to `claudebase`, not to `oh-my-project`), `omo` has none. Independently
verified per repo (not taken on report) with `grep -n '\.omp\|\.oms\|\.omd\|\.omx\|\.omha'
.gitignore` against each of the five sibling checkouts on this machine.

Outstanding, and this is **not** the same as the removals above — these come
after `--purge` (§7 stage 3), which has not run on this machine: `claudebase`'s
own `.omp/*` + `!.omp/rules.json` and `**/.orchestration/.hq-lock`, and the
vault's `.omp/work/` · `.omp/state/` · `.omha/` · `**/.orchestration/.hq-lock`.
No file has been deleted anywhere in this campaign; only ignore lines for
already-migrated, still-present legacy directories have been dropped.

| Repo | Legacy lines today | Note |
|:---|:---|:---|
| `ksm_Obsidian` | `.omp/work/` · `.omp/state/` · `.omha/` · `.sp/` · `.omc/` · `**/.omc/` | `.sp` and `.omc` are third-party, untouched |
| `claudebase` | `.omp/*` + `!.omp/rules.json` · `.omc/` | also updates `GATEGUARD_EXEMPT_GLOBS` and `.omp/rules.json` |
| `oh-my-docs` | `.omd/` | `policy-shift` — `learned.md` becomes tracked |
| `oh-my-scholar` | `.oms/` | `policy-shift` — `learned.md` becomes tracked |
| `oh-my-experiments` | `.omx/` · `.omc/` | `policy-shift`; P7 |
| `oh-my-heroacademia` | `.omc/` · `.omha/redact-patterns.txt` | the pattern file is absorbed by `**/.hq/runtime/` |
| `oh-my-project` | `.sp/` · `.omp-buildout.workflow.js` | no own store; two new lines only |
| `oh-my-orchestrator` | `.omc/` | no own store; two new lines only |

### 9.5 The root string is declared in seven places

Renaming `.hq` later costs five releases plus a `claudebase` sync. The declarations:

| # | Where | What |
|:---|:---|:---|
| 1–5 | `omp` · `oms` · `omd` · `omx` · `omha` paths module (one each) | the literal, plus a re-entry lint |
| 6 | `claudebase` `config/settings.json:4` `GATEGUARD_EXEMPT_GLOBS` | deployed to `~/.claude/settings.json` |
| 7 | `claudebase` `runtime/bin/migrate-om-store.sh` `HQ=` | the migration tool; a `claudebase` sync, not a release |

Number 6 is not optional and not late. Its matcher is `Edit|Write|MultiEdit|Bash`, so
**without the exemption the very first write to a `.hq/` path is refused by gateguard's
first-edit gate** — including the migration script's own writes. The trigger is the
first new-path write, which happens in the P3 pilot, not at the cutover release.

---

## 10. Expected machines per anchor

Reference material for the §7 fallback-removal judgment. **Only `ksm-mac` was observed
directly; every other row is unverified from here and must be confirmed on that machine
before it is used to justify a purge.**

| Anchor group | Expected machines | Verified? |
|:---|:---|:---|
| `ksm_Obsidian/**` | `ksm-mac`; other clones unknown | ksm-mac only |
| `workspace/**` | every machine on this iCloud account | **no** |
| `claudebase/**` | every machine (it is the deployment repo) | **no** |
| `oh-my-*` repos | development machine(s); consumers get the plugin cache, not the store | ksm-mac only |

---

## 11. `harness-progress.txt` — kept

Physical instances on this machine: **one**, and it is test scratch
(`.phase0-scratch/test-live/`). That looked like a dead file. It is not:
`harness-stop.py:281` resolves `root / "harness-progress.txt"` and `:87` counts `ERROR`
lines per task id from it, and `SKILL.md` documents it across 14 sites (§Progress
Persistence, the 3-strike escalation at `:343`, the log-format greps at `:462-467`,
`/harness init` at `:488`).

Zero instances means no long-running harness session has run on this machine — not that
the code path is dead. **Kept, in `runtime/`** (⑤: an append-only log, both conditions
hold).

---

## 12. What this spec does not cover

- **Cross-model enforcement.** Hooks are Claude Code only. `codex` and `antigravity`
  workers follow this spec in advisory mode; nothing enforces it on their side.
- **`.omc/` and `.sp/`.** Third-party. `.omc` is already centralized via
  `OMC_STATE_DIR` (`~/.claude/settings.json:9`); `.sp` is disposable scaffolding.
- **Split-brain on ignored layers and no-git anchors.** Undetectable by the drift
  instrument; `tar` hashes are the only partial cover (§8).

---

**Spec owner**: `oh-my-orchestrator` — `skills/harness/references/store-spec.md`
**Frozen**: 2026-08-27 (Phase 0)
**Amended**: 2026-08-28 (P5) — §7 names the shipped tool · §9.2 is patterns, not a count ·
§9.3 gains `omp env/`, `omd wiki/`, `omo INDEX.md`/`.hq-lock`, and corrects the `wiki/` and
`knowledge/` targets to what P3 shipped · §9.5 counts the tool as a seventh declaration site
**Amended**: 2026-08-28 (P6) — §9.3's `oms` table gains the store-root Workflow `.js` row,
found when the `12_Masters_Thesis` dry-run refused it (`finding/015`'s rule, applied); the
`venues/` and `workflows/` rows gain the sub-path the tool has always written, without which
the new row's contrast with `workflows/*.js` is unreadable
**Amended**: 2026-08-28 (omo §7 stage 2) — the top Status box, §6 row 2, and §9.4 now
describe the anchor-gated stage-2 rule instead of the P1-era existence fallback; omo's own
`hq/store.py:community_dir()` and `_harness_common.py`'s `board_path()`/`agent_memory_md()`/
`hub_md()` were the last legacy-only resolvers in this repo and are now anchor-gated to
match. Cross-checked against the other five harnesses' own `*_paths.py` docstrings rather
than assumed: `omp`/`omd`/`omx`/`omha` confirm stage 2 shipped; `oms` does not — its
`hooks/oms_paths.py` docstring still describes stage-1 per-file existence fallback as of its
0.19.0 release, so this amendment reports five of six, not all six
**Amended**: 2026-08-28 (correction, same day) — the "five of six" line above was a
mid-edit read: `oms` had a sibling agent landing its own stage-2 release in the same
working tree while it was being checked. Re-read `~/oh-my-scholar/hooks/oms_paths.py`
directly at its current 0.20.0 state (not on report) and confirmed: "Stage 2 (store-spec
§7) removes that per-file read fallback. Reads and writes now resolve identically." All
six harnesses ship stage 2 in this round — `omp` 0.16.0, `oms` 0.20.0, `omd` 0.11.0, `omx`
0.14.0, `omha` 0.10.0, `omo` 0.8.0 — none pushed yet. The top Status box and §9.4 are
updated to match; `hq/anchor.py:141`'s `gate_state()` corrupt-board check had the same
legacy-only shape as the two P7 fixes above (checked `.orchestration/board.json`
unconditionally even once anchored) and is now anchor-gated too, via a new
`hq_board_json()` in `hq/paths.py`
**Amended**: 2026-08-28 (§5 correction) — "do not remove the legacy lines yet" was
correct on 08-27 and is false now that all six harnesses have shipped their
fallback-removal release: the per-harness lines are gone (§9.4), and the "needs
approval" framing on the three-repo tracked/ignored shift is resolved (shipped, not
pending). §5 now describes the current state — done vs. outstanding-until-`--purge` —
instead of a still-open instruction five other repos' next sessions would otherwise
read and wrongly obey
**Supersedes**: `campaign-protocol.md` §Layout and its owning-store table ·
`omo/references/shared-context.md` §Layout — those sections now point here.

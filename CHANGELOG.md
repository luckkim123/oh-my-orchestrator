# Changelog

All notable changes to this project will be documented in this file.

## [0.13.0] - 2026-08-29 — a status nobody could move is not a status

### Added
- **`hq edit --status <value>`** (`skills/harness/hq/`). Until now a post's
  `status:` was whatever `hq post` stamped at birth and **no verb could move it** —
  `hq query --status needs-experiment` existed on the read side with nothing on the
  write side, so a lead that closed stayed open on the board forever. Measured on the
  live store: 121 posts, **113 at `status: none`**, 4 `needs-experiment`, 3 `resolved`,
  2 `needs-apply-before-retrain`. That skew is not what the world looks like; it is what
  a field that cannot be updated looks like. This is B1 of the hq-engine-consolidation
  plan and the prerequisite for B2 ranking, which cannot weight a field nobody maintains.

  Adopted as a flag on `edit` rather than a new `hq status` verb or a forced supersede:
  `--summary` already sits in that position, forcing supersede would mint a new post per
  status change, and a new verb grows the surface for nothing.

- **`--body-file` is now optional on `hq edit`.** A field-only edit had no way to supply
  it: `hq query --post-id` returns fields and **never the body**, so requiring it would
  have forced the caller to hand-extract markdown — precisely the raw-file editing these
  verbs exist to replace. An edit passing none of `--body-file`/`--summary`/`--status` is
  refused rather than appending a comment and changing nothing.

### Fixed
- **`hq edit --summary` silently truncated any summary containing ` · `.**
  `set_summary_in_raw` split the bullet on ` · ` and replaced only the matching
  *segment*, but `summary:` is a `REST_OF_LINE_KEYS` field — the parser reads
  `- summary: A · B` as one value. Replacing segment 0 left `- summary: <new> · B`, and
  the reparse read the old tail glued onto the new summary. Exit 0, lint clean, no
  warning anywhere. **12 of 121 live posts carry a ` · ` inside `summary:`** and every
  one of them was exposed.

  The fix is in the generalized `set_field_in_raw(post, key, value)` that `--status`
  needed anyway: a REST_OF_LINE key now takes its own segment **and every segment after
  it** (`segs[j:] = [...]`), a normal key still takes only its own — which is what
  `status:` requires, since it shares a bullet with `confidence:`. One mutator, both
  callers, the bug fixed where all callers route through.

- **The raw-line mutator resolved a different occurrence than the parser does** — four
  ways, each writing wrong bytes at **exit 0**. Found by handing the first version of
  this diff to codex with "attack it, do not write a patch"; six judgments went in, it
  rejected five, and four were real. The author could not see them.

  1. **A `REST_OF_LINE` value hides a later key.** `parse_bullet_line` stops at
     `summary:` — `- summary: A · status: none` contains *no* status field. The mutator
     scanned past it, rewrote the prose (`A · status: resolved`) and left the real
     `status:` on the next line untouched, reporting `{"edited": true}`.
  2. **A repeated key resolves to the last one** (dict assignment), and the mutator took
     the first, so the effective value never moved.
  3. **Keys are lowercased on parse**, so `Status:` *is* the status field; the
     case-sensitive scan called it absent and refused a legitimate edit.
  4. **A newline in a value forges a frontmatter bullet.**
     `hq edit --summary $'safe\n- status: hacked'` wrote `status: hacked` straight past
     the `STATUSES` gate — validating one field is worthless while another can forge it.
     Values containing a newline are now refused.

  The scan now walks every bullet, keeps the **last** case-insensitive match, and breaks
  at a `REST_OF_LINE` key exactly where the parser does.

- **`post.py`'s module docstring claimed `edit()` never touches frontmatter.** It has
  been false since `--summary` landed and would have been false again for `--status`.
  A stale invariant in the file that documents the invariant is worse than none.

### Verification
- `python3 -m unittest tests.test_hq tests.test_hooks tests.test_paths_lint` — **162/162**.
  Twelve new. Seven for the verb: status round-trips *through the file* (re-parsed from disk, not from the
  in-memory Post — a fixture that inspects only the object is green while the file never
  changed), the `confidence:` line-mate survives, the body survives a status-only edit,
  an unknown status is refused, an edit that changes nothing is refused, a no-git anchor
  still redirects to supersede, and a summary with separators is replaced whole.
- **End-to-end against a copy of the live vault store** (121 real posts), via `bin/hq`:
  `hq --json edit finding/121 --status resolved` → the raw line moved
  `- confidence: high · status: none` → `· status: resolved`, `hq query --post-id`
  reparsed `resolved`, `confidence` and the 183-char summary intact, `hq lint` clean, and
  `diff` against the original showed **exactly two changed lines** — the status value and
  the audit comment. On `finding/109` (a real post with ` · ` in its summary) an
  `--summary` edit now replaces the value whole instead of gluing on the old tail, and
  `--summary $'x\n- status: hacked'` exits **1** where it previously exited 0 having
  written `status: hacked`.

### Notes
- **`--status` does not open a write path on a no-git anchor.** `edit` still refuses
  there and redirects to supersede — without git there is no copy of the old body. B2's
  ranking design must not assume otherwise.
- A `--status`-only edit does **not** reindex: `INDEX.md` renders id, subject, title and
  summary, and no status. `--summary` still does.
- **A legacy post with no `status:` line cannot be repaired through this verb** — it
  refuses loudly rather than inserting one. Measured: 0 such posts across all four
  anchors on this machine, and `hq lint` already reports one as pre-schema. Loud is the
  point; the silent version of this was defect 1 above.
- Three weaknesses the same attack surfaced that **predate this diff and are not fixed
  here**, recorded so the next round does not rediscover them: `_is_git_anchor` accepts
  an empty or malformed `.git/` (`git rev-parse` exits 128 and the gate still opens);
  `lint`'s index-drift check compares id sets, not rendered summaries; and the parser
  drops non-bullet text between `## Comments` and the first `- ` entry, which a
  field-only edit would then persist. The last is not reachable on either live store —
  the mandatory round-trip tests over the real vault and claudebase posts both pass.

## [0.12.0] - 2026-08-29 — the vendor lane could not change vendors, and nobody could see it

### Fixed
- **`--backend <other>` no longer carries the role's model across vendors**
  (`codeagent-wrapper/internal/adapter/cli/parse.go`). The backend and the model
  were settled by two switches that did not know about each other: `--backend`
  moved the call to codex, and the model switch then took the *role card's* model
  because `--model` was absent. So `--agent oracle --backend codex` built
  `codex e --model claude-opus-5 …` and died with **HTTP 400, exit 1, 14s** — the
  exact invocation omo's own `SKILL.md` prescribes for the adversarial-review
  ground ("override with `--backend codex` and no `--model`"). The documentation
  was not wrong; the behaviour it described did not exist.

  The new branch fires only when a role is in play, `--backend` was passed, and
  the effective backend differs from the role's own, and it sets the model to the
  empty string. Empty is the correct value rather than a fallback: every backend
  appends `--model` only when it is non-empty (`codex.go:55`, and the same shape
  in `gemini.go`, `agy.go`, `opencode.go`), so the vendor CLI picks its own
  default. Declaring `--agent` *after* `--backend` is unaffected — the later
  `--agent` wins the backend too, so nothing mismatches and the role keeps its
  model.

  **The `agy` case is the one that mattered most and showed least.** Codex
  answered a wrong model name with a 400. `agy` answered with a completed run at
  the wrong model and no error anywhere, which silently defeats the reason the
  override exists: a judge that did not author the work.

  Four table-driven cases pin it in `internal/app/main_test.go`
  (`TestBackendParseArgs_BackendSwitchDoesNotInheritRoleModel`) — switch drops the
  model, no switch keeps it, explicit `--model` still wins, `--agent` last keeps it.

### Added
- **`bin/omo-consult` — a vendor consultation you can watch.** The wrapper has
  zero lines of tmux/pane code, so a consultation was an invisible child process
  and the only observable was whatever the session pasted back. This is a thin
  POSIX-sh launcher (no Go change) that runs the same call in a panel: an Orca tab
  when `orca worktree current` succeeds, a detached `tmux split-window -d` when
  `$TMUX` is set, and the current foreground behaviour otherwise. Forced with
  `--surface`.

  All three surfaces `tee` to the **same** output file and the launcher prints its
  path, so the machine-side recovery path does not change — only the human-side
  surface is added. `--focus` is opt-in on every surface: a consultation must not
  steal focus from the work that asked for it.

  `orca worktree current`, not `command -v orca`, is the detection test. Orca can
  be installed while the current directory is not a registered worktree, and
  `terminal create --worktree active` fails there; measured in this repo, which is
  exactly that case, and the launcher fell through as designed.

### Changed
- `skills/omo/references/vendor-ops.md`: documents the backend-override behaviour
  above (including "if your build predates the fix, keep passing `--model`"), the
  new launcher, and the `--prompt-file` path restriction.

  That restriction is **narrower than it looks**, and what is written there is the
  measured version rather than the one first drafted: it binds the *role card's*
  `prompt_file`, which must resolve under `~/.claude` or `~/.codeagent/agents`; a
  path passed with `--prompt-file` or set in settings is flagged explicit and is
  not restricted at all. And a refusal is a hard error
  (`failed to read prompt file: …`), not a fallback to stdin
  (`internal/app/app.go:91`, `internal/app/task_runtime_adapter.go:73`).

### Notes
- **The Go fix does not ship with this version bump.** The plugin cache carries
  `codeagent-wrapper/` as *source*; the binary that actually runs is whatever sits
  on `PATH`. Updating the plugin gets you the launcher, the docs and the source —
  the fixed behaviour requires `make build` in `codeagent-wrapper/` and putting the
  result on `PATH`. Verified here by hash: the pre-existing
  `~/.local/bin/codeagent-wrapper` differed from a fresh build before it was
  replaced.

## [0.11.0] - 2026-08-29 — a correction that cannot reach the summary is not a correction

### Added
- **`hq edit --summary`.** `edit` replaced the body and appended a `정정:` comment,
  but had no way to touch `summary:` — the one field `INDEX.md` and `hq query`
  actually show. A corrected post therefore kept advertising the claim it had just
  been corrected for, which is the exact failure the "fix the body, fix its summary
  in the same edit" rule exists to stop, made unenforceable by the tool.

  Found within an hour of shipping `community`, by needing it: `finding/117` had
  miscounted open backlog leads and the number was in both the body and the summary.

  The fix needed a second layer. `serialize_post` echoes a parsed post's
  `raw_prefix_lines` verbatim — the round-trip fidelity guarantee — so assigning
  `post.fields["summary"]` was silently discarded. `post.set_summary_in_raw()` now
  rewrites the summary segment of its own bullet and leaves every other line, and
  every other segment of that line, byte-identical. `edit` also reindexes when the
  summary changes; it did not touch the index before, which was safe only while
  nothing it could change was indexed.

## [0.10.0] - 2026-08-29 — the board gets a front door

### Added
- **`skills/community` — the board's operating surface, as its own skill.** Reading
  before deciding, posting what was settled, commenting on someone else's record,
  and correcting one that is wrong. Category choice, subject chains, and the rule
  that nothing here is deleted.

  It replaces the wiki rather than sitting beside it. A wiki page was a state and a
  post is an event; the merge kept both — the page's taxonomy became `topic:`, its
  staleness banner became `verified:`, and "what is true now" became the head of a
  `subject:` chain. Measured the same day: `.hq/community/wiki/` holds **0 files on
  all seven stores** on this machine, while the posts hold 116 (vault) and 17
  (claudebase). There was no data to migrate — only a missing front door.

  The extraction is also what makes the rules reachable by a vendor worker.
  `omo/references/vendor-ops.md` measures `harness/SKILL.md` at 28,261 characters,
  1.8x the whole `--skills` budget, so the board's rules could never be passed to
  one. The `community` card is under 6,000 and fits.

### Fixed
- **`hq post` produced a post its own `hq lint` warned about.** `Post.is_legacy`
  reads a missing `verified:` as pre-schema, and `post_new` wrote the field only
  when `--verified` was given — so every post created through the supported writer
  without that flag was flagged `legacy-schema` the moment it was written. It now
  writes `verified: none`, the same explicit-absence idiom `supersedes`, `status`,
  and `confidence` already use, and which all 116 live vault posts already carry.

  Found by running the new skill's own documented examples against a fresh anchor
  rather than by a failing test. The live stores never hit it: their posts were
  either filled by the migration script or written with `--verified` by hand.

### Changed
- `harness/SKILL.md`'s `## The hq store CLI` section is now a pointer. The verb
  table, flags, and usage rules live in `community`; the design SSOT
  (`references/store-spec.md`) stays with `harness`.

## [0.9.1] - 2026-08-29 — the index drifts everywhere the verbs are not

### Added
- **`hq lint` now fails on index drift.** It compares the post ids on disk with
  the ids listed in `INDEX.md` and reports both directions — posts present but
  unlisted, and listed posts that no longer exist.

  `hq post` has always regenerated the index inside the write lock, so the verb
  path never drifted. Everything else does: a post written by heredoc, a rename,
  a `git rm`, a migration script. None of those pass through a verb, so no verb
  can catch them, and the failure is the silent kind this store keeps recording —
  `hq query` simply does not return the missing post, with no error anywhere.
  Lint already reads every post, so the comparison is nearly free there and
  nowhere else. `comment` and `edit` deliberately do **not** reindex: `INDEX.md`
  carries id, subject, title and summary, none of which either verb touches.

### Fixed
- `skills/omo/SKILL.md` preflight now checks `codeagent-wrapper` itself, not only
  the role backends. The wrapper ships as Go source rather than a published
  artifact, so a machine that never ran `make build` has no vendor lane at all
  while every backend check passes — which is exactly how one machine passed the
  preflight with no entry point installed.
- `.claude-plugin/plugin.json` description named `.orchestration/`, retired by the
  `.hq/` cutover. It is the marketplace line a user reads before installing.

## [0.9.0] - 2026-08-29

### Changed
- **`store-spec.md` §2 reverses its own granularity rule.** It said the anchor
  belongs at "the project's folder, not the repo root" and defended nesting
  outright — *"Nesting is legitimate, not a mistake to clean up."* It now says
  **one anchor per git repository, at its root**, with projects separated by the
  `project:` field. The old argument was internally sound (ascent shadows an
  inner store unambiguously; per-anchor numbering avoids id collisions) and
  still beside the point: **ascent only walks up**, so two sibling projects in
  one repo are invisible to each other by construction. Measured on `ksm-mac`
  the day of the decision — four sibling anchors in one repo, 114 posts,
  **zero** citations had ever crossed an anchor. That is the same shape as the
  two capabilities this ecosystem already retired for going unrouted
  (`tokensave` 6 calls / 10,813; `graphify`'s MCP server 0 / 30 days), and an
  option flag is not an answer to it. `workspace`'s three-deep chain is now
  recorded as **debt against the rule, not an exception to it** — the user
  deferred it, and it is not a git repository, so the merge procedure does not
  transfer unchanged.
- `campaign-protocol.md` restated the old rule in its pointer to §2; corrected
  in the same pass rather than left to drift.
- `store-spec.md` §9's mapping table carries a banner: its anchor column is a
  2026-08-27 snapshot and four of its rows no longer exist. The per-file *layer*
  assignments are unaffected — they say which layer a file belongs to, not which
  anchor owns it.

### Added
- **`project:` in the §4 post schema**, and `hq query --project` / `hq post
  --project` to write and read it. `project:` and `harness:` are two independent
  axes; with no filter, `query` still returns everything, because invisibility
  was the failure the §2 change fixed.
- **`confidence: none`.** The value set was `high|medium|low`, which left no way
  to say "this post predates the field" — the only honest options were to
  fabricate a confidence or to leave the post permanently `legacy-schema`.
  `none` is the absence of an assessment, the same way `status: none` and
  `supersedes: none` already read. Do not use it for a post whose author did judge.
- `agy` backend (D24), from the previous session's `3e3aa78`: the registry is now
  `codex` · `claude` · `agy`. `gemini.go` and `opencode.go` are unregistered, not
  deleted — the user retired both (gemini CLI no longer authenticates on this
  machine; opencode unused), and agy is gemini's successor. Deleting the code is
  a separate ~80-line pass through parser, filter, and tests.

### Fixed
- **Round-trip lost a blank line under `## Comments`.** 12 live posts write one
  there; the parser dropped it and `serialize_post` never put it back, so any
  `hq comment` or `hq edit` on those posts silently reflowed the file. Now
  captured per post (`Post.comments_lead_blank`) and echoed back.
- **`test_hq.py`'s live-store paths were two moves stale** (`.orchestration/`,
  and the vault board's pre-merge location), and `RoundTripTest` skips silently
  when a path is wrong — so both of its cases had been passing by not running.
  Fixing the paths made the blank-line bug above visible immediately. Suite: 144
  passed, 0 skipped (was 139 + 2 skipped).

### Verification
- `python3.12 -m pytest skills/harness/tests/ -q` -> **144 passed, 0 skipped**.
- `go test ./...` in `codeagent-wrapper/` -> 19 packages ok.
- Applied end-to-end on the vault: four anchors merged into one, 114 posts,
  `hq index` errors 0, `hq lint` clean (WARN 0 including legacy-schema),
  `hq query --project` returns 77 / 30 / 5 / 2 and no filter returns 114.

### Notes
- The vault's own migration record — the renumbering map, the reference-rewrite
  traps, and the `config/project/` collision that has no field-based answer — is
  in that store's `handoff/107`, not here. This repo owns the spec; the project
  owns its own history.

## [0.8.1] - 2026-08-28

### Changed
- `store-spec.md` §9.3 — a note under the `omp` table records that the deferred
  §4 form conversion **was executed for one tree**: the vault's three anchors
  (`vault`, `vault-albc`, `vault-krit-simulator`), 16 pages, by hand into
  `posts/` under the five reader-intent categories. The `community/wiki/` target
  in the table is unchanged and still correct — `migrate-om-store.sh` moves
  files and cannot mint the per-page `subject:` the form needs, so conversion is
  a second manual pass over an already-migrated anchor, not a remapping. The
  `oms` row already said "same deferral as omp's row above" and inherits the
  note. Measurements from that pass (field mapping per source form, dropped
  fields, and why `verified:` cannot be derived from git in a migrated tree) are
  in the vault harness board's `finding/021`.
- The status banner's stage-3 paragraph said `--purge` had not run and every
  legacy store on `ksm-mac` was still on disk. It ran on 2026-08-28 — 20 stores
  deleted, `census` reports `in scope: 0`. The plugin-cache precondition the
  paragraph named did hold and is kept; the per-anchor decision now reads as
  what it is on *other* machines.

## [0.8.0] - 2026-08-28

> This is the first `0.x` entry in this file — recent `0.4.0`–`0.7.2` plugin
> releases were versioned in `.claude-plugin/plugin.json` and commit
> messages only, without a CHANGELOG entry. This file's numbering above is a
> separate, older product line (`codeagent`/install-wrapper) that stopped
> being updated well before the `omo`/harness plugin split; the two version
> lines are unrelated.

### 🚀 Features

- feat(store): om\* store unification P7 — `oh-my-orchestrator` (harness slot
  `omo`) ships `store-spec.md` §7 stage 2, fallback removal. A project with a
  parseable `.hq/.anchor` now resolves reads and writes to `.hq/` only, in
  both directions, with no existence-based fallback to `.orchestration/`; a
  project without an anchor keeps resolving to `.orchestration/` exactly as
  before.

### 🐛 Bug Fixes

- fix(hooks): `_harness_common.py`'s `agent_memory_md()` and `hub_md()`
  resolved to `.orchestration/` unconditionally — no `.hq/` path at all, even
  on an anchored project. Both are now anchor-gated like every other
  resolver in this repo.
- fix(store): `hq/store.py`'s `community_dir()` was existence-gated (`.hq/
  community` wins only if the directory already exists), which left an
  anchored-but-not-yet-copied project split-brained between the two stores.
  Now anchor-gated per store-spec §7 stage 2.
- fix(anchor): `hq/anchor.py`'s `gate_state()` corrupt-board check read
  `.orchestration/board.json` unconditionally, even once an anchor existed —
  the same legacy-only shape as the two fixes above, found after the first
  round shipped. A corrupt `.hq/runtime/board.json` on an anchored project
  could never trip `GATE_CORRUPT`. Anchor-gated via a new `hq_board_json()`
  in `hq/paths.py`; a corrupt legacy board.json is now correctly *not*
  examined once anchored (`GateStateTest` covers both directions). Widened
  the resolver audit to all of `skills/harness/` (not just the two files the
  first round scoped) by grepping `legacy_root(`/`LEGACY_ROOT`/
  `legacy_board_json(`/`has_legacy_store(` across the whole tree and reading
  every hit — this is how `gate_state()` was found. Nothing else turned up a
  fourth instance: every remaining hit is either root *discovery* (which
  must keep finding both `.hq/` and legacy markers — `find_harness_root()`,
  `find_anchor_root()`, `_resolve_anchor_roots_for_query()` — untouched by
  design), a `/tmp`-hash lock file or session-tempdir counter unrelated to
  the store split, or `Post.is_legacy` (a *schema*-legacy check on missing
  post fields, an unrelated meaning of "legacy" that happens to share the
  word). One docstring staleness found in passing outside that grep's scope
  (`hq/verbs.py`'s `_resolve_anchor_roots_for_query`, a stale "today's
  reality for both P1 target stores" parenthetical) corrected for accuracy.
- fix(hooks): swept every hook-injected string and docstring naming
  `.orchestration/` literally — `harness-subagentstart.py`'s "what this role
  has learned" notice, `harness-subagentstop.py`'s "land the post under"
  failure message, and `self-reflect-stop.py`'s knowledge-mining checklist —
  to resolve dynamically via `agent_memory_md()`/`community_posts_dir()`/
  `knowledge_dir()`/`hub_md()` (`community_posts_dir()` and `knowledge_dir()`
  new in `_harness_common.py`). Left untouched: `LEGACY_ROOT = ".orchestration"`
  itself and every string genuinely about the unmigrated-legacy-store case
  (SKILL.md's `harness-tasks.json`→`board.json` migration note, the CLI's
  dual-ascent doc). Also corrected six identical stale `find_harness_root()`
  wrapper docstrings (named only the legacy marker; the function has checked
  `.hq/runtime/board.json` first since P6) and two `SKILL.md` passages
  describing the pre-stage-2 existence-fallback algorithm.

### 📚 Documentation

- docs(store-spec): the top Status box, §6 row 2, and §9.4 now describe the
  anchor-gated stage-2 rule instead of the P1-era existence fallback. First
  cross-check (against the other five harnesses' own `*_paths.py`
  docstrings) caught `oms` mid-edit and reported it as still stage 1;
  re-verified after `oms` landed its own 0.20.0 release in the same window —
  all six harnesses (`omp` 0.16.0, `oms` 0.20.0, `omd` 0.11.0, `omx` 0.14.0,
  `omha` 0.10.0, `omo` 0.8.0) ship stage 2 in this round, confirmed by
  reading each sibling repo's own source, not by count. §9.4 also now lists
  which repos have removed their legacy `.gitignore` lines (independently
  verified per repo, not taken on report) versus what is still outstanding
  for `--purge` (stage 3, not run anywhere on this machine). §5's "do not
  remove the legacy lines yet" was correct on 08-27 and was still shipping
  as of the first draft of this entry — now false with all six harnesses on
  stage 2, so it is rewritten to describe done (the per-harness lines) vs.
  outstanding-until-purge (claudebase's and the vault's, which host anchors
  for multiple harnesses); the "needs approval" framing on the three-repo
  tracked/ignored boundary shift is likewise resolved to "shipped."

## [6.7.0] - 2026-02-10

### 🚀 Features

- feat(install): per-module agent merge/unmerge for ~/.codeagent/models.json
- feat(install): post-install verification (wrapper version, PATH, backend CLIs)
- feat(install): install CLAUDE.md by default
- feat(docs): document 9 skills, 11 commands, claudekit module, OpenCode backend

### 🐛 Bug Fixes

- fix(docs): correct 7-phase → 5-phase for do skill across all docs
- fix(install): best-effort default config install (never crashes main flow)
- fix(install): interactive quit no longer triggers post-install actions
- fix(install): empty parent directory cleanup on copy_file uninstall
- fix(install): agent restore on uninstall when shared by multiple modules
- fix(docs): remove non-existent on-stop hook references

### 📚 Documentation

- Updated USER_GUIDE.md with 13 CLI flags and OpenCode backend
- Updated README.md/README_CN.md with complete module and skill listings
- Added templates/models.json.example with all agent presets (do + omo)

## [6.6.0] - 2026-02-10

### 🚀 Features

- feat(skills): add per-task skill spec auto-detection and injection
- feat: add worktree support and refactor do skill to Python

### 🐛 Bug Fixes

- fix(test): set USERPROFILE on Windows for skills tests
- fix(do): reuse worktree across phases via DO_WORKTREE_DIR env var
- fix(release): auto-generate release notes from git history

### 📚 Documentation

- audit and fix documentation, installation scripts, and default configuration

## [6.0.0] - 2026-01-26

### 🚀 Features

- support `npx github:stellarlinkco/myclaude` for installation and execution
- default module changed from `dev` to `do`

### 🚜 Refactor

- restructure: create `agents/` and move `bmad-agile-workflow` → `agents/bmad`, `requirements-driven-workflow` → `agents/requirements`, `development-essentials` → `agents/development-essentials`
- remove legacy directories: `docs/`, `hooks/`, `dev-workflow/`
- update references across `config.json`, `README.md`, `README_CN.md`, `marketplace.json`, etc.

### 📚 Documentation

- add `skills/README.md` and `PLUGIN_README.md`

### 💼 Other

- add `package.json` and `bin/cli.js` for npx packaging

## [6.1.5] - 2026-01-25


### 🐛 Bug Fixes


- correct gitignore to not exclude cmd/codeagent-wrapper

## [6.1.4] - 2026-01-25


### 🐛 Bug Fixes


- support concurrent tasks with unique state files

## [6.1.3] - 2026-01-25


### 🐛 Bug Fixes


- correct build path in release workflow

- increase stdoutDrainTimeout from 100ms to 500ms

## [6.1.2] - 2026-01-24


### 🐛 Bug Fixes


- use ANTHROPIC_AUTH_TOKEN for Claude CLI env injection

### 💼 Other


- update codeagent version

### 📚 Documentation


- restructure root READMEs with do as recommended workflow

- update do/omo/sparv module READMEs with detailed workflows

- add README for bmad and requirements modules

### 🧪 Testing


- use prefix match for version flag tests

## [6.1.1] - 2026-01-23


### 🚜 Refactor


- rename feature-dev to do workflow

## [6.1.0] - 2026-01-23


### ⚙️ Miscellaneous Tasks


- ignore references directory

- add go.work.sum for workspace dependencies

### 🐛 Bug Fixes


- read GEMINI_MODEL from ~/.gemini/.env ([#131](https://github.com/stellarlinkco/myclaude/issues/131))

- validate non-empty output message before printing

### 🚀 Features


- add feature-dev skill with 7-phase workflow

- support \${CLAUDE_PLUGIN_ROOT} variable in hooks config

## [6.0.0-alpha1] - 2026-01-20


### 🐛 Bug Fixes


- add missing cmd/codeagent/main.go entry point

- update release workflow build path for new directory structure

- write PATH config to both profile and rc files ([#128](https://github.com/stellarlinkco/myclaude/issues/128))

### 🚀 Features


- add course module with dev, product-requirements and test-cases skills

- add hooks management to install.py

### 🚜 Refactor


- restructure codebase to internal/ directory with modular architecture

## [5.6.7] - 2026-01-17


### 💼 Other


- remove .sparv

### 📚 Documentation


- update 'Agent Hierarchy' model for frontend-ui-ux-engineer and document-writer in README ([#127](https://github.com/stellarlinkco/myclaude/issues/127))

- update mappings for frontend-ui-ux-engineer and document-writer in README ([#126](https://github.com/stellarlinkco/myclaude/issues/126))

### 🚀 Features


- add sparv module and interactive plugin manager

- add sparv enhanced rules v1.1

- add sparv skill to claude-plugin v1.1.0

- feat sparv skill

## [5.6.6] - 2026-01-16


### 🐛 Bug Fixes


- remove extraneous dash arg for opencode stdin mode ([#124](https://github.com/stellarlinkco/myclaude/issues/124))

### 💼 Other


- update readme

## [5.6.5] - 2026-01-16


### 🐛 Bug Fixes


- correct default models for oracle and librarian agents ([#120](https://github.com/stellarlinkco/myclaude/issues/120))

### 🚀 Features


- feat dev skill

## [5.6.4] - 2026-01-15


### 🐛 Bug Fixes


- filter codex 0.84.0 stderr noise logs ([#122](https://github.com/stellarlinkco/myclaude/issues/122))

- filter codex stderr noise logs

## [5.6.3] - 2026-01-14


### ⚙️ Miscellaneous Tasks


- bump codeagent-wrapper version to 5.6.3

### 🐛 Bug Fixes


- update version tests to match 5.6.3

- use config override for codex reasoning effort

## [5.6.2] - 2026-01-14


### 🐛 Bug Fixes


- propagate SkipPermissions to parallel tasks ([#113](https://github.com/stellarlinkco/myclaude/issues/113))

- add timeout for Windows process termination

- reject dash as workdir parameter ([#118](https://github.com/stellarlinkco/myclaude/issues/118))

### 📚 Documentation


- add OmO workflow to README and fix plugin marketplace structure

### 🚜 Refactor


- remove sisyphus agent and unused code

## [5.6.1] - 2026-01-13


### 🐛 Bug Fixes


- add sleep in fake script to prevent CI race condition

- fix gemini env load

- fix omo

### 🚀 Features


- add reasoning effort config for codex backend

## [5.6.0] - 2026-01-13


### 📚 Documentation


- update FAQ for default bypass/skip-permissions behavior

### 🚀 Features


- default to skip-permissions and bypass-sandbox

- add omo module for multi-agent orchestration

### 🚜 Refactor


- streamline agent documentation and remove sisyphus

## [5.5.0] - 2026-01-12


### 🐛 Bug Fixes


- 修复 Gemini init 事件 session_id 未提取的问题 ([#111](https://github.com/stellarlinkco/myclaude/issues/111))

- fix codeagent skill TaskOutput

### 💼 Other


- Merge branch 'master' of github.com:stellarlinkco/myclaude

- add test-cases skill

- add browser skill

### 🚀 Features


- add multi-agent support with yolo mode

## [5.4.4] - 2026-01-08


### 💼 Other


- 修复 Windows 后端退出：taskkill 结束进程树 + turn.completed 支持 ([#108](https://github.com/stellarlinkco/myclaude/issues/108))

## [5.4.3] - 2026-01-06


### 🐛 Bug Fixes


- support model parameter for all backends, auto-inject from settings ([#105](https://github.com/stellarlinkco/myclaude/issues/105))

### 📚 Documentation


- add FAQ Q5 for permission/sandbox env vars

### 🚀 Features


- feat skill-install install script and security scan

- add uninstall scripts with selective module removal

## [5.4.2] - 2025-12-31


### 🐛 Bug Fixes


- replace setx with reg add to avoid 1024-char PATH truncation ([#101](https://github.com/stellarlinkco/myclaude/issues/101))

## [5.4.1] - 2025-12-26


### 🐛 Bug Fixes


- 移除未知事件格式的日志噪声 ([#96](https://github.com/stellarlinkco/myclaude/issues/96))

- prevent duplicate PATH entries on reinstall ([#95](https://github.com/stellarlinkco/myclaude/issues/95))

### 📚 Documentation


- 添加 FAQ 常见问题章节

- update troubleshooting with idempotent PATH commands ([#95](https://github.com/stellarlinkco/myclaude/issues/95))

### 🚀 Features


- Add intelligent backend selection based on task complexity ([#61](https://github.com/stellarlinkco/myclaude/issues/61))

## [5.4.0] - 2025-12-24


### 🐛 Bug Fixes


- Minor issues #12 and #13 - ASCII mode and performance optimization

- code review fixes for PR #94 - all critical and major issues resolved

### 🚀 Features


- v5.4.0 structured execution report ([#94](https://github.com/stellarlinkco/myclaude/issues/94))

## [5.2.8] - 2025-12-22


### ⚙️ Miscellaneous Tasks


- simplify release workflow to use GitHub auto-generated notes

### 🐛 Bug Fixes


- correct settings.json filename and bump version to v5.2.8

## [5.2.7] - 2025-12-21


### ⚙️ Miscellaneous Tasks


- bump version to v5.2.7

### 🐛 Bug Fixes


- allow claude backend to read env from setting.json while preventing recursion ([#92](https://github.com/stellarlinkco/myclaude/issues/92))

- comprehensive security and quality improvements for PR #85 & #87 ([#90](https://github.com/stellarlinkco/myclaude/issues/90))

- Parser重复解析优化 + 严重bug修复 + PR #86兼容性 ([#88](https://github.com/stellarlinkco/myclaude/issues/88))

### 💼 Other


- Improve backend termination after message and extend timeout ([#86](https://github.com/stellarlinkco/myclaude/issues/86))

### 🚀 Features


- add millisecond-precision timestamps to all log entries ([#91](https://github.com/stellarlinkco/myclaude/issues/91))

## [5.2.6] - 2025-12-19


### 🐛 Bug Fixes


- filter noisy stderr output from gemini backend ([#83](https://github.com/stellarlinkco/myclaude/issues/83))

- 修復 wsl install.sh 格式問題 ([#78](https://github.com/stellarlinkco/myclaude/issues/78))

### 💼 Other


- update all readme

- BMADh和Requirements-Driven支持根据语义生成对应的文档 ([#82](https://github.com/stellarlinkco/myclaude/issues/82))

## [5.2.5] - 2025-12-17


### 🐛 Bug Fixes


- 修复多 backend 并行日志 PID 混乱并移除包装格式 ([#74](https://github.com/stellarlinkco/myclaude/issues/74)) ([#76](https://github.com/stellarlinkco/myclaude/issues/76))

- replace "Codex" to "codeagent" in dev-plan-generator subagent

- 修復 win python install.py

### 💼 Other


- Merge pull request #71 from aliceric27/master

- Merge branch 'stellarlinkco:master' into master

- Merge pull request #72 from changxvv/master

- update changelog

- update codeagent skill backend select

## [5.2.4] - 2025-12-16


### ⚙️ Miscellaneous Tasks


- integrate git-cliff for automated changelog generation

- bump version to 5.2.4

### 🐛 Bug Fixes


- 防止 Claude backend 无限递归调用

- isolate log files per task in parallel mode

### 💼 Other


- Merge pull request #70 from stellarlinkco/fix/prevent-codeagent-infinite-recursion

- Merge pull request #69 from stellarlinkco/myclaude-master-20251215-073053-338465000

- update CHANGELOG.md

- Merge pull request #65 from stellarlinkco/fix/issue-64-buffer-overflow

## [5.2.3] - 2025-12-15


### 🐛 Bug Fixes


- 修复 bufio.Scanner token too long 错误 ([#64](https://github.com/stellarlinkco/myclaude/issues/64))

### 💼 Other


- change version

### 🧪 Testing


- 同步测试中的版本号至 5.2.3

## [5.2.2] - 2025-12-13


### ⚙️ Miscellaneous Tasks


- Bump version and clean up documentation

### 🐛 Bug Fixes


- fix codeagent backend claude no auto

- fix install.py dev fail

### 🧪 Testing


- Fix tests for ClaudeBackend default --dangerously-skip-permissions

## [5.2.1] - 2025-12-13


### 🐛 Bug Fixes


- fix codeagent claude and gemini root dir

### 💼 Other


- update readme

## [5.2.0] - 2025-12-13


### ⚙️ Miscellaneous Tasks


- Update CHANGELOG and remove deprecated test files

### 🐛 Bug Fixes


- fix race condition in stdout parsing

- add worker limit cap and remove legacy alias

- use -r flag for gemini backend resume

- clarify module list shows default state not enabled

- use -r flag for claude backend resume

- remove binary artifacts and improve error messages

- 异常退出时显示最近错误信息

- op_run_command 实时流式输出

- 修复权限标志逻辑和版本号测试

- 重构信号处理逻辑避免重复 nil 检查

- 移除 .claude 配置文件验证步骤

- 修复并行执行启动横幅重复打印问题

- 修复master合并后的编译和测试问题

### 💼 Other


- Merge rc/5.2 into master: v5.2.0 release improvements

- Merge pull request #53 from stellarlinkco/rc/5.2

- remove docs

- remove docs

- add prototype prompt skill

- add prd skill

- update memory claude

- remove command gh flow

- update license

- Merge branch 'master' into rc/5.2

- Merge pull request #52 from stellarlinkco/fix/parallel-log-path-on-startup

### 📚 Documentation


- remove GitHub workflow related content

### 🚀 Features


- Complete skills system integration and config cleanup

- Improve release notes and installation scripts

- 添加终端日志输出和 verbose 模式

- 完整多后端支持与安全优化

- 替换 Codex 为 codeagent 并添加 UI 自动检测

### 🚜 Refactor


- 调整文件命名和技能定义

### 🧪 Testing


- 添加 ExtractRecentErrors 单元测试

## [5.1.4] - 2025-12-09


### 🐛 Bug Fixes


- 任务启动时立即返回日志文件路径以支持实时调试

## [5.1.3] - 2025-12-08


### 🐛 Bug Fixes


- resolve CI timing race in TestFakeCmdInfra

## [5.1.2] - 2025-12-08


### 🐛 Bug Fixes


- 修复channel同步竞态条件和死锁问题

### 💼 Other


- Merge pull request #51 from stellarlinkco/fix/channel-sync-race-conditions

- change codex-wrapper version

## [5.1.1] - 2025-12-08


### 🐛 Bug Fixes


- 增强日志清理的安全性和可靠性

- resolve data race on forceKillDelay with atomic operations

### 💼 Other


- Merge pull request #49 from stellarlinkco/freespace8/master

- resolve signal handling conflict preserving testability and Windows support

### 🧪 Testing


- 补充测试覆盖提升至 89.3%

## [5.1.0] - 2025-12-07


### 💼 Other


- Merge pull request #45 from Michaelxwb/master

- 修改windows安装说明

- 修改打包脚本

- 支持windows系统的安装

- Merge pull request #1 from Michaelxwb/feature-win

- 支持window

### 🚀 Features


- 添加启动时清理日志的功能和--cleanup标志支持

- implement enterprise workflow with multi-backend support

## [5.0.0] - 2025-12-05


### ⚙️ Miscellaneous Tasks


- clarify unit-test coverage levels in requirement questions

### 🐛 Bug Fixes


- defer startup log until args parsed

### 💼 Other


- Merge branch 'master' of github.com:stellarlinkco/myclaude

- Merge pull request #43 from gurdasnijor/smithery/add-badge

- Add Smithery badge

- Merge pull request #42 from freespace8/master

### 📚 Documentation


- rewrite documentation for v5.0 modular architecture

### 🚀 Features


- feat install.py

- implement modular installation system

### 🚜 Refactor


- remove deprecated plugin modules

## [4.8.2] - 2025-12-02


### 🐛 Bug Fixes


- skip signal test in CI environment

- make forceKillDelay testable to prevent signal test timeout

- correct Go version in go.mod from 1.25.3 to 1.21

- fix codex wrapper async log

- capture and include stderr in error messages

### 💼 Other


- Merge pull request #41 from stellarlinkco/fix-async-log

- remove test case 90

- optimize codex-wrapper

- Merge branch 'master' into fix-async-log

## [4.8.1] - 2025-12-01


### 🎨 Styling


- replace emoji with text labels

### 🐛 Bug Fixes


- improve --parallel parameter validation and docs

### 💼 Other


- remove codex-wrapper bin

## [4.8.0] - 2025-11-30


### 💼 Other


- update codex skill dependencies

## [4.7.3] - 2025-11-29


### 🐛 Bug Fixes


- 保留日志文件以便程序退出后调试并完善日志输出功能

### 💼 Other


- Merge pull request #34 from stellarlinkco/cce-worktree-master-20251129-111802-997076000

- update CLAUDE.md and codex skill

### 📚 Documentation


- improve codex skill parameter best practices

### 🚀 Features


- add session resume support and improve output format

- add parallel execution support to codex-wrapper

- add async logging to temp file with lifecycle management

## [4.7.2] - 2025-11-28


### 🐛 Bug Fixes


- improve buffer size and streamline message extraction

### 💼 Other


- Merge pull request #32 from freespace8/master

### 🧪 Testing


- 增加对超大单行文本和非字符串文本的处理测试

## [4.7.1] - 2025-11-27


### 💼 Other


- optimize dev pipline

- Merge feat/codex-wrapper: fix repository URLs

## [4.7] - 2025-11-27


### 🐛 Bug Fixes


- update repository URLs to stellarlinkco/myclaude

## [4.7-alpha1] - 2025-11-27


### 🐛 Bug Fixes


- fix marketplace schema validation error in dev-workflow plugin

### 💼 Other


- Merge pull request #29 from stellarlinkco/feat/codex-wrapper

- Add codex-wrapper Go implementation

- update readme

- update readme

## [4.6] - 2025-11-25


### 💼 Other


- update dev workflow

- update dev workflow

## [4.5] - 2025-11-25


### 🐛 Bug Fixes


- fix codex skill eof

### 💼 Other


- update dev workflow plugin

- update readme

## [4.4] - 2025-11-22


### 🐛 Bug Fixes


- fix codex skill timeout and add more log

- fix codex skill

### 💼 Other


- update gemini skills

- update dev workflow

- update codex skills model config

- Merge branch 'master' of github.com:stellarlinkco/myclaude

- Merge pull request #24 from stellarlinkco/swe-agent/23-1763544297

### 🚀 Features


- 支持通过环境变量配置 skills 模型

## [4.3] - 2025-11-19


### 🐛 Bug Fixes


- fix codex skills running

### 💼 Other


- update skills plugin

- update gemini

- update doc

- Add Gemini CLI integration skill

### 🚀 Features


- feat simple dev workflow

## [4.2.2] - 2025-11-15


### 💼 Other


- update codex skills

## [4.2.1] - 2025-11-14


### 💼 Other


- Merge pull request #21 from Tshoiasc/master

- Merge branch 'master' into master

- Change default model to gpt-5.1-codex

- Enhance codex.py to auto-detect long inputs and switch to stdin mode, improving handling of shell argument issues. Updated build_codex_args to support stdin and added relevant logging for task length warnings.

## [4.2] - 2025-11-13


### 🐛 Bug Fixes


- fix codex.py wsl run err

### 💼 Other


- optimize codex skills

- Merge branch 'master' of github.com:stellarlinkco/myclaude

- Rename SKILLS.md to SKILL.md

- optimize codex skills

### 🚀 Features


- feat codex skills

## [4.1] - 2025-11-04


### 💼 Other


- update enhance-prompt.md response

- update readme

### 📚 Documentation


- 新增 /enhance-prompt 命令并更新所有 README 文档

## [4.0] - 2025-10-22


### 🐛 Bug Fixes


- fix skills format

### 💼 Other


- Merge branch 'master' of github.com:stellarlinkco/myclaude

- Merge pull request #18 from stellarlinkco/swe-agent/17-1760969135

- update requirements clarity

- update .gitignore

- Fix #17: Update root marketplace.json to use skills array

- Fix #17: Convert requirements-clarity to correct plugin directory format

- Fix #17: Convert requirements-clarity to correct plugin directory format

- Convert requirements-clarity to plugin format with English prompts

- Translate requirements-clarity skill to English for plugin compatibility

- Add requirements-clarity Claude Skill

- Add requirements clarification command

- update

## [3.5] - 2025-10-20


### 💼 Other


- Merge pull request #15 from stellarlinkco/swe-agent/13-1760944712

- Fix #13: Clean up redundant README files

- Optimize README structure - Solution A (modular)

- Merge pull request #14 from stellarlinkco/swe-agent/12-1760944588

- Fix #12: Update Makefile install paths for new directory structure

## [3.4] - 2025-10-20


### 💼 Other


- Merge pull request #11 from stellarlinkco/swe-agent/10-1760752533

- Fix marketplace metadata references

- Fix plugin configuration: rename to marketplace.json and update repository URLs

- Fix #10: Restructure plugin directories to ensure proper command isolation

## [3.3] - 2025-10-15


### 💼 Other


- Update README-zh.md

- Update README.md

- Update marketplace.json

- Update Chinese README with v3.2 plugin system documentation

- Update README with v3.2 plugin system documentation

## [3.2] - 2025-10-10


### 💼 Other


- Add Claude Code plugin system support

- update readme

- Add Makefile for quick deployment and update READMEs

## [3.1] - 2025-09-17


### ◀️ Revert


- revert

### 🐛 Bug Fixes


- fixed bmad-orchestrator not fund

- fix bmad

### 💼 Other


- update bmad review with codex support

- 优化 BMAD 工作流和代理配置

- update gpt5

- support bmad output-style

- update bmad user guide

- update bmad readme

- optimize requirements pilot

- add use gpt5 codex

- add bmad pilot

- sync READMEs with actual commands/agents; remove nonexistent commands; enhance requirements-pilot with testing decision gate and options.

- Update Chinese README and requirements-pilot command to align with latest workflow

- update readme

- update agent

- update bugfix sub agents

- Update ask support KISS YAGNI SOLID

- Add comprehensive documentation and multi-agent workflow system

- update commands
<!-- generated by git-cliff -->

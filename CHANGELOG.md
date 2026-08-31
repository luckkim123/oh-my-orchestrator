# Changelog

All notable changes to this project will be documented in this file.

## [0.21.6] - 2026-08-31 — the ledger knew the cost and never the reason

`SKILL.md:375` has forbidden delegating without naming one of four grounds since
0.1. The ledger, added 08-31, records what every vendor call cost — backend,
model, effort, tokens, duration, exit — and could not say **why any of them was
made**, because the obligation was discharged in prompt prose that nothing
machine-readable ever saw. Nine rows in, the first question a weekly routing
review would ask ("which grounds do we actually delegate on, and how often on
none?") had no denominator.

### Added

- `--ground <1-4>` on the wrapper, recorded as `"ground"` in
  `calls.jsonl`. Validated at parse time against the four grounds rather than
  carried as free text: an unchecked field is a denominator nobody can trust,
  and parse time is before any vendor process starts, so a typo costs a message
  instead of a call. An absent `ground` is a measurement, not a gap — it counts
  a delegation made without the obligation met.
- `TestGroundFlag` pins the six cases through `BuildSingleConfig`; the
  out-of-range and prose cases fail when the validation is widened, checked.

### Changed

- `skills/omo/SKILL.md`: both statements of the ground obligation now require the
  flag alongside the prose. A ground stated only in prose is one no review can
  see, which is how tokensave, CRG, and graphify's MCP server each died here —
  a layer nothing routes to.
- `references/vendor-ops.md`: the sample row carries `ground`, and the ledger
  section gains the grounds-and-unstated-share `jq` query the review runs.

### Removed

- `skills/harness/tests/verify_census.py`. It set-compared §9.1's roster against
  a live `find` for legacy store directories, and the 2026-08-28 stage-3 purge
  deleted every one of them, so all 24 rows read `STALE` — the subject of the
  check is gone, not the table. Measured 2026-08-31 before and after that day's
  §9.2 edit (24 → 25), which places the failure days earlier than the edit.
  Nothing ran it: the filename is deliberately not `test_*.py` (a machine-specific
  census would fail the suite on every machine but the one the spec was written
  on — a correct call), and the P5 dry-run acceptance that two planning prompts
  said would reuse it was never wired, leaving zero callers in the repo. The
  script had earned its place — its P0 run caught a mapping table writing
  `workspace/...` for `~/Desktop/workspace/...` across eight rows, which a
  row-count check would have passed. It died the way tokensave, CRG, and
  graphify's MCP server died here: **a layer nothing routes to.** §9 now carries
  a banner saying not to rebuild it; `census` (roster) and `audit` (git config)
  are the instruments that answer about the current machine.

### Notes

- The field crosses six hops (`config.Config` → `runtask.Command` → `Spec` →
  `TaskSpec` → the executor's own `Config` → `ledger.Call`). The first attempt
  patched only the ends, built clean, passed the parse tests, and wrote a live
  row with no `ground` in it — `internal/executor/executor.go:979` rebuilds
  `cfg` from `taskSpec` and drops anything the spec does not carry. Verified
  end-to-end against a real codex call, not by unit test alone.

## [0.21.5] - 2026-08-31 — the roster counted another computer's backup

`census` printed `in scope: 8` while this spec's own banner claimed `in scope: 0`
since the 08-28 purge. The banner was right. All eight rows were Google Drive's
**other-computers backup** of `workspace`, whose `.omp` (08-20) and `.oms`/`.omd`
(08-10) are a snapshot from *before* the purge that emptied the live tree — a
roster a later round would have read as anchors needing migration, on a machine
that does not own them. Two numbers disagreed for three days and nothing said so.

### Changed
- §9.2 — eighth exclusion pattern, `*/Library/CloudStorage/*`. A cloud
  provider's virtual tree is never an anchor this machine owns: it is a mirror
  of a local path already counted, or a backup of a different computer. Matched
  on the **provider directory**, not the folder name, which is localized
  (`다른 컴퓨터` here, `Other computers` elsewhere). Implemented in claudebase
  `514c7b4`; census now prints `in scope: 0`.
- §8 — three stale facts in one sentence. `~/Desktop/workspace` → `~/workspace`,
  iCloud → Google Drive, and **five nested anchors → one anchor, zero legacy
  stores** (unbounded `find` for `.hq/.anchor` and the six legacy names: one
  hit, none). The five nested ones survive only in that pre-purge backup.
  claudebase's `sync-claudebase` §4n-b had kept looping over the Desktop path,
  where `[ -d "$a" ]` is false — so workspace had **zero `drift` coverage** from
  the move until that loop was fixed, with no error anywhere.

### Known issue, not fixed here
`skills/harness/tests/verify_census.py` has been FAIL-by-construction since the
stage-3 purge: it set-compares §9.1's roster against a live `find` for legacy
store directories, and the purge deleted every one of them, so all 24 rows read
STALE. Measured before and after this change (24 → 25; the new glob row is the
25th). Its premise is gone — §9.1 became a dated record the day the stores did.
Retire it or repoint it at `.hq/.anchor`; that is a decision, not a patch.

## [0.21.4] - 2026-08-31 — the vendor's own default is now written down

The evaluation reported the ledger "losing" a role's model on a `--backend`
override. It does not: `internal/adapter/cli/parse.go` clears the model there on
purpose, because a model name lives in its own vendor's namespace and carrying
`claude-opus-5` onto codex is an HTTP 400 (and onto agy, a silent wrong-model
run). `model: None` was a true record of "nothing was configured".

The real gap sat one step further out. Nothing recorded what the vendor then
picked for itself, so 2026-08-31's two most expensive calls — 4.8M and 8.9M input
tokens, 766s and 1462s — carried `backend: codex` and no model at all. Measured
here, that was `gpt-5.6-sol`, not the `gpt-5.6-terra` that `models.json` binds
the codex roles to; agy's is `Gemini 3.7 Flash (High)`. Both sit in the vendors'
own config files, so no output parsing is involved.

### Added
- `internal/backend/defaultmodel.go` `DefaultModel(backend)` — reads the declared
  fallback from `~/.codex/config.toml` and
  `~/.gemini/antigravity-cli/settings.json`. The codex reader matches on the `=`
  rather than the key name (`model_reasoning_effort` shares the prefix) and stops
  at the first `[table]` header (a model inside a profile is not the default).
  Every failure returns empty: this runs inside a deferred ledger write and must
  never affect the call it describes.
- Ledger field `model_default`, written only when `model` is empty. It is the
  weakest of the three model fields and gets its own name for that reason:
  `model` is what was configured, `model_resolved` is what served the turn (claude
  only), `model_default` is what the vendor's config says it reaches for.

### Changed
- `skills/omo/references/vendor-ops.md` — the ledger schema section documents the
  third field and why an override leaves `model` empty.

### Verification
Full Go suite green. New: 8 cases in `internal/backend` (the
`model_reasoning_effort` prefix trap, a table-scoped model, an inline comment, a
commented-out key, absent config, claude-always-empty) and a two-branch executor
test asserting `model_default` appears when no model was passed and is *absent*
when one was. Probed against this machine's real config files: `gpt-5.6-sol` /
`Gemini 3.7 Flash (High)` / empty for claude. Live end-to-end, one real
`--agent oracle --backend codex` call: the row carries
`"model_default":"gpt-5.6-sol"`. The first live run recorded nothing — the
installed binary was still 0.21.3, which is the `make install` step this repo's
own SKILL.md warns about.

## [0.21.3] - 2026-08-31 — the pipe nobody closes now has a deadline

A background launcher hands the wrapper a stdin that is not a tty, is never
written to, and is never closed. `readPipedTask` read that with `io.ReadAll`,
which has no reason to ever return, so the call sat silent with one log line
("Reading from stdin pipe...") and no timeout — measured at 65 minutes on
2026-08-31, read the whole time as a running consultation.

The `--prompt-file` framing in the first report was wrong: that flag supplies the
agent prompt that *wraps* the task, not the task, and `parse.go` already rejects
an empty positional list ("task required"), so `cfg.Task` is never empty. Skipping
stdin whenever a task exists would therefore delete the implicit-pipe path
entirely. Whether a pipe will ever produce is undecidable without waiting, so the
wait is bounded instead.

### Fixed
- `internal/app/utils.go` `readPipedTask()` — the implicit pipe read is bounded by
  `stdinReadTimeout` (5s) and fails loudly, naming both escapes (`< /dev/null`, or
  the explicit `- <workdir> < file`). The explicit-stdin branch in
  `resolveSingleTaskText` never reaches this path and is unchanged, as is the
  precedence of piped text over a positional task.

### Changed
- `skills/omo/SKILL.md` — the invocation section now says where to launch a
  consultation (`bin/omo-consult` pane when someone is watching; background only
  when leaving) and to confirm liveness once right after firing. Zero bytes is not
  "still thinking."

### Verification
Full Go suite green (`go test ./...`, 19 packages). New regression test
`TestReadPipedTask_DeadlineOnNeverClosingStdin` reads a never-closing reader.
Discriminated against a control that keeps the new variable and restores the old
`io.ReadAll` body: the control is killed by `go test -timeout 15s`, the fix
returns in 0.6s. Live probe against a held-open fifo: loud failure at 5s, exit
non-zero, no vendor process launched.

## [0.21.2] - 2026-08-31 — the same stale sentence, one section further down

0.21.1 corrected §5's "`--purge` … has not run anywhere on this machine" and
left §9.4's identical claim standing, so the shipped spec contradicted itself:
§5 said the purge ran on 2026-08-28, §9.4 called the very lines it had deleted
"Outstanding". Fixing a claim in one place and not in its other statement is
the defect this spec keeps recording about other people's tooling.

### Changed
- `store-spec.md` §9.4 — the "Outstanding" group (`claudebase`'s `.omp/*` +
  `!.omp/rules.json` + `**/.orchestration/.hq-lock`, the vault's `.omp/work/` ·
  `.omp/state/` · `.omha/` + the same lock path) went with the stage-3 purge
  itself (`ed36266`, `e746ea3c`), verified against both repos' current
  `.gitignore`. What carries to other machines is the **ordering rule** — those
  lines stay until that machine runs its own purge — not the date.

### Verification
287 tests pass. `grep 'has not run'` over the spec: 0 hits.

## [0.21.1] - 2026-08-31 — the staging state stops looking finished

Reported by `ksm-MS-7E01` while migrating `stonefish_ws` (`.omp` + `.omx` under
one anchor — the first project with that pair, so the combination had never
actually run). Five findings, all one shape: **the procedure is in store-spec
and nothing in code binds it**, so the tool's exit signal never reaches the
next step and the operator reads a clean summary as done.

### Changed
- `convert-wiki-form.py apply --commit` now removes the staging directory, not
  only its pages. `migrate-om-store.sh` copies an omp store's `wiki/.gitkeep`
  (not a `.md`, so the converter never touched it) and `community/wiki/`
  outlived every page in it — a retired form still looking live. Only
  `.gitkeep` is removed; any other leftover keeps the directory and says so.
- `store-spec.md` §2 — the `migrated.jsonl` row is written by
  `migrate-om-store.sh apply` (claudebase, same date). Stage 1 said "a row is
  appended" and **no code anywhere appended one**, so `drift` answered "this
  store was never cut over" (exit 6) on the machine that had just migrated it.
  Also: `machine` is a human-stable label, not `hostname` (`ksm-mac` vs
  `gwe52`), set by `HQ_MACHINE`.
- `store-spec.md` §2 — the union-merge rule generalized to every append-only
  log in a *tracked* layer, naming omp's `secretary/ledger.jsonl` and
  `secretary/journal/*.md`. The vault union-merged the legacy `.omp/` paths in
  2026-08 and the `.hq/` cutover did not carry the rule across; 465 ledger
  lines and 37 journal files sat tracked with no merge driver.
- `store-spec.md` §5 — a **fourth** ignore line, `**/.hq/**/.hq-lock`.
  `hq`'s advisory write lock is classified *not moved, recreated on demand*
  yet `store.py` creates it inside `community_dir()`, a tracked layer, so the
  `work/` + `runtime/` pair never covered it. A new anchor seeded from the
  two-line block put the lock straight into `git status`.
- `store-spec.md` §5 — the "purge has not run anywhere on this machine"
  paragraph contradicted this file's own banner: stage 3 ran on `ksm-mac`
  2026-08-28 and the legacy ignore lines went with it.
- `store-spec.md` §7 — the wiki staging notice the migration tool now prints.

### Verification
287 tests pass (2 new: the directory removal, and its discrimination — an
unknown leftover must keep the directory). Both new tests fail against 0.21.0.

## [0.21.0] - 2026-08-31 — the npx installer is gone, and the lock lives where the state lives

The legacy `npx github:stellarlinkco/myclaude` install path shipped its last
release: 13 files removed (package.json, bin/cli.js, install/uninstall
scripts, config.json + schema, the pre-bash hook and its orphaned
hooks.json). What it alone provided — seeding `~/.codeagent/models.json` —
moved to `scripts/seed_models.py`: copy the template when absent, merge only
missing entries when present, never overwrite, atomic writes.

### Removed
- Legacy npx installer and everything only it consumed (13 files, −4,000 lines).
- `config.json`/`config.schema.json` — `~/.codeagent/models.json` `agents.<role>`
  is the one role-binding surface (vendor-ops.md updated in 3 places).

### Added
- `scripts/seed_models.py` — the supported way to create `models.json`.
- Root-local lock: `<root>/.harness.lock` replaces the TMPDIR-hashed lockdir,
  so TMPDIR drift between sessions cannot split the lock (`.gitignore` covers
  `.harness.lock*/`, stale renames included).
- B-r1 gate widening: an unparseable legacy board with no anchor is
  GATE_CORRUPT (loud), no longer a silent GATE_LEGACY.

### Changed (from the codex xhigh cross-review, 9 findings, all applied)
- Gate corruption check follows `state_path` precedence — a corrupt stale
  `harness-tasks.json` beside a valid live board no longer flips the gate.
- `TeammateIdle` warns and allows idle on a corrupt gate instead of blocking
  forever (it has no retry escape).
- `SubagentStart` reports corruption via `additionalContext` — its exit 2 and
  stderr were both measured invisible.
- The SKILL.md bash lock snippet gained the `CLAUDE_PROJECT_DIR` discovery
  layer, matching the Python side.
- Surviving docs (Makefile, wrapper README/USER_GUIDE) stop recommending the
  deleted npx path.
- Codex effort defaults lowered (develop xhigh→medium, security xhigh→high) —
  flat-rate vendor plans; task-type override remains the way up.
- store-spec §6 (precedence + discovery boundary noted), §7 (the `.anchor`
  marker covers every store under it).

### Verification
- `python3.12 -m pytest skills/harness/tests/ tests/test_version_sync.py` —
  285 passed (new: root-local lock ×2, legacy corrupt ×2, stale-sibling
  precedence ×1; updated: TeammateIdle/SubagentStart corrupt-channel
  expectations).
- Dual-store fixture: gate-closed warn fires, gate-open silent,
  gitignored→tracked marks (claudebase side, commit 14a8c42).

## [0.20.0] - 2026-08-31 — every reader now counts failures the way the Stop hook does

An audit against PLAN Phase 2-B found its claim — "the unlimited-retry hole is
closed" — true for exactly one of four readers. `harness-stop.py` judged
retryability on `max(attempts, logged ERROR lines)`; `harness-claim.py`,
`harness-teammateidle.py` and `harness-sessionstart.py` still read the raw
`attempts` self-report, so a session that never bumped the field could claim a
task the Stop hook had already ruled out. Same data, two read rules — the
defect class this repo has now recorded four times. The fix is not another
copy of the rule but the removal of the copies: the eligibility logic now
lives once in `_harness_common.py` and every hook consumes it.

### Changed
- **`_harness_common.eligible_tasks(tasks, logged)`** — retryability is judged
  on `effective_attempts` (max of the `attempts` field and the per-task ERROR
  count from `harness-progress.txt`). `logged_failures` /
  `progress_logged_failures` / `effective_attempts` moved up from
  `harness-stop.py`; claim, teammateidle and sessionstart all pass the
  log-derived count now — the cross-family review caught that a
  display-only sessionstart would advertise `next=t1` for a task every
  enforcing hook already considered exhausted.
- **Hook dedup, −546 net lines** — claim (286→84), renew (199→83),
  teammateidle (162→89), sessionstart (185→87), stop (474→345) shed their
  private copies of payload reading, root discovery, JSON I/O, lock
  primitives, priority sort and lease reaping in favor of `hc.*`. The
  fail-open contract is unchanged: `hc is None` still means every hook is a
  no-op, and the corrupt-gate path still fails loud.
- **`lockdir_for_root` uses `tempfile.gettempdir()`** instead of a hardcoded
  `/tmp` (PLAN Global Constraints; 3-OS distribution). Measured on macOS: the
  lock lands under the real `$TMPDIR` (`/var/folders/...`). Windows remains
  unmeasured. Transitional note: a process on the old build locks
  `/tmp/harness-<hash>.lock` while a new one locks the tempdir path — no
  active campaign exists, so no live lock crosses the upgrade. Residual
  (review finding, recorded): two same-version processes with different
  `TMPDIR` environments (GUI vs env-stripped launch) still derive different
  lock directories for one board; a root-local lockdir would close it and is
  backlogged rather than stacked onto this move.
- **`SKILL.md` concurrency snippet agrees with the hooks** — the bash lock
  ascends to the root carrying any of the three state markers
  (`.hq/runtime/board.json`, `.orchestration/board.json`,
  `harness-tasks.json`) instead of only the legacy file, honors
  `HARNESS_STATE_ROOT` the way `find_harness_root` does (marker-checked,
  resolved), hashes the physical path (`pwd -P` — the hooks hash the
  resolved path, so a symlinked cwd used to hash a different key), and uses
  `${TMPDIR:-/tmp}`. Measured: bash ROOT equals the hook's root in the
  subdirectory, symlinked-cwd, env-root, and markerless-env cases.
- **`hq --version` reports the plugin manifest version** (walks up to
  `.claude-plugin/plugin.json`), retiring the fourth version lineage
  (`hq.__version__ = "0.1.0"`, deleted). Presence-not-currency needs a
  comparable number, and `0.1.0` compared to nothing.

### Added
- **`hq post --date YYYY-MM-DD`** — the frontmatter date, defaulting to
  today. Every store migration so far (finding/098) has had to `sed` dates
  after the fact because `post` hardwired `_now_date()`; the ISO shape check
  in `verbs.post_new` still rejects anything else.
- **7 tests** (280 → 287): claim refuses a task whose logged failures exhaust
  `max_attempts` (the reproduction fixture), claim still hands out pending
  and under-limit tasks, teammateidle and sessionstart agree with the Stop
  hook on logged failures, and `--date` lands in frontmatter / bad dates
  still die.

### Fixed
- **Delegation-ground renumbering, the 7 sites 0.15.0 missed.** Its Notes
  claimed "every cross-reference moved with it"; the sweep covered
  `omo/SKILL.md` and stopped. `harness-stop.py:27,246`,
  `harness/SKILL.md:397` (3-strike = ground 3, not 1),
  `orchestrator/SKILL.md:24` (seven roles, four grounds), `:76` (adversarial
  review = ground 4), `:87` (escape = ground 3), and the half-migrated
  paragraph in `vendor-ops.md:165-177` now all use the 0.15.0 numbering.
  `grep -rn "ground [0-9]" skills/` audits clean against the canonical table.
- **Stale stage-2 declarations.** `hq/paths.py` and `_harness_common.py` both
  still declared "P2 is behavior-unchanged — `.hq` is not yet the live root
  anywhere", and `hq/__init__.py` "nothing here assumes `.hq/community/`
  exists yet" — false since 0.8.0 flipped the anchor gate. The docstrings now
  state the gate. `SKILL.md`'s migration guidance pointed at
  `.orchestration/board.json` as the destination; the board seed's `_comment`
  and `install_vendor_context.py`'s loader description likewise. All now name
  the anchor-gated pair. Operational prose that said `harness-tasks.json`
  where it meant "the state file" is generalized.
- **`config.json`** security operation description read "Install develop
  agent prompt" (copy-paste).
- **`ledger.go`** carried the same test-run comment paragraph twice; one
  survives.
- **`README.md` described an installation that does not deliver the plugin.**
  Install said `python3 install.py` (the npx-era route) and never mentioned
  building the wrapper, the `$GOBIN` symlink, or `~/.codeagent/models.json` —
  a stranger following it got a harness with no vendor lane. Status still said
  "Phases 1–5 are in progress" with all of them complete. Both rewritten;
  `install.sh`'s upstream-binary trap is now warned about where an installer
  would look for it.

### Removed
- **The fork-remnant sweep the earlier releases deferred** (user-approved
  2026-08-31; the npx-era installer set — `package.json`, `bin/cli.js`,
  `install.py`, root `hooks/` — stays until a replacement seeder for
  `~/.codeagent/models.json` exists, since `install.py` is today's only
  automated one):
  - `install.sh` no longer downloads the upstream `stellarlinkco/myclaude`
    binary — a build with no `agy` backend that overwrote a local one while
    every existence check passed. It now refuses with build-from-source
    instructions.
  - `skills/omo/.claude-plugin/plugin.json` — the nested fork manifest
    (5.6.1, upstream author); zero readers, and the third version lineage
    0.19.2's Notes left unresolved is closed with it.
  - The `gemini` and `opencode` backends, fully: `gemini.go`, `opencode.go`,
    their parser branches and event structs (`GeminiEvent`, `OpencodePart`,
    five UnifiedEvent fields), the gemini stderr noise list, the
    `~/.gemini/.env` loading path, the infrastructure aliases, and ~200 test
    lines. `Select()` had rejected both since D24 — this is the "separate
    sweep" that decision named. `templates/vendor/gemini/` and the
    installer's gemini vendor entry go with it; docs that listed gemini as a
    loader-capable backend now say codex/antigravity.
- `_harness_common.py`: `emit_block` / `emit_allow` / `emit_context` /
  `maybe_log_hook_event` — zero callers (grep-measured before deletion;
  `emit_json` and `load_state` stay, they have callers).
- `self-reflect-stop.py`: the hc-None "fallback" discovery block whose every
  inner branch required `hc is not None` — unreachable by construction,
  ~28 lines whose comment claimed a behavior the code could not perform.
- `.code-review-graphignore` — config for a tool removed from every machine
  on 2026-08-29; nothing reads it.

### Distribution
- `store-spec.md` §9 (the 23-anchor migration census) is now bannered
  **non-normative — origin-machine migration record**: the paths and project
  names in it are the origin operator's, not part of the spec, and nothing in
  it binds a new deployment.

### Verification
- `python3.12 -m pytest skills/harness/tests/ tests/test_version_sync.py
  hooks/test_pre_bash.py -q` → 287 passed.
- Cross-family adversarial review (codex, ground 4) over the hook diff:
  equivalence of the deleted copies confirmed; four findings adopted
  (sessionstart display drift, two SKILL.md prose sites still selecting on
  raw `attempts`, `HARNESS_STATE_ROOT` and symlink parity in the bash lock
  snippet — all fixed above); two recorded as pre-existing backlog (legacy
  unanchored corrupt board is read as inactive rather than loud, and the
  `TMPDIR`-variance lock split noted in the Changed entry).
- Mutation, not just green: reverting `eligible_tasks` to the raw `attempts`
  count fails exactly three tests — the new claim test, the new teammateidle
  test, and the Stop hook's own `test_logged_errors_exhaust_retries` — which
  is also the proof all three hooks now run through the one shared path.
- `go vet ./...` and `go test ./...` (18 packages) pass after the comment
  dedup and the gemini/opencode deletion; the one parser test that pinned the
  retired agy-before-gemini ordering was removed with the branch it guarded.
- Live: `bin/hq --version` → `0.20.0` (manifest); claim under a custom
  `TMPDIR` locks there and leaves nothing in `/tmp`.

### Notes
- `harness-subagentstop.py` keeps its four small local wrappers
  (payload/root/json/active): it carries no eligibility logic, and the audit
  item was scoped to the four files that did.
- Windows lock-path behavior is asserted from `tempfile.gettempdir()`
  semantics, not measured (audit plan B2 stands).

## [0.19.2] - 2026-08-31 — the guard the sibling repos already had

0.19.1 fixed a manifest that was never bumped. This adds the check that would
have caught it, which every other om* repo has had since it was written for
oh-my-scholar and ported to omp, omd and omx. omo was the one repo without it,
which is the entire reason the drift survived a release.

### Added
- **`scripts/sync_version.py`** — read-only drift report across the version
  surfaces: `.claude-plugin/plugin.json` (the anchor the marketplace resolves
  against), the top released `CHANGELOG.md` heading, the latest comparable `v*`
  tag, and the omha card. omo has no card, so that surface reports SKIP rather
  than failing.
- **`tests/test_version_sync.py`** — 14 tests. `test_plugin_changelog_drift_detected`
  is the 0.19.0 defect itself, frozen: anchor `0.18.0` against a CHANGELOG top of
  `0.19.0` must report drift.
- **`.github/workflows/tag-guard.yml`** — the layer that makes the test binding.
  `ci.yml` is Go-only and checks out shallow and tagless, which silently skips
  the tag surface; this job fetches tags and runs the pytest file. A test no CI
  job runs is the failure mode this repo has now recorded three times.

### Changed
- `parse_tags` takes `max_major` and ignores tags above the anchor's major.
  **omo carries a legacy `v6.7.x`–`v6.8.2` lineage beside the live `v0.x`
  series**, and the sibling implementation's plain max-by-tuple picks `v6.8.2`
  forever — a guard that reports drift on every correct release is a guard that
  gets ignored. The filter reopens on its own if the anchor ever reaches that
  major.

### Verification
- Mutation, not just a green run: setting `plugin.json` back to `0.18.0` makes
  `sync_version.py` exit 1 and name both surfaces
  (`plugin.json version 0.18.0 != CHANGELOG top released 0.19.1`,
  `latest tag v0.19.1 matches neither …`). Restoring it returns exit 0.
- `python3.12 -m pytest tests/test_version_sync.py -q` → 14 passed.
- `sync_version.py` on the release state → all surfaces PASS, card SKIP.

### Notes
- The two remaining version fields are untouched and still disagree with the
  anchor by design-or-neglect: `package.json` at `6.7.0` and
  `skills/omo/.claude-plugin/plugin.json` at `5.6.1`. The guard does not read
  them, because it is not established which of them anything consumes.
  Reconciling that is its own change.

## [0.19.1] - 2026-08-31 — the release that did not ship, and the check that let it not ship

0.19.0 wrote its CHANGELOG, its skill text and its tag, and left
`.claude-plugin/plugin.json` at `0.18.0`. The marketplace entry carries no pinned
version, so the plugin's own manifest is what `/plugin update` resolves against:
the ledger, the ground-4 gate and the vendor-ops section were all pushed and none
of them could be pulled. This entry is the first version that actually carries
them.

The same shape, one layer down, is why the ledger recorded nothing for the seven
hours after it shipped. `make install` puts the binary in `$GOBIN`, which is not on
`PATH` on this machine; `PATH` resolved to a hand-copied build from two days
earlier, and omo's pre-flight check — `command -v codeagent-wrapper` — passed on
it, because presence is not currency. Both failures are a version-bearing layer
that the thing above it never reads.

### Changed
- **`skills/omo/SKILL.md`, pre-flight step 1** now says that `command -v` cannot
  distinguish a current wrapper from a stale one, and gives the comparison that
  can (`--version` against the top of `CHANGELOG.md`) plus the symlink that stops
  the drift recurring.
- **`codeagent-wrapper/README.md`** names `$GOBIN` rather than `$GOPATH/bin` and
  tells the reader to link from a `PATH` directory instead of copying. The copy is
  what put a two-day-old binary on `PATH` here.

### Fixed
- `.claude-plugin/plugin.json` version, `0.18.0` → `0.19.1`. Nothing from 0.19.0
  was reachable by a consumer until this line moved.

### Verification
- `codeagent-wrapper --version` through `PATH` → `v0.19.0` after the symlink
  replaced the copy (it read `v0.8.1-8-gd45fc34-dirty` before).
- One `--agent explore` call through `PATH` grew
  `~/.local/state/codeagent-wrapper/calls.jsonl` from 3 rows to 4, with
  `backend=codex role=explore in=32242 cached_in=26112 out=146` — the ledger is
  live for anything invoking the wrapper by name, which it was not before.
- `python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"` parses,
  and the diff on that file is one line.

### Notes
- The old `PATH` binary was moved to `codeagent-wrapper.pre-0.19.0.bak` rather
  than overwritten; it was built from a dirty tree and is not reproducible from a
  commit.
- This repo carries three version fields on three different lineages —
  `.claude-plugin/plugin.json` (`0.x`, the one delivery resolves against),
  `package.json` (`6.7.0`), and `skills/omo/.claude-plugin/plugin.json` (`5.6.1`) —
  alongside tags in both a `v0.x` and a `v6.x` series. Only the first was moved
  here. Reconciling them is its own change and is not attempted in a patch.

## [0.19.0] - 2026-08-31 — the wrapper starts measuring what its roles cost

The binding question — which role should run on which vendor — has been parked
since round 4 for want of a denominator, and the operator's decision this round
was to build the denominator before moving anything. So no binding changed.

The premise turned out to be half wrong in a useful way. `codeagent-wrapper`
already wrote a JSON line per call to `$TMPDIR`; what it never wrote was the
role, the model, the tokens, or anything surviving seven days. This is four
missing fields and a durable file, not new logging.

### Added

- `internal/ledger`: one JSON line per vendor call at `$CODEAGENT_LEDGER` or
  `${XDG_STATE_HOME:-~/.local/state}/codeagent-wrapper/calls.jsonl`. Role,
  backend, configured model, resolved model, effort, mode, workdir, exit, ok,
  character counts, tokens, cost, duration, log path, pid. Best-effort by
  contract: a write failure never touches the vendor call. Rows stay under
  4096 B so cross-process `O_APPEND` stays atomic, and a row that cannot fit is
  dropped rather than written.
- Token usage from the two backends that report it. codex sends it on
  `turn.completed`; claude sends it on its `result` event under different names
  and adds `total_cost_usd` and `modelUsage` — all of which the parser had been
  discarding. agy reports none, and its rows say so by omission.
- `skills/omo/SKILL.md` ground 4 and `references/vendor-ops.md`: two vendor
  families in parallel is a gate, not the default. Its conditions are a
  release, a data-loss path, or a change that is hard to undo.

### Changed

- The ledger is wired with a single `defer`, not per-return. There are twelve
  return points and most are failure paths; a missed one would drop failed
  calls only — the worst possible bias for a measurement. A panic is corrected
  and re-panicked rather than recorded as a clean exit.
- `taskSpec.Backend` now sets the command as well as the argument builder when
  the caller left the command at its default. Setting one without the other ran
  the default binary with another vendor's flags.
- Task and response text are never recorded — character counts only, in runes
  rather than bytes. The wrapper handles arbitrary repository content, and the
  `err` field now keeps the wrapper's own sentence without the vendor stderr
  that `attachStderr` appends to it.

### Verification

- `go build`, `go vet`, `go test ./...` clean across 18 packages. Tests
  401 → 429, files 53 → 57, none deleted.
- Three mutations confirmed the new guards fire before they were trusted.
- Live calls against codex, claude and agy each wrote a correct row; an
  unwritable ledger left the vendor call at exit 0; a `go test ./...` that had
  been leaving 65 rows in the real ledger now leaves none.

### Notes

- Cross-family adversarial verification on the release commit produced 26
  claims, 16 reproduced and fixed, 2 rejected with reasons, and the rest
  documented as boundaries. The two families barely overlapped — agy found the
  ranking and criterion defects, codex the token accounting and a FIFO at the
  ledger path that blocked every parallel task. That is the second sample
  behind the gate added above, and it is still a sample of two.
- A pre-flight rejection (unsupported backend, unreadable prompt file) leaves
  no row because no vendor process ran.

## [0.18.0] - 2026-08-30 — the wiki form is retired, and the two-level read it promised arrives here

The sibling harnesses (oms, omd, omp) each carried their own reader over
`community/wiki/`, and PLAN item 6 said to replace those helpers with `hq`
calls. Measured, that is not possible as written: **`hq` has no wiki verb**
(post·comment·edit·query·index·lint·gc), and the checks barely overlap — `hq
lint` does id uniqueness, supersede chains, enum values and review counting,
while the three helpers do misplaced/near-dup/stale/orphan/oversized/INDEX
drift. The real duplication was among the siblings: three readers of one path
with three different shape assumptions (omd and oms expect category
sub-directories, omp globs `wiki/*.md` flat).

And every one of those readers was aimed at nothing. On this machine no anchor
holds a wiki page — the vault converted on 2026-08-28 and the workspace with
it — while the same anchors hold 127/33/17 posts. The three readers disagreed
even about how to say so: oms exits non-zero, omd returns `('info','empty', …,
'no wiki store at this root (fresh project — not an error)')`, and omp returns
`[]`. Two of the three report an all-clear over a store they never opened.

So the user retired the form outright ("wiki 는 아예 없애는 걸로. Wiki 폴더
안만들게") and asked for the conversion procedure first. This release is hq's
half of that.

### Added
- **`hq query --ascend`** — opt-in. Searches every anchor the ascent reaches
  instead of only the nearest, and every returned post carries its `anchor`.

  This is the capability the retiring wiki form actually had and `hq` did not.
  omd's and oms's wiki was read at **two levels** — the project's store plus the
  parent folder's, merged by ascent — and `doc-inspector`'s `wiki_query(category)`
  stands on that. `hq query --keyword` read `roots[0]`: the nearest anchor, full
  stop. Only `--subject` walked the chain. Converting the pages without this
  would have moved the layer and dropped the capability, which is the exact
  failure this campaign's PLAN §1 exists to prevent.

  Ranking runs **per anchor** and the ranked lists are concatenated, nearest
  first — never re-sorted on the two exposed scores. Per anchor because
  `all_posts` is how the ranker learns what is superseded and `supersedes:`
  names an id unique only within one anchor; pooled, anchor A's `finding/007`
  would mark anchor B's as superseded. Concatenated because `(field, body)` is
  only the *reported* part of the ranker's key — the rest carries chain-head,
  date and number, and a grounded contradiction deliberately sinks a post below
  a weaker match. The first cut re-sorted on the two scores and silently undid
  that; `RankContradictedSinksTest` caught it.
- **`skills/harness/convert-wiki-form.py`** — the wiki→posts conversion, in two
  phases. `plan` derives what is derivable and leaves three fields null;
  `apply` refuses while any is null, writes each post through `verbs.post_new`
  (the store's one serializer, whose `now=` takes the page's own date — the
  CLI's missing `--date` is what forced the post-hoc `sed` that `finding/098`
  recorded as a trap), verifies the body survived byte-for-byte, and `git rm`s
  the originals.

  It refuses to guess `category`, `subject`, and a missing title because
  `finding/098` measured each one going wrong: reader-intent category
  assignment is D22's call per page ("everything ends up in one `finding/`" is
  the named anti-pattern), filename-derived subjects were truncated at 64 chars
  or carried a date that locks later posts out of the chain, and two pages had
  no H1 at all.

  `verified:` is derived as **the largest ISO date the page's own text
  mentions**, not from git: `git log --follow -M` skips into an unrelated
  file's history on a migrated tree, and gave three contradictory answers for
  the same seven files.
- **`technique` and `history` in `TOPICS`.** D22 put the wiki taxonomy on this
  axis and these two were missing from it. Measured on the wiki trees still on
  backup: six category directories are in use — convention, decision, history,
  pattern, reference, technique — and `technique` is not even in omd's own
  `lint_wiki.CATEGORIES` while store-spec's omd row lists it. Without them the
  conversion would have to merge `technique` into `pattern` and `history` into
  `reference`, losing a distinction the author drew. Widening an enum makes
  `hq lint` more permissive, so both were added on the evidence of real pages.

### Changed
- **The anchor ascent now stops at the user's home directory.** Two unrelated
  projects under `~` share `~` and `/Users`, so a single `.hq/.anchor` at
  either would silently merge them. This is omd's ST-3 gate, which existed only
  as prose in `references/wiki/README.md` — its test asserted the *sentence*
  appeared twice, and nothing enforced it. The wiki form it guarded is retired,
  so the guarantee moves into code. A start path outside home keeps the full
  ascent: a container mount like `/workspace` is a documented anchor location
  and home is not its ancestor.
- **`store-spec.md` §9.3**: the four `community/wiki/` target rows are retired
  and now point at `community/posts/`, the blockquote that said "the `wiki/`
  target above still stands" is replaced, and its citation is corrected from
  `finding/021` to `finding/098` (the D29 anchor merge renumbered it, and
  `finding/021` is now an unrelated post).

### Verification
- 266 tests pass (`skills/harness/tests/` 259 + 7 elsewhere), up from 223.
- **Eleven mutations, each caught by at least one test**: dropping the HOME
  break; bounding at `home.parent`; ignoring `--ascend`; pooling `all_posts`
  across anchors; always emitting the `anchor` tag; removing the re-apply
  guard; removing the unfilled-judgment refusal; accepting an unmappable
  category; leaving the H1 in the body; taking the first ISO date instead of
  the largest; ignoring the plan's refusals.
- **Live round-trip on a copy** of a real 29-page wiki tree (the workspace's,
  from the Google Drive backup — the backup itself was never touched): 26
  posts, 3 tool-generated pages dropped, 0 refusals, **body byte-identical
  26/26**, `hq lint` clean, `git rm` of all 29.
- The re-apply guard came out of that run. The help text says "rerun with
  `--commit`", and the rerun **minted a second copy of all 26 posts** — visible
  only one layer downstream, as `hq lint` reporting two chain heads per
  subject. `apply` now skips a page whose `subject` already has a head, which
  also makes an interrupted run resumable rather than destructive.

### Fixed after the pre-merge attack

The first cut of everything above was handed to **two vendors from different
families, same prompt, same commit** — and they came back with almost no
overlap. agy (Gemini) found parser and boundary defects; codex (GPT) found
contract and side-effect defects. Eleven were reproduced and fixed:

- **The HOME bound was on one of the two ascents.** `_resolve_anchor_roots_for_query`
  falls back to `find_anchor_root` whenever the strict ascent finds no
  `.hq/.anchor`, and that function had no bound — so the guard was absent for
  exactly the trees with no anchor of their own to protect them.
- **`d == home` compared strings.** `Path` equality is textual, so a
  case-insensitive filesystem or a symlinked route to the same directory never
  matched and the loop ran to `/`. Now `(st_dev, st_ino)`.
- **`--post-id` ignored `--ascend`**, so the flag returned
  `{"id": "finding/007", "anchor": "outer"}` and the obvious follow-up raised
  "does not exist". It now resolves nearest-first across the ascent and names
  the anchor it answered from.
- **The converter `git rm`ed a page it never converted.** Two pages given one
  `subject` — the second hit the already-converted guard, landed in `skipped`,
  and `skipped` was folded into the removal list. Duplicate subjects are now
  refused before anything is written.
- **The frontmatter fence was `text.find("\n---")`**, which matched the first
  three dashes anywhere — a `---` inside a code fence ended the frontmatter and
  every prose line above it was dropped, then the page was removed. Both fences
  must now be a line that is exactly `---`.
- **The H1 pattern matched `# comment` inside a code fence**, taking a shell
  comment as the post title and deleting that line from the snippet.
- **`kept_fields` was recorded and never read.** `apply` looked for
  `confidence` at the top level of the entry while `plan` put it inside that
  dict, so all 26 pages of the real backup tree reached their posts as
  `confidence: none` while the plan showed the value preserved.
- **`--commit` staged the deletions and not the posts**, so a commit made right
  after recorded the originals disappearing and nothing arriving.
- **A page's `date:` could forge frontmatter.** `date` shares its bullet with
  `author`/`harness`/`to`, joined by " · ", and `now=` was free text from a
  file: a value of `2026-08-07 · author: someone-else` wrote the author line
  and `hq lint` passed it. `post_new` now requires `YYYY-MM-DD`.
- **`now="unknown"`** outsorted every real date — the ranker's date tiebreaker
  is a string compare and `"unknown" > "2026-08-30"`. Undated pages are refused.
- **`TOPICS` was widened in code only.** `store-spec.md`'s normative enum still
  listed eight values, so the same post was valid to the implementation and
  invalid to anything reading the spec. Both now list ten.

Two vendor findings were **rejected with reasons**: the `technique`/`history`
values themselves (15 real pages across two harnesses, and §9.3 already listed
`technique`), and the nearest-first concatenation (the ranker reorders
*after* sorting — a grounded contradiction sinks a post below a weaker match by
position, which `(field, body)` cannot express). codex's counter-proposal —
compute supersession per anchor, then merge on the ranker's full key — is a
valid alternative and is recorded as an open design question rather than
silently decided.

And two claims of my own outran the work: `store-spec` said "this machine no
anchor holds a wiki page" without the *live* qualifier (a Drive backup of
another machine holds 35), and asserted omp's wiki clause was already retired
while that release was still in flight. Both corrected.

Correcting §9.3 the first time also **over-corrected**: the four `wiki/` rows
were repointed at `community/posts/`, but §9.3 is `migrate-om-store.sh`'s
mapping table and a file move cannot mint a post id. That target would have
produced unreadable files in `posts/` and left the converter with no
`community/wiki/` to read. The rows are back to `community/wiki/`, now labelled
**staging only**: an anchor with pages still there is mid-migration.

### Notes
- `--ascend` is opt-in for the same reason `--weight-metadata` is: on by
  default it would silently widen every existing caller's result set.
- This release is hq's half of PLAN item 6. The sibling half — oms/omd/omp
  dropping `wiki_dir()` and calling `hq` — follows in their own releases.

## [0.17.0] - 2026-08-29 — the weights come back, as a flag, on the tier that breaks ties

### Added
- **`body` on `hq query --post-id`**, and on that path only. Asking for one named
  post and withholding its body forced the one consumer that needed it (omx's
  `wiki read`) to open the file and re-split the header itself — a second parser
  for the format this store exists to have exactly one of. A keyword query still
  omits bodies: 125 of them in one response is a different question.
- **`hq query --weight-metadata`** — opt-in, off by default. It lets `confidence:`
  and `status:` re-order keyword matches, using omx's own
  `_CONFIDENCE_WEIGHT`/`_STATUS_WEIGHT` maps carried over verbatim from
  `wiki/query.py`. This is what unblocks B4: omx's reader moves onto this ranker
  and would otherwise silently lose a signal its experiment trees are built to fill.

  **Opt-in is the whole design.** 0.14.0 refused these weights outright, and that
  refusal still holds for this store: `confidence` is absent on 77 of 122 posts,
  `status` on 113, and `verified:` marks exactly the same 45 posts as `confidence` —
  so on *this* store the fields record which schema generation a post was written
  under, not how well it is backed. A caller whose store fills them can ask; nobody
  gets them by accident.

  **It weighs the body tier and then sits below it as its own tier — two
  corrections, in opposite directions.** omx could multiply its single blended
  score because a 20x better body match still beat a 0.56 discount, which is
  exactly the contract its docstring states ("re-orders NEAR-tied scores while a
  clearly-stronger keyword match still wins"). This ranker's key is tiered and
  sorted lexicographically, so a discount on the FIRST tier is unrecoverable by
  the ones below it: applied there, `status: resolved` alone dropped a post with
  twenty keyword matches below one with a single mention — a veto, not a nudge.
  Moving it to the body tier alone then made it inert exactly where it was
  needed, because `b * w` is 0 for every weight when `b` is 0: two posts matching
  on their fields alone — the common case for a short, well-tagged store — tied
  at zero and fell through to the accidental tiebreakers, with `resolved`
  sometimes leading. So the weight scales the body tier AND breaks its ties. The
  first error was caught by a test written before the implementation; the second
  by a cross-model review after it.

  Absence is neutral in both maps, never a penalty — a post that never set
  `confidence` must not sink below one that set it to `low` — and `none`, this
  store's explicit-absence sentinel, weighs the same as a missing field.

  The returned `score` is the **weighted** number under the flag, not the raw match.
  Handing back a raw score under a weighted order would let a caller that re-sorts by
  it produce a different order than the list it was handed; two readers of one number
  disagreeing about the rule is the defect class this plan has now hit four rounds
  running.

### Fixed
- **`hq query --keyword` returned nothing for a multi-word query whose terms sat
  in different fields.** The filter tested the whole query string as a substring
  of one field while the ranker scored per token, so `--keyword "gpu memory"`
  found zero posts against one with `keywords: gpu, memory` and both words in
  its body. Membership is now the ranker's own verdict —
  `score_post(p, keyword) == (0, 0)` — which deletes the second rule instead of
  correcting it for a fourth time (the first three: a joined field string
  inventing phrases, `subject` carrying a weight no query could reach,
  `keywords: none` matching here and scoring zero there). On the vault's store,
  `--keyword "graphify 색인"` goes from 0 posts to 19.

### Verification
- 223 tests pass (210 before, 13 added).
- Eight mutations, each caught by at least one test: flag ignored (3 fail);
  weight applied to the field tier, i.e. the veto bug (2); the weight tier
  removed so body-only weighting returns (1); the `none` sentinel weighted as a
  penalty (1); absence penalised below `low` (2); raw scores returned under a
  weighted order (1); the keyword filter reverted to whole-string substring (1).
- Reviewed adversarially by a model from another family (`--backend agy`), which
  is what surfaced the inert-weight case and the multi-word filter bug. It also
  argued three judgements were wrong; two were (both above), one was not.
- Live, on the vault's 125-post store: `--keyword 랭킹 --weight-metadata` sinks
  `finding/122` (`status: resolved`) below `decision/118` (`status: none`), which the
  default ordering ranks the other way.

## [0.16.0] - 2026-08-29 — a review without evidence is an opinion

### Added
- **`hq comment` can write a grounded review** (`--assessment` / `--scope` /
  `--evidence`), and `hq query` reports the ones that count. This is B3 of the
  hq-engine-consolidation plan; its acceptance criterion is PLAN §7's "an ungrounded
  review comment is not counted".

  No new file and no new store layer, per PLAN §2.2 — a review is a comment in the
  post's own `## Comments` section, with `scope:` and `evidence:` on continuation
  lines:

  ```
  - (2026-08-29, reviewer) [contradicted] tier 2 에서 뒤집힌다
    scope: §3 의 "전 tier 우위" 주장
    evidence: pytest -k tier → 2 failed (커밋 1062dc2)
  ```

  **Line-anchored, not ` · `-separated.** The frontmatter's separator is not reused
  here: comment text is prose, prose contains ` · `, and a seam-crossing split is the
  exact defect class 0.13.0 and 0.14.0 each shipped a guard against. Nothing has to be
  split, so nothing can be split wrong.

  A review is **counted** only with a non-empty `evidence:` and a reviewer who is not
  the post's own `author:` — author and approver are different passes, which is the
  rule omo already applies to vendors. The verb refuses to write a review missing
  either rather than minting a record its own gate discards; that is how a gate ends
  up green while enforcing nothing (`omx` shipped exactly that in 0.11.1).

  Three values only — `confirmed`, `contradicted`, `superseded`. PLAN §2.2(c): in a
  store most of whose posts one model wrote, a reaction is self-approval, and a count
  of them carries less than one sentence saying why.

### Changed
- **A counted `contradicted` review sinks the post in `hq query --keyword`.** It is
  the one review signal that survives a population of zero: at n=1 it still says
  someone reproduced the post being wrong, which is what a ranker must not lead with.
  Sorting is stable, so nothing else moves.
- **`confirmed` gets no rank bonus**, which is a deliberate deviation from PLAN
  §2.3-4's "grounded confirms" signal. A confirm count measures attention, not truth,
  and the store has zero of them to calibrate against — 0.14.0 already refused to
  weight a field whose population is a proxy for when a post was written. Revisit when
  confirms exist.
- **`hq query` results carry `reviews`, on every path** (unlike 0.14.0's `score`,
  which is keyword-only). Counted reviews only: a caller that has to filter the
  uncounted ones itself is a caller that will forget to. Additive, so omx
  `wiki/query.py` — which reads `id`/`title`/`fields` — is unaffected.
- **`hq lint` names each uncounted review** (warning, not error). The uncounted ones
  are invisible to query by design, and something has to make them visible where a
  mistake gets fixed rather than where an answer gets decided.

### Fixed
- **A newline in `comment --text` or `edit --reason` could forge a whole comment.**
  A comment block ends at the next `- ` line, so free text carrying one minted a
  second comment — and once B3 reads `[assessment]` off that line, a counted review
  nobody wrote. This is 0.13.0's defect one layer up, where a newline in `--summary`
  forged a frontmatter bullet and walked through the `status:` enum gate. Both flags
  now refuse a line starting with `- `, `scope:`, or `evidence:`. Validating one field
  is worth nothing while another field can forge it.

- **Four more in the first B3 draft, found by handing it to codex with "attack it,
  do not write a patch".** Eight judgments went in; it rejected four, and all four
  reproduced. They are one root — **the write gate and the parser read `author` under
  different rules**, which is the third distinct pair of readers in this codebase to
  disagree about one datum (0.13.0: parser vs mutator; 0.14.0: filter vs ranker):

  | Input | What happened | Exit |
  |:---|:---|---:|
  | `--author "rev)"` | closed `(date, author)` early, so the parser saw no review at all — written, invisible | 0 |
  | `--author " test "` on a post by `test` | write gate compared raw, parser compared stripped: the self-review check passed and the parser then declined to count it | 0 |
  | `--text "…\r- (…, ghost) [confirmed] forged\r  evidence: fake"` | **a counted review by an author nobody invoked** | 0 |
  | a post with no `author:` | a review counted without anyone being shown to differ from the author | 0 |

  The carriage return is the worst of them and the reason is worth keeping: `"\n" in s`
  is not a test for "does this contain a line break". The store is read back with
  universal newlines, so a lone `\r` is not a line break *going in* and is one *coming
  out*. `_has_line_break` now asks `s != "".join(s.splitlines())`, and the forgery scan
  splits the same way.

  `--author` is now canonicalised at write time to exactly what the parser will read —
  stripped, and refused if it holds `)`, `,`, or a line break, for plain comments as
  well as reviews. A review of a post with no `author:` is refused rather than counted,
  and `parse_review` carries "the review names no reviewer" / "the post names no
  author" as its own uncounted reasons.

### Verification
- `python3 -m unittest tests.test_hq tests.test_hooks tests.test_paths_lint` —
  **210 pass** (25 new), exit code read directly, not through a pipe.
- **Mutation-checked, all five guards.** Disabling the forgery guard fails exactly
  the three forgery tests; forcing `counted` true fails the three that depend on the
  gate; removing the sink fails only the sink test; reverting `_has_line_break` to
  `"\n" in s` fails only the CR-in-evidence test; disabling the author canonicaliser
  fails exactly the three author tests. One test passed *for the wrong reason* until
  this was run — `edit --reason` forgery asserted only `HqError`, and with the guard
  disabled it still raised one from the no-subject path. It now asserts the message.
- **Live store copy, through `bin/hq`**, re-run after the four fixes: a grounded
  review on `finding/121` adds **exactly three lines** and nothing else;
  `hq query --post-id` returns it under `reviews`; a planted evidence-less review is
  reported by `hq lint` as `not counted — no evidence: line`; and each of
  `--author "ghost)"`, `--author " omo-consolidation-r2 "` (the post's own author,
  padded), and a CR-forged `--text` exits **1**.
- The live store's baseline stays clean: its 9 legacy verdicts are prose
  ("교차검증 verdict: ok|issues"), not bracketed, so they are not review-shaped and
  nothing retroactively fails. Migrating them is a separate call, not made here.

## [0.15.0] - 2026-08-29 — the volume goes out, the decision stays

### Changed
- **omo's delegation model, rewritten around cost** (`skills/omo/SKILL.md`). The
  operator's stated reason for building omo:

  > "claude 하나로는 토큰 소모량이 너무 심해서 퀄리티는 claude가 담당하고, 작업은
  > codex나 agy가 담당하는 느낌으로 하려고 해서야."

  omo did not do that. It opened with "**You are the executor.** You read the code, you
  make the edit, you run the tests", and its "Not grounds for delegation" list led with
  **"It's a code change." You write code.** The role table bound `develop`, `explore`,
  and `security` to codex, but nothing could reach them: the three grounds were
  three-strike, context budget, and adversarial verification, and none of them is
  "this is ordinary work". The vendor lane was wired and gated shut.

  It now splits by strength the way `cco` does, along the axis this operator built it
  for. cco puts deep reasoning on codex and bulk reading on Gemini, keeping Claude as
  orchestrator; here the reasoning stays with Claude — that is the half worth paying
  Opus for — and the two high-volume halves go out.

  | | Before | Now |
  |:---|:---|:---|
  | Ground 1 | three-strike | **settled plan, mechanical execution** → `develop` |
  | Ground 2 | context budget | volume — reading *or writing* wider than the decision |
  | Ground 3 | adversarial verification | three-strike |
  | Ground 4 | — | adversarial verification |

  The line is not "who types" but **whether the decision is already made**. That keeps
  what the old model was right about: upstream `myclaude` forbade the session to touch
  code at all, so a one-line fix cost a round trip and lost the context that made it
  correct. Undecided work still stays; decided work now goes.

  Three guards came with it, because a delegation model without them just moves the
  mistakes downstream:
  - **"I know what I want" is not a settled plan.** If you cannot paste it, it is not
    settled — and the plan goes to the vendor *verbatim*, not summarized.
  - **What comes back is a draft, not a result.** The vendor is asked to list every
    place the plan was silent, because that list is where a mechanical executor had to
    decide something it was not given.
  - **The saving is not free.** Reading the returned diff is a real cost; it is
    positive on 400 lines and negative on 4. Written into the skill so the model does
    not oversell it.

### Notes
- Ground numbering shifted, so every cross-reference moved with it — `SKILL.md`'s
  routing table, role catalog, Context Pack template, examples, and
  `references/vendor-ops.md`. The anti-example that read "Consult `develop` to write
  the change (you write code)" is now an example of ground 1 *not* holding, for the
  right reason: the design was never settled.
- **What this does not answer**: how much it actually saves. Vendor calls leave no
  durable record — `finding/104` measured that vendor workers write nothing to `.hq`,
  and `codeagent-wrapper` logs land in `/var/folders/.../T/` and vanish with the
  session. There is no denominator. PLAN §4.7 carries this as T-0: instrument the
  wrapper before claiming a number.

## [0.14.0] - 2026-08-29 — filtering is not ordering

### Added
- **`hq query --keyword` now ranks its results** (`skills/harness/hq/rank.py`, new).
  Before this the verb had a filter and no order at all: `matches()` was a boolean
  predicate and the survivors came back in post-number order. The pinned case, and now
  a regression test — `--keyword graphify` led with `finding/088`, which mentions
  graphify once in passing, while `finding/121`, the post *about* graphify, sat tenth.
  This is B2 of the hq-engine-consolidation plan; B1 (`hq edit --status`, 0.13.0) was
  its prerequisite.

  Ported from omx `wiki/query.py`: CJK bigram tokenization, so a Korean query has an
  ordering signal at all (Korean is not space-delimited inside a compound), and
  field-tiered weights. **Not** ported: that ranker multiplies its score by
  `confidence` and `status`, and this store does not support those weights. Measured
  on the live store — `confidence` absent on 77 of 122 posts, `status` on 113, and
  `verified:` present on **exactly the same 45 posts as `confidence`**, which makes it
  a marker of the post-schema generation rather than of the evidence behind a post.
  Weighting any of the three would order by when a post was written while claiming to
  order by how well it is backed.

  The key is two-level rather than blended — field placement first, body only to break
  its ties — which is what PLAN §2.3-3 asks for. A superseded post sinks below every
  chain head (§2.3-2) but is still returned; dropping it would answer a history
  question with silence. Each hit carries its own `score` so the order can be argued
  with, per §2.3's rejection of opaque scores.

  **No ranking index was built,** though PLAN §2.3 provisions one in the `work/` layer.
  A full scan with ranking measured 50–60 ms end to end across all four anchors
  (122, 33, 17, 0 posts). An index at that size buys nothing and adds the staleness
  failure mode the plan itself names as its risk. Revisit if a store gets large.

### Fixed
- **`--keyword ""` answered instead of refusing.** `"" in hay` is true for every post
  and `str.count("")` returns `len(s) + 1`, so an empty keyword returned the whole
  store ordered longest-body-first while looking like a search. Now refused, the way
  `edit --summary ""` already is.
- **`subject:` carried a ranking weight no query could reach.** The filter's haystack
  (title, body, keywords, summary) and the ranker's weight table (keywords, title,
  subject, summary) are two readers of one post, and they disagreed — `subject` could
  only ever score when some *other* field had already matched. This is the third time
  in this codebase that two readers of the same data under different rules produced a
  silent wrong answer. `subject` is now in both.
- **The `none` sentinel scored as content.** `keywords: none` means "no keywords" —
  `p.supersedes` already reads it that way — but the ranker matched the literal string.
  Both of the above are now read through one function, `rank.field_text`, so the filter
  and the ranker cannot disagree about what a field says again.
- **A post outranked its own replacement whenever the replacement used different
  words.** The superseded set was built from the *filtered* slice, so a post counted as
  a chain head unless its successor also matched the keyword — and a rewrite that
  changes the vocabulary is exactly the case where it does not. It now reads the
  unfiltered store: a post is superseded by the existence of its successor, not by that
  successor's word choice.

- **A backend override could still hand a role its own family's model**
  (`codeagent-wrapper/internal/adapter/cli/parse.go`). 0.12.0 stopped the *accidental*
  leak by clearing the model on a cross-vendor move; an explicit one still passed.
  `--agent oracle --backend agy --model claude-opus-4-6-thinking` ran at **exit 0** and
  returned a review written by the same family that wrote the code — agy serves Gemini,
  Claude, and GPT-OSS from one CLI, so nothing rejected it. That defeats omo's
  delegation ground 3, which exists precisely to get a judge that did not author the
  work, and it defeats it silently.

  Worse, the gesture that opens it is the *recommended* one: `vendor-ops.md` tells
  callers to keep passing `--model` if their build predates the 0.12.0 fix.

  Now refused, with the reason. The check needs no knowledge of the caller's own model:
  the only reason to move `oracle` off claude is to get off claude, so a cross-vendor
  override that lands back on the home family is decidably a mistake. Family matching is
  by substring (`claude` / `gemini` / `gpt`·`codex`·`terra`) rather than a model list —
  a list that must be updated per release is a guard that silently stops guarding — and
  an unrecognised id passes, since this refuses a *known* self-review rather than
  policing the namespace.

  Measured 2026-08-29: `agy` with no `--model` resolves to Gemini 3.7 Flash, so the
  default path was never affected.

  ⚠️ **Go changes do not ship with the version bump.** `make build` and put the binary
  on PATH, per machine.

- **Five more, found by handing the diff to codex with "attack it, do not write a
  patch".** Eight judgments went in; it rejected five, and all five reproduced. Four of
  them were one root cause — **substring matching where token matching was meant**:

  | Query | What used to lead | Why |
  |:---|:---|:---|
  | `api` | a title reading "capitalization" | `"api" in "capitalization"` |
  | `cat` | a body saying "concatenate" ten times | ten substring hits |
  | `상태` | a post whose keywords are `상자, 태풍` | CJK singletons `상`, `태` scored |
  | `contention measured` | a post holding neither phrase | the filter joined `keywords:` and `summary:` with a space and matched across the seam |

  Fixed at the root: field and body matching is now over **tokens**, the phrase bonus
  needs every term present as a token (not just the substring), CJK emits bigrams and
  keeps singletons only for a one-character query, and the filter tests each field
  separately instead of a joined string.

- **Head preference was a global key, so unrelated posts outranked relevant ones.**
  `is_head` meant "never superseded by anything", not "the head of *this* chain", so any
  never-superseded singleton sorted above a superseded post squarely about the keyword.
  Demoting it to a last tiebreaker then broke the other way — the live `decision/086`
  led the very post that replaced it on a one-point difference. Head preference is now
  **chain-scoped**, which is all PLAN §2.3-2 ever asked for: a superseded post takes its
  own head's position and sits just below it, and keeps its own place when that head did
  not match the query at all.

### Verification
- `python3 -m unittest tests.test_hq tests.test_hooks tests.test_paths_lint` — **185
  pass** (23 new), exit code read directly, not through a pipe. Three tests that pinned
  the pre-attack behaviour were rewritten, not deleted: the capability is corrected,
  not gone.
- Live store, through `bin/hq`, re-run after every fix above: `--keyword graphify`
  leads with `finding/121` (field 22 / body 17) where `finding/088` used to;
  `--keyword 라우팅` leads with `decision/103`; `--keyword 상태` leads with
  `finding/111`; `--keyword om-store-layout` returns the chain head `decision/087`
  first and the post it supersedes, `decision/086`, second — despite `086` scoring
  one point higher.
- `go test ./internal/adapter/cli/...` passes, and the same-family guard was checked by
  **mutation**: disabling it (`if false && …`) makes exactly
  `claude_role_to_agy_on_a_claude_model` fail. A green test is not evidence a guard
  fires. Live: the refused command exits 1 with its reason.
- Output shape for non-keyword queries is unchanged — no `score` key — so omx
  `wiki/query.py`, which shells out to `hq --json query [--status X]`, is unaffected.
  Grepped: no programmatic `--keyword` caller exists outside this repo.

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

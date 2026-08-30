# Vendor Operations

Everything that makes a vendor call fail for reasons unrelated to the task. Read
this before your first `codeagent-wrapper` call in a session; come back to it when
a call returns nothing, hangs, or errors on something that is not your prompt.

Ported from `gaebalai/claude-code-orchestrator` (MIT), which was the only surveyed
repo that kept vendor CLI failure modes in a table. Flags verified against this
repo's `codeagent-wrapper` on 2026-08-26.

## What the wrapper already does

`codeagent-wrapper` (`internal/backend/`) builds the vendor argv for you. Do not
hand-roll the CLI call:

| Concern | Handled where | You pass |
|:---|:---|:---|
| `--skip-git-repo-check` on codex | `backend/codex.go` -- always appended | nothing |
| Effort tier on codex | `backend/codex.go` -- emitted as `-c model_reasoning_effort=<v>` | `--reasoning-effort <tier>` |
| Effort tier on claude | `backend/claude.go` -- emitted as `--effort <v>` | `--reasoning-effort <tier>` |
| Backend + model selection | `config.json` `modules.omo.agents.<role>` | `--agent <role>`, or override with `--backend` / `--model` |
| Prompt delivery | stdin (`-`) or `--prompt-file` | the Context Pack heredoc |
| Watching a call in a panel | `bin/omo-consult` -- Orca tab / tmux split / foreground | `--role`, `--workdir`, `--prompt <file>` |

**A backend override drops the role's model, and that is the point.**
`--agent oracle --backend codex` sends no `--model` at all, so codex picks its own
default. Until 2026-08-29 it did the opposite -- the model switch in
`adapter/cli/parse.go` never looked at whether `--backend` had moved the role off
its own vendor, so `oracle` (claude-bound) built `codex e --model claude-opus-5 …`
and died with HTTP 400 in 14s. Measured twice; passing `--model gpt-5.6-terra`
explicitly was the only thing that worked. On the `agy` backend the same leak
threw no error at all, which is worse: the adversarial-review ground exists to get
a judge that did not author the work, and a silent wrong-model run defeats it with
nothing to notice. If your build predates that fix, keep passing `--model`.
Declaring `--agent` *after* `--backend` still hands the role both its backend and
its model -- the later `--agent` wins the backend, so no mismatch is left to break.

**The prompt-file path restriction binds the role card, not your flag.** A
`prompt_file` coming from the role (default `~/.codeagent/agents/<name>.md`) must
resolve under `~/.claude` or `~/.codeagent/agents`; anything else is refused with
`prompt file must be under ~/.claude or ~/.codeagent/agents` and the run **fails**
-- there is no stdin fallback. A path you pass on the command line with
`--prompt-file`, or set in settings, is marked explicit and is not restricted at
all (`app.go:91` `readAgentPromptFile`, guarded by `PromptFileExplicit`).

Flags the wrapper accepts, verified against `--help` on a build of this repo
(2026-08-27): `--agent`, `--backend`, `--model`, `--reasoning-effort`,
`--prompt-file`, `--output`, `--skills`, `--worktree`, `--parallel`,
`--skip-permissions` (alias `--dangerously-skip-permissions`), `--config`,
`--cleanup`, `--full-output`, `--version`.
**There is no `--timeout`** -- the timeout is the one you give the shell tool that
runs the wrapper. That is by design, not an omission: `RunCodexTaskWithContext`
takes a `timeoutSec` and discards it, waiting for the vendor process to exit, and
`TestRunCodexTaskWithContext_IgnoresWrapperTimeoutAndWaitsForExit` pins it.

The two effort rows are worth reading twice. Until 2026-08-27 the claude row did
not exist -- `buildClaudeArgs` never read `ReasoningEffort` -- so the `reasoning`
value on every claude-backed role was accepted, displayed, and dropped. If you are
reading an older transcript, its claude calls all ran at the CLI default.

## Reasoning effort: pick the tier, then the timeout

The tier drives the cost and the wall clock, so set the shell timeout from the tier
rather than defaulting everything to two hours.

| Tier | Shell timeout | Use for |
|:---|:---|:---|
| `low` | 60s | Mechanical lookups; a question with one right answer |
| `medium` | 180s | Ordinary consultation -- the default when nothing below applies |
| `high` | 600s | Architecture review; the two-failure escape (ground 3) |
| `xhigh` | 900s | Performance optimization; security audit |

A tier above the task wastes the budget quietly -- the call still returns, just
slower and dearer. A tier below it returns a shallow answer that reads finished.

## Effort precedence: two tiers

The role's `reasoning` in `config.json` is the **default**. The task type **overrides
it** when the table above says so — a `develop` call doing a security audit runs
`xhigh` even though its default is already there, and an `oracle` call answering a
mechanical lookup can drop to `low`.

Set it explicitly with `--reasoning-effort` when you override. An override you do
not pass is an override that did not happen.

## Role assignment

`config.json` `modules.omo.agents` binds each role to a backend and model.
**Measured 2026-08-26 on this machine** — the previous table pointed three roles at
CLIs that are not installed:

| Role | Backend | Model | Default effort |
|:---|:---|:---|:---|
| `oracle` | claude | claude-opus-5 | high |
| `security` | codex | gpt-5.6-terra | xhigh |
| `develop` | codex | gpt-5.6-terra | xhigh |
| `librarian` | claude | claude-sonnet-5 | medium |
| `explore` | codex | gpt-5.6-terra | low |
| `frontend-ui-ux-engineer` | claude | claude-sonnet-5 | medium |
| `document-writer` | claude | claude-sonnet-5 | medium |

**Diversity is counted in models, not backends** -- and it is counted against *your
own* model, not just against the previous vendor. A backend running a Claude model
gives you the prior the session already has. That is not hypothetical: `agy models`
lists `claude-sonnet-4-6` and `claude-opus-4-6-thinking` alongside its Gemini models,
so "codex failed, try antigravity" can route straight back into the same family.
Check what a backend resolves to before calling it a second opinion.

**This binds ground 4 as well as ground 3, and ground 4 is where it actually bites.**
Ground 1 fails loudly -- you already know the approach is stuck. Ground 3 fails
silently: `oracle` is `claude-opus-5`, so *an Opus 5 session that calls `--agent
oracle` to review its own work has consulted itself* while believing the rule was
satisfied. There is no error, just an approving answer from your own prior. Before
any ground-3 call, compare the role's model against the model you are running; if
they match, override with `--backend codex` and leave `--model` off so codex picks
the account default. Measured 2026-08-27: that override caught a fabricated
mechanism in the session's own docstring that a same-model reviewer had no reason
to doubt.

A config file cannot fix this, because it cannot know which model the session is.
The check belongs to the session, every time.

`oracle` is Claude and `security` is GPT deliberately. When `oracle` has failed
twice, the escape has somewhere to go.

### Two families in parallel is a gate, not the default

`SKILL.md` ground 4 states the conditions -- shipping in a release, a path where
data can be lost, a change that is hard to undo. This is the operational half.

Open the gate by sending the same prompt against the same commit to two vendor
families at once, and read both before judging either:

```bash
codeagent-wrapper --agent oracle --backend codex - "$PWD" < attack.txt > out-codex.txt &
codeagent-wrapper --agent oracle --backend agy   - "$PWD" < attack.txt > out-agy.txt   &
wait
```

Number every claim from both and record CONFIRMED or rejected **with a reason for
the rejections too** -- a finding dismissed without one is indistinguishable from a
finding nobody read. Measured 2026-08-30 on `b781d4a`: 11 defects reproduced and
fixed, 2 rejected with reasons, almost no overlap between the two families.

Two cautions come with it. `agy` serves `claude-sonnet-4-6` and
`claude-opus-4-6-thinking` alongside its Gemini models, so "codex, then agy" can
land back in the family that authored the work -- check what the backend resolved
to, not what its name suggests. And when both families run, the fair comparison is
the *union* of findings, not each one's hit rate: they are being paid for because
they miss different things.

### What is installed is a per-machine fact -- measure it, do not read it

The table below is one machine's measurement, kept as a worked example of what the
check looks like. **It is not a claim about yours.** This skill ships to every
machine the plugin is installed on, and a claude-only machine -- no codex account,
no antigravity -- is a supported setup: four of the seven roles still work, and
`SKILL.md`'s ladder does not require any of them.

Run the check yourself before the first vendor call, and never install a missing
CLI without asking (see `SKILL.md`, "Before the First Vendor Call"):

```bash
for c in codex claude agy; do printf '%-8s %s\n' "$c" "$(command -v $c || echo '-- absent')"; done
```

Measured 2026-08-27 on the machine this was written on (`command -v`, a build of the
wrapper, and one live call):

| CLI | On PATH | Reachable through the wrapper | Note |
|:---|:---|:---|:---|
| `codex` | yes | yes | ChatGPT-account auth rejects `gpt-5.2` with HTTP 400; the account resolves to `gpt-5.6-terra` |
| `claude` | yes | yes | |
| `agy` (antigravity) | yes, authenticated | **yes**, since 2026-08-29 | `AgyBackend`; see the three flag traps below |
| `gemini` | no | **removed from the registry** (D24) | antigravity is its successor; the CLI no longer authenticates here |
| `opencode` | no | **removed from the registry** (D24) | the old `explore` assignment pointed here |

**`agy` is now a backend.** `internal/backend/registry.go` holds exactly three —
`codex`, `claude`, `agy` — after D24 removed `gemini` and `opencode`. Wiring it was
not the one-line registry edit the decision assumed; three measured differences
(agy 1.1.22, 2026-08-29) each needed their own workaround, and each fails *silently*
if skipped:

1. **agy never reads the prompt from stdin.** `--print` takes it as a flag value:
   bare `--print` dies with `flag needs an argument: -print`, and `--print -` sends
   the literal `-`, which the model answers with a generic greeting at exit 0. omo's
   own invocation form (`codeagent-wrapper --agent X - <workdir> <<EOF`) is exactly
   that path, so `executor.go` forces `useStdin = false` for this backend and
   materialises the prompt into argv. Bounded by ARG_MAX (~1 MB on darwin).
2. **`--effort` accepts only `low|medium|high`.** The role table's `xhigh` is a hard
   error — `invalid --effort "xhigh" (valid: low, medium, high)` — so `agyEffort`
   clamps `xhigh`/`max` to `high` and drops anything unrecognised.
3. **Its stream-json shares no field with the other backends** (everything nests
   under an `event` discriminator), so the parser drops it without erroring. The
   backend therefore runs `--output-format json` and the parser carries an agy
   branch keyed on `conversation_id`/`response`/`error`. That branch must be tested
   **before** the gemini one, which fires on any non-empty `status`.

Resume is `--conversation <id>`, not `-r`. Model names embed the effort tier
(`gemini-3.1-pro-high`), and passing `--model` and `--effort` together is accepted.

`GeminiBackend` and `OpencodeBackend` still compile — the parser, the stderr filter,
and about 80 test lines name them — but `Select()` rejects both, so nothing can
route there. Deleting that code is a separate sweep.

⚠️ **The shipped binary may not have any of this.** `install.sh` downloads a
prebuilt `codeagent-wrapper` from `stellarlinkco/myclaude` — the *upstream* repo —
into `$HOME/.claude/bin`. That build has no `agy` backend and still carries
`gemini`/`opencode`, and it overwrites a local build. Until this fork publishes its
own binary, `agy` works only where someone ran `make install` from this tree.

Until then, the multimodal and long-context work the lane table hands to a vendor
goes to `claude`, not to Gemini.

## Codex

**Not found.** `which codex` / `codex --version`; install with
`npm install -g @openai/codex`.

**Auth.** `codex login`; check with `codex login status`.

**Reasoning floods stderr.** The wrapper reads stdout, so a noisy stderr is
cosmetic -- but it buries real errors. Suppress with `2>/dev/null`, or set
`hide_agent_reasoning = true` in `~/.codex/config.toml`.

**Lost session.** `codex sessions list`, then `codex sessions show <SESSION_ID>`.

**Sandbox errors.**

| Error | Cause | Fix |
|:---|:---|:---|
| `Permission denied` | Writing under a read-only sandbox | Raise to `workspace-write` |
| `Network blocked` | Sandbox restriction | `danger-full-access`, and only deliberately |

**Out of memory on a large codebase.** Narrow the target files, split the analysis
into stages, or lower `--config context_limit=...`. In this harness the first option
is usually right: a read that large is ground 2, and ground 2 wants an inventory
back, not a verdict.

## Gemini and antigravity (`agy`)

**`agy` is reachable through the wrapper since 2026-08-29; `gemini` is not and will
not be** — D24 replaced it rather than keeping both. The limits below are agy's now.

> The two `agy` flag notes at the end of this section predate the backend and were
> already correct. They were then re-derived from scratch during the wiring session
> because nobody read this card first — the failure `feedback_resolved_knowledge_not_in_launch_path`
> names. Read this section before touching an agy call path.

**Free tier limits: 60 requests/minute, 1,000 requests/day.** A fan-out that ignores
this fails partway through and returns a mix of results and rate-limit errors, which
is worse than failing at the start. Count the calls before launching one.

**Auth is per-machine and never assumed.** A binary on PATH does not mean an
authenticated session — verify with one cheap call before routing a role to it. The
survey that declared antigravity "not installed" had looked for a binary named
`antigravity`; the binary is `agy`, and it answered on the first try. A negative
result from the wrong name is not absence.

**`agy` flag notes**, if you call it directly rather than through the wrapper: the
prompt must be attached to the flag (`--print='...'`), because a detached prompt gets
swallowed as the previous flag's value and the real prompt is silently dropped. Use
`--print-timeout` for the wall clock; `--effort` takes `low|medium|high` only, with
no `xhigh`.

## Passing skills to a worker

`codeagent-wrapper --skills <name>` injects a skill card into the worker's prompt.
Four constraints, all read out of `internal/executor/prompt.go`:

1. **The budget is 16,000 characters across every skill passed** (`defaultSkillBudget`,
   roughly 4K tokens). Over budget, a card is **truncated with a warning** rather than
   rejected — so an oversized card fails quietly and looks like it worked.
2. **Cards load only from `~/.claude/skills/<name>/SKILL.md`.** The path is hardcoded;
   a plugin-scoped skill is invisible to it. The installer has to place a copy there.
3. **Names must match `^[a-zA-Z0-9_-]+$`.** A namespaced `plugin:skill` name is
   rejected outright.
4. **YAML frontmatter is stripped** before the body is wrapped in `<skill>` tags.
5. **On a claude backend it is the only path.** `buildClaudeArgs` passes
   `--setting-sources ""`, so a claude worker loads no user- or project-scope skill
   and no repo `CLAUDE.md` (measured 2026-08-27). The `context-loader` design in
   `shared-context.md` therefore covers codex, gemini, and antigravity only; for
   `oracle`, `librarian`, `frontend-ui-ux-engineer`, and `document-writer` the rules
   have to ride in the prompt, inside the 16,000-character budget above.

Measured against our own cards on 2026-08-26:

| Card | Chars | Fits |
|:---|---:|:---|
| `skills/omo/SKILL.md` | 10,109 | yes, leaving ~5,900 |
| `skills/harness/SKILL.md` | 28,261 | **no — 1.8x the whole budget** |

The harness card not fitting is correct rather than a defect. It is written for the
*session* running the campaign, which loads skills natively with no budget. A vendor
worker does not need the campaign protocol; it needs its own obligations, and those
arrive through the vendor-side `context-loader` reading the store's `rules/`
(5,175 characters for all five slots) plus the role card the SubagentStart hook
injects. Do not pass `harness` through `--skills`.

**Auto-detection is not worth extending.** `techSkillMap` in `prompt.go` is a
five-entry hardcoded list keyed on `go.mod`, `Cargo.toml`, `pyproject.toml`,
`package.json`, and the Vue configs. Adding `.tex` or `.pptx` rows means a Go change
and a rebuild for every OS this ships to. Pass `--skills` explicitly instead; build a
release pipeline when explicit passing becomes the thing that hurts, not before.

## Reading a vendor result

- **The result is advice, not a result.** Verify it against the repo before acting.
  A confident file:line from a vendor is still a claim.
- **An empty return is a failure, not a "no".** Check the exit code and stderr
  before reporting that the vendor found nothing.
- **A vendor cannot see your session rules.** It does not inherit the output style,
  the language protocol, or the project conventions unless the shared knowledge
  store loaded them on its side. See `shared-context.md`.

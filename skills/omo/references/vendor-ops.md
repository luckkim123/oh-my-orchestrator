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
| `model_reasoning_effort` | `backend/codex.go` -- emitted as `-c model_reasoning_effort=<v>` | `--reasoning-effort <tier>` |
| Backend + model selection | `config.json` `modules.omo.agents.<role>` | `--agent <role>`, or override with `--backend` / `--model` |
| Prompt delivery | stdin (`-`) or `--prompt-file` | the Context Pack heredoc |

Flags the wrapper accepts: `--agent`, `--backend`, `--model`, `--reasoning-effort`,
`--prompt-file`, `--output`. **There is no `--timeout`** -- the timeout is the one
you give the shell tool that runs the wrapper.

## Reasoning effort: pick the tier, then the timeout

The tier drives the cost and the wall clock, so set the shell timeout from the tier
rather than defaulting everything to two hours.

| Tier | Shell timeout | Use for |
|:---|:---|:---|
| `low` | 60s | Mechanical lookups; a question with one right answer |
| `medium` | 180s | Ordinary consultation -- the default when nothing below applies |
| `high` | 600s | Architecture review; the two-failure escape (ground 1) |
| `xhigh` | 900s | Performance optimization; security audit |

A tier above the task wastes the budget quietly -- the call still returns, just
slower and dearer. A tier below it returns a shallow answer that reads finished.

## Role assignment

`config.json` `modules.omo.agents` binds each role to a backend and model:

| Role | Backend | Model |
|:---|:---|:---|
| `oracle` | claude | claude-opus-4-5 |
| `librarian` | claude | claude-sonnet-4-5 |
| `explore` | opencode | opencode/grok-code |
| `develop` | codex | gpt-5.2 (`xhigh`) |
| `frontend-ui-ux-engineer` | gemini | gemini-3-pro-preview |
| `document-writer` | gemini | gemini-3-flash-preview |

Diversity is counted in *models*, not backends: a backend that runs a Claude model
gives you the same prior the session already has, so it does not satisfy ground 1.
Check what a backend actually resolves to before calling it a second opinion.

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

## Gemini

**Free tier limits: 60 requests/minute, 1,000 requests/day.** A fan-out that ignores
this fails partway through and returns a mix of results and rate-limit errors, which
is worse than failing at the start. Count the calls before launching one.

**Auth is per-machine and not assumed.** A `gemini` binary on PATH does not mean an
authenticated session; verify before routing a role to it.

## Reading a vendor result

- **The result is advice, not a result.** Verify it against the repo before acting.
  A confident file:line from a vendor is still a claim.
- **An empty return is a failure, not a "no".** Check the exit code and stderr
  before reporting that the vendor found nothing.
- **A vendor cannot see your session rules.** It does not inherit the output style,
  the language protocol, or the project conventions unless the shared knowledge
  store loaded them on its side. See `shared-context.md`.

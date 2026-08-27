# Shared Knowledge Store

The one axis where `gaebalai/claude-code-orchestrator` (MIT) beats upstream
`myclaude`, and the reason it is ported here.

## The problem it solves

`myclaude` has no shared state that outlives a task. The `omo` Context Pack is an
inline heredoc, so it lives for exactly one call. Upstream's `do` module (not
carried into this fork) kept `.claude/do-tasks/<task>/*.jsonl`, which lived for
exactly one task. When the task ends,
nothing remains. A vendor you consulted twice about the same subsystem learns it
twice.

Worse, a per-call payload is **truncatable**. Prompt injection through argv or stdin
competes with the task text for the same budget, and the rules lose. Measured on
claude 2.1.239, injected context above 10,000 characters is truncated: 9,800 arrives
whole, 10,400 does not.

## Four pieces, and why one alone does nothing

| Piece | What it is |
|:---|:---|
| ① The store | `rules/`, `HUB.md`, and the post store, with asymmetric write permission. Layout is owned by `harness/references/store-spec.md` §3 |
| ② The vendor-side loader | A `context-loader` skill attached to the *vendor's own session config*, so it loads every task |
| ③ The payload | Five rule slots: coding principles, language, safety, evidence, domain |
| ④ Per-project pruning | Drop the slots a project does not need; tailor `domain.md` |

Port the loader without the payload and you get an empty loader. Port the payload
without the loader and it is a per-call injection again -- the exact failure above.
Port both without the asymmetric write rules and vendors overwrite each other's
notes. The set is the unit.

**② may matter more than ①.** The store is a place to put knowledge; the loader is
what makes a vendor a worker in *this* harness instead of a stranger who happens to
answer questions. That difference is what the whole inversion rests on: the session
executes, the vendors advise *from the same rules*.

## Layout

**Owned by `harness/references/store-spec.md` §3.** What this file adds is the payload
that lives inside it:

```
  rules/
    coding-principles.md          ┐
    language.md                   │ the payload -- loaded on every vendor task
    safety.md                     │
    evidence.md                   │
    domain.md                     ┘ project-specific; delete if there is none
```

Seed it from `templates/orchestration/`.

**There is no `knowledge/` directory.** It held `libraries/<name>.md` and
`research/<topic>.md` and has been absorbed into the post store: a verified fact is a
post carrying `harness:`, `verified:`, and a `subject:` whose supersede chain names the
current answer. See `store-spec.md` §4 for the schema and §Knowledge goes stale below for
the discipline, which survived the move intact.

## Write permission is asymmetric on purpose

| Path | Writer |
|:---|:---|
| `rules/` | The Claude session only |
| `HUB.md` decision table | The session, and any vendor -- append a row, never rewrite one |
| A post's body | Its author, on a git anchor; nobody, on a no-git anchor (supersede instead) |
| A post's `## Comments` | Anyone -- append only, never rewrite |

A vendor that can rewrite the rules it was given is not constrained by them.

## Installing the loader per vendor

| Vendor | Files | Source |
|:---|:---|:---|
| codex | `.codex/config.toml` with a `[[skills.config]]` block per skill, plus `.codex/skills/{context-loader,decision-record}/` | `templates/vendor/codex/` |
| gemini | `.gemini/settings.json` with `experimental.skills = true`, plus `.gemini/skills/{context-loader,decision-record}/` | `templates/vendor/gemini/` |
| antigravity | `.agents/skills/{context-loader,decision-record}/` — **project scope only** | `templates/vendor/antigravity/` |
| claude | **The session-config loader does not work here.** `backend/claude.go` passes `--setting-sources ""` to break the recursion loop, which also disables every user- and project-scope skill and the repo `CLAUDE.md`. Pass the rules with `--skills` instead | -- |

**The antigravity row was measured 2026-08-27 and lost its user-scope half.** It
previously also named `~/.gemini/antigravity-cli/skills/`, carrying a banner saying the
paths were unverified because the CLI was absent when the row was written. `agy` is
installed now, and the measurement reverses that half twice over:

- **The path does not exist.** `~/.gemini/antigravity-cli/` holds `builtin/`, `plugins/`,
  `brain/`, `conversations/`, `log/` — no `skills/`. `builtin/skills/` does exist but
  carries a `.checksum` and holds agy's own shipped skills (`agy-customizations`,
  `antigravity_guide`), so it is replaced on update: a cache, not an install target.
- **The nearest real user-scope directory belongs to everyone.** `~/.agents/skills/` is
  live, but its `.skill-lock.json` is the `vercel-labs/skills` cross-agent format and its
  `lastSelectedAgents` lists `amp, antigravity, antigravity-cli, cline, codex, cursor,
  deepagents, gemini-cli, github-copilot, ...`. Installing one project's loader there
  pushes that project's rules into every agent on the machine — the opposite of what a
  per-project loader is for.

The project-scope path is confirmed by agy's own shipped documentation rather than by
inference: `builtin/skills/agy-customizations/SKILL.md:42` gives the customization root
as `.agents/` (or `.agent/`, `_agents/`, `_agent/`) **at the root of the project**, and
`docs/skills.md:10` places skills at `<root>/skills/<name>/SKILL.md`.

One thing that row does not carry, worth knowing when piece ① is wired for this vendor:
agy reads rules from `GEMINI.md`, `AGENTS.md`, and `.agents/rules/*.md`
(`agy-customizations/SKILL.md:49`) — `.agents/rules/` is the direct analogue of this
store's `rules/`.

**The claude row is the exception that costs something.** Measured 2026-08-27 with
`claude --setting-sources "" -p`: only built-in skills are listed, and the repo
`CLAUDE.md` does not appear in the loaded instructions. So piece ② -- the whole
reason a vendor is a worker rather than a stranger -- is unavailable on the one
backend four of the seven roles use. What is left is `--skills`, which is prompt
injection under a 16,000-character budget (`vendor-ops.md`), i.e. exactly the
truncatable per-call payload this store exists to replace.

Do not resolve this by dropping `--setting-sources ""`. It is the recursion guard:
without it the invoked Claude loads the rules that call `codeagent-wrapper` and
calls it again. The tension is real and unresolved -- when a claude-backed
consultation needs the rules, pass them with `--skills` and treat the answer as
coming from a worker that saw a truncatable copy.

## Two skills go to the vendor side

`context-loader` reads the store on every task. `decision-record` writes back to it:
a vendor that can read the decisions but never add one makes the store
one-directional, and whatever it concluded dies with the call. Protocol and row
format: `decision-record.md`.

## Pruning the payload per project

Ship the slots the project needs and delete the rest. A rule that does not apply
still costs tokens on every single vendor call, and a slot full of irrelevant
instruction teaches the worker that the rules are noise.

| Project shape | Payload |
|:---|:---|
| Code | All five. `domain.md` carries the test command and the generated directories. |
| Paper | Drop nothing, but `domain.md` becomes citation discipline -- never invent a reference, equations in English, which `.bib` entries are verified. |
| Documents | `domain.md` carries the template and the verification gate. `coding-principles.md` usually still applies to any build scripts. |
| Data / experiments | `domain.md` carries the dataset registry, checksum discipline, and what counts as split leakage. |

`domain.md` is the only slot meant to be rewritten per project. If a project has no
domain rules, delete the file rather than shipping the placeholder: an empty rule
reads as "no rules here", which is a different claim from "not written yet".

## Knowledge goes stale, and nothing notices on its own

A store with no re-check verb accumulates confident wrong answers. The symptom is
visible in the sibling harnesses: an observation sat at `stuck_candidate` for 75 days
because nothing ever asked whether it still held.

The fix here is a rule, not a tool. Every post carrying a verified fact fills the
frontmatter field

```
- verified: YYYY-MM-DD (against <version|commit>)
```

which is the same discipline the old `> Last verified:` banner carried, moved into a
field a linter can read.

**Before relying on one of these posts, compare that version to what is installed.**
If they differ, the file is suspect: use it as a lead, verify the specific claim you
need, and update the banner in the same pass. If they match, the file stands.

Three rules keep this from rotting:

1. **A stale entry is superseded, never deleted.** Write the new post with
   `supersedes:` naming the old one; the old post stays on disk and stays reachable.
   Deletion loses the record that someone checked, and the next reader re-derives it
   from scratch. (Pre-migration stores did this with a `> (stale as of YYYY-MM-DD:
   <what changed>)` banner — the supersede chain is that banner, made queryable.)
2. **Re-verification is part of the task that needed the post,** not a separate
   cleanup someone will do later. "Distill later" measured at zero follow-through,
   and so does "re-check later".
3. **A version bump alone is not verification.** Advancing `verified:` without
   re-running the check that produced the claim converts an old fact into a fresh
   lie.

Posts carrying external research (`topic: reference`) follow the same rule. Their
staleness clock is the source's publication date, not a package version.

## Vendor worker permissions

`templates/orchestration/settings/worker-permissions.json` carries an 11-entry
`deny` block -- `.env`, `*.pem`, `*.key`, `credentials*`, `*secret*`, `~/.ssh`,
`~/.aws`, `~/.config/gcloud`, and bare root deletes. Merge it into the
`.claude/settings.json` that claude-backend workers run under. `deny` wins over
`allow`, so it holds whatever the surrounding settings permit.

The matching `allow` list is deliberately not ported: allow-lists belong to whatever
renders the project's own settings, and two sources writing one allow-list conflict.

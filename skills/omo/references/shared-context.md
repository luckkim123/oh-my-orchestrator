# Shared Knowledge Store

The one axis where `gaebalai/claude-code-orchestrator` (MIT) beats upstream
`myclaude`, and the reason it is ported here.

## The problem it solves

`myclaude` has no shared state that outlives a task. The `omo` Context Pack is an
inline heredoc, so it lives for exactly one call. The `do` module's
`.claude/do-tasks/<task>/*.jsonl` lives for exactly one task. When the task ends,
nothing remains. A vendor you consulted twice about the same subsystem learns it
twice.

Worse, a per-call payload is **truncatable**. Prompt injection through argv or stdin
competes with the task text for the same budget, and the rules lose. Measured on
claude 2.1.245, injected context above roughly 10,000 characters is dropped.

## Four pieces, and why one alone does nothing

| Piece | What it is |
|:---|:---|
| ① The store | `.orchestration/rules/`, `.orchestration/HUB.md`, `.orchestration/knowledge/{libraries,research}/`, with asymmetric write permission |
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

```
.orchestration/
  HUB.md                          human-readable prose: goal, the user's words
                                  verbatim, the decision table, artifact map
  rules/
    coding-principles.md          ┐
    language.md                   │ the payload -- loaded on every vendor task
    safety.md                     │
    evidence.md                   │
    domain.md                     ┘ project-specific; delete if there is none
  knowledge/
    libraries/<name>.md           verified library behavior (fixed section order)
    libraries/_TEMPLATE.md        the section schema
    research/<topic>.md           external research results
```

Seed it from `templates/orchestration/`.

## Write permission is asymmetric on purpose

| Path | Writer |
|:---|:---|
| `rules/` | The Claude session only |
| `HUB.md` decision table | The session, and any vendor -- append a row, never rewrite one |
| `knowledge/research/` | Whichever role was asked to research |
| `knowledge/libraries/` | Whoever verified the behavior |

A vendor that can rewrite the rules it was given is not constrained by them.

## Installing the loader per vendor

| Vendor | Files | Source |
|:---|:---|:---|
| codex | `.codex/config.toml` with `[[skills.config]] path = ".codex/skills/context-loader"`, plus that skill directory | `templates/vendor/codex/` |
| gemini | `.gemini/settings.json` with `experimental.skills = true`, plus `.gemini/skills/context-loader/` | `templates/vendor/gemini/` |
| antigravity | `.agents/skills/context-loader/`, and `~/.gemini/antigravity-cli/skills/` for the user-scope copy | `templates/vendor/antigravity/` |
| claude | Nothing to install -- a claude-backend worker reads `.orchestration/` directly | -- |

**The antigravity paths are unverified.** The CLI was not installed on the machine
where this was written, and `agy plugin import claude` was never run. Treat that row
as a plan, not a measurement, until someone confirms it.

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

## Vendor worker permissions

`templates/orchestration/settings/worker-permissions.json` carries an 11-entry
`deny` block -- `.env`, `*.pem`, `*.key`, `credentials*`, `*secret*`, `~/.ssh`,
`~/.aws`, `~/.config/gcloud`, and bare root deletes. Merge it into the
`.claude/settings.json` that claude-backend workers run under. `deny` wins over
`allow`, so it holds whatever the surrounding settings permit.

The matching `allow` list is deliberately not ported: allow-lists belong to whatever
renders the project's own settings, and two sources writing one allow-list conflict.

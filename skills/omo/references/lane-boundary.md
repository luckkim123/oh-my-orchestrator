# Lane Boundary

This harness runs alongside domain harnesses — papers, documents, experiments,
project governance. The question this file answers is not *which* of them handles a
task, but **what a vendor worker may be handed once one of them is running**.

One rule decides it:

> **A vendor gathers, investigates, and rebuts. The lane judges, generates, and
> writes the artifact.**

The reason is not politeness about ownership. Each lane has an integrity gate that
exists precisely because a plausible-looking wrong answer is expensive there — an
invented citation, a corrupt `.pptx`, a fabricated metric. Those gates live inside
the lane. A vendor that produces the artifact directly has routed around the gate,
and the output still *looks* finished.

| Lane | A vendor may be handed | Never delegated |
|:---|:---|:---|
| Paper | related-work sweeps over a large corpus, deep reads of one PDF | **citation generation** — a fabricated reference survives review and is unrecoverable |
| Document | reading rendered PNGs of every slide, gathering source material | the integrity gate — zip CRC, engine parse, dangling rels |
| Experiment | sweeping large logs and run outputs | the wiki SSOT and report parsing — a number that entered unsourced is worse than a missing one |
| Code | reading a subsystem too wide to hold, adversarial review | — |
| Governance | — | everything. File moves follow a safety procedure that cannot be handed to a process that will not verify the destination |

**Governance delegates nothing.** Its whole content is the careful sequence around
irreversible operations — move, verify the destination, only then delete. A worker
that reports "moved" without the verification step has produced the exact failure the
procedure exists to prevent, and the files are already gone.

## What "gather" means concretely

A gathering task returns **material with provenance**, not a conclusion:

- **Good**: "these 14 files call `serialize()`; here are the call shapes" — the
  session decides which are wrong.
- **Good**: "this paper's method section claims X, measured on Y, table 3" — the
  session decides whether to cite it.
- **Bad**: "I added the citation" — the lane's gate never ran.
- **Bad**: "the regression is caused by the scheduler change" — a conclusion with no
  evidence trail is a claim the session now has to re-derive.

Every returned fact carries where it came from: `file:symbol`, a commit sha, a page
number. **Cite symbols, not line numbers** — line numbers drift silently, and 4 of 4
line-cited anchors had moved on recheck.

## Detect the project type, then prune

Before the first vendor call in a project, work out what it produces and cut the
payload to match. A rule that does not apply still costs tokens on every single
call, and a slot full of irrelevant instruction teaches the worker that the rules
are noise.

| Signal in the tree | Type | Prune to |
|:---|:---|:---|
| `.tex`, `.bib`, a venue template | Paper | `domain.md` becomes citation discipline. Drop the code-review role from the roster. |
| `.pptx`, `.docx`, a style spec | Document | `domain.md` carries the template and the verification gate. |
| run directories, eval outputs, a dataset registry | Experiment | `domain.md` carries checksum discipline and what counts as split leakage. |
| `go.mod`, `pyproject.toml`, `package.json`, `Cargo.toml` | Code | all five slots as shipped; `domain.md` gets the test command and the generated directories. |
| none of the above | Unknown | **ask, do not guess.** Shipping the code payload to a writing project is how the rules become noise. |

**Propose the pruning; do not apply it silently.** The user sees one line — "this
looks like a paper project, so I am dropping the code-review role and adding the
citation card" — and can say no. A payload quietly trimmed is a payload nobody can
audit when a worker later does something the missing rule would have prevented.

If a project has no domain rules at all, delete `domain.md` rather than shipping the
placeholder. An empty rule file reads as "there are no rules here", which is a
different and wrong claim.

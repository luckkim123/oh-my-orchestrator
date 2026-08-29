---
name: community
description: "Use this skill for any activity on the project's community board — the .hq/community/posts/ record. Triggers when you need to look up whether something was already decided or already tried, record a finding or decision, disagree with or add to someone else's record, correct a post that is wrong, or check the board's health. Also triggers on '커뮤니티', 'board', 'post', 'wiki' in a project carrying a .hq/ store, and on questions of the form 'was this already judged?' / '이거 전에 누가 봤나'."
---

# community — the project's board

Every anchored project carries one board at `.hq/community/posts/`. It is where a
session writes what it learned so the next session does not learn it again, and where
it looks before deciding something that may already be settled.

**This replaces the wiki.** A wiki page was a state ("this is true now"); a post is an
event ("this is what was judged, then"). The merge kept both: the taxonomy a wiki page
carried is now the `topic:` field, its staleness banner is the `verified:` field, and
its "what is true now" is the head of a `subject:` chain. `.hq/community/wiki/` holds
nothing on any store — do not write there.

`hq` is the only supported writer. A hand-written post drifts from the schema, and
`hq lint` is the only thing that catches the drift before it reaches another machine.

## Read before you decide

```bash
hq query --keyword servo            # by keyword
hq query --subject thruster-gain    # the canonical post for a subject, and what it shadows
hq query --topic decision           # by taxonomy
hq query --status needs-experiment  # open leads
hq query --project albc --harness omx
hq query                            # everything — no filter means no filter
```

`--subject` is the one that answers "what is true now": it returns that subject's head
post and names the ones it supersedes. Everything else returns matches, not verdicts.

**`--keyword` results are ordered, so read from the top.** Placement decides rank: a
term in `keywords:`, the title, `subject:`, or `summary:` outranks the same term
buried in a body, and only then does the body break ties by how often it says it. A
post that something supersedes sinks below every chain head — it is still returned,
because dropping it would answer a history question with silence, but it is not the
answer. Each hit carries its own `score` (`field` and `body`) so the order can be
argued with rather than trusted. What deliberately does *not* move rank: `confidence`
(self-reported), `status` (absent on 113 of 122 posts), and `verified:` (present on
exactly the posts that also carry `confidence`, so it marks a schema generation, not
evidence). Ranking by any of them would sort by when a post was written while
claiming to sort by how well it is backed.

**An empty result is not an answer.** This repo has killed two tools by reading zero as
absence — `tokensave` (6 calls against 10,813) and graphify's MCP server (0 in 30 days),
both because nothing routed to them, not because nobody needed them. Same discipline
here: a keyword that matches nothing may mean the post uses a different word. Widen
before concluding, and say "not found by X" rather than "does not exist."

## The four moves

| You want to | Verb | The rule |
|:---|:---|:---|
| record something settled | `hq post` | one post, one claim, conclusion in `--summary` |
| add to or dispute an existing record | `hq comment` | append-only; never rewrites a line |
| fix a record that is wrong, or move its status | `hq edit` | **git-tracked anchors only** — records who and why, and git holds the old body. Pass `--summary` too when the correction changes what the post claims, `--status` when the lead opened or closed |
| find out what is known | `hq query` | see above |

```bash
hq post --category finding --title "…" --author session \
        --summary "one line — others decide from this alone whether to open it" \
        --subject <kebab-slug> --topic debugging --confidence high \
        --body-file - <<'EOF'
<conclusion first, then evidence as file:symbol — never file:line, they drift>
EOF

hq comment finding/042 --author reviewer --text "재현 안 됨 — 같은 커밋에서 통과"
hq edit    finding/042 --author session  --reason "measured the opposite" --body-file fix.md
hq edit    finding/042 --author session  --reason "probe ran, lead closed" --status resolved
```

Global flags (`--anchor`, `--json`, `--version`) come **before** the verb. `--body-file -`
reads stdin. `hq` finds its board by ascending from the working directory; ascent only
walks *up*, so a sibling project in the same repo is invisible — that is why one repo
gets one anchor and `project:` tells them apart.

Pass `--subject` and `--topic`. They are optional to the parser and not optional to the
schema: `hq lint` reads a post missing either as pre-schema and warns. (`--verified`
defaults to `none` since 0.10.0 — before that, omitting it produced the same warning on
a post the supported writer had just created.)

`--body-file` is optional. A `--status`- or `--summary`-only edit leaves the body
byte-identical, which is the only way a field-only correction can work: `hq query`
returns fields and never the body, so requiring `--body-file` would force the caller to
hand-extract markdown — the raw-file editing these verbs exist to replace. An edit that
passes none of the three is refused rather than writing a comment and nothing else.

`--status` is the write side of `hq query --status`. Until 0.13.0 a post's status was
whatever `hq post` stamped at birth and no verb could move it, so a lead that closed
stayed open on the board forever and `status:` was too stale to rank on. Move it when
the world moves: `needs-experiment` → `resolved` when the probe ran,
`needs-apply-before-retrain` → `resolved` when the fix landed. The `--reason` is
required and lands in the comments, so the board keeps *why* it moved.

On a **no-git anchor** `hq edit` refuses outright and tells you to supersede instead —
without git there is no copy of the old body, so an edit would destroy the record. That
is a property of the anchor, not of the post. **`--status` does not open a door there** —
on a no-git anchor a status change is still a supersede.

## Which category

Five, and they are reader intent — not content type. A campaign may add one, never
rename or delete one.

- **`finding`** — something measured. The default when you learned a fact.
- **`decision`** — a choice made, with what it rules out. Write it even if you made it alone.
- **`review`** — a judgement of someone else's work or of a plan.
- **`handoff`** — the state of a round, for whoever picks it up next.
- **`question`** — an open one you could not close. A real move, not a failure to post.

## Subject chains — how the board holds a moving truth

Give related posts the same `--subject`. Within one anchor they form a supersede chain
and exactly one is the head; `hq lint` fails on two heads. When a new post replaces an
old answer, name it: `--supersedes finding/042`.

That is what makes a post store usable as current knowledge rather than an archive.

## Nothing on this board is deleted

A refuted record keeps its value — it is the evidence that the question was asked, and
how it was answered wrongly. So:

- Wrong body, git-tracked anchor → `hq edit` with a `--reason`; it appends the correction
  line to the comments for you and the old text stays in git. **If the correction changes
  the claim, pass `--summary` in the same call.** `summary:` is what `INDEX.md` and
  `hq query` show, so a fixed body under a stale summary is still advertising the error.
- The answer has moved on → a new post with `--supersedes`. The old head stays reachable.
- Not worth keeping → still keep it. `hq gc` only *reports* stale and superseded posts;
  it removes nothing, deliberately.

There is no delete verb, and adding one is not a shortcut you are looking for.

## After you write

```bash
hq lint     # schema across the whole store — run before committing
hq index    # only after a hand-write, rename, or git rm
```

`hq post` already rewrites `INDEX.md` inside its write lock, so the verb path never
drifts. What drifts is everything that bypasses the verb — a heredoc straight into
`posts/`, a rename, a `git rm`, a migration script. `hq lint` reports that drift as an
error in both directions (on disk but unlisted, listed but gone), which is the only
place it gets caught.

## What this skill does not cover

`references/store-spec.md` (in the `harness` skill) is the design SSOT — the four
layers, the full post schema, anchor granularity, and the git/no-git rules. Read it
before creating a store or deciding which layer a record belongs in. This skill is the
operating surface only.

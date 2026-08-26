# Decision Record

A design question settled in conversation and written nowhere is a question that
gets re-asked, re-argued, and eventually answered differently. `.orchestration/HUB.md`
carries the decision table so that does not happen -- and so a vendor loading the
shared context sees what this project already settled before it advises against it.

Ported in concept from cco's `design-tracker` and `update-design` (MIT).

## Two entry points, one workflow

cco shipped these as two skills because its explicit twin set
`disable-model-invocation: true`. Ours is one protocol reached two ways:

- **Proactively.** When a decision gets made -- an architecture choice, a library
  selection, a pattern settled, a tradeoff resolved -- record it without being asked.
  Waiting for the user to say "write that down" means most decisions never land.
- **On demand.** When the user says to record it, or asks what was decided, run the
  same steps against the current conversation.

Both write the same row to the same table. The difference is what starts it.

## What counts as a decision

Record it when **all three** hold:

1. A choice was made between real alternatives. "We used the stdlib" is not a
   decision; "we used the stdlib over `requests` because the install footprint
   matters here" is.
2. Someone later could reasonably choose otherwise. If there is only one sane
   option, the code already says so.
3. Reversing it would cost something -- a migration, a rewrite, a re-argument.

Do not record: task progress, what you implemented, a bug you fixed. Those are the
commit log's job. A decision table that fills up with activity stops being read.

## Row format

```markdown
| # | Date | Decision | Because | Reversal cost | By |
|:--|:-----|:---------|:--------|:--------------|:---|
| D7 | 2026-08-26 | The session executes; vendors advise | A round trip drops the context that made the edit correct | Rewrite of the omo skill and all six role cards | claude |
```

- **Decision** states what was chosen, in the affirmative. Not "we discussed X".
- **Because** carries the reason that would have to stop being true for the decision
  to change. That is what makes the row re-readable a month later.
- **Reversal cost** is why the row exists. A free-to-reverse decision does not need
  a table.
- **By** names the role or vendor that settled it, so a later reader knows whose
  prior it came from.

Numbers are globally monotonic and never reused. **Append only.** A decision that
gets overturned gets a *new* row that names the one it supersedes; the original stays
so the reasoning trail survives.

## Who may write

Any role that settles a design question may append a row -- including a vendor. That
is the point of mirroring this protocol into `templates/vendor/*/skills/`: a vendor
that can read the decisions but not add to them makes the store one-directional, and
its conclusions die with the call.

Nobody rewrites an existing row. Nobody, vendor or session, edits
`.orchestration/rules/` -- see `shared-context.md` for the full write table.

## Before recording, check

Read the existing table first. If the decision contradicts a row, say so explicitly
and argue against that row by number. A contradiction recorded as if it were a fresh
decision is how a project ends up with two answers and no memory of the argument.

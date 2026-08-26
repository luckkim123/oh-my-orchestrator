---
name: decision-record
description: Record design decisions into .orchestration/HUB.md without being asked. Activate when a choice is settled between real alternatives -- architecture, library selection, pattern, or a resolved tradeoff -- and when asked to record one or asked what was decided.
---

# Decision Record

You can append to this project's decision table. Use it when you settle a design
question, so the conclusion outlives this call.

## When

**All three** must hold:

1. A choice was made between real alternatives.
2. Someone later could reasonably choose otherwise.
3. Reversing it would cost a migration, a rewrite, or a re-argument.

Do not record task progress, what got implemented, or a bug that got fixed. Those
belong to the commit log. A decision table full of activity stops being read.

## How

1. **Read the existing table in `.orchestration/HUB.md` first.** If your conclusion
   contradicts a row, say so and argue against that row by number. Recording a
   contradiction as if it were fresh leaves the project with two answers.
2. Append one row. Never rewrite an existing one.
3. Number it one past the highest existing number. Numbers are never reused.

```markdown
| # | Date | Decision | Because | Reversal cost | By |
|:--|:-----|:---------|:--------|:--------------|:---|
| D8 | YYYY-MM-DD | what was chosen, affirmatively | the reason that would have to stop being true | what undoing it costs | your role name |
```

**Because** is the load-bearing column. Write the condition that would have to change
for the decision to change -- not a restatement of the decision.

## Not yours

- `.orchestration/rules/` -- read-only to you.
- Any existing row -- append only. A decision that is overturned gets a new row
  naming the one it supersedes.
- Deciding on the human's behalf. Record what was settled; do not settle what was
  left open.

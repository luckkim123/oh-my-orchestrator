---
name: context-loader
description: ALWAYS activate at the start of every task. Loads shared project context from .orchestration/ -- coding rules, recorded decisions, library constraints -- before executing anything.
---

# Context Loader

## Purpose

Load the shared project context from `.orchestration/` so this session works from the
same rules as the Claude session that called it.

## When to activate

**Always**, at the start of every task, before reading the task itself.

## Steps

1. **Read every file in `.orchestration/rules/`.** These are the constitution:
   `coding-principles.md`, `language.md`, `safety.md`, `evidence.md`, and
   `domain.md` when present. A project that tailored its payload may ship fewer;
   read what is there and do not assume a missing slot is empty.

2. **Read `.orchestration/HUB.md`.** The decision table is the record of what this
   project already settled. Contradicting a recorded decision without saying so is
   the most expensive mistake available to you -- if your analysis contradicts one,
   name the decision and argue against it explicitly.

3. **If the task names a library, look for a post about it.** Search the post store
   for one whose `keywords:` or `subject:` names that library. Its constraints and
   avoid-patterns override your defaults for this project. Check its `verified:` field
   against the installed version before relying on it -- a stale post is a lead, not
   an answer.

4. **If the task is research-shaped, search the post store before searching outside.**
   Someone may already have answered it; a post with `topic: reference` is exactly that.

## Write access

Asymmetric, and it matters:

| Path | Who writes |
|:---|:---|
| `.orchestration/rules/` | The Claude session only. Read-only to you. |
| `.orchestration/HUB.md` decision table | The session, and you -- append a row when you settle a design question. Never rewrite an existing row. |
| A post's body | Its author. On a repo without git, nobody -- correct it by writing a new post whose `supersedes:` names the old one. |
| A post's `## Comments` | You, and anyone. Append only; never rewrite someone else's line. |
| Everything else in the repo | Per your role card. |

## Confirm

After loading, state in one line: which rule files you read, whether HUB.md had a
decision bearing on this task, and any library or research note you pulled. If
`.orchestration/` does not exist, say so and proceed on the task alone -- an absent
store is a fact to report, not a reason to stop.

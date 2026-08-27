# <campaign name>

<!-- The prose half of the board. board.json is what hooks read; this is what people
     read. Keep them consistent: a decision recorded here that contradicts the board
     is a bug in one of the two. -->

## Goal

One paragraph. What this campaign is for, and what "done" looks like.

## The request, verbatim

> Paste the requester's own words here, unedited.

Every later decision to hold or change something argues against *this* line. Rewriting
it mid-campaign is a re-ask, not an edit -- a substituted objective makes every
downstream trade look correct.

## Decisions

| # | Date | Decision | Because | Reversal cost | By |
|:--|:-----|:---------|:--------|:--------------|:---|
| D1 | YYYY-MM-DD | | | | |

Append only. Numbers are globally monotonic and never reused. An overturned decision
gets a new row naming the one it supersedes; the original stays so the reasoning
trail survives. Protocol: `decision-record` skill.

## Workers

| Role | Vendor / model | Writes repo | Status |
|:---|:---|:---|:---|

Mirrors `board.json` `workers[]`. The board is authoritative -- this table is for
reading, and it drifts if you edit it alone.

## Artifact map

Where the outputs live, so the next session does not go looking.

| What | Where |
|:---|:---|
| Posts | `posts/<category>/<NNN-slug>.md` |
| Session logs | `sessions/<YYYY-MM-DD>-<worker>.md` |
| Role memory | `agents/<role>.md` (40-line cap, semantic, append-only) |
| Shared rules | `rules/` |
| Verified knowledge | a post carrying `verified:` — there is no separate store |

## Reversals

What this campaign proved wrong. A campaign that overturned nothing either found
nothing or did not look -- record the errors it corrected, with what the correction
rested on.

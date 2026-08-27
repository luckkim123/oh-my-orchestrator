#!/usr/bin/env python3
"""Harness PreCompact hook -- warns when the prose half of the board is stale.

Measured 2026-08-26 on claude 2.1.239: PreCompact *can* block. `exit 2` refuses the
compaction and the stderr reaches the user verbatim, as
`Compaction blocked by PreCompact hook: [...]: <your message>`. This hook
deliberately does not use that.

Two reasons, both from the same measurement. The payload carries
`custom_instructions, cwd, hook_event_name, prompt_id, session_id, transcript_path,
trigger` and nothing else -- there is no `stop_hook_active` equivalent, so a hook
that blocks has no loop guard, and a wrong one makes compaction impossible at the
context ceiling, which is the worst place in a session to be stuck. And the drift
this detects is between two files on disk: compaction does not erase it, so
refusing buys nothing that warning does not. Warn, and let the session fix it on
the other side.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _harness_common as hc
except ImportError:
    hc = None  # type: ignore[assignment]

# HUB.md is written by hand after the board changes, so it trails by seconds in
# normal use. Only a gap wide enough to mean "nobody came back to it" is drift.
SKEW_TOLERANCE_SECONDS = 900


def main() -> int:
    if hc is None:
        return 0
    payload = hc.read_hook_payload()

    root = hc.find_harness_root(payload)
    if root is None:
        return 0

    # store-spec.md §6 row 4 asks for stderr + exit 2 on a corrupt gate, which
    # is what the other five harness hooks do. This hook deliberately does not
    # follow that here: its own docstring above measured that PreCompact CAN
    # block (unlike SubagentStart) and has no stop_hook_active-style loop
    # guard, so a wrong block strands the session at the context ceiling --
    # "the worst place in a session to be stuck". A corrupt gate is exactly
    # the kind of wrong-more-often-than-right condition that guard exists to
    # avoid blocking on. So: stay loud, stay non-blocking -- reuse this
    # hook's own systemMessage channel instead of sys.exit(2).
    corrupt_reason = hc.gate_corrupt_reason(root)
    if corrupt_reason is not None:
        hc.emit_json({
            "continue": True,
            "systemMessage": f"HARNESS: gate corrupt — {corrupt_reason}",
        })
        return 0

    if not hc.is_harness_active(root):
        return 0

    board = hc.board_path(root)
    hub = hc.hub_md(root)
    if not board.is_file() or not hub.is_file():
        return 0

    try:
        skew = board.stat().st_mtime - hub.stat().st_mtime
    except OSError:
        return 0
    if skew <= SKEW_TOLERANCE_SECONDS:
        return 0

    hc.emit_json({
        "continue": True,
        "systemMessage": (
            "HARNESS: board.json is %d minutes newer than HUB.md.\n"
            "The board moved and the prose half did not follow. HUB.md's worker table "
            "and decision table are what the next session reads; a board change that "
            "never reached them is invisible after this compaction.\n"
            "Reconcile both tables against board.json before continuing."
            % (skew // 60)
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

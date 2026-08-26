#!/usr/bin/env python3
"""
Pre-Bash Hook - Block dangerous commands before execution.

Reads the PreToolUse payload from stdin (JSON) and blocks with exit 2.

Two things this hook got wrong before 2026-08-26, both measured on
claude 2.1.239 (see the harness measurements for the transcripts):

1. It read `sys.argv[1]`, wired as `"$CLAUDE_TOOL_INPUT"`. That variable does
   not exist -- the string appears 0 times in the Claude Code binary -- so the
   argument always expanded to the empty string and no pattern could match.
   Hooks receive their payload on stdin as JSON; the command is at
   `tool_input.command`.
2. It exited 1 on a match. Only exit 2 blocks; exit 1 is non-blocking, so even
   a correct match would have let the command through.

Fail-open by contract: any unexpected error exits 0 rather than killing the
user's turn.
"""

import json
import re
import sys

DANGEROUS_PATTERNS = [
    'dd if=',
    ':(){:|:&};:',
    'mkfs.',
    '> /dev/sd',
]

# `rm -rf /` and `rm -rf ~` were plain substrings upstream, which also matched
# `rm -rf /tmp/scratch` -- a routine command. That false positive was invisible
# while the hook was dead; it is not once the hook blocks. Only a bare / or ~
# target is dangerous, so the path must end there.
DANGEROUS_ROOT_DELETE = re.compile(r'rm -rf [/~](?=\s|$)')

BLOCK_EXIT_CODE = 2  # the only code Claude Code treats as blocking


def find_dangerous(command):
    """Return the first dangerous pattern in `command`, or None."""
    match = DANGEROUS_ROOT_DELETE.search(command)
    if match:
        return match.group(0).strip()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in command:
            return pattern
    return None


def read_command(stream):
    """Extract tool_input.command from a PreToolUse stdin payload."""
    payload = json.load(stream)
    tool_input = payload.get('tool_input') or {}
    return tool_input.get('command') or ''


def main():
    try:
        command = read_command(sys.stdin)
    except Exception:
        sys.exit(0)  # fail-open: a malformed payload must not block the turn

    pattern = find_dangerous(command)
    if pattern:
        print(f"[omo] BLOCKED: dangerous command detected: {pattern}", file=sys.stderr)
        sys.exit(BLOCK_EXIT_CODE)

    sys.exit(0)


if __name__ == "__main__":
    main()

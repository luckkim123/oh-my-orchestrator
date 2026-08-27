#!/usr/bin/env python3
"""Verify store-spec's mapping table still matches the anchors on this machine.

The check is a **set comparison of path strings**, not a row count. That is the
whole point: the P0 run of this script caught a mapping table that wrote
`workspace/...` where the real path is `~/Desktop/workspace/...`. A row-count
check would have passed silently on all eight of those rows.

Two instruments, deliberately not shared (store-spec §9): this is the *census*
(the roster of anchors). Drift detection — split-brain between a legacy store and
`migrated.jsonl` — compares mtimes against ISO timestamps and lives elsewhere.
Merging them would leave zero independent detectors.

Not a pytest test, and the filename keeps it that way: pytest collects
`test_*.py`, and a census is machine-specific, so collecting this would fail the
suite on every machine but the one the spec was written on.

    python3 skills/harness/tests/verify_census.py

Exit 0 = the table and the filesystem agree. Exit 1 = they do not; the offending
paths are printed as MISSING (on disk, absent from the table) or STALE (in the
table, absent from disk).

This script produced two false FAILs during P0, both its own bugs: `<sha>` passed
through `re.escape` unchanged (Python 3.7+ does not escape `<`/`>`, hence the NUL
sentinel below), and an earlier version's row regex swept in §9.5 rows (hence the
explicit block slicing). **On a FAIL, suspect the verifier before you edit the
spec.** But one P0 FAIL was a real defect, so do not assume its innocence either
— read the reported path and decide.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HOME = os.path.expanduser("~")
SPEC = Path(__file__).resolve().parent.parent / "references" / "store-spec.md"

# The fixed census command, unbounded depth. A -maxdepth 6 variant missed three
# real anchors at depths 7-8; the depth limit is not an optimisation, it is a
# defect.
FIND_ARGS = [
    "find", HOME, "-type", "d",
    "(", "-name", ".omp", "-o", "-name", ".oms", "-o", "-name", ".omd",
    "-o", "-name", ".omx", "-o", "-name", ".omha", "-o", "-name", ".orchestration", ")",
    "-not", "-path", "*/.git/*",
]


def row_to_regex(row: str) -> str:
    """A mapping-table path -> a regex matching the absolute paths it covers.

    `~` expands to the home directory and a bare relative path is taken as
    home-relative. `**` matches across directory separators, `*` within one
    segment, and `<sha>` is a single opaque segment.
    """
    p = row.replace("~", HOME).rstrip("/")
    if not p.startswith("/"):
        p = f"{HOME}/{p}"
    p = p.replace("<sha>", "\x00")          # sentinel: survives re.escape intact
    r = re.escape(p)
    r = r.replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return r.replace(re.escape("\x00"), "[^/]*")


def main() -> int:
    if not SPEC.is_file():
        print(f"store-spec not found at {SPEC}", file=sys.stderr)
        return 1

    out = subprocess.run(FIND_ARGS, capture_output=True, text=True)
    census = sorted(line for line in out.stdout.splitlines() if line.strip())
    spec = SPEC.read_text(encoding="utf-8")

    # Slice the two blocks first. Without this, section 9.5's numbered table
    # (whose rows also start with `| <n> | \`...\``) is read as in-scope anchors.
    block_91 = spec.split("### 9.1")[1].split("### 9.2")[0]
    block_92 = spec.split("### 9.2")[1].split("### 9.3")[0]
    inscope = re.findall(r"^\|\s*\d+\s*\|\s*`([^`]+)`", block_91, re.M)
    excluded = re.findall(r"^\|\s*`([^`]+)`", block_92, re.M)

    covered: set[str] = set()
    stale: list[str] = []
    for row in inscope + excluded:
        rx = row_to_regex(row)
        hits = [c for c in census if re.fullmatch(rx, c)]
        if hits:
            covered.update(hits)
        else:
            stale.append(row)
    missing = [c for c in census if c not in covered]

    print(f"find census={len(census)}  9.1 in-scope={len(inscope)}  "
          f"9.2 excluded={len(excluded)}  covered={len(covered)}")
    for m in missing:
        print("  MISSING:", m)
    for s in stale:
        print("  STALE  :", s)

    ok = not missing and not stale
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

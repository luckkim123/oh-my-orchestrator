"""anchor.py — .hq/.anchor parse, ascent, anchor-id uniqueness, and the
4-state hook gate (store-spec.md §2, §6).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import ANCHOR_REL, has_legacy_store, legacy_board_json

GATE_OFF = "off"
GATE_LEGACY = "legacy"
GATE_NORMAL = "normal"
GATE_CORRUPT = "corrupt"

_ID_RE = re.compile(r"^id:\s*(\S.*)$")


class HqError(Exception):
    """Raised on any refused hq operation or unparseable store artifact."""


@dataclass(frozen=True)
class Anchor:
    root: Path
    id: str


def parse_anchor(path: Path) -> str:
    """Parse a `.hq/.anchor` file: exactly one non-empty line `id: <value>`
    after stripping a single trailing newline. Anything else — a second
    non-blank line, a missing `id:` prefix, an empty value — raises HqError.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise HqError(f"{path}: cannot read anchor file: {e}") from e

    text = raw[:-1] if raw.endswith("\n") else raw
    non_empty = [line for line in text.split("\n") if line.strip() != ""]
    if len(non_empty) != 1:
        raise HqError(
            f"{path}: expected exactly one non-empty line, found {len(non_empty)}"
        )
    m = _ID_RE.match(non_empty[0])
    if not m:
        raise HqError(f"{path}: line does not match 'id: <value>': {non_empty[0]!r}")
    value = m.group(1).strip()
    if not value:
        raise HqError(f"{path}: empty id value")
    return value


def find_anchors(start: Path) -> list:
    """Ascent from start.resolve() through every parent, nearest first. One
    Anchor per directory carrying a parseable .hq/.anchor. An unparseable
    anchor propagates HqError — a broken anchor is not an absent one. Stops
    at the filesystem root (Path.parents exhausts there on its own).
    """
    anchors: list = []
    cur = start.resolve()
    for d in [cur, *cur.parents]:
        anchor_file = d / ANCHOR_REL
        if anchor_file.is_file():
            anchors.append(Anchor(root=d, id=parse_anchor(anchor_file)))
    return anchors


def nearest_anchor(start: Path) -> Anchor:
    anchors = find_anchors(start)
    if not anchors:
        raise HqError(f"no .hq/.anchor found ascending from {start}")
    return anchors[0]


def check_id_uniqueness(anchors: list) -> list:
    """store-spec §2 scopes this to anchors reachable by ascent — callers
    pass find_anchors(start), never a machine-wide scan."""
    seen: dict = {}
    for a in anchors:
        seen.setdefault(a.id, []).append(a.root)
    reports = []
    for aid, roots in seen.items():
        if len(roots) > 1:
            reports.append(
                f"duplicate anchor id {aid!r}: {', '.join(str(r) for r in roots)}"
            )
    return reports


def find_anchor_root(start: Path) -> Path:
    """Ascend from start looking for a directory that is either a proper .hq
    anchor (a parseable .hq/.anchor) or a not-yet-migrated legacy store
    (.orchestration/ dir or harness-tasks.json file) — store-spec §6 rows 1-2.

    This is the CLI's default `--anchor`-less resolution (not part of the
    hq-contract.md anchor.py API list — added because neither live P1 target
    store carries a .hq/.anchor file yet). nearest_anchor() requires a
    parseable .hq/.anchor and would raise HqError for both; a strict
    anchor-only default would make every `hq` command fail against the two
    stores this package ships against today.
    """
    cur = start.resolve()
    for d in [cur, *cur.parents]:
        if (d / ANCHOR_REL).is_file() or has_legacy_store(d):
            return d
    raise HqError(f"no .hq anchor or legacy store found ascending from {start}")


def gate_state(root: Path) -> tuple:
    """store-spec §6, the 4-state hook gate. Never raises — an HqError from a
    broken ascent anchor (duplicate id, unparseable .anchor) is caught here
    and reported as GATE_CORRUPT rather than propagating.

    | legacy store | .hq/.anchor | result                                    |
    |--------------|-------------|-------------------------------------------|
    | no           | no          | GATE_OFF                                  |
    | yes          | no          | GATE_LEGACY (reason names the legacy path)|
    | --           | yes, valid, unique id, board parses/absent | GATE_NORMAL|
    | --           | unparseable, or dup id, or board invalid   | GATE_CORRUPT|
    """
    try:
        anchor_file = root / ANCHOR_REL
        if not anchor_file.is_file():
            if has_legacy_store(root):
                return (
                    GATE_LEGACY,
                    f"legacy store present at {root} (.orchestration/ or "
                    f"harness-tasks.json), no .hq/.anchor yet",
                )
            return (GATE_OFF, "")

        parse_anchor(anchor_file)  # raises HqError -> caught below as GATE_CORRUPT

        dup_reports = check_id_uniqueness(find_anchors(root))
        if dup_reports:
            return (GATE_CORRUPT, "; ".join(dup_reports))

        board_path = legacy_board_json(root)
        if board_path.is_file():
            try:
                json.loads(board_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                return (GATE_CORRUPT, f"{board_path}: board.json invalid: {e}")

        return (GATE_NORMAL, "")
    except HqError as e:
        return (GATE_CORRUPT, str(e))

"""anchor.py — .hq/.anchor parse, ascent, anchor-id uniqueness, and the
4-state hook gate (store-spec.md §2, §6).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import (ANCHOR_REL, LEGACY_STATE_FILE, has_legacy_store,
                    hq_board_json, legacy_board_json)

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


def _home_key():
    """(st_dev, st_ino) of the home directory, or None when it cannot be read.

    Not `Path.home()` compared with `==`: `Path` compares strings, so on a
    case-insensitive filesystem a cwd entered as `/Users/Name/p` never equals a
    `$HOME` of `/Users/name`, and the bound silently stops binding. Identity is
    the property the guard actually means.
    """
    try:
        st = Path.home().resolve().stat()
    except (OSError, RuntimeError):
        return None
    return (st.st_dev, st.st_ino)


def _is_home(d: Path, home_key) -> bool:
    if home_key is None:
        return False
    try:
        st = d.stat()
    except OSError:
        return False
    return (st.st_dev, st.st_ino) == home_key


def find_anchors(start: Path) -> list:
    """Ascent from start.resolve() through every parent, nearest first. One
    Anchor per directory carrying a parseable .hq/.anchor. An unparseable
    anchor propagates HqError — a broken anchor is not an absent one.

    The ascent stops AT the user's home directory and never examines its
    parents. Two unrelated projects under `~` share `~` and `/Users` as
    ancestors, so without this bound a single `.hq/.anchor` placed at either
    would silently merge them — one project's store answering another
    project's query. This is omd's ST-3 gate, which until now existed only as
    prose in `references/wiki/README.md` (its test asserted the sentence was
    printed twice, not that anything enforced it); the wiki form it guarded is
    retired, so the guarantee moves here, into code.

    A start path OUTSIDE the home directory keeps the full ascent to the
    filesystem root: a container mount like `/workspace` is a documented
    anchor location (`.claude/rules/code-graph.md`), home is not its ancestor,
    and bounding there would find nothing at all.
    """
    anchors: list = []
    cur = start.resolve()
    home_key = _home_key()
    for d in [cur, *cur.parents]:
        anchor_file = d / ANCHOR_REL
        if anchor_file.is_file():
            anchors.append(Anchor(root=d, id=parse_anchor(anchor_file)))
        if _is_home(d, home_key):
            break
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

    The home bound applies here too. It has to: `_resolve_anchor_roots_for_query`
    falls back to this function whenever the strict ascent finds no
    `.hq/.anchor` at all, so an unanchored subtree under `~` took this path and
    walked straight past home to `/`. Bounding only the strict ascent left the
    guard in place for anchored trees and absent for exactly the trees that had
    no anchor of their own to protect them.
    """
    cur = start.resolve()
    home_key = _home_key()
    for d in [cur, *cur.parents]:
        if (d / ANCHOR_REL).is_file() or has_legacy_store(d):
            return d
        if _is_home(d, home_key):
            break
    raise HqError(f"no .hq anchor or legacy store found ascending from {start}")


def gate_state(root: Path) -> tuple:
    """store-spec §6, the 4-state hook gate. Never raises — an HqError from a
    broken ascent anchor (duplicate id, unparseable .anchor) is caught here
    and reported as GATE_CORRUPT rather than propagating.

    | legacy store | .hq/.anchor | result                                    |
    |--------------|-------------|-------------------------------------------|
    | no           | no          | GATE_OFF                                  |
    | yes, board parses or absent | no | GATE_LEGACY (reason names the path) |
    | yes, board unparseable      | no | GATE_CORRUPT (B-r1 widening, 2026-08-31)|
    | --           | yes, valid, unique id, board parses/absent | GATE_NORMAL|
    | --           | unparseable, or dup id, or board invalid   | GATE_CORRUPT|
    """
    try:
        anchor_file = root / ANCHOR_REL
        if not anchor_file.is_file():
            if has_legacy_store(root):
                # B-r1 widening (2026-08-31): a legacy board that exists and
                # will not parse is corrupt even with no anchor. GATE_LEGACY's
                # warn channel is silent at hook entry (gate_corrupt_reason
                # returns None for it), so a corrupt store read as merely
                # "unmigrated" is the same silent failure row 4 exists to
                # surface.
                # Check only the file the hooks actually read -- state_path
                # precedence: the board when it exists, else the legacy state
                # file. A stale corrupt sibling must not override a valid
                # live board (codex review 2026-08-31).
                board = legacy_board_json(root)
                selected = board if board.is_file() else root / LEGACY_STATE_FILE
                if selected.is_file():
                    try:
                        json.loads(selected.read_text(encoding="utf-8"))
                    except (OSError, ValueError) as e:
                        return (GATE_CORRUPT, f"{selected}: legacy board invalid: {e}")
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

        # store-spec §7 stage 2: this branch is only reached once anchor_file
        # is confirmed to exist and parse (the unanchored case already
        # returned above), so the board that matters here is the one an
        # anchored project actually reads -- .hq/runtime/board.json, never
        # the legacy .orchestration/board.json -- same rule board_path() in
        # hooks/_harness_common.py and community_dir() in store.py follow.
        # Before this fix, an anchored project's corrupt .hq/runtime/
        # board.json went unexamined here: this check looked at the legacy
        # path unconditionally, so GATE_CORRUPT could never fire for it.
        board_path = hq_board_json(root)
        if board_path.is_file():
            try:
                json.loads(board_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                return (GATE_CORRUPT, f"{board_path}: board.json invalid: {e}")

        return (GATE_NORMAL, "")
    except HqError as e:
        return (GATE_CORRUPT, str(e))

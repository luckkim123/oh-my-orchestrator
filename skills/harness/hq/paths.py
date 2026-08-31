"""paths.py — the single declared location for this repo's `hq/` package
root-literal strings (store-spec.md §9.5, item omo; P2 re-entry contract).

omo already carries both of the store's root literals in code before this
module existed (`ANCHOR_REL = ".hq/.anchor"` in anchor.py, `.hq/community` in
store.py), so unlike the other four repos' paths modules this one declares
BOTH `HQ_ROOT` and `LEGACY_ROOT` — there is no single literal to centralize,
there are two, and P2 does not pick a winner between them.

**Which root is live is anchor-gated, per project** (store-spec.md §7
stage 2, live since 0.8.0): a parseable `.hq/.anchor` resolves reads and
writes to `.hq/` only; a project without one keeps resolving to
`.orchestration/`. `community_dir()` in store.py implements that gate — the
helpers here only declare the literals and never pick the winner.

Hooks under hooks/ deliberately do NOT import this module. See
hooks/_harness_common.py's own module docstring and
skills/harness/tests/test_paths_lint.py for why: a cross-package import in
every hook's hot path would trade a real literal-drift risk for a real
availability risk (`_harness_common.py:gate_corrupt_reason` already documents
the same import path degrading to "not corrupt" on any failure — a bare
`ImportError` guard around `_harness_common` itself already exists in every
hook, but that is importing a sibling in the *same* package, not crossing
into `hq/`). `hq/paths.py` and `hooks/_harness_common.py` are therefore both
allowed declaration points for the lint in test_paths_lint.py.
"""
from __future__ import annotations

from pathlib import Path

HQ_ROOT = ".hq"
LEGACY_ROOT = ".orchestration"

# --- .hq/ (new root -- not live anywhere yet; P3+) --------------------------

ANCHOR_REL = f"{HQ_ROOT}/.anchor"

HQ_LOCK_NAME = ".hq-lock"


def hq_community_dir(base: Path) -> Path:
    return base / HQ_ROOT / "community"


def hq_board_json(base: Path) -> Path:
    return base / HQ_ROOT / "runtime" / "board.json"


# --- .orchestration/ (legacy root -- live today) ----------------------------

LEGACY_STATE_FILE = "harness-tasks.json"


def legacy_root(base: Path) -> Path:
    return base / LEGACY_ROOT


def legacy_board_json(base: Path) -> Path:
    return legacy_root(base) / "board.json"


def has_legacy_store(base: Path) -> bool:
    """True when `base` carries a not-yet-migrated legacy store: an
    `.orchestration/` dir or a `harness-tasks.json` file. Moved bodily from
    anchor.py's `_has_legacy_store` (store-spec.md §6 rows 1-2) -- same two
    conditions, same result."""
    return legacy_root(base).is_dir() or (base / LEGACY_STATE_FILE).is_file()

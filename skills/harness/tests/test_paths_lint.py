#!/usr/bin/env python3
"""Re-entry lint for hq/paths.py's root literals (P2 contract,
store-spec.md §9.5).

Rule (exact, from the P2 contract -- not a heuristic): parse every scanned
.py file with `ast`, walk every `ast.Constant` whose value is a `str`
(`ast.walk()` descends into a JoinedStr/f-string's `.values`, so each
constant *fragment* of an f-string is checked exactly like any other
Constant). A violation is a string containing one of the root literals
(`.hq`, `.orchestration`) with NOT A SINGLE whitespace character anywhere in
it -- a path never contains whitespace, prose always does. Module- and
def-level docstrings (a node's first body statement, `Expr(Constant(str))`,
for Module/FunctionDef/AsyncFunctionDef/ClassDef) are excluded before the
walk ever sees them; comments are not AST nodes and are excluded for free.

Scan root: skills/harness/ only, not the whole omo repo. Measured
2026-08-28 via `grep -rln '\\.orchestration\\|\\.hq' --include=*.py` against
bin/, hooks/ (top-level), codeagent-wrapper/, and skills/omo/: zero hits.
Those trees don't touch the harness store at all, so widening the scan buys
no coverage and drags in an unrelated skill's source.

Excluded from the scan (each measured against today's tree, 2026-08-28):
- tests/**                  -- fixtures need the literal to build fixture
                               trees. 28 matching lines in this directory.
- references/**             -- copied into user projects as inert data;
                               can't import a hook module. 0 .py files exist
                               here today.
- .phase0-scratch/** (omo)  -- not even under skills/harness/ (it's a
                               repo-root sibling); listed anyway per the
                               shared P2 contract text. 0 .py files there
                               mention either literal.
- templates/**              -- same: repo-root templates/, not under
                               skills/harness/, vendored payload. 0 .py
                               files exist there at all.
- hq/paths.py               -- the module itself.
- hooks/_harness_common.py  -- the SECOND allowed declaration point, see
                               below.

Two allowed files, not one
---------------------------
The P2 contract's default is one paths module per repo. Inside hq/
(anchor.py, store.py, verbs.py, cli.py, post.py) importing hq/paths.py is a
plain same-package import -- no fragility, so those files have no excuse to
keep their own literal.

hooks/ is a different, sibling top-level package. Every hook already does

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import _harness_common as hc
    except ImportError:
        hc = None

and every hook's main() bails out (`if hc is None: return 0`) before touching
any path helper -- that guard is pre-existing and load-bearing, not something
this refactor invented. `_harness_common.py:gate_corrupt_reason()` documents
exactly why a cross-package reach from hooks/ into hq/ degrades on failure
rather than raising: "a missing hq package, a stale sys.path, anything --
must degrade to 'not corrupt' ... rather than break every session on the
machine." That guard is deliberately scoped to one optional feature
(surfacing a corrupt-gate reason), not to the hot path every hook always
runs (find_harness_root, board_path, ...).

Making hooks/_harness_common.py additionally do `from hq import paths` at
import time would put that same cross-package reach on the hot path instead
-- trading a literal-drift risk this lint already catches for a real
availability risk this lint cannot catch (an import failure there breaks
every hook on every Stop/SessionStart/etc., harness or not). So
hooks/_harness_common.py keeps its own `LEGACY_ROOT` declaration (see its
module docstring) and is the second allowed file here.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent.parent  # skills/harness/

ROOT_LITERALS = (".hq", ".orchestration")

ALLOWED_FILES = {
    HARNESS_DIR / "hq" / "paths.py",
    HARNESS_DIR / "hooks" / "_harness_common.py",
}

EXCLUDED_DIR_NAMES = {"tests", "references", "__pycache__"}


def _iter_scanned_files():
    for path in sorted(HARNESS_DIR.rglob("*.py")):
        if path in ALLOWED_FILES:
            continue
        parent_parts = path.relative_to(HARNESS_DIR).parts[:-1]
        if any(part in EXCLUDED_DIR_NAMES for part in parent_parts):
            continue
        yield path


def _docstring_constant_ids(tree: ast.Module) -> set:
    """id()s of Constant nodes that ARE a docstring: the first body
    statement of Module/FunctionDef/AsyncFunctionDef/ClassDef, in the shape
    Expr(Constant(str))."""
    excluded = set()
    scopes = [tree] + [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for scope in scopes:
        body = getattr(scope, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            excluded.add(id(first.value))
    return excluded


def _violations_in_file(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstring_ids = _docstring_constant_ids(tree)

    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstring_ids:
            continue
        s = node.value
        if any(lit in s for lit in ROOT_LITERALS) and not any(c.isspace() for c in s):
            violations.append((path, getattr(node, "lineno", "?"), s))
    return violations


class TestPathsLint(unittest.TestCase):
    def test_no_reentrant_root_literals(self):
        all_violations = []
        for path in _iter_scanned_files():
            all_violations.extend(_violations_in_file(path))

        if all_violations:
            lines = [
                f"{p.relative_to(HARNESS_DIR)}:{ln}: {s!r}"
                for p, ln, s in all_violations
            ]
            self.fail(
                f"{len(all_violations)} re-entrant root-literal violation(s) "
                f"outside the allowed paths module(s):\n" + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()

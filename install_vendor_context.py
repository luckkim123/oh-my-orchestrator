#!/usr/bin/env python3
"""Install the vendor-side context-loader / decision-record skill payloads.

A vendor CLI (codex, antigravity, gemini) does not inherit the Claude session's
project rules automatically -- it reads them from a `context-loader` skill placed
in that vendor's own config directory, which reads `.orchestration/` on every task
(see `skills/omo/references/shared-context.md`). This script installs that skill
(and its `decision-record` sibling) from `templates/vendor/<vendor>/` into the
resolved destination, byte-for-byte -- it never re-types their content.

Destination roots come from `shared-context.md` ("Installing the loader per
vendor"): codex, gemini, and antigravity each get one project-scope root.
Antigravity's is `.agents/`, per agy's own shipped `agy-customizations` skill
(`~/.gemini/antigravity-cli/builtin/skills/agy-customizations/SKILL.md`), not a
user-scope copy -- an earlier "unverified" row proposed writing into
`~/.gemini/antigravity-cli/`, which measurement ruled out: that tree has no
`skills/` directory (only a `builtin/skills/` cache agy overwrites on update),
and the nearest real user-scope skills dir, `~/.agents/skills/`, is a
cross-agent store shared with every other tool on the machine -- the wrong place
for one project's rules.

Usage:
    python3 install_vendor_context.py --vendor all --project . --dry-run
    python3 install_vendor_context.py --vendor codex --project ~/some/repo
    python3 install_vendor_context.py --vendor all --project ~/some/repo --force
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

REPO_ROOT = Path(__file__).resolve().parent
TEMPLATES_VENDOR_DIR = REPO_ROOT / "templates" / "vendor"

ALL_VENDORS = ["codex", "antigravity", "gemini"]

# The binary to probe with `command -v` (shutil.which) per vendor -- informational
# only, never gates whether a plan is built. antigravity's binary is `agy`, not
# `antigravity`; name-based discovery has already failed once on exactly this
# (skills/omo/references/vendor-ops.md).
VENDOR_BINARY = {
    "codex": "codex",
    "antigravity": "agy",
    "gemini": "gemini",
}


class VendorResolutionError(Exception):
    """A vendor's config location could not be resolved on this machine.

    Carries every candidate path considered so the caller can report them --
    "refuse and name every path it looked for", never guess a fallback.
    """

    def __init__(self, vendor: str, candidates: List[tuple], reason: str) -> None:
        super().__init__(reason)
        self.vendor = vendor
        self.candidates = candidates
        self.reason = reason


class Destination(NamedTuple):
    scope: str  # "project" or "user"
    root: Path


class CopyItem(NamedTuple):
    vendor: str
    scope: str
    source: Path
    dest: Path


def resolve_vendor_destinations(vendor: str, project_dir: Path) -> List[Destination]:
    """Resolve the destination root(s) for a vendor's context-loader payload.

    One clearly-named function, candidate paths kept as a visible list, so a wrong
    guess here is a one-line fix rather than a hunt. Source of the convention:
    `skills/omo/references/shared-context.md` plus each template's own header
    (codex's `config.toml` states "Copy to <project>/.codex/config.toml"). All
    three vendors are project-scope only -- antigravity's `.agents/` is grounded
    in agy's own shipped `agy-customizations` skill (customization root `.agents/`
    at the project root, skills at `<root>/skills/<name>/SKILL.md`; measured at
    `~/.gemini/antigravity-cli/builtin/skills/agy-customizations/SKILL.md:42` and
    `docs/skills.md:10`), not a user-scope copy: `~/.gemini/antigravity-cli/` has
    no `skills/` directory to install into (only a `builtin/skills/` cache agy
    overwrites on update), and `~/.agents/skills/` is a cross-agent store shared
    with every other tool on the machine, not antigravity-private.
    """
    candidates: List[tuple] = []

    if vendor == "codex":
        candidates.append(("project", project_dir / ".codex"))
    elif vendor == "gemini":
        candidates.append(("project", project_dir / ".gemini"))
    elif vendor == "antigravity":
        candidates.append(("project", project_dir / ".agents"))
    else:
        raise VendorResolutionError(
            vendor, candidates, f"no destination convention registered for vendor {vendor!r}"
        )

    return [Destination(scope=scope, root=root) for scope, root in candidates]


def build_copy_plan(vendor: str, project_dir: Path) -> List[CopyItem]:
    """Mirror templates/vendor/<vendor>/ onto every resolved destination root."""
    src_root = TEMPLATES_VENDOR_DIR / vendor
    if not src_root.is_dir():
        raise VendorResolutionError(vendor, [], f"no template directory at {src_root}")

    destinations = resolve_vendor_destinations(vendor, project_dir)
    src_files = sorted(p for p in src_root.rglob("*") if p.is_file())

    items: List[CopyItem] = []
    for dest in destinations:
        for src_file in src_files:
            rel = src_file.relative_to(src_root)
            items.append(CopyItem(vendor=vendor, scope=dest.scope, source=src_file, dest=dest.root / rel))
    return items


def classify(item: CopyItem) -> str:
    """create | already current | differs, needs --force"""
    if not item.dest.exists():
        return "create"
    if item.dest.is_dir():
        return "differs, needs --force"
    if filecmp.cmp(item.source, item.dest, shallow=False):
        return "already current"
    return "differs, needs --force"


def apply_item(item: CopyItem) -> None:
    if item.dest.is_dir():
        shutil.rmtree(item.dest)
    item.dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(item.source, item.dest)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install vendor context-loader/decision-record skill payloads from "
            "templates/vendor/ into a vendor CLI's own config directory."
        )
    )
    parser.add_argument(
        "--vendor",
        required=True,
        choices=["codex", "antigravity", "gemini", "all"],
        help="Which vendor to install for, or 'all'.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project directory for project-scope destinations (default: cwd).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print source -> destination pairs and actions; write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite a destination file whose content differs from the template.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    project_dir = args.project.expanduser().resolve()
    vendors = ALL_VENDORS if args.vendor == "all" else [args.vendor]

    overall_ok = True

    for vendor in vendors:
        print(f"== {vendor} ==")
        binary = VENDOR_BINARY[vendor]
        found = shutil.which(binary)
        print(f"  binary: `command -v {binary}` -> {found or 'not found'}")

        try:
            items = build_copy_plan(vendor, project_dir)
        except VendorResolutionError as exc:
            print(f"  REFUSED: {exc.reason}")
            print("  looked for:")
            for scope, root in exc.candidates:
                print(f"    - {scope}: {root}")
            overall_ok = False
            continue

        if not items:
            print("  (no template files found)")
            continue

        blocked = 0
        for item in items:
            action = classify(item)
            print(f"  [{item.scope}] {item.source} -> {item.dest} : {action}")

            if args.dry_run:
                continue

            if action == "create":
                apply_item(item)
            elif action == "differs, needs --force":
                if args.force:
                    apply_item(item)
                    print("    -> overwritten (--force)")
                else:
                    blocked += 1
            # "already current": no write needed -- idempotent by construction.

        if blocked and not args.dry_run:
            print(f"  {blocked} file(s) differ and were left in place (pass --force to overwrite).")
            overall_ok = False

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""store.py — filesystem IO: locate the community dir, list/read/write posts,
INDEX.md regeneration, and the store lock (store-spec.md §3, §4; D-P1-1).
"""
from __future__ import annotations

import fcntl
import os
import re
import time
from pathlib import Path

from .anchor import HqError, parse_anchor
from .paths import ANCHOR_REL, HQ_LOCK_NAME, hq_community_dir, legacy_root
from .post import Post, parse_post, serialize_post

INDEX_NAME = "INDEX.md"

_FILENAME_NUM_RE = re.compile(r"^(\d{3})-")


def community_dir(anchor_root: Path) -> Path:
    """store-spec.md §7 stage 2 (fallback removal): the anchor decides, per
    project, in both directions. A project with a parseable `.hq/.anchor`
    resolves reads and writes to `.hq/community/` only -- no fallback to
    `.orchestration/`, even when a legacy copy still exists on disk. A
    project without an anchor keeps resolving to `.orchestration/`, exactly
    as it always has, so a machine that never migrated keeps working.

    An unparseable anchor is treated as absent (falls back to the legacy
    path) rather than routed into a half-broken `.hq/` structure -- the
    loud GATE_CORRUPT failure is a separate concern, surfaced by
    hq.anchor.gate_state() at the hook layer."""
    anchor_file = anchor_root / ANCHOR_REL
    if anchor_file.is_file():
        try:
            parse_anchor(anchor_file)
        except HqError:
            pass
        else:
            return hq_community_dir(anchor_root)
    return legacy_root(anchor_root)


def posts_dir(anchor_root: Path) -> Path:
    return community_dir(anchor_root) / "posts"


def _post_files(anchor_root: Path) -> list:
    pd = posts_dir(anchor_root)
    if not pd.is_dir():
        return []
    return sorted(pd.glob("*/[0-9][0-9][0-9]-*.md"))


def list_posts_with_errors(anchor_root: Path):
    """Parse every posts/<category>/<NNN>-*.md file. A file that fails to
    parse is collected here (not swallowed, not crashed on) rather than
    silently dropped — lint reports it, index skips it under a final
    '## unparseable' section."""
    posts: list = []
    errors: list = []
    for f in _post_files(anchor_root):
        try:
            posts.append(parse_post(f, f.read_text(encoding="utf-8")))
        except HqError as e:
            errors.append((f, str(e)))
        except OSError as e:
            errors.append((f, f"read error: {e}"))
    posts.sort(key=lambda p: p.number)
    return posts, errors


def list_posts(anchor_root: Path) -> list:
    posts, _ = list_posts_with_errors(anchor_root)
    return posts


def read_post(anchor_root: Path, post_id: str) -> Post:
    category, sep, number = post_id.partition("/")
    if not sep or not category or not number:
        raise HqError(f"invalid post id {post_id!r} (expected '<category>/<NNN>')")
    try:
        n = int(number)
    except ValueError as e:
        raise HqError(f"invalid post id {post_id!r}: {e}") from e

    pd = posts_dir(anchor_root) / category
    matches = sorted(pd.glob(f"{n:03d}-*.md")) if pd.is_dir() else []
    if not matches:
        raise HqError(f"post {post_id!r} not found under {pd}")
    if len(matches) > 1:
        raise HqError(f"post {post_id!r} has multiple matching files: {matches}")
    f = matches[0]
    return parse_post(f, f.read_text(encoding="utf-8"))


def next_number(anchor_root: Path) -> int:
    """max(number) + 1 over ALL categories, min 1. Derived from filenames
    directly (not from parsed Post objects) so a numbering slot already taken
    by an unparseable legacy file (e.g. the vault's pre-schema 001/002/004,
    which have no id: field at all and so cannot become a Post) is never
    reissued to a new post."""
    max_n = 0
    for f in _post_files(anchor_root):
        m = _FILENAME_NUM_RE.match(f.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max(max_n + 1, 1)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-")


def post_filename(number: int, title: str) -> str:
    slug = _slugify(title) or f"post-{number:03d}"
    return f"{number:03d}-{slug}.md"


def write_post(anchor_root: Path, post: Post) -> Path:
    """Atomic write: <name>.tmp in the same directory, os.replace onto the
    target. No .bak. Writes to post.path when set (comment()/edit() on an
    existing post keep the original filename); allocates a fresh filename
    under posts/<category>/ otherwise (post_new)."""
    pd = posts_dir(anchor_root) / post.category
    pd.mkdir(parents=True, exist_ok=True)
    target = post.path if post.path is not None else pd / post_filename(post.number, post.title)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(serialize_post(post), encoding="utf-8")
    os.replace(tmp, target)
    return target


def update_index(anchor_root: Path, anchor_id: str, now: str) -> Path:
    posts, errors = list_posts_with_errors(anchor_root)
    by_cat: dict = {}
    for p in posts:
        by_cat.setdefault(p.category, []).append(p)

    lines = [
        f"# INDEX — {anchor_id}", "",
        f"> {len(posts)} posts · regenerated {now} by `hq index`", "",
    ]
    for cat in sorted(by_cat):
        lines.append(f"## {cat}")
        for p in sorted(by_cat[cat], key=lambda x: x.number):
            subj = f" [subject: {p.subject}]" if p.subject else ""
            # A legacy post has no summary:, and an em dash with nothing after
            # it reads as a truncation rather than an absence.
            summary = p.fields.get("summary", "").strip()
            tail = f" — {summary}" if summary else ""
            lines.append(f"- `{p.id}`{subj} {p.title}{tail}")
        lines.append("")
    if errors:
        lines.append("## unparseable")
        for f, reason in errors:
            lines.append(f"- `{f}` — {reason}")
        lines.append("")

    idx_path = community_dir(anchor_root) / INDEX_NAME
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = idx_path.with_name(idx_path.name + ".tmp")
    tmp.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    os.replace(tmp, idx_path)
    return idx_path


def with_store_lock(anchor_root: Path, fn, *, timeout_s: float = 5.0):
    """Run fn() while holding an exclusive fcntl lock on
    community_dir()/.hq-lock. Every write verb holds it; read verbs do not.
    The lock file is created if absent."""
    lock_path = community_dir(anchor_root) / HQ_LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        deadline = time.time() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    raise HqError(
                        f"could not acquire store lock {lock_path} within {timeout_s}s"
                    )
                time.sleep(0.05)
        return fn()
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

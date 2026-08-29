"""verbs.py — the seven hq verbs. Each takes anchor_root/start plus keyword
args, returns a plain dict, and raises HqError with an actionable message on
refusal (store-spec.md §4, §6, §8; hq-contract.md).
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from .anchor import (
    ANCHOR_REL, HqError, check_id_uniqueness, find_anchor_root, find_anchors,
    parse_anchor,
)
from .post import CONFIDENCES, STATUSES, TOPICS, Post, parse_bullet_line
from .store import (
    INDEX_NAME, community_dir, list_posts, list_posts_with_errors, next_number,
    read_post, update_index, with_store_lock, write_post,
)

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _parse_date_prefix(s):
    if not s:
        return None
    m = _DATE_RE.match(s.strip())
    if not m:
        return None
    try:
        return datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _resolve_anchor_id(anchor_root: Path) -> str:
    anchor_file = anchor_root / ANCHOR_REL
    if anchor_file.is_file():
        try:
            return parse_anchor(anchor_file)
        except HqError:
            pass
    return anchor_root.name or str(anchor_root)


def _resolve_anchor_roots_for_query(start: Path) -> list:
    """Ascent for query()/lint(): prefer the strict .hq/.anchor chain; use
    the single nearest legacy-store root when no .hq/.anchor exists anywhere
    in the ascent -- root DISCOVERY only, unaffected by §7 stage 2 (which
    anchor-gates path RESOLUTION downstream, in store.py)."""
    try:
        anchors = find_anchors(start)
    except HqError:
        anchors = []
    if anchors:
        return [a.root for a in anchors]
    return [find_anchor_root(start)]


def _is_git_anchor(anchor_root: Path) -> bool:
    """Decide by walking up for a .git file-or-directory, never by shelling
    out to git — no-git anchors are on iCloud and `git rev-parse` there can
    answer about an unrelated outer repo."""
    cur = anchor_root.resolve()
    for d in [cur, *cur.parents]:
        if (d / ".git").exists():
            return True
    return False


def _chain_heads(posts, subj):
    same = [p for p in posts if p.subject == subj]
    superseded = {p.supersedes for p in same if p.supersedes}
    return [p for p in same if p.id not in superseded]


def _post_to_dict(p: Post) -> dict:
    return {
        "id": p.id, "title": p.title, "path": str(p.path) if p.path else None,
        "fields": dict(p.fields), "summary": p.fields.get("summary", ""),
    }


def post_new(anchor_root, *, category, title, author, summary, body, harness="omo",
             to="all", subject=None, supersedes=None, topic=None, confidence="medium",
             status="none", verified=None, keywords=(), project=None, now):
    if topic is not None and topic not in TOPICS:
        raise HqError(f"unknown topic {topic!r}; expected one of {TOPICS}")
    if confidence not in CONFIDENCES:
        raise HqError(f"unknown confidence {confidence!r}; expected one of {CONFIDENCES}")
    if status not in STATUSES:
        raise HqError(f"unknown status {status!r}; expected one of {STATUSES}")
    if supersedes is not None and subject is None:
        raise HqError("supersedes given but subject is absent — a chain needs a subject")

    def _do():
        if supersedes is not None:
            existing_ids = {p.id for p in list_posts(anchor_root)}
            if supersedes not in existing_ids:
                raise HqError(f"supersedes target {supersedes!r} does not exist")

        n = next_number(anchor_root)
        post_id = f"{category}/{n:03d}"
        fields = {"id": post_id, "date": now, "author": author, "harness": harness, "to": to}
        if project is not None:
            fields["project"] = project
        if subject is not None:
            fields["subject"] = subject
            fields["supersedes"] = supersedes if supersedes is not None else "none"
        if topic is not None:
            fields["topic"] = topic
        fields["confidence"] = confidence
        fields["status"] = status
        # `none` rather than an absent line: `is_legacy` treats a missing `verified`
        # as pre-schema, so omitting it made every post the supported writer produced
        # without `--verified` warn on its own `hq lint` the moment it was written.
        # Same idiom as `supersedes`/`status`/`confidence` — the explicit absence of a
        # verification, not the claim of one.
        fields["verified"] = verified if verified is not None else "none"
        if keywords:
            fields["keywords"] = ", ".join(keywords)
        fields["summary"] = summary

        post = Post(
            path=None, title=title, fields=fields, body=body, comments=[],
            raw_prefix_lines=None, has_comments_section=True,
        )
        path = write_post(anchor_root, post)
        idx = update_index(anchor_root, _resolve_anchor_id(anchor_root), now)
        return {"id": post_id, "path": str(path), "index": str(idx)}

    return with_store_lock(anchor_root, _do)


def comment(anchor_root, post_id, *, author, text, now):
    """Append-only: never rewrites an existing comment line."""
    def _do():
        post = read_post(anchor_root, post_id)
        post.comments.append(f"({now}, {author}) {text}")
        post.has_comments_section = True
        write_post(anchor_root, post)
        return {"id": post_id, "comment_count": len(post.comments)}

    return with_store_lock(anchor_root, _do)


def edit(anchor_root, post_id, *, new_body, reason, author, now):
    if not reason or not reason.strip():
        raise HqError("edit requires a non-empty reason")

    def _do():
        post = read_post(anchor_root, post_id)
        if _is_git_anchor(anchor_root):
            post.body = new_body
            post.comments.append(f"({now}, {author}) 정정: {reason}")
            post.has_comments_section = True
            write_post(anchor_root, post)
            return {"id": post_id, "edited": True}

        subject = post.subject
        if subject is None:
            raise HqError(
                f"{post_id} has no subject: field — it cannot be superseded until it "
                f"has one; add subject: to this post before it can be corrected"
            )
        raise HqError(
            f"{post_id} is on a no-git anchor — its body is immutable there; supersede "
            f"instead: hq post --subject {subject} --supersedes {post_id}"
        )

    return with_store_lock(anchor_root, _do)


def query(start, *, subject=None, post_id=None, keyword=None, harness=None,
          topic=None, status=None, project=None):
    roots = _resolve_anchor_roots_for_query(start)

    if post_id is not None:
        post = read_post(roots[0], post_id)
        return {"post": _post_to_dict(post)}

    if subject is not None:
        per_anchor = []
        for root in roots:
            posts = list_posts(root)
            heads = _chain_heads(posts, subject)
            per_anchor.append(
                {"anchor": _resolve_anchor_id(root), "root": str(root), "heads": heads}
            )

        nearest = per_anchor[0]
        ambiguous = len(nearest["heads"]) > 1
        canonical = (
            _post_to_dict(nearest["heads"][0]) if len(nearest["heads"]) == 1 else None
        )

        shadowed = []
        for entry in per_anchor[1:]:
            if len(entry["heads"]) > 1:
                ambiguous = True
            for h in entry["heads"]:
                d = _post_to_dict(h)
                d["citation"] = f"{entry['anchor']}:{h.id}"
                shadowed.append(d)

        result = {
            "subject": subject, "canonical": canonical, "shadowed": shadowed,
            "ambiguous": ambiguous,
        }
        if ambiguous and canonical is None and nearest["heads"]:
            result["heads_nearest"] = [_post_to_dict(h) for h in nearest["heads"]]
        return result

    posts = list_posts(roots[0])

    def matches(p):
        if keyword is not None:
            hay = " ".join(
                [p.title, p.body, p.fields.get("keywords", ""), p.fields.get("summary", "")]
            ).lower()
            if keyword.lower() not in hay:
                return False
        if harness is not None and p.fields.get("harness") != harness:
            return False
        if project is not None and p.fields.get("project") != project:
            return False
        if topic is not None and p.fields.get("topic") != topic:
            return False
        if status is not None and p.fields.get("status") != status:
            return False
        return True

    return {"posts": [_post_to_dict(p) for p in posts if matches(p)]}


def index(anchor_root, now):
    def _do():
        path = update_index(anchor_root, _resolve_anchor_id(anchor_root), now)
        posts, errors = list_posts_with_errors(anchor_root)
        return {"path": str(path), "count": len(posts), "errors": len(errors)}

    return with_store_lock(anchor_root, _do)


_INDEX_ID_RE = re.compile(r"^- `([a-z]+/\d{3})`", re.M)


def _index_drift(anchor_root, posts):
    """Post ids on disk vs ids listed in INDEX.md.

    `hq post` regenerates the index inside the write lock, so the verb path
    never drifts. What drifts is everything else: a post written by heredoc,
    a rename, a `git rm`, a migration script. None of those pass through a
    verb, so no verb can catch them — and a stale index fails the way this
    store's failures always fail, by answering confidently: `hq query` simply
    does not return the missing post. Lint is the one place that already
    reads every post, so the comparison is nearly free here and nowhere else.
    """
    idx = community_dir(anchor_root) / INDEX_NAME
    if not idx.exists():
        return [f"{INDEX_NAME} is absent — run `hq index`"] if posts else []
    listed = set(_INDEX_ID_RE.findall(idx.read_text(encoding="utf-8")))
    on_disk = {p.id for p in posts}
    out = []
    missing = sorted(on_disk - listed)
    stale = sorted(listed - on_disk)
    if missing:
        out.append(f"{INDEX_NAME} is stale — {len(missing)} post(s) on disk are not "
                   f"listed ({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}); "
                   f"run `hq index`")
    if stale:
        out.append(f"{INDEX_NAME} lists {len(stale)} post(s) that no longer exist "
                   f"({', '.join(stale[:5])}{'...' if len(stale) > 5 else ''}); "
                   f"run `hq index`")
    return out


def lint(start):
    errors: list = []
    warnings: list = []

    try:
        errors.extend(check_id_uniqueness(find_anchors(start)))
    except HqError as e:
        errors.append(str(e))

    root = _resolve_anchor_roots_for_query(start)[0]
    posts, parse_errors = list_posts_with_errors(root)

    for f, reason in parse_errors:
        errors.append(f"{f}: fails to parse — {reason}")

    seen_full: dict = {}
    seen_number: dict = {}
    for p in posts:
        seen_full.setdefault(p.id, []).append(p)
        seen_number.setdefault(p.number, []).append(p)
    for pid, plist in seen_full.items():
        if len(plist) > 1:
            errors.append(f"duplicate post id {pid!r}: {[str(x.path) for x in plist]}")
    for num, plist in seen_number.items():
        cats = {p.category for p in plist}
        if len(cats) > 1:
            errors.append(f"number {num:03d} used in multiple categories: {sorted(cats)}")

    by_id = {p.id: p for p in posts}
    for p in posts:
        if p.supersedes:
            target = by_id.get(p.supersedes)
            if target is None:
                errors.append(f"{p.id}: supersedes {p.supersedes!r} which does not exist")
            elif target.subject is not None and target.subject != p.subject:
                # target.subject is None precisely for a pre-schema/legacy
                # post being superseded for the first time under the new
                # subject: schema (e.g. decision/010 -> decision/009 in the
                # vault store) — D-P1-3's migration is deferred to P6, so a
                # legacy target simply has no subject to conflict with. Only
                # an explicit, differing subject on the target is a real
                # authoring mistake (citing the wrong post).
                errors.append(
                    f"{p.id}: supersedes {p.supersedes!r} but subjects differ "
                    f"({p.subject!r} vs {target.subject!r})"
                )

    by_subject: dict = {}
    for p in posts:
        if p.subject:
            by_subject.setdefault(p.subject, []).append(p)
    for subj, plist in by_subject.items():
        heads = _chain_heads(plist, subj)
        if len(heads) > 1:
            errors.append(f"subject {subj!r} has {len(heads)} chain heads: {[h.id for h in heads]}")

    for p in posts:
        t = p.fields.get("topic")
        if t is not None and t not in TOPICS:
            errors.append(f"{p.id}: topic {t!r} not in {TOPICS}")
        c = p.fields.get("confidence")
        if c is not None and c not in CONFIDENCES:
            errors.append(f"{p.id}: confidence {c!r} not in {CONFIDENCES}")
        s = p.fields.get("status")
        if s is not None and s not in STATUSES:
            errors.append(f"{p.id}: status {s!r} not in {STATUSES}")

    errors.extend(_index_drift(root, posts))

    numbers = sorted(p.number for p in posts)
    if numbers:
        missing = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
        for m in missing:
            warnings.append(f"number gap: {m:03d} missing")

    for p in posts:
        if p.is_legacy:
            warnings.append(
                f"{p.id}: legacy-schema (missing one of subject/topic/confidence/status/verified)"
            )

    for p in posts:
        if p.raw_prefix_lines is not None:
            for line in p.raw_prefix_lines:
                if line.startswith("- "):
                    _, had_rejoin = parse_bullet_line(line)
                    if had_rejoin:
                        warnings.append(
                            f"{p.id}: frontmatter fragment with no ': ' was re-joined"
                        )

    return {"errors": errors, "warnings": warnings}


def gc(anchor_root, *, stale_days=180, now):
    """Report only — never removes, moves, or rewrites a file (D-P1-4)."""
    posts = list_posts(anchor_root)
    today = _parse_date_prefix(now) or datetime.date.today()

    by_subject: dict = {}
    for p in posts:
        if p.subject:
            by_subject.setdefault(p.subject, []).append(p)

    superseded_ids = {p.supersedes for p in posts if p.supersedes}

    stale_resolved = []
    stale_verified = []
    for p in posts:
        if p.fields.get("status") == "resolved":
            d = _parse_date_prefix(p.fields.get("date"))
            if d is not None and (today - d).days > stale_days:
                stale_resolved.append(p.id)
        vd = _parse_date_prefix(p.fields.get("verified"))
        if vd is not None and (today - vd).days > stale_days:
            stale_verified.append(p.id)

    orphan_subjects = []
    for subj, plist in by_subject.items():
        if not _chain_heads(plist, subj):
            orphan_subjects.append(subj)

    return {
        "superseded_count": len(superseded_ids),
        "superseded_ids": sorted(superseded_ids),
        "stale_resolved": stale_resolved,
        "stale_verified": stale_verified,
        "orphan_subjects": sorted(set(orphan_subjects)),
    }

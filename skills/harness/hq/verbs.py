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
from .post import (CONFIDENCES, REVIEW_ASSESSMENTS, STATUSES, TOPICS, Post,
                   counted_reviews, parse_bullet_line, parse_review,
                   set_field_in_raw)
from .rank import rank, score_post
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
        "reviews": counted_reviews(p),
    }


_ISO_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def post_new(anchor_root, *, category, title, author, summary, body, harness="omo",
             to="all", subject=None, supersedes=None, topic=None, confidence="medium",
             status="none", verified=None, keywords=(), project=None, now):
    # `date` shares its bullet with `author`, `harness` and `to`, joined by
    # " \u00b7 ". A caller passing a `now` that already contains that separator
    # writes those keys itself: a migrated page whose `date:` read
    # "2026-08-07 \u00b7 author: someone-else" forged the author line and lint
    # passed it, because lint checks the vocabulary of fields and not the shape
    # of a date. The other bullet-sharing values reach here from a closed
    # vocabulary; this one is free text from a file.
    if not _ISO_DATE_ONLY.match(str(now)):
        raise HqError(f"date must be YYYY-MM-DD, got {now!r}")
    if topic is not None and topic not in TOPICS:
        raise HqError(f"unknown topic {topic!r}; expected one of {TOPICS}")
    if confidence not in CONFIDENCES:
        raise HqError(f"unknown confidence {confidence!r}; expected one of {CONFIDENCES}")
    if status not in STATUSES:
        raise HqError(f"unknown status {status!r}; expected one of {STATUSES}")
    if supersedes is not None and subject is None:
        raise HqError("supersedes given but subject is absent — a chain needs a subject")
    # The keyword default is not a guard. `dict.get(k, d)` returns the STORED
    # value when the key exists, so a caller reading `harness` out of a legacy
    # page's frontmatter -- `e.get("harness", "omo")` where `e["harness"]` is
    # None because a wiki page never had the field -- passes None here and
    # never reaches "omo". `fields` then carries `harness: None` and the
    # renderer's `if fields.get(k)` drops the line: a post with no harness,
    # written by a call that looks like it set one. Measured 300 of 300 posts
    # on ksm-MS-7E01, 2026-09-01, after which `hq query --harness omx`
    # returned `{"posts": []}` on the store holding all of them.
    #
    # Rejected rather than defaulted, and that is the decision: `or "omo"` here
    # would have stamped 300 omx posts as omo, and a wrong harness is worse
    # than a missing one because it looks answered. Guarded at this one point
    # because every writer routes through it; the CLI already passes a string.
    if not harness:
        raise HqError("harness is required — pass the harness that wrote this post; "
                      "`hq query --harness` partitions on it (store-spec §1)")

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


_FORGEABLE = re.compile(r"^\s*(-\s|scope:|evidence:)")


def _has_line_break(s: str) -> bool:
    """True if `s` holds anything the reader will treat as a line break.

    `"\n" in s` is not that test. The store is read back with universal
    newlines, so a lone `\r` written into a value comes back as a line break --
    which is how a CR-separated payload walked past a `\n`-only guard and
    materialised as a counted review by an author nobody invoked (measured
    2026-08-29, exit 0). `splitlines` splits on strictly more separators than
    the file reader joins on, and erring toward refusal is the right side here.
    """
    return s != "".join(s.splitlines())


def _reject_forged_lines(flag: str, value: str) -> None:
    """Refuse free text that would forge structure once serialized.

    A comment block ends at the next `- ` line and its review fields are read
    off `scope:`/`evidence:` continuation lines, so a line break inside free
    text can mint a whole second comment -- including a counted review nobody
    wrote. This is the B1 defect one layer up: there, a newline in `--summary`
    forged a frontmatter bullet and walked straight through the `status:` enum
    gate. Validating one field is worth nothing while another field can forge
    it.
    """
    for line in value.splitlines()[1:]:
        if _FORGEABLE.match(line):
            raise HqError(
                f"{flag} cannot contain a line starting with '- ', 'scope:', or "
                f"'evidence:' — that would forge a separate comment or a review "
                f"field; put the continuation on a line that starts otherwise"
            )


def _canonical_author(value: str) -> str:
    """The author as `parse_review` will read it back, or a refusal.

    Write-time and read-time have to agree on one string. They did not: the
    write gate compared the raw flag while the parser stripped it, so
    `--author " test "` on a post by `test` passed the self-review check and
    was then declined by the parser -- a review written and silently not
    counted. And `--author "rev)"` closed the `(date, author)` paren early, so
    the parser saw no review at all. Both are the same defect this codebase
    keeps re-finding: two readers of one datum under different rules.
    """
    a = value.strip()
    if not a:
        raise HqError("--author cannot be empty")
    if _has_line_break(value) or ")" in a or "," in a:
        raise HqError(
            f"--author {value!r} cannot contain ')', ',', or a line break — the "
            f"comment line is `(date, author) …` and those end the field early"
        )
    return a


def comment(anchor_root, post_id, *, author, text, now,
            assessment=None, scope=None, evidence=None):
    """Append-only: never rewrites an existing comment line.

    With `assessment` this writes a *review* (PLAN B3) rather than a remark.
    All three of scope/evidence/a foreign reviewer are required at write time,
    rather than written-and-then-ignored: `parse_review` refuses to count a
    review missing any of them, and minting a record your own gate discards is
    how a gate ends up looking green while enforcing nothing.
    """
    author = _canonical_author(author)
    _reject_forged_lines("--text", text)
    if assessment is None:
        if scope or evidence:
            raise HqError("--scope/--evidence describe a review; give --assessment too")
    elif assessment not in REVIEW_ASSESSMENTS:
        raise HqError(
            f"unknown assessment {assessment!r}; expected one of {REVIEW_ASSESSMENTS}")
    else:
        for flag, v in (("--scope", scope), ("--evidence", evidence)):
            if not v or not v.strip():
                raise HqError(f"a review requires a non-empty {flag}")
            if _has_line_break(v):
                raise HqError(f"{flag} must be a single line")

    def _do():
        post = read_post(anchor_root, post_id)
        post_author = post.fields.get("author", "").strip()
        if assessment is not None:
            if not post_author:
                raise HqError(
                    f"{post_id} names no author, so a review of it cannot be shown to "
                    f"come from anyone else — add author: to the post first"
                )
            if author == post_author:
                raise HqError(
                    f"{post_id} was written by {author!r} — a review of one's own post "
                    f"is not counted (PLAN 2.2); comment without --assessment, or have "
                    f"another session review it"
                )
        if assessment is None:
            entry = f"({now}, {author}) {text}"
        else:
            entry = (f"({now}, {author}) [{assessment}] {text}\n"
                     f"  scope: {scope.strip()}\n"
                     f"  evidence: {evidence.strip()}")
        post.comments.append(entry)
        post.has_comments_section = True
        write_post(anchor_root, post)
        return {"id": post_id, "comment_count": len(post.comments),
                "review": assessment is not None}

    return with_store_lock(anchor_root, _do)


def edit(anchor_root, post_id, *, new_body=None, reason, author, now,
         new_summary=None, new_status=None):
    if not reason or not reason.strip():
        raise HqError("edit requires a non-empty reason")
    _reject_forged_lines("--reason", reason)   # edit appends a comment too
    author = _canonical_author(author)
    if new_summary is not None and not new_summary.strip():
        raise HqError("edit --summary requires a non-empty value")
    if new_status is not None and new_status not in STATUSES:
        raise HqError(f"unknown status {new_status!r}; expected one of {STATUSES}")
    if new_body is None and new_summary is None and new_status is None:
        raise HqError("edit changes nothing — give --body-file, --summary, or --status")

    def _do():
        post = read_post(anchor_root, post_id)
        if _is_git_anchor(anchor_root):
            # `--body-file` is optional because a field-only edit has no way to
            # supply it: `hq query --post-id` returns fields, never the body, so
            # requiring it would force the caller to hand-extract markdown --
            # exactly the raw-file editing these verbs exist to replace.
            if new_body is not None:
                post.body = new_body
            # `summary:` is the field INDEX.md and `hq query` surface, so a body
            # correction that cannot reach it leaves the post advertising the claim
            # it was just corrected for. Reindex with it -- edit did not touch the
            # index before, which was safe only while nothing indexed could change.
            if new_summary is not None:
                set_field_in_raw(post, "summary", new_summary)
            # `status:` is not on INDEX.md, so it needs the raw-line write but no
            # reindex. It is what ranking and `omx queue-launch` read.
            if new_status is not None:
                set_field_in_raw(post, "status", new_status)
            post.comments.append(f"({now}, {author}) 정정: {reason}")
            post.has_comments_section = True
            write_post(anchor_root, post)
            if new_summary is not None:
                update_index(anchor_root, _resolve_anchor_id(anchor_root), now)
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
          topic=None, status=None, project=None, weight_metadata=False,
          ascend=False):
    # An empty keyword is not "match everything" — `"" in hay` is always true
    # and `body.count("")` returns len(body)+1, so the query would come back
    # with every post ordered longest-first while looking like a search.
    if keyword is not None and not keyword.strip():
        raise HqError("query --keyword requires a non-empty value")
    roots = _resolve_anchor_roots_for_query(start)

    if post_id is not None:
        # `--ascend` reaches here too, because without it the flag hands you a
        # result you cannot then open: a keyword query with `--ascend` returns
        # `{"id": "finding/007", "anchor": "outer"}`, and `--post-id finding/007`
        # without ascent looked only at the nearest anchor and raised
        # "does not exist". A post id is unique only WITHIN an anchor, so the
        # ascent order decides: nearest first, and the answer names the anchor
        # it came from so a same-numbered post elsewhere is never mistaken for it.
        search = roots if ascend else roots[:1]
        post, found_root = None, None
        for root in search:
            try:
                post = read_post(root, post_id)
                found_root = root
                break
            except HqError:
                continue
        if post is None:
            raise HqError(
                f"post {post_id!r} not found in "
                + (f"{len(search)} anchor(s) on the ascent" if ascend
                   else f"the nearest anchor ({roots[0]}) — try --ascend")
            )
        # The body rides along on this path and this path only. `--post-id` asks
        # for one named post in full, so withholding its body forced the one
        # consumer that needed it (omx's `wiki read`) to open the file and
        # re-split the header itself -- a second parser for the format this
        # store exists to have exactly one of. A keyword query still omits
        # bodies: 125 of them in one response is a different question.
        out = {**_post_to_dict(post), "body": post.body}
        if ascend:
            out["anchor"] = _resolve_anchor_id(found_root)
        return {"post": out}

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

    def matches(p):
        if keyword is not None:
            # Membership IS the ranker's own score, not a second rule that
            # happens to agree. Every earlier attempt to state it separately
            # diverged: joining the fields invented phrases in no field;
            # `subject` carried a weight no query could reach; `keywords: none`
            # matched here while scoring zero there. The last one survived all
            # three fixes -- a whole-string substring test drops a multi-word
            # query whose terms live in different fields, so `--keyword "gpu
            # memory"` returned nothing against a post with `keywords: gpu,
            # memory` and both words in its body. Asking the ranker removes the
            # second rule instead of correcting it again.
            if score_post(p, keyword) == (0, 0):
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

    # `--ascend` searches every anchor the ascent reached, not just the nearest.
    # It is opt-in because turning it on by default would silently widen every
    # existing caller's result set -- omx's reader included. The retiring wiki
    # form had exactly this two-level read (a project store plus the parent
    # folder's, merged), and that capability has to arrive here before the wiki
    # can go; a store that moved without it would answer local-only while
    # looking complete.
    search_roots = roots if ascend else roots[:1]

    def _anchor_tag(root):
        # Only under --ascend. Without it every result is from the nearest
        # anchor and the field would be a constant. `--subject` marks the
        # non-nearest instead (`citation`), because there one post is canonical
        # and the rest are shadows; here the results are a flat merged list, so
        # every row says where it came from rather than making absence mean
        # "nearest" -- a rule a reader gets wrong exactly once.
        return _resolve_anchor_id(root) if ascend else None

    if keyword is None:
        out = []
        for root in search_roots:
            tag = _anchor_tag(root)
            for p in list_posts(root):
                if not matches(p):
                    continue
                d = _post_to_dict(p)
                if tag is not None:
                    d["anchor"] = tag
                out.append(d)
        return {"posts": out}

    # Filtering is not ordering. Before this the result came back in post-number
    # order, so `--keyword graphify` led with a post that mentions graphify once
    # in passing while the post *about* graphify sat tenth.
    #
    # Ranking runs PER ANCHOR and the ranked lists are CONCATENATED, nearest
    # store first -- never re-sorted on the two exposed scores.
    #
    # Per anchor because `all_posts` is how the ranker learns what is
    # superseded, and `supersedes:` names an id unique only within one anchor:
    # pooled, anchor A's `finding/007` would mark anchor B's `finding/007` as
    # superseded.
    #
    # Concatenated because `(field, body)` is not the ranker's order, only the
    # part of it that is reported. Its key also carries the metadata weight,
    # chain-head, date and number, and a grounded contradiction deliberately
    # sinks a post BELOW a weaker match -- re-sorting on the two visible scores
    # silently undid that (caught by `RankContradictedSinksTest`). Nearest-first
    # is also what the two-level wiki model this replaces actually promised:
    # the local store is the project's answer, the parent's is the fallback.
    out = []
    for root in search_roots:
        tag = _anchor_tag(root)
        posts = list_posts(root)
        selected = [p for p in posts if matches(p)]
        for post, field_score, body_score in rank(selected, keyword, all_posts=posts,
                                                  weighted=weight_metadata):
            d = _post_to_dict(post)
            d["score"] = {"field": field_score, "body": body_score}
            if tag is not None:
                d["anchor"] = tag
            out.append(d)
    return {"posts": out}


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

    # Aggregated, and a warning rather than an error. `harness:` is what
    # store-spec §1 partitions on -- it is the field that replaced the
    # per-harness directory, so a post without one is unreachable through
    # `hq query --harness` and reachable by nothing else. The whole reason it
    # needs saying here is that nothing said it: 300 posts landed with the
    # field dropped (ksm-MS-7E01, 2026-09-01) and lint answered `clean`,
    # because lint validated the VOCABULARY of the fields present and never
    # the presence of one. Not an error, because a legacy store mid-migration
    # legitimately holds pre-schema posts; not per-post, because 300 lines is
    # how a finding gets scrolled past. The count is the finding.
    no_harness = [p for p in posts if not p.fields.get("harness")]
    if no_harness:
        warnings.append(
            f"{len(no_harness)} post(s) have no harness: — invisible to "
            f"`hq query --harness` (store-spec §1). First: "
            f"{', '.join(p.id for p in no_harness[:5])}"
            f"{'...' if len(no_harness) > 5 else ''}"
        )

    for p in posts:
        for entry in p.comments:
            r = parse_review(entry, p.fields.get("author", ""))
            if r and not r["counted"]:
                warnings.append(
                    f"{p.id}: review by {r['author']!r} is not counted — "
                    f"{r['uncounted_reason']}"
                )

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

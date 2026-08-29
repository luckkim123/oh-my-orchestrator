#!/usr/bin/env python3
"""Convert a store's `community/wiki/` page tree into `posts/` (store-spec §4).

Two phases, because the conversion is not fully mechanical and pretending it
is would invent the parts that matter:

    convert-wiki-form.py plan  <anchor> [--out plan.json]
    convert-wiki-form.py apply <anchor> --plan plan.json [--commit]

`plan` reads every page and fills in what is DERIVABLE. It leaves three fields
null and refuses to guess them, because `finding/098` measured that guessing
each one goes wrong in a specific way:

  * `category`  — the post directory. The axis is what a READER wants to do
    with the post, never its topic (campaign-protocol §Post categories, which
    names "everything ends up in one `finding/`" as the anti-pattern). D22
    settled that wiki pages are distributed across the five categories
    per page, so a script that picked one would be re-deciding D22 by default.
  * `subject`   — the supersede-chain key. The vault conversion had to MINT
    these: albc filenames were truncated at 64 chars (`…citation_a`) and krit
    filenames carried a date, and a subject with a date in it locks every later
    post out of the chain. A filename-derived slug is right often enough to be
    dangerous.
  * `title`     — only when the page has no H1. Two krit pages had none.

`apply` refuses while any of those is null, writes each post through
`verbs.post_new` (the store's one serializer, and its `now=` takes the page's
own date -- the CLI's missing `--date` is what forced the post-hoc `sed` that
`finding/098` recorded as a trap), verifies the body survived byte-for-byte,
and `git rm`s the originals.

What it will NOT do, by design: create a `community/wiki/` directory, or write
anything into one. That form is retired (r7, user decision 2026-08-30).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))
from hq import verbs  # noqa: E402
from hq.anchor import HqError  # noqa: E402
from hq.post import CATEGORIES, TOPICS  # noqa: E402
from hq.store import community_dir, list_posts  # noqa: E402

# Fields measured to be constant or empty across every converted page, so they
# carry no information into the post schema (`finding/098` §"버린 원본 필드").
DROP_FIELDS = frozenset({
    "sources", "links", "schemaVersion", "qualityScore", "qualityReasons",
})
# Tool-generated or meta pages: `hq index` regenerates INDEX.md, and a wiki
# README documents a form that no longer exists.
SKIP_NAMES = frozenset({"index.md", "INDEX.md", "README.md"})

_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_H1 = re.compile(r"^#(?!#)\s+(.+?)\s*$", re.M)


def parse_page(path: Path) -> tuple:
    """(frontmatter dict, body text). No PyYAML: `---` fences, `key: value`
    split on the first colon. A page with no fences is all body."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm = {}
    for line in text[3:end].split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    rest = text[end + len("\n---"):]
    return fm, rest.lstrip("\n")


def derive_verified(text: str):
    """The largest ISO date the page's own text mentions.

    NOT git. `finding/098` measured `git log --follow -M` skipping into an
    unrelated file's history on a migrated tree -- the same seven files gave
    two empty answers, one 2026-05-31 and one migration-commit date. Content
    that says its own freshness is immune to renames and a reader can check it.
    """
    dates = _ISO.findall(text)
    return max(dates) if dates else None


def derive_keywords(fm: dict, limit: int = 6) -> list:
    raw = fm.get("tags", "")
    raw = raw.strip().strip("[]")
    out = []
    for tok in re.split(r"[,\s]+", raw):
        tok = tok.strip().strip("'\"#")
        if tok and tok not in out:
            out.append(tok)
    return out[:limit]


def plan(anchor: Path) -> dict:
    wiki = community_dir(anchor) / "wiki"
    if not wiki.is_dir():
        raise SystemExit(f"no wiki tree at {wiki} — nothing to convert")

    entries, drops, refusals = [], [], []
    for page in sorted(wiki.rglob("*.md")):
        rel = page.relative_to(wiki)
        if page.name in SKIP_NAMES:
            drops.append({"path": str(rel), "reason": "tool-generated or meta page"})
            continue
        # The category axis is the immediate parent directory. A page sitting
        # directly in wiki/ has none -- omp's store is flat by construction
        # (`omp_content_audit.lint_wiki` globs `wiki/*.md`), so this is a real
        # shape, not a malformed one, and `topic` is then a judgment call too.
        topic = rel.parts[0] if len(rel.parts) > 1 else None
        if topic is not None and topic not in TOPICS:
            refusals.append({
                "path": str(rel),
                "reason": f"wiki category {topic!r} has no hq topic; TOPICS={list(TOPICS)}",
            })
            continue
        fm, body = parse_page(page)
        h1 = _H1.search(body)
        text = page.read_text(encoding="utf-8")
        entries.append({
            "path": str(rel),
            "topic": topic,
            "date": fm.get("date"),
            "verified": derive_verified(text),
            "keywords": derive_keywords(fm),
            "dropped_fields": sorted(set(fm) & DROP_FIELDS),
            "kept_fields": {k: v for k, v in fm.items()
                            if k not in DROP_FIELDS and k not in ("title", "tags")},
            "title": h1.group(1) if h1 else None,
            "title_from_h1": bool(h1),
            # judgment — `apply` refuses while any is null
            "category": None,
            "subject": None,
        })
    return {
        "anchor": str(anchor), "wiki": str(wiki),
        "post_categories": list(CATEGORIES),
        "entries": entries, "drops": drops, "refusals": refusals,
    }


def apply(anchor: Path, plan_path: Path, commit: bool) -> int:
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    wiki = Path(data["wiki"])
    entries = data["entries"]

    missing = [
        f"{e['path']}: {', '.join(k for k in ('category', 'subject', 'title') if not e.get(k))}"
        for e in entries
        if not e.get("category") or not e.get("subject") or not e.get("title")
    ]
    if missing:
        print("refusing — the plan still has judgment fields unfilled:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        return 2
    if data.get("refusals"):
        print("refusing — the plan carries unresolved refusals; edit or remove them:",
              file=sys.stderr)
        for r in data["refusals"]:
            print(f"  {r['path']}: {r['reason']}", file=sys.stderr)
        return 2

    # Which subjects already have a head in this store. `apply` is documented
    # as "rerun with --commit", and without this the rerun MINTED A SECOND COPY
    # of all 26 posts -- caught only downstream, by `hq lint` reporting two
    # chain heads per subject. A subject with a head is the store saying "this
    # page is already converted", which also makes a run interrupted halfway
    # resumable instead of destructive.
    existing_subjects = {p.subject for p in list_posts(anchor) if p.subject}

    created, skipped = [], []
    for e in entries:
        if e["subject"] in existing_subjects:
            skipped.append(e["path"])
            print(f"{e['path']} -> already converted (subject {e['subject']!r}), skipped")
            continue
        page = wiki / e["path"]
        _, body = parse_page(page)
        # The H1 becomes the post title, so it must not stay in the body too.
        if e["title_from_h1"]:
            body = _H1.sub("", body, count=1).lstrip("\n")
        res = verbs.post_new(
            anchor, category=e["category"], title=e["title"],
            author="wiki-form-conversion",
            summary=e.get("summary") or e["title"],
            body=body, harness=e.get("harness", "omo"),
            subject=e["subject"], topic=e["topic"],
            confidence=e.get("confidence") or "none",
            status=e.get("status") or "none",
            verified=e.get("verified"), keywords=e["keywords"],
            project=e.get("project"),
            now=e.get("date") or e.get("verified") or "unknown",
        )
        # Byte-for-byte: the conversion moves a form, it does not edit prose.
        written = verbs.read_post(anchor, res["id"])
        if written.body.strip() != body.strip():
            raise SystemExit(f"{e['path']}: body changed on write — refusing to continue")
        created.append((e["path"], res["id"]))
        existing_subjects.add(e["subject"])
        print(f"{e['path']} -> {res['id']}")

    # Only pages that are now IN the store get removed -- a page skipped for a
    # reason other than "already converted" must not be deleted along with them.
    converted = {p for p, _ in created} | set(skipped)
    removed = [str(wiki / e["path"]) for e in entries if e["path"] in converted] + \
              [str(wiki / d["path"]) for d in data.get("drops", [])]
    if skipped:
        print(f"\n{len(skipped)} page(s) were already converted and were not re-created")
    if commit:
        subprocess.run(["git", "rm", "-q", "--", *removed], cwd=anchor, check=True)
        print(f"git rm: {len(removed)} page(s)")
    else:
        print(f"\n{len(removed)} page(s) left in place — rerun with --commit to `git rm` them")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("plan")
    p.add_argument("anchor")
    p.add_argument("--out", default=None)
    a = sub.add_parser("apply")
    a.add_argument("anchor")
    a.add_argument("--plan", required=True)
    a.add_argument("--commit", action="store_true",
                   help="`git rm` the converted pages (omitted: leave them in place)")
    args = ap.parse_args(argv)

    anchor = Path(args.anchor).resolve()
    try:
        if args.verb == "plan":
            out = json.dumps(plan(anchor), ensure_ascii=False, indent=2)
            if args.out:
                Path(args.out).write_text(out + "\n", encoding="utf-8")
                print(f"wrote {args.out}")
            else:
                print(out)
            return 0
        return apply(anchor, Path(args.plan), args.commit)
    except HqError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

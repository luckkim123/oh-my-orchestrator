#!/usr/bin/env python3
"""Convert a store's `community/wiki/` page tree into `posts/` (store-spec §4).

Two phases, because the conversion is not fully mechanical and pretending it
is would invent the parts that matter:

    convert-wiki-form.py plan  <anchor> [--harness omx] [--out plan.json]
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
and `git rm`s the originals. It also writes `<plan>.idmap.json` — the
old-page -> new-id map, which is what a page's `links:`/`sources:` need to stay
resolvable once the files they name are gone (store-spec §9.3.1). Keep it.

What it will NOT do, by design: create a `community/wiki/` directory, or write
anything into one. That form is retired (r7, user decision 2026-08-30).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_DIR))
from hq import verbs  # noqa: E402
from hq.anchor import HqError, parse_anchor  # noqa: E402
from hq.paths import ANCHOR_REL, HQ_ROOT  # noqa: E402
from hq.post import CATEGORIES, TOPICS  # noqa: E402
from hq.store import community_dir, list_posts  # noqa: E402

# Fields measured to be constant or empty across every converted page, so they
# carry no information into the post schema (`finding/098` §"버린 원본 필드").
DROP_FIELDS = frozenset({
    "sources", "links", "schemaVersion", "qualityScore", "qualityReasons",
})
# A dropped field is dropped because it was measured EMPTY or constant, not
# because its name is on a list. `plan` records any that carry a real value so
# `apply` can refuse rather than discard somebody's data on another store.
_EMPTY = frozenset({"", "[]", "{}", "none", "null", "0", "100"})
# Tool-generated or meta pages: `hq index` regenerates INDEX.md, and a wiki
# README documents a form that no longer exists.
SKIP_NAMES = frozenset({"index.md", "INDEX.md", "README.md"})

_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_H1 = re.compile(r"^#(?!#)\s+(.+?)\s*$", re.M)
_FENCE = re.compile(r"^\s*(```|~~~)")


def _strip_fenced(text: str) -> str:
    """Blank out fenced code blocks, keeping line count so offsets still line up.

    A shell or Python comment (`# do the thing`) inside a fence matches the H1
    pattern exactly. Without this the converter took a code comment as the post
    title AND deleted that line from inside the snippet on the way out.
    """
    out, in_fence = [], False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def find_h1(body: str):
    """The first real markdown H1, or None. Never one inside a code fence."""
    return _H1.search(_strip_fenced(body))


def parse_page(path: Path) -> tuple:
    """(frontmatter dict, body text). No PyYAML: `---` fences, `key: value`
    split on the first colon. A page with no fences is all body.

    Both fences must be a LINE that is exactly `---`. `text.find("\n---")` was
    the first cut and it matched the first three dashes anywhere -- including a
    `---` inside a fenced code block, or a YAML document separator in an
    example. Everything above that point was then read as frontmatter, its
    colon-less lines silently dropped, and the prose deleted from the body that
    `apply` writes. The page is `git rm`ed afterwards, so the loss is permanent.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    fm = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm, "\n".join(lines[end + 1:]).lstrip("\n")


def derive_verified(text: str):
    """The largest ISO date the page's own text mentions.

    NOT git. `finding/098` measured `git log --follow -M` skipping into an
    unrelated file's history on a migrated tree -- the same seven files gave
    two empty answers, one 2026-05-31 and one migration-commit date. Content
    that says its own freshness is immune to renames and a reader can check it.
    """
    dates = _ISO.findall(text)
    return max(dates) if dates else None


def _unquote(value):
    """YAML's quotes are not part of the value. `parse_page` splits on the first
    colon and strips whitespace only, so `category: "debugging"` arrives with the
    quote characters attached -- which compares unequal to every TOPIC and turned
    a valid page into an unmappable-category refusal."""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def _leading_day(value):
    """`YYYY-MM-DD` off the front of a date or timestamp, or None.

    A day, not a prefix that looks like one: `2026-02-31garbage` matched the
    shape and `post_new` validates the shape only, so an impossible calendar
    date serialized cleanly. And the rest has to be a real timestamp boundary --
    otherwise `2026-07-0499` reads as the 4th.
    """
    v = _unquote(value)
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?![-\d])", v)
    if not m:
        return None
    try:
        _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return m.group(1)


def derive_keywords(fm: dict, limit: int = 6) -> list:
    raw = fm.get("tags", "")
    raw = raw.strip().strip("[]")
    out = []
    for tok in re.split(r"[,\s]+", raw):
        tok = tok.strip().strip("'\"#")
        if tok and tok not in out:
            out.append(tok)
    return out[:limit]


def ledger_harnesses(anchor: Path) -> list:
    """The distinct `harness` values `migrated.jsonl` recorded at this anchor.

    `migrate-om-store.sh append_ledger` writes one
    `{"harness": "<kind>", "at": ..., "machine": ...}` row per store it copies,
    and that is the ONLY surviving record of where a staged wiki page came
    from: the pages land flat in `community/wiki/` and the `.omx/` they came
    out of is gone by the time anyone converts them. Order preserved, deduped.

    Advisory input to a `--harness` default, never an inference. "Derive it
    from the legacy store directory" is right for a single-store anchor and
    measurably wrong elsewhere: the vault anchor records five distinct kinds,
    and the `ksm-MS-7E01` workspace anchor records two that BOTH shipped wiki
    pages (`.omd` -> decision/001, `.omp` -> 002/003). That is why the
    multi-kind case refuses instead of picking one.
    """
    ledger = anchor / HQ_ROOT / "config" / "migrated.jsonl"
    out: list = []
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            k = json.loads(line).get("harness")
        except ValueError:
            continue              # a hand-edited row is not a reason to fail
        if k and k not in out:
            out.append(k)
    return out


def resolve_harness(anchor: Path, override):
    """The harness to stamp on every converted page, or a refusal.

    A wiki page never carried a `harness:` field -- the field REPLACED the
    per-harness directory the pages used to live in (store-spec §1), so it is
    born at conversion time and there is nowhere else to read it from. It was
    silently dropped instead: `post_new(harness=e.get("harness", "omo"))`
    passed None, because `dict.get` returns a stored None rather than its
    default, and 300 posts reached disk with no harness line at all. `hq query
    --harness omx` then answered `{"posts": []}` on the store holding all 300
    (ksm-MS-7E01, 2026-09-01).

    Required rather than defaulted, for the reason `post_new` now refuses a
    falsy one: defaulting to "omo" would have stamped 300 omx posts omo, and a
    wrong harness is worse than a missing one because it looks answered.
    """
    if override:
        return override
    kinds = ledger_harnesses(anchor)
    if len(kinds) == 1:
        return kinds[0]
    if not kinds:
        raise SystemExit(
            "--harness is required: this anchor has no migrated.jsonl to derive it "
            "from. Pass the harness whose wiki these pages are."
        )
    raise SystemExit(
        f"--harness is required: this anchor's migrated.jsonl records {len(kinds)} "
        f"harnesses ({', '.join(kinds)}), and a flat community/wiki/ cannot say which "
        f"page came from which. Convert one harness's pages at a time."
    )


def write_idmap(anchor: Path, plan_path: Path, pairs: list) -> tuple:
    """Persist old-page -> new-id beside the plan, and never shrink it.

    Three key forms per page, because a citation is written by a human and does
    not agree with itself about which one it uses: the store-relative path
    (`convention/a.md`), the bare filename (`a.md` -- what `links:` actually
    holds), and the stem (`a` -- what prose uses). A form two pages would share
    is DROPPED rather than aliased: `convention/a.md` and `debugging/a.md` both
    claim `a.md`, and silently keeping the last one resolves a citation to the
    WRONG post, which is worse than not resolving it. The dropped forms are
    listed, so the ambiguity is visible rather than absent.

    Merged with whatever the file already holds. `apply` is documented as
    "rerun with --commit", and on that rerun every page lands in `skipped`; a
    rebuild from `created` alone overwrote a complete map with `{}` and then
    deleted the sources. The same merge makes an interrupted run resumable.
    """
    idmap = plan_path.with_suffix(plan_path.suffix + ".idmap.json")
    prior, prior_ambiguous = {}, []
    if idmap.exists():
        try:
            old = json.loads(idmap.read_text(encoding="utf-8"))
            prior = dict(old.get("map") or {})
            prior_ambiguous = list(old.get("ambiguous") or [])
        except (OSError, ValueError, AttributeError, TypeError):
            # A corrupt or non-file map is not permission to write a smaller
            # one over it -- this is the only record of the citation join.
            raise SystemExit(f"{idmap} exists and is not a readable idmap — move "
                             "it aside before rerunning; refusing to overwrite it")

    claims: dict = {}
    for path, pid in pairs:
        for key in (path, Path(path).name, Path(path).stem):
            claims.setdefault(key, set()).add(pid)
    fresh = {k: next(iter(v)) for k, v in claims.items() if len(v) == 1}
    ambiguous = sorted(set(prior_ambiguous) | {k for k, v in claims.items() if len(v) > 1})
    merged = {**prior, **fresh}
    for k in ambiguous:
        merged.pop(k, None)

    try:
        anchor_id = parse_anchor(anchor / ANCHOR_REL)
    except (HqError, OSError):
        anchor_id = None      # no readable anchor file; plain ids still join locally

    payload = json.dumps({
        "anchor": str(anchor), "anchor_id": anchor_id,
        "map": merged, "ambiguous": ambiguous,
    }, ensure_ascii=False, indent=2)
    # Atomic, and loud. A partial map reads exactly like a complete one, and
    # this runs before the `git rm` precisely so a failure here still has pages.
    tmp = idmap.with_suffix(idmap.suffix + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(idmap)
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise SystemExit(f"cannot write {idmap} ({e.strerror}) — refusing to continue: "
                         "the conversion would remove the pages and leave their "
                         "citations with nothing to resolve against")
    if ambiguous:
        print(f"idmap: {len(ambiguous)} ambiguous key(s) dropped (two pages claim "
              f"them): {', '.join(ambiguous[:5])}" + (" …" if len(ambiguous) > 5 else ""))
    return idmap, len(merged)


def plan(anchor: Path, harness: str) -> dict:
    wiki = community_dir(anchor) / "wiki"
    if not wiki.is_dir():
        raise SystemExit(f"no wiki tree at {wiki} — nothing to convert")

    entries, drops, refusals = [], [], []
    for page in sorted(wiki.rglob("*.md")):
        rel = page.relative_to(wiki)
        if page.name in SKIP_NAMES and len(rel.parts) == 1:
            drops.append({"path": str(rel), "reason": "tool-generated or meta page"})
            continue
        if page.name in SKIP_NAMES:
            # A README one level down is a sub-category guide somebody wrote,
            # not the store's own index — `convention/writing-guide/README.md`
            # is a real page in a real store. Dropping by basename alone
            # `git rm`ed it without converting it. Nested ones go through the
            # normal path and need the same judgment fields as any other page.
            pass
        fm, body = parse_page(page)
        # The category axis is the immediate parent directory, and a page with
        # no parent directory may still carry that same axis as a field. omp's
        # store is flat by construction (`omp_content_audit.lint_wiki` globs
        # `wiki/*.md`) and has no such field; omx's is flat AND has one. On the
        # 300-page albc store all 7 distinct `category:` values were already
        # valid TOPICS, 0 unmappable (ksm-MS-7E01, 2026-09-01) -- and `plan`
        # emitted `topic: null` for all 300 while the answer sat unread in
        # `kept_fields`. That is the `confidence` defect below a second time:
        # the tool HELD the value and wrote none. Directory first, so a filed
        # tree still wins over a field that disagrees with it.
        topic_src = "directory"
        topic = rel.parts[0] if len(rel.parts) > 1 else None
        if topic is None and fm.get("category"):
            topic, topic_src = _unquote(fm["category"]), "frontmatter category:"
        if topic is not None and topic not in TOPICS:
            refusals.append({
                "path": str(rel),
                "reason": f"wiki category {topic!r} ({topic_src}) has no hq topic; "
                          f"TOPICS={list(TOPICS)}",
            })
            continue
        h1 = find_h1(body)
        text = page.read_text(encoding="utf-8")
        entries.append({
            "path": str(rel),
            "topic": topic,
            # `created:` is the same fact under the name omx's writer used. 65
            # of 300 pages reached the undated refusal with no `date:` and no
            # derivable `verified:` while carrying `created:` all along -- and
            # `derive_verified` scans the whole file INCLUDING frontmatter, so
            # a bare `created: YYYY-MM-DD` was never one of those 65. What is,
            # is a TIMESTAMP: `_ISO`'s trailing `\b` fails on the `T` in
            # `2026-07-04T13:22:11Z`, so the date is right there and invisible.
            # Hence the leading-day slice rather than the raw value -- `date:`
            # is `YYYY-MM-DD` per store-spec §4 and a timestamp is not one.
            "date": _leading_day(fm.get("date")) or _leading_day(fm.get("created")),
            "verified": derive_verified(text),
            "keywords": derive_keywords(fm),
            "dropped_fields": sorted(set(fm) & DROP_FIELDS),
            "dropped_nonempty": {k: fm[k] for k in sorted(set(fm) & DROP_FIELDS)
                                 if fm[k].strip().lower() not in _EMPTY},
            # Lifted to the top level, because `apply` reads them from there.
            # They used to sit only inside `kept_fields`, which `apply` never
            # opens -- so every page's own `confidence:` was recorded in the
            # plan, looked preserved, and reached the post as "none". Measured:
            # 26 of 26 pages in the real backup tree carried one.
            "confidence": fm.get("confidence"),
            "status": fm.get("status"),
            "summary": fm.get("summary"),
            "project": fm.get("project"),
            # The page's own value wins where it has one -- a store that grew
            # the field mid-life keeps it -- and `--harness` fills the rest.
            # `or`, not `fm.get("harness", harness)`: the key can be PRESENT
            # and None (a `harness:` line with nothing after it parses to an
            # empty string, and a plan hand-edited to null parses to None),
            # and `dict.get`'s default does not fire on either. That exact
            # distinction is the defect this whole path exists to close.
            "harness": fm.get("harness") or harness,
            "kept_fields": {k: v for k, v in fm.items()
                            if k not in DROP_FIELDS
                            and k not in ("title", "tags", "date", "confidence",
                                          "status", "summary", "project", "harness")},
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
    # Both sides resolved: on macOS `/var` is a symlink to `/private/var`, so a
    # caller that passed an unresolved path compared unequal to its own plan.
    anchor = anchor.resolve()
    if Path(data.get("anchor", "")).resolve() != anchor:
        # `wiki` is an absolute path from whichever anchor `plan` ran against.
        # Trusting it while writing posts into a different anchor copies one
        # store's content into another and removes the first store's pages.
        raise SystemExit(
            f"plan was made for anchor {data.get('anchor')!r}, not {anchor} — refusing")
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
    dupes = {}
    for e in entries:
        dupes.setdefault(e["subject"], []).append(e["path"])
    collided = {k: v for k, v in dupes.items() if len(v) > 1}
    if collided:
        # Two pages with one subject silently DESTROYED the second one: the
        # first minted the post, the second hit the already-converted guard,
        # landed in `skipped`, and `skipped` was folded into the `git rm` list.
        # A page removed without a post is the one outcome this tool exists to
        # make impossible, so the collision is refused before anything is written.
        print("refusing — two or more pages share a subject:", file=sys.stderr)
        for subj, paths in sorted(collided.items()):
            print(f"  {subj!r}: {', '.join(paths)}", file=sys.stderr)
        return 2
    missing_topic = [e["path"] for e in entries if not e.get("topic")]
    if missing_topic:
        # A flat `wiki/*.md` tree (omp's shape) has no category directory, so
        # `plan` cannot derive a topic and leaves it null. `post_new` accepts
        # None and writes a post with no `topic:` line, which `hq lint` then
        # reports as legacy-schema. Refusing puts the choice where it belongs.
        print("refusing — these pages have no topic (flat tree: fill it in the plan):",
              file=sys.stderr)
        for pth in missing_topic:
            print(f"  {pth}", file=sys.stderr)
        return 2
    carrying = [(e["path"], e["dropped_nonempty"]) for e in entries
                if e.get("dropped_nonempty")]
    if carrying:
        print("refusing — these pages carry a value in a field this tool drops. "
              "It is on the drop list because it measured empty or constant on the "
              "stores censused, which is not true here:", file=sys.stderr)
        for pth, fields in carrying:
            print(f"  {pth}: {fields}", file=sys.stderr)
        return 2
    undated = [e["path"] for e in entries if not (e.get("date") or e.get("verified"))]
    if undated:
        # `now=` fell back to the literal "unknown", and the ranker's date
        # tiebreaker is a STRING compare: "unknown" > "2026-08-30" is True, so
        # every undated post floated above every dated one on a score tie.
        print("refusing — these pages have neither a date nor a derivable "
              "verified date; set `date` in the plan:", file=sys.stderr)
        for pth in undated:
            print(f"  {pth}", file=sys.stderr)
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
    # subject -> id, not just the subject set: a page skipped as already
    # converted still has a post, and the idmap that replaces its dangling
    # citations needs that id. Building only the set is what made the
    # documented `apply` then `apply --commit` rerun write `"map": {}`.
    posts_by_subject = {p.subject: p.id for p in list_posts(anchor) if p.subject}
    existing_subjects = set(posts_by_subject)

    created, skipped, created_paths = [], [], []
    for e in entries:
        if e["subject"] in existing_subjects:
            skipped.append((e["path"], posts_by_subject[e["subject"]]))
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
            body=body, harness=e.get("harness"),
            subject=e["subject"], topic=e["topic"],
            confidence=e.get("confidence") or "none",
            status=e.get("status") or "none",
            verified=e.get("verified"), keywords=e["keywords"],
            project=e.get("project"),
            now=e.get("date") or e["verified"],
        )
        # Byte-for-byte: the conversion moves a form, it does not edit prose.
        written = verbs.read_post(anchor, res["id"])
        if written.body.strip() != body.strip():
            raise SystemExit(f"{e['path']}: body changed on write — refusing to continue")
        created.append((e["path"], res["id"]))
        created_paths.append((e["path"], res["path"]))
        existing_subjects.add(e["subject"])
        print(f"{e['path']} -> {res['id']}")

    # Only pages that are now IN the store get removed -- a page skipped for a
    # reason other than "already converted" must not be deleted along with them.
    converted = {p for p, _ in created} | {p for p, _ in skipped}
    removed = [str(wiki / e["path"]) for e in entries if e["path"] in converted] + \
              [str(wiki / d["path"]) for d in data.get("drops", [])]
    if skipped:
        print(f"\n{len(skipped)} page(s) were already converted and were not re-created")

    # BEFORE `git rm`, not after. `links:` and `sources:` cite other pages by
    # OLD FILENAME, so the citation graph between converted pages is what a
    # conversion costs unless this join survives -- and a map written after the
    # deletion is a map that an unwritable directory or a full disk turns into
    # deleted sources, a live post, and no way back.
    idmap_path, idmap_n = write_idmap(anchor, plan_path, created + skipped)
    print(f"idmap: {idmap_path} — {idmap_n} page(s)")

    if commit:
        # `--ignore-unmatch` because a page can be untracked (written this
        # session, or in a store whose `wiki/` was never added). Plain `git rm`
        # exits 128 on the first such file and leaves the rest in place, so a
        # half-removed tree looked like a crash rather than a partial run.
        r = subprocess.run(["git", "rm", "-q", "--ignore-unmatch", "--", *removed],
                           cwd=anchor, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"git rm failed: {r.stderr.strip()}")
        left = [f for f in removed if Path(f).exists()]
        for f in left:                       # untracked: git rm ignored them
            Path(f).unlink()
        print(f"git rm: {len(removed) - len(left)} tracked, "
              f"{len(left)} untracked page(s) removed")
        # Stage the posts too. `git rm` stages only the deletions, so a commit
        # made right after recorded the originals disappearing and nothing
        # arriving -- the posts sat untracked under `?? .hq/community/`.
        # The idmap is staged too when it lives inside the anchor: it is the
        # ONLY record of the citation join once the pages are gone, and a
        # commit made right after this used to record their deletion while
        # leaving the map untracked beside it.
        made = sorted({str(Path(res).parent) for _, res in created_paths} |
                      {str(community_dir(anchor) / "INDEX.md")} |
                      ({str(idmap_path)} if idmap_path.is_relative_to(anchor) else set()))
        a = subprocess.run(["git", "add", "--", *made], cwd=anchor,
                           capture_output=True, text=True)
        if a.returncode != 0:
            raise SystemExit(f"git add failed: {a.stderr.strip()}")
        print(f"git add: {len(created_paths)} post(s) + INDEX.md staged")
        # The wiki form is retired, so the exit must take the DIRECTORY with it,
        # not just its pages. `migrate-om-store.sh` copies whatever the store
        # held, and an omp store's `wiki/.gitkeep` is not a `.md`, so it came
        # across and kept `community/wiki/` alive after every page was gone —
        # a live-looking staging directory is exactly what this conversion
        # exists to remove (measured on stonefish_ws, 2026-08-31, deleted by
        # hand). Only `.gitkeep` is removed: anything else left in there is
        # unknown content, and `rmdir` refusing on it is the right outcome.
        if wiki.is_dir() and not any(wiki.rglob("*.md")):
            keep = wiki / ".gitkeep"
            if keep.exists():
                subprocess.run(["git", "rm", "-q", "--ignore-unmatch", "--", str(keep)],
                               cwd=anchor, capture_output=True, text=True)
                if keep.exists():
                    keep.unlink()
            for d in sorted((p for p in wiki.rglob("*") if p.is_dir()),
                            key=lambda p: len(p.parts), reverse=True):
                try:
                    d.rmdir()
                except OSError:
                    pass
            try:
                wiki.rmdir()
                print(f"rmdir: {wiki} — the staging directory is gone")
            except OSError as e:
                print(f"note: {wiki} kept ({e.strerror}) — something else is in it")
    else:
        print(f"\n{len(removed)} page(s) left in place — rerun with --commit to `git rm` them")

    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("plan")
    p.add_argument("anchor")
    p.add_argument("--out", default=None)
    p.add_argument("--harness", default=None,
                   help="harness to stamp on every converted page; derived from the "
                        "anchor's migrated.jsonl when it records exactly one, and "
                        "required otherwise (a page carrying its own wins either way)")
    a = sub.add_parser("apply")
    a.add_argument("anchor")
    a.add_argument("--plan", required=True)
    a.add_argument("--commit", action="store_true",
                   help="`git rm` the converted pages (omitted: leave them in place)")
    args = ap.parse_args(argv)

    anchor = Path(args.anchor).resolve()
    try:
        if args.verb == "plan":
            harness = resolve_harness(anchor, args.harness)
            out = json.dumps(plan(anchor, harness), ensure_ascii=False, indent=2)
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

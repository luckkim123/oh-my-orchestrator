"""cli.py — argparse dispatch + __main__ for the hq CLI (skills/harness/hq).

Every verb is callable from verbs.py without argparse; this module holds only
dispatch. Runs both as a package module (`python3 -m hq.cli`, or `import
hq.cli`) and as a standalone script invoked by the bin/hq shim — the
try/except below puts skills/harness/ on sys.path in the script case so `hq`
resolves as a top-level package, matching how _harness_common.py imports
hq.anchor.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

try:
    from . import __version__, post, verbs
    from .anchor import HqError, find_anchor_root
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from hq import __version__, post, verbs
    from hq.anchor import HqError, find_anchor_root


def _now_date() -> str:
    return datetime.date.today().isoformat()


def _read_body(path_arg: str) -> str:
    if path_arg == "-":
        return sys.stdin.read()
    return Path(path_arg).read_text(encoding="utf-8")


def _resolve_anchor(args) -> Path:
    if args.anchor:
        return Path(args.anchor).resolve()
    return find_anchor_root(Path.cwd())


def _print(data, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if isinstance(data, dict) and "errors" in data and "warnings" in data:
        for e in data["errors"]:
            print(f"ERROR: {e}")
        for w in data["warnings"]:
            print(f"WARN: {w}")
        if not data["errors"] and not data["warnings"]:
            print("lint: clean")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hq")
    p.add_argument("--anchor", default=None, help="anchor root (default: ascend from cwd)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--version", action="store_true")
    sub = p.add_subparsers(dest="verb")

    post_p = sub.add_parser("post")
    post_p.add_argument("--category", required=True)
    post_p.add_argument("--title", required=True)
    post_p.add_argument("--author", required=True)
    post_p.add_argument("--summary", required=True)
    post_p.add_argument("--body-file", required=True, help="path, or '-' for stdin")
    post_p.add_argument("--harness", default="omo")
    post_p.add_argument("--project", default=None)
    post_p.add_argument("--to", default="all")
    post_p.add_argument("--subject", default=None)
    post_p.add_argument("--supersedes", default=None)
    post_p.add_argument("--topic", default=None)
    post_p.add_argument("--confidence", default="medium")
    post_p.add_argument("--status", default="none")
    post_p.add_argument("--verified", default=None)
    post_p.add_argument("--keywords", default=None, help="comma-separated")

    comment_p = sub.add_parser("comment")
    comment_p.add_argument("post_id")
    comment_p.add_argument("--author", required=True)
    comment_p.add_argument("--text", required=True)
    comment_p.add_argument("--assessment", default=None,
                           help=f"make this a review: one of {post.REVIEW_ASSESSMENTS}"
                                f" (requires --scope and --evidence)")
    comment_p.add_argument("--scope", default=None,
                           help="exactly which claim was checked")
    comment_p.add_argument("--evidence", default=None,
                           help="a reproducible command, output, commit, or measurement")

    edit_p = sub.add_parser("edit")
    edit_p.add_argument("post_id")
    edit_p.add_argument("--author", required=True)
    edit_p.add_argument("--reason", required=True)
    edit_p.add_argument("--body-file", default=None,
                        help="path, or '-' for stdin; omit to leave the body alone")
    edit_p.add_argument("--summary", default=None,
                        help="replace summary: too — the field INDEX.md and query show")
    edit_p.add_argument("--status", default=None,
                        help=f"replace status: too — one of {verbs.STATUSES}")

    query_p = sub.add_parser("query")
    query_p.add_argument("--subject", default=None)
    query_p.add_argument("--post-id", default=None)
    query_p.add_argument("--keyword", default=None)
    query_p.add_argument("--harness", default=None)
    query_p.add_argument("--project", default=None)
    query_p.add_argument("--topic", default=None)
    query_p.add_argument("--status", default=None)
    query_p.add_argument("--weight-metadata", action="store_true",
                         help="opt-in: let confidence:/status: re-order NEAR-TIED "
                              "keyword matches (off by default -- see rank.py)")
    query_p.add_argument("--ascend", action="store_true",
                         help="opt-in: search every anchor the ascent reaches, not "
                              "just the nearest; each result carries its `anchor`. "
                              "Applies to --keyword, --post-id, and the "
                              "filter-only form. --subject already walks the "
                              "whole chain without it (canonical + shadowed). "
                              "--post-id resolves nearest-first, because an id "
                              "is unique only within one anchor and "
                              "`finding/007` exists in most of them")

    sub.add_parser("index")
    sub.add_parser("lint")

    gc_p = sub.add_parser("gc")
    gc_p.add_argument("--stale-days", type=int, default=180)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if not args.verb:
        parser.print_help()
        return 1

    try:
        if args.verb == "post":
            root = _resolve_anchor(args)
            body = _read_body(args.body_file)
            keywords = (
                tuple(k.strip() for k in args.keywords.split(",") if k.strip())
                if args.keywords else ()
            )
            result = verbs.post_new(
                root, category=args.category, title=args.title, author=args.author,
                summary=args.summary, body=body, harness=args.harness, to=args.to,
                project=args.project,
                subject=args.subject, supersedes=args.supersedes, topic=args.topic,
                confidence=args.confidence, status=args.status, verified=args.verified,
                keywords=keywords, now=_now_date(),
            )
            _print(result, args.json)
            return 0

        if args.verb == "comment":
            root = _resolve_anchor(args)
            result = verbs.comment(
                root, args.post_id, author=args.author, text=args.text,
                now=_now_date(), assessment=args.assessment, scope=args.scope,
                evidence=args.evidence,
            )
            _print(result, args.json)
            return 0

        if args.verb == "edit":
            root = _resolve_anchor(args)
            new_body = _read_body(args.body_file) if args.body_file else None
            result = verbs.edit(
                root, args.post_id, new_body=new_body, reason=args.reason,
                author=args.author, now=_now_date(), new_summary=args.summary,
                new_status=args.status,
            )
            _print(result, args.json)
            return 0

        if args.verb == "query":
            start = _resolve_anchor(args)
            result = verbs.query(
                start, subject=args.subject, post_id=args.post_id, keyword=args.keyword,
                harness=args.harness, topic=args.topic, status=args.status,
                project=args.project, weight_metadata=args.weight_metadata,
                ascend=args.ascend,
            )
            _print(result, args.json)
            return 0

        if args.verb == "index":
            root = _resolve_anchor(args)
            result = verbs.index(root, _now_date())
            _print(result, args.json)
            return 0

        if args.verb == "lint":
            start = _resolve_anchor(args)
            result = verbs.lint(start)
            _print(result, args.json)
            return 1 if result["errors"] else 0

        if args.verb == "gc":
            root = _resolve_anchor(args)
            result = verbs.gc(root, stale_days=args.stale_days, now=_now_date())
            _print(result, args.json)
            return 0
    except HqError as e:
        print(f"hq: {e}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""post.py — Post dataclass, frontmatter parse/serialize, and validation
constants (store-spec.md §4).

Frontmatter is a run of `- key: value [· key: value ...]` bullets. Splitting
on ' · ' is parenthesis-aware (D-P1-2); a fragment with no ': ' is re-joined
onto the previous fragment's value rather than dropped (lint reports it as a
warning).

Round-trip fidelity for posts parsed off disk is achieved by storing the
exact original title+frontmatter lines (`raw_prefix_lines`) and echoing them
back unchanged on serialize, instead of recomputing frontmatter from the
fixed §4 template. This was necessary: real historical posts group fields
onto bullet lines differently than the template describes — e.g. the vault's
`finding/005-cli-worker-pilot.md` pairs `to:`+`keywords:` on one line, where
the §4 template pairs `harness:`+`to:` and `verified:`+`keywords:`
separately — so template-based reconstruction cannot reproduce them
byte-for-byte, which the mandatory round-trip test requires.
`raw_prefix_lines` is None only for a freshly constructed Post (post_new),
which always uses the §4 template; comment()/edit() never touch frontmatter,
so a parsed post's raw_prefix_lines stays valid across those mutations.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .anchor import HqError

CATEGORIES = ("finding", "decision", "review", "handoff", "question")  # defaults; more allowed
TOPICS = (
    "architecture", "decision", "pattern", "debugging", "environment",
    "reference", "convention", "session-log",
)
# "none" is not an assessment, it is the explicit absence of one — the same
# idiom `status:`/`supersedes:` already use. Added 2026-08-29 so a pre-schema
# post can satisfy the schema without anyone inventing a confidence for it.
CONFIDENCES = ("high", "medium", "low", "none")
STATUSES = ("none", "needs-experiment", "needs-apply-before-retrain", "resolved")

# Keys whose value runs to the end of its bullet line, ' · ' separators and all.
# Only free-prose fields belong here; a field that shares a bullet with another
# key must not be listed, or the key after it is swallowed. store-spec section 4
# puts `summary:` alone on its own bullet, which is what makes it safe.
REST_OF_LINE_KEYS = ("summary",)

_COMMENTS_MARKER = "## Comments"


@dataclass
class Post:
    path: Optional[Path]
    title: str
    fields: dict           # ordered as parsed/serialized
    body: str               # everything between the frontmatter and "## Comments"
    comments: list          # one entry per comment block (first line's "- " stripped;
                             # continuation lines kept verbatim, joined with "\n")
    raw_prefix_lines: Optional[list] = None   # see module docstring
    has_comments_section: bool = False
    comments_lead_blank: bool = False   # a blank line between the marker and
                                        # the first comment; 12 live posts have
                                        # one and dropping it broke round-trip

    @property
    def id(self) -> str:
        return self.fields.get("id", "")

    @property
    def number(self) -> int:
        return int(self.id.partition("/")[2])

    @property
    def category(self) -> str:
        return self.id.partition("/")[0]

    @property
    def subject(self):
        return self.fields.get("subject") or None

    @property
    def supersedes(self):
        v = self.fields.get("supersedes")
        if not v or v.strip().lower() == "none":
            return None
        return v

    @property
    def is_legacy(self) -> bool:
        return any(
            not self.fields.get(k)
            for k in ("subject", "topic", "confidence", "status", "verified")
        )


def _split_paren_aware(s: str, sep: str) -> list:
    parts, buf, depth, i, n, seplen = [], [], 0, 0, len(s), len(sep)
    while i < n:
        ch = s[i]
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
        elif depth == 0 and s[i:i + seplen] == sep:
            parts.append("".join(buf))
            buf = []
            i += seplen
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf))
    return parts


def parse_bullet_line(line: str):
    """Parse one '- key: value · key: value' bullet line (D-P1-2).

    Returns (pairs, had_rejoin): pairs is a list of (key, value) with keys
    lowercased+stripped; had_rejoin is True when a ' · '-split fragment had
    no ': ' and was re-joined onto the previous fragment's value (this is the
    signal lint uses for its "frontmatter fragment re-joined" warning).

    A key in REST_OF_LINE_KEYS swallows the remainder of the bullet verbatim,
    separators and all, and never sets had_rejoin. store-spec section 4 puts
    `summary:` alone on its bullet as free prose, and this store writes prose
    with middle dots -- claudebase `review/006` summarises as "무너짐 3 · 강등 3
    · 유지 1 · 검증불가 0", `finding/015` as "규칙 없음 80% · CLAUDE.md 경유 40%
    · 프롬프트 원문 13%". Splitting those and re-joining them preserved the text
    but warned on both, forever, for writing normal Korean. A lint line that
    fires on correct input teaches people to stop reading lint.
    """
    content = line[2:] if line.startswith("- ") else line
    fragments = _split_paren_aware(content, " · ")
    pairs: list = []
    had_rejoin = False
    for i, frag in enumerate(fragments):
        if ": " in frag:
            key, _, val = frag.partition(": ")
            key = key.strip().lower()
            if key in REST_OF_LINE_KEYS:
                rest = [val.strip(), *(f.strip() for f in fragments[i + 1:])]
                pairs.append([key, " · ".join(rest)])
                break
            pairs.append([key, val.strip()])
        else:
            had_rejoin = True
            if pairs:
                pairs[-1][1] = pairs[-1][1] + " · " + frag.strip()
            # a fragment with no ': ' and no prior key on this line has
            # nothing to attach to; had_rejoin still signals the anomaly.
    return [(k, v) for k, v in pairs if k], had_rejoin


def parse_post(path: Path, raw: str) -> Post:
    lines = raw.split("\n")
    if not lines or not lines[0].startswith("# ") or not lines[0][2:].strip():
        raise HqError(f"{path}: missing or empty title line ('# ...')")
    title = lines[0][2:].strip()

    # Skip blank lines AND any banner/blockquote lines between the title and
    # the frontmatter bullet run (e.g. claudebase's finding/011 has a later
    # `>` correction blockquote sitting directly under the title, before
    # `- id: ...`). Stop early on a heading — a "##" before any bullet line
    # means there is no frontmatter here at all, which is a real failure, not
    # a banner to skip past. Nothing here needs separate preservation: the
    # skipped lines are still inside lines[0:fm_end], which raw_prefix_lines
    # captures verbatim below, so round-trip stays byte-identical.
    i = 1
    while i < len(lines) and not lines[i].startswith("- ") and not lines[i].startswith("##"):
        i += 1
    if i >= len(lines) or lines[i].startswith("##"):
        raise HqError(f"{path}: no frontmatter bullets found before the first heading")
    fm_start = i
    while i < len(lines) and lines[i].startswith("- "):
        i += 1
    fm_end = i
    fm_bullet_lines = lines[fm_start:fm_end]

    fields: dict = {}
    for line in fm_bullet_lines:
        pairs, _ = parse_bullet_line(line)
        for k, v in pairs:
            fields[k] = v

    if "id" not in fields:
        raise HqError(f"{path}: frontmatter has no 'id' field")

    remainder = lines[fm_end:]
    comments_idx = None
    for k, l in enumerate(remainder):
        if l == _COMMENTS_MARKER:
            comments_idx = k
            break

    comments_lead_blank = False
    if comments_idx is not None:
        body_lines = remainder[:comments_idx]
        comment_lines = remainder[comments_idx + 1:]
        has_comments_section = True
        # A blank line directly under "## Comments" is a real authoring choice in
        # this store (12 posts), not noise. It has to survive serialize or every
        # `hq comment`/`hq edit` on those posts silently reflows the file.
        if comment_lines and comment_lines[0] == "" and any(
                l.startswith("- ") for l in comment_lines):
            comments_lead_blank = True
            comment_lines = comment_lines[1:]
    else:
        body_lines = remainder
        comment_lines = []
        has_comments_section = False

    body = "\n".join(body_lines)

    comments: list = []
    cur = None
    for cl in comment_lines:
        if cl.startswith("- "):
            if cur is not None:
                comments.append("\n".join(cur))
            cur = [cl[2:]]
        elif cur is not None:
            cur.append(cl)
        # else: stray content before any '- ' entry started (observed only as
        # the lone blank line produced by EOF's own trailing newline) — not a
        # comment, dropped.
    if cur is not None:
        comments.append("\n".join(cur))

    return Post(
        path=path,
        title=title,
        fields=fields,
        body=body,
        comments=comments,
        raw_prefix_lines=lines[0:fm_end],
        has_comments_section=has_comments_section,
        comments_lead_blank=comments_lead_blank,
    )


_TEMPLATE_LINES = [
    ("id", "date", "author"),
    ("project", "harness", "to"),
    ("subject", "supersedes"),
    ("topic",),
    ("confidence", "status"),
    ("verified", "keywords"),
    ("summary",),
]
_TEMPLATE_KEYS = {k for line in _TEMPLATE_LINES for k in line}


def _build_frontmatter_bullets(fields: dict) -> list:
    out = []
    for keys in _TEMPLATE_LINES:
        parts = [f"{k}: {fields[k]}" for k in keys if fields.get(k)]
        if parts:
            out.append("- " + " · ".join(parts))
    for k, v in fields.items():
        if k not in _TEMPLATE_KEYS and v:
            out.append(f"- {k}: {v}")
    return out


def serialize_post(post: Post) -> str:
    """Reproduce the §4 line grouping for a freshly built Post
    (raw_prefix_lines is None); echo the exact original title+frontmatter
    lines verbatim otherwise. Body/comments mutations (edit()/comment()) are
    folded in either way — see module docstring for why this split exists.
    """
    if post.raw_prefix_lines is not None:
        lines = list(post.raw_prefix_lines) + post.body.split("\n")
    else:
        fm_lines = _build_frontmatter_bullets(post.fields)
        lines = (
            ["# " + post.title, ""] + fm_lines + [""] + post.body.strip("\n").split("\n")
        )

    if post.has_comments_section:
        lines.append(_COMMENTS_MARKER)
        if post.comments_lead_blank:
            lines.append("")
        for entry in post.comments:
            entry_lines = entry.split("\n")
            lines.append("- " + entry_lines[0])
            lines.extend(entry_lines[1:])

    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text

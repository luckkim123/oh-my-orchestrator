"""rank.py — relevance ordering for `hq query --keyword` (PLAN B2).

Ported from omx `wiki/query.py` (CJK bigrams, field-tiered weights), minus
the two weights that port did not earn here. omx multiplies its keyword score
by `confidence` and `status`; measured on this vault's store, `confidence` is
absent on 77 of 122 posts and self-reported on the rest, and `status` is
absent on 113 — and `verified:` is present on exactly the same 45 posts as
`confidence`, so it marks the post-schema generation, not the evidence behind
a post. Weighting any of the three would rank by when a post was written
while claiming to rank by how well it is backed.

What is left is placement: a term the author put in `keywords:` says more than
the same term appearing once in the body. So the key is two-level rather than
blended -- field score first, body only to break its ties -- which is what
PLAN 2.3 asks for ("keyword/subject/summary exact match first, then body").
"""
from __future__ import annotations

import re
from collections import Counter

from .post import counted_reviews

_LATIN = re.compile(r"[a-z0-9À-ɏ]+")
_CJK = re.compile(r"[぀-ヿ一-鿿가-힯]+")

# (field, weight for the whole query as a phrase, weight per token).
# The tuning knob lives here, not inline at the call site.
_FIELDS = (
    ("keywords", 12, 3),
    ("title", 8, 2),
    ("subject", 6, 1),
    ("summary", 6, 1),
)

# OPT-IN only (`--weight-metadata`), never the default. These are omx's
# `_CONFIDENCE_WEIGHT`/`_STATUS_WEIGHT`, carried over verbatim from
# `wiki/query.py` when omx's reader moved onto this ranker (PLAN B4).
#
# The default stays off for the reason B2 gave for not porting them at all:
# measured on this store, `confidence` is absent on 77 of 122 posts and
# `status` on 113, and `verified:` marks the same 45 posts as `confidence`, so
# the fields record the post-schema generation rather than the evidence behind
# a post. Weighting them by default would rank by when a post was written while
# claiming to rank by how well it is backed. A caller whose store *does* fill
# those fields -- which is what omx's experiment trees were built to do -- can
# ask for them; nobody gets them by accident.
#
# Absent (None) is neutral in both maps, never a penalty: a hand-written post
# that never set the field must not sink below one that set it to "low".
_CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.92, "low": 0.80, "none": 0.90, None: 0.90}
_STATUS_WEIGHT = {
    "needs-experiment": 1.0,
    "needs-apply-before-retrain": 1.0,
    "resolved": 0.70,
    "none": 1.0,
    None: 1.0,
}


def metadata_weight(post) -> float:
    """confidence x status multiplier for one post; 1.0-neutral when absent.

    An unknown value is neutral too -- the store's vocabulary is enforced by
    `hq lint`, and a ranker is the wrong place to punish a post for failing it.
    """
    conf = post.fields.get("confidence")
    stat = post.fields.get("status")
    return (_CONFIDENCE_WEIGHT.get(conf, 0.90)
            * _STATUS_WEIGHT.get(stat, 1.0))


def tokenize(text: str) -> list:
    """Lowercased tokens: Latin/digit words, CJK singletons, and CJK bigrams.

    Korean is not space-delimited inside a compound, so a bigram is the
    smallest unit that carries meaning across a word boundary -- without it a
    Korean query orders by nothing at all.
    """
    lower = text.lower()
    tokens = list(_LATIN.findall(lower))
    for seg in _CJK.findall(lower):
        if len(seg) == 1:
            tokens.append(seg)          # a one-character query still has to work
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


def field_text(post, name: str) -> str:
    """The searchable text of one frontmatter field -- the single reader.

    `none` is this store's explicit-absence sentinel (`Post.supersedes` already
    reads it that way), so it is not content. The filter and the ranker have to
    agree about that: when only one of them knew, a post was matched by a word
    it does not contain and then scored zero for that same word.
    """
    v = (post.fields.get(name) or "").strip()
    return "" if v.lower() == "none" else v


def score_post(post, keyword: str) -> tuple:
    """(field_score, body_score) for one post against one keyword string.

    Matching is against each field's TOKENS, not its raw text. Substring
    matching was the first cut and it scored words that merely contain the
    query: `--keyword api` took a title reading "capitalization" to the top of
    the results, and `--keyword cat` ranked a body that says "concatenate" ten
    times above one that says "cat". Tokens give the word boundary that a
    substring never had.
    """
    phrase = keyword.lower()
    terms = set(tokenize(keyword))

    field_score = 0
    for name, phrase_w, token_w in _FIELDS:
        hay = (post.title if name == "title" else field_text(post, name)).lower()
        if not hay:
            continue
        hay_tokens = set(tokenize(hay))
        # The phrase bonus needs the substring AND every term as a real token:
        # the substring alone is what let "api" collect a title bonus from
        # "capitalization". An all-punctuation query has no terms, and the
        # empty set is a subset of anything, so it still searches by substring.
        if terms <= hay_tokens and phrase in hay:
            field_score += phrase_w
        field_score += token_w * len(terms & hay_tokens)

    # Occurrences, not presence: with a one-word query, presence gave every
    # matched post the identical body score and the tier that is supposed to
    # break field ties broke nothing. Counted over tokens for the same
    # word-boundary reason as above; the phrase bonus is a flat constant so a
    # long post cannot accumulate its way past a real match.
    body_tokens = Counter(tokenize(post.body))
    body_score = sum(body_tokens[t] for t in terms)
    if phrase in post.body.lower():
        body_score += 3
    return field_score, body_score


def rank(posts, keyword: str, *, all_posts=None, weighted: bool = False) -> list:
    """Posts ordered by relevance to `keyword`, most relevant first.

    Membership is not touched -- the caller's filter already decided that.

    Being a chain head breaks ties (PLAN 2.3-2); it is NOT the primary key.
    Making it primary read "head" as a global property, so any unrelated
    never-superseded post outranked a superseded post that was squarely about
    the keyword. What 2.3-2 asks for is a preference *within* a chain, and a
    tiebreaker is where that lives. Superseded posts are still returned --
    dropping them would answer a history question with silence.

    `all_posts` is the unfiltered store, and it has to be: a post is superseded
    by the existence of its successor, not by that successor happening to match
    the same keyword. Reading only the filtered set made an outdated post rank
    as a head whenever its replacement used different words.

    `weighted` scales the BODY tier by `metadata_weight` and then uses that same
    weight as its own tier below it -- opt-in, off by default; see that function
    for why it is opt-in and this paragraph for why it is placed here.

    Not the field tier. omx's contract is that these weights "re-order NEAR-tied
    scores while a clearly-stronger keyword match still wins", and omx could
    honour it by blending everything into one number, where a 20x better body
    beats a 0.56 discount. This key is tiered and sorted lexicographically, so a
    discount on the FIRST tier is unrecoverable by the ones below it: applied
    there, `status: resolved` alone dropped a post with twenty keyword matches
    below one with a single mention. That is a veto, not a nudge.

    And not the body tier alone, which was the first fix and was still wrong in
    the other direction: `b * w` is 0 for every weight when b is 0, so two posts
    matching only on their fields -- the common case for a short, well-tagged
    store -- tied at zero and fell through to the accidental tiebreakers, with
    `resolved` sometimes leading. The weight is therefore also its own tier, and
    that tier is what decides when the body scores are equal.

    The RETURNED scores are the weighted ones, not the raw match: a caller that
    re-sorted by a raw score it was handed would get a different order than the
    list it was handed, and this store has already paid four times over for two
    readers of one number disagreeing about the rule.
    """
    superseded = {p.supersedes for p in (all_posts or posts) if p.supersedes}
    scored = []
    for p in posts:
        f, b = score_post(p, keyword)
        w = metadata_weight(p) if weighted else 1.0
        scored.append((f, b * w, w, p.id not in superseded,
                       p.fields.get("date", ""), p))
    scored.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4], t[5].number),
                reverse=True)
    ordered = [t[5] for t in scored]
    score_of = {t[5].id: (t[0], t[1]) for t in scored}

    # Head preference is *within a chain*, which is the only place PLAN 2.3-2
    # asks for it. Neither extreme works: as the primary key it put unrelated
    # never-superseded posts above a superseded post squarely about the
    # keyword, and as a last tiebreaker it let `decision/086` lead the very
    # post that replaced it, on a one-point scoring difference. So a superseded
    # post takes its own head's *position* and then sorts just below it -- and
    # keeps its own position when that head did not match the query at all,
    # because then there is nothing it would be shadowing.
    pos = {p.id: i for i, p in enumerate(ordered)}
    head_pos = {}
    for p in ordered:
        if p.subject and p.id not in superseded:
            head_pos.setdefault(p.subject, pos[p.id])
    ordered.sort(key=lambda p: (
        head_pos.get(p.subject, pos[p.id]) if p.id in superseded else pos[p.id],
        p.id in superseded,
        pos[p.id],
    ))

    # A counted `contradicted` review sinks the post (PLAN B3). It is the one
    # review signal that survives having a population of zero: at n=1 it still
    # says "someone reproduced this being wrong", which is exactly what a
    # ranker should not lead with. `confirmed` gets NO bonus, which PLAN 2.3-4
    # provisions -- a confirm count measures attention, the store has none of
    # them yet to calibrate against, and B2 already refused to weight a field
    # whose population is a proxy for when a post was written. Revisit once
    # confirms exist. Sorting is stable, so everything else keeps its order.
    ordered.sort(key=lambda p: any(
        r["assessment"] == "contradicted" for r in counted_reviews(p)))
    return [(p, score_of[p.id][0], score_of[p.id][1]) for p in ordered]

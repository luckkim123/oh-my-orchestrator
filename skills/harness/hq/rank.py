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


def rank(posts, keyword: str, *, all_posts=None) -> list:
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
    """
    superseded = {p.supersedes for p in (all_posts or posts) if p.supersedes}
    scored = []
    for p in posts:
        f, b = score_post(p, keyword)
        scored.append((f, b, p.id not in superseded, p.fields.get("date", ""), p))
    scored.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4].number), reverse=True)
    ordered = [t[4] for t in scored]
    score_of = {t[4].id: (t[0], t[1]) for t in scored}

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
    return [(p, score_of[p.id][0], score_of[p.id][1]) for p in ordered]

#!/usr/bin/env python3
"""Unit tests for the hq community verbs package (skills/harness/hq).

Matches test_hooks.py's house convention: stdlib unittest, tempfile,
subprocess for CLI checks.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent.parent  # skills/harness
BIN_HQ = HARNESS_DIR.parent.parent / "bin" / "hq"      # repo root/bin/hq

sys.path.insert(0, str(HARNESS_DIR))
from hq import anchor, post, store, verbs  # noqa: E402
from hq.anchor import (  # noqa: E402
    GATE_CORRUPT, GATE_LEGACY, GATE_NORMAL, GATE_OFF, HqError,
)

# Live stores, used by RoundTripTest. These paths have moved twice and the test
# skips silently when they are wrong, so a stale literal here buys nothing but a
# green run: `.community/` -> `.orchestration/` -> `.hq/community/` (store-spec
# §3), and on 2026-08-29 the vault's three boards merged into its root anchor
# (D29), so the vault's posts are no longer under `1_Area/harness/`.
VAULT_POSTS = Path.home() / "ksm_Obsidian" / ".hq" / "community" / "posts"
CLAUDEBASE_POSTS = Path.home() / "claudebase" / ".hq" / "community" / "posts"


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def _write_anchor(root: Path, anchor_id: str) -> None:
    d = root / ".hq"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".anchor").write_text(f"id: {anchor_id}\n", encoding="utf-8")


def _write_post(root: Path, category: str, number: int, *, title: str,
                 extra_bullets: str = "", body: str = "body text.",
                 with_comments: bool = True) -> Path:
    # store-spec §7 stage 2: goes through store.community_dir() rather than
    # hardcoding `.orchestration/`, so it lands wherever the fixture's own
    # anchor state actually resolves -- `.hq/community/posts/` when the
    # caller wrote a `.hq/.anchor` first (every caller here except the two
    # no-anchor fixtures below), `.orchestration/posts/` otherwise.
    d = store.community_dir(root) / "posts" / category
    d.mkdir(parents=True, exist_ok=True)
    fm = f"- id: {category}/{number:03d} · date: 2026-08-27 · author: test\n"
    if extra_bullets:
        fm += extra_bullets
    text = f"# {title}\n\n{fm}\n{body}\n"
    if with_comments:
        text += "\n## Comments\n"
    f = d / f"{number:03d}-{title.lower().replace(' ', '-')}.md"
    f.write_text(text, encoding="utf-8")
    return f


class RoundTripTest(unittest.TestCase):
    """Required: every post in both live stores, copied into a tmpdir, parses
    and re-serializes byte-identically. Skips if a store is absent."""

    def _check_store(self, posts_dir: Path):
        if not posts_dir.is_dir():
            self.skipTest(f"{posts_dir} not present on this machine")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            shutil.copytree(posts_dir, tmp_root / ".orchestration" / "posts")
            parsed, errors = store.list_posts_with_errors(tmp_root)
            self.assertGreater(len(parsed), 0, "expected at least one parseable post")
            for p in parsed:
                original = p.path.read_text(encoding="utf-8")
                self.assertEqual(
                    post.serialize_post(p), original, f"round-trip mismatch: {p.path}"
                )
            return parsed, errors

    def test_vault_store_round_trips(self):
        self._check_store(VAULT_POSTS)

    def test_claudebase_store_round_trips(self):
        self._check_store(CLAUDEBASE_POSTS)

    def test_a_post_with_no_id_field_is_collected_as_an_error_not_dropped(self):
        # store.py contract: "A file that fails to parse is collected, not
        # swallowed" — list_posts_with_errors must report an unparseable file
        # (here: no id: field at all, e.g. an ad hoc pre-schema post) via its
        # second return value, never crash, and never silently drop it from
        # both channels. Synthetic fixture rather than live-store filenames:
        # this was originally pinned to four vault posts (finding/001,002,004,
        # question/003) that predated even the id:/date:/author: "old
        # convention" — the team lead has since patched those files to carry
        # an id: bullet, so pinning specific live filenames here would make
        # the test brittle against further store edits instead of testing
        # the behavior it's meant to test.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_post(root, "finding", 1, title="Has An Id")
            d = root / ".orchestration" / "posts" / "finding"
            (d / "002-no-id.md").write_text(
                "# No Id Here\n\n- 분류: finding\n- 날짜: 2026-08-25\n\nbody\n",
                encoding="utf-8",
            )
            parsed, errors = store.list_posts_with_errors(root)
            self.assertEqual([p.id for p in parsed], ["finding/001"])
            self.assertEqual(len(errors), 1)
            f, reason = errors[0]
            self.assertEqual(f.name, "002-no-id.md")
            self.assertIn("id", reason)


class SummaryRestOfLineTest(unittest.TestCase):
    """`summary:` takes the rest of its bullet verbatim, separators included.

    Both live claudebase posts that tripped the "fragment re-joined" warning did
    so by writing a normal Korean summary with middle dots outside parentheses.
    The re-join preserved the text, so the warning was pure noise on correct
    input -- and a lint line that fires on correct input trains people to stop
    reading lint. `summary:` is safe to treat this way because store-spec
    section 4 puts it alone on its own bullet.
    """

    def test_summary_keeps_middle_dots_and_does_not_flag_a_rejoin(self):
        line = "- summary: 무너짐 3 · 강등 3 · 유지 1 · 검증불가 0 (표적 7 은 후속)"
        pairs, had_rejoin = post.parse_bullet_line(line)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], "summary")
        self.assertEqual(
            pairs[0][1], "무너짐 3 · 강등 3 · 유지 1 · 검증불가 0 (표적 7 은 후속)")
        self.assertFalse(had_rejoin)

    def test_a_genuine_keyless_fragment_still_warns(self):
        # The narrowing must not disarm the check it was carved out of: a
        # fragment with no ': ' on a line that is not a summary is still an
        # anomaly worth reporting.
        _, had_rejoin = post.parse_bullet_line("- to: all · dangling fragment")
        self.assertTrue(had_rejoin)

    def test_a_summary_with_middle_dots_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "010-x.md"
            raw = (
                "# T\n"
                "- id: finding/010 · date: 2026-08-27 · author: a\n"
                "- summary: 규칙 없음 80% · CLAUDE.md 경유 40% · 원문 13%\n"
                "\nbody\n"
            )
            p.write_text(raw, encoding="utf-8")
            parsed = post.parse_post(p, raw)
            self.assertEqual(
                parsed.fields["summary"],
                "규칙 없음 80% · CLAUDE.md 경유 40% · 원문 13%")
            self.assertEqual(post.serialize_post(parsed), raw)


class ParenAwareSplitTest(unittest.TestCase):
    """Required: a post whose verified: value contains ' · ' inside
    parentheses parses into one field (D-P1-2)."""

    def test_verified_field_with_middle_dot_inside_parens_stays_one_field(self):
        line = (
            "- verified: 2026-08-27 (against ksm-mac 실측 · 계획 v5 CONSENSUS ACCEPT) "
            "· keywords: a, b"
        )
        pairs, had_rejoin = post.parse_bullet_line(line)
        d = dict(pairs)
        self.assertFalse(had_rejoin)
        self.assertEqual(
            d["verified"], "2026-08-27 (against ksm-mac 실측 · 계획 v5 CONSENSUS ACCEPT)"
        )
        self.assertEqual(d["keywords"], "a, b")


class BlockquoteBannerBeforeFrontmatterTest(unittest.TestCase):
    """A correction blockquote can sit between the title and the frontmatter
    bullet run (claudebase's finding/011 does this for real). parse_post must
    skip past it rather than failing with "no frontmatter bullets", and
    serialize_post must reproduce it byte-for-byte."""

    def test_blockquote_before_bullets_parses_and_round_trips(self):
        raw = (
            "# Title With A Later Correction\n"
            "\n"
            "> 🔴 **(correction)** this banner sits before the frontmatter.\n"
            "- id: finding/099 · date: 2026-08-27 · author: test\n"
            "- to: all · keywords: a, b\n"
            "- summary: a summary.\n"
            "\n"
            "body text.\n"
        )
        parsed = post.parse_post(Path("finding/099-x.md"), raw)
        self.assertEqual(parsed.id, "finding/099")
        self.assertEqual(post.serialize_post(parsed), raw)

    def test_heading_before_any_bullet_is_a_real_parse_error(self):
        raw = "# No Frontmatter At All\n\n> just a banner\n\n## Comments\n"
        with self.assertRaises(HqError):
            post.parse_post(Path("finding/098-x.md"), raw)


class LintPlantedDefectsTest(unittest.TestCase):
    """Required planted-defect fixtures, one test each."""

    def test_two_chain_heads_for_one_subject_is_lint_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            _write_post(
                root, "finding", 1, title="Head A",
                extra_bullets="- subject: dup-subject · supersedes: none\n",
            )
            _write_post(
                root, "finding", 2, title="Head B",
                extra_bullets="- subject: dup-subject · supersedes: none\n",
            )
            result = verbs.lint(root)
            self.assertTrue(
                any("dup-subject" in e and "chain head" in e for e in result["errors"]),
                result["errors"],
            )

    def test_duplicate_post_id_is_lint_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            d = store.community_dir(root) / "posts" / "finding"
            d.mkdir(parents=True)
            (d / "001-a.md").write_text(
                "# A\n\n- id: finding/001 · date: 2026-08-27 · author: t\n\nbody\n",
                encoding="utf-8",
            )
            (d / "001-b.md").write_text(
                "# B\n\n- id: finding/001 · date: 2026-08-27 · author: t\n\nbody\n",
                encoding="utf-8",
            )
            result = verbs.lint(root)
            self.assertTrue(
                any("duplicate post id" in e for e in result["errors"]), result["errors"]
            )

    def test_duplicate_anchor_id_across_nested_anchors_is_lint_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            _write_anchor(outer, "same-id")
            _write_anchor(inner, "same-id")
            result = verbs.lint(inner)
            self.assertTrue(
                any("duplicate anchor id" in e for e in result["errors"]), result["errors"]
            )


class GateStateTest(unittest.TestCase):
    """Required 4-state fixtures, one test each (gate_state directly)."""

    def test_empty_dir_is_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _reason = anchor.gate_state(Path(tmp))
            self.assertEqual(state, GATE_OFF)

    def test_legacy_store_no_anchor_is_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".orchestration").mkdir()
            state, reason = anchor.gate_state(root)
            self.assertEqual(state, GATE_LEGACY)
            self.assertTrue(reason)

    def test_valid_anchor_no_board_is_normal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            state, _reason = anchor.gate_state(root)
            self.assertEqual(state, GATE_NORMAL)

    def test_valid_anchor_with_invalid_hq_board_json_is_corrupt(self):
        """store-spec §7 stage 2: once an anchor exists, the board that
        matters is .hq/runtime/board.json -- a corrupt .orchestration/
        board.json is never even looked at (see the test right below)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            (root / ".hq" / "runtime").mkdir(parents=True)
            (root / ".hq" / "runtime" / "board.json").write_text("{invalid", encoding="utf-8")
            state, reason = anchor.gate_state(root)
            self.assertEqual(state, GATE_CORRUPT)
            self.assertTrue(reason)

    def test_valid_anchor_with_invalid_legacy_board_json_is_not_examined(self):
        """The other half of the same fix: a corrupt .orchestration/
        board.json is no longer read once an anchor exists -- it is not
        this project's live board anymore, so gate_state() must not trip on
        it (an anchored project with no .hq/ board is a normal off state,
        same as no board at all)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            (root / ".orchestration").mkdir()
            (root / ".orchestration" / "board.json").write_text("{invalid", encoding="utf-8")
            state, _reason = anchor.gate_state(root)
            self.assertEqual(state, GATE_NORMAL)


class EditNoGitAnchorTest(unittest.TestCase):
    """Required: edit on a no-git anchor refuses and the message names the
    subject."""

    def test_edit_refuses_and_names_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            _write_post(
                root, "finding", 1, title="No Git Post",
                extra_bullets="- subject: my-subject · supersedes: none\n",
            )
            with self.assertRaises(HqError) as ctx:
                verbs.edit(
                    root, "finding/001", new_body="new body", reason="typo fix",
                    author="tester", now="2026-08-27",
                )
            msg = str(ctx.exception)
            self.assertIn("my-subject", msg)
            self.assertIn("hq post --subject my-subject --supersedes finding/001", msg)


class QuerySubjectAscentTest(unittest.TestCase):
    """Required: query --subject across two nested anchors returns the inner
    as canonical and the outer in shadowed."""

    def test_inner_is_canonical_outer_is_shadowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            _write_anchor(outer, "outer-anchor")
            _write_anchor(inner, "inner-anchor")
            _write_post(
                outer, "finding", 1, title="Outer Head",
                extra_bullets="- subject: shared-topic · supersedes: none\n",
            )
            _write_post(
                inner, "finding", 1, title="Inner Head",
                extra_bullets="- subject: shared-topic · supersedes: none\n",
            )
            result = verbs.query(inner, subject="shared-topic")
            self.assertIsNotNone(result["canonical"])
            self.assertEqual(result["canonical"]["id"], "finding/001")
            self.assertEqual(result["canonical"]["title"], "Inner Head")
            self.assertEqual(len(result["shadowed"]), 1)
            self.assertEqual(result["shadowed"][0]["title"], "Outer Head")
            self.assertTrue(result["shadowed"][0]["citation"].startswith("outer-anchor:"))


class CommentAppendOnlyTest(unittest.TestCase):
    """Required: comment is append-only — two comments, both present, first
    unchanged."""

    def test_two_comments_both_present_first_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            _write_post(root, "finding", 1, title="Commentable")
            verbs.comment(root, "finding/001", author="a1", text="first comment", now="2026-08-27")
            first_snapshot = store.read_post(root, "finding/001").comments[0]
            verbs.comment(root, "finding/001", author="a2", text="second comment", now="2026-08-28")
            p = store.read_post(root, "finding/001")
            self.assertEqual(len(p.comments), 2)
            self.assertEqual(p.comments[0], first_snapshot)
            self.assertIn("first comment", p.comments[0])
            self.assertIn("second comment", p.comments[1])


class GcWritesNothingTest(unittest.TestCase):
    """Required: gc writes nothing — snapshot the tmpdir tree hash before and
    after."""

    def test_gc_does_not_modify_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            _write_post(
                root, "finding", 1, title="Old Resolved",
                extra_bullets="- confidence: high · status: resolved\n",
                body="body.",
            )
            before = _tree_hash(root)
            verbs.gc(root, stale_days=1, now="2026-08-27")
            after = _tree_hash(root)
            self.assertEqual(before, after)


class CliSmokeTest(unittest.TestCase):
    """A handful of tests go through the CLI, matching test_hooks.py's own
    subprocess convention."""

    def test_version_flag(self):
        proc = subprocess.run([str(BIN_HQ), "--version"], capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(proc.stdout.strip())

    def test_lint_on_clean_anchor_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "t1")
            proc = subprocess.run(
                [str(BIN_HQ), "--anchor", str(root), "lint"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class ProjectFieldTest(unittest.TestCase):
    """D29 (2026-08-29): one `.hq` per repo, so the axis that used to be the
    anchor directory is now the `project:` field. These three checks are what
    make that substitution actually work rather than merely be declared."""

    def test_query_filters_by_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            _write_post(root, "finding", 1, title="A",
                        extra_bullets="- project: alpha · harness: omo · to: all\n")
            _write_post(root, "finding", 2, title="B",
                        extra_bullets="- project: beta · harness: omo · to: all\n")
            ids = lambda **kw: sorted(p["id"] for p in verbs.query(root, **kw)["posts"])
            self.assertEqual(ids(project="alpha"), ["finding/001"])
            self.assertEqual(ids(project="beta"), ["finding/002"])
            # no argument returns everything -- the default has to stay "all",
            # because the failure this merge fixed was records being invisible.
            self.assertEqual(ids(), ["finding/001", "finding/002"])

    def test_project_and_harness_are_independent_axes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            _write_post(root, "finding", 1, title="A",
                        extra_bullets="- project: alpha · harness: omx · to: all\n")
            _write_post(root, "finding", 2, title="B",
                        extra_bullets="- project: alpha · harness: omo · to: all\n")
            got = sorted(p["id"] for p in
                         verbs.query(root, project="alpha", harness="omo")["posts"])
            self.assertEqual(got, ["finding/002"])

    def test_confidence_none_is_accepted(self):
        """A pre-schema post has no confidence to recover. `none` lets it satisfy
        the schema without anyone inventing one -- the same idiom `status:` uses."""
        self.assertIn("none", post.CONFIDENCES)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            res = verbs.post_new(
                root, category="finding", title="T", author="test", summary="s",
                body="b", confidence="none", project="alpha", now="2026-08-29",
            )
            written = (root / ".hq/community/posts/finding/001-t.md").read_text("utf-8")
            self.assertIn("confidence: none", written)
            self.assertIn("project: alpha", written)
            self.assertEqual(res["id"], "finding/001")
            self.assertEqual(verbs.lint(root)["errors"], [])


if __name__ == "__main__":
    unittest.main()

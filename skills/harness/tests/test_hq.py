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
from hq import anchor, post, rank, store, verbs  # noqa: E402
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


class EditSummaryTest(unittest.TestCase):
    """`summary:` is what INDEX.md and `hq query` show, so a body correction that
    cannot reach it leaves the post advertising the claim it was corrected for."""

    def _git_anchor(self, root):
        _write_anchor(root, "one-repo")
        subprocess.run(["git", "init", "-q", str(root)], check=True)

    def test_summary_is_replaced_and_reindexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            verbs.post_new(root, category="finding", title="T", author="t",
                           summary="10 open leads", body="b", subject="s",
                           topic="debugging", now="2026-08-29")
            verbs.edit(root, "finding/001", new_body="corrected",
                       reason="miscounted", author="t", now="2026-08-29",
                       new_summary="5 open leads")
            written = (root / ".hq/community/posts/finding/001-t.md").read_text("utf-8")
            self.assertIn("summary: 5 open leads", written)
            self.assertNotIn("10 open leads", written)
            idx = (root / ".hq/community/INDEX.md").read_text("utf-8")
            self.assertIn("5 open leads", idx)
            self.assertNotIn("10 open leads", idx)
            self.assertEqual(verbs.lint(root)["errors"], [])

    def test_a_summary_with_separators_is_replaced_whole(self):
        """A REST_OF_LINE field owns every segment after its own.

        Measured 2026-08-29: 12 live posts carry ' · ' inside `summary:`, and
        the segment-only replacement left the old value's tail glued onto the
        new one -- `hq edit --summary` silently corrupted them, exit 0.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            verbs.post_new(root, category="finding", title="T", author="t",
                           summary="A 는 X · B 는 Y · C 는 Z", body="b",
                           subject="s", topic="debugging", now="2026-08-29")
            verbs.edit(root, "finding/001", new_body="corrected",
                       reason="miscounted", author="t", now="2026-08-29",
                       new_summary="고침")
            path = root / ".hq/community/posts/finding/001-t.md"
            reparsed = post.parse_post(path, path.read_text("utf-8"))
            self.assertEqual(reparsed.fields["summary"], "고침")

    def test_summary_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            verbs.post_new(root, category="finding", title="T", author="t",
                           summary="kept", body="b", subject="s",
                           topic="debugging", now="2026-08-29")
            verbs.edit(root, "finding/001", new_body="corrected",
                       reason="body only", author="t", now="2026-08-29")
            written = (root / ".hq/community/posts/finding/001-t.md").read_text("utf-8")
            self.assertIn("summary: kept", written)


class RawFieldMutatorTest(unittest.TestCase):
    """`set_field_in_raw` must resolve the SAME occurrence `parse_bullet_line`
    does. All five cases below were reproduced writing the wrong bytes at exit 0
    on 2026-08-29, and four came from a cross-model attack on the first version
    of this mutator -- the author could not see them.
    """

    def _round_trip(self, raw, key, value):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-x.md"
            path.write_text(raw, encoding="utf-8")
            parsed = post.parse_post(path, raw)
            post.set_field_in_raw(parsed, key, value)
            return post.parse_post(path, post.serialize_post(parsed))

    def test_a_rest_of_line_value_hides_a_later_key_from_the_mutator_too(self):
        # `- summary: A · status: none` has NO status field in it -- summary
        # swallows the rest of the bullet. Scanning past it rewrote the prose
        # and left the real status untouched.
        raw = ("# T\n- id: finding/001\n"
               "- summary: A · status: none\n"
               "- confidence: high · status: needs-experiment\n\nb\n")
        out = self._round_trip(raw, "status", "resolved")
        self.assertEqual(out.fields["status"], "resolved")
        self.assertEqual(out.fields["summary"], "A · status: none")

    def test_a_repeated_key_resolves_to_the_last_one(self):
        raw = ("# T\n- id: finding/001\n- status: none\n"
               "- status: needs-experiment\n\nb\n")
        self.assertEqual(
            self._round_trip(raw, "status", "resolved").fields["status"], "resolved")

    def test_a_capitalised_key_is_found(self):
        # parse_bullet_line lowercases keys, so `Status:` IS the status field;
        # a case-sensitive scan called it absent and refused a legitimate edit.
        raw = "# T\n- id: finding/001\n- Status: none\n\nb\n"
        self.assertEqual(
            self._round_trip(raw, "status", "resolved").fields["status"], "resolved")

    def test_a_newline_in_a_value_is_refused(self):
        # It would end the bullet and start another, forging a frontmatter
        # field that never passed its own gate: `--summary $'safe\n- status:
        # hacked'` wrote status: hacked past STATUSES.
        raw = ("# T\n- id: finding/001\n- confidence: high · status: none\n"
               "- summary: safe\n\nb\n")
        with self.assertRaises(HqError):
            self._round_trip(raw, "summary", "safe\n- status: hacked")

    def test_an_absent_field_refuses_loudly(self):
        # A legacy post with no `status:` line cannot be repaired through this
        # verb. That is a boundary, not a silent no-op -- `hq lint` reports such
        # a post as pre-schema and the fix is a supersede.
        raw = "# T\n- id: finding/001\n- confidence: high\n\nb\n"
        with self.assertRaises(HqError):
            self._round_trip(raw, "status", "resolved")


class EditStatusTest(unittest.TestCase):
    """`hq edit --status` -- B1 of the hq-engine-consolidation plan.

    Acceptance (PLAN section 7): the value reaches the FILE, verified by
    re-parsing from disk. `post.fields[...] = v` alone is discarded by
    `serialize_post`, so a fixture that only inspects the in-memory Post is
    green while the file never changed.
    """

    def _git_anchor(self, root):
        _write_anchor(root, "one-repo")
        subprocess.run(["git", "init", "-q", str(root)], check=True)

    def _seed(self, root, **kw):
        verbs.post_new(root, category="finding", title="T", author="t",
                       summary="s", body="b", subject="sub", topic="debugging",
                       now="2026-08-29", **kw)
        return root / ".hq/community/posts/finding/001-t.md"

    def test_status_round_trips_through_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            path = self._seed(root, status="needs-experiment")
            verbs.edit(root, "finding/001", reason="probe ran", author="t",
                       now="2026-08-29", new_status="resolved")
            reparsed = post.parse_post(path, path.read_text("utf-8"))
            self.assertEqual(reparsed.fields["status"], "resolved")
            self.assertEqual(verbs.lint(root)["errors"], [])

    def test_status_change_leaves_its_line_mate_intact(self):
        # `status:` shares a bullet with `confidence:` -- a rest-of-line
        # replacement here would swallow nothing, but a wrong split would.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            path = self._seed(root, confidence="high", status="none")
            verbs.edit(root, "finding/001", reason="r", author="t",
                       now="2026-08-29", new_status="needs-experiment")
            written = path.read_text("utf-8")
            self.assertIn("- confidence: high · status: needs-experiment", written)

    def test_body_survives_a_status_only_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            path = self._seed(root)
            verbs.edit(root, "finding/001", reason="r", author="t",
                       now="2026-08-29", new_status="resolved")
            self.assertIn("\nb\n", path.read_text("utf-8"))

    def test_unknown_status_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            self._seed(root)
            with self.assertRaises(HqError):
                verbs.edit(root, "finding/001", reason="r", author="t",
                           now="2026-08-29", new_status="done")

    def test_an_edit_that_changes_nothing_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git_anchor(root)
            self._seed(root)
            with self.assertRaises(HqError):
                verbs.edit(root, "finding/001", reason="r", author="t",
                           now="2026-08-29")

    def test_no_git_anchor_still_redirects_to_supersede(self):
        # PLAN section 2.4: `--status` does NOT open a write path on a no-git
        # anchor. Ranking must not assume it did.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            self._seed(root)
            with self.assertRaises(HqError) as cm:
                verbs.edit(root, "finding/001", reason="r", author="t",
                           now="2026-08-29", new_status="resolved")
            self.assertIn("supersede", str(cm.exception))


class VerifiedDefaultTest(unittest.TestCase):
    """`is_legacy` reads a missing `verified:` as pre-schema. So a post the
    supported writer produced without `--verified` warned on its own `hq lint`
    the moment it was written -- measured 2026-08-29 against a fresh anchor."""

    def test_post_without_verified_is_not_flagged_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            verbs.post_new(root, category="finding", title="T", author="t",
                           summary="s", body="b", subject="a-subject",
                           topic="debugging", now="2026-08-29")
            written = (root / ".hq/community/posts/finding/001-t.md").read_text("utf-8")
            self.assertIn("verified: none", written)
            warns = verbs.lint(root)["warnings"]
            self.assertFalse([w for w in warns if "legacy-schema" in w], warns)

    def test_explicit_verified_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            verbs.post_new(root, category="finding", title="T", author="t",
                           summary="s", body="b", verified="2026-08-29 (against 0.10.0)",
                           now="2026-08-29")
            written = (root / ".hq/community/posts/finding/001-t.md").read_text("utf-8")
            self.assertIn("verified: 2026-08-29 (against 0.10.0)", written)


class IndexDriftTest(unittest.TestCase):
    """`hq post` reindexes inside the write lock, so the verb path never drifts.
    Everything else does -- a heredoc, a rename, a `git rm`, a migration script --
    and a stale index fails silently: `hq query` just does not return the post."""

    def test_hand_written_post_is_reported_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            verbs.post_new(root, category="finding", title="T", author="t",
                           summary="s", body="b", now="2026-08-29")
            self.assertEqual(verbs.lint(root)["errors"], [])
            _write_post(root, "finding", 2, title="B")     # 손으로 쓴 것 -- verb 를 안 탄다
            errs = verbs.lint(root)["errors"]
            self.assertTrue(any("stale" in e and "finding/002" in e for e in errs), errs)
            verbs.index(root, "2026-08-29")
            self.assertEqual(verbs.lint(root)["errors"], [])

    def test_deleted_post_still_listed_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "one-repo")
            verbs.post_new(root, category="finding", title="T", author="t",
                           summary="s", body="b", now="2026-08-29")
            (root / ".hq/community/posts/finding/001-t.md").unlink()
            errs = verbs.lint(root)["errors"]
            self.assertTrue(any("no longer exist" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()


class TokenizeTest(unittest.TestCase):
    """B2: the CJK half of the port. Korean is not space-delimited inside a
    compound, so without bigrams a Korean query has no ordering signal."""

    def test_latin_words_and_digits(self):
        self.assertEqual(rank.tokenize("Graphify v2"), ["graphify", "v2"])

    def test_korean_yields_bigrams_not_singletons(self):
        # Singletons were in the first cut, ported from omx. A lone Hangul
        # syllable carries no meaning, so they only handed unrelated posts
        # credit: querying 상태 scored a post whose keywords are 상자, 태풍.
        self.assertEqual(rank.tokenize("라우팅"), ["라우", "우팅"])

    def test_a_one_character_query_still_has_a_token(self):
        self.assertEqual(rank.tokenize("팀"), ["팀"])

    def test_matching_is_by_token_not_substring(self):
        # `--keyword api` used to take a title reading "capitalization" first.
        self.assertNotIn("api", set(rank.tokenize("capitalization")))

    def test_mixed_script_keeps_both(self):
        t = rank.tokenize("hq 상태")
        self.assertIn("hq", t)
        self.assertIn("상태", t)


class RankFieldTiersTest(unittest.TestCase):
    """B2 (PLAN §2.3-3): keyword/subject/summary placement outranks the body."""

    def _post(self, **fields):
        f = {"id": "finding/001", "date": "2026-08-27"}
        f.update({k: v for k, v in fields.items() if k != "body" and k != "title"})
        return post.Post(path=None, title=fields.get("title", "t"), fields=f,
                         body=fields.get("body", ""), comments=[])

    def test_keywords_field_outranks_body(self):
        in_kw = self._post(keywords="graphify, index", body="unrelated")
        in_body = self._post(body="graphify " * 50)
        self.assertGreater(rank.score_post(in_kw, "graphify")[0],
                           rank.score_post(in_body, "graphify")[0])

    def test_body_only_scores_zero_on_the_field_tier(self):
        p = self._post(body="graphify appears here")
        self.assertEqual(rank.score_post(p, "graphify")[0], 0)

    def test_body_tier_counts_occurrences_not_presence(self):
        # Presence was the first cut: with a one-word query every matched post
        # scored identically and the tie-breaking tier broke nothing.
        once = self._post(body="graphify")
        thrice = self._post(body="graphify graphify graphify")
        self.assertGreater(rank.score_post(thrice, "graphify")[1],
                           rank.score_post(once, "graphify")[1])

    def test_a_word_that_merely_contains_the_query_does_not_outscore_it(self):
        # `--keyword cat` ranked ten "concatenate"s above one "cat".
        contains = self._post(body="concatenate " * 10)
        is_it = self._post(body="cat")
        self.assertGreater(rank.score_post(is_it, "cat")[1],
                           rank.score_post(contains, "cat")[1])

    def test_ordering_is_field_tier_first_then_body(self):
        weak_field = self._post(summary="graphify")
        strong_body = self._post(body="graphify " * 100)
        ordered = rank.rank([strong_body, weak_field], "graphify")
        self.assertIs(ordered[0][0], weak_field)


class RankSupersededSinksTest(unittest.TestCase):
    """B2 (PLAN §2.3-2): a chain head outranks what it supersedes, even on an
    identical score — but the superseded post is still returned, because
    dropping it would answer a history question with silence."""

    def test_head_leads_and_superseded_is_kept(self):
        common = dict(subject="s", keywords="graphify")
        old = post.Post(path=None, title="old", comments=[], body="",
                        fields={"id": "decision/001", "date": "2026-08-01",
                                "supersedes": "none", **common})
        new = post.Post(path=None, title="new", comments=[], body="",
                        fields={"id": "decision/002", "date": "2026-08-02",
                                "supersedes": "decision/001", **common})
        ordered = [p.id for p, _f, _b in rank.rank([old, new], "graphify")]
        self.assertEqual(ordered, ["decision/002", "decision/001"])


class QueryKeywordRankingTest(unittest.TestCase):
    """B2 acceptance (PLAN §7): the top hit for a word is a post about it."""

    def test_the_post_about_the_word_leads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "a")
            _write_post(root, "finding", 1, title="Path lint recount",
                        body="we ran graphify once to check.")
            _write_post(root, "finding", 2, title="Vault prose is indexed",
                        extra_bullets="- keywords: graphify, prose-index\n"
                                      "- summary: graphify indexed 12,721 md nodes\n",
                        body="graphify graphify")
            ids = [p["id"] for p in verbs.query(root, keyword="graphify")["posts"]]
            self.assertEqual(ids[0], "finding/002")

    def test_subject_is_searchable_because_it_is_scored(self):
        # The filter's haystack and the ranker's weight table are two readers
        # of one post; when they disagreed, `subject:` carried a weight no
        # query could ever reach.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "a")
            _write_post(root, "decision", 1, title="unrelated title",
                        extra_bullets="- subject: om-store-layout\n",
                        body="nothing else matches.")
            ids = [p["id"] for p in verbs.query(root, keyword="om-store-layout")["posts"]]
            self.assertEqual(ids, ["decision/001"])

    def test_score_is_reported_so_the_order_can_be_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "a")
            _write_post(root, "finding", 1, title="x", body="graphify")
            got = verbs.query(root, keyword="graphify")["posts"][0]
            self.assertEqual(set(got["score"]), {"field", "body"})

    def test_a_non_keyword_query_is_unranked_and_carries_no_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "a")
            _write_post(root, "finding", 1, title="x", extra_bullets="- topic: pattern\n")
            got = verbs.query(root, topic="pattern")["posts"][0]
            self.assertNotIn("score", got)


class LiveStoreRankingRegressionTest(unittest.TestCase):
    """The case PLAN §2.1 pinned as the proof that filtering is not ordering:
    `--keyword graphify` used to lead with `finding/088`, which mentions
    graphify in passing, while `finding/121` — the post about it — sat tenth."""

    def test_graphify_leads_with_the_post_about_graphify(self):
        if not VAULT_POSTS.exists():
            self.skipTest("vault store not present on this machine")
        posts = verbs.query(VAULT_POSTS.parents[2], keyword="graphify")["posts"]
        self.assertTrue(posts, "expected the vault store to match 'graphify'")
        self.assertEqual(posts[0]["id"], "finding/121")


class QueryKeywordEdgeTest(unittest.TestCase):
    """Two silent-nonsense inputs found while probing the ranker."""

    def test_empty_keyword_is_refused_not_answered(self):
        # `"" in hay` is always true and `body.count("")` returns len(body)+1,
        # so an empty keyword came back as every post ordered longest-first.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_anchor(root, "a")
            _write_post(root, "finding", 1, title="x")
            with self.assertRaises(HqError):
                verbs.query(root, keyword="   ")

    def test_the_none_sentinel_is_absence_not_content(self):
        p = post.Post(path=None, title="t", comments=[], body="",
                      fields={"id": "finding/001", "keywords": "none"})
        self.assertEqual(rank.score_post(p, "none"), (0, 0))


class RankSupersededOutsideTheFilterTest(unittest.TestCase):
    """A post is superseded by the existence of its successor, not by that
    successor matching the same keyword. Reading the superseded set off the
    filtered slice made an outdated post rank as a head whenever its
    replacement was written with different words."""

    def _p(self, num, **f):
        base = {"id": f"finding/{num:03d}", "date": "2026-08-01", "subject": "s"}
        base.update(f)
        return post.Post(path=None, title=f.pop("title", "t"), comments=[],
                         body=f.pop("body", ""), fields=base)

    def test_the_successor_need_not_match_for_its_parent_to_sink(self):
        # Two equally relevant posts; only one of them is superseded, and its
        # successor is not in the filtered set. Head-ness breaks the tie only
        # if the superseded set was read off the whole store.
        outdated = self._p(1, keywords="servo", supersedes="none")
        rival = self._p(3, subject="other", keywords="servo", supersedes="none")
        successor = self._p(2, supersedes="finding/001", body="rewritten")
        matched = [outdated, rival]
        self.assertEqual(rank.score_post(outdated, "servo"),
                         rank.score_post(rival, "servo"))   # the tie is real
        ids = [p.id for p, _f, _b in
               rank.rank(matched, "servo", all_posts=matched + [successor])]
        self.assertEqual(ids, ["finding/003", "finding/001"])

    def test_without_the_full_store_the_tie_breaks_the_other_way(self):
        # The defect this pins, stated as the behaviour of the old call shape:
        # `outdated` looks like a head because its successor did not match.
        outdated = self._p(1, keywords="servo", supersedes="none")
        rival = self._p(3, subject="other", keywords="servo", supersedes="none")
        ids = [p.id for p, _f, _b in rank.rank([outdated, rival], "servo")]
        self.assertEqual(ids[0], "finding/003")  # both look like heads; number wins

    def test_relevance_outranks_head_ness(self):
        # Head-ness as the PRIMARY key put any unrelated never-superseded post
        # above a superseded post that was squarely about the keyword.
        focused = self._p(1, keywords="graphify", supersedes="none")
        successor = self._p(2, supersedes="finding/001", body="rewritten")
        unrelated = self._p(3, subject="other", supersedes="none", body="graphify")
        ids = [p.id for p, _f, _b in rank.rank([focused, unrelated], "graphify",
                                               all_posts=[focused, successor, unrelated])]
        self.assertEqual(ids[0], "finding/001")


class RankHeadPreferenceIsChainScopedTest(unittest.TestCase):
    """PLAN §2.3-2 asks for head preference *within a chain*. Both extremes
    were tried and both were wrong: as the primary sort key it put unrelated
    never-superseded posts above a superseded post squarely about the keyword;
    as a last tiebreaker it let the live `decision/086` lead the very post that
    replaced it, on a one-point scoring difference."""

    def _p(self, num, **f):
        base = {"id": f"decision/{num:03d}", "date": "2026-08-01", "subject": "s"}
        base.update(f)
        return post.Post(path=None, title=f.pop("title", "t"), comments=[],
                         body=f.pop("body", ""), fields=base)

    def test_the_head_leads_its_chain_even_when_it_scores_lower(self):
        old = self._p(1, keywords="store layout", supersedes="none",
                      summary="om-store-layout om-store-layout")
        new = self._p(2, keywords="store layout", supersedes="decision/001")
        self.assertGreater(rank.score_post(old, "store")[0],
                           rank.score_post(new, "store")[0])   # the inversion is real
        ids = [p.id for p, _f, _b in rank.rank([old, new], "store")]
        self.assertEqual(ids, ["decision/002", "decision/001"])

    def test_a_superseded_post_keeps_its_place_when_its_head_did_not_match(self):
        # Nothing to shadow, so relevance decides and the outdated post leads.
        focused = self._p(1, keywords="graphify", supersedes="none")
        successor = self._p(2, supersedes="decision/001", body="rewritten")
        unrelated = self._p(3, subject="other", supersedes="none", body="graphify")
        ids = [p.id for p, _f, _b in rank.rank([focused, unrelated], "graphify",
                                               all_posts=[focused, successor, unrelated])]
        self.assertEqual(ids[0], "decision/001")

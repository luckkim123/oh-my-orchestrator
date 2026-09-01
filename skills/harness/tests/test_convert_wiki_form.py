#!/usr/bin/env python3
"""convert-wiki-form.py — the wiki→posts form conversion (r7 B).

House convention: stdlib unittest + tempfile, matching test_hq.py.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS_DIR))

_spec = importlib.util.spec_from_file_location(
    "convert_wiki_form", HARNESS_DIR / "convert-wiki-form.py")
cwf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cwf)

from hq import store, verbs  # noqa: E402
from hq.anchor import HqError  # noqa: E402


def _anchor(tmp: Path, anchor_id: str = "conv") -> Path:
    (tmp / ".hq").mkdir(parents=True, exist_ok=True)
    (tmp / ".hq" / ".anchor").write_text(f"id: {anchor_id}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "."], cwd=tmp, check=True)
    return tmp


def _page(tmp: Path, rel: str, text: str) -> Path:
    p = tmp / ".hq" / "community" / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _fill(plan: dict) -> dict:
    for i, e in enumerate(plan["entries"]):
        e["category"] = "finding"
        e["subject"] = f"subject-{i}"
        e.setdefault("date", None)
        if not e["date"] and not e["verified"]:
            e["date"] = "2026-08-30"
    return plan


def _write_plan(tmp: Path, plan: dict) -> Path:
    p = tmp / "plan.json"
    p.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return p


class PlanDerivationTest(unittest.TestCase):
    def test_verified_is_the_largest_iso_date_in_the_text(self):
        # NOT git: `finding/098` measured `git log --follow -M` skipping into an
        # unrelated file's history on a migrated tree.
        self.assertEqual(
            cwf.derive_verified("seen 2026-05-31, corrected 2026-08-25, ref 2026-01-02"),
            "2026-08-25")
        self.assertIsNone(cwf.derive_verified("no dates here"))

    def test_the_category_directory_becomes_the_topic(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "# Title A\n\nbody\n")
            plan = cwf.plan(tmp, "omx")
            self.assertEqual(plan["entries"][0]["topic"], "convention")

    def test_a_nested_directory_still_reports_its_top_category(self):
        # `convention/writing-guide/` exists in a real store (measured on the
        # workspace backup); the topic is the category, not the sub-folder.
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/writing-guide/a.md", "# Nested\n\nbody\n")
            self.assertEqual(cwf.plan(tmp, "omx")["entries"][0]["topic"], "convention")

    def test_an_unmappable_category_is_refused_not_guessed(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "mystery/a.md", "# X\n\nbody\n")
            plan = cwf.plan(tmp, "omx")
            self.assertEqual(plan["entries"], [])
            self.assertEqual(len(plan["refusals"]), 1)
            self.assertIn("mystery", plan["refusals"][0]["reason"])

    def test_technique_and_history_are_mappable(self):
        # Both are real category directories in stores still on backup, and
        # both were absent from TOPICS until r7 widened it.
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "technique/a.md", "# T\n\nbody\n")
            _page(tmp, "history/b.md", "# H\n\nbody\n")
            plan = cwf.plan(tmp, "omx")
            self.assertEqual(plan["refusals"], [])
            self.assertEqual({e["topic"] for e in plan["entries"]},
                             {"technique", "history"})

    def test_a_flat_page_takes_its_topic_from_frontmatter_category(self):
        # omx's store is flat AND carries `category:`. All 300 pages of the
        # albc store planned as `topic: null` while every one of them held a
        # valid TOPIC in that field (ksm-MS-7E01, 2026-09-01).
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "a.md", "---\ncategory: debugging\n---\n\n# Flat\n\nbody\n")
            plan = cwf.plan(tmp, "omx")
            self.assertEqual(plan["refusals"], [])
            self.assertEqual(plan["entries"][0]["topic"], "debugging")

    def test_the_directory_outranks_a_disagreeing_frontmatter_category(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\ncategory: debugging\n---\n\n# Filed\n\nbody\n")
            self.assertEqual(cwf.plan(tmp, "omx")["entries"][0]["topic"], "convention")

    def test_an_unmappable_frontmatter_category_is_refused_not_guessed(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "a.md", "---\ncategory: mystery\n---\n\n# X\n\nbody\n")
            plan = cwf.plan(tmp, "omx")
            self.assertEqual(plan["entries"], [])
            self.assertEqual(len(plan["refusals"]), 1)
            self.assertIn("frontmatter category:", plan["refusals"][0]["reason"])

    def test_a_created_timestamp_is_the_date_fallback(self):
        """The 65 undated pages were undated because of the `T`.

        `derive_verified` scans the whole file INCLUDING frontmatter, so a bare
        `created: YYYY-MM-DD` was never one of them. `_ISO`'s trailing `\\b`
        fails on the `T` of a timestamp, so the date sat there unreadable --
        and `date:` is `YYYY-MM-DD` per store-spec §4, so the slice is the fix,
        not the raw value."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\ncreated: 2026-07-04T13:22:11Z\n---\n\n# C\n\nno date in body\n")
            e = cwf.plan(tmp, "omx")["entries"][0]
            self.assertIsNone(e["verified"], "the T is why _ISO misses it")
            self.assertEqual(e["date"], "2026-07-04")

    def test_a_created_value_that_is_not_a_date_stays_null(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\ncreated: unknown\n---\n\n# C\n\nno date in body\n")
            self.assertIsNone(cwf.plan(tmp, "omx")["entries"][0]["date"])

    def test_date_beats_created_when_both_are_present(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\ndate: 2026-08-01\ncreated: 2026-07-04\n---\n\n# C\n\nbody\n")
            self.assertEqual(cwf.plan(tmp, "omx")["entries"][0]["date"], "2026-08-01")

    def test_judgment_fields_are_left_null(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "# Title\n\nbody\n")
            e = cwf.plan(tmp, "omx")["entries"][0]
            self.assertIsNone(e["category"])
            self.assertIsNone(e["subject"])

    def test_a_page_without_an_h1_leaves_the_title_null(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "---\ntags: x\n---\n\njust body\n")
            e = cwf.plan(tmp, "omx")["entries"][0]
            self.assertIsNone(e["title"])
            self.assertFalse(e["title_from_h1"])

    def test_constant_fields_are_dropped_and_named(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\nschemaVersion: 1\nqualityScore: 100\nkeep: yes\n---\n# T\n\nb\n")
            e = cwf.plan(tmp, "omx")["entries"][0]
            self.assertEqual(e["dropped_fields"], ["qualityScore", "schemaVersion"])
            self.assertIn("keep", e["kept_fields"])

    def test_tool_generated_pages_are_dropped_not_converted(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "INDEX.md", "# index\n")
            _page(tmp, "convention/a.md", "# T\n\nb\n")
            plan = cwf.plan(tmp, "omx")
            self.assertEqual([e["path"] for e in plan["entries"]], ["convention/a.md"])
            self.assertEqual([d["path"] for d in plan["drops"]], ["INDEX.md"])


class ApplyTest(unittest.TestCase):
    def _one_page(self, t):
        tmp = _anchor(Path(t))
        _page(tmp, "convention/a.md", "# Title A\n\nthe body survives.\n")
        return tmp

    def test_apply_refuses_while_a_judgment_field_is_null(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            path = _write_plan(tmp, cwf.plan(tmp, "omx"))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 2)
            self.assertEqual(store.list_posts(tmp), [])

    def test_apply_refuses_while_the_plan_carries_a_refusal(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            _page(tmp, "mystery/b.md", "# B\n\nb\n")
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 2)

    def test_the_body_survives_and_the_h1_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 0)
            posts = store.list_posts(tmp)
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0].title, "Title A")
            self.assertIn("the body survives.", posts[0].body)
            self.assertNotIn("# Title A", posts[0].body)

    def test_apply_persists_the_old_page_to_new_id_map(self):
        """`links:`/`sources:` cite other pages by OLD FILENAME, and `git rm`
        makes every one of them dangle. The loop already knew the join -- it
        printed `path -> id` and let stdout carry it away (measured on the
        300-page albc store, ksm-MS-7E01 2026-09-01)."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 0)
            idmap = json.loads(
                (tmp / "plan.json.idmap.json").read_text(encoding="utf-8"))
            self.assertEqual(idmap["anchor_id"], "conv")
            post_id = store.list_posts(tmp)[0].id
            # Both keys: `links:` cites `a.md`, prose often cites bare `a`.
            self.assertEqual(idmap["map"]["convention/a.md"], post_id)
            self.assertEqual(idmap["map"]["a"], post_id)
            # Three forms, because a citation does not agree with itself.
            self.assertEqual(idmap["map"]["a.md"], post_id)

    def test_the_documented_rerun_does_not_erase_the_map(self):
        """`apply` then `apply --commit` is the documented flow. On the second
        run every page is `skipped`, and rebuilding from `created` alone wrote
        `"map": {}` over a good map and THEN deleted the sources."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 0)
            first = json.loads((tmp / "plan.json.idmap.json").read_text(encoding="utf-8"))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 0)
            second = json.loads((tmp / "plan.json.idmap.json").read_text(encoding="utf-8"))
            self.assertEqual(second["map"], first["map"])
            self.assertTrue(second["map"], "the rerun emptied the map")

    def test_two_pages_claiming_one_filename_drop_that_key(self):
        """`convention/a.md` and `debugging/a.md` both claim `a.md` and `a`.
        Resolving a citation to the WRONG post is worse than not resolving it."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "# One\n\n2026-08-30 body\n")
            _page(tmp, "debugging/a.md", "# Two\n\n2026-08-30 body\n")
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 0)
            idmap = json.loads((tmp / "plan.json.idmap.json").read_text(encoding="utf-8"))
            self.assertIn("a.md", idmap["ambiguous"])
            self.assertIn("a", idmap["ambiguous"])
            self.assertNotIn("a.md", idmap["map"])
            # The unambiguous full paths still resolve.
            self.assertIn("convention/a.md", idmap["map"])
            self.assertIn("debugging/a.md", idmap["map"])

    def test_the_map_exists_before_the_pages_are_removed(self):
        """Written after `git rm`, an unwritable directory left a live post, a
        deleted source, and no way back."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "-qm", "init"], cwd=tmp, check=True)
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=True), 0)
            idmap = tmp / "plan.json.idmap.json"
            self.assertTrue(idmap.is_file())
            self.assertFalse((tmp / ".hq" / "community" / "wiki" / "convention" / "a.md").exists())

    def test_rerunning_does_not_mint_a_second_copy(self):
        """The help text says "rerun with --commit", and without the guard that
        rerun created every post twice -- caught only by `hq lint` reporting two
        chain heads per subject, one layer downstream."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            cwf.apply(tmp, path, commit=False)
            cwf.apply(tmp, path, commit=False)
            self.assertEqual(len(store.list_posts(tmp)), 1)

    def test_commit_removes_the_pages_and_leaves_no_wiki_markdown(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            _page(tmp, "INDEX.md", "# index\n")
            subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "-qm", "init"], cwd=tmp, check=True)
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=True), 0)
            wiki = tmp / ".hq" / "community" / "wiki"
            self.assertEqual(list(wiki.rglob("*.md")), [])

    def _committed_one_page(self, t, extra=None):
        tmp = self._one_page(t)
        if extra:
            (tmp / ".hq" / "community" / "wiki" / extra).write_text("", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "init"], cwd=tmp, check=True)
        return tmp

    def test_commit_takes_the_staging_directory_with_the_last_page(self):
        """A `.gitkeep` is not a `.md`, so `migrate-om-store.sh` carried one
        across and `community/wiki/` outlived every page in it — a retired form
        still looking live in the tree."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._committed_one_page(t, extra=".gitkeep")
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=True), 0)
            self.assertFalse((tmp / ".hq" / "community" / "wiki").exists())

    def test_an_unknown_leftover_keeps_the_directory_rather_than_deleting_it(self):
        """The discrimination: only `.gitkeep` is removed. Anything else in
        there is content nobody classified, and `rmdir` must refuse."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._committed_one_page(t, extra="somebody-elses.txt")
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, commit=True), 0)
            wiki = tmp / ".hq" / "community" / "wiki"
            self.assertTrue(wiki.is_dir())
            self.assertTrue((wiki / "somebody-elses.txt").exists())

    def test_it_never_creates_a_wiki_directory(self):
        """r7's user decision is "Wiki 폴더 안만들게" — the tool reads that tree
        where it already exists and refuses when it does not, never mints one."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            with self.assertRaises(SystemExit):
                cwf.plan(tmp, "omx")
            self.assertFalse((tmp / ".hq" / "community" / "wiki").exists())


if __name__ == "__main__":
    unittest.main()


class ApplyRefusalTest(unittest.TestCase):
    """The three refusals that came out of the cross-model attack on r7's
    first cut. Each one was a silent data loss or a silent wrong answer."""

    def _page(self, t, rel="convention/a.md", text="# Title A\n\nbody\n"):
        tmp = _anchor(Path(t))
        _page(tmp, rel, text)
        return tmp

    def test_two_pages_sharing_a_subject_are_refused_before_anything_is_written(self):
        """The first page minted a post, the second hit the already-converted
        guard, landed in `skipped` — and `skipped` was folded into the `git rm`
        list. The second page was deleted without ever becoming a post."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "# A\n\nbody a\n")
            _page(tmp, "convention/b.md", "# B\n\nbody b\n")
            plan = cwf.plan(tmp, "omx")
            for e in plan["entries"]:
                e["category"], e["subject"], e["date"] = "finding", "same", "2026-08-30"
            path = _write_plan(tmp, plan)
            self.assertEqual(cwf.apply(tmp, path, commit=False), 2)
            self.assertEqual(store.list_posts(tmp), [])

    def test_a_flat_tree_page_is_refused_rather_than_written_without_a_topic(self):
        """omp's store is flat (`wiki/*.md`), so there is no category directory
        to read a topic from. `post_new` accepts None and writes a post with no
        `topic:` line, which `hq lint` then calls legacy-schema."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._page(t, rel="loose.md")
            plan = cwf.plan(tmp, "omx")
            self.assertIsNone(plan["entries"][0]["topic"])
            path = _write_plan(tmp, _fill(plan))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 2)
            self.assertEqual(store.list_posts(tmp), [])

    def test_an_undated_page_is_refused_because_unknown_outsorts_every_date(self):
        """`now=` fell back to the literal "unknown", and the ranker's date
        tiebreaker is a string compare: `"unknown" > "2026-08-30"` is True."""
        self.assertGreater("unknown", "2026-08-30")   # the arithmetic itself
        with tempfile.TemporaryDirectory() as t:
            tmp = self._page(t, text="# T\n\nno date anywhere in this body\n")
            plan = cwf.plan(tmp, "omx")
            self.assertIsNone(plan["entries"][0]["verified"])
            for e in plan["entries"]:
                e["category"], e["subject"] = "finding", "s"
            path = _write_plan(tmp, plan)
            self.assertEqual(cwf.apply(tmp, path, commit=False), 2)


class ParsePageBoundaryTest(unittest.TestCase):
    def test_a_dash_rule_inside_a_code_fence_is_not_the_frontmatter_end(self):
        """`text.find("\\n---")` matched the first three dashes ANYWHERE, so a
        YAML example inside a fence ended the frontmatter and every prose line
        above it was dropped — then the page was `git rm`ed."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            pg = _page(tmp, "convention/a.md",
                       "---\ntags: x\n---\n\n# T\n\nkeep this prose.\n\n"
                       "```yaml\na: 1\n---\nb: 2\n```\n")
            fm, body = cwf.parse_page(pg)
            self.assertEqual(fm, {"tags": "x"})
            self.assertIn("keep this prose.", body)
            self.assertIn("b: 2", body)

    def test_a_page_that_opens_with_a_horizontal_rule_is_all_body(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            pg = _page(tmp, "convention/a.md", "---\n\nnot frontmatter at all\n")
            fm, body = cwf.parse_page(pg)
            self.assertEqual(fm, {})
            self.assertIn("not frontmatter at all", body)

    def test_a_comment_inside_a_code_fence_is_not_the_title(self):
        """`# do the thing` in a shell snippet matches the H1 pattern exactly.
        It became the post title AND was deleted from inside the snippet."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "```bash\n# run the build\nmake\n```\n\n# Real Title\n\nbody\n")
            e = cwf.plan(tmp, "omx")["entries"][0]
            self.assertEqual(e["title"], "Real Title")

    def test_a_nested_readme_is_content_not_a_dropped_meta_page(self):
        """`convention/writing-guide/README.md` is a real page in a real store.
        Skipping by basename `git rm`ed it without converting it."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "README.md", "# store readme\n")
            _page(tmp, "convention/writing-guide/README.md", "# Guide\n\nbody\n")
            plan = cwf.plan(tmp, "omx")
            self.assertEqual([d["path"] for d in plan["drops"]], ["README.md"])
            self.assertEqual([e["path"] for e in plan["entries"]],
                             ["convention/writing-guide/README.md"])


class HarnessFieldTest(unittest.TestCase):
    """`harness:` — the field store-spec §1 partitions on, dropped in silence.

    A legacy wiki page never carried one: the field REPLACED the per-harness
    directory the pages used to live in, so it is born at conversion time. The
    converter read it anyway (`fm.get("harness")` -> None) and handed that None
    to `post_new(harness=e.get("harness", "omo"))`, where `dict.get`'s default
    does not fire on a key that exists holding None. `fields["harness"] = None`,
    the renderer's `if fields.get(k)` dropped the line, and 300 of 300 converted
    posts reached disk with no harness while every layer reported clean
    (ksm-MS-7E01, 2026-09-01). `hq query --harness omx` then returned
    `{"posts": []}` on the store holding all 300.
    """

    @staticmethod
    def _ledger(tmp: Path, *kinds: str) -> None:
        p = tmp / ".hq" / "config" / "migrated.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(
            json.dumps({"harness": k, "at": "2026-01-01T00:00:00+09:00",
                        "machine": "test"}) + "\n" for k in kinds),
            encoding="utf-8")

    def test_the_dict_get_default_does_not_fire_on_a_stored_none(self):
        """The two-line mechanism, isolated. This is the whole defect."""
        e = {"harness": None}
        self.assertIsNone(e.get("harness", "omo"))      # NOT "omo" — the trap
        self.assertEqual(e.get("harness") or "omo", "omo")

    def test_a_page_with_no_harness_gets_the_resolved_one(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "---\ndate: 2026-08-01\n---\n\n# T\n\nbody\n")
            self.assertEqual(cwf.plan(tmp, "omx")["entries"][0]["harness"], "omx")

    def test_a_page_carrying_its_own_harness_keeps_it(self):
        """`--harness` fills the blank; it does not overwrite a real value."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\ndate: 2026-08-01\nharness: omd\n---\n\n# T\n\nbody\n")
            self.assertEqual(cwf.plan(tmp, "omx")["entries"][0]["harness"], "omd")

    def test_an_empty_harness_line_falls_back_rather_than_writing_blank(self):
        """`harness:` with nothing after it parses to "" — falsy, not absent.
        `fm.get("harness", harness)` would have returned that empty string."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\ndate: 2026-08-01\nharness:\n---\n\n# T\n\nbody\n")
            self.assertEqual(cwf.plan(tmp, "omx")["entries"][0]["harness"], "omx")

    def test_the_written_post_actually_carries_the_line(self):
        """The end-to-end assertion. `plan` holding the value is not enough —
        the 2026-09-01 store's plan held `confidence` too, and the posts did
        not, because `apply` read a different key. Read it back off disk."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "---\ndate: 2026-08-01\n---\n\n# T\n\nbody\n")
            path = _write_plan(tmp, _fill(cwf.plan(tmp, "omx")))
            self.assertEqual(cwf.apply(tmp, path, False), 0)
            posts = list(store.list_posts(tmp))
            self.assertEqual([p.fields.get("harness") for p in posts], ["omx"])
            self.assertIn("harness: omx",
                          posts[0].path.read_text(encoding="utf-8"))

    def test_a_single_kind_ledger_supplies_the_default(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            self._ledger(tmp, "omx", "omx")
            self.assertEqual(cwf.ledger_harnesses(tmp), ["omx"])
            self.assertEqual(cwf.resolve_harness(tmp, None), "omx")

    def test_a_multi_kind_ledger_refuses_instead_of_picking(self):
        """The workspace anchor on ksm-MS-7E01: `.omd` wrote decision/001 and
        `.omp` wrote 002/003, both into one flat staging directory. Deriving
        per-anchor would have stamped one of them wrong."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            self._ledger(tmp, "omd", "omp")
            with self.assertRaises(SystemExit) as cm:
                cwf.resolve_harness(tmp, None)
            self.assertIn("2 harnesses", str(cm.exception))
            self.assertEqual(cwf.resolve_harness(tmp, "omd"), "omd")

    def test_no_ledger_refuses_rather_than_defaulting_to_omo(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            with self.assertRaises(SystemExit) as cm:
                cwf.resolve_harness(tmp, None)
            self.assertIn("--harness is required", str(cm.exception))

    def test_post_new_refuses_a_falsy_harness(self):
        """The choke-point guard. Every writer routes through here, so a future
        caller that reconstructs the same None cannot write a harness-less post
        even if this converter is not the one doing it."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            for bad in (None, ""):
                with self.assertRaises(HqError) as cm:
                    verbs.post_new(tmp, category="finding", title="T", author="t",
                                   summary="s", body="b", harness=bad,
                                   now="2026-08-30")
                self.assertIn("harness is required", str(cm.exception))

    def test_lint_names_the_count_of_posts_with_no_harness(self):
        """The layer that reported `clean` on 300 harness-less posts."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            res = verbs.post_new(tmp, category="finding", title="T", author="t",
                                 summary="s", body="b", harness="omx",
                                 now="2026-08-30")
            # Scoped to this warning, not to an empty list: a bare post also
            # trips the unrelated legacy-schema warning, and asserting silence
            # would make this test fail on any future warning anywhere.
            self.assertFalse([w for w in verbs.lint(tmp)["warnings"]
                              if "no harness" in w])
            p = tmp / ".hq" / "community" / "posts" / "finding"
            f = next(p.glob("001-*.md"))
            # The bullet is `- harness: omx · to: all` when the post has no
            # `project:`, so the separator sits AFTER the pair, not before it.
            f.write_text(f.read_text(encoding="utf-8")
                         .replace("harness: omx · ", ""), encoding="utf-8")
            warn = verbs.lint(tmp)["warnings"]
            self.assertTrue(any("1 post(s) have no harness:" in w for w in warn),
                            warn)
            self.assertIn(res["id"], " ".join(warn))

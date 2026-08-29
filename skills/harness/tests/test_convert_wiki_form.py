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

from hq import store  # noqa: E402


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
            plan = cwf.plan(tmp)
            self.assertEqual(plan["entries"][0]["topic"], "convention")

    def test_a_nested_directory_still_reports_its_top_category(self):
        # `convention/writing-guide/` exists in a real store (measured on the
        # workspace backup); the topic is the category, not the sub-folder.
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/writing-guide/a.md", "# Nested\n\nbody\n")
            self.assertEqual(cwf.plan(tmp)["entries"][0]["topic"], "convention")

    def test_an_unmappable_category_is_refused_not_guessed(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "mystery/a.md", "# X\n\nbody\n")
            plan = cwf.plan(tmp)
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
            plan = cwf.plan(tmp)
            self.assertEqual(plan["refusals"], [])
            self.assertEqual({e["topic"] for e in plan["entries"]},
                             {"technique", "history"})

    def test_judgment_fields_are_left_null(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "# Title\n\nbody\n")
            e = cwf.plan(tmp)["entries"][0]
            self.assertIsNone(e["category"])
            self.assertIsNone(e["subject"])

    def test_a_page_without_an_h1_leaves_the_title_null(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md", "---\ntags: x\n---\n\njust body\n")
            e = cwf.plan(tmp)["entries"][0]
            self.assertIsNone(e["title"])
            self.assertFalse(e["title_from_h1"])

    def test_constant_fields_are_dropped_and_named(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "convention/a.md",
                  "---\nschemaVersion: 1\nqualityScore: 100\nkeep: yes\n---\n# T\n\nb\n")
            e = cwf.plan(tmp)["entries"][0]
            self.assertEqual(e["dropped_fields"], ["qualityScore", "schemaVersion"])
            self.assertIn("keep", e["kept_fields"])

    def test_tool_generated_pages_are_dropped_not_converted(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            _page(tmp, "INDEX.md", "# index\n")
            _page(tmp, "convention/a.md", "# T\n\nb\n")
            plan = cwf.plan(tmp)
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
            path = _write_plan(tmp, cwf.plan(tmp))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 2)
            self.assertEqual(store.list_posts(tmp), [])

    def test_apply_refuses_while_the_plan_carries_a_refusal(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            _page(tmp, "mystery/b.md", "# B\n\nb\n")
            path = _write_plan(tmp, _fill(cwf.plan(tmp)))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 2)

    def test_the_body_survives_and_the_h1_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            path = _write_plan(tmp, _fill(cwf.plan(tmp)))
            self.assertEqual(cwf.apply(tmp, path, commit=False), 0)
            posts = store.list_posts(tmp)
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0].title, "Title A")
            self.assertIn("the body survives.", posts[0].body)
            self.assertNotIn("# Title A", posts[0].body)

    def test_rerunning_does_not_mint_a_second_copy(self):
        """The help text says "rerun with --commit", and without the guard that
        rerun created every post twice -- caught only by `hq lint` reporting two
        chain heads per subject, one layer downstream."""
        with tempfile.TemporaryDirectory() as t:
            tmp = self._one_page(t)
            path = _write_plan(tmp, _fill(cwf.plan(tmp)))
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
            path = _write_plan(tmp, _fill(cwf.plan(tmp)))
            self.assertEqual(cwf.apply(tmp, path, commit=True), 0)
            wiki = tmp / ".hq" / "community" / "wiki"
            self.assertEqual(list(wiki.rglob("*.md")), [])

    def test_it_never_creates_a_wiki_directory(self):
        """r7's user decision is "Wiki 폴더 안만들게" — the tool reads that tree
        where it already exists and refuses when it does not, never mints one."""
        with tempfile.TemporaryDirectory() as t:
            tmp = _anchor(Path(t))
            with self.assertRaises(SystemExit):
                cwf.plan(tmp)
            self.assertFalse((tmp / ".hq" / "community" / "wiki").exists())


if __name__ == "__main__":
    unittest.main()

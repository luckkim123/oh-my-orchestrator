#!/usr/bin/env python3
"""Tests for the omo census hook (UserPromptSubmit injector + PreToolUse gate).

The tests that matter are the discriminating ones, and they are named here so a
future edit cannot quietly remove the property they pin:

  * a prompt merely *about* omo must not fire the census -- defect reports paste
    the word dozens of times, and a census on every one trains the operator to
    ignore it;
  * an `OMO ->` line written BEFORE the census was injected must not satisfy the
    gate, or one acknowledgement at the top of a long session covers every later
    turn;
  * `Bash` must stay ungated, because the session needs it to run the very checks
    the census names;
  * every instrument failure must fail OPEN.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "omo-census.py"

_spec = importlib.util.spec_from_file_location("omo_census", HOOK)
census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census)


def run_hook(payload: dict, census_dir: Path):
    env = os.environ.copy()
    env["OMO_CENSUS_DIR"] = str(census_dir)
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=30,
    )
    out = proc.stdout.strip()
    return proc.returncode, (json.loads(out) if out else None)


def transcript(path: Path, assistant_texts):
    path.write_text(
        "".join(json.dumps({"type": "assistant",
                            "message": {"content": [{"type": "text", "text": t}]}}) + "\n"
                for t in assistant_texts),
        encoding="utf-8")
    return path


class TestInvocationDetection(unittest.TestCase):
    def test_slash_forms_fire(self):
        for prompt in ("/omo fix this", "/oh-my-orchestrator:omo audit",
                       "line one\n/omo audit the repo", "  /omo indented"):
            self.assertTrue(census._INVOCATION_RE.search(prompt), prompt)

    def test_mid_sentence_mention_is_not_an_invocation(self):
        """codex's counterexample, and it is this session's own prompt: a defect
        report saying ``the user ran `/oh-my-orchestrator:omo` and it failed``
        armed the gate for a review that had nothing to do with an omo run. A
        typed slash command starts its line; a mention does not."""
        for prompt in ("the user ran `/oh-my-orchestrator:omo` and it failed",
                       "please run /omo now",
                       "see the note about /omo above"):
            self.assertIsNone(census._INVOCATION_RE.search(prompt), prompt)

    def test_quoted_and_bracketed_invocations_fire(self):
        r"""`(?:^|\s)` alone missed a backticked invocation (agy, 2026-09-01)."""
        for prompt in ("`/omo audit`", '"/omo audit"', "(/omo)", "[/omo audit]"):
            self.assertTrue(census._INVOCATION_RE.search(prompt), prompt)

    def test_paths_naming_this_tooling_do_not_fire(self):
        """`\b` matches before a hyphen or slash, so `/omo-init` armed the gate on
        a prompt that was only NAMING the tool (agy, 2026-09-01)."""
        for prompt in ("run /omo-init now", "cat /omo/rules.md",
                       "see /omo-census.py", "check /omo:status"):
            self.assertIsNone(census._INVOCATION_RE.search(prompt), prompt)

    def test_prose_about_omo_does_not_fire(self):
        """The false-positive guard. A defect report is not an invocation."""
        for prompt in ("omo has no binding layer",
                       "the omo skill was invoked on another machine",
                       "update oh-my-orchestrator/skills/omo/SKILL.md",
                       "domo arigato"):
            self.assertIsNone(census._INVOCATION_RE.search(prompt), prompt)


class TestBackendList(unittest.TestCase):
    def test_backend_list_matches_registry(self):
        """The census must not name a backend `--backend` would reject.

        The first version listed `antigravity` and `gemini`: the former is the
        LOADER vendor name (the CLI is `agy`) and the latter was replaced by agy
        in 0.20.0, so both would have reported MISSING forever on every machine.
        """
        import re as _re
        reg = (Path(__file__).resolve().parents[3] / "codeagent-wrapper" /
               "internal" / "backend" / "registry.go").read_text(encoding="utf-8")
        # Split on a `}` that starts a line, not the first `}` in the text --
        # every entry is `"codex":  CodexBackend{},` and the naive split stopped
        # inside the first value, finding exactly one backend and passing for
        # the wrong reason.
        body = reg.split("var registry = map[string]Backend{", 1)[1].split("\n}", 1)[0]
        names = set(_re.findall(r'"([a-z]+)":', body))
        self.assertEqual(set(census._BACKENDS), names)


class TestStoreStatus(unittest.TestCase):
    def test_no_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(census.store_status(Path(td)), "NO-ANCHOR")

    def test_unseeded_names_what_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".hq" / "runtime").mkdir(parents=True)
            got = census.store_status(Path(td))
            self.assertTrue(got.startswith("UNSEEDED("), got)
            self.assertIn("rules/", got)
            self.assertIn("HUB.md", got)

    def test_seeded(self):
        with tempfile.TemporaryDirectory() as td:
            c = Path(td) / ".hq" / "community"
            (c / "rules").mkdir(parents=True)
            (c / "rules" / "safety.md").write_text("x", encoding="utf-8")
            (c / "HUB.md").write_text("x", encoding="utf-8")
            self.assertEqual(census.store_status(Path(td)), "seeded")

    def test_unreadable_store_reports_rather_than_raising(self):
        """`omo-init --census-only` calls this directly, where an OSError is a
        traceback instead of a census (agy, 2026-09-01)."""
        import os as _os
        with tempfile.TemporaryDirectory() as td:
            c = Path(td) / ".hq" / "community"
            (c / "rules").mkdir(parents=True)
            _os.chmod(c / "rules", 0o000)
            try:
                got = census.store_status(Path(td))
            finally:
                _os.chmod(c / "rules", 0o755)
            self.assertTrue(got.startswith(("UNKNOWN(", "UNSEEDED(")), got)

    def test_empty_rules_dir_is_unseeded(self):
        """A directory is not a payload -- `mkdir rules` must not read as seeded."""
        with tempfile.TemporaryDirectory() as td:
            c = Path(td) / ".hq" / "community"
            (c / "rules").mkdir(parents=True)
            (c / "HUB.md").write_text("x", encoding="utf-8")
            self.assertIn("rules/", census.store_status(Path(td)))


class TestWrapperStatus(unittest.TestCase):
    def _patch(self, which, version_out):
        census.shutil.which = lambda n: which
        census.subprocess.run = lambda *a, **k: type("R", (), {"stdout": version_out})()

    def setUp(self):
        self._which, self._run = census.shutil.which, census.subprocess.run

    def tearDown(self):
        census.shutil.which, census.subprocess.run = self._which, self._run

    def test_missing(self):
        self._patch(None, "")
        self.assertEqual(census.wrapper_status("0.21.6"), "MISSING")

    def test_git_describe_output_is_parsed_not_compared_raw(self):
        """`v0.21.5-1-g7573f4e-dirty` is a real reading, not a hypothetical."""
        self._patch("/x/codeagent-wrapper", "codeagent-wrapper version v0.21.5-1-g7573f4e-dirty")
        self.assertEqual(census.wrapper_status("0.21.6"), "0.21.5!=0.21.6(STALE)")

    def test_current(self):
        self._patch("/x/codeagent-wrapper", "codeagent-wrapper version v0.21.6")
        self.assertEqual(census.wrapper_status("0.21.6"), "0.21.6")

    def test_unstamped_build_is_named_not_guessed(self):
        self._patch("/x/codeagent-wrapper", "codeagent-wrapper version dev")
        self.assertIn("unstamped", census.wrapper_status("0.21.6"))


class TestHqStatus(unittest.TestCase):
    """`hq` present is not `hq` installed — see hq_status's docstring."""

    def setUp(self):
        self._which, self._real = census.shutil.which, census.os.path.realpath
        self._home = census.Path.home

    def tearDown(self):
        census.shutil.which, census.os.path.realpath = self._which, self._real
        census.Path.home = self._home

    def _patch(self, path, home, real=None):
        census.shutil.which = lambda name: path if name == "hq" else None
        census.os.path.realpath = lambda p: real or p
        census.Path.home = staticmethod(lambda: Path(home))

    def test_missing_names_the_fix(self):
        with tempfile.TemporaryDirectory() as home:
            self._patch(None, home)
            self.assertIn("omo-init", census.hq_status())

    def test_a_plugin_cache_hit_is_not_installed(self):
        # The default state on any machine with the plugin enabled: Claude Code
        # puts the plugin's bin/ on the session PATH, and the next update
        # replaces that versioned directory.
        with tempfile.TemporaryDirectory() as home:
            self._patch(f"{home}/.claude/plugins/cache/heroacademia/"
                        "oh-my-orchestrator/0.22.0/bin/hq", home)
            self.assertIn("version-pinned", census.hq_status())

    def test_a_stable_path_entry_is_ok(self):
        with tempfile.TemporaryDirectory() as home:
            self._patch(f"{home}/.local/bin/hq", home)
            self.assertEqual(census.hq_status(), "ok")

    def test_a_symlink_into_the_cache_is_not_stable(self):
        """`/usr/local/bin/hq -> …/cache/0.22.0/bin/hq` looks installed and dies
        with the next update. The test is on the realpath (codex, 2026-09-01)."""
        with tempfile.TemporaryDirectory() as home:
            self._patch("/usr/local/bin/hq", home,
                        real=f"{home}/.claude/plugins/cache/heroacademia/"
                             "oh-my-orchestrator/0.22.0/bin/hq")
            self.assertIn("version-pinned", census.hq_status())

    def test_an_installed_shim_behind_the_cache_on_path_says_reorder(self):
        """Re-running omo-init cannot fix a PATH ORDER problem, so it must not
        be the advice given to someone who just ran it."""
        with tempfile.TemporaryDirectory() as home:
            shim = Path(home) / ".local" / "bin"
            shim.mkdir(parents=True)
            (shim / "hq").write_text("#!/bin/sh\n")
            self._patch(f"{home}/.claude/plugins/cache/heroacademia/"
                        "oh-my-orchestrator/0.22.0/bin/hq", home)
            status = census.hq_status()
            self.assertIn("shadowed", status)
            self.assertNotIn("run omo-init", status)


class TestPromptEvent(unittest.TestCase):
    def test_fires_and_writes_state(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            rc, out = run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                                "prompt": "/omo audit", "cwd": str(d)}, d)
            self.assertEqual(rc, 0)
            self.assertIn("OMO ->", out["hookSpecificOutput"]["additionalContext"])
            self.assertTrue((d / "census-s1.json").is_file())

    def test_silent_on_unrelated_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            rc, out = run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s2",
                                "prompt": "omo is broken, explain why", "cwd": str(d)}, d)
            self.assertEqual(rc, 0)
            self.assertIsNone(out)
            self.assertFalse((d / "census-s2.json").is_file())


class TestGate(unittest.TestCase):
    def _pending(self, d: Path, sid="s", offset=0):
        (d / f"census-{sid}.json").write_text(
            json.dumps({"line": "OMO -> wrapper:MISSING backends:claude-only store:UNSEEDED",
                        "offset": offset}), encoding="utf-8")

    def test_prose_quoting_the_prefix_does_not_satisfy_the_gate(self):
        """The passing mention the skill text forbids in so many words. A bare
        `OMO ->` search let `the required prefix is OMO ->` open the gate with
        nothing reported (codex, 2026-09-01)."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = transcript(d / "t.jsonl", [
                "I have not reported it yet; the required prefix is OMO ->."])
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_markdown_wrapped_census_line_counts(self):
        """The other half of the same fix: requiring an EXACT string match would
        wedge on a quote or a code span, which a model reporting to a user writes
        routinely. A wedge is the worse failure, so the line must merely *be* a
        census."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = transcript(d / "t.jsonl", [
                "Here is the state:\n\n> `OMO -> wrapper:0.22.0 backends:claude "
                "store:seeded`\n\nProceeding."])
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertIsNone(out)

    def test_non_object_row_does_not_wedge_the_rows_after_it(self):
        """A row that parses to a list made `rec.get` raise, and the outer handler
        then denied every retry forever (codex, 2026-09-01)."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = d / "t.jsonl"
            t.write_text("[]\n" + json.dumps(
                {"type": "assistant", "message": {"content": [
                    {"type": "text",
                     "text": "OMO -> wrapper:0.22.0 backends:claude store:seeded"}]}}) + "\n",
                encoding="utf-8")
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertIsNone(out)

    def test_denies_agent_without_acknowledgement(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = transcript(d / "t.jsonl", ["working on it"])
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("store:UNSEEDED", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allows_after_acknowledgement(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = transcript(d / "t.jsonl", ["OMO -> wrapper:MISSING backends:claude-only store:UNSEEDED"])
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertIsNone(out)
            self.assertTrue(json.loads((d / "census-s.json").read_text())["done"])

    def test_acknowledgement_before_the_census_does_not_count(self):
        """The property the byte offset exists for. Without it one line at the top
        of a session satisfies every later turn."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            t = transcript(d / "t.jsonl",
                           ["OMO -> wrapper:0.22.0 backends:claude store:seeded"])
            self._pending(d, offset=t.stat().st_size)
            with t.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "assistant",
                                     "message": {"content": [{"type": "text",
                                                              "text": "carrying on"}]}}) + "\n")
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_bash_is_not_gated(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = transcript(d / "t.jsonl", ["nothing"])
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Bash", "transcript_path": str(t)}, d)
            self.assertIsNone(out)

    def test_unreadable_transcript_fails_open(self):
        """The wedge. Returning "not acknowledged" for a transcript that cannot be
        read denies forever -- re-emitting the line cannot make the file appear
        (agy, 2026-09-01)."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            for tp in ("", str(d / "does-not-exist.jsonl")):
                _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                                   "tool_name": "Agent", "transcript_path": tp}, d)
                self.assertIsNone(out, tp)

    def test_unknown_offset_fails_open_rather_than_scanning_from_zero(self):
        """A null offset means the size could not be read at prompt time. Scanning
        from 0 instead would accept an EARLIER turn's acknowledgement -- the one
        property the offset exists for."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "census-s.json").write_text(json.dumps({"line": "OMO -> x", "offset": None}),
                                             encoding="utf-8")
            t = transcript(d / "t.jsonl", ["nothing here"])
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertIsNone(out)

    def test_no_census_state_allows(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "nope",
                               "tool_name": "Agent", "transcript_path": ""}, d)
            self.assertIsNone(out)

    def test_malformed_transcript_row_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = d / "t.jsonl"
            t.write_text("{not json\n" + json.dumps(
                {"type": "assistant",
                 "message": {"content": [{"type": "text", "text": "OMO -> wrapper:0.22.0 backends:claude store:seeded"}]}}) + "\n",
                encoding="utf-8")
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertIsNone(out)

    def test_truncated_transcript_scans_whole_file(self):
        """Offset past EOF means the log rotated. Scanning everything can only
        produce a false PASS, which is the safe direction for this gate."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d, offset=10**9)
            t = transcript(d / "t.jsonl", ["OMO -> wrapper:0.22.0 backends:claude store:seeded"])
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertIsNone(out)

    def test_string_content_is_read_too(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); self._pending(d)
            t = d / "t.jsonl"
            t.write_text(json.dumps({"type": "assistant",
                                     "message": {"content": "OMO -> wrapper:0.22.0 backends:claude store:seeded"}}) + "\n",
                         encoding="utf-8")
            _, out = run_hook({"hook_event_name": "PreToolUse", "session_id": "s",
                               "tool_name": "Agent", "transcript_path": str(t)}, d)
            self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()

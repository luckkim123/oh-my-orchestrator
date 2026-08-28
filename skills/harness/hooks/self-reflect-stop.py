#!/usr/bin/env python3
"""Self-reflection Stop hook -- injects a review pass once the task loop is done.

Fires only when both hold:
  1. harness-tasks.json exists (the harness was initialised at some point)
  2. .harness-active is gone (every task finished)

Where the harness was never started, this hook is a complete no-op.

Config:
  - REFLECT_MAX_ITERATIONS env var (default 5)
  - Set it to 0 to disable
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

# Add hooks directory to sys.path for _harness_common import
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _harness_common as hc
except ImportError:
    hc = None  # type: ignore[assignment]

DEFAULT_MAX_ITERATIONS = 5

# The loop's own prompt has always told the model that finishing is enough to end
# it. Until 2026-08-26 nothing read that answer back, so the only exit was the
# counter and every run paid all five iterations. A demand the model cannot
# discharge is the same defect the cost gate had.
DONE_SENTINEL = "REFLECT-DONE"


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _find_harness_root(payload: dict[str, Any]) -> Optional[Path]:
    """Find the directory holding harness-tasks.json. Its presence means the
    harness was used here at least once."""
    if hc is not None:
        return hc.find_harness_root(payload)

    # Fallback: inline discovery if _harness_common not available
    candidates: list[Path] = []
    state_root = os.environ.get("HARNESS_STATE_ROOT")
    if state_root:
        p = Path(state_root)
        if hc is not None and hc._has_marker(p):
            try:
                return p.resolve()
            except Exception:
                return p
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    cwd = payload.get("cwd") or os.getcwd()
    candidates.append(Path(cwd))
    seen: set[str] = set()
    for base in candidates:
        try:
            base = base.resolve()
        except Exception:
            continue
        if str(base) in seen:
            continue
        seen.add(str(base))
        for parent in [base, *list(base.parents)[:8]]:
            if hc is not None and hc._has_marker(parent):
                return parent
    return None


def _counter_path(session_id: str) -> Path:
    """One counter file per session."""
    return Path(tempfile.gettempdir()) / f"claude-reflect-{session_id}"


def _read_counter(session_id: str) -> int:
    p = _counter_path(session_id)
    try:
        return int(p.read_text("utf-8").strip().split("\n")[0])
    except Exception:
        return 0


def _write_counter(session_id: str, count: int) -> None:
    p = _counter_path(session_id)
    try:
        p.write_text(str(count), encoding="utf-8")
    except Exception:
        pass


def _extract_original_prompt(transcript_path: str, max_bytes: int = 100_000) -> str:
    """Pull the first user message out of the transcript JSONL as the request."""
    try:
        p = Path(transcript_path)
        if not p.is_file():
            return ""
        with p.open("r", encoding="utf-8") as f:
            # JSONL: parse line by line until the first user message
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue
                # Claude Code writes {"type": "user", "message": {"role": ..,
                # "content": ..}}. Reading entry["content"] finds nothing and the
                # function silently returns "" for every transcript, which is why
                # the reflect prompt shipped without the original request.
                message = entry.get("message")
                if not isinstance(message, dict):
                    message = {}
                role = message.get("role") or entry.get("role") or entry.get("type", "")
                if role == "user":
                    content = message.get("content", entry.get("content", ""))
                    if isinstance(content, list):
                        # content may be a list of blocks
                        texts = []
                        for block in content:
                            if isinstance(block, dict):
                                t = block.get("text", "")
                                if t:
                                    texts.append(t)
                            elif isinstance(block, str):
                                texts.append(block)
                        content = "\n".join(texts)
                    if isinstance(content, str) and content.strip():
                        # truncate an over-long request
                        if len(content) > 2000:
                            content = content[:2000] + "..."
                        return content.strip()
    except Exception:
        pass
    return ""


def main() -> int:
    payload = _read_payload()
    session_id = payload.get("session_id", "")
    if not session_id:
        return 0  # no session_id, allow

    # Gate: reflect only after the harness finished every task, which .harness-reflect
    # marks. That marker exists to avoid two failures:
    #   1. a leftover harness-tasks.json firing this on an unrelated session (false positive)
    #   2. harness-stop.py removing .harness-active, after which Claude Code skips the
    #      remaining hooks and the reflection never runs at all (false negative)
    root = _find_harness_root(payload)
    if root is None:
        return 0

    if not (root / ".harness-reflect").is_file():
        return 0

    # The model's way out. It is checked before the counter so that answering the
    # checklist honestly costs one iteration, not five.
    if DONE_SENTINEL in str(payload.get("last_assistant_message") or ""):
        try:
            (root / ".harness-reflect").unlink(missing_ok=True)
        except Exception:
            pass
        return 0

    # Read the iteration ceiling
    try:
        max_iter = int(os.environ.get("REFLECT_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS))
    except (ValueError, TypeError):
        max_iter = DEFAULT_MAX_ITERATIONS

    # Disabled
    if max_iter <= 0:
        return 0

    # Read the current count
    count = _read_counter(session_id)

    # Ceiling reached: clear the marker and allow the stop
    if count >= max_iter:
        try:
            (root / ".harness-reflect").unlink(missing_ok=True)
        except Exception:
            pass
        return 0

    # Advance the count
    _write_counter(session_id, count + 1)

    # Pull the original request
    transcript_path = payload.get("transcript_path", "")
    original_prompt = _extract_original_prompt(transcript_path)
    last_message = payload.get("last_assistant_message", "")
    if last_message and len(last_message) > 3000:
        last_message = last_message[:3000] + "..."

    # Build the reflection prompt
    parts = [
        f"[Self-Reflect] pass {count + 1}/{max_iter} -- review before going further:",
    ]

    if original_prompt:
        parts.append(f"\n\nThe original request:\n{original_prompt}")

    parts.append(
        "\n\nChecklist:"
        "\n1. Against the original request, confirm each requirement point by point."
        "\n2. Look for edge cases, error handling, or failure paths that were skipped."
        "\n3. Code quality: readability, performance, security -- anything worth fixing?"
        "\n4. Do the changes need tests or documentation they do not have?"
        "\n5. Final check: are the changes consistent with each other, and with the repo?"
        "\n\nFound something? Fix it and this checklist runs again."
        "\n**Nothing left? Summarise what was done and end that summary with the line "
        f"`{DONE_SENTINEL}` on its own.** That is what ends the loop -- without it this "
        f"prompt returns up to {max_iter} times, whatever you answer."
    )

    parts.append(
        "\n6. Knowledge mining (only if the run produced something reusable):"
        "\n   A candidate qualifies only with BOTH of these, and you state both:"
        "\n   - Evidence: the file, command, or log line that demonstrates it. Not a"
        " recollection of the session."
        "\n   - Confidence >= 0.6 that it holds beyond this one task. Below that it is"
        " an anecdote, and an anecdote promoted to a rule costs more than the gap it filled."
        f"\n   Where it lands: verified library behavior ->"
        f" {hc.knowledge_dir(root).relative_to(root)}/libraries/<name>.md (fixed section"
        f" order); a settled design question -> the {hc.hub_md(root).relative_to(root)}"
        f" decision table; research someone would otherwise redo ->"
        f" {hc.knowledge_dir(root).relative_to(root)}/research/."
        "\n   Nothing qualifying? Say so. An empty mining pass is a normal outcome and"
        " a fabricated one poisons the store."
    )

    reason = "\n".join(parts)

    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

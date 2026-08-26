#!/usr/bin/env python3
"""Self-reflection Stop hook — harness 任务循环完成后注入自省 prompt。

仅在以下条件同时满足时生效：
  1. harness-tasks.json 存在（harness 曾被初始化）
  2. .harness-active 不存在（harness 任务已全部完成）

当 harness 未曾启动时，本 hook 是完全的 no-op。

配置:
  - REFLECT_MAX_ITERATIONS 环境变量（默认 5）
  - 设为 0 可禁用
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
    """查找 harness-tasks.json 所在的目录。存在则说明 harness 曾被使用。"""
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
    """每个 session 独立计数文件。"""
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
    """从 transcript JSONL 中提取第一条用户消息作为原始 prompt。"""
    try:
        p = Path(transcript_path)
        if not p.is_file():
            return ""
        with p.open("r", encoding="utf-8") as f:
            # JSONL 格式，逐行解析找第一条 user message
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
                        # content 可能是 list of blocks
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
                        # 截断过长的 prompt
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
        return 0  # 无 session_id，放行

    # 守卫：仅当 harness 完成所有任务后（.harness-reflect 存在）才触发自省
    # 这避免了两个问题：
    #   1. 历史残留的 harness-tasks.json 导致误触发（false positive）
    #   2. harness-stop.py 移除 .harness-active 后 Claude Code 跳过后续 hook（false negative）
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

    # 读取最大迭代次数
    try:
        max_iter = int(os.environ.get("REFLECT_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS))
    except (ValueError, TypeError):
        max_iter = DEFAULT_MAX_ITERATIONS

    # 禁用
    if max_iter <= 0:
        return 0

    # 读取当前计数
    count = _read_counter(session_id)

    # 超过最大次数，清理 marker 并放行
    if count >= max_iter:
        try:
            (root / ".harness-reflect").unlink(missing_ok=True)
        except Exception:
            pass
        return 0

    # 递增计数
    _write_counter(session_id, count + 1)

    # 提取原始 prompt
    transcript_path = payload.get("transcript_path", "")
    original_prompt = _extract_original_prompt(transcript_path)
    last_message = payload.get("last_assistant_message", "")
    if last_message and len(last_message) > 3000:
        last_message = last_message[:3000] + "..."

    # 构建自省 prompt
    parts = [
        f"[Self-Reflect] 迭代 {count + 1}/{max_iter} — 请在继续之前进行自省检查：",
    ]

    if original_prompt:
        parts.append(f"\n📋 原始请求：\n{original_prompt}")

    parts.append(
        "\n🔍 自省清单："
        "\n1. 对照原始请求，逐项确认每个需求点是否已完整实现"
        "\n2. 检查是否有遗漏的边界情况、错误处理或异常场景"
        "\n3. 代码质量：是否有可以改进的地方（可读性、性能、安全性）"
        "\n4. 是否需要补充测试或文档"
        "\n5. 最终确认：所有改动是否一致且不互相冲突"
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
        "\n   Where it lands: verified library behavior ->"
        " .orchestration/knowledge/libraries/<name>.md (fixed section order);"
        " a settled design question -> the .orchestration/HUB.md decision table;"
        " research someone would otherwise redo -> .orchestration/knowledge/research/."
        "\n   Nothing qualifying? Say so. An empty mining pass is a normal outcome and"
        " a fabricated one poisons the store."
    )

    reason = "\n".join(parts)

    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

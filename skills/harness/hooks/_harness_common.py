"""Shared utilities for harness hooks.

Consolidates duplicated logic: payload reading, state root discovery,
JSON I/O, lock primitives, task eligibility, and ISO time helpers.

Ported from Codex harness hooks to Claude Code.

Also the hooks-side declaration point for the `.orchestration` root literal
(LEGACY_ROOT below), a sibling to hq/paths.py rather than an import of it --
see hq/paths.py's module docstring and test_paths_lint.py for why a hook does
not reach across into the hq/ package for this. Path resolution here is
anchor-gated (store-spec.md §7 stage 2), mirroring hq/store.py: a parseable
`.hq/.anchor` routes to `.hq/`, otherwise the legacy `.orchestration/` paths.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def utc_now() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def iso_z(dt: _dt.datetime) -> str:
    dt = dt.astimezone(_dt.timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def parse_iso(ts: Any) -> Optional[_dt.datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# Hook payload
# ---------------------------------------------------------------------------

def read_hook_payload() -> dict[str, Any]:
    """Read JSON payload from stdin (sent by Claude Code to command hooks)."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# State root discovery
# ---------------------------------------------------------------------------

HQ_ROOT = ".hq"
LEGACY_ROOT = ".orchestration"
HQ_BOARD_REL = f"{HQ_ROOT}/runtime/board.json"
HQ_ANCHOR_REL = f"{HQ_ROOT}/.anchor"
HQ_COMMUNITY_REL = f"{HQ_ROOT}/community"
BOARD_REL = f"{LEGACY_ROOT}/board.json"
LEGACY_STATE = "harness-tasks.json"

_HQ_ANCHOR_ID_RE = re.compile(r"^id:\s*(\S.*)$")

# Board file names a root, in preference order: the unified store's runtime
# board first (store-spec.md section 9.3 -- board.json is the (3)/(5) tie that
# (5) wins, so it lands in the ignored runtime layer), then the legacy board,
# then the pre-board state file a project that never migrated still carries.
# P6 added the first entry: the store cutover moved the board and the hooks
# would otherwise resolve only the path the migration had just vacated, which
# reads exactly like "no active campaign" -- a silent off, not an error.
ROOT_MARKERS = (HQ_BOARD_REL, BOARD_REL, LEGACY_STATE)


def _has_marker(base: Path) -> bool:
    return any((base / m).is_file() for m in ROOT_MARKERS)


def find_harness_root(payload: dict[str, Any]) -> Optional[Path]:
    """Locate the directory holding .hq/runtime/board.json, .orchestration/
    board.json, or harness-tasks.json -- root DISCOVERY checks all three
    ROOT_MARKERS regardless of anchor state (store-spec.md §6 requires an
    unmigrated project stay findable); only path RESOLUTION for a found root
    (board_path(), agent_memory_md(), hub_md(), etc.) is anchor-gated.

    Search order:
    1. HARNESS_STATE_ROOT env var
    2. CLAUDE_PROJECT_DIR env var (+ parents)
    3. payload["cwd"] / os.getcwd() (+ parents)
    """
    env_root = os.environ.get("HARNESS_STATE_ROOT")
    if env_root:
        p = Path(env_root)
        if _has_marker(p):
            try:
                return p.resolve()
            except Exception:
                return p

    candidates: list[Path] = []
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
            if _has_marker(parent):
                return parent
    return None


# ---------------------------------------------------------------------------
# Board and community resolvers -- anchor-gated (.hq/) with legacy fallback
# for an unanchored project (.orchestration/) (store-spec.md §7 stage 2)
# ---------------------------------------------------------------------------

def legacy_root(root: Path) -> Path:
    return root / LEGACY_ROOT


def _has_hq_anchor(root: Path) -> bool:
    """store-spec.md §7 stage 2 (fallback removal): a parseable `.hq/.anchor`
    is what switches a project's reads and writes to `.hq/` -- in both
    directions, unconditionally, with no existence check on the target path
    (an anchored project resolves to `.hq/` even when only a legacy file
    exists; an unanchored one resolves to the legacy path even when a `.hq/`
    file exists). An unparseable anchor is read as "no anchor" here -- it
    falls back to the legacy path rather than routing into a half-broken
    `.hq/` structure -- because the loud GATE_CORRUPT failure is a separate
    concern already surfaced by gate_corrupt_reason() below, at hook entry,
    before any resolver in this file is reached on the normal hook path.

    Reimplements hq/anchor.py's one-line parse_anchor() rule locally rather
    than importing it -- same reason HQ_ROOT/LEGACY_ROOT above are
    redeclared rather than imported, per this module's docstring: a
    cross-package import in every hook's hot path (this function is called
    on every board/agent-memory/HUB read) trades literal-drift risk for
    availability risk. Every sibling harness (omp/oms/omd/omx/omha) makes
    the identical call in its own *_paths.py module.
    """
    f = root / HQ_ANCHOR_REL
    if not f.is_file():
        return False
    try:
        raw = f.read_text(encoding="utf-8")
    except OSError:
        return False
    text = raw[:-1] if raw.endswith("\n") else raw
    non_empty = [line for line in text.split("\n") if line.strip() != ""]
    if len(non_empty) != 1:
        return False
    m = _HQ_ANCHOR_ID_RE.match(non_empty[0])
    return bool(m and m.group(1).strip())


def board_path(root: Path) -> Path:
    """The board this root actually carries -- anchor-gated (store-spec.md
    §7 stage 2), not existence-gated.

    A project with a parseable `.hq/.anchor` resolves to `.hq/runtime/
    board.json` only -- no fallback to the legacy path, even when a legacy
    board still exists on disk. A project without an anchor resolves to the
    legacy board, exactly as it always has, so a machine that never
    migrated keeps working.
    """
    if _has_hq_anchor(root):
        return root / HQ_BOARD_REL
    return legacy_root(root) / "board.json"


def observations_jsonl(root: Path) -> Path:
    """Sibling of the board, so it follows whichever board this root carries."""
    return board_path(root).parent / "observations.jsonl"


def agent_memory_md(root: Path, role: str) -> Path:
    if _has_hq_anchor(root):
        return root / HQ_COMMUNITY_REL / "agents" / f"{role}.md"
    return legacy_root(root) / "agents" / f"{role}.md"


def hub_md(root: Path) -> Path:
    if _has_hq_anchor(root):
        return root / HQ_COMMUNITY_REL / "HUB.md"
    return legacy_root(root) / "HUB.md"


def community_posts_dir(root: Path) -> Path:
    if _has_hq_anchor(root):
        return root / HQ_COMMUNITY_REL / "posts"
    return legacy_root(root) / "posts"


def knowledge_dir(root: Path) -> Path:
    """store-spec.md §9.3 (omo table): the layer moved to `.hq/community/
    knowledge/` in P7; full absorption into the post schema (§4) is a
    separate, deferred P6 item -- the directory still exists as its own
    thing under either root."""
    if _has_hq_anchor(root):
        return root / HQ_COMMUNITY_REL / "knowledge"
    return legacy_root(root) / "knowledge"


def state_path(root: Path) -> Path:
    """The file hooks read: the board when it exists, else the legacy state."""
    bp = board_path(root)
    return bp if bp.is_file() else (root / LEGACY_STATE)


def load_state(root: Path) -> dict[str, Any]:
    """Load whichever state file this root carries. Raises on malformed JSON."""
    return load_json(state_path(root))


def is_harness_active(root: Path) -> bool:
    """True when hooks are live for this root.

    The gate is `board.json.status == "active"`. It is a status bit rather than a
    marker file because a closed campaign's board stays on disk -- posts are kept
    by convention -- so presence cannot mean active.

    A root that has not migrated still gates on the .harness-active marker.
    """
    bp = board_path(root)
    if bp.is_file():
        try:
            return str(load_json(bp).get("status") or "").strip() == "active"
        except Exception:
            # A corrupt board is not an active one. The stop hook reports the
            # parse failure separately; here, fail closed so a broken file does
            # not leave every hook firing.
            return False
    return (root / ".harness-active").is_file()


def gate_corrupt_reason(root: Path) -> Optional[str]:
    """store-spec.md §6 row 4: a corrupt `.hq/.anchor` (duplicate anchor id,
    unparseable `.anchor`, or a board that exists and will not parse --
    anchored or, since the 2026-08-31 B-r1 widening, unanchored legacy)
    must fail loud, not be read as an absent store. `is_harness_active()`
    above reads a corrupt board as merely inactive -- correct for gating
    "should this hook do work", but it is also the exact silent-failure this
    function exists to surface separately, at hook entry, before that gate.

    hq.anchor.gate_state() is the single implementation of the 4-state table
    (off/legacy/normal/corrupt); this only translates its GATE_CORRUPT case
    into the one-line reason a hook prints. Every other state (off, legacy,
    normal) returns None here -- unchanged from what is_harness_active()
    already does for those three.

    Never raises. These hooks fire on every Stop/SessionStart/etc. in every
    repo on this machine, harness or not; a traceback here -- a missing hq
    package, a stale sys.path, anything -- must degrade to "not corrupt"
    (today's behavior) rather than break every session on the machine. That
    degradation is the load-bearing property, not a detail: the failure mode
    being fixed (silent corruption) is strictly better than a hook that can no
    longer run at all.
    """
    try:
        harness_dir = str(Path(__file__).resolve().parent.parent)  # skills/harness/
        if harness_dir not in sys.path:
            sys.path.insert(0, harness_dir)
        from hq import anchor as hq_anchor
        state, reason = hq_anchor.gate_state(root)
        return reason if state == hq_anchor.GATE_CORRUPT else None
    except Exception:
        return None


def board_workers(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("workers")
    return [w for w in raw if isinstance(w, dict)] if isinstance(raw, list) else []


def find_worker(state: dict[str, Any], role: str) -> Optional[dict[str, Any]]:
    """Look up a worker row by role name. Roles are unique on the board."""
    role = str(role or "").strip()
    if not role:
        return None
    for w in board_workers(state):
        if str(w.get("role") or "").strip() == role:
            return w
    return None


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return data


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: backup -> tmp -> rename."""
    bak = path.with_name(f"{path.name}.bak")
    tmp = path.with_name(f"{path.name}.tmp")
    shutil.copy2(path, bak)
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def tail_text(path: Path, max_bytes: int = 200_000) -> str:
    """Read the last max_bytes of a text file."""
    with path.open("rb") as f:
        try:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes), os.SEEK_SET)
        except Exception:
            f.seek(0, os.SEEK_SET)
        chunk = f.read()
    return chunk.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Lock primitives (mkdir-based, POSIX-portable)
# ---------------------------------------------------------------------------

def lockdir_for_root(root: Path) -> Path:
    # Root-local so TMPDIR drift between sessions cannot split the lock;
    # the root is writable by construction (the board lives in it).
    return root / ".harness.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _read_pid(lockdir: Path) -> Optional[int]:
    try:
        raw = (lockdir / "pid").read_text("utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None


def acquire_lock(lockdir: Path, timeout_seconds: float = 5.0) -> None:
    deadline = time.time() + timeout_seconds
    missing_pid_since: Optional[float] = None
    while True:
        try:
            lockdir.mkdir(mode=0o700)
            (lockdir / "pid").write_text(str(os.getpid()), encoding="utf-8")
            return
        except FileExistsError:
            pid = _read_pid(lockdir)
            if pid is None:
                if missing_pid_since is None:
                    missing_pid_since = time.time()
                if time.time() - missing_pid_since < 1.0:
                    if time.time() >= deadline:
                        raise TimeoutError("lock busy (pid missing)")
                    time.sleep(0.05)
                    continue
            else:
                missing_pid_since = None
                if _pid_alive(pid):
                    if time.time() >= deadline:
                        raise TimeoutError(f"lock busy (pid={pid})")
                    time.sleep(0.05)
                    continue

            stale = lockdir.with_name(
                f"{lockdir.name}.stale.{os.getpid()}.{int(time.time())}"
            )
            try:
                lockdir.rename(stale)
            except Exception:
                if time.time() >= deadline:
                    raise TimeoutError("lock contention")
                time.sleep(0.05)
                continue
            shutil.rmtree(stale, ignore_errors=True)
            missing_pid_since = None
            continue


def release_lock(lockdir: Path) -> None:
    shutil.rmtree(lockdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Task helpers
# ---------------------------------------------------------------------------

def priority_rank(v: Any) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(str(v or ""), 9)


def task_attempts(t: dict[str, Any]) -> int:
    try:
        return int(t.get("attempts") or 0)
    except Exception:
        return 0


def task_max_attempts(t: dict[str, Any]) -> int:
    try:
        v = t.get("max_attempts")
        return int(v) if v is not None else 3
    except Exception:
        return 3


def logged_failures(progress_tail: str) -> dict[str, int]:
    """Count ERROR lines per task id in a harness-progress.txt tail.

    `attempts` is written by whoever executed the task, so a session that
    forgets to bump it silently earns unlimited retries. The progress log is
    the file's own record of what happened; taking the larger of the two
    (effective_attempts) makes the failure count a fact, not a self-report.
    """
    counts: dict[str, int] = {}
    for line in progress_tail.splitlines():
        if " ERROR [" not in line:
            continue
        _, _, rest = line.partition(" ERROR [")
        tid, sep, _ = rest.partition("]")
        if sep and tid:
            counts[tid.strip()] = counts.get(tid.strip(), 0) + 1
    return counts


def progress_logged_failures(root: Path) -> dict[str, int]:
    """logged_failures() over this root's progress log; {} when unreadable."""
    p = root / "harness-progress.txt"
    try:
        return logged_failures(tail_text(p)) if p.is_file() else {}
    except Exception:
        return {}


def effective_attempts(t: dict[str, Any], logged: dict[str, int]) -> int:
    return max(task_attempts(t), logged.get(str(t.get("id") or ""), 0))


def deps_completed(t: dict[str, Any], completed_ids: set[str]) -> bool:
    deps = t.get("depends_on") or []
    if not isinstance(deps, list):
        return False
    return all(str(d) in completed_ids for d in deps)


def parse_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract validated task list from state dict."""
    tasks_raw = state.get("tasks") or []
    if not isinstance(tasks_raw, list):
        raise ValueError("tasks must be a list")
    return [t for t in tasks_raw if isinstance(t, dict)]


def completed_ids(tasks: list[dict[str, Any]]) -> set[str]:
    return {
        str(t.get("id", ""))
        for t in tasks
        if str(t.get("status", "")) == "completed"
    }


def eligible_tasks(
    tasks: list[dict[str, Any]],
    logged: Optional[dict[str, int]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (pending_eligible, retryable) sorted by priority then id.

    `logged` is the per-task ERROR-line count from the progress log (see
    progress_logged_failures below). Every reader that decides whether a
    failed task may run again must pass it: retryability is judged on
    effective_attempts -- the same count the Stop hook enforces -- so a
    session that never bumped `attempts` cannot earn extra retries from a
    reader that only trusted the self-report.
    """
    done = completed_ids(tasks)
    logged = logged or {}

    pending = [
        t for t in tasks
        if str(t.get("status", "")) == "pending" and deps_completed(t, done)
    ]
    retry = [
        t for t in tasks
        if str(t.get("status", "")) == "failed"
        and effective_attempts(t, logged) < task_max_attempts(t)
        and deps_completed(t, done)
    ]

    def key(t: dict[str, Any]) -> tuple[int, str]:
        return (priority_rank(t.get("priority")), str(t.get("id", "")))

    pending.sort(key=key)
    retry.sort(key=key)
    return pending, retry


def pick_next(
    pending: list[dict[str, Any]], retry: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    return pending[0] if pending else (retry[0] if retry else None)


def status_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tasks:
        s = str(t.get("status") or "pending")
        counts[s] = counts.get(s, 0) + 1
    return counts


def reap_stale_leases(
    tasks: list[dict[str, Any]], now: _dt.datetime
) -> bool:
    """Reset in_progress tasks with expired leases to failed. Returns True if any changed."""
    changed = False
    for t in tasks:
        if str(t.get("status", "")) != "in_progress":
            continue
        exp = parse_iso(t.get("lease_expires_at"))
        if exp is None or exp > now:
            continue

        t["attempts"] = task_attempts(t) + 1
        err = f"[SESSION_TIMEOUT] Lease expired (claimed_by={t.get('claimed_by')})"
        log = t.get("error_log")
        if isinstance(log, list):
            log.append(err)
        else:
            t["error_log"] = [err]

        t["status"] = "failed"
        t.pop("claimed_by", None)
        t.pop("lease_expires_at", None)
        t.pop("claimed_at", None)
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Session config helpers
# ---------------------------------------------------------------------------

def get_session_config(state: dict[str, Any]) -> dict[str, Any]:
    cfg = state.get("session_config") or {}
    return cfg if isinstance(cfg, dict) else {}


def is_concurrent(cfg: dict[str, Any]) -> bool:
    return str(cfg.get("concurrency_mode") or "exclusive") == "concurrent"


# ---------------------------------------------------------------------------
# Hook output helpers
# ---------------------------------------------------------------------------

def emit_json(data: dict[str, Any]) -> None:
    """Print arbitrary JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False))

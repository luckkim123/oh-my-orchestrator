#!/usr/bin/env python3
"""Seed ~/.codeagent/models.json from templates/models.json.example.

The wrapper resolves --agent <role> from ~/.codeagent/models.json and fails
loud when it is missing. This is the supported way to create it: copy the
repo template when absent, merge only the missing role entries when present.
Existing entries are never overwritten.
"""

import json
import os
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "models.json.example"
TARGET = Path.home() / ".codeagent" / "models.json"


def _write_atomic(path: Path, text: str) -> None:
    """A crash or full disk mid-write must not destroy an existing config."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    if not TARGET.exists():
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(TARGET, json.dumps(template, indent=2, ensure_ascii=False) + "\n")
        print(f"created {TARGET} with {len(template.get('agents', {}))} role(s)")
        return 0

    models = json.loads(TARGET.read_text(encoding="utf-8"))
    added = []
    for key in ("default_backend", "default_model", "backends"):
        if key not in models and key in template:
            models[key] = template[key]
            added.append(key)
    agents = models.setdefault("agents", {})
    for name, cfg in template.get("agents", {}).items():
        if name not in agents:
            agents[name] = cfg
            added.append(f"agents.{name}")

    if not added:
        print(f"{TARGET} already has every template entry; nothing to do")
        return 0

    _write_atomic(TARGET, json.dumps(models, indent=2, ensure_ascii=False) + "\n")
    print(f"updated {TARGET}: added {', '.join(added)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

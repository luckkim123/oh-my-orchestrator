"""hq — community verbs for the .hq/ unified state store (store-spec.md).

Resolution is anchor-gated (store-spec.md §7 stage 2): a parseable
`.hq/.anchor` routes to `.hq/community/`, otherwise the legacy
`.orchestration/` layout. Ships inside the plugin (skills/harness/hq/), not
as a pip package — see hq-contract.md "Deployment form".
"""
from __future__ import annotations

"""hq — community verbs for the .hq/ unified state store (store-spec.md).

P1 targets the current `.orchestration/` layout via community_dir()'s
fallback (D-P1-1 in hq-contract.md); nothing here assumes `.hq/community/`
exists yet. Ships inside the plugin (skills/harness/hq/), not as a pip
package — see hq-contract.md "Deployment form".
"""
from __future__ import annotations

__version__ = "0.1.0"

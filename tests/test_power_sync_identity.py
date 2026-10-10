"""Contract for the restored upstream-compatible PowerSync HA identity."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = ROOT / "custom_components" / "power_sync"
PRIVATE_UPDATER_POLICY = ROOT / "docs/private-fork/upstream-update-policy.md"


def test_private_repo_keeps_upstream_ha_domain():
    """The private fork retains its repository identity but restores HA identity."""
    assert COMPONENT_ROOT.is_dir()

    manifest = json.loads((COMPONENT_ROOT / "manifest.json").read_text())
    const_source = (COMPONENT_ROOT / "const.py").read_text()
    init_source = (COMPONENT_ROOT / "__init__.py").read_text()
    private_updater_policy = PRIVATE_UPDATER_POLICY.read_text()

    assert manifest["domain"] == "power_sync"
    assert manifest["name"] == "PowerSync"
    assert 'DOMAIN = "power_sync"' in const_source
    assert 'url = "/api/power_sync/ev/vehicles"' in init_source
    assert "nirnachmani/powersync-nir" in private_updater_policy

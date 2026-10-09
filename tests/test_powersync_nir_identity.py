"""Contract for the private PowerSync Nir integration identity."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = ROOT / "custom_components" / "powersync_nir"


def test_private_integration_uses_distinct_hass_domain_and_visible_name():
    """PowerSync Nir can coexist with upstream PowerSync in one HA instance."""
    manifest = json.loads((COMPONENT_ROOT / "manifest.json").read_text())

    assert manifest["domain"] == "powersync_nir"
    assert manifest["name"] == "PowerSync Nir"


def test_private_integration_preserves_android_http_route_namespace():
    """The closed-source Android app still calls its established API routes."""
    init_source = (COMPONENT_ROOT / "__init__.py").read_text()

    assert 'url = "/api/power_sync/ev/vehicles"' in init_source
    assert 'url = "/api/power_sync/ev/vehicle_config"' in init_source

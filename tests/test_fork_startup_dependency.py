"""Unrelated Tesla Fleet setup must not block the Sigenergy fork."""
import json
from pathlib import Path


def test_tesla_fleet_is_not_a_startup_dependency():
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'custom_components/power_sync/manifest.json').read_text())
    assert 'tesla_fleet' not in manifest.get('dependencies', [])
    assert 'tesla_fleet' not in manifest.get('after_dependencies', [])

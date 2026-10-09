"""Static Android-app HTTP route contract for PowerSync Nir.

The released Android binary hard-codes the PowerSync HTTP namespace.  This
contract freezes only strings observed in that binary; dynamic payload fixtures
are added separately when captured from the user's HA instance.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/contracts/android_app/fixtures/android-1.0.7-336-static-routes.json"
SOURCES = (
    ROOT / "custom_components/powersync_nir/__init__.py",
    ROOT / "custom_components/powersync_nir/powerwall_local/views.py",
)


def test_installed_android_static_routes_remain_registered_by_the_fork():
    """Every app route observed in build 336 remains available unchanged."""
    contract = json.loads(FIXTURE.read_text())
    registered_routes = set()
    for source in SOURCES:
        registered_routes.update(
            re.findall(r'url\s*=\s*"(/api/power_sync/[^" ]+)"', source.read_text())
        )

    assert contract["app"] == {"package": "com.powersync.mobile", "version": "1.0.7", "build": 336}
    assert set(contract["routes"]) <= registered_routes


def test_vehicle_list_contract_preserves_app_consumed_fields():
    """The generic logical-profile implementation cannot remove app fields."""
    contract = json.loads(FIXTURE.read_text())

    assert contract["vehicle_list"]["route"] == "/api/power_sync/ev/vehicles"
    assert contract["vehicle_list"]["fields"] == [
        "id", "vehicle_id", "vin", "display_name", "model", "battery_level",
        "charging_state", "charge_limit_soc", "charger_power", "is_online",
        "is_plugged_in", "data_updated_at",
    ]


def test_capture_script_redacts_sensitive_values_without_changing_json_shape(tmp_path):
    """A later physical capture can safely be committed as a shape fixture."""
    raw = tmp_path / "raw.json"
    output = tmp_path / "sanitised.json"
    raw.write_text(json.dumps({
        "access_token": "secret", "url": "http://192.168.1.99:8123/api",
        "nested": {"vin": "ABC123", "enabled": True, "count": 2},
    }))

    subprocess.run(
        [sys.executable, "scripts/private-fork/capture_android_contract.py", str(raw), str(output)],
        cwd=ROOT,
        check=True,
    )

    assert json.loads(output.read_text()) == {
        "access_token": "[REDACTED]", "url": "[REDACTED]",
        "nested": {"vin": "[REDACTED]", "enabled": True, "count": 2},
    }

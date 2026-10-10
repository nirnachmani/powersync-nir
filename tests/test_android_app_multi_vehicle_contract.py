"""Released Android app multi-logical-vehicle compatibility contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/contracts/android_app/fixtures/android-1.0.7-336-two-logical-vehicles.json"
SOURCE = ROOT / "custom_components/power_sync/__init__.py"


def test_two_anonymous_logical_profiles_fit_the_released_app_vehicle_contract():
    """The app model does not require Tesla identity data for two records."""
    contract = json.loads(FIXTURE.read_text())
    vehicles = contract["vehicles"]

    assert [vehicle["id"] for vehicle in vehicles] == ["ev_profile_a", "ev_profile_b"]
    assert [vehicle["vehicle_id"] for vehicle in vehicles] == ["ev_profile_a", "ev_profile_b"]
    assert [vehicle["display_name"] for vehicle in vehicles] == ["Profile A", "Profile B"]
    assert all(vehicle["vin"] is None for vehicle in vehicles)
    assert all(vehicle["is_online"] is True for vehicle in vehicles)
    assert all(vehicle["is_plugged_in"] is False for vehicle in vehicles)


def test_selected_logical_profile_keeps_existing_app_routes_and_shared_policy_shapes():
    """Per-profile IDs remain separate from global charger/site policies."""
    contract = json.loads(FIXTURE.read_text())
    source = SOURCE.read_text()

    assert contract["vehicle_config_write"] == {
        "route": "/api/power_sync/ev/vehicle_config",
        "key": "vehicle_id",
    }
    assert contract["command"] == {
        "route": "/api/power_sync/ev/vehicles/{vehicle_id}/command",
        "selected_id_in_path": True,
    }
    assert contract["global_policy_routes"] == [
        "/api/power_sync/ev/solar_surplus_config",
        "/api/power_sync/ev/price_level_charging/settings",
        "/api/power_sync/ev/scheduled_charging/settings",
    ]
    for route in [contract["vehicle_config_write"]["route"], contract["command"]["route"], *contract["global_policy_routes"]]:
        assert f'url = "{route}"' in source

"""Red specification for one Generic Charger shared by two logical EV profiles."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / "custom_components/powersync_nir/automations/actions.py"
PLANNER = ROOT / "custom_components/powersync_nir/automations/ev_charging_planner.py"

GENERIC_SHARED_LOADPOINT = {
    "binding_id": "generic_home",
    "backend": "generic",
    "connected_vehicle_entity": "sensor.connected_vehicle",
    "control": {
        "switch": "switch.generic_ev_charge_control",
        "amps": "number.generic_ev_charge_amps",
    },
    "telemetry": {
        "status": "sensor.generic_ev_status",
        "power": "sensor.generic_ev_power",
    },
    "profiles": ("ev_profile_a", "ev_profile_b"),
}


def test_two_profiles_require_one_explicit_physical_generic_loadpoint_binding():
    """Current generic_ev pseudo-ID cannot distinguish two connected profiles."""
    source = ACTIONS.read_text()

    assert "SharedLoadpointBinding" in source, (
        "missing explicit shared physical loadpoint binding for logical EV profiles"
    )


def test_generic_start_stop_and_current_commands_require_shared_loadpoint_guard():
    """No profile-local command may reach the shared Generic Charger directly."""
    source = ACTIONS.read_text() + PLANNER.read_text()

    assert "resolve_shared_loadpoint_command" in source, (
        "missing one shared-loadpoint command guard for Generic Charger writes"
    )


def test_unknown_connected_vehicle_state_cannot_start_or_change_shared_charger():
    """Unknown/unavailable/unmapped profile selection fails closed for starts."""
    source = PLANNER.read_text()

    assert "connected_vehicle_entity" in source and "unmapped" in source, (
        "missing fail-closed connected-profile resolution before Generic commands"
    )

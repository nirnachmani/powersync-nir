"""Red specification for shared Generic-Charger external-session reconciliation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECONCILER = ROOT / "custom_components/powersync_nir/automations/external_session_reconciler.py"
PLANNER = ROOT / "custom_components/powersync_nir/automations/ev_charging_planner.py"


def test_fresh_unowned_generic_power_requires_external_session_observation():
    """Positive charger power without a matching command is an external session."""
    assert RECONCILER.exists(), (
        "missing external-session reconciler for fresh Generic Charger observations"
    )


def test_stale_or_missing_generic_power_cannot_establish_or_confirm_a_session():
    """Telemetry freshness is mandatory for a session and for stop readback."""
    source = RECONCILER.read_text() if RECONCILER.exists() else ""

    assert "fresh_power" in source and "indeterminate" in source, (
        "missing stale-telemetry and indeterminate-stop protection"
    )


def test_override_stops_unplanned_external_generic_session_once_and_waits_for_readback():
    """Unknown connected profile is unplanned under override, but not under yield."""
    source = PLANNER.read_text()

    assert "reconcile_shared_external_session" in source, (
        "missing single reconciled external-session result for EV mode decisions"
    )

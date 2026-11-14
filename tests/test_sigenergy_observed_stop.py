"""EVAC telemetry may settle only an unshared, proven provisional stop."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_ev_ownership_runtime import _Entry, _Hass, ev_ownership


def setup_stop():
    hass, entry = _Hass(), _Entry()
    now = datetime.now(timezone.utc)
    command = ev_ownership.record_ev_command(hass, entry, "sigenergy_charger", command="stop", success=True)
    command["at"] = (now - timedelta(seconds=5)).isoformat()
    ev_ownership.ensure_external_ev_ownership(hass, entry, "sigenergy_charger", observed_at=now - timedelta(seconds=4))
    lease = ev_ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1]
    assert lease and lease["stop_settling"]
    return hass, entry, now, lease


def state(**overrides):
    values = dict(charger_type="evac", status="b1", power_kw=0.0, is_charging=False, is_discharging=False)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fresh_unshared_evac_stop_releases_only_provisional_owner():
    hass, entry, now, _ = setup_stop()
    ev_ownership.observe_sigenergy_ev_stop(hass, entry, state(), observed_at=now)
    assert ev_ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is None


@pytest.mark.parametrize("change", [
    {"status": None}, {"status": "c2"}, {"charger_type": "evdc"}, {"power_kw": None},
    {"power_kw": float("nan")}, {"power_kw": -0.01}, {"power_kw": 0.1},
    {"power_kw": False}, {"is_charging": None}, {"is_discharging": None},
    {"is_charging": True}, {"is_discharging": True},
])
def test_incomplete_active_and_invalid_evac_reads_do_not_settle(change):
    hass, entry, now, lease = setup_stop()
    ev_ownership.observe_sigenergy_ev_stop(hass, entry, state(**change), observed_at=now)
    assert ev_ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is lease


@pytest.mark.parametrize("delta", [-6, -61, 30])
def test_old_pre_command_and_future_reads_do_not_settle(delta):
    hass, entry, now, lease = setup_stop()
    ev_ownership.observe_sigenergy_ev_stop(hass, entry, state(), observed_at=now + timedelta(seconds=delta))
    assert ev_ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is lease


def test_external_owner_and_missing_stop_time_are_not_released():
    for mode in ("external", "missing-time"):
        hass, entry, now, lease = setup_stop()
        lease.pop("stop_settling" if mode == "external" else "stop_command_at")
        ev_ownership.observe_sigenergy_ev_stop(hass, entry, state(), observed_at=now)
        assert ev_ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is lease


def test_collector_routes_direct_sigenergy_read_to_stop_observer():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / "custom_components/power_sync/__init__.py").read_text())
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and ast.unparse(n.test) == "sigenergy_state is not None")
    hass, entry, now, lease = setup_stop()
    namespace = dict(__package__="power_sync", hass=hass, entry=entry, sigenergy_state=state(),
                     entry_data=hass.data["power_sync"][entry.entry_id], observed_at=now,
                     observations=[], EvLoadObservation=lambda **kw: kw,
                     EvMeasurementKind=SimpleNamespace(INTEGRATED_CHARGER="integrated"))
    exec(compile(ast.Module(body=[branch], type_ignores=[]), "collector", "exec"), namespace)
    assert ev_ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is None
    assert len(namespace["observations"]) == 1


@pytest.mark.parametrize("options", [
    {"shared_loadpoint_connected_vehicle_entity": "sensor.selected"},
    {"shared_loadpoint_connected_vehicle_entity": "sensor.selected", "shared_loadpoint_profile_a_name": "A",
     "shared_loadpoint_profile_a_state": "a", "shared_loadpoint_profile_b_name": "B",
     "shared_loadpoint_profile_b_state": "b", "sigenergy_charger_enabled": True,
     "sigenergy_charger_type": "evac"},
])
def test_shared_or_incomplete_binding_keeps_identity_bound_lease(options):
    hass, entry, now, lease = setup_stop()
    entry.options = options
    ev_ownership.observe_sigenergy_ev_stop(hass, entry, state(), observed_at=now)
    assert ev_ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is lease

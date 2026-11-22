"""Observation-driven shared-session promotion uses the existing read cycle."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_external_session_reconciler import module


@pytest.fixture
def setup_cycle(monkeypatch):
    now = datetime.now(timezone.utc)
    session = SimpleNamespace(id="session-a", logical_vehicle_id="car-a", loadpoint_id="generic_ev", start_time=(now - timedelta(seconds=5)).isoformat())
    manager = SimpleNamespace(active_sessions={"generic_ev": session}, promote_pending_session=AsyncMock(return_value=True))
    store = SimpleNamespace(_data={"vehicle_charging_configs": []}, async_save=AsyncMock())
    entry = SimpleNamespace(entry_id="entry", data={"generic_charger_power_entity": "sensor.ev"}, options={})
    sensor = SimpleNamespace(state="20", attributes={"unit_of_measurement": "W"}, last_reported=now)
    selected = ["car-a"]
    backend = ["generic_ev"]
    data = {"automation_store": store, "session_manager": manager,
            "_shared_stop_fences": {"generic_ev": {}, "sigenergy_charger": {}}}
    hass = SimpleNamespace(data={"power_sync": {"entry": data}}, states=SimpleNamespace(get=lambda _: sensor),
                           services=SimpleNamespace(async_call=AsyncMock()))
    shared = SimpleNamespace(binding_for_entry=lambda _: True, resolve_active_shared_profile=lambda *_: selected[0], canonical_shared_loadpoint_id=lambda *_: backend[0])
    import sys
    monkeypatch.setattr(module, "__package__", "custom_components.power_sync.automations")
    monkeypatch.setitem(sys.modules, "custom_components.power_sync.automations.shared_loadpoint", shared)
    monkeypatch.setitem(sys.modules, "custom_components.power_sync.automations.ev_ownership", SimpleNamespace(get_ev_last_commands=lambda *_: {}))
    return SimpleNamespace(now=now, session=session, manager=manager, hass=hass, entry=entry, sensor=sensor, selected=selected, backend=backend)


def test_generic_fresh_low_positive_power_promotes_exact_session(setup_cycle):
    c = setup_cycle
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(c.hass, c.entry, now=c.now))
    call = c.manager.promote_pending_session.await_args
    assert call.args == ("generic_ev", "car-a", "session-a")
    assert call.kwargs["still_selected"]()
    c.hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("value,unit,age", [("0", "W", 0), ("20", "MW", 0), ("20", "W", 91), ("nan", "W", 0), ("-1", "W", 0)])
def test_generic_invalid_or_idle_does_not_promote(setup_cycle, value, unit, age):
    c = setup_cycle
    c.sensor.state = value
    c.sensor.attributes["unit_of_measurement"] = unit
    c.sensor.last_reported = c.now - timedelta(seconds=age)
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(c.hass, c.entry, now=c.now))
    c.manager.promote_pending_session.assert_not_awaited()
    c.hass.services.async_call.assert_not_awaited()


def test_generic_previous_session_power_does_not_promote(setup_cycle):
    c = setup_cycle
    c.sensor.last_reported = c.now - timedelta(seconds=6)
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(c.hass, c.entry, now=c.now))
    c.manager.promote_pending_session.assert_not_awaited()


def test_generic_attribute_update_does_not_promote(setup_cycle):
    c = setup_cycle
    c.sensor.last_reported = None
    c.sensor.last_updated = c.now
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(c.hass, c.entry, now=c.now))
    c.manager.promote_pending_session.assert_not_awaited()


def prepare_evac(c):
    c.backend[0] = "sigenergy_charger"
    c.session.loadpoint_id = "sigenergy_charger"
    c.manager.active_sessions = {"sigenergy_charger": c.session}


@pytest.mark.parametrize("change", ["session", "selector"])
def test_evac_observation_does_not_promote_after_identity_changes(setup_cycle, change):
    c = setup_cycle
    prepare_evac(c)
    async def read():
        if change == "session":
            c.manager.active_sessions = {"sigenergy_charger": SimpleNamespace(id="session-b", logical_vehicle_id="car-a", loadpoint_id="sigenergy_charger")}
        else:
            c.selected[0] = "car-b"
        return SimpleNamespace(charger_type="evac", raw_state=4, is_charging=True, power_kw=1.0)
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(c.hass, c.entry, now=c.now, read_evac_state=read))
    c.manager.promote_pending_session.assert_not_awaited()
    c.hass.services.async_call.assert_not_awaited()


def test_evac_charging_state_promotes(setup_cycle):
    c = setup_cycle
    prepare_evac(c)
    async def read():
        return SimpleNamespace(charger_type="evac", raw_state=4, is_charging=True, power_kw=0.0)
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(c.hass, c.entry, now=c.now, read_evac_state=read))
    call = c.manager.promote_pending_session.await_args
    assert call.args == ("sigenergy_charger", "car-a", "session-a")
    assert call.kwargs["still_selected"]()
    c.hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("state", [None, SimpleNamespace(charger_type="evac", is_charging=True),
    SimpleNamespace(charger_type="evac", raw_state=4, is_charging=True, power_kw=None),
    SimpleNamespace(charger_type="evac", raw_state=6, is_charging=True, power_kw=1),
    SimpleNamespace(charger_type="evac", raw_state=4, is_charging=True, power_kw=float("nan"))])
def test_evac_incomplete_or_invalid_state_does_not_promote(setup_cycle, state):
    c = setup_cycle
    prepare_evac(c)
    async def read():
        return state
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(c.hass, c.entry, now=c.now, read_evac_state=read))
    c.manager.promote_pending_session.assert_not_awaited()
    c.hass.services.async_call.assert_not_awaited()

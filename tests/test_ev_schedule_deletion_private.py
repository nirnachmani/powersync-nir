"""Shared-profile deletion must not retire a sibling's physical runtime."""

import asyncio
import copy
import importlib
from types import SimpleNamespace

from test_ev_vehicle_status import _Hass, _State, _power_sync_module
from test_shared_logical_vehicle_api import _shared_entry


def test_delete_shared_profile_preserves_sibling_and_physical_runtime(monkeypatch):
    power_sync = _power_sync_module()
    actions = importlib.import_module("power_sync.automations.actions")
    planner = importlib.import_module("power_sync.automations.ev_charging_planner")
    sessions = importlib.import_module("power_sync.automations.ev_charging_session")
    a, b, physical = "shared_ev_profile_a", "shared_ev_profile_b", "generic_ev"

    class Profiles:
        def __init__(self):
            self._data = {"vehicle_charging_configs": [
                {"vehicle_id": a, "charger_type": "generic", "charger_switch_entity": "switch.charger"},
                {"vehicle_id": b, "charger_type": "generic", "charger_switch_entity": "switch.charger"},
            ]}
        async def async_save(self):
            pass

    class Settings:
        def __init__(self):
            self.data = {"auto_schedule_settings": {a: {"enabled": True}, b: {"enabled": True}, physical: {"enabled": True}},
                         "cached_vehicle_soc": {a: 70, b: 60, physical: 50}, "other": 123}
        async def async_load(self):
            return copy.deepcopy(self.data)
        async def async_save(self, data):
            self.data = copy.deepcopy(data)

    profiles, settings = Profiles(), Settings()
    entry = _shared_entry()
    hass = _Hass([_State("select.connected_ev", "tesla")], config_entries=[entry],
                 entry_data={"automation_store": profiles, "store": settings})
    dynamic = {"entry-1": {physical: {"params": {"charger_type": "generic", "charger_switch_entity": "switch.charger", "logical_vehicle_id": b}}}}
    monkeypatch.setattr(actions, "_dynamic_ev_state", dynamic)
    executor = SimpleNamespace(_settings={a: 1, b: 2, physical: 3}, _state={a: 1, b: 2, physical: 3},
                               _cached_soc={a: 70, b: 60, physical: 50}, _current_charge_amps={physical: 16},
                               _clear_active_charging_preserve_intent=lambda *args: None)
    monkeypatch.setattr(planner, "get_auto_schedule_executor", lambda: executor)
    monkeypatch.setattr(planner, "get_price_level_executor", lambda: None)
    monkeypatch.setattr(sessions, "get_session_manager", lambda: None)
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **kwargs: body)
    result = asyncio.run(power_sync.VehicleChargingConfigView(hass).delete(SimpleNamespace(query={"vehicle_id": a})))
    assert result["success"]
    assert a not in settings.data["auto_schedule_settings"]
    assert a not in settings.data["cached_vehicle_soc"]
    assert settings.data["auto_schedule_settings"][b]["enabled"]
    assert settings.data["auto_schedule_settings"][physical]["enabled"]
    assert settings.data["other"] == 123
    assert physical in dynamic["entry-1"]
    assert b in executor._settings and physical in executor._settings


def test_store_update_retains_lock_after_cancellation():
    power_sync = _power_sync_module()

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Store:
            def __init__(self):
                self.data = {}
                self.writes = 0
            async def async_load(self):
                return copy.deepcopy(self.data)
            async def async_save(self, data):
                self.writes += 1
                if self.writes == 1:
                    entered.set()
                    await release.wait()
                self.data = copy.deepcopy(data)

        store = Store()
        first = asyncio.create_task(power_sync._update_powerwall_store(store, {"first": 1}))
        await entered.wait()
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        second = asyncio.create_task(power_sync._update_powerwall_store(store, {"second": 2}))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert store.writes == 1
        release.set()
        assert await second
        assert store.data == {"first": 1, "second": 2}

    asyncio.run(run())


def test_delete_active_shared_profile_preserves_physical_control(monkeypatch):
    power_sync = _power_sync_module()
    actions = importlib.import_module("power_sync.automations.actions")
    planner = importlib.import_module("power_sync.automations.ev_charging_planner")
    sessions = importlib.import_module("power_sync.automations.ev_charging_session")
    a, b, physical = "shared_ev_profile_a", "shared_ev_profile_b", "generic_ev"
    cancelled = []
    class Profiles:
        _data = {"vehicle_charging_configs": [
            {"vehicle_id": a, "charger_type": "generic", "charger_switch_entity": "switch.charger"},
            {"vehicle_id": b, "charger_type": "generic", "charger_switch_entity": "switch.charger"},
        ]}
        async def async_save(self): pass
    class Settings:
        data = {"auto_schedule_settings": {a: {"enabled": True}, b: {"enabled": True}}}
        async def async_load(self): return copy.deepcopy(self.data)
        async def async_save(self, data): self.data = copy.deepcopy(data)
    profiles, settings = Profiles(), Settings()
    hass = _Hass([], config_entries=[_shared_entry()], entry_data={"automation_store": profiles, "store": settings})
    state = {"active": True, "active_profile_id": a,
             "params": {"active_logical_vehicle_id": a, "charger_type": "generic",
                        "charger_switch_entity": "switch.charger"},
             "cancel_timer": lambda: cancelled.append("cancelled")}
    monkeypatch.setattr(actions, "_dynamic_ev_state", {"entry-1": {physical: state}})
    cleared = []
    executor = SimpleNamespace(_settings={physical: "schedule", b: "sibling"},
                               _state={physical: "charging"}, _cached_soc={},
                               _current_charge_amps={physical: 16},
                               _clear_active_charging_preserve_intent=lambda *args: cleared.append(args))
    ended = []
    async def end_session(*args): ended.append(args)
    manager = SimpleNamespace(active_sessions={physical: "active session"}, end_session=end_session)
    monkeypatch.setattr(planner, "get_auto_schedule_executor", lambda: executor)
    monkeypatch.setattr(planner, "get_price_level_executor", lambda: None)
    monkeypatch.setattr(sessions, "get_session_manager", lambda: manager)
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **kwargs: body)
    result = asyncio.run(power_sync.VehicleChargingConfigView(hass).delete(SimpleNamespace(query={"vehicle_id": a})))
    assert result["success"]
    assert state["active"] is True and not state.get("handoff_settling")
    assert cancelled == []
    assert actions._dynamic_ev_state["entry-1"][physical] is state
    assert manager.active_sessions[physical] == "active session" and not ended
    assert all(args[0] != physical for args in cleared)
    assert executor._state[physical] == "charging"
    assert executor._current_charge_amps[physical] == 16
    assert b in settings.data["auto_schedule_settings"]

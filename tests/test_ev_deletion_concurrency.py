"""Deterministic regression for a planner save racing vehicle deletion."""
import asyncio
import copy
import importlib
from types import SimpleNamespace

import pytest

from test_ev_vehicle_status import _Hass, _power_sync_module


@pytest.mark.parametrize("cancel_writer", [False, True])
def test_delete_waits_for_inflight_planner_write(monkeypatch, cancel_writer):
    async def scenario():
        power = _power_sync_module()
        planner = importlib.import_module("power_sync.automations.ev_charging_planner")
        actions = importlib.import_module("power_sync.automations.actions")
        sessions = importlib.import_module("power_sync.automations.ev_charging_session")
        entered, release = asyncio.Event(), asyncio.Event()

        class Store:
            def __init__(self):
                self.data = {"auto_schedule_settings": {"byd_device": {"enabled": True}}}
                self.count = 0

            async def async_load(self):
                return copy.deepcopy(self.data)

            async def async_save(self, data):
                self.count += 1
                if self.count == 1:
                    entered.set()
                    await release.wait()
                self.data = copy.deepcopy(data)

        class Profiles:
            def __init__(self):
                self._data = {"vehicle_charging_configs": [{"vehicle_id": "byd_device", "charger_type": "byd"}]}

            async def async_save(self):
                pass

        store, profiles = Store(), Profiles()
        hass = _Hass([], config_entries=[], entry_data={"automation_store": profiles, "store": store})
        settings = SimpleNamespace(to_dict=lambda: {"enabled": True})
        executor = SimpleNamespace(_settings={"byd_device": settings}, _state={}, _cached_soc={},
                                   _current_charge_amps={}, _clear_active_charging_preserve_intent=lambda *args: None)
        monkeypatch.setattr(planner, "get_auto_schedule_executor", lambda: executor)
        monkeypatch.setattr(planner, "get_price_level_executor", lambda: None)
        monkeypatch.setattr(sessions, "get_session_manager", lambda: None)
        monkeypatch.setattr(actions, "_dynamic_ev_state", {})
        monkeypatch.setattr(power.web, "json_response", lambda body, **kwargs: body)
        writer = asyncio.create_task(planner.AutoScheduleExecutor.save_settings(executor, store))
        await entered.wait()
        if cancel_writer:
            writer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await writer
        deletion = asyncio.create_task(power.VehicleChargingConfigView(hass).delete(
            SimpleNamespace(query={"vehicle_id": "byd_device"})))
        await asyncio.sleep(0)
        assert not deletion.done()
        release.set()
        if not cancel_writer:
            await writer
        result = await deletion
        assert result["success"]
        assert "byd_device" not in store.data["auto_schedule_settings"]
        assert "byd_device" not in executor._settings

    asyncio.run(scenario())

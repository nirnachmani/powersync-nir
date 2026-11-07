"""A real unrelated whole-store writer must serialize with EV deletion."""
import asyncio
import copy
import importlib
from types import SimpleNamespace

from test_ev_vehicle_status import _Hass, _power_sync_module


def test_uncoordinated_whole_store_writer_cannot_restore_deleted_schedule(monkeypatch):
    async def scenario():
        power = _power_sync_module()
        planner = importlib.import_module("power_sync.automations.ev_charging_planner")
        actions = importlib.import_module("power_sync.automations.actions")
        sessions = importlib.import_module("power_sync.automations.ev_charging_session")
        entered, release = asyncio.Event(), asyncio.Event()

        class Store:
            def __init__(self):
                self.data = {"auto_schedule_settings": {"byd_device": {"enabled": True}}}
                self.calls = 0

            async def async_load(self):
                return copy.deepcopy(self.data)

            async def async_save(self, data):
                self.calls += 1
                if self.calls == 1:
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
        executor = SimpleNamespace(_settings={}, _state={}, _cached_soc={}, _current_charge_amps={},
                                   _clear_active_charging_preserve_intent=lambda *args: None)
        monkeypatch.setattr(planner, "get_auto_schedule_executor", lambda: executor)
        monkeypatch.setattr(planner, "get_price_level_executor", lambda: None)
        monkeypatch.setattr(sessions, "get_session_manager", lambda: None)
        monkeypatch.setattr(actions, "_dynamic_ev_state", {})
        monkeypatch.setattr(power.web, "json_response", lambda body, **kwargs: body)
        writer = asyncio.create_task(power.BatteryHealthView(hass)._sync_live_battery_health_to_sensor(
            SimpleNamespace(entry_id="entry-1"), {"available": True, "health_percent": 90}))
        await entered.wait()
        writer.cancel()
        await asyncio.sleep(0)
        deletion = asyncio.create_task(power.VehicleChargingConfigView(hass).delete(
            SimpleNamespace(query={"vehicle_id": "byd_device"})))
        await asyncio.wait({deletion}, timeout=0.1)
        assert not deletion.done(), "deletion must wait for the real writer's transaction"
        release.set()
        try:
            await writer
            assert False, "cancelled writer should propagate cancellation"
        except asyncio.CancelledError:
            pass
        result = await deletion
        assert result["success"]
        assert "byd_device" not in store.data["auto_schedule_settings"]
        assert store.data["battery_health"]["degradation_percent"] == 10.0

    asyncio.run(scenario())

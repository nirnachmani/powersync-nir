"""Queued price edits must not restore a deleted logical profile."""
import asyncio
import copy
import importlib
from types import SimpleNamespace

import pytest
from test_ev_vehicle_status import _Hass, _power_sync_module


def test_queued_price_cap_does_not_resurrect_deleted_profile(monkeypatch):
    async def scenario():
        power = _power_sync_module()
        planner = importlib.import_module("power_sync.automations.ev_charging_planner")
        shared = importlib.import_module("power_sync.automations.shared_loadpoint")
        actions = importlib.import_module("power_sync.automations.actions")
        sessions = importlib.import_module("power_sync.automations.ev_charging_session")
        profile = shared.PROFILE_A_ID
        entered, release = asyncio.Event(), asyncio.Event()

        class Store:
            def __init__(self):
                self.data = {"auto_schedule_settings": {profile: {"enabled": True}}, "other": 1}

            async def async_load(self):
                return copy.deepcopy(self.data)

            async def async_save(self, data):
                entered.set()
                await release.wait()
                self.data = copy.deepcopy(data)

        class Profiles:
            def __init__(self):
                self._data = {"vehicle_charging_configs": [{"vehicle_id": profile}]}

            async def async_save(self):
                pass

        store, profiles = Store(), Profiles()
        hass = _Hass([], config_entries=[], entry_data={"automation_store": profiles, "store": store})
        monkeypatch.setattr(planner, "get_auto_schedule_executor", lambda: None)
        monkeypatch.setattr(planner, "get_price_level_executor", lambda: None)
        monkeypatch.setattr(sessions, "get_session_manager", lambda: None)
        monkeypatch.setattr(actions, "_dynamic_ev_state", {})
        monkeypatch.setattr(power.web, "json_response", lambda body, **kwargs: body)
        deletion = asyncio.create_task(power.VehicleChargingConfigView(hass).delete(
            SimpleNamespace(query={"vehicle_id": profile})))
        await asyncio.wait_for(entered.wait(), 2)
        edit = asyncio.create_task(planner.save_shared_auto_schedule_price_caps(store, {profile: 20}))
        await asyncio.sleep(0)
        release.set()
        assert (await asyncio.wait_for(deletion, 2))["success"]
        with pytest.raises(RuntimeError, match="deleted"):
            await asyncio.wait_for(edit, 2)
        assert profile not in store.data["auto_schedule_settings"]
        assert store.data["other"] == 1

    asyncio.run(scenario())

"""A shared options capacity write must not revive a deleted profile."""
import asyncio
import copy
import importlib
from types import SimpleNamespace

from test_ev_vehicle_status import _Hass, _power_sync_module


def test_capacity_write_cannot_overwrite_completed_deletion(monkeypatch):
    async def scenario():
        power = _power_sync_module()
        shared = importlib.import_module('power_sync.automations.shared_loadpoint')
        planner = importlib.import_module('power_sync.automations.ev_charging_planner')
        actions = importlib.import_module('power_sync.automations.actions')
        sessions = importlib.import_module('power_sync.automations.ev_charging_session')
        profile = shared.PROFILE_A_ID
        entered, release = asyncio.Event(), asyncio.Event()

        class Profiles:
            def __init__(self):
                self._data = {'vehicle_charging_configs': [{'vehicle_id': profile}]}
                self.saved = copy.deepcopy(self._data)
                self.calls = 0
            async def async_save(self):
                snapshot = copy.deepcopy(self._data)
                self.calls += 1
                if self.calls == 1:
                    entered.set()
                    await release.wait()
                self.saved = snapshot

        class Settings:
            def __init__(self):
                self.data = {'auto_schedule_settings': {profile: {'enabled': True}}}
            async def async_load(self): return copy.deepcopy(self.data)
            async def async_save(self, data): self.data = copy.deepcopy(data)

        profiles, settings = Profiles(), Settings()
        hass = _Hass([], config_entries=[], entry_data={'automation_store': profiles, 'store': settings})
        monkeypatch.setattr(planner, 'get_auto_schedule_executor', lambda: None)
        monkeypatch.setattr(planner, 'get_price_level_executor', lambda: None)
        monkeypatch.setattr(sessions, 'get_session_manager', lambda: None)
        monkeypatch.setattr(actions, '_dynamic_ev_state', {})
        monkeypatch.setattr(power.web, 'json_response', lambda body, **kwargs: body)
        update = asyncio.create_task(shared.save_shared_profile_capacities(
            profiles, {profile: 42}, settings_store=settings))
        await entered.wait()
        deletion = asyncio.create_task(power.VehicleChargingConfigView(hass).delete(
            SimpleNamespace(query={'vehicle_id': profile})))
        await asyncio.sleep(0.05)
        assert not deletion.done()
        release.set()
        await update
        response = await asyncio.wait_for(deletion, 2)
        assert response['success']
        assert profile not in [item['vehicle_id'] for item in profiles.saved['vehicle_charging_configs']]

    asyncio.run(scenario())

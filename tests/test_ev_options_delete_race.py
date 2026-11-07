"""The entire shared options submission must serialize with deletion."""
import ast
import asyncio
import copy
import importlib
from types import SimpleNamespace

from test_ev_vehicle_status import _Hass, _power_sync_module
from test_config_flow_weather_options import CONFIG_FLOW_PATH, _options_flow_method


def test_options_price_replan_cannot_revive_deleted_profile(monkeypatch):
    async def scenario():
        power = _power_sync_module()
        shared = importlib.import_module('power_sync.automations.shared_loadpoint')
        planner = importlib.import_module('power_sync.automations.ev_charging_planner')
        actions = importlib.import_module('power_sync.automations.actions')
        sessions = importlib.import_module('power_sync.automations.ev_charging_session')
        a = shared.PROFILE_A_ID
        entered, release = asyncio.Event(), asyncio.Event()
        class Profiles:
            def __init__(self): self._data = {'vehicle_charging_configs': [{'vehicle_id': a}]}
            async def async_save(self): pass
        class Settings:
            def __init__(self): self.data = {'auto_schedule_settings': {a: {'enabled': True}}}
            async def async_load(self): return copy.deepcopy(self.data)
            async def async_save(self, data): self.data = copy.deepcopy(data)
        class Executor:
            def __init__(self):
                self._settings = {}; self._state = {}; self._cached_soc = {}; self._current_charge_amps = {}
            def _clear_active_charging_preserve_intent(self, *args): pass
            def update_settings(self, profile, updates): return object()
            def get_state(self, profile): return object()
            async def _regenerate_plan(self, *args):
                entered.set()
                await release.wait()
        profiles, settings, executor = Profiles(), Settings(), Executor()
        hass = _Hass([], config_entries=[], entry_data={'automation_store': profiles, 'store': settings, 'auto_schedule_executor': executor})
        monkeypatch.setattr(planner, 'get_auto_schedule_executor', lambda: executor)
        monkeypatch.setattr(planner, 'get_price_level_executor', lambda: None)
        monkeypatch.setattr(sessions, 'get_session_manager', lambda: None)
        monkeypatch.setattr(actions, '_dynamic_ev_state', {})
        monkeypatch.setattr(power.web, 'json_response', lambda body, **kwargs: body)
        ns = {'__package__': 'power_sync', 'Any': object, 'FlowResult': object, 'DOMAIN': 'power_sync'}
        for name, value in {
            'A_CAPACITY_FORM': 'a_capacity', 'B_CAPACITY_FORM': 'b_capacity',
            'A_CAPACITY_CLEAR_FORM': 'a_clear', 'B_CAPACITY_CLEAR_FORM': 'b_clear',
            'A_PRICE_CAP_FORM': 'a_price', 'B_PRICE_CAP_FORM': 'b_price',
        }.items(): ns['CONF_SHARED_PROFILE_' + name] = value
        exec(compile(ast.Module(body=[_options_flow_method('_save_ev_options_and_capacities')], type_ignores=[]), str(CONFIG_FLOW_PATH), 'exec'), ns)
        flow = SimpleNamespace(_get_shared_capacity_store=lambda: profiles, _get_shared_schedule_store=lambda: settings,
                               hass=hass, config_entry=SimpleNamespace(entry_id='entry-1'), _save_ev_options=lambda data: data)
        submitted = {'generic_charger_enabled': True, 'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_ev',
                     'shared_loadpoint_profile_a_name': 'A', 'shared_loadpoint_profile_a_state': 'a',
                     'shared_loadpoint_profile_b_name': 'B', 'shared_loadpoint_profile_b_state': 'b',
                     'a_price': 20, 'a_capacity': 42}
        options = asyncio.create_task(ns['_save_ev_options_and_capacities'](flow, submitted))
        await asyncio.wait_for(entered.wait(), 2)
        deletion = asyncio.create_task(power.VehicleChargingConfigView(hass).delete(SimpleNamespace(query={'vehicle_id': a})))
        await asyncio.sleep(0.05)
        assert not deletion.done()
        release.set()
        await options
        result = await asyncio.wait_for(deletion, 2)
        assert result['success']
        assert a not in [r['vehicle_id'] for r in profiles._data['vehicle_charging_configs']]
    asyncio.run(scenario())

"""PS-013: real dynamic controller, reconciler, session manager and API lifecycle."""
import asyncio
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions
from test_shared_logical_session_api import _sessions_get_method
from test_shared_stop_storage import Store


@pytest.mark.parametrize('backend', ['generic', 'evac'])
@pytest.mark.parametrize('promote', [False, True])
def test_dynamic_pending_observation_and_confirmed_stop(monkeypatch, tmp_path, backend, promote):
    async def run():
        sessions = importlib.import_module('power_sync.automations.ev_charging_session')
        reconciler = importlib.import_module('power_sync.automations.external_session_reconciler')
        monkeypatch.setattr(sessions.dt_util, 'now', lambda: datetime.now(timezone.utc), raising=False)
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        async def executor(func, *args):
            return func(*args)
        hass.async_add_executor_job = executor
        hass.config = SimpleNamespace(config_dir=str(tmp_path))
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store({'automations': [], 'vehicle_charging_configs': []})
        manager = sessions.ChargingSessionManager(hass, storage_path=tmp_path / 'history.json')
        manager._cache_loaded = True
        data['session_manager'] = manager
        monkeypatch.setattr(sessions, 'get_session_manager', lambda: manager)
        binding = 'generic_ev' if backend == 'generic' else 'sigenergy_charger'
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'smart_schedule', 'owner_mode': 'smart_schedule',
                  'fixed_charge_amps': 8, 'max_charge_amps': 8,
                  'notify_on_start': False, 'notify_on_complete': False}
        state = {}
        original_get = hass.states.get
        hass.states.get = lambda key: state.get(key) or original_get(key)
        reader = AsyncMock(return_value=None)
        stop_write = AsyncMock()
        start_write = AsyncMock(return_value=True)
        amps_write = AsyncMock(return_value=True)
        def command_counts():
            return (hass.services.async_call.await_count, start_write.await_count,
                    amps_write.await_count, stop_write.await_count)
        if backend == 'evac':
            entry.options = {**entry.options, 'generic_charger_enabled': False,
                             'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac',
                             'sigenergy_charger_host': 'charger.invalid'}
            params['charger_type'] = 'sigenergy'
            monkeypatch.setattr(actions, '_start_sigenergy_charger', start_write)
            monkeypatch.setattr(actions, '_set_sigenergy_charger_amps', amps_write)
            async def dispatch(*args):
                actions._mark_shared_stop_dispatch()
                return True
            stop_write.side_effect = dispatch
            monkeypatch.setattr(actions, '_stop_sigenergy_charger', stop_write)
            monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: SimpleNamespace(
                _read_input_registers=reader, disconnect=AsyncMock()))
        get = _sessions_get_method()
        view = SimpleNamespace(_get_session_manager=lambda: manager)
        async def api():
            return await get(view, SimpleNamespace(query={'vehicle_id': 'shared_ev_profile_a'}))
        actions._dynamic_ev_state.clear()
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        session = manager.active_sessions[binding]
        assert session.pending and session.logical_vehicle_id == 'shared_ev_profile_a'
        assert actions._dynamic_ev_state[entry.entry_id][binding]['session_id'] == session.id
        assert (await api())['active_sessions'] == []
        # Observation and recording must not issue a new physical command.
        writes = command_counts()
        now = datetime.now(timezone.utc)
        state['sensor.shared_ev_power'] = SimpleNamespace(state='0',
            attributes={'unit_of_measurement': 'W'}, last_reported=now)
        async def idle_evac():
            return SimpleNamespace(charger_type='evac', raw_state=2, is_connected=True,
                                   is_charging=False, power_kw=0.0)
        await reconciler.reconcile_selected_shared_loadpoint_cycle(hass, entry, now=now, read_evac_state=idle_evac)
        assert session.pending and manager.active_sessions[binding] is session
        assert (await api())['active_sessions'] == []
        now = datetime.now(timezone.utc)
        state['sensor.shared_ev_power'].state = '20' if promote else 'unknown'
        state['sensor.shared_ev_power'].last_reported = now
        async def read_evac():
            return SimpleNamespace(charger_type='evac', raw_state=4, is_connected=True,
                                   is_charging=True, power_kw=0.02) if promote else None
        await reconciler.reconcile_selected_shared_loadpoint_cycle(hass, entry, now=now, read_evac_state=read_evac)
        assert command_counts() == writes
        assert session.pending is (not promote)
        active = (await api())['active_sessions']
        assert [item['id'] for item in active] == ([session.id] if promote else [])
        stop = {'vehicle_id': binding, 'stop_charging': True}
        # Unknown observation retains the session after the stop command.
        assert not await actions._action_stop_ev_charging_dynamic(hass, entry, stop)
        state['sensor.shared_ev_power'].state = 'unknown'
        state['sensor.shared_ev_power'].last_reported = datetime.now(timezone.utc)
        assert not await actions._action_stop_ev_charging_dynamic(hass, entry, stop)
        assert manager.active_sessions[binding] is session
        writes = command_counts()
        state['sensor.shared_ev_power'].state = '100'
        state['sensor.shared_ev_power'].last_reported = datetime.now(timezone.utc)
        reader.return_value = [2, 0, 0, 0, 100, 0, 0, 0, 0, 0, 0, 0]
        assert not await actions._action_stop_ev_charging_dynamic(hass, entry, stop)
        assert manager.active_sessions[binding] is session
        assert command_counts() == writes
        state['sensor.shared_ev_power'].state = '0'
        state['sensor.shared_ev_power'].last_reported = datetime.now(timezone.utc)
        reader.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        assert await actions._action_stop_ev_charging_dynamic(hass, entry, stop)
        assert command_counts() == writes
        assert binding not in manager.active_sessions
        result = await api()
        assert result['active_sessions'] == []
        assert [item['id'] for item in result['sessions']] == ([session.id] if promote else [])
        if manager._history_retry_handle:
            manager._history_retry_handle.cancel()
    try:
        asyncio.run(run())
    finally:
        actions._dynamic_ev_state.clear()

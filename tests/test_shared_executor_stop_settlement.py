"""A confirmed shared stop reconciles only the executor that owned it."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from test_ev_price_level_ownership import ev_planner
from test_shared_loadpoint_action_guard import _Hass, _Entry, actions, ownership
from test_shared_stop_storage import Store


@pytest.mark.parametrize('mode', ['smart_schedule', 'scheduled'])
@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
def test_background_stop_clears_outgoing_state(monkeypatch, mode, backend, physical):
    async def scenario():
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        if backend == 'sigenergy':
            entry.options = {**entry.options, 'generic_charger_enabled': False,
                'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac',
                'sigenergy_charger_host': 'charger.invalid'}
            class Controller:
                async def connect(self): return True
                async def stop_charging(self):
                    return self._shared_write_authorized()
                async def disconnect(self): pass
                _read_input_registers = AsyncMock(return_value=None)
            controller = Controller()
            monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        lease = ownership.acquire_shared_loadpoint_ownership(
            hass, entry, physical, active_profile_id='shared_ev_profile_a',
            owner_mode=mode)
        assert lease
        if mode == 'smart_schedule':
            executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
            state = executor.get_state('shared_ev_profile_a')
            monkeypatch.setattr(ev_planner, 'get_auto_schedule_executor', lambda: executor)
            settings = ev_planner.AutoScheduleSettings(enabled=True, vehicle_id='shared_ev_profile_a')
            state.is_charging = True
            stopped = await executor._stop_charging('shared_ev_profile_a', settings, state, reason='window ended')
        else:
            executor = ev_planner.ScheduledChargingExecutor(hass, entry)
            state = executor._state
            state.is_charging = True
            executor._active_shared_profile_id = 'shared_ev_profile_a'
            monkeypatch.setattr(ev_planner, 'get_scheduled_charging_executor', lambda: executor)
            stopped = await executor._stop_charging('window ended')
        assert not stopped
        assert state.is_charging
        pending = actions._dynamic_ev_state[entry.entry_id][physical]['pending_stop']
        if backend == 'generic':
            states['sensor.shared_ev_power'] = SimpleNamespace(
                state='0', attributes={'unit_of_measurement': 'W'}, last_reported=pending['dispatch_at'])
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert state.is_charging
        if backend == 'generic':
            states['sensor.shared_ev_power'].last_reported = datetime.now(timezone.utc)
        else:
            controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert ownership.get_ev_ownership(hass, entry, physical)[1] is None, (pending['status'], pending.get('dispatch_at'), pending.get('latest_observation'), pending.get('record'))
        assert not state.is_charging

    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_scheduled_settlement_preserves_price_level_coordinator_and_battery_hold(monkeypatch):
    hass, entry = _Hass(), _Entry()
    scheduled = ev_planner.ScheduledChargingExecutor(hass, entry)
    scheduled._state.is_charging = True
    scheduled._active_shared_profile_id = 'shared_ev_profile_a'
    scheduled._preserve_home_battery_active = True
    price = ev_planner.PriceLevelChargingExecutor(hass, entry)
    price._preserve_home_battery_active = True
    coordinator = ev_planner.EVChargingModeCoordinator(hass, entry)
    coordinator._active_modes = ['Scheduled', 'Price-Level']
    coordinator._is_charging = True
    hass.data['power_sync'][entry.entry_id]['scheduled_ev_preserve_state'] = {
        'active': True, 'source': 'scheduled_charging'}
    monkeypatch.setattr(ev_planner, 'get_scheduled_charging_executor', lambda: scheduled)
    monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: price)
    monkeypatch.setattr(ev_planner, 'get_ev_charging_coordinator', lambda: coordinator)
    snap = {'executor': scheduled, 'state': scheduled._state, 'profile': 'shared_ev_profile_a',
            'family': 'scheduled', 'generation': scheduled._state.charging_generation}
    ev_planner._complete_shared_executor_stop(entry, snap)
    assert not scheduled._state.is_charging
    assert coordinator._active_modes == ['Price-Level']
    assert coordinator._is_charging
    hold = hass.data['power_sync'][entry.entry_id]['scheduled_ev_preserve_state']
    assert hold['active'] and hold['source'] == 'price_level_charging'
    assert price._preserve_home_battery_active


def test_foreign_owner_rejection_is_not_a_physical_stop_failure(monkeypatch):
    from unittest.mock import Mock
    from power_sync import action_events

    hass, entry = _Hass(), _Entry()
    hass.bus = SimpleNamespace(async_fire=Mock())
    notice = Mock()
    monkeypatch.setattr(action_events, '_notification', notice)
    assert ownership.acquire_shared_loadpoint_ownership(
        hass, entry, 'generic_ev', active_profile_id='shared_ev_profile_a',
        owner_mode='solar_surplus')
    physical_stop = ownership.record_ev_command(hass, entry, 'generic_ev',
        command='stop', success=False, reason='physical stop failed')
    existing_alert = hass.data['power_sync'][entry.entry_id]['ev_stop_alerts']['generic_ev']
    notice.reset_mock()
    hass.bus.async_fire.reset_mock()
    assert not ev_planner._can_stop_loadpoint_for_mode(
        hass, entry, 'generic_ev', expected_owner_mode='smart_schedule',
        command='stop_smart_schedule')
    notice.assert_not_called()
    assert hass.data['power_sync'][entry.entry_id]['ev_stop_alerts']['generic_ev'] is existing_alert
    assert ownership.get_ev_last_commands(hass, entry)['generic_ev'] is physical_stop
    assert all(call.args[0] != 'power_sync_ev_stop_failed'
               for call in hass.bus.async_fire.call_args_list)
    assert any(call.args[0] == 'power_sync_ev_command'
               for call in hass.bus.async_fire.call_args_list)


@pytest.mark.parametrize('mode', ['smart_schedule', 'scheduled'])
def test_late_stop_return_does_not_clear_new_generation(monkeypatch, mode):
    async def scenario():
        hass, entry = _Hass(), _Entry()
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return True
        monkeypatch.setattr(ev_planner, '_stop_coordinated_charging', delayed)
        if mode == 'smart_schedule':
            executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
            state = executor.get_state('shared_ev_profile_a')
            settings = ev_planner.AutoScheduleSettings(enabled=True, vehicle_id='shared_ev_profile_a')
            coro = executor._stop_charging('shared_ev_profile_a', settings, state, reason='old')
        else:
            executor = ev_planner.ScheduledChargingExecutor(hass, entry)
            state = executor._state
            executor._active_shared_profile_id = 'shared_ev_profile_a'
            coro = executor._stop_charging('old')
        state.is_charging = True
        task = asyncio.create_task(coro)
        await entered.wait()
        state.charging_generation += 1
        state.is_charging = True
        release.set()
        await task
        assert state.is_charging
    asyncio.run(scenario())


def test_incoming_scheduled_handover_cleans_smart_solar_executor(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params

    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        solar = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                 'active_logical_vehicle_id': 'shared_ev_profile_a',
                 'logical_vehicle_id': 'shared_ev_profile_a', 'shared_loadpoint_binding': True,
                 'dynamic_mode': 'solar_surplus', 'owner_mode': 'smart_schedule_solar_surplus',
                 'notify_on_start': False}
        runtime = {'active': True, 'params': solar, 'active_profile_id': 'shared_ev_profile_a',
                   'session_id': None, 'current_amps': 0, 'cancel_timer': lambda: None}
        actions._dynamic_ev_state[entry.entry_id] = {'generic_ev': runtime}
        ownership.claim_ev_ownership(hass, entry, 'generic_ev',
            owner_mode='smart_schedule_solar_surplus', extra={'active_profile_id': 'shared_ev_profile_a'})
        executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
        state = executor.get_state('shared_ev_profile_a')
        state.is_charging = True
        monkeypatch.setattr(ev_planner, 'get_auto_schedule_executor', lambda: executor)
        ev_planner._bind_shared_executor_runtime(executor, state, 'shared_ev_profile_a', 'smart_schedule')
        incoming = {**solar, 'dynamic_mode': 'battery_target', 'owner_mode': 'scheduled',
                    'allow_ownership_takeover': True, 'fixed_charge_amps': 8, 'max_charge_amps': 8}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='scheduled', reason='', source='test')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert runtime.get('pending_stop')
        assert state.is_charging
        states['sensor.shared_ev_power'] = SimpleNamespace(
            state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not state.is_charging
        assert 'generic_ev' not in actions._dynamic_ev_state.get(entry.entry_id, {})
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='scheduled', reason='', source='test')
        assert await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]['owner_mode'] == 'scheduled'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


@pytest.mark.parametrize('mode', ['smart_schedule', 'scheduled'])
def test_fresh_idle_profile_handoff_cleans_old_executor(monkeypatch, mode):
    from test_shared_pause_evac_behavior import setup

    async def scenario():
        hass, entry, _, physical, params, runtime, _ = setup('generic')
        params['owner_mode'] = mode
        params['charger_power_entity'] = 'sensor.shared_ev_power'
        runtime['params']['owner_mode'] = mode
        runtime['params']['charger_power_entity'] = 'sensor.shared_ev_power'
        ownership.claim_ev_ownership(hass, entry, physical, owner_mode=mode,
                                     extra={'active_profile_id': 'shared_ev_profile_a'})
        if mode == 'smart_schedule':
            executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
            state = executor.get_state('shared_ev_profile_a')
            monkeypatch.setattr(ev_planner, 'get_auto_schedule_executor', lambda: executor)
        else:
            executor = ev_planner.ScheduledChargingExecutor(hass, entry)
            state = executor._state
            executor._active_shared_profile_id = 'shared_ev_profile_a'
            monkeypatch.setattr(ev_planner, 'get_scheduled_charging_executor', lambda: executor)
        state.is_charging = True
        ev_planner._bind_shared_executor_runtime(executor, state, 'shared_ev_profile_a', mode)
        assert runtime.get('executor_stop_snapshot')
        states, original = {}, hass.states.get
        states['sensor.shared_ev_power'] = SimpleNamespace(
            state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        hass.states.get = lambda key: states.get(key) or original(key)
        hass.states.get('sensor.connected_vehicle').state = 'tesla'
        incoming = {**params, 'vehicle_id': 'shared_ev_profile_b',
                    'active_logical_vehicle_id': 'shared_ev_profile_b',
                    'logical_vehicle_id': 'shared_ev_profile_b',
                    'dynamic_mode': 'battery_target', 'owner_mode': 'scheduled',
                    'allow_ownership_takeover': True, 'fixed_charge_amps': 8,
                    'max_charge_amps': 8, 'notify_on_start': False}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='scheduled', reason='', source='test')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert physical not in actions._dynamic_ev_state.get(entry.entry_id, {})
        assert not state.is_charging
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


@pytest.mark.parametrize('mode', ['smart_schedule', 'scheduled', 'price_level'])
@pytest.mark.parametrize('newer_generation', [False, True])
def test_incoming_teardown_uses_outgoing_runtime_identity(monkeypatch, mode, newer_generation):
    from test_shared_loadpoint_action_guard import _generic_params

    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'smart_schedule' if mode == 'smart_schedule' else 'battery_target', 'owner_mode': mode,
                  'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        if mode == 'smart_schedule':
            executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
            state = executor.get_state('shared_ev_profile_a')
            monkeypatch.setattr(ev_planner, 'get_auto_schedule_executor', lambda: executor)
        elif mode == 'scheduled':
            executor = ev_planner.ScheduledChargingExecutor(hass, entry)
            state = executor._state
            executor._active_shared_profile_id = 'shared_ev_profile_a'
            monkeypatch.setattr(ev_planner, 'get_scheduled_charging_executor', lambda: executor)
        else:
            executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
            state = executor._get_or_create_vehicle_state('shared_ev_profile_a')
            state.charging_mode = 'price_level'
            monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        state.is_charging = True
        ev_planner._bind_shared_executor_runtime(executor, state, 'shared_ev_profile_a', mode)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        assert runtime.get('executor_stop_snapshot')
        # This stop is initiated at the dynamic transition seam, without calling
        # the outgoing executor's _stop_charging method.
        assert not await actions._action_stop_ev_charging_dynamic(
            hass, entry, {'vehicle_id': 'generic_ev', 'stop_charging': True})
        if newer_generation:
            state.charging_generation += 1
        states['sensor.shared_ev_power'] = SimpleNamespace(
            state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert state.is_charging is newer_generation

    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()

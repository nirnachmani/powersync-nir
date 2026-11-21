"""A confirmed shared stop reconciles only the executor that owned it."""
import asyncio
from datetime import datetime, timedelta, timezone
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


def test_opportunity_start_waits_for_its_adopted_directive(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store()
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_opportunity',
                  'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        data['optimization_coordinator'] = SimpleNamespace(_enabled=True)
        incoming = {**params, '_opportunity_generation': object()}
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        assert runtime['active'] and not runtime.get('pending_stop')
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]['owner_mode'] == 'price_level_opportunity'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_passive_solar_candidate_uses_existing_policy_and_counts_ev_power(monkeypatch):
    from test_shared_loadpoint_action_guard import _shared_solar_preflight_setup, _generic_params
    hass, entry = _shared_solar_preflight_setup()
    selector = hass.states.get('sensor.connected_vehicle')
    selector.last_changed = datetime.now(timezone.utc)
    store = hass.data['power_sync'][entry.entry_id]['automation_store']
    store._data['solar_surplus_config'].update({'min_battery_soc': 50,
        'household_buffer_kw': 0.5, 'max_export_price_cents': 10})
    monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
    monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
    monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
    monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value={
        'battery_soc': 80, 'solar_power': 7000, 'grid_power': -1000,
        'battery_power': 0, 'load_power': 6000}))
    monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', AsyncMock(return_value=(5.0, True)))
    params = {**_generic_params(), 'charger_power_entity': 'sensor.shared_ev_power',
        'vehicle_id': 'generic_ev', 'active_logical_vehicle_id': 'shared_ev_profile_a', 'shared_loadpoint_binding': True,
        'voltage': 230, 'phases': 1, 'min_charge_amps': 6, 'max_charge_amps': 32}
    candidate = asyncio.run(actions._evaluate_shared_solar_candidate(hass, entry, params))
    assert candidate['eligible']
    assert candidate['capacity_kw'] == pytest.approx(5.5)
    assert candidate['max_kw'] == pytest.approx(7.36)
    hass.services.async_call.assert_not_awaited()
    monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 20)
    candidate = asyncio.run(actions._evaluate_shared_solar_candidate(hass, entry, params))
    assert not candidate['eligible']
    hass.services.async_call.assert_not_awaited()


def test_passive_solar_candidate_preserves_active_battery_floor_hysteresis(monkeypatch):
    from test_shared_loadpoint_action_guard import _shared_solar_preflight_setup, _generic_params
    hass, entry = _shared_solar_preflight_setup()
    hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc)
    store = hass.data['power_sync'][entry.entry_id]['automation_store']
    store._data['solar_surplus_config'].update({'min_battery_soc': 50})
    monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
    monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
    monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 0)
    monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value={
        'battery_soc': 45, 'solar_power': 7000, 'grid_power': -3000, 'battery_power': 0, 'load_power': 3000}))
    monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', AsyncMock(return_value=(2.0, True)))
    params = {**_generic_params(), 'vehicle_id': 'generic_ev', 'active_logical_vehicle_id': 'shared_ev_profile_a',
              'voltage': 230, 'phases': 1, 'min_charge_amps': 6, 'max_charge_amps': 32}
    runtime = {'active': True, 'active_profile_id': 'shared_ev_profile_a', 'charging_started': True,
        'current_amps': 6, 'params': {'owner_mode': 'solar_surplus'}}
    actions._dynamic_ev_state['entry-1'] = {'generic_ev': runtime}
    try:
        result = asyncio.run(actions._evaluate_shared_solar_candidate(hass, entry, params))
        assert result['eligible']
        runtime['params']['owner_mode'] = 'price_level_recovery'
        result = asyncio.run(actions._evaluate_shared_solar_candidate(hass, entry, params))
        assert not result['eligible']
    finally:
        actions._dynamic_ev_state.clear()


@pytest.mark.parametrize('soc,parallel,expected', [(40, False, False), (80, False, True),
                                                   (40, True, True), (80, True, True)])
def test_solar_candidate_battery_floor_and_parallel_reserve(monkeypatch, soc, parallel, expected):
    from test_shared_loadpoint_action_guard import _shared_solar_preflight_setup, _generic_params
    hass, entry = _shared_solar_preflight_setup()
    hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc)
    store = hass.data['power_sync'][entry.entry_id]['automation_store']
    store._data['solar_surplus_config'].update({'min_battery_soc': 50,
        'allow_parallel_charging': parallel, 'max_battery_charge_rate_kw': 2,
        'household_buffer_kw': 0.5, 'max_export_price_cents': 10})
    monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
    monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
    monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
    monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value={
        'battery_soc': soc, 'solar_power': 9000, 'grid_power': -5000,
        'battery_power': -2000, 'load_power': 2000}))
    monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', AsyncMock(return_value=(0.0, True)))
    params = {**_generic_params(), 'vehicle_id': 'generic_ev', 'active_logical_vehicle_id': 'shared_ev_profile_a',
              'voltage': 230, 'phases': 1, 'min_charge_amps': 6, 'max_charge_amps': 32}
    result = asyncio.run(actions._evaluate_shared_solar_candidate(hass, entry, params))
    assert result['eligible'] is expected
    if expected:
        assert result['capacity_kw'] == pytest.approx(4.5 if parallel else 6.5)
        assert result['parallel'] is (soc < 50 and parallel)


def test_live_shared_arbitration_uses_capacity_not_recovery_label(monkeypatch):
    from test_ev_price_level_ownership import _FakeHass, _FakeConfigEntry
    hass, entry = _FakeHass(), _FakeConfigEntry()
    entry.options = {'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Other', 'shared_loadpoint_profile_b_state': 'other'}
    hass.states._states['sensor.connected_vehicle'] = SimpleNamespace(state='tank', last_changed=datetime.now(timezone.utc))
    executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
    executor._get_settings = lambda: {'opportunity_price_cents': 10}
    monkeypatch.setattr(ev_planner, '_build_dynamic_charging_params', lambda *a, **k: {
        'vehicle_id': 'generic_ev', 'active_logical_vehicle_id': 'shared_ev_profile_a'})
    candidate = {'eligible': True, 'capacity_kw': 3, 'max_kw': 7, 'min_kw': 1.4,
        'params': {'sustained_surplus_minutes': 0, 'stop_delay_minutes': 0},
        'selection_changed': hass.states.get('sensor.connected_vehicle').last_changed}
    monkeypatch.setattr(actions, '_evaluate_shared_solar_candidate', AsyncMock(return_value=candidate))
    choice, _ = asyncio.run(ev_planner._shared_live_opportunity_decision(
        executor, 'shared_ev_profile_a', (True, 'recovery', 'price_level_recovery'), 8))
    assert choice == 'price_level'
    candidate['capacity_kw'] = 7
    choice, _ = asyncio.run(ev_planner._shared_live_opportunity_decision(
        executor, 'shared_ev_profile_a', (True, 'recovery', 'price_level_recovery'), 8))
    assert choice == 'solar_surplus'
    candidate['capacity_kw'] = 3
    choice, _ = asyncio.run(ev_planner._shared_live_opportunity_decision(
        executor, 'shared_ev_profile_a', (True, 'recovery', 'price_level_recovery'), 20))
    assert choice == 'solar_surplus'


def test_solar_max_boundary_resets_when_configured_max_changes(monkeypatch):
    from test_ev_price_level_ownership import _FakeHass, _FakeConfigEntry
    hass, entry = _FakeHass(states={'sensor.connected_vehicle': 'tank'}), _FakeConfigEntry()
    executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
    executor._get_settings = lambda: {'opportunity_price_cents': 10}
    monkeypatch.setattr(ev_planner, '_build_dynamic_charging_params', lambda *a, **k: {'vehicle_id': 'generic_ev'})
    candidate = {'eligible': True, 'capacity_kw': 6, 'max_kw': 5, 'min_kw': 1.4,
                 'params': {'sustained_surplus_minutes': 0, 'stop_delay_minutes': 3},
                 'selection_changed': datetime.now(timezone.utc)}
    monkeypatch.setattr(actions, '_evaluate_shared_solar_candidate', AsyncMock(return_value=candidate))
    decision = (True, 'cheap', 'price_level_recovery')
    assert asyncio.run(ev_planner._shared_live_opportunity_decision(executor, 'shared_ev_profile_a', decision, 8))[0] == 'solar_surplus'
    candidate['max_kw'] = 7
    assert asyncio.run(ev_planner._shared_live_opportunity_decision(executor, 'shared_ev_profile_a', decision, 8))[0] == 'price_level'


def test_unknown_solar_evidence_resets_pending_sustained_boundary(monkeypatch):
    from test_ev_price_level_ownership import _FakeHass, _FakeConfigEntry
    hass, entry = _FakeHass(states={'sensor.connected_vehicle': 'tank'}), _FakeConfigEntry()
    executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
    executor._get_settings = lambda: {'opportunity_price_cents': 10}
    monkeypatch.setattr(ev_planner, '_build_dynamic_charging_params', lambda *a, **k: {'vehicle_id': 'generic_ev'})
    candidate = {'eligible': True, 'capacity_kw': 8, 'max_kw': 7, 'min_kw': 1.4,
                 'params': {'sustained_surplus_minutes': 3, 'stop_delay_minutes': 3},
                 'selection_changed': datetime.now(timezone.utc)}
    probe = AsyncMock(side_effect=[candidate, None, candidate])
    monkeypatch.setattr(actions, '_evaluate_shared_solar_candidate', probe)
    clock = [0.0]
    monkeypatch.setattr(ev_planner.time, 'monotonic', lambda: clock[0])
    decision = (True, 'cheap', 'price_level_recovery')
    assert asyncio.run(ev_planner._shared_live_opportunity_decision(executor, 'shared_ev_profile_a', decision, 8))[0] == 'price_level'
    clock[0] = 100
    assert asyncio.run(ev_planner._shared_live_opportunity_decision(executor, 'shared_ev_profile_a', decision, 8))[0] is None
    clock[0] = 200
    assert asyncio.run(ev_planner._shared_live_opportunity_decision(executor, 'shared_ev_profile_a', decision, 8))[0] == 'price_level'


def test_active_full_rate_solar_is_not_evicted_during_boundary_initialization(monkeypatch):
    from test_ev_price_level_ownership import _FakeHass, _FakeConfigEntry
    hass, entry = _FakeHass(states={'sensor.connected_vehicle': 'tank'}), _FakeConfigEntry()
    entry.options = {'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Other', 'shared_loadpoint_profile_b_state': 'other'}
    hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc)
    executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
    executor._get_settings = lambda: {'opportunity_price_cents': 10}
    monkeypatch.setattr(ev_planner, '_build_dynamic_charging_params', lambda *a, **k: {
        'vehicle_id': 'generic_ev', 'active_logical_vehicle_id': 'shared_ev_profile_a'})
    candidate = {'eligible': True, 'capacity_kw': 8, 'max_kw': 7, 'min_kw': 1.4,
        'params': {'sustained_surplus_minutes': 3, 'stop_delay_minutes': 3},
        'selection_changed': hass.states.get('sensor.connected_vehicle').last_changed}
    monkeypatch.setattr(actions, '_evaluate_shared_solar_candidate', AsyncMock(return_value=candidate))
    actions._dynamic_ev_state['entry-1'] = {'generic_ev': {'active': True, 'current_amps': 32,
        'active_profile_id': 'shared_ev_profile_a', 'params': {'owner_mode': 'solar_surplus'}}}
    try:
        choice, _ = asyncio.run(ev_planner._shared_live_opportunity_decision(
            executor, 'shared_ev_profile_a', (True, 'cheap', 'price_level_recovery'), 8))
        assert choice == 'solar_surplus'
        candidate['capacity_kw'] = 6.9
        choice, _ = asyncio.run(ev_planner._shared_live_opportunity_decision(
            executor, 'shared_ev_profile_a', (True, 'cheap', 'price_level_recovery'), 8))
        assert choice == 'solar_surplus'
    finally:
        actions._dynamic_ev_state.clear()


def test_unowned_solar_dip_does_not_trigger_graceful_takeover(monkeypatch):
    from test_ev_price_level_ownership import _FakeHass, _FakeConfigEntry
    hass, entry = _FakeHass(states={'sensor.connected_vehicle': 'tank'}), _FakeConfigEntry()
    entry.options = {'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Other', 'shared_loadpoint_profile_b_state': 'other'}
    hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc)
    executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
    executor._get_settings = lambda: {'opportunity_price_cents': 10}
    monkeypatch.setattr(ev_planner, '_build_dynamic_charging_params', lambda *a, **k: {
        'vehicle_id': 'generic_ev', 'active_logical_vehicle_id': 'shared_ev_profile_a'})
    candidate = {'eligible': True, 'capacity_kw': 8, 'max_kw': 7, 'min_kw': 1.4,
        'params': {'sustained_surplus_minutes': 0, 'stop_delay_minutes': 3},
        'selection_changed': hass.states.get('sensor.connected_vehicle').last_changed}
    monkeypatch.setattr(actions, '_evaluate_shared_solar_candidate', AsyncMock(return_value=candidate))
    actions._dynamic_ev_state['entry-1'] = {'generic_ev': {'active': True,
        'active_profile_id': 'shared_ev_profile_a', 'params': {'owner_mode': 'price_level_recovery'}}}
    try:
        choice, _ = asyncio.run(ev_planner._shared_live_opportunity_decision(
            executor, 'shared_ev_profile_a', (True, 'recovery', 'price_level_recovery'), 20))
        assert choice == 'solar_surplus'
        candidate.update(eligible=False, capacity_kw=0)
        choice, _ = asyncio.run(ev_planner._shared_live_opportunity_decision(
            executor, 'shared_ev_profile_a', (True, 'recovery', 'price_level_recovery'), 20))
        assert choice == 'price_level'
    finally:
        actions._dynamic_ev_state.clear()


def test_solar_winner_publishes_before_attempting_price_handover(monkeypatch):
    from unittest.mock import Mock
    from test_ev_price_level_ownership import _FakeHass, _FakeConfigEntry
    hass, entry = _FakeHass(states={'sensor.connected_vehicle': 'tank'}), _FakeConfigEntry()
    entry.options = {'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Other', 'shared_loadpoint_profile_b_state': 'other'}
    monkeypatch.setattr(ev_planner.dt_util, 'now', lambda: datetime.now(timezone.utc))
    selector = hass.states.get('sensor.connected_vehicle')
    selector.last_changed = datetime.now(timezone.utc) - timedelta(seconds=5)
    data = hass.data['power_sync']['entry-1']
    data['automation_store']._data['solar_surplus_config'] = {'enabled': True}
    data['amber_prices'] = {'import_cents': 8}
    data['optimization_coordinator'] = SimpleNamespace(_enabled=True, _schedule_settings_reoptimization=Mock())
    executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
    executor.get_charging_decision = AsyncMock(return_value=(True, 'recovery', 'price_level_recovery'))
    executor._start_charging = AsyncMock()
    params = {'vehicle_id': 'generic_ev', 'active_logical_vehicle_id': 'shared_ev_profile_a',
              'owner_mode': 'solar_surplus', 'dynamic_mode': 'solar_surplus',
              'shared_loadpoint_binding': True, 'charger_type': 'generic',
              'min_charge_amps': 6, 'max_charge_amps': 32, 'voltage': 230, 'phases': 1}
    candidate = {'eligible': True, 'capacity_kw': 8, 'max_kw': 7.36, 'min_kw': 1.38,
                 'floor_soc': .5, 'parallel': False, 'selection_changed': selector.last_changed,
                 'params': params}
    monkeypatch.setattr(ev_planner, '_shared_live_opportunity_decision', AsyncMock(return_value=('solar_surplus', candidate)))
    monkeypatch.setattr(ev_planner, 'discover_all_tesla_vehicles', AsyncMock(return_value=[]))
    monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *a: False)
    start = AsyncMock(return_value=False)
    monkeypatch.setattr(actions, '_action_start_ev_charging_dynamic', start)
    actions._dynamic_ev_state['entry-1'] = {'generic_ev': {'active': True, 'active_profile_id': 'shared_ev_profile_a',
        'params': {'owner_mode': 'price_level_recovery'}}}
    try:
        asyncio.run(executor.evaluate_all_vehicles(8))
        request = data['_shared_opportunity_request']
        assert request['mode'] == 'solar_surplus'
        assert request['profile'] == 'shared_ev_profile_a'
        data['optimization_coordinator']._schedule_settings_reoptimization.assert_called_once()
        start.assert_not_awaited()
        executor._start_charging.assert_not_awaited()
        monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *a: True)
        asyncio.run(executor.evaluate_all_vehicles(8))
        assert start.await_count == 1
        assert start.await_args.args[2]['_opportunity_generation'] == request['generation'], {k:(request.get(k), data['_shared_opportunity_request'].get(k)) for k in request if request.get(k) != data['_shared_opportunity_request'].get(k)}
        data['_shared_loadpoint_handover'] = {'profile': 'shared_ev_profile_a', 'loadpoint': 'generic_ev',
            'owner_mode': 'solar_surplus', 'pending': {'settled_observation': {'power': 0}}, 'reaffirmed': True}
        actions._dynamic_ev_state['entry-1'].pop('generic_ev')
        asyncio.run(executor.evaluate_all_vehicles(8))
        assert start.await_count == 2
        assert start.await_args.args[2]['_opportunity_generation'] == request['generation'], {k:(request.get(k), data['_shared_opportunity_request'].get(k)) for k in request if request.get(k) != data['_shared_opportunity_request'].get(k)}
    finally:
        actions._dynamic_ev_state.clear()


def test_opportunity_revalidates_price_policy_before_controller_start(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *a: True)
        executor = SimpleNamespace(config_entry=entry,
            get_charging_decision=AsyncMock(return_value=(False, 'unplugged', '')))
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_opportunity',
                  '_opportunity_generation': 'generation', 'notify_on_start': False}
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, params)
        assert not actions._dynamic_ev_state.get(entry.entry_id, {}).get('generic_ev')
        hass.services.async_call.assert_not_awaited()
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_opportunity_rechecks_after_solar_soc_await(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store()
        valid = [True]
        monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *a: valid[0])
        async def check_soc(*args):
            valid[0] = False
            return None
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', check_soc)
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'solar_surplus', 'owner_mode': 'solar_surplus',
                  '_opportunity_generation': object(), 'notify_on_start': False}
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, params)
        assert not actions._dynamic_ev_state.get(entry.entry_id, {}).get('generic_ev')
        hass.services.async_call.assert_not_awaited()
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_smart_taking_price_session_settles_outgoing_executor(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params

    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_opportunity',
                  'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        state = executor._get_or_create_vehicle_state('shared_ev_profile_a')
        state.charging_mode = 'price_level_opportunity'
        state.is_charging = True
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        ev_planner._bind_shared_executor_runtime(executor, state, 'shared_ev_profile_a', 'price_level')
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        incoming = {**params, 'owner_mode': 'smart_schedule', 'allow_ownership_takeover': True}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert runtime.get('pending_stop')
        states['sensor.shared_ev_power'] = SimpleNamespace(
            state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not state.is_charging
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]['owner_mode'] == 'smart_schedule'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


@pytest.mark.parametrize('incoming_mode,incoming_owner', [
    ('battery_target', 'smart_schedule'),
    ('solar_surplus', 'smart_schedule_solar_surplus'),
])
def test_smart_takeover_waits_when_enabled_optimizer_has_no_matching_adoption(monkeypatch, incoming_mode, incoming_owner):
    from test_shared_loadpoint_action_guard import _generic_params

    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store()
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_opportunity',
                  'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        data['optimization_coordinator'] = SimpleNamespace(_enabled=True)
        incoming = {**params, 'dynamic_mode': incoming_mode,
                    'owner_mode': incoming_owner, 'allow_ownership_takeover': True}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert not runtime.get('pending_stop')
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]['owner_mode'] == 'price_level_opportunity'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_real_solar_policy_optimizer_and_fenced_price_handover(monkeypatch, tmp_path):
    from test_decision_diagnostics_writer import load_writer
    import json
    import importlib
    from test_ev_load_profile_bucketing import _extract_coordinator_method
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        selector = hass.states.get('sensor.connected_vehicle')
        selector.last_changed = datetime.now(timezone.utc) - timedelta(minutes=1)
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        data = hass.data['power_sync'][entry.entry_id]
        store = Store()
        store._data.update({'solar_surplus_config': {'enabled': True, 'min_battery_soc': 50,
            'sustained_surplus_minutes': 0, 'stop_delay_minutes': 0, 'max_export_price_cents': 20},
            'price_level_charging': {'enabled': True, 'opportunity_price_cents': 10},
            'vehicle_charging_configs': [{'vehicle_id': 'shared_ev_profile_a', 'charger_type': 'generic',
                'solar_charging_enabled': True, 'max_amps': 8, 'min_amps': 6, 'voltage': 230, 'phases': 1}]})
        data.update(automation_store=store, amber_prices={'import_cents': 8})
        outgoing = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
            'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_recovery',
            'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, outgoing)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        executor._get_home_battery_soc = AsyncMock(return_value=90)
        executor._get_ev_soc = AsyncMock(return_value=14)
        monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value='home'))
        executor.apply_preserve_home_battery = AsyncMock()
        price_state = executor._get_or_create_vehicle_state('shared_ev_profile_a')
        price_state.is_charging = True
        ev_planner._bind_shared_executor_runtime(executor, price_state, 'shared_ev_profile_a', 'price_level')
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        monkeypatch.setattr(ev_planner, 'discover_all_tesla_vehicles', AsyncMock(return_value=[]))
        monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(ev_planner.dt_util, 'now', lambda: now)
        live = {'battery_soc': 90, 'solar_power': 7000, 'grid_power': -5000,
                'battery_power': 0, 'load_power': 2000}
        monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value=live))
        ev_power = {'value': 2.0}
        async def observed(*a, **k): return ev_power['value'], True
        monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', observed)
        coordinator = SimpleNamespace(hass=hass, config_entry=entry, _enabled=True,
            _schedule_settings_reoptimization=lambda: None, _config=SimpleNamespace(interval_minutes=60),
            _last_planned_ev_load_forecast_w=None, _last_effective_ev_load_forecast_w=None)
        data['optimization_coordinator'] = coordinator
        def begin(active):
            actions._begin_automated_shared_loadpoint_cycle(hass, entry)
            data['_shared_loadpoint_cycle_context'] = {'binding_id': 'generic_ev',
                'active_profile_id': 'shared_ev_profile_a', 'physical_active': active}
        writer = load_writer().AsyncDecisionWriter(tmp_path)
        writer.start()
        data['decision_diagnostics'] = writer
        begin(True)
        await executor.evaluate_all_vehicles(8)
        request = data['_shared_opportunity_request']
        assert request['mode'] == 'solar_surplus' and not runtime.get('pending_stop')
        await writer.queue.join()
        events = [json.loads(line) for path in tmp_path.glob('ev-*.jsonl') for line in path.read_text().splitlines()]
        decision_event = next(event for event in events if event['event'] == 'shared_opportunity_decision')
        assert decision_event['source'] == 'solar_surplus'
        assert decision_event['opportunity_generation'] == request['generation']
        assert decision_event['solar_surplus_kw'] == pytest.approx(6.5)
        timestamps = [now + timedelta(hours=i) for i in range(8)]
        plans = _extract_coordinator_method('_merge_shared_opportunity')(coordinator, None, timestamps)
        coordinator._pending_ev_charge_plan = plans
        optimizer = importlib.import_module('power_sync.optimization.battery_optimizer').BatteryOptimizer(
            capacity_wh=40000, max_charge_w=14700, max_discharge_w=10000,
            max_grid_import_w=5000, backup_reserve=.05, interval_minutes=60, horizon_hours=8)
        result = optimizer.optimize(import_prices=[.08]*8, export_prices=[.05]*8,
            solar_forecast=[6.] + [0.]*7, load_forecast=[.5]*8, current_soc=1.,
            schedule_timestamps=timestamps, allow_grid_charge=False, ev_plan=plans)
        _extract_coordinator_method('_adopt_solved_ev_series')(coordinator, result)
        await writer.queue.join()
        events = [json.loads(line) for path in tmp_path.glob('ev-*.jsonl') for line in path.read_text().splitlines()]
        adopted_event = next(event for event in events if event['event'] == 'shared_opportunity_adoption')
        assert adopted_event['opportunity_generation'] == request['generation']
        assert adopted_event['success'] is True and adopted_event['planned_ev_kw'] > 0
        await writer.close()
        coordinator._current_schedule = result.schedule
        coordinator._get_current_action = lambda: result.schedule.actions[0]
        begin(True)
        await executor.evaluate_all_vehicles(8)
        assert runtime.get('pending_stop')
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'},
            last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        ev_power['value'] = 0
        live['grid_power'] = -7000
        begin(False)
        await executor.evaluate_all_vehicles(8)
        solar = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        assert solar['params']['owner_mode'] == 'solar_surplus'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_real_price_policy_optimizer_and_fenced_solar_handover(monkeypatch):
    import importlib
    from test_ev_load_profile_bucketing import _extract_coordinator_method
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc) - timedelta(minutes=1)
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        data = hass.data['power_sync'][entry.entry_id]
        store = Store()
        store._data.update({'solar_surplus_config': {'enabled': True, 'min_battery_soc': 50,
            'sustained_surplus_minutes': 0, 'stop_delay_minutes': 0, 'max_export_price_cents': 20},
            'price_level_charging': {'enabled': True, 'opportunity_price_cents': 10},
            'vehicle_charging_configs': [{'vehicle_id': 'shared_ev_profile_a', 'charger_type': 'generic',
                'solar_charging_enabled': True, 'max_amps': 32, 'min_amps': 6, 'voltage': 230, 'phases': 1}]})
        data.update(automation_store=store, amber_prices={'import_cents': 8})
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        outgoing = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
            'dynamic_mode': 'solar_surplus', 'owner_mode': 'solar_surplus', 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, outgoing)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        runtime.update(current_amps=6, target_amps=6, charging_started=True)
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        executor._get_home_battery_soc = AsyncMock(return_value=90)
        executor._get_ev_soc = AsyncMock(return_value=14)
        executor.apply_preserve_home_battery = AsyncMock()
        monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value='home'))
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        monkeypatch.setattr(ev_planner, 'discover_all_tesla_vehicles', AsyncMock(return_value=[]))
        monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_is_vehicle_charge_complete', AsyncMock(return_value=False))
        monkeypatch.setattr(actions, '_wait_for_generic_physical_start', AsyncMock(return_value=(True, 'controlled readback')))
        monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(ev_planner.dt_util, 'now', lambda: now)
        live = {'battery_soc': 90, 'solar_power': 4000, 'grid_power': -1000,
                'battery_power': 0, 'load_power': 2000}
        monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value=live))
        ev_power = {'value': 2.0}
        async def observed(*a, **k): return ev_power['value'], True
        monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', observed)
        coordinator = SimpleNamespace(hass=hass, config_entry=entry, _enabled=True,
            _schedule_settings_reoptimization=lambda: None, _config=SimpleNamespace(interval_minutes=60),
            _last_planned_ev_load_forecast_w=None, _last_effective_ev_load_forecast_w=None)
        data['optimization_coordinator'] = coordinator
        def begin(active):
            actions._begin_automated_shared_loadpoint_cycle(hass, entry)
            data['_shared_loadpoint_cycle_context'] = {'binding_id': 'generic_ev',
                'active_profile_id': 'shared_ev_profile_a', 'physical_active': active}
        begin(True)
        await executor.evaluate_all_vehicles(8)
        request = data['_shared_opportunity_request']
        assert request['mode'] == 'price_level_recovery' and not runtime.get('pending_stop')
        timestamps = [now + timedelta(hours=i) for i in range(8)]
        plans = _extract_coordinator_method('_merge_shared_opportunity')(coordinator, None, timestamps)
        coordinator._pending_ev_charge_plan = plans
        optimizer = importlib.import_module('power_sync.optimization.battery_optimizer').BatteryOptimizer(
            capacity_wh=40000, max_charge_w=14700, max_discharge_w=10000,
            max_grid_import_w=10000, backup_reserve=.05, interval_minutes=60, horizon_hours=8)
        result = optimizer.optimize(import_prices=[.08]*8, export_prices=[.05]*8,
            solar_forecast=[3.] + [0.]*7, load_forecast=[.5]*8, current_soc=1.,
            schedule_timestamps=timestamps, allow_grid_charge=False, ev_plan=plans)
        _extract_coordinator_method('_adopt_solved_ev_series')(coordinator, result)
        coordinator._current_schedule = result.schedule
        coordinator._get_current_action = lambda: result.schedule.actions[0]
        begin(True)
        await executor.evaluate_all_vehicles(8)
        assert runtime.get('pending_stop')
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'},
            last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        ev_power['value'] = 0
        live['grid_power'] = -3000
        begin(False)
        await executor.evaluate_all_vehicles(8)
        price = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        assert price['params']['owner_mode'] == 'price_level_recovery'
        price['params']['_opportunity_generation'] = request['generation']
        prior_params = price['params']
        # Existing grid-capable charging must not be torn down when the
        # tariff turns negative; PV/grid sourcing remains with other controls.
        data['amber_prices']['import_cents'] = -5
        begin(True)
        await executor.evaluate_all_vehicles(-5)
        assert actions._dynamic_ev_state[entry.entry_id]['generic_ev'] is price
        assert price['active'] and not price.get('pending_stop')
        assert '_opportunity_generation' not in price['params']
        assert prior_params['_opportunity_generation'] == request['generation']
        assert price['params'] is not prior_params
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_evac_positive_write_guard_rechecks_opportunity(monkeypatch):
    from test_shared_pause_evac_behavior import setup
    hass, entry, store, physical, params, runtime, _lease = setup('sigenergy')
    params['_opportunity_generation'] = 'adopted-generation'
    valid = [True]
    monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *args: valid[0])
    guard = actions._shared_positive_write_guard(hass, entry, params)
    assert guard()
    valid[0] = False
    assert not guard()
    actions._dynamic_ev_state.clear()


def test_evac_solar_to_price_uses_adopted_solve_and_confirmed_stop(monkeypatch):
    import importlib
    from test_ev_load_profile_bucketing import _extract_coordinator_method
    from test_shared_pause_evac_behavior import setup, FakeEvac
    async def scenario():
        hass, entry, store, physical, params, runtime, _lease = setup('sigenergy')
        hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc) - timedelta(minutes=1)
        store._data.update({'solar_surplus_config': {'enabled': True, 'min_battery_soc': 50,
            'sustained_surplus_minutes': 0, 'stop_delay_minutes': 0, 'max_export_price_cents': 20},
            'price_level_charging': {'enabled': True, 'opportunity_price_cents': 10},
            'vehicle_charging_configs': [{'vehicle_id': 'shared_ev_profile_a', 'charger_type': 'sigenergy',
                'solar_charging_enabled': True, 'max_amps': 32, 'min_amps': 6, 'voltage': 230, 'phases': 1}]})
        runtime.update(charging_started=True, current_amps=6, target_amps=6)
        data = hass.data['power_sync'][entry.entry_id]
        data['amber_prices'] = {'import_cents': 8}
        controller = FakeEvac()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        executor._get_home_battery_soc = AsyncMock(return_value=90)
        executor._get_ev_soc = AsyncMock(return_value=14)
        executor.apply_preserve_home_battery = AsyncMock()
        monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value='home'))
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        monkeypatch.setattr(ev_planner, 'discover_all_tesla_vehicles', AsyncMock(return_value=[]))
        monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        monkeypatch.setattr(actions, '_is_vehicle_charge_complete', AsyncMock(return_value=False))
        monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
        monkeypatch.setattr(actions, '_read_sigenergy_charger_power_kw', AsyncMock(return_value=2.0))
        monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', AsyncMock(return_value=(2.0, True)))
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(ev_planner.dt_util, 'now', lambda: now)
        monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value={
            'battery_soc': 90, 'solar_power': 4000, 'grid_power': -1000, 'battery_power': 0, 'load_power': 2000}))
        coordinator = SimpleNamespace(hass=hass, config_entry=entry, _enabled=True,
            _schedule_settings_reoptimization=lambda: None, _config=SimpleNamespace(interval_minutes=60),
            _last_planned_ev_load_forecast_w=None, _last_effective_ev_load_forecast_w=None)
        data['optimization_coordinator'] = coordinator
        def begin(active):
            actions._begin_automated_shared_loadpoint_cycle(hass, entry)
            data['_shared_loadpoint_cycle_context'] = {'binding_id': physical,
                'active_profile_id': 'shared_ev_profile_a', 'physical_active': active}
        begin(True)
        await executor.evaluate_all_vehicles(8)
        assert data['_shared_opportunity_request']['mode'] == 'price_level_recovery'
        assert not runtime.get('pending_stop')
        timestamps = [now + timedelta(hours=i) for i in range(8)]
        plans = _extract_coordinator_method('_merge_shared_opportunity')(coordinator, None, timestamps)
        coordinator._pending_ev_charge_plan = plans
        optimizer = importlib.import_module('power_sync.optimization.battery_optimizer').BatteryOptimizer(
            capacity_wh=40000, max_charge_w=14700, max_discharge_w=10000,
            max_grid_import_w=10000, backup_reserve=.05, interval_minutes=60, horizon_hours=8)
        result = optimizer.optimize(import_prices=[.08]*8, export_prices=[.05]*8,
            solar_forecast=[3.] + [0.]*7, load_forecast=[.5]*8, current_soc=1.,
            schedule_timestamps=timestamps, allow_grid_charge=False, ev_plan=plans)
        _extract_coordinator_method('_adopt_solved_ev_series')(coordinator, result)
        coordinator._current_schedule = result.schedule
        coordinator._get_current_action = lambda: result.schedule.actions[0]
        begin(True)
        await executor.evaluate_all_vehicles(8)
        assert runtime.get('pending_stop')
        controller.stop_charging.assert_awaited_once()
        controller.start_charging.assert_not_awaited()
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert runtime.get('pending_stop')
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        begin(False)
        await executor.evaluate_all_vehicles(8)
        price_runtime = actions._dynamic_ev_state[entry.entry_id][physical]
        assert price_runtime['params']['owner_mode'] == 'price_level_recovery'
        controller.start_charging.assert_awaited_once()
        data['amber_prices']['import_cents'] = -5
        begin(True)
        await executor.evaluate_all_vehicles(-5)
        assert price_runtime['active'] and not price_runtime.get('pending_stop')
        monkeypatch.setattr(actions, '_shared_callback_authorized', lambda *args: True)
        assert actions._shared_positive_write_guard(hass, entry, {**price_runtime['params'], 'vehicle_id': physical})()
        assert await actions._set_vehicle_amps(hass, entry, physical, 8, price_runtime['params'])
        controller.set_charging_amps.assert_awaited()
        controller.stop_charging.assert_awaited_once()
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_evac_price_to_solar_uses_adopted_solve_and_confirmed_stop(monkeypatch):
    import importlib
    from test_ev_load_profile_bucketing import _extract_coordinator_method
    from test_shared_pause_evac_behavior import setup, FakeEvac
    async def scenario():
        hass, entry, store, physical, params, runtime, lease = setup('sigenergy')
        hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc) - timedelta(minutes=1)
        store._data.update({'solar_surplus_config': {'enabled': True, 'min_battery_soc': 50,
            'sustained_surplus_minutes': 0, 'stop_delay_minutes': 0, 'max_export_price_cents': 20},
            'price_level_charging': {'enabled': True, 'opportunity_price_cents': 10},
            'vehicle_charging_configs': [{'vehicle_id': 'shared_ev_profile_a', 'charger_type': 'sigenergy',
                'solar_charging_enabled': True, 'max_amps': 8, 'min_amps': 6, 'voltage': 230, 'phases': 1}]})
        params.update(owner_mode='price_level_recovery', dynamic_mode='battery_target')
        lease['owner_mode'] = 'price_level_recovery'
        runtime.update(charging_started=True, current_amps=6, target_amps=6)
        data = hass.data['power_sync'][entry.entry_id]
        data['amber_prices'] = {'import_cents': 8}
        controller = FakeEvac()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        executor._get_home_battery_soc = AsyncMock(return_value=90)
        executor._get_ev_soc = AsyncMock(return_value=14)
        executor.apply_preserve_home_battery = AsyncMock()
        price_state = executor._get_or_create_vehicle_state('shared_ev_profile_a')
        price_state.is_charging = True
        ev_planner._bind_shared_executor_runtime(executor, price_state, 'shared_ev_profile_a', 'price_level')
        monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value='home'))
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        monkeypatch.setattr(ev_planner, 'discover_all_tesla_vehicles', AsyncMock(return_value=[]))
        monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
        monkeypatch.setattr(actions, '_read_sigenergy_charger_power_kw', AsyncMock(return_value=2.0))
        monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', AsyncMock(return_value=(2.0, True)))
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(ev_planner.dt_util, 'now', lambda: now)
        monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value={
            'battery_soc': 90, 'solar_power': 7000, 'grid_power': -5000, 'battery_power': 0, 'load_power': 2000}))
        coordinator = SimpleNamespace(hass=hass, config_entry=entry, _enabled=True,
            _schedule_settings_reoptimization=lambda: None, _config=SimpleNamespace(interval_minutes=60),
            _last_planned_ev_load_forecast_w=None, _last_effective_ev_load_forecast_w=None)
        data['optimization_coordinator'] = coordinator
        def begin(active):
            actions._begin_automated_shared_loadpoint_cycle(hass, entry)
            data['_shared_loadpoint_cycle_context'] = {'binding_id': physical,
                'active_profile_id': 'shared_ev_profile_a', 'physical_active': active}
        begin(True)
        await executor.evaluate_all_vehicles(8)
        assert data['_shared_opportunity_request']['mode'] == 'solar_surplus'
        assert not runtime.get('pending_stop')
        timestamps = [now + timedelta(hours=i) for i in range(8)]
        plans = _extract_coordinator_method('_merge_shared_opportunity')(coordinator, None, timestamps)
        coordinator._pending_ev_charge_plan = plans
        optimizer = importlib.import_module('power_sync.optimization.battery_optimizer').BatteryOptimizer(
            capacity_wh=40000, max_charge_w=14700, max_discharge_w=10000,
            max_grid_import_w=5000, backup_reserve=.05, interval_minutes=60, horizon_hours=8)
        result = optimizer.optimize(import_prices=[.08]*8, export_prices=[.05]*8,
            solar_forecast=[6.] + [0.]*7, load_forecast=[.5]*8, current_soc=1.,
            schedule_timestamps=timestamps, allow_grid_charge=False, ev_plan=plans)
        _extract_coordinator_method('_adopt_solved_ev_series')(coordinator, result)
        coordinator._current_schedule = result.schedule
        coordinator._get_current_action = lambda: result.schedule.actions[0]
        begin(True)
        await executor.evaluate_all_vehicles(8)
        assert runtime.get('pending_stop')
        controller.stop_charging.assert_awaited_once()
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        begin(False)
        await executor.evaluate_all_vehicles(8)
        assert actions._dynamic_ev_state[entry.entry_id][physical]['params']['owner_mode'] == 'solar_surplus'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_solar_takeover_revalidates_arbitration_after_await(monkeypatch):
    hass, entry = _Hass(), _Entry()
    data = hass.data['power_sync'][entry.entry_id]
    data['amber_prices'] = {'import_cents': 8}
    data['_shared_opportunity_request'] = {'mode': 'solar_surplus', 'solar_arbitrated': True}
    executor = SimpleNamespace(config_entry=entry,
        get_charging_decision=AsyncMock(return_value=(True, 'cheap', 'price_level_opportunity')))
    monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
    monkeypatch.setattr(ev_planner, '_shared_live_opportunity_decision',
                        AsyncMock(return_value=('price_level', {})))
    monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *a: True)
    params = {'owner_mode': 'solar_surplus', 'active_logical_vehicle_id': 'shared_ev_profile_a',
              '_opportunity_generation': 'candidate'}
    assert not asyncio.run(actions._shared_opportunity_revalidate(hass, entry, 'generic_ev', params))


def test_idle_smart_yields_to_solar_even_when_price_mode_disabled(monkeypatch):
    from unittest.mock import Mock
    import importlib
    from test_ev_load_profile_bucketing import _extract_coordinator_method
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        monkeypatch.setattr(ev_planner.dt_util, 'now', lambda: datetime.now(timezone.utc))
        hass.states.async_all = lambda: []
        hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc) - timedelta(minutes=1)
        data = hass.data['power_sync'][entry.entry_id]
        store = Store()
        store._data.update({'solar_surplus_config': {'enabled': True, 'min_battery_soc': 50,
            'sustained_surplus_minutes': 0, 'stop_delay_minutes': 0, 'max_export_price_cents': 20},
            'price_level_charging': {'enabled': False},
            'vehicle_charging_configs': [{'vehicle_id': 'shared_ev_profile_a', 'charger_type': 'generic',
                'solar_charging_enabled': True, 'max_amps': 8, 'min_amps': 6, 'voltage': 230, 'phases': 1}]})
        data.update(automation_store=store, amber_prices={'import_cents': 8})
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        outgoing = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                    'dynamic_mode': 'solar_surplus', 'owner_mode': 'smart_schedule_solar_surplus', 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, outgoing)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        actions.record_smart_schedule_effective_authorization(entry, 'shared_ev_profile_a',
            allowed=False, source='waiting', hass=hass)
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
        monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value={
            'battery_soc': 90, 'solar_power': 7000, 'grid_power': -5000,
            'battery_power': 0, 'load_power': 2000}))
        monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', AsyncMock(return_value=(0.0, True)))
        coordinator = SimpleNamespace(hass=hass, config_entry=entry, _enabled=True,
            _schedule_settings_reoptimization=Mock(), _config=SimpleNamespace(interval_minutes=60),
            _last_planned_ev_load_forecast_w=None, _last_effective_ev_load_forecast_w=None)
        data['optimization_coordinator'] = coordinator
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        data['_shared_loadpoint_cycle_context'] = {'binding_id': 'generic_ev',
            'active_profile_id': 'shared_ev_profile_a', 'physical_active': False}
        await ev_planner._evaluate_solar_for_idle_smart(executor)
        assert data['_shared_opportunity_request']['mode'] == 'solar_surplus'
        assert not runtime.get('pending_stop')
        data['optimization_coordinator']._schedule_settings_reoptimization.assert_called_once()
        request = data['_shared_opportunity_request']
        now = datetime.now(timezone.utc)
        timestamps = [now + timedelta(hours=i) for i in range(8)]
        plans = _extract_coordinator_method('_merge_shared_opportunity')(coordinator, None, timestamps)
        coordinator._pending_ev_charge_plan = plans
        optimizer = importlib.import_module('power_sync.optimization.battery_optimizer').BatteryOptimizer(
            capacity_wh=40000, max_charge_w=14700, max_discharge_w=10000,
            max_grid_import_w=5000, backup_reserve=.05, interval_minutes=60, horizon_hours=8)
        result = optimizer.optimize(import_prices=[.08]*8, export_prices=[.05]*8,
            solar_forecast=[6.] + [0.]*7, load_forecast=[.5]*8, current_soc=1.,
            schedule_timestamps=timestamps, allow_grid_charge=False, ev_plan=plans)
        _extract_coordinator_method('_adopt_solved_ev_series')(coordinator, result)
        coordinator._current_schedule = result.schedule
        coordinator._get_current_action = lambda: result.schedule.actions[0]
        monkeypatch.setattr(actions, '_observe_shared_loadpoint_for_direct_lease',
                            AsyncMock(return_value=SimpleNamespace(fresh=True, charging=False)))
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        data['_shared_loadpoint_cycle_context'] = {'binding_id': 'generic_ev',
            'active_profile_id': 'shared_ev_profile_a', 'physical_active': False}
        await ev_planner._evaluate_solar_for_idle_smart(executor)
        assert actions._dynamic_ev_state[entry.entry_id]['generic_ev']['params']['owner_mode'] == 'solar_surplus'
        assert data['_shared_opportunity_request']['generation'] == request['generation']
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()
        actions._smart_schedule_effective_authorizations.clear()


def test_evac_idle_smart_exposes_solar_when_price_disabled(monkeypatch):
    from unittest.mock import Mock
    from test_shared_pause_evac_behavior import setup
    async def scenario():
        hass, entry, store, physical, params, runtime, lease = setup('sigenergy')
        params.update(owner_mode='smart_schedule_solar_surplus')
        lease['owner_mode'] = 'smart_schedule_solar_surplus'
        runtime['current_amps'] = 0
        hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc) - timedelta(minutes=1)
        store._data.update({'solar_surplus_config': {'enabled': True, 'min_battery_soc': 50,
            'sustained_surplus_minutes': 0, 'stop_delay_minutes': 0, 'max_export_price_cents': 20},
            'price_level_charging': {'enabled': False}, 'vehicle_charging_configs': [
                {'vehicle_id': 'shared_ev_profile_a', 'charger_type': 'sigenergy',
                 'solar_charging_enabled': True, 'max_amps': 8, 'min_amps': 6, 'voltage': 230, 'phases': 1}]})
        data = hass.data['power_sync'][entry.entry_id]
        data['amber_prices'] = {'import_cents': 8}
        data['optimization_coordinator'] = SimpleNamespace(_enabled=True, _schedule_settings_reoptimization=Mock())
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        monkeypatch.setattr(ev_planner.dt_util, 'now', lambda: datetime.now(timezone.utc))
        monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 5)
        monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value={
            'battery_soc': 90, 'solar_power': 7000, 'grid_power': -5000,
            'battery_power': 0, 'load_power': 2000}))
        monkeypatch.setattr(actions, '_get_observed_ev_power_reading_kw', AsyncMock(return_value=(0.0, True)))
        monkeypatch.setattr(actions, '_read_sigenergy_charger_power_kw', AsyncMock(return_value=0.0))
        actions.record_smart_schedule_effective_authorization(entry, 'shared_ev_profile_a',
            allowed=False, source='waiting', hass=hass)
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        data['_shared_loadpoint_cycle_context'] = {'binding_id': physical,
            'active_profile_id': 'shared_ev_profile_a', 'physical_active': False}
        await ev_planner._evaluate_solar_for_idle_smart(executor)
        assert data['_shared_opportunity_request']['mode'] == 'solar_surplus'
        assert not runtime.get('pending_stop')
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()
        actions._smart_schedule_effective_authorizations.clear()


@pytest.mark.parametrize('backend', ['generic', 'sigenergy'])
@pytest.mark.parametrize('free_price', [-5, 0])
def test_negative_grid_smart_handover_preserves_fresh_free_grid_authorization(monkeypatch, backend, free_price):
    hass, entry = _Hass(profile_a_soc='14'), _Entry()
    physical = 'generic_ev'
    if backend == 'sigenergy':
        entry.options = {**entry.options, 'generic_charger_enabled': False,
                         'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac'}
        physical = 'sigenergy_charger'
    selector = hass.states.get('sensor.connected_vehicle')
    selector.last_changed = datetime.now(timezone.utc) - timedelta(minutes=1)
    data = hass.data['power_sync'][entry.entry_id]
    data['amber_prices'] = {'import_cents': free_price}
    data['optimization_coordinator'] = SimpleNamespace(_enabled=True, _adopted_smart_handover={})
    params = {'vehicle_id': physical, 'active_logical_vehicle_id': 'shared_ev_profile_a',
              'owner_mode': 'smart_schedule', '_smart_handover_source': 'grid_free',
              'voltage': 230, 'phases': 1, 'min_charge_amps': 6, 'max_charge_amps': 32}
    actions.record_smart_schedule_effective_authorization(entry, 'shared_ev_profile_a',
        allowed=True, source='grid_free', hass=hass)
    monkeypatch.setattr(actions, '_optimizer_planned_ev_charge_kw', lambda *a, **k: 0.0)
    try:
        assert actions._shared_smart_handover_adopted(hass, entry, physical, params)
        data['amber_prices']['import_cents'] = 5
        assert not actions._shared_smart_handover_adopted(hass, entry, physical, params)
    finally:
        actions._smart_schedule_effective_authorizations.clear()


def test_new_smart_intent_blocks_price_after_outgoing_settlement(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc)
        actions.record_smart_schedule_effective_authorization(entry, 'shared_ev_profile_a',
            allowed=True, source='grid_offpeak', hass=hass)
        incoming = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'dynamic_mode': 'battery_target',
                    'owner_mode': 'price_level_opportunity', 'allow_ownership_takeover': True}
        hass.services.async_call.reset_mock()
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        hass.services.async_call.assert_not_awaited()
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()
        actions._smart_schedule_effective_authorizations.clear()


def test_live_smart_solar_intent_cannot_be_evicted_by_price(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store()
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        outgoing = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'dynamic_mode': 'solar_surplus',
                    'owner_mode': 'smart_schedule_solar_surplus', 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, outgoing)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc)
        actions.record_smart_schedule_effective_authorization(entry, 'shared_ev_profile_a',
            allowed=True, source='solar_surplus', hass=hass)
        incoming = {**outgoing, 'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_opportunity',
                    'allow_ownership_takeover': True}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='price_level', reason='', source='price_level_opportunity')
        hass.services.async_call.reset_mock()
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert not runtime.get('pending_stop')
        hass.services.async_call.assert_not_awaited()
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()
        actions._smart_schedule_effective_authorizations.clear()


@pytest.mark.parametrize('outgoing_owner', ['solar_surplus', 'smart_schedule_solar_surplus'])
def test_idle_solar_monitor_yields_without_gratuitous_stop(monkeypatch, outgoing_owner):
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store()
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        outgoing = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                    'dynamic_mode': 'solar_surplus', 'owner_mode': outgoing_owner, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, outgoing)
        smart_state = None
        if outgoing_owner.startswith('smart_schedule'):
            executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
            smart_state = executor.get_state('shared_ev_profile_a')
            smart_state.is_charging = True
            monkeypatch.setattr(ev_planner, 'get_auto_schedule_executor', lambda: executor)
            ev_planner._bind_shared_executor_runtime(executor, smart_state, 'shared_ev_profile_a', 'smart_schedule')
            hass.states.get('sensor.connected_vehicle').last_changed = datetime.now(timezone.utc)
            actions.record_smart_schedule_effective_authorization(entry, 'shared_ev_profile_a',
                allowed=False, source='waiting', hass=hass)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        assert runtime['current_amps'] == 0
        monkeypatch.setattr(actions, '_observe_shared_loadpoint_for_direct_lease',
                            AsyncMock(return_value=SimpleNamespace(fresh=True, charging=False)))
        monkeypatch.setattr(actions, '_shared_opportunity_revalidate', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *a: True)
        monkeypatch.setattr(actions, '_is_vehicle_charge_complete', AsyncMock(return_value=False))
        monkeypatch.setattr(actions, '_wait_for_generic_physical_start', AsyncMock(return_value=(True, 'controlled')))
        incoming = {**outgoing, 'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_opportunity',
                    'allow_ownership_takeover': True, '_opportunity_generation': 'candidate'}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='price_level', reason='', source='price_level_opportunity')
        hass.services.async_call.reset_mock()
        assert await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        if smart_state is not None:
            assert not smart_state.is_charging
        assert not any(c.args[:2] == ('switch', 'turn_off') for c in hass.services.async_call.await_args_list)
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()
        actions._smart_schedule_effective_authorizations.clear()


def test_adopted_solar_can_fence_price_runtime(monkeypatch):
    from test_shared_loadpoint_action_guard import _generic_params
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store()
        outgoing = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                    'dynamic_mode': 'battery_target', 'owner_mode': 'price_level_opportunity',
                    'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, outgoing)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        data['optimization_coordinator'] = SimpleNamespace(_enabled=True)
        monkeypatch.setattr(actions, '_shared_opportunity_revalidate', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_shared_opportunity_handover_adopted', lambda *a: True)
        monkeypatch.setattr(actions, '_dynamic_ev_full_soc_reason', AsyncMock(return_value=None))
        incoming = {**outgoing, 'dynamic_mode': 'solar_surplus', 'owner_mode': 'solar_surplus',
                    'allow_ownership_takeover': True, '_opportunity_generation': 'adopted'}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='solar_surplus', reason='', source='solar_surplus')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert runtime.get('pending_stop')
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


@pytest.mark.parametrize('outgoing_mode', ['price_level_opportunity', 'solar_surplus'])
def test_smart_takeover_uses_matching_adopted_plan(monkeypatch, outgoing_mode):
    from test_shared_loadpoint_action_guard import _generic_params

    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = Store()
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'solar_surplus' if outgoing_mode == 'solar_surplus' else 'battery_target',
                  'owner_mode': outgoing_mode,
                  'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        runtime = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        if outgoing_mode == 'solar_surplus':
            runtime.update(current_amps=8, target_amps=8, charging_started=True)
            original_get = hass.states.get
            power_state = SimpleNamespace(state='1800', attributes={'unit_of_measurement': 'W'},
                                          last_reported=datetime.now(timezone.utc))
            hass.states.get = lambda key: power_state if key == 'sensor.shared_ev_power' else original_get(key)
        plan = object()
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(actions.dt_util, 'now', lambda: now, raising=False)
        action = SimpleNamespace()
        data['optimization_coordinator'] = SimpleNamespace(
            _enabled=True, _current_schedule=SimpleNamespace(last_updated=now, actions=[action]),
            _last_ev_charge_schedule_updated=now, _get_current_action=lambda: action,
            _last_ev_charge_by_vehicle_w={'shared_ev_profile_a': [2000]},
            _adopted_smart_handover={'shared_ev_profile_a': {
                'plan': plan, 'source': 'grid_offpeak', 'schedule_updated': now}})
        incoming = {**params, 'dynamic_mode': 'battery_target', 'owner_mode': 'smart_schedule', 'allow_ownership_takeover': True,
                    '_smart_handover_plan_id': id(plan), '_smart_handover_source': 'grid_offpeak'}
        from power_sync.automations.shared_loadpoint import resolve_shared_loadpoint_command
        resolved = resolve_shared_loadpoint_command(hass, entry, 'shared_ev_profile_a', incoming)
        assert actions._shared_smart_handover_adopted(hass, entry, 'generic_ev', resolved)
        assert not actions._shared_smart_handover_adopted(
            hass, entry, 'generic_ev', {**resolved, '_smart_handover_source': 'solar_surplus'})
        assert not actions._shared_smart_handover_adopted(
            hass, entry, 'generic_ev', {**resolved, '_smart_handover_plan_id': id(object())})
        data['optimization_coordinator']._last_ev_charge_by_vehicle_w['shared_ev_profile_a'] = [0]
        assert not actions._shared_smart_handover_adopted(hass, entry, 'generic_ev', resolved)
        data['optimization_coordinator']._last_ev_charge_by_vehicle_w['shared_ev_profile_a'] = [2000]
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert runtime.get('pending_stop')
        states = {}
        original = hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        states['sensor.shared_ev_power'] = SimpleNamespace(
            state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        data['optimization_coordinator']._adopted_smart_handover = {}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert 'generic_ev' not in actions._dynamic_ev_state.get(entry.entry_id, {})
        data['optimization_coordinator']._adopted_smart_handover = {'shared_ev_profile_a': {
            'plan': plan, 'source': 'grid_offpeak', 'schedule_updated': now}}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert actions._dynamic_ev_state[entry.entry_id]['generic_ev']['params']['owner_mode'] == 'smart_schedule'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_smart_taking_price_evac_fences_stop(monkeypatch):
    from test_shared_pause_evac_behavior import FakeEvac, setup

    async def scenario():
        hass, entry, _, physical, params, runtime, lease = setup('sigenergy')
        params.update(owner_mode='price_level_opportunity', dynamic_mode='battery_target')
        lease['owner_mode'] = 'price_level_opportunity'
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        state = executor._get_or_create_vehicle_state('shared_ev_profile_a')
        state.is_charging = True
        state.charging_mode = 'price_level_opportunity'
        monkeypatch.setattr(ev_planner, 'get_price_level_executor', lambda: executor)
        ev_planner._bind_shared_executor_runtime(executor, state, 'shared_ev_profile_a', 'price_level')
        controller = FakeEvac()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        incoming = {**params, 'vehicle_id': 'shared_ev_profile_a',
                    'owner_mode': 'smart_schedule', 'allow_ownership_takeover': True}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert not await asyncio.wait_for(actions._action_start_ev_charging_dynamic(hass, entry, incoming), 2)
        assert runtime.get('pending_stop')
        controller.stop_charging.assert_awaited_once_with()
        assert state.is_charging
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not state.is_charging
        assert physical not in actions._dynamic_ev_state.get(entry.entry_id, {})
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


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

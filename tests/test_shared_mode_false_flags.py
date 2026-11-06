"""Shared mode stops must not depend solely on executor flags."""
import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest
from test_ev_price_level_ownership import _FakeHass, _FakeConfigEntry, ev_planner


@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
def test_price_level_false_flag_stops_matching_owner_on_price_denial(monkeypatch, backend, physical):
    hass = _FakeHass(states={'sensor.connected_vehicle': 'tank'})
    entry = _FakeConfigEntry()
    entry.options = {
        'generic_charger_enabled': backend == 'generic',
        'sigenergy_charger_enabled': backend == 'sigenergy',
        'sigenergy_charger_type': 'evac',
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future',
    }
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    lease = ownership.acquire_shared_loadpoint_ownership(hass, entry, physical,
        active_profile_id='shared_ev_profile_a', owner_mode='price_level_opportunity')
    assert lease
    executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
    executor.get_charging_decision = AsyncMock(return_value=(False, 'Price too high', ''))
    executor._stop_charging = AsyncMock(return_value=False)
    executor.apply_preserve_home_battery = AsyncMock()
    asyncio.run(executor.evaluate_all_vehicles(40))
    executor._stop_charging.assert_awaited_once_with('Price too high', vehicle_vin='shared_ev_profile_a')


@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
def test_smart_schedule_target_false_flag_retains_pending_stop(monkeypatch, backend, physical):
    hass = _FakeHass(states={'sensor.connected_vehicle': 'tank'})
    entry = _FakeConfigEntry()
    entry.options = {
        'generic_charger_enabled': backend == 'generic',
        'sigenergy_charger_enabled': backend == 'sigenergy', 'sigenergy_charger_type': 'evac',
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future',
    }
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    assert ownership.acquire_shared_loadpoint_ownership(hass, entry, physical,
        active_profile_id='shared_ev_profile_a', owner_mode='smart_schedule')
    monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value='home'))
    monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
    executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
    executor._get_vehicle_soc = AsyncMock(return_value=80)
    executor._stop_charging = AsyncMock(return_value=False)
    settings = ev_planner.AutoScheduleSettings(enabled=True, vehicle_id='shared_ev_profile_a', target_soc=80)
    state = executor.get_state('shared_ev_profile_a')
    asyncio.run(executor._evaluate_vehicle('shared_ev_profile_a', settings, {}, None))
    executor._stop_charging.assert_awaited_once()
    assert state.last_decision == 'complete'
    assert 'stop unconfirmed' in state.last_decision_reason
    assert state.is_charging is False
    # Simulate the existing pending-stop finalizer removing the exact lease.
    ownership.get_ev_ownerships(hass, entry).pop(physical)
    executor._stop_charging.reset_mock()
    asyncio.run(executor._evaluate_vehicle('shared_ev_profile_a', settings, {}, None))
    executor._stop_charging.assert_not_awaited()
    assert state.last_decision == 'complete'
    assert 'stop unconfirmed' not in state.last_decision_reason


@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
def test_scheduled_false_flag_stops_matching_owner_outside_window(monkeypatch, backend, physical):
    hass = _FakeHass(states={'sensor.connected_vehicle': 'tank'})
    entry = _FakeConfigEntry()
    entry.options = {
        'generic_charger_enabled': backend == 'generic',
        'sigenergy_charger_enabled': backend == 'sigenergy', 'sigenergy_charger_type': 'evac',
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future',
    }
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    assert ownership.acquire_shared_loadpoint_ownership(hass, entry, physical,
        active_profile_id='shared_ev_profile_a', owner_mode='scheduled')
    executor = ev_planner.ScheduledChargingExecutor(hass, entry)
    executor.get_charging_decision = AsyncMock(return_value=(False, 'Outside schedule', ''))
    executor._stop_charging = AsyncMock(return_value=False)
    executor.apply_preserve_home_battery = AsyncMock()
    asyncio.run(executor.evaluate(40))
    executor._stop_charging.assert_awaited_once_with('Outside schedule')


@pytest.mark.parametrize('selection', ['unknown', 'future'])
def test_scheduled_does_not_stop_unselected_owner(monkeypatch, selection):
    hass = _FakeHass(states={'sensor.connected_vehicle': selection})
    entry = _FakeConfigEntry()
    entry.options = {
        'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future',
    }
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    assert ownership.acquire_shared_loadpoint_ownership(hass, entry, 'generic_ev',
        active_profile_id='shared_ev_profile_a', owner_mode='scheduled')
    executor = ev_planner.ScheduledChargingExecutor(hass, entry)
    executor.get_charging_decision = AsyncMock(return_value=(False, 'Outside schedule', ''))
    executor._stop_charging = AsyncMock(return_value=False)
    executor.apply_preserve_home_battery = AsyncMock()
    asyncio.run(executor.evaluate(40))
    executor._stop_charging.assert_not_awaited()


def test_disabled_smart_schedule_false_flag_stops_matching_owner(monkeypatch):
    hass = _FakeHass(states={'sensor.connected_vehicle': 'tank'})
    entry = _FakeConfigEntry()
    entry.options = {
        'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future',
    }
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    assert ownership.acquire_shared_loadpoint_ownership(hass, entry, 'generic_ev',
        active_profile_id='shared_ev_profile_a', owner_mode='smart_schedule')
    monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value='home'))
    monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
    executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
    executor._settings['shared_ev_profile_a'] = ev_planner.AutoScheduleSettings(enabled=False, vehicle_id='shared_ev_profile_a')
    executor._stop_charging = AsyncMock(return_value=False)
    executor._save_cached_soc_if_needed = AsyncMock()
    asyncio.run(executor.evaluate({}))
    executor._stop_charging.assert_awaited_once()


@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
@pytest.mark.parametrize('owner,profile,selected,expected', [
    ('price_level_opportunity', 'shared_ev_profile_a', 'tank', True),
    ('scheduled', 'shared_ev_profile_a', 'tank', False),
    ('price_level_opportunity', 'shared_ev_profile_b', 'tank', False),
    ('price_level_opportunity', 'shared_ev_profile_a', 'unknown', False),
    (None, None, 'tank', False),
    ('external', 'shared_ev_profile_a', 'tank', False),
])
def test_matching_mode_uses_exact_selected_owner(backend, physical, owner, profile, selected, expected):
    hass = _FakeHass(states={'sensor.connected_vehicle': selected})
    entry = _FakeConfigEntry()
    entry.options = {
        'generic_charger_enabled': backend == 'generic',
        'sigenergy_charger_enabled': backend == 'sigenergy', 'sigenergy_charger_type': 'evac',
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future',
    }
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    if owner == 'external':
        ownership.claim_ev_ownership(hass, entry, physical, owner='external', owner_mode='price_level', extra={'active_profile_id': profile})
    elif owner:
        assert ownership.acquire_shared_loadpoint_ownership(hass, entry, physical, active_profile_id=profile, owner_mode=owner)
    assert ev_planner._matching_shared_mode_owner(hass, entry, 'shared_ev_profile_a', 'price_level') is expected


@pytest.mark.parametrize('location,plugged', [('away', True), ('home', False)])
def test_disabled_smart_true_flag_preserves_original_stop_and_restore(monkeypatch, location, plugged):
    hass = _FakeHass(states={'sensor.connected_vehicle': 'tank'})
    entry = _FakeConfigEntry()
    entry.options = {'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future'}
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    assert ownership.acquire_shared_loadpoint_ownership(hass, entry, 'generic_ev',
        active_profile_id='shared_ev_profile_a', owner_mode='smart_schedule')
    monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value=location))
    monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=plugged))
    executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
    executor._settings['shared_ev_profile_a'] = ev_planner.AutoScheduleSettings(enabled=False, vehicle_id='shared_ev_profile_a')
    state = executor.get_state('shared_ev_profile_a')
    state.is_charging = True
    state.curtailment_override_active = True
    executor._stop_charging = AsyncMock(return_value=False)
    executor._restore_curtailment = AsyncMock()
    executor._save_cached_soc_if_needed = AsyncMock()
    asyncio.run(executor.evaluate({}))
    executor._stop_charging.assert_awaited_once()
    executor._restore_curtailment.assert_awaited_once()


@pytest.mark.parametrize('location,plugged', [('away', True), ('home', False)])
def test_disabled_smart_false_flag_does_not_stop_away_or_unplugged(monkeypatch, location, plugged):
    hass = _FakeHass(states={'sensor.connected_vehicle': 'tank'})
    entry = _FakeConfigEntry()
    entry.options = {'generic_charger_enabled': True,
        'shared_loadpoint_connected_vehicle_entity': 'sensor.connected_vehicle',
        'shared_loadpoint_profile_a_name': 'Tank', 'shared_loadpoint_profile_a_state': 'tank',
        'shared_loadpoint_profile_b_name': 'Future', 'shared_loadpoint_profile_b_state': 'future'}
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    lease = ownership.acquire_shared_loadpoint_ownership(hass, entry, 'generic_ev',
        active_profile_id='shared_ev_profile_a', owner_mode='smart_schedule')
    monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value=location))
    monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=plugged))
    executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
    executor._settings['shared_ev_profile_a'] = ev_planner.AutoScheduleSettings(enabled=False, vehicle_id='shared_ev_profile_a')
    executor._save_cached_soc_if_needed = AsyncMock()
    asyncio.run(executor.evaluate({}))
    assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is lease


@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
@pytest.mark.parametrize('mode', ['scheduled', 'price_level', 'smart_schedule'])
def test_lease_only_mode_stop_fences_until_observed(monkeypatch, backend, physical, mode):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from test_shared_loadpoint_action_guard import _Hass, _Entry
    from test_shared_stop_storage import Store
    actions = importlib.import_module('power_sync.automations.actions')
    ownership = importlib.import_module('power_sync.automations.ev_ownership')

    async def scenario():
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        entry.options = dict(entry.options)
        if backend == 'sigenergy':
            entry.options.update(generic_charger_enabled=False, sigenergy_charger_enabled=True,
                                 sigenergy_charger_type='evac', sigenergy_charger_host='charger.invalid')
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        calls = []
        if backend == 'sigenergy':
            class Controller:
                async def connect(self): return True
                async def stop_charging(self):
                    assert self._shared_write_authorized()
                    calls.append('stop')
                    return True
                async def disconnect(self): pass
                _read_input_registers = AsyncMock(return_value=None)
            controller = Controller()
            monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        lease = ownership.acquire_shared_loadpoint_ownership(hass, entry, physical,
            active_profile_id='shared_ev_profile_a', owner_mode=mode)
        assert lease
        if mode == 'scheduled':
            executor = ev_planner.ScheduledChargingExecutor(hass, entry)
            executor.get_charging_decision = AsyncMock(return_value=(False, 'Outside schedule', ''))
            executor.apply_preserve_home_battery = AsyncMock()
            await executor.evaluate(40)
        elif mode == 'price_level':
            executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
            executor.get_charging_decision = AsyncMock(return_value=(False, 'Price too high', ''))
            executor.apply_preserve_home_battery = AsyncMock()
            await executor.evaluate_all_vehicles(40)
        else:
            monkeypatch.setattr(ev_planner, 'get_ev_location', AsyncMock(return_value='home'))
            monkeypatch.setattr(ev_planner, 'is_ev_plugged_in', AsyncMock(return_value=True))
            executor = ev_planner.AutoScheduleExecutor(hass, entry, ev_planner.ChargingPlanner(hass, entry))
            executor._get_vehicle_soc = AsyncMock(return_value=80)
            settings = ev_planner.AutoScheduleSettings(enabled=True, vehicle_id='shared_ev_profile_a', target_soc=80)
            await executor._evaluate_vehicle('shared_ev_profile_a', settings, {}, None)
        assert (hass.services.async_call.await_count if backend == 'generic' else len(calls)) == 1
        if backend == 'generic':
            hass.services.async_call.assert_awaited_once_with(
                'switch', 'turn_off', {'entity_id': 'switch.shared_ev'}, blocking=True)
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        assert ownership.get_ev_ownership(hass, entry, physical)[1] is lease
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        if backend == 'generic':
            states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        else:
            controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, physical)
        assert ownership.get_ev_ownership(hass, entry, physical)[1] is None
        actions._dynamic_ev_state.clear()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['scheduled', 'price_level'])
@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
def test_false_flag_denial_does_not_touch_other_mode_lease(mode, backend, physical):
    from test_shared_loadpoint_action_guard import _Hass, _Entry
    actions = importlib.import_module('power_sync.automations.actions')
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    async def scenario():
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        entry.options = dict(entry.options)
        if backend == 'sigenergy':
            entry.options.update(generic_charger_enabled=False, sigenergy_charger_enabled=True,
                                 sigenergy_charger_type='evac')
        lease = ownership.acquire_shared_loadpoint_ownership(hass, entry, physical,
            active_profile_id='shared_ev_profile_a', owner_mode='smart_schedule')
        assert lease
        if mode == 'scheduled':
            executor = ev_planner.ScheduledChargingExecutor(hass, entry)
            executor.get_charging_decision = AsyncMock(return_value=(False, 'Outside schedule', ''))
            executor.apply_preserve_home_battery = AsyncMock()
            await executor.evaluate(40)
        else:
            executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
            executor.get_charging_decision = AsyncMock(return_value=(False, 'Price too high', ''))
            executor.apply_preserve_home_battery = AsyncMock()
            await executor.evaluate_all_vehicles(40)
        assert hass.services.async_call.await_count == 0
        assert not actions.is_shared_stop_fenced(hass, entry, physical)
        assert ownership.get_ev_ownership(hass, entry, physical)[1] is lease
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['replace', 'mutate', 'session'])
def test_lease_only_stop_rechecks_owner_after_wait(monkeypatch, change):
    from test_shared_loadpoint_action_guard import _Hass, _Entry
    actions = importlib.import_module('power_sync.automations.actions')
    ownership = importlib.import_module('power_sync.automations.ev_ownership')
    async def scenario():
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        lease = ownership.acquire_shared_loadpoint_ownership(hass, entry, 'generic_ev',
            active_profile_id='shared_ev_profile_a', owner_mode='scheduled')
        original = actions._action_stop_ev_charging
        async def changed_owner(*args):
            if change == 'replace':
                ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner='powersync',
                    owner_mode='smart_schedule', extra={'active_profile_id': 'shared_ev_profile_a'})
            elif change == 'mutate':
                lease['owner_mode'] = 'smart_schedule'
            else:
                lease['session_id'] = 'new-session'
            return await original(*args)
        monkeypatch.setattr(actions, '_action_stop_ev_charging', changed_owner)
        executor = ev_planner.ScheduledChargingExecutor(hass, entry)
        executor.get_charging_decision = AsyncMock(return_value=(False, 'Outside schedule', ''))
        executor.apply_preserve_home_battery = AsyncMock()
        await executor.evaluate(40)
        assert hass.services.async_call.await_count == 0
        assert not actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        current = ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]
        assert current['session_id'] == 'new-session' if change == 'session' else current['owner_mode'] == 'smart_schedule'
    asyncio.run(scenario())

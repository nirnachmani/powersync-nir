"""Regression for an asynchronous shared-charger mode handover."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


def test_shared_mode_decision_is_persisted(tmp_path):
    import importlib, json
    diagnostics = importlib.import_module('power_sync.decision_diagnostics')
    async def scenario():
        hass, entry = _Hass(), _Entry()
        writer = diagnostics.AsyncDecisionWriter(tmp_path)
        writer.start()
        hass.data['power_sync'][entry.entry_id]['decision_diagnostics'] = writer
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        await writer.close()
    asyncio.run(scenario())
    event = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert event['event'] == 'shared_policy_decision' and event['allowed'] is True
    assert event['owner_mode'] == 'smart_schedule' and event['profile'] == 'shared_ev_profile_a'
    assert event['source'] == 'grid'


def test_smart_schedule_retains_handover_after_solar_stop(monkeypatch, tmp_path):
    import importlib, json
    async def scenario():
        hass, entry = _Hass(profile_a_soc='14'), _Entry()
        writer = importlib.import_module('power_sync.decision_diagnostics').AsyncDecisionWriter(tmp_path)
        writer.start()
        hass.data['power_sync'][entry.entry_id]['decision_diagnostics'] = writer
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, get = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or get(key)
        solar = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a',
                 'active_logical_vehicle_id': 'shared_ev_profile_a',
                 'logical_vehicle_id': 'shared_ev_profile_a', 'shared_loadpoint_binding': True,
                 'dynamic_mode': 'solar_surplus', 'owner_mode': 'solar_surplus',
                 'notify_on_start': False}
        runtime = {'active': True, 'params': solar, 'active_profile_id': 'shared_ev_profile_a',
                   'session_id': None, 'current_amps': 0, 'cancel_timer': lambda: None}
        actions._dynamic_ev_state[entry.entry_id] = {'generic_ev': runtime}
        ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner_mode='solar_surplus',
                                     extra={'active_profile_id': 'shared_ev_profile_a'})
        smart = {**solar, 'dynamic_mode': 'battery_target', 'owner_mode': 'smart_schedule',
                 'allow_ownership_takeover': True, 'fixed_charge_amps': 8, 'max_charge_amps': 8}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, smart)
        assert runtime.get('pending_stop')
        assert hass.services.async_call.await_args.args[:2] == ('switch', 'turn_off')
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, smart)
        assert hass.services.async_call.await_count == 1
        states['sensor.shared_ev_power'] = SimpleNamespace(
            state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert 'generic_ev' not in actions._dynamic_ev_state.get(entry.entry_id, {})
        import sys
        planner = SimpleNamespace(is_ev_plugged_in=AsyncMock(return_value=True))
        monkeypatch.setitem(sys.modules, 'power_sync.automations.ev_charging_planner', planner)
        # A fallback mode must not reacquire the physical charger while the
        # still-eligible successor is awaiting its next policy evaluation.
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, solar)
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        assert await actions._action_start_ev_charging_dynamic(hass, entry, smart)
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]['owner_mode'] == 'smart_schedule'
        await writer.close()
        events = [json.loads(line) for line in next(tmp_path.glob('ev-*.jsonl')).read_text().splitlines()]
        stop = next(e for e in events if e['event'] == 'dynamic_stop_requested')
        observed = next(e for e in events if e['event'] == 'stop_observation')
        command = next(e for e in events if e['event'] == 'command_handler_result' and e['command'] == 'set_amps' and e['requested_amps'] == 0)
        assert stop['trace_id'] == command['trace_id'] == observed['trace_id']

    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


@pytest.mark.parametrize('owner_mode', ['scheduled', 'price_level'])
def test_evac_successor_waits_for_real_stop_then_takes_control(monkeypatch, owner_mode):
    from test_shared_pause_evac_behavior import setup, FakeEvac

    async def scenario():
        hass, entry, _, physical, solar, runtime, _ = setup('sigenergy')
        controller = FakeEvac()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        incoming = {**solar, 'vehicle_id': 'shared_ev_profile_a', 'dynamic_mode': 'battery_target',
                    'owner_mode': owner_mode, 'allow_ownership_takeover': True,
                    'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode=owner_mode, reason='', source='test')
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert runtime.get('pending_stop')
        controller.stop_charging.assert_awaited_once()
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        controller.start_charging.assert_not_awaited()
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, physical)
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, solar)
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode=owner_mode, reason='', source='test')
        assert await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert ownership.get_ev_ownership(hass, entry, physical)[1]['owner_mode'] == owner_mode
        controller.start_charging.assert_awaited_once()

    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


@pytest.mark.parametrize('decision', ['denied', 'missing'])
def test_handover_reservation_expires_when_policy_no_longer_allows(decision):
    hass, entry = _Hass(), _Entry()
    params = {'active_logical_vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'smart_schedule'}
    actions._begin_automated_shared_loadpoint_cycle(hass, entry)
    actions._record_automated_shared_loadpoint_decision(
        hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
    actions._remember_shared_handover(hass, entry, 'generic_ev', params, {'generation': 'stop-1'})
    assert actions._shared_handover_waiting(hass, entry, 'generic_ev', 'shared_ev_profile_a', 'smart_schedule')
    actions._begin_automated_shared_loadpoint_cycle(hass, entry)
    if decision == 'denied':
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=False, responsible_mode='smart_schedule', reason='window ended', source='grid')
    actions._expire_unconfirmed_shared_handover(hass, entry)
    assert not actions._shared_handover_waiting(hass, entry, 'generic_ev', 'shared_ev_profile_a', 'smart_schedule')


def test_profile_change_cancels_waiting_handover_without_start(monkeypatch):
    async def scenario():
        hass, entry = _Hass(), _Entry()
        params = {'active_logical_vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'smart_schedule'}
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='smart_schedule', reason='', source='grid')
        actions._remember_shared_handover(hass, entry, 'generic_ev', params,
                                          {'settled_observation': object()})
        hass.states.get('sensor.connected_vehicle').state = 'tesla'
        import sys
        monkeypatch.setitem(sys.modules, 'power_sync.automations.ev_charging_planner',
                            SimpleNamespace(is_ev_plugged_in=AsyncMock(return_value=False)))
        solar_b = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_b',
                   'dynamic_mode': 'solar_surplus', 'owner_mode': 'solar_surplus'}
        assert not await actions._action_start_ev_charging_dynamic(hass, entry, solar_b)
        assert not actions._shared_handover_waiting(
            hass, entry, 'generic_ev', 'shared_ev_profile_a', 'smart_schedule')
        hass.services.async_call.assert_not_awaited()
    asyncio.run(scenario())


def test_fresh_idle_profile_handoff_keeps_new_profiles_successor(monkeypatch):
    from test_shared_pause_evac_behavior import setup

    async def scenario():
        hass, entry, _, physical, solar_a, runtime, _ = setup('generic')
        solar_a['charger_power_entity'] = 'sensor.shared_ev_power'
        states, original = {}, hass.states.get
        states['sensor.shared_ev_power'] = SimpleNamespace(
            state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        hass.states.get = lambda key: states.get(key) or original(key)
        hass.states.get('sensor.connected_vehicle').state = 'tesla'
        incoming = {**solar_a, 'vehicle_id': 'shared_ev_profile_b',
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
        assert actions._shared_handover_waiting(hass, entry, physical, 'shared_ev_profile_b', 'scheduled')
        assert not await actions._action_start_ev_charging_dynamic(
            hass, entry, {**solar_a, 'vehicle_id': 'shared_ev_profile_b',
                          'active_logical_vehicle_id': 'shared_ev_profile_b',
                          'logical_vehicle_id': 'shared_ev_profile_b'})
        actions._begin_automated_shared_loadpoint_cycle(hass, entry)
        actions._record_automated_shared_loadpoint_decision(
            hass, entry, allowed=True, responsible_mode='scheduled', reason='', source='test')
        assert await actions._action_start_ev_charging_dynamic(hass, entry, incoming)
        assert ownership.get_ev_ownership(hass, entry, physical)[1]['active_profile_id'] == 'shared_ev_profile_b'
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()

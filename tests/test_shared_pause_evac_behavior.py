"""Production-path shared pauses: physical dispatch, readback, and ownership."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


@pytest.fixture(autouse=True)
def clean_runtime():
    actions._dynamic_ev_state.clear()
    yield
    actions._dynamic_ev_state.clear()


def setup(charger):
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    store = Store()
    hass.data['power_sync'][entry.entry_id]['automation_store'] = store
    physical = 'sigenergy_charger' if charger == 'sigenergy' else 'generic_ev'
    params = {**(_generic_params() if charger == 'generic' else {'charger_type': 'sigenergy'}),
              'vehicle_id': physical, 'logical_vehicle_id': 'shared_ev_profile_a',
              'active_logical_vehicle_id': 'shared_ev_profile_a', 'shared_loadpoint_binding': True,
              'owner_mode': 'solar_surplus', 'dynamic_mode': 'solar_surplus'}
    if charger == 'sigenergy':
        entry.options = {**entry.options, 'generic_charger_enabled': False,
                         'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac',
                         'sigenergy_charger_host': 'charger.invalid'}
    runtime = {'active': True, 'params': params, 'active_profile_id': 'shared_ev_profile_a',
               'session_id': None, 'current_amps': 6, 'cancel_timer': lambda: None}
    actions._dynamic_ev_state[entry.entry_id] = {physical: runtime}
    ownership.claim_ev_ownership(hass, entry, physical, owner_mode='solar_surplus',
                                 extra={'active_profile_id': 'shared_ev_profile_a'})
    lease = ownership.get_ev_ownership(hass, entry, physical)[1]
    return hass, entry, store, physical, params, runtime, lease


class FakeEvac:
    def __init__(self):
        self.connect = AsyncMock(return_value=True)
        self.disconnect = AsyncMock()
        self._read_input_registers = AsyncMock(return_value=None)
        self.stop_charging = AsyncMock(side_effect=self.stop)
        self.set_charging_amps = AsyncMock(side_effect=self.set_amps)
        self.start_charging = AsyncMock(side_effect=self.start)

    async def stop(self):
        assert self._shared_write_authorized()
        return True

    async def set_amps(self, amps):
        assert self._shared_write_authorized()
        return True

    async def start(self, amps=None):
        assert self._shared_write_authorized()
        return True


def test_evac_dynamic_pause_invalid_then_idle_retains_exact_runtime_and_lease(monkeypatch):
    async def scenario():
        hass, entry, store, physical, params, runtime, lease = setup('sigenergy')
        controller = FakeEvac()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        await asyncio.wait_for(actions._set_vehicle_amps(hass, entry, physical, 0, params), 2)
        controller.stop_charging.assert_awaited_once_with()
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        assert store.saved['_shared_pending_stops'][physical]['dispatch_at'] is not None
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller._read_input_registers.await_count >= 1
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        assert not await actions._set_vehicle_amps(hass, entry, physical, 6, params)
        controller.set_charging_amps.assert_not_awaited()
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, physical)
        assert actions._dynamic_ev_state[entry.entry_id][physical] is runtime
        assert runtime['active']
        assert ownership.get_ev_ownership(hass, entry, physical)[1] is lease
        assert await actions._set_vehicle_amps(hass, entry, physical, 6, params)
        controller.set_charging_amps.assert_awaited_once_with(6)
        controller.start_charging.assert_awaited_once_with(amps=None)
        controller.stop_charging.assert_awaited_once_with()
    asyncio.run(scenario())


def test_evac_pause_blocks_concurrent_resume_until_dispatch_and_idle(monkeypatch):
    async def scenario():
        hass, entry, _, physical, params, runtime, lease = setup('sigenergy')
        controller = FakeEvac()
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_stop():
            assert controller._shared_write_authorized()
            entered.set()
            await release.wait()
            return True
        controller.stop_charging.side_effect = delayed_stop
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        pause = asyncio.create_task(actions._set_vehicle_amps(hass, entry, physical, 0, params))
        await asyncio.wait_for(entered.wait(), 2)
        resume = asyncio.create_task(actions._set_vehicle_amps(hass, entry, physical, 6, params))
        await asyncio.sleep(0)
        controller.set_charging_amps.assert_not_awaited()
        release.set()
        await asyncio.wait_for(pause, 2)
        assert not await asyncio.wait_for(resume, 2)
        controller.stop_charging.assert_awaited_once_with()
        controller.set_charging_amps.assert_not_awaited()
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        assert ownership.get_ev_ownership(hass, entry, physical)[1] is lease
    asyncio.run(scenario())


def test_evac_pause_restart_recovers_fence_without_redispatch(monkeypatch):
    async def scenario():
        hass, entry, store, physical, params, _, _ = setup('sigenergy')
        controller = FakeEvac()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        await actions._set_vehicle_amps(hass, entry, physical, 0, params)
        controller.stop_charging.assert_awaited_once_with()
        generation = store.saved['_shared_pending_stops'][physical]['generation']
        restored = _Hass()
        restored.states.async_all = lambda: []
        restored.data['power_sync'][entry.entry_id]['automation_store'] = Store(deepcopy(store.saved))
        actions._dynamic_ev_state.clear()
        await actions.async_load_pending_shared_stops(restored, entry)
        assert actions.is_shared_stop_fenced(restored, entry, physical)
        assert actions._dynamic_ev_state[entry.entry_id][physical]['pending_stop']['record']['generation'] == generation
        await actions.async_reconcile_pending_shared_stops(restored, entry)
        assert actions.is_shared_stop_fenced(restored, entry, physical)
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(restored, entry)
        assert not actions.is_shared_stop_fenced(restored, entry, physical)
        controller.stop_charging.assert_awaited_once_with()
        assert ownership.get_ev_ownership(restored, entry, physical)[1] is None
    asyncio.run(scenario())


@pytest.mark.parametrize('charger', ['generic', 'sigenergy'])
def test_positive_phase_clamp_to_zero_fences_before_physical_stop(monkeypatch, charger):
    async def scenario():
        hass, entry, _, physical, params, runtime, lease = setup(charger)
        controller = FakeEvac()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        monkeypatch.setattr(actions, '_phase_load_management_applies', lambda *a: True)
        clamp = AsyncMock(return_value=0)
        monkeypatch.setattr(actions, '_phase_load_managed_target_amps', clamp)
        await asyncio.wait_for(actions._set_vehicle_amps(hass, entry, physical, 6, params), 2)
        assert clamp.await_count >= 1
        if charger == 'generic':
            hass.services.async_call.assert_awaited_once_with('switch', 'turn_off', {'entity_id': 'switch.shared_ev'}, blocking=True)
        else:
            controller.stop_charging.assert_awaited_once_with()
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        assert actions._dynamic_ev_state[entry.entry_id][physical] is runtime
        assert ownership.get_ev_ownership(hass, entry, physical)[1] is lease
    asyncio.run(scenario())


def test_evac_shared_stop_refuses_missing_dispatch_context(monkeypatch):
    async def scenario():
        hass, entry, _, _, params, _, _ = setup('sigenergy')
        controller = FakeEvac()
        controller.stop_charging.side_effect = None
        controller.stop_charging.return_value = True
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        assert not await actions._stop_sigenergy_charger(hass, entry, params)
        controller.stop_charging.assert_not_awaited()
    asyncio.run(scenario())


def test_undispatched_stop_never_reports_physical_command(monkeypatch):
    async def scenario():
        hass, entry, store, physical, params, runtime, _ = setup('generic')
        monkeypatch.setattr(actions, '_shared_generic_stop_authorized', lambda *args: False)
        report = {}
        async with actions._start_dynamic_lock:
            result = await actions._stop_dynamic_under_transition_lock(hass, entry, {
                **params, 'vehicle_id': physical, '_expected_state': runtime,
                '_physical_stop_report': report,
            })
        assert result is False
        assert not report.get('physical_stop_vehicle_ids')
        assert runtime['pending_stop'].get('dispatch_at') is None
        hass.services.async_call.assert_not_awaited()
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        restored = _Hass()
        restored.states.async_all = lambda: []
        restored.data['power_sync'][entry.entry_id]['automation_store'] = Store(deepcopy(store.saved))
        actions._dynamic_ev_state.clear()
        await actions.async_load_pending_shared_stops(restored, entry)
        await actions.async_reconcile_pending_shared_stops(restored, entry)
        assert actions.is_shared_stop_fenced(restored, entry, physical)
        restored.services.async_call.assert_not_awaited()
    asyncio.run(scenario())


def test_nested_generic_set_amps_action_dispatches_fenced_zero():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual', 'amps': 0}
        assert not await asyncio.wait_for(actions._execute_single_action(hass, entry, 'set_ev_charging_amps', params), 2)
        hass.services.async_call.assert_awaited_once_with('switch', 'turn_off', {'entity_id': 'switch.shared_ev'}, blocking=True)
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())

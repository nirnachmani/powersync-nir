"""Regression: ordinary shared dynamic pauses need a fenced stop."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


def test_generic_dynamic_pause_dispatches_then_waits_for_fresh_idle():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        original = hass.states.get
        power = SimpleNamespace(state='1400', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        hass.states.get = lambda key: power if key == 'sensor.shared_ev_power' else original(key)
        params = {**_generic_params(), 'vehicle_id': 'generic_ev',
                  'logical_vehicle_id': 'shared_ev_profile_a',
                  'active_logical_vehicle_id': 'shared_ev_profile_a',
                  'shared_loadpoint_binding': True, 'owner_mode': 'solar_surplus',
                  'dynamic_mode': 'solar_surplus'}
        runtime = {'active': True, 'params': params, 'active_profile_id': 'shared_ev_profile_a',
                   'session_id': None, 'current_amps': 6, 'cancel_timer': lambda: None}
        actions._dynamic_ev_state.clear()
        actions._dynamic_ev_state[entry.entry_id] = {'generic_ev': runtime}
        ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner_mode='solar_surplus',
                                     extra={'active_profile_id': 'shared_ev_profile_a'})
        await asyncio.wait_for(actions._set_vehicle_amps(hass, entry, 'generic_ev', 0, params), 2)
        assert hass.services.async_call.await_count == 1
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        power.state = '0'
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        power.last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert actions._dynamic_ev_state[entry.entry_id]['generic_ev'] is runtime
        assert runtime['active']
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is not None
        assert await actions._set_vehicle_amps(hass, entry, 'generic_ev', 6, params)
        assert hass.services.async_call.await_count >= 2
        actions._dynamic_ev_state.clear()
    asyncio.run(scenario())


def test_shared_pause_does_not_invert_physical_lock_order():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        params = {**_generic_params(), 'shared_loadpoint_binding': True,
                  'active_logical_vehicle_id': 'shared_ev_profile_a'}
        token = actions._shared_io_owner.set((asyncio.current_task(), object()))
        try:
            async with actions._start_dynamic_lock:
                async with asyncio.timeout(0.1):
                    result = await actions._set_vehicle_amps(hass, entry, 'generic_ev', 0, params)
            assert result is False
        finally:
            actions._shared_io_owner.reset(token)
    asyncio.run(scenario())

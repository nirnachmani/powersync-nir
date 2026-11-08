"""A mode teardown must supersede, not silently settle, a live pause."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


def test_teardown_while_pause_pending_releases_only_after_idle():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        original = hass.states.get
        power = SimpleNamespace(state='1400', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        hass.states.get = lambda key: power if key == 'sensor.shared_ev_power' else original(key)
        params = {**_generic_params(), 'vehicle_id': 'generic_ev', 'logical_vehicle_id': 'shared_ev_profile_a', 'active_logical_vehicle_id': 'shared_ev_profile_a', 'shared_loadpoint_binding': True, 'owner_mode': 'solar_surplus', 'dynamic_mode': 'solar_surplus'}
        cancelled = []
        runtime = {'active': True, 'params': params, 'active_profile_id': 'shared_ev_profile_a', 'session_id': None, 'current_amps': 6, 'cancel_timer': lambda: cancelled.append(True)}
        actions._dynamic_ev_state[entry.entry_id] = {'generic_ev': runtime}
        ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner_mode='solar_surplus', extra={'active_profile_id': 'shared_ev_profile_a'})
        await actions._set_vehicle_amps(hass, entry, 'generic_ev', 0, params)
        assert not await actions._action_stop_ev_charging_dynamic(hass, entry, params)
        assert not runtime['active'] and cancelled
        power.state = '0'
        power.last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is None
        assert 'generic_ev' not in actions._dynamic_ev_state.get(entry.entry_id, {})
    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()

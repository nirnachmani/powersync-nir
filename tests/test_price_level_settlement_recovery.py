"""Price-level executor must recover only its own strictly settled stop."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_ev_price_level_ownership import ev_planner


def test_price_level_retries_after_strict_settlement_and_solar_successor():
    from test_shared_loadpoint_action_guard import _Hass, _Entry, actions, ownership
    from test_shared_stop_storage import Store

    async def scenario():
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        lease = ownership.acquire_shared_loadpoint_ownership(
            hass, entry, 'generic_ev', active_profile_id='shared_ev_profile_a',
            owner_mode='price_level_recovery')
        assert lease
        executor = ev_planner.PriceLevelChargingExecutor(hass, entry)
        executor.apply_preserve_home_battery = AsyncMock()
        executor.get_charging_decision = AsyncMock(return_value=(False, 'Price too high', ''))
        state = executor._get_or_create_vehicle_state('shared_ev_profile_a')
        state.is_charging = True
        state.charging_mode = 'price_level_recovery'
        await executor.evaluate_all_vehicles(40)
        assert state.is_charging
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        pending = actions._dynamic_ev_state[entry.entry_id]['generic_ev']['pending_stop']
        power = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'},
                                last_reported=pending['dispatch_at'])
        states['sensor.shared_ev_power'] = power
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert state.is_charging
        power.last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        successor = ownership.acquire_shared_loadpoint_ownership(
            hass, entry, 'generic_ev', active_profile_id='shared_ev_profile_a',
            owner_mode='solar_surplus')
        assert successor
        executor.get_charging_decision.return_value = (True, 'Price low', 'price_level_recovery')
        executor._start_charging = AsyncMock(return_value=False)
        calls = hass.services.async_call.await_count
        await executor.evaluate_all_vehicles(10)
        assert not state.is_charging
        executor._start_charging.assert_awaited_once_with(
            'price_level_recovery', 'Price low', vehicle_vin='shared_ev_profile_a')
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is successor
        assert hass.services.async_call.await_count == calls

    try:
        asyncio.run(scenario())
    finally:
        actions._dynamic_ev_state.clear()


def test_delayed_price_stop_does_not_attach_to_new_start(monkeypatch):
    from test_shared_loadpoint_action_guard import _Hass, _Entry, actions
    async def scenario():
        executor = ev_planner.PriceLevelChargingExecutor(_Hass(), _Entry())
        executor.apply_preserve_home_battery = AsyncMock()
        state = executor._get_or_create_vehicle_state('shared_ev_profile_a')
        state.is_charging = True
        state.charging_mode = 'price_level'
        entered, release = asyncio.Event(), asyncio.Event()
        pending = {'record': {'profile_id': 'shared_ev_profile_a', 'owner_mode': 'price_level'},
                   'settled_observation': object()}
        async def delayed_stop(*args, **kwargs):
            kwargs['stop_episode_report']['pending'] = pending
            entered.set()
            await release.wait()
            return False
        monkeypatch.setattr(ev_planner, '_stop_coordinated_charging', delayed_stop)
        monkeypatch.setattr(ev_planner, '_start_coordinated_charging', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_is_vehicle_charge_complete', AsyncMock(return_value=False))
        task = asyncio.create_task(executor._stop_charging('old', vehicle_vin='shared_ev_profile_a'))
        await entered.wait()
        assert await executor._start_charging('price_level', 'new', vehicle_vin='shared_ev_profile_a')
        release.set()
        assert not await task
        assert state.is_charging
        assert state.pending_shared_stop is None
    asyncio.run(scenario())

"""Solar callback regressions using the shared physical charger fake."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


@pytest.fixture
def rig(monkeypatch):
    actions._dynamic_ev_state.clear()
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
    original_get = hass.states.get
    power = SimpleNamespace(state='1400', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
    hass.states.get = lambda key: power if key == 'sensor.shared_ev_power' else original_get(key)
    params = {**_generic_params(), 'charger_power_entity': 'sensor.shared_ev_power',
              'vehicle_id': 'generic_ev', 'vehicle_name': 'Tank',
              'logical_vehicle_id': 'shared_ev_profile_a',
              'active_logical_vehicle_id': 'shared_ev_profile_a',
              'shared_loadpoint_binding': True, 'owner_mode': 'solar_surplus',
              'dynamic_mode': 'solar_surplus', 'min_battery_soc': 50,
              'pause_below_soc': 40, 'sustained_surplus_minutes': 0,
              'notify_on_error': True, 'notify_on_start': True}
    runtime = {'active': True, 'params': params, 'active_profile_id': 'shared_ev_profile_a',
               'session_id': None, 'current_amps': 6, 'target_amps': 6,
               'charging_started': True, 'cancel_timer': lambda: None}
    actions._dynamic_ev_state[entry.entry_id] = {'generic_ev': runtime}
    ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner_mode='solar_surplus',
                                 extra={'active_profile_id': 'shared_ev_profile_a'})
    live = {'battery_soc': 20, 'battery_power': 0, 'grid_power': 0, 'solar_power': 5000}
    monkeypatch.setattr(actions, '_get_tesla_live_status', AsyncMock(return_value=live))
    monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 0)
    push = AsyncMock()
    monkeypatch.setattr(actions, '_send_expo_push', push)
    async def tick():
        await asyncio.wait_for(actions._dynamic_ev_update_surplus(hass, entry, entry.entry_id, 'generic_ev'), 2)
    yield SimpleNamespace(hass=hass, entry=entry, power=power, runtime=runtime, live=live, push=push, tick=tick)
    actions._dynamic_ev_state.clear()


def test_floor_pause_pending_repeated_ticks_stale_and_fresh_idle(rig):
    async def scenario():
        await rig.tick()
        assert rig.hass.services.async_call.await_count == 1
        assert actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
        pending = rig.runtime['pending_stop']
        assert rig.runtime['current_amps'] == 6
        assert rig.push.await_count == 0
        for value in ('1400', 'unknown', '0'):
            rig.power.state = value  # zero retains its pre-command timestamp
            await rig.tick()
            await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
            assert actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
            assert rig.runtime['pending_stop'] is pending
            assert rig.runtime['current_amps'] == 6
            assert rig.hass.services.async_call.await_count == 1
            assert rig.push.await_count == 0
        rig.power.last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
        assert not actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
        assert rig.runtime['active']
        rig.live['battery_soc'] = 80
        rig.live['grid_power'] = -5000
        await rig.tick()
        assert not rig.runtime.get('stop_outcome')
        assert rig.runtime['paused'] is False, rig.runtime.get('paused_reason')
        await rig.tick()
        assert rig.hass.services.async_call.await_count > 1
    asyncio.run(scenario())


def test_external_generic_export_price_pending_does_not_reissue_each_tick(rig, monkeypatch):
    rig.runtime['external_generic_session'] = True
    monkeypatch.setattr(actions, '_get_current_ev_export_price', lambda *_: 50)
    monkeypatch.setattr(actions, 'solar_surplus_price_allows_charging', lambda *a, **k: False)
    monkeypatch.setattr(actions, 'get_solar_surplus_max_export_price_cents', lambda *_: 10)
    async def scenario():
        await rig.tick()
        assert rig.hass.services.async_call.await_count == 1
        assert rig.runtime.get('stop_outcome')
        assert rig.runtime['current_amps'] == 6
        for value in ('1400', 'unknown', '0'):
            rig.power.state = value
            await rig.tick()
            await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
            assert actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
            assert rig.runtime.get('stop_outcome')
            assert rig.runtime['current_amps'] == 6
            assert rig.hass.services.async_call.await_count == 1
            assert rig.push.await_count == 0
        rig.power.last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
        assert not actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
        assert rig.runtime['current_amps'] == 0
        assert not rig.runtime.get('stop_outcome')
        assert not rig.runtime.get('external_generic_session')
    asyncio.run(scenario())


def test_floor_pending_does_not_claim_paused_before_power_readback(rig):
    async def scenario():
        await rig.tick()
        assert rig.hass.services.async_call.await_count == 1
        assert actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
        assert rig.runtime['current_amps'] == 6
        # A pending fenced stop must not be announced as physically paused.
        assert rig.push.await_count == 0
    asyncio.run(scenario())


def test_external_floor_warning_identity_and_timer(rig, monkeypatch):
    from power_sync import action_events
    notice = Mock(return_value=True)
    monkeypatch.setattr(action_events, '_notification', notice)
    rig.runtime['external_generic_session'] = True
    async def scenario():
        await rig.tick()
        assert rig.hass.services.async_call.await_count == 1
        pending = rig.runtime['pending_stop']
        generation = pending['record']['generation']
        first = pending['requested_at']
        await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
        notice.assert_not_called()
        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(seconds=121)
        monkeypatch.setattr(actions, 'datetime', Later)
        for power in ('unknown', '0', '1400'):
            rig.power.state = power
            await rig.tick()
            await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
            assert rig.runtime['pending_stop'] is pending
            assert pending['record']['generation'] == generation
            assert pending['requested_at'] == first
            assert rig.runtime['current_amps'] == 6
            assert rig.hass.services.async_call.await_count == 1
            assert notice.call_count == 1
        alert_id = notice.call_args.kwargs['notification_id']
        assert not notice.call_args.kwargs.get('clear', False)
        rig.power.state = '0'
        rig.power.last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
        assert not actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
        assert notice.call_count == 2
        assert notice.call_args.kwargs['notification_id'] == alert_id
        assert notice.call_args.kwargs['clear'] is True
        assert rig.runtime['current_amps'] == 0
        rig.live['battery_soc'] = 80
        await rig.tick()
        assert rig.runtime['active']
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['solar_surplus', 'battery_target'])
def test_callback_started_before_settled_pause_cannot_resume(rig, monkeypatch, mode):
    async def scenario():
        rig.runtime['params']['dynamic_mode'] = mode
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_status(*args):
            entered.set()
            await release.wait()
            return rig.live
        monkeypatch.setattr(actions, '_get_tesla_live_status', delayed_status)
        tick = asyncio.create_task(actions._dynamic_ev_update(rig.hass, rig.entry, rig.entry.entry_id, 'generic_ev'))
        await asyncio.wait_for(entered.wait(), 2)
        await actions._set_vehicle_amps(rig.hass, rig.entry, 'generic_ev', 0, rig.runtime['params'])
        rig.power.state = '0'
        rig.power.last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
        assert not actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
        calls = rig.hass.services.async_call.await_count
        rig.runtime['reason'] = 'settled sentinel'
        release.set()
        await asyncio.wait_for(tick, 2)
        assert rig.runtime['reason'] == 'settled sentinel'
        assert rig.hass.services.async_call.await_count == calls
    asyncio.run(scenario())


def test_solar_start_queued_before_pause_settles_is_rejected(rig, monkeypatch):
    async def scenario():
        rig.live.update(battery_soc=80, grid_power=-5000)
        rig.runtime.update(current_amps=0, target_amps=0, charging_started=False,
                           high_surplus_start=datetime.now() - timedelta(minutes=1))
        rig.power.state = '0'
        lock = asyncio.Lock()
        rig.hass.data['power_sync'][rig.entry.entry_id].setdefault('_shared_physical_io_locks', {})['generic_ev'] = lock
        entered = asyncio.Event()
        original = actions._action_start_ev_charging
        async def queued(*args, **kwargs):
            entered.set()
            return await original(*args, **kwargs)
        monkeypatch.setattr(actions, '_action_start_ev_charging', queued)
        async with lock:
            token = actions._shared_io_owner.set((asyncio.current_task(), lock))
            try:
                tick = asyncio.create_task(rig.tick())
                await asyncio.wait_for(entered.wait(), 2)
                for _ in range(20):
                    if lock._waiters:
                        break
                    await asyncio.sleep(0)
                assert lock._waiters, 'start must be waiting at physical I/O'
                await actions._stop_dynamic_under_transition_lock(rig.hass, rig.entry, {
                    **rig.runtime['params'], 'vehicle_id': 'generic_ev',
                    '_expected_state': rig.runtime, '_shared_runtime_pause': True,
                })
                rig.power.last_reported = datetime.now(timezone.utc)
                await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
                assert not actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
                assert rig.runtime['_shared_pause_generation'] == 1
                rig.hass.states.get('switch.shared_ev').state = 'off'
                calls = rig.hass.services.async_call.await_count
                assert calls == 1
            finally:
                actions._shared_io_owner.reset(token)
        await asyncio.wait_for(tick, 2)
        assert rig.hass.services.async_call.await_count == calls
        rig.runtime['high_surplus_start'] = datetime.now() - timedelta(minutes=1)
        await rig.tick()
        assert rig.hass.services.async_call.await_count > calls
    asyncio.run(scenario())


def test_solar_rate_queued_before_pause_settles_is_rejected(rig, monkeypatch):
    async def scenario():
        rig.live.update(battery_soc=80, grid_power=-5000)
        lock = asyncio.Lock()
        rig.hass.data['power_sync'][rig.entry.entry_id].setdefault('_shared_physical_io_locks', {})['generic_ev'] = lock
        entered = asyncio.Event()
        original = actions._set_vehicle_amps
        async def queued(hass, entry, vehicle, amps, params):
            if amps > 0:
                entered.set()
            return await original(hass, entry, vehicle, amps, params)
        monkeypatch.setattr(actions, '_set_vehicle_amps', queued)
        async with lock:
            token = actions._shared_io_owner.set((asyncio.current_task(), lock))
            try:
                tick = asyncio.create_task(rig.tick())
                await asyncio.wait_for(entered.wait(), 2)
                for _ in range(20):
                    if lock._waiters:
                        break
                    await asyncio.sleep(0)
                assert lock._waiters
                await actions._stop_dynamic_under_transition_lock(rig.hass, rig.entry, {
                    **rig.runtime['params'], 'vehicle_id': 'generic_ev',
                    '_expected_state': rig.runtime, '_shared_runtime_pause': True,
                })
                rig.power.state = '0'
                rig.power.last_reported = datetime.now(timezone.utc)
                await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
                assert rig.runtime['_shared_pause_generation'] == 1
                assert not actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
                calls = rig.hass.services.async_call.await_count
                assert calls == 1
            finally:
                actions._shared_io_owner.reset(token)
        await asyncio.wait_for(tick, 2)
        assert rig.hass.services.async_call.await_count == calls
    asyncio.run(scenario())


def test_solar_rate_rechecks_generation_after_awaited_resolution(rig, monkeypatch):
    async def scenario():
        rig.live.update(battery_soc=80, grid_power=-5000)
        original = actions._resolve_shared_loadpoint_direct_command
        triggered = False
        calls_after_pause = None
        async def resolve(*args, **kwargs):
            nonlocal triggered, calls_after_pause
            if not triggered and kwargs.get('require_live_shared_profile_soc'):
                triggered = True
                await actions._stop_dynamic_under_transition_lock(rig.hass, rig.entry, {
                    **rig.runtime['params'], 'vehicle_id': 'generic_ev',
                    '_expected_state': rig.runtime, '_shared_runtime_pause': True,
                })
                rig.power.state = '0'
                rig.power.last_reported = datetime.now(timezone.utc)
                await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
                assert not actions.is_shared_stop_fenced(rig.hass, rig.entry, 'generic_ev')
                assert rig.runtime['_shared_pause_generation'] == 1
                calls_after_pause = rig.hass.services.async_call.await_count
                assert calls_after_pause == 1
            return await original(*args, **kwargs)
        monkeypatch.setattr(actions, '_resolve_shared_loadpoint_direct_command', resolve)
        await rig.tick()
        assert triggered
        assert rig.hass.services.async_call.await_count == calls_after_pause
    asyncio.run(scenario())


def test_solar_rate_rechecks_generation_after_phase_clamp(rig, monkeypatch):
    async def scenario():
        rig.live.update(battery_soc=80, grid_power=-5000)
        monkeypatch.setattr(actions, '_phase_load_management_applies', lambda *args: True)
        clamp_params = []
        async def clamp(*args):
            clamp_params.append(args[-1])
            monkeypatch.setattr(actions, '_phase_load_management_applies', lambda *args: False)
            await actions._stop_dynamic_under_transition_lock(rig.hass, rig.entry, {
                **rig.runtime['params'], 'vehicle_id': 'generic_ev',
                '_expected_state': rig.runtime, '_shared_runtime_pause': True,
            })
            rig.power.state = '0'
            rig.power.last_reported = datetime.now(timezone.utc)
            await actions.async_reconcile_pending_shared_stops(rig.hass, rig.entry)
            assert rig.runtime['_shared_pause_generation'] == 1
            return 0
        monkeypatch.setattr(actions, '_phase_load_managed_target_amps', clamp)
        await rig.tick()
        assert rig.runtime['_shared_pause_generation'] == 1
        assert '_phase_load_management_applied_amps' not in clamp_params[0]
        assert rig.hass.services.async_call.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("caller", ["start", "rate"])
@pytest.mark.parametrize("invalidate", ["selector", "generation", "lease", "none"])
def test_generic_reset_rechecks_shared_guard_after_turn_off(rig, monkeypatch, invalidate, caller):
    async def scenario():
        params = {**rig.runtime["params"], "charger_switch_entity": "switch.test_charge_control",
                  "charger_amps_entity": None}
        rig.entry.options = {**rig.entry.options, "generic_charger_switch_entity": "switch.test_charge_control",
                             "generic_charger_amps_entity": ""}
        original_get = rig.hass.states.get
        switch = SimpleNamespace(state="on")
        connector = SimpleNamespace(state="finishing")
        rig.hass.states.get = lambda key: (switch if key == "switch.test_charge_control" else
                                           connector if key == "sensor.test_status_connector" else original_get(key))
        async def service(domain, service, data, **kwargs):
            if service == "turn_off":
                if invalidate == "selector":
                    rig.hass.states.get("sensor.connected_vehicle").state = "tesla"
                elif invalidate == "generation":
                    rig.runtime["_shared_pause_generation"] = 1
                elif invalidate == "lease":
                    leases = ownership.get_ev_ownerships(rig.hass, rig.entry)
                    leases["generic_ev"] = dict(leases["generic_ev"])
        rig.hass.services.async_call.side_effect = service
        monkeypatch.setattr(actions.asyncio, "sleep", AsyncMock())
        token = actions._shared_callback_capability.set(
            (asyncio.current_task(), rig.entry.entry_id, "generic_ev", rig.runtime, 0)
        )
        try:
            if caller == "start":
                result = await actions._action_start_ev_charging(rig.hass, rig.entry, params)
            else:
                result = await actions._set_vehicle_amps_unchecked(rig.hass, rig.entry, "generic_ev", 6, params)
        finally:
            actions._shared_callback_capability.reset(token)
        calls = [call.args[1] for call in rig.hass.services.async_call.await_args_list]
        assert calls == (["turn_off", "turn_on"] if invalidate == "none" else ["turn_off"])
        assert result is (invalidate == "none")
    asyncio.run(scenario())

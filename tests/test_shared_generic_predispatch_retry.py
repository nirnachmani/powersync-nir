"""Retry only a proven Generic validation rejection, never an ambiguous call."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


def test_missing_switch_retries_when_available_then_waits_for_idle(monkeypatch):
    class Clock(datetime):
        value = datetime.now(timezone.utc) - timedelta(seconds=31)
        @classmethod
        def now(cls, tz=None):
            return cls.value

    async def scenario():
        monkeypatch.setattr(actions, 'datetime', Clock)
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        store = Store()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        hass.states.async_all = lambda: []
        original = hass.states.get
        switch = _generic_params()['charger_switch_entity']
        available = False
        power = None
        def get(entity):
            if entity == switch:
                return original(entity) if available else None
            if entity == 'sensor.shared_ev_power':
                return power
            return original(entity)
        hass.states.get = get
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'}
        assert not await actions._action_stop_ev_charging(hass, entry, params)
        record = store.saved['_shared_pending_stops']['generic_ev']
        assert record['last_status'] == 'validation_rejected_before_dispatch'
        assert hass.services.async_call.await_count == 0
        available = True
        Clock.value += timedelta(seconds=30)
        await asyncio.wait_for(actions.async_reconcile_pending_shared_stops(hass, entry), 2)
        assert hass.services.async_call.await_count == 1
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        Clock.value += timedelta(seconds=1)
        power = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=Clock.value)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['owner', 'profile', 'endpoint', 'restart'])
def test_rejected_stop_never_retries_without_exact_identity(monkeypatch, caplog, change):
    class Clock(datetime):
        value = datetime.now(timezone.utc) - timedelta(seconds=31)
        @classmethod
        def now(cls, tz=None):
            return cls.value

    async def scenario():
        monkeypatch.setattr(actions, 'datetime', Clock)
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        store = Store()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        hass.states.async_all = lambda: []
        original = hass.states.get
        switch = _generic_params()['charger_switch_entity']
        available = False
        hass.states.get = lambda entity: None if entity == switch and not available else original(entity)
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'}
        await actions._action_stop_ev_charging(hass, entry, params)
        state = actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        if change == 'owner':
            ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]['session_id'] = 'replacement'
        elif change == 'profile':
            original('sensor.connected_vehicle').state = 'tesla'
        elif change == 'endpoint':
            state['pending_stop']['physical_params']['charger_switch_entity'] = 'switch.other'
        else:
            actions._dynamic_ev_state.clear()
            hass.data['power_sync'][entry.entry_id].pop('_shared_stop_fences', None)
            await actions.async_load_pending_shared_stops(hass, entry)
            assert 'ownership cannot be proven after restart' in caplog.text
        available = True
        Clock.value += timedelta(seconds=30)
        await asyncio.wait_for(actions.async_reconcile_pending_shared_stops(hass, entry), 2)
        assert hass.services.async_call.await_count == 0
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())


def test_ambiguous_service_error_is_not_retried(monkeypatch):
    class Clock(datetime):
        value = datetime.now(timezone.utc) - timedelta(seconds=31)
        @classmethod
        def now(cls, tz=None):
            return cls.value

    async def scenario():
        monkeypatch.setattr(actions, 'datetime', Clock)
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        store = Store()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        hass.states.async_all = lambda: []
        hass.services.async_call.side_effect = OSError('ambiguous')
        await actions._action_stop_ev_charging(hass, entry,
            {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'})
        record = store.saved['_shared_pending_stops']['generic_ev']
        assert record['last_status'] == 'unknown' and record['dispatch_at']
        Clock.value += timedelta(seconds=60)
        await asyncio.wait_for(actions.async_reconcile_pending_shared_stops(hass, entry), 2)
        assert hass.services.async_call.await_count == 1
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())


def test_profile_change_while_waiting_for_io_lock_blocks_retry(monkeypatch):
    class Clock(datetime):
        value = datetime.now(timezone.utc) - timedelta(seconds=31)
        @classmethod
        def now(cls, tz=None):
            return cls.value

    async def scenario():
        monkeypatch.setattr(actions, 'datetime', Clock)
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        hass.states.async_all = lambda: []
        original = hass.states.get
        switch = _generic_params()['charger_switch_entity']
        available = False
        hass.states.get = lambda entity: None if entity == switch and not available else original(entity)
        await actions._action_stop_ev_charging(hass, entry,
            {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'})
        locks = hass.data['power_sync'][entry.entry_id].setdefault('_shared_physical_io_locks', {})
        lock = locks.setdefault('generic_ev', asyncio.Lock())
        available = True
        Clock.value += timedelta(seconds=30)
        async with lock:
            task = asyncio.create_task(actions.async_reconcile_pending_shared_stops(hass, entry))
            await asyncio.sleep(0)
            original('sensor.connected_vehicle').state = 'tesla'
        await asyncio.wait_for(task, 2)
        assert hass.services.async_call.await_count == 0
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())

"""Direct shared stops must remain fenced until post-dispatch observation."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


@pytest.fixture(autouse=True)
def clear_dynamic_runtime():
    actions._dynamic_ev_state.clear()
    yield
    actions._dynamic_ev_state.clear()


def test_untracked_direct_generic_stop_fences_until_new_report():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        actions._dynamic_ev_state.clear()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'}
        assert not await actions._action_stop_ev_charging(hass, entry, params)
        assert hass.services.async_call.await_count == 1
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert not await actions._action_stop_ev_charging(hass, entry, params)
        assert hass.services.async_call.await_count == 1
        states['sensor.shared_ev_power'].last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is None
    asyncio.run(scenario())


@pytest.mark.parametrize('external', [False, True])
def test_immediate_failure_clears_on_strict_settlement_before_release(monkeypatch, external):
    from unittest.mock import Mock
    from power_sync import action_events
    from power_sync.automations.external_session_reconciler import reconcile_selected_shared_loadpoint_cycle

    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        notices = Mock(return_value=True)
        monkeypatch.setattr(action_events, '_notification', notices)
        failed = ownership.record_ev_command(hass, entry, 'generic_ev', command='stop', success=False)
        if external:
            ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner='external', owner_mode='external',
                extra={'active_profile_id': 'shared_ev_profile_a', 'resolver_stop_lease_token': 'episode'})
        stop = actions._stop_external_shared_session_guarded if external else actions._action_stop_ev_charging
        await stop(hass, entry, {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'})
        pending = actions._dynamic_ev_state[entry.entry_id]['generic_ev']['pending_stop']
        power = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'},
                                last_reported=pending['dispatch_at'], last_updated=datetime.now(timezone.utc))
        states['sensor.shared_ev_power'] = power
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        await reconcile_selected_shared_loadpoint_cycle(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert not any(c.kwargs.get('clear') for c in notices.call_args_list)
        power.last_reported = datetime.now(timezone.utc)
        original_release = ownership.release_ev_ownership
        def release(*args, **kwargs):
            assert failed.get('settled_at') == power.last_reported.isoformat()
            assert any(c.kwargs.get('clear') for c in notices.call_args_list)
            return original_release(*args, **kwargs)
        monkeypatch.setattr(ownership, 'release_ev_ownership', release)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is None
        await reconcile_selected_shared_loadpoint_cycle(hass, entry)
        assert hass.services.async_call.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('replacement', ['command', 'owner'])
def test_settlement_does_not_dismiss_newer_episode(monkeypatch, replacement):
    from unittest.mock import Mock
    from power_sync import action_events
    from power_sync.automations.external_session_reconciler import reconcile_selected_shared_loadpoint_cycle

    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        notices = Mock(return_value=True)
        monkeypatch.setattr(action_events, '_notification', notices)
        ownership.record_ev_command(hass, entry, 'generic_ev', command='stop', success=False)
        await actions._action_stop_ev_charging(hass, entry, {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'})
        if replacement == 'command':
            ownership.record_ev_command(hass, entry, 'generic_ev', command='start', success=True)
            ownership.record_ev_command(hass, entry, 'generic_ev', command='stop', success=False)
        else:
            ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]['active_profile_id'] = 'shared_ev_profile_b'
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc), last_updated=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        await reconcile_selected_shared_loadpoint_cycle(hass, entry)
        assert not any(c.kwargs.get('clear') for c in notices.call_args_list)
        assert hass.services.async_call.await_count == 1
    asyncio.run(scenario())


def test_untracked_external_override_does_not_complete_on_service_ack():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        actions._dynamic_ev_state.clear()
        ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner='external', owner_mode='external', extra={'active_profile_id': 'shared_ev_profile_a', 'resolver_stop_lease_token': 'episode-a'})
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a'}
        assert not await actions._stop_external_shared_session_guarded(hass, entry, params)
        assert hass.services.async_call.await_count == 1
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())


def test_failed_store_still_settles_only_on_fresh_observation():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        store = Store()
        async def fail():
            raise OSError("storage unavailable")
        store.async_save = fail
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        actions._dynamic_ev_state.clear()
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'}
        assert not await actions._action_stop_ev_charging(hass, entry, params)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        states['sensor.shared_ev_power'].last_reported = datetime.now(timezone.utc)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is None
        assert hass.services.async_call.await_count == 1
    asyncio.run(scenario())


def test_external_stop_persists_episode_identity():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        store = Store()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        actions._dynamic_ev_state.clear()
        ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner='external', owner_mode='external', extra={'active_profile_id': 'shared_ev_profile_a', 'resolver_stop_lease_token': 'lease-a'})
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', '_observed_session_token': 'observed-a'}
        assert not await actions._stop_external_shared_session_guarded(hass, entry, params)
        record = store.saved['_shared_pending_stops']['generic_ev']
        assert record['owner_kind'] == 'external'
        assert record['observed_session_token'] == 'observed-a'
        assert record['resolver_stop_lease_token'] == 'lease-a'
        lease = ownership.get_ev_ownership(hass, entry, 'generic_ev')[1]
        lease['resolver_stop_lease_token'] = 'new-episode'
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
        assert ownership.get_ev_ownership(hass, entry, 'generic_ev')[1] is lease
    asyncio.run(scenario())


@pytest.mark.parametrize('external', [False, True])
def test_untracked_evac_stop_waits_for_direct_idle_read(monkeypatch, external):
    from unittest.mock import AsyncMock
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        entry.options = {**entry.options, 'generic_charger_enabled': False,
                         'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac',
                         'sigenergy_charger_host': 'charger.invalid'}
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        actions._dynamic_ev_state.clear()
        class Controller:
            async def connect(self):
                return True
            async def stop_charging(self):
                assert self._shared_write_authorized()
                stops.append(True)
                return True
            async def disconnect(self):
                pass
            _read_input_registers = AsyncMock(return_value=None)
        stops = []
        controller = Controller()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        params = {'charger_type': 'sigenergy', 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'}
        if external:
            ownership.claim_ev_ownership(hass, entry, 'sigenergy_charger', owner='external', owner_mode='external', extra={'active_profile_id': 'shared_ev_profile_a', 'resolver_stop_lease_token': 'episode'})
            stop = actions._stop_external_shared_session_guarded
        else:
            stop = actions._action_stop_ev_charging
        assert not await stop(hass, entry, params)
        assert len(stops) == 1
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert actions.is_shared_stop_fenced(hass, entry, 'sigenergy_charger')
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert not actions.is_shared_stop_fenced(hass, entry, 'sigenergy_charger')
        assert ownership.get_ev_ownership(hass, entry, 'sigenergy_charger')[1] is None
        assert len(stops) == 1
    asyncio.run(scenario())


def test_direct_generic_does_not_dispatch_after_selector_changes_during_save():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        store = Store()
        save = store.async_save
        async def switch_profile():
            hass.states.get('sensor.connected_vehicle').state = 'tesla'
            await save()
        store.async_save = switch_profile
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        actions._dynamic_ev_state.clear()
        params = {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'}
        assert not await actions._action_stop_ev_charging(hass, entry, params)
        assert hass.services.async_call.await_count == 0
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())


def test_failed_store_emits_two_minute_warning_once(monkeypatch):
    from datetime import timedelta
    from unittest.mock import Mock
    from power_sync import action_events
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        store = Store()
        async def fail():
            raise OSError('storage unavailable')
        store.async_save = fail
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        notice = Mock(return_value=True)
        monkeypatch.setattr(action_events, '_notification', notice)
        await actions._action_stop_ev_charging(hass, entry, {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', 'owner_mode': 'manual'})
        assert notice.call_count == 1
        pending = actions._dynamic_ev_state[entry.entry_id]['generic_ev']['pending_stop']
        pending['requested_at'] -= timedelta(seconds=121)
        pending['volatile_record']['first_attempt_at'] = pending['requested_at'].isoformat()
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert notice.call_count == 2
        assert actions.is_shared_stop_fenced(hass, entry, 'generic_ev')
    asyncio.run(scenario())


def test_external_settlement_confirms_only_matching_episode():
    from power_sync.automations.external_session_reconciler import (
        ReconciliationState, load_reconciliation_state, persist_reconciliation_state,
    )
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        store = Store()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        state = ReconciliationState(origin='external', active_profile_id='shared_ev_profile_a',
                                    observed_session_token='episode-a', temporary_external_lease_token='episode-a',
                                    stop_outcome={'status': 'pending'})
        await persist_reconciliation_state(hass, entry, 'generic_ev', state)
        ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner='external', owner_mode='external', extra={'active_profile_id': 'shared_ev_profile_a', 'resolver_stop_lease_token': 'episode-a'})
        await actions._stop_external_shared_session_guarded(hass, entry, {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', '_observed_session_token': 'episode-a'})
        states, original = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or original(key)
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        result = load_reconciliation_state(hass, entry, 'generic_ev')
        assert result.observed_session_token == 'episode-a'
        assert result.stop_outcome == {'status': 'confirmed'}
        assert result.temporary_external_lease_token is None
    asyncio.run(scenario())


def test_external_restart_recovery_observes_without_restoring_lease():
    from copy import deepcopy
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        store = Store()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = store
        ownership.claim_ev_ownership(hass, entry, 'generic_ev', owner='external', owner_mode='external', extra={'active_profile_id': 'shared_ev_profile_a', 'resolver_stop_lease_token': 'episode-a'})
        await actions._stop_external_shared_session_guarded(hass, entry, {**_generic_params(), 'vehicle_id': 'shared_ev_profile_a', '_observed_session_token': 'episode-a'})
        record = store.saved['_shared_pending_stops']['generic_ev']
        recovered_hass = _Hass()
        recovered_hass.states.async_all = lambda: []
        recovered_store = Store()
        recovered_store._data = deepcopy(store.saved)
        recovered_hass.data['power_sync'][entry.entry_id]['automation_store'] = recovered_store
        actions._dynamic_ev_state.clear()
        await actions.async_load_pending_shared_stops(recovered_hass, entry)
        assert actions.is_shared_stop_fenced(recovered_hass, entry, 'generic_ev')
        assert ownership.get_ev_ownership(recovered_hass, entry, 'generic_ev')[1] is None
        assert actions._dynamic_ev_state[entry.entry_id]['generic_ev']['pending_stop']['record']['generation'] == record['generation']
        states, original = {}, recovered_hass.states.get
        recovered_hass.states.get = lambda key: states.get(key) or original(key)
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(recovered_hass, entry)
        assert not actions.is_shared_stop_fenced(recovered_hass, entry, 'generic_ev')
        assert recovered_hass.services.async_call.await_count == 0
        assert ownership.get_ev_ownership(recovered_hass, entry, 'generic_ev')[1] is None
    asyncio.run(scenario())


def test_pending_warning_uses_active_report_and_direct_settlement_clears(monkeypatch):
    from datetime import timedelta
    from unittest.mock import Mock
    from power_sync import action_events
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data["power_sync"][entry.entry_id]["automation_store"] = Store()
        states, get = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or get(key)
        notice = Mock(return_value=True)
        monkeypatch.setattr(action_events, "_notification", notice)
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "owner_mode": "manual"}
        assert not await actions._action_stop_ev_charging(hass, entry, params)
        pending = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]["pending_stop"]
        pending["requested_at"] -= timedelta(seconds=121)
        pending["record"]["first_attempt_at"] = pending["requested_at"].isoformat()
        hass.data["power_sync"][entry.entry_id]["automation_store"]._data["_shared_pending_stops"]["generic_ev"]["first_attempt_at"] = pending["requested_at"].isoformat()
        states["sensor.shared_ev_power"] = SimpleNamespace(state="1500", attributes={"unit_of_measurement": "W"}, last_reported=datetime.now(timezone.utc))
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert "reported charging" in notice.call_args.kwargs["reason"]
        states["sensor.shared_ev_power"].state = "0"
        states["sensor.shared_ev_power"].last_reported = datetime.now(timezone.utc)
        assert await actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "generic_ev"})
        assert notice.call_args.kwargs["clear"] is True
    asyncio.run(scenario())


@pytest.mark.parametrize("charger", ["generic", "sigenergy"])
def test_direct_zero_amps_creates_fenced_stop(monkeypatch, charger):
    from unittest.mock import AsyncMock
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        hass.data["power_sync"][entry.entry_id]["automation_store"] = Store()
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "owner_mode": "manual", "amps": 0}
        if charger == "generic":
            params["charger_switch_entity"] = ""
            entry.options = {**entry.options, "generic_charger_switch_entity": ""}
        else:
            entry.options = {**entry.options, "generic_charger_enabled": False, "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac", "sigenergy_charger_host": "charger.invalid"}
            params = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a", "owner_mode": "manual", "amps": 0}
            class Controller:
                async def connect(self): return True
                async def stop_charging(self):
                    assert self._shared_write_authorized()
                    stops.append(True)
                    return True
                async def disconnect(self): pass
            stops = []
            monkeypatch.setattr(actions, "_new_sigenergy_charger", lambda config: Controller())
        assert not await actions._action_set_ev_charging_amps(hass, entry, params)
        physical = "generic_ev" if charger == "generic" else "sigenergy_charger"
        assert actions.is_shared_stop_fenced(hass, entry, physical)
        if charger == "generic":
            assert hass.services.async_call.await_count == 1
            assert hass.services.async_call.await_args.args[:2] == ("number", "set_value")
            assert hass.services.async_call.await_args.args[2]["value"] == 0
        else:
            assert len(stops) == 1
        assert not await actions._action_set_ev_charging_amps(hass, entry, params)
        if charger == "generic": assert hass.services.async_call.await_count == 1
        else: assert len(stops) == 1
    asyncio.run(scenario())

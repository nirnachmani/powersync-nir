"""Focused classification of EVAC stops which never reached dispatch."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_shared_loadpoint_action_guard import _Entry, _Hass, actions
from test_shared_stop_storage import Store


@pytest.mark.parametrize('outcome, expected', [
    ('connect_false', 'connect_rejected_before_dispatch'),
    ('connect_timeout', 'unknown'),
    ('write_false', 'unknown'),
])
def test_stop_failure_classification(monkeypatch, outcome, expected):
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        entry.options = {**entry.options, 'generic_charger_enabled': False,
                         'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac',
                         'sigenergy_charger_host': 'charger.invalid'}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        params = {'charger_type': 'sigenergy', 'vehicle_id': 'shared_ev_profile_a',
                  'dynamic_mode': 'battery_target', 'owner_mode': 'battery_target',
                  'fixed_charge_amps': 8, 'max_charge_amps': 8, 'notify_on_start': False}
        monkeypatch.setattr(actions, '_start_sigenergy_charger', AsyncMock(return_value=True))
        monkeypatch.setattr(actions, '_set_sigenergy_charger_amps', AsyncMock(return_value=True))
        controller = SimpleNamespace(connect=AsyncMock(return_value=outcome == 'write_false'),
                                     disconnect=AsyncMock())
        if outcome == 'connect_timeout':
            controller.connect.side_effect = asyncio.TimeoutError()
        async def stop_charging():
            assert controller._shared_write_authorized()
            return False
        controller.stop_charging = AsyncMock(side_effect=stop_charging)
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        assert not await actions._action_stop_ev_charging_dynamic(
            hass, entry, {'vehicle_id': 'sigenergy_charger', 'stop_charging': True})
        record = hass.data['power_sync'][entry.entry_id]['automation_store'].saved['_shared_pending_stops']['sigenergy_charger']
        assert record['last_status'] == expected
        assert record['attempt_count'] == 1
        assert (record['dispatch_at'] is not None) == (outcome == 'write_false')
        assert controller.stop_charging.await_count == (outcome == 'write_false')
    asyncio.run(scenario())


def test_regular_cycle_retries_only_at_thirty_seconds_and_caps_attempts(monkeypatch):
    from datetime import datetime, timedelta, timezone
    class Clock(datetime):
        now_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None):
            return cls.now_value
    async def scenario():
        monkeypatch.setattr(actions, "datetime", Clock)
        hass, entry = _Hass(), _Entry()
        store = Store()
        hass.data["power_sync"][entry.entry_id]["automation_store"] = store
        entry.options = {**entry.options, "generic_charger_enabled": False,
                         "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac",
                         "sigenergy_charger_host": "charger.invalid"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        monkeypatch.setattr(actions, "_start_sigenergy_charger", AsyncMock(return_value=True))
        monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", AsyncMock(return_value=True))
        controller = SimpleNamespace(connect=AsyncMock(return_value=False), disconnect=AsyncMock(),
                                     stop_charging=AsyncMock())
        monkeypatch.setattr(actions, "_new_sigenergy_charger", lambda config: controller)
        params = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a",
                  "dynamic_mode": "battery_target", "owner_mode": "battery_target",
                  "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        assert not await actions._action_stop_ev_charging_dynamic(
            hass, entry, {"vehicle_id": "sigenergy_charger", "stop_charging": True})
        first = store.saved["_shared_pending_stops"]["sigenergy_charger"]["first_attempt_at"]
        Clock.now_value += timedelta(seconds=29.9)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 1
        Clock.now_value += timedelta(seconds=.1)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 2
        Clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        Clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 3
        record = store.saved["_shared_pending_stops"]["sigenergy_charger"]
        assert record["attempt_count"] == 3
        assert record["first_attempt_at"] == first
    asyncio.run(scenario())


async def _retry_setup(monkeypatch, *, handoff=False):
    from datetime import datetime, timezone
    class Clock(datetime):
        now_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None):
            return cls.now_value
    monkeypatch.setattr(actions, "datetime", Clock)
    hass, entry = _Hass(), _Entry()
    store = Store()
    hass.data["power_sync"][entry.entry_id]["automation_store"] = store
    entry.options = {**entry.options, "generic_charger_enabled": False,
                     "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac",
                     "sigenergy_charger_host": "charger.invalid"}
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    monkeypatch.setattr(actions, "_start_sigenergy_charger", AsyncMock(return_value=True))
    monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", AsyncMock(return_value=True))
    controller = SimpleNamespace(connect=AsyncMock(return_value=False), disconnect=AsyncMock(),
                                 stop_charging=AsyncMock())
    monkeypatch.setattr(actions, "_new_sigenergy_charger", lambda config: controller)
    params = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a",
              "dynamic_mode": "battery_target", "owner_mode": "battery_target",
              "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
    token = None
    if handoff:
        state = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]
        capability = {"_shared_handoff_stop_authorization": actions._SHARED_HANDOFF_STOP_AUTHORIZATION,
                      "_shared_handoff_outgoing_profile_id": "shared_ev_profile_a"}
        token = actions._direct_shared_stop_owner.set((asyncio.current_task(), state, None, capability))
        hass.states.get("sensor.connected_vehicle").state = "tesla"
    try:
        assert not await actions._action_stop_ev_charging_dynamic(
            hass, entry, {"vehicle_id": "sigenergy_charger", "stop_charging": True})
    finally:
        if token is not None:
            actions._direct_shared_stop_owner.reset(token)
    return hass, entry, store, controller, Clock


@pytest.mark.parametrize("outcome", ["success", "write_false", "timeout", "cancelled"])
def test_retry_outcomes_are_not_repeated(monkeypatch, outcome):
    from datetime import timedelta
    async def scenario():
        hass, entry, store, controller, clock = await _retry_setup(monkeypatch)
        if outcome in ("success", "write_false"):
            controller.connect.return_value = True
            async def stop():
                assert controller._shared_write_authorized()
                return outcome == "success"
            controller.stop_charging.side_effect = stop
        else:
            controller.connect.side_effect = (asyncio.TimeoutError() if outcome == "timeout"
                                              else asyncio.CancelledError())
        clock.now_value += timedelta(seconds=30)
        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await actions.async_reconcile_pending_shared_stops(hass, entry)
        else:
            await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert store.saved["_shared_pending_stops"]["sigenergy_charger"]["last_status"] in ("unknown", "unconfirmed")
        controller.connect.side_effect = None
        clock.now_value += timedelta(seconds=90)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["lease", "selector", "binding", "session", "fence", "generation", "recovered"])
def test_retry_rejects_changed_identity(monkeypatch, change):
    from datetime import timedelta
    async def scenario():
        hass, entry, store, controller, clock = await _retry_setup(monkeypatch)
        state = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]
        pending = state["pending_stop"]
        if change == "lease":
            owners = hass.data["power_sync"][entry.entry_id]["ev_ownership"]
            owners["sigenergy_charger"] = dict(pending["lease"])
        elif change == "selector":
            hass.states.get("sensor.connected_vehicle").state = "tesla"
        elif change == "binding":
            entry.options["sigenergy_charger_host"] = "different.invalid"
        elif change == "session":
            state["session_id"] = "new-session"
        elif change == "fence":
            hass.data["power_sync"][entry.entry_id]["_shared_stop_fences"]["sigenergy_charger"] = {}
        elif change == "generation":
            pending["record"]["generation"] = "other"
            # A CAS mismatch must not authorize a command.
        else:
            pending["recovered"] = True
        clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 1
    asyncio.run(scenario())


def test_retry_store_failure_still_attempts_and_tracks_in_memory(monkeypatch):
    from datetime import timedelta
    async def scenario():
        hass, entry, store, controller, clock = await _retry_setup(monkeypatch)
        warning = Mock()
        monkeypatch.setattr(actions, "_warn_shared_stop_storage_failure", warning)
        async def fail():
            raise OSError("disk failed")
        store.async_save = fail
        clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 2
        warning.assert_called()
        pending = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]["pending_stop"]
        assert pending["record"] is None
        assert pending["volatile_record"]["attempt_count"] == 2
        assert pending["volatile_record"]["last_status"] == "connect_rejected_before_dispatch"
        clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 3
        assert pending["volatile_record"]["attempt_count"] == 3
    asyncio.run(scenario())


def test_retry_preserves_outgoing_handoff_authorization(monkeypatch):
    from datetime import timedelta
    async def scenario():
        hass, entry, store, controller, clock = await _retry_setup(monkeypatch, handoff=True)
        assert controller.connect.await_count == 1
        clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == 2
    asyncio.run(scenario())


def test_retry_marks_unknown_before_connect_and_rechecks_after_await(monkeypatch):
    from datetime import timedelta
    async def scenario():
        hass, entry, store, controller, clock = await _retry_setup(monkeypatch)
        async def connect():
            saved = store.saved["_shared_pending_stops"]["sigenergy_charger"]
            assert saved["last_status"] == "unknown"
            assert saved["attempt_count"] == 2
            hass.states.get("sensor.connected_vehicle").state = "tesla"
            return True
        controller.connect.side_effect = connect
        clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        controller.stop_charging.assert_not_awaited()
        assert store.saved["_shared_pending_stops"]["sigenergy_charger"]["last_status"] == "unknown"
    asyncio.run(scenario())


@pytest.mark.parametrize("changed", [False, True])
def test_external_retry_checks_observed_session_identity(monkeypatch, changed):
    from datetime import timedelta
    import importlib
    async def scenario():
        hass, entry, store, controller, clock = await _retry_setup(monkeypatch)
        pending = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]["pending_stop"]
        pending["lease"]["owner"] = "external"
        pending["lease"]["resolver_stop_lease_token"] = "lease-token"
        pending["lease_identity"]["owner"] = "external"
        pending["lease_identity"]["resolver_stop_lease_token"] = "lease-token"
        record = pending["record"]
        record.update(owner_kind="external", observed_session_token="session-token",
                      resolver_stop_lease_token="lease-token")
        store._data["_shared_pending_stops"]["sigenergy_charger"] = dict(record)
        reconciler = importlib.import_module(actions.__package__ + ".external_session_reconciler")
        monkeypatch.setattr(reconciler, "load_reconciliation_state", lambda *a: SimpleNamespace(
            observed_session_token="new-session" if changed else "session-token",
            active_profile_id="shared_ev_profile_a", temporary_external_lease_token="lease-token"))
        clock.now_value += timedelta(seconds=30)
        await actions.async_reconcile_pending_shared_stops(hass, entry)
        assert controller.connect.await_count == (1 if changed else 2)
    asyncio.run(scenario())

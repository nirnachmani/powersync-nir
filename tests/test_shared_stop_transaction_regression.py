"""Regression for a managed stop on a real shared physical lease."""
import asyncio

import pytest
from unittest.mock import MagicMock

from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store


@pytest.fixture(autouse=True)
def shared_store(monkeypatch, request):
    if request.node.name == "test_missing_store_attempts_stop_and_retains_fence":
        return
    original = _Hass.__init__
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.data["power_sync"]["entry-1"]["automation_store"] = Store()
    monkeypatch.setattr(_Hass, "__init__", init)


def test_missing_store_attempts_stop_and_retains_fence():
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    lease = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    hass.services.async_call.reset_mock()
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
    assert hass.services.async_call.await_args.args[:2] == ("switch", "turn_off")
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is lease
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"]["pending_stop"]


def test_save_failure_warns_and_attempts_stop_once(monkeypatch):
    import importlib
    events = importlib.import_module("power_sync.action_events")
    warning = MagicMock(return_value=True)
    monkeypatch.setattr(events, "_notification", warning)
    from unittest.mock import AsyncMock
    push = AsyncMock()
    monkeypatch.setattr(actions, "_send_expo_push", push)
    hass, entry = _Hass(), _Entry()
    hass.bus = type("Bus", (), {"async_fire": MagicMock()})()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    store = hass.data["power_sync"][entry.entry_id]["automation_store"]
    async def fail():
        raise OSError("disk unavailable")
    store.async_save = fail
    lease = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    hass.services.async_call.reset_mock()
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert hass.services.async_call.await_count == 1
    assert hass.services.async_call.await_args.args[:2] == ("switch", "turn_off")
    assert warning.call_count == 1
    assert any(c.args[0] == "power_sync_ev_stop_failed" for c in hass.bus.async_fire.call_args_list)
    push.assert_not_awaited()
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert hass.services.async_call.await_count == 1
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is lease


def test_report_during_save_is_not_post_dispatch_evidence():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    states, get = {}, hass.states.get
    hass.states.get = lambda key: states.get(key) or get(key)
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    store = hass.data["power_sync"][entry.entry_id]["automation_store"]
    save = store.async_save
    async def save_with_report():
        if "sensor.shared_ev_power" not in states:
            states["sensor.shared_ev_power"] = SimpleNamespace(state="0",
                attributes={"unit_of_measurement": "W"}, last_reported=datetime.now(timezone.utc))
        await save()
    store.async_save = save_with_report
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    store.async_save = save
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is not None


def test_write_ahead_store_save_precedes_dispatch():
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    store = hass.data["power_sync"][entry.entry_id]["automation_store"]
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    seen = []
    async def check(*args, **kwargs):
        record = store.saved["_shared_pending_stops"]["generic_ev"]
        assert record["last_status"] == "pending"
        assert record["session_id"] and record["generation"]
        assert record["binding_id"] == "generic_ev"
        assert record["profile_id"] == "shared_ev_profile_a"
        assert "notify_on_start" not in record["parameters"]
        seen.append(record)
    hass.services.async_call.side_effect = check
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
    assert len(seen) == 1
    assert store.saved["_shared_pending_stops"]["generic_ev"]["last_status"] == "unconfirmed"


def test_owner_change_during_delete_preserves_persisted_fence():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        states, get = {}, hass.states.get
        hass.states.get = lambda key: states.get(key) or get(key)
        actions._dynamic_ev_state.clear()
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
                  "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
                  "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        stop = {"vehicle_id": "generic_ev", "stop_charging": True}
        assert not await actions._action_stop_ev_charging_dynamic(hass, entry, stop)
        states["sensor.shared_ev_power"] = SimpleNamespace(state="0",
            attributes={"unit_of_measurement": "W"}, last_reported=datetime.now(timezone.utc))
        store = hass.data["power_sync"][entry.entry_id]["automation_store"]
        save = store.async_save
        async def change_owner_during_save():
            ownership.claim_ev_ownership(hass, entry, "generic_ev", owner_mode="manual", session_id="new")
            await save()
        store.async_save = change_owner_during_save
        assert not await actions._action_stop_ev_charging_dynamic(hass, entry, stop)
        assert actions.is_shared_stop_fenced(hass, entry, "generic_ev")
        assert store.saved["_shared_pending_stops"].get("generic_ev")
    asyncio.run(scenario())


def test_delete_failure_retains_lease_and_runtime():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    states, get = {}, hass.states.get
    hass.states.get = lambda key: states.get(key) or get(key)
    store = hass.data["power_sync"][entry.entry_id]["automation_store"]
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    lease = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    states["sensor.shared_ev_power"] = SimpleNamespace(state="0",
        attributes={"unit_of_measurement": "W"}, last_reported=datetime.now(timezone.utc))
    async def fail():
        raise OSError("disk unavailable")
    store.async_save = fail
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"] is runtime
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is lease


def test_delete_failure_warns_without_reissuing_stop(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import importlib
    events = importlib.import_module("power_sync.action_events")
    warning = MagicMock(return_value=True)
    monkeypatch.setattr(events, "_notification", warning)
    hass, entry = _Hass(), _Entry()
    hass.bus = SimpleNamespace(async_fire=MagicMock())
    hass.states.async_all = lambda: []
    states, get = {}, hass.states.get
    hass.states.get = lambda key: states.get(key) or get(key)
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    hass.services.async_call.reset_mock()
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    states["sensor.shared_ev_power"] = SimpleNamespace(state="0", attributes={"unit_of_measurement": "W"},
                                                       last_reported=datetime.now(timezone.utc))
    async def fail():
        raise OSError("disk unavailable")
    hass.data["power_sync"][entry.entry_id]["automation_store"].async_save = fail
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert warning.call_count == 1
    assert any(c.args[0] == "power_sync_ev_stop_failed" for c in hass.bus.async_fire.call_args_list)
    assert hass.services.async_call.await_count == 1


def test_cancelled_dispatch_records_unknown_without_retry():
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    store = hass.data["power_sync"][entry.entry_id]["automation_store"]
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    hass.services.async_call.reset_mock()
    hass.services.async_call.side_effect = asyncio.CancelledError
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert store.saved["_shared_pending_stops"]["generic_ev"]["last_status"] == "unknown"
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert hass.services.async_call.await_count == 1


def test_smart_schedule_stop_retains_original_lease_until_post_stop_observation():
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, {
        **_generic_params(), "vehicle_id": "shared_ev_profile_a",
        "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
        "fixed_charge_amps": 8, "max_charge_amps": 8,
        "notify_on_complete": False,
    })) is True
    original = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    hass.services.async_call.reset_mock()

    result = asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, {
        "vehicle_id": "generic_ev", "stop_charging": True,
        "stop_reason": "EV reached target 52",
    }))

    # The service acknowledgement is not post-stop power evidence.
    assert result is False
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is original
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"] is runtime
    assert hass.services.async_call.await_args_list[-1].args == (
        "switch", "turn_off", {"entity_id": "switch.shared_ev"}
    )


@pytest.mark.parametrize("failure", [None, RuntimeError("service failed")])
def test_pending_stop_is_not_reissued_and_blocks_start(failure):
    hass, entry = _Hass(profile_a_soc="50"), _Entry()
    entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {
        **_generic_params(), "vehicle_id": "shared_ev_profile_a",
        "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
        "fixed_charge_amps": 8, "max_charge_amps": 8,
        "notify_on_start": False, "notify_on_complete": False,
    }
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    original = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    hass.services.async_call.reset_mock()
    hass.services.async_call.side_effect = failure
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}

    assert asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop)) is False
    assert runtime["pending_stop"]["status"] == ("failed" if failure else "unconfirmed")
    assert runtime["pending_stop"]["requested_at"].tzinfo is not None
    assert runtime["pending_stop"]["params"]["vehicle_id"] == "generic_ev"
    assert asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop)) is False
    assert asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": False}
    )) is False
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start)) is False
    assert asyncio.run(actions._set_vehicle_amps(hass, entry, "generic_ev", 8, runtime["params"])) is False
    assert hass.services.async_call.await_count == 1
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is original
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"] is runtime



def test_direct_start_cannot_bypass_pending_shared_stop():
    hass, entry = _Hass(profile_a_soc="50"), _Entry()
    entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
    hass.services.async_call.reset_mock()
    assert not asyncio.run(actions._action_start_ev_charging(hass, entry, start))
    hass.services.async_call.assert_not_awaited()


def test_active_profile_handoff_persists_outgoing_pending_stop(monkeypatch):
    import importlib
    from types import SimpleNamespace
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
              "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
              "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, params))
    old = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    lease = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    hass.states.get("sensor.connected_vehicle").state = "tesla"
    reconciler = importlib.import_module("power_sync.automations.external_session_reconciler")
    monkeypatch.setattr(reconciler, "generic_observation_from_hass",
                        lambda *a, **k: SimpleNamespace(fresh=True, charging=True))
    monkeypatch.setattr(reconciler, "reconcile_shared_external_session",
                        lambda *a, **k: SimpleNamespace(active_profile_id="shared_ev_profile_a"))
    async def legacy_handoff(*args, **kwargs):
        pytest.fail("active handoff must use the pending stop transaction")
    monkeypatch.setattr(reconciler, "stop_and_confirm_shared_handoff", legacy_handoff)
    hass.services.async_call.reset_mock()
    assert not asyncio.run(actions._action_start_ev_charging_dynamic(
        hass, entry, {**params, "vehicle_id": "shared_ev_profile_b"}))
    assert actions.is_shared_stop_fenced(hass, entry, "generic_ev")
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"] is old
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is lease
    assert hass.data["power_sync"][entry.entry_id]["automation_store"].saved["_shared_pending_stops"]["generic_ev"]
    assert hass.services.async_call.await_args.args[:2] == ("switch", "turn_off")


def test_direct_stop_ack_does_not_release_managed_shared_owner():
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
              "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
              "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, params))
    lease = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    hass.services.async_call.reset_mock()
    assert not asyncio.run(actions._action_stop_ev_charging(hass, entry, params))
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is lease
    assert actions.is_shared_stop_fenced(hass, entry, "generic_ev")
    assert hass.services.async_call.await_args.args[:2] == ("switch", "turn_off")


def test_direct_evac_stop_ack_retains_managed_owner(monkeypatch):
    from unittest.mock import AsyncMock

    hass, entry = _Hass(), _Entry()
    entry.options = {**entry.options, "generic_charger_enabled": False,
                     "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac",
                     "sigenergy_charger_host": "charger.invalid"}
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    params = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a",
              "dynamic_mode": "battery_target", "owner_mode": "battery_target",
              "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    monkeypatch.setattr(actions, "_start_sigenergy_charger", AsyncMock(return_value=True))
    monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", AsyncMock(return_value=True))
    async def stop(*args):
        actions._mark_shared_stop_dispatch()
        return True
    stopped = AsyncMock(side_effect=stop)
    monkeypatch.setattr(actions, "_stop_sigenergy_charger", stopped)
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, params))
    lease = ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1]
    assert not asyncio.run(actions._action_stop_ev_charging(hass, entry, params))
    assert ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is lease
    assert actions.is_shared_stop_fenced(hass, entry, "sigenergy_charger")
    assert actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]["pending_stop"]["status"] == "unconfirmed"
    stopped.assert_awaited_once()


def test_direct_start_waiting_in_wake_cannot_resume_after_stop(monkeypatch):
    async def scenario():
        hass, entry = _Hass(profile_a_soc="50"), _Entry()
        entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
                 "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
                 "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, start)
        hass.services.async_call.reset_mock()
        entered, resume, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def service(domain, operation, *args, **kwargs):
            if (domain, operation) == ("switch", "turn_off"):
                hass.states.get("switch.shared_ev").state = "off"
                stopped.set()
        hass.services.async_call.side_effect = service
        async def wait_wake(*args):
            entered.set()
            await resume.wait()
            return True
        monkeypatch.setattr(actions, "_run_pre_charge_wake_sequence", wait_wake)
        queued = asyncio.create_task(actions._action_start_ev_charging(hass, entry, start))
        await asyncio.wait_for(entered.wait(), 1)
        stop = asyncio.create_task(actions._action_stop_ev_charging_dynamic(
            hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
        try:
            await asyncio.wait_for(stopped.wait(), 0.05)
        except TimeoutError:
            # A serialized stop waits until the in-flight start has finished.
            pass
        resume.set()
        await queued
        assert not await stop
        commands = [call.args[:2] for call in hass.services.async_call.await_args_list]
        assert ("switch", "turn_off") in commands
        assert ("switch", "turn_on") not in commands[commands.index(("switch", "turn_off")) + 1:]
    asyncio.run(scenario())


def test_mode_replacement_does_not_start_after_unconfirmed_stop():
    hass, entry = _Hass(profile_a_soc="50"), _Entry()
    entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    lease = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    hass.services.async_call.reset_mock()
    replacement = {**start, "dynamic_mode": "battery_target"}
    assert not asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, replacement))
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"] is runtime
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is lease
    assert hass.services.async_call.await_count == 1
    assert hass.services.async_call.await_args.args[:2] == ("switch", "turn_off")


def test_generic_pending_stop_settles_only_after_fresh_report():
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    states = {}
    get = hass.states.get
    hass.states.get = lambda key: states.get(key) or get(key)
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False,
             "notify_on_complete": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    hass.services.async_call.reset_mock()
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    pending = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]["pending_stop"]
    states["sensor.shared_ev_power"] = SimpleNamespace(state="0", attributes={"unit_of_measurement": "W"},
        last_reported=pending["requested_at"] - timedelta(seconds=1))
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    states["sensor.shared_ev_power"].last_reported = datetime.now(timezone.utc)
    # Reconfiguration must not redirect an already pending stop observation.
    entry.options = {**entry.options, "generic_charger_power_entity": "sensor.other"}
    assert asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is None
    assert "generic_ev" not in actions._dynamic_ev_state.get(entry.entry_id, {})
    assert hass.services.async_call.await_count == 1


@pytest.mark.parametrize("replace_owner", [False, True])
def test_evac_pending_settlement_uses_direct_read_and_fences_new_owner(monkeypatch, replace_owner):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    entry.options = {**entry.options, "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac",
        "sigenergy_charger_host": "charger.invalid"}
    actions._dynamic_ev_state.clear()
    async def dispatch(*args):
        actions._mark_shared_stop_dispatch()
        return True
    physical_stop = AsyncMock(side_effect=dispatch)
    monkeypatch.setattr(actions, "_stop_sigenergy_charger", physical_stop)
    monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", AsyncMock(return_value=True))
    start = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a",
        "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
        "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False,
        "notify_on_complete": False}
    monkeypatch.setattr(actions, "_start_sigenergy_charger", AsyncMock(return_value=True))
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    stop = {"vehicle_id": "sigenergy_charger", "stop_charging": True}
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    runtime = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]
    original = ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1]
    read = AsyncMock(return_value=None)
    controller = SimpleNamespace(_read_input_registers=read, disconnect=AsyncMock())
    monkeypatch.setattr(actions, "_new_sigenergy_charger", lambda config: controller)
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1] is original
    async def read_idle(address, count):
        if replace_owner:
            ownership.claim_ev_ownership(hass, entry, "sigenergy_charger",
                owner_mode="manual", session_id="new-session")
        return [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    read.side_effect = read_idle
    result = asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert result is (not replace_owner)
    lease = ownership.get_ev_ownership(hass, entry, "sigenergy_charger")[1]
    if replace_owner:
        assert lease["session_id"] == "new-session"
        assert actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"] is runtime
    else:
        assert lease is None
        assert "sigenergy_charger" not in actions._dynamic_ev_state.get(entry.entry_id, {})
    assert read.await_args.args == (32000, 12)
    physical_stop.assert_awaited_once()


@pytest.mark.parametrize("change", ["new_owner", "default_alias", "new_session"])
def test_generic_pending_stop_preserves_new_generation_or_default(change):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    states = {}
    get = hass.states.get
    hass.states.get = lambda key: states.get(key) or get(key)
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
        "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
        "fixed_charge_amps": 8, "max_charge_amps": 8,
        "notify_on_start": False, "notify_on_complete": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    hass.services.async_call.reset_mock()
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    original = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    states["sensor.shared_ev_power"] = SimpleNamespace(state="0",
        attributes={"unit_of_measurement": "W"}, last_reported=datetime.now(timezone.utc))
    if change == "new_owner":
        ownership.claim_ev_ownership(hass, entry, "generic_ev", owner_mode="manual", session_id="new")
    elif change == "default_alias":
        ownership.get_ev_ownerships(hass, entry)["_default"] = {"owner_mode": "manual"}
    else:
        runtime["session_id"] = "new"
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"] is runtime
    if change == "default_alias":
        assert ownership.get_ev_ownerships(hass, entry)["_default"]["owner_mode"] == "manual"
    elif change == "new_owner":
        assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1]["session_id"] == "new"
    else:
        assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is original
    assert hass.services.async_call.await_count == 1


def test_newer_history_session_blocks_generic_settlement(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import importlib
    sessions = importlib.import_module("power_sync.automations.ev_charging_session")
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    states = {}
    get = hass.states.get
    hass.states.get = lambda key: states.get(key) or get(key)
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
        "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
        "fixed_charge_amps": 8, "max_charge_amps": 8,
        "notify_on_start": False, "notify_on_complete": False}
    monkeypatch.setattr(sessions, "get_session_manager", lambda: None)
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    lease = ownership.get_ev_ownership(hass, entry, "generic_ev")[1]
    states["sensor.shared_ev_power"] = SimpleNamespace(state="0",
        attributes={"unit_of_measurement": "W"}, last_reported=datetime.now(timezone.utc))
    manager = SimpleNamespace(_session_lock=asyncio.Lock(),
        active_sessions={"generic_ev": SimpleNamespace(id="new")},
        _end_session_unlocked=AsyncMock())
    monkeypatch.setattr(sessions, "get_session_manager", lambda: manager)
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"] is runtime
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is lease
    manager._end_session_unlocked.assert_not_awaited()


@pytest.mark.parametrize("history_failure", [False, True])
def test_settlement_finalizes_only_matching_history_without_blocking_release(monkeypatch, history_failure):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import importlib
    sessions = importlib.import_module("power_sync.automations.ev_charging_session")
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    states = {}
    get = hass.states.get
    hass.states.get = lambda key: states.get(key) or get(key)
    actions._dynamic_ev_state.clear()
    monkeypatch.setattr(sessions, "get_session_manager", lambda: None)
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
        "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
        "fixed_charge_amps": 8, "max_charge_amps": 8,
        "notify_on_start": False, "notify_on_complete": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    runtime["session_id"] = "old-session"
    stop = {"vehicle_id": "generic_ev", "stop_charging": True}
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    states["sensor.shared_ev_power"] = SimpleNamespace(state="0",
        attributes={"unit_of_measurement": "W"}, last_reported=datetime.now(timezone.utc))
    finish = AsyncMock(side_effect=RuntimeError("history failure") if history_failure else None)
    manager = SimpleNamespace(_session_lock=asyncio.Lock(),
        active_sessions={"generic_ev": SimpleNamespace(id="old-session")},
        _end_session_unlocked=finish)
    monkeypatch.setattr(sessions, "get_session_manager", lambda: manager)
    assert asyncio.run(actions._action_stop_ev_charging_dynamic(hass, entry, stop))
    assert ownership.get_ev_ownership(hass, entry, "generic_ev")[1] is None
    finish.assert_awaited_once()


def test_restart_recovers_fence_without_reissuing_stop():
    import json
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
    saved = json.loads(json.dumps(hass.data["power_sync"][entry.entry_id]["automation_store"].saved))
    restarted = _Hass()
    restarted.states.async_all = lambda: []
    restarted.data["power_sync"][entry.entry_id]["automation_store"] = Store(saved)
    actions._dynamic_ev_state.clear()
    asyncio.run(actions.async_load_pending_shared_stops(restarted, entry))
    assert actions._dynamic_ev_state[entry.entry_id]["generic_ev"]["pending_stop"]
    assert ownership.get_ev_ownership(restarted, entry, "generic_ev")[1] is None
    asyncio.run(actions.async_reconcile_pending_shared_stops(restarted, entry))
    assert not asyncio.run(actions._action_start_ev_charging_dynamic(restarted, entry, start))
    restarted.services.async_call.assert_not_awaited()


def test_restart_fresh_idle_settles_without_owner_or_command():
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
    saved = json.loads(json.dumps(hass.data["power_sync"][entry.entry_id]["automation_store"].saved))
    restarted = _Hass()
    restarted.states.async_all = lambda: []
    get = restarted.states.get
    reported = datetime.now(timezone.utc)
    restarted.states.get = lambda key: (SimpleNamespace(state="0", attributes={"unit_of_measurement": "W"},
        last_reported=reported) if key == "sensor.shared_ev_power" else get(key))
    store = Store(saved)
    restarted.data["power_sync"][entry.entry_id]["automation_store"] = store
    actions._dynamic_ev_state.clear()
    asyncio.run(actions.async_load_pending_shared_stops(restarted, entry))
    asyncio.run(actions.async_reconcile_pending_shared_stops(restarted, entry))
    assert "generic_ev" not in actions._dynamic_ev_state.get(entry.entry_id, {})
    assert store.saved["_shared_pending_stops"] == {}
    restarted.services.async_call.assert_not_awaited()


def test_shared_stop_fence_api_tracks_recovered_record():
    hass, entry = _Hass(), _Entry()
    actions._dynamic_ev_state.clear()
    assert not actions.is_shared_stop_fenced(hass, entry, "generic_ev")
    actions._dynamic_ev_state[entry.entry_id] = {"generic_ev": {"pending_stop": {"recovered": True}}}
    assert actions.is_shared_stop_fenced(hass, entry, "generic_ev")
    assert not actions.is_shared_stop_fenced(hass, entry, "sigenergy_charger")


def test_recovered_warning_after_two_minutes_is_persisted_once(monkeypatch):
    import json, importlib
    from datetime import datetime, timezone, timedelta
    events = importlib.import_module("power_sync.action_events")
    notification = MagicMock(return_value=True)
    monkeypatch.setattr(events, "_notification", notification)
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
    saved = json.loads(json.dumps(hass.data["power_sync"][entry.entry_id]["automation_store"].saved))
    saved["_shared_pending_stops"]["generic_ev"]["first_attempt_at"] = (datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()
    restarted = _Hass()
    restarted.states.async_all = lambda: []
    store = Store(saved)
    restarted.data["power_sync"][entry.entry_id]["automation_store"] = store
    actions._dynamic_ev_state.clear()
    asyncio.run(actions.async_load_pending_shared_stops(restarted, entry))
    asyncio.run(actions.async_reconcile_pending_shared_stops(restarted, entry))
    assert notification.call_count == 1
    assert store.saved["_shared_pending_stops"]["generic_ev"]["alerted"] is True
    again = _Hass()
    again.states.async_all = lambda: []
    again.data["power_sync"][entry.entry_id]["automation_store"] = Store(json.loads(json.dumps(store.saved)))
    actions._dynamic_ev_state.clear()
    asyncio.run(actions.async_load_pending_shared_stops(again, entry))
    asyncio.run(actions.async_reconcile_pending_shared_stops(again, entry))
    assert notification.call_count == 1
    again.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("change", ["binding", "pre_dispatch", "new_owner", "unknown_dispatch"])
def test_recovered_stop_remains_fenced_without_exact_evidence(change):
    import json
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    hass, entry = _Hass(), _Entry()
    hass.states.async_all = lambda: []
    actions._dynamic_ev_state.clear()
    start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
             "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
             "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
    assert asyncio.run(actions._action_start_ev_charging_dynamic(hass, entry, start))
    assert not asyncio.run(actions._action_stop_ev_charging_dynamic(
        hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
    saved = json.loads(json.dumps(hass.data["power_sync"][entry.entry_id]["automation_store"].saved))
    record = saved["_shared_pending_stops"]["generic_ev"]
    reported = datetime.fromisoformat(record["dispatch_at"]) - timedelta(seconds=1) if change == "pre_dispatch" else datetime.now(timezone.utc)
    if change == "unknown_dispatch":
        record["dispatch_at"] = None
        record["last_status"] = "pending"
    restarted = _Hass()
    restarted.states.async_all = lambda: []
    get = restarted.states.get
    restarted.states.get = lambda key: (SimpleNamespace(state="0", attributes={"unit_of_measurement": "W"},
        last_reported=reported) if key == "sensor.shared_ev_power" else get(key))
    restarted.data["power_sync"][entry.entry_id]["automation_store"] = Store(saved)
    actions._dynamic_ev_state.clear()
    asyncio.run(actions.async_load_pending_shared_stops(restarted, entry))
    if change == "binding":
        entry.options = {**entry.options, "generic_charger_power_entity": "sensor.replaced"}
    if change == "new_owner":
        ownership.claim_ev_ownership(restarted, entry, "generic_ev", owner_mode="manual", session_id="new")
    asyncio.run(actions.async_reconcile_pending_shared_stops(restarted, entry))
    assert actions.is_shared_stop_fenced(restarted, entry, "generic_ev")
    restarted.services.async_call.assert_not_awaited()


def test_fence_lookup_does_not_require_dynamic_runtime():
    hass, entry = _Hass(), _Entry()
    actions._dynamic_ev_state.clear()
    hass.data["power_sync"][entry.entry_id]["_shared_stop_fences"] = {"generic_ev": {"recovered": True}}
    assert actions.is_shared_stop_fenced(hass, entry, "generic_ev")


def test_cancelled_recovery_deletion_keeps_in_memory_fence():
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "smart_schedule",
                 "owner_mode": "smart_schedule", "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, start)
        assert not await actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True})
        saved = json.loads(json.dumps(hass.data["power_sync"][entry.entry_id]["automation_store"].saved))
        restarted = _Hass()
        restarted.states.async_all = lambda: []
        report = datetime.now(timezone.utc)
        get = restarted.states.get
        restarted.states.get = lambda key: (SimpleNamespace(state="0", attributes={"unit_of_measurement": "W"}, last_reported=report) if key == "sensor.shared_ev_power" else get(key))
        store = Store(saved)
        restarted.data["power_sync"][entry.entry_id]["automation_store"] = store
        actions._dynamic_ev_state.clear()
        await actions.async_load_pending_shared_stops(restarted, entry)
        entered = asyncio.Event()
        async def block():
            entered.set()
            await asyncio.Event().wait()
        store.async_save = block
        task = asyncio.create_task(actions.async_reconcile_pending_shared_stops(restarted, entry))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert actions.is_shared_stop_fenced(restarted, entry, "generic_ev")
        restarted.services.async_call.assert_not_awaited()
    asyncio.run(scenario())


def test_pending_direct_positive_current():
    async def run():
        hass, entry = _Hass(profile_a_soc='50'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        p = {**_generic_params(), 'vehicle_id':'shared_ev_profile_a', 'dynamic_mode':'smart_schedule', 'owner_mode':'smart_schedule', 'fixed_charge_amps':8, 'max_charge_amps':8, 'notify_on_start':False, 'amps':8}
        assert await actions._action_start_ev_charging_dynamic(hass,entry,p)
        assert not await actions._action_stop_ev_charging_dynamic(hass,entry,{'vehicle_id':'generic_ev','stop_charging':True})
        assert actions._dynamic_ev_state[entry.entry_id]['generic_ev']['pending_stop']
        hass.services.async_call.reset_mock()
        result = await actions._action_set_ev_charging_amps(hass,entry,p)
        print('direct rate result',result,'service calls',hass.services.async_call.await_args_list)
        assert not result
        hass.services.async_call.assert_not_awaited()
    asyncio.run(run())

def test_dynamic_rate_wake_after_pending_stop(monkeypatch):
    async def run():
        hass, entry = _Hass(profile_a_soc='50'), _Entry()
        entry.options = {**entry.options, 'shared_loadpoint_profile_a_soc_entity': 'sensor.tank_soc'}
        hass.data['power_sync'][entry.entry_id]['automation_store'] = Store()
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        p = {**_generic_params(), 'vehicle_id':'shared_ev_profile_a', 'dynamic_mode':'smart_schedule', 'owner_mode':'smart_schedule', 'fixed_charge_amps':8, 'max_charge_amps':8, 'notify_on_start':False}
        assert await actions._action_start_ev_charging_dynamic(hass,entry,p)
        state=actions._dynamic_ev_state[entry.entry_id]['generic_ev']
        entered,resume=asyncio.Event(),asyncio.Event()
        async def wake(*args):
            entered.set(); await resume.wait(); return True
        monkeypatch.setattr(actions,'_run_pre_charge_wake_sequence',wake)
        hass.services.async_call.reset_mock()
        task=asyncio.create_task(actions._set_vehicle_amps(hass,entry,'generic_ev',8,state['params']))
        await asyncio.wait_for(entered.wait(),1)
        stop = asyncio.create_task(actions._action_stop_ev_charging_dynamic(hass,entry,{'vehicle_id':'generic_ev','stop_charging':True}))
        await asyncio.sleep(0)
        assert not stop.done()
        resume.set(); result=await task
        assert not await stop
        commands=[x.args[:2] for x in hass.services.async_call.await_args_list]
        print('rate result',result,'commands',commands)
        assert not commands[commands.index(('switch','turn_off'))+1:]
    asyncio.run(run())


def test_pending_stop_during_current_write_blocks_later_start():
    async def scenario():
        hass, entry = _Hass(profile_a_soc="50"), _Entry()
        entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule", "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
        entered, resume = asyncio.Event(), asyncio.Event()
        async def service(domain, operation, *args, **kwargs):
            if (domain, operation) == ("number", "set_value"):
                entered.set()
                await resume.wait()
        hass.services.async_call.reset_mock()
        hass.services.async_call.side_effect = service
        task = asyncio.create_task(actions._set_vehicle_amps(hass, entry, "generic_ev", 8, runtime["params"]))
        await asyncio.wait_for(entered.wait(), 1)
        stop = asyncio.create_task(actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
        await asyncio.sleep(0)
        assert not stop.done()
        resume.set()
        await task
        assert not await stop
        calls = [c.args[:2] for c in hass.services.async_call.await_args_list]
        assert ("switch", "turn_on") not in calls[calls.index(("switch", "turn_off")) + 1:]
    asyncio.run(scenario())


def test_stop_fence_waits_for_inflight_physical_current():
    async def scenario():
        hass, entry = _Hass(profile_a_soc="50"), _Entry()
        entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule", "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
        entered, release = asyncio.Event(), asyncio.Event()
        async def service(domain, operation, *args, **kwargs):
            if (domain, operation) == ("number", "set_value"):
                entered.set()
                await release.wait()
        hass.services.async_call.side_effect = service
        rate = asyncio.create_task(actions._set_vehicle_amps(hass, entry, "generic_ev", 8, runtime["params"]))
        await asyncio.wait_for(entered.wait(), 1)
        stop = asyncio.create_task(actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
        await asyncio.sleep(0.02)
        try:
            assert not actions.is_shared_stop_fenced(hass, entry, "generic_ev")
            assert not stop.done()
        finally:
            release.set()
            await asyncio.gather(rate, stop)
    asyncio.run(scenario())


def test_pending_stop_blocks_queued_direct_and_dynamic_current():
    async def scenario():
        hass, entry = _Hass(profile_a_soc="50"), _Entry()
        entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule", "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False, "amps": 8}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
        entered, release = asyncio.Event(), asyncio.Event()
        async def service(domain, operation, *args, **kwargs):
            if (domain, operation) == ("switch", "turn_off"):
                entered.set()
                await release.wait()
        hass.services.async_call.reset_mock()
        hass.services.async_call.side_effect = service
        stop = asyncio.create_task(actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
        await asyncio.wait_for(entered.wait(), 1)
        direct = asyncio.create_task(actions._action_set_ev_charging_amps(hass, entry, params))
        dynamic = asyncio.create_task(actions._set_vehicle_amps(hass, entry, "generic_ev", 8, runtime["params"]))
        start = asyncio.create_task(actions._action_start_ev_charging(hass, entry, params))
        await asyncio.sleep(0)
        assert not direct.done() and not dynamic.done() and not start.done()
        release.set()
        assert await asyncio.gather(stop, direct, dynamic, start) == [False, False, False, False]
        assert [c.args[:2] for c in hass.services.async_call.await_args_list] == [("switch", "turn_off")]
    asyncio.run(scenario())


def test_cancelled_inflight_current_releases_lock_for_stop():
    async def scenario():
        hass, entry = _Hass(profile_a_soc="50"), _Entry()
        entry.options = {**entry.options, "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule", "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        runtime = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
        entered = asyncio.Event()
        async def service(domain, operation, *args, **kwargs):
            if (domain, operation) == ("number", "set_value"):
                entered.set()
                await asyncio.Event().wait()
        hass.services.async_call.reset_mock()
        hass.services.async_call.side_effect = service
        rate = asyncio.create_task(actions._set_vehicle_amps(hass, entry, "generic_ev", 8, runtime["params"]))
        await asyncio.wait_for(entered.wait(), 1)
        stop = asyncio.create_task(actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "generic_ev", "stop_charging": True}))
        await asyncio.sleep(0)
        rate.cancel()
        with pytest.raises(asyncio.CancelledError):
            await rate
        assert not await asyncio.wait_for(stop, 1)
        assert actions.is_shared_stop_fenced(hass, entry, "generic_ev")
        assert hass.services.async_call.await_args.args[:2] == ("switch", "turn_off")
    asyncio.run(scenario())


def test_evac_rate_does_not_start_after_selector_changes(monkeypatch):
    from unittest.mock import AsyncMock
    async def scenario():
        hass, entry = _Hass(), _Entry()
        entry.options = {**entry.options, "generic_charger_enabled": False, "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac", "sigenergy_charger_host": "charger.invalid"}
        actions._dynamic_ev_state.clear()
        params = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "battery_target", "owner_mode": "battery_target"}
        entered, release = asyncio.Event(), asyncio.Event()
        async def rate(*args):
            entered.set()
            await release.wait()
            return True
        start = AsyncMock(return_value=True)
        monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", rate)
        monkeypatch.setattr(actions, "_start_sigenergy_charger", start)
        task = asyncio.create_task(actions._set_vehicle_amps(hass, entry, "shared_ev_profile_a", 8, params))
        await asyncio.wait_for(entered.wait(), 1)
        hass.states.get("sensor.connected_vehicle").state = "tesla"
        release.set()
        assert not await task
        start.assert_not_awaited()
    asyncio.run(scenario())


def test_child_task_cannot_inherit_lock_authority():
    async def scenario():
        hass, entry = _Hass(), _Entry()
        actions._dynamic_ev_state.clear()
        hass.states.get("switch.shared_ev").state = "off"
        params = {**_generic_params(), "vehicle_id": "shared_ev_profile_a", "owner_mode": "manual", "amps": 8}
        entered, release = asyncio.Event(), asyncio.Event()
        child = None
        async def service(domain, operation, *args, **kwargs):
            nonlocal child
            if (domain, operation) == ("switch", "turn_on"):
                child = asyncio.create_task(actions._action_set_ev_charging_amps(hass, entry, params))
                await asyncio.sleep(0)
                assert not child.done()
                entered.set()
                await release.wait()
        hass.services.async_call.side_effect = service
        parent = asyncio.create_task(actions._action_start_ev_charging(hass, entry, params, {}))
        await asyncio.wait_for(entered.wait(), 1)
        release.set()
        assert await parent
        assert await asyncio.wait_for(child, 1)
        assert [c.args[:2] for c in hass.services.async_call.await_args_list] == [("switch", "turn_on"), ("number", "set_value")]
    asyncio.run(scenario())


def test_evac_stop_waits_for_inflight_rate(monkeypatch):
    from unittest.mock import AsyncMock
    async def scenario():
        hass, entry = _Hass(), _Entry()
        entry.options = {**entry.options, "generic_charger_enabled": False, "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac", "sigenergy_charger_host": "charger.invalid"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        params = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "battery_target", "owner_mode": "battery_target", "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        monkeypatch.setattr(actions, "_start_sigenergy_charger", AsyncMock(return_value=True))
        monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", AsyncMock(return_value=True))
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        runtime = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def rate(*args):
            calls.append("rate")
            entered.set()
            await release.wait()
            return True
        async def stop_command(*args):
            calls.append("stop")
            actions._mark_shared_stop_dispatch()
            return True
        monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", rate)
        monkeypatch.setattr(actions, "_stop_sigenergy_charger", stop_command)
        monkeypatch.setattr(actions, "_start_sigenergy_charger", AsyncMock(side_effect=lambda *a: calls.append("start") or True))
        task = asyncio.create_task(actions._set_vehicle_amps(hass, entry, "sigenergy_charger", 8, runtime["params"]))
        await asyncio.wait_for(entered.wait(), 1)
        stop = asyncio.create_task(actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "sigenergy_charger", "stop_charging": True}))
        await asyncio.sleep(0)
        assert not actions.is_shared_stop_fenced(hass, entry, "sigenergy_charger")
        release.set()
        await task
        assert not await stop
        assert calls == ["rate", "start", "stop"]
    asyncio.run(scenario())


# Reuse the protocol-level fixture without contacting an EVAC device.
from test_sigenergy_ev_charger import charger_module


def test_evac_register_write_rechecks_authority_after_read(charger_module):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    async def scenario():
        controller = charger_module.SigenergyEVChargerController(host="charger.invalid", charger_type="evac")
        entered, release = asyncio.Event(), asyncio.Event()
        valid = True
        async def read(*args):
            entered.set()
            await release.wait()
            return [0, 3200, 0, 0, 4000]
        write = AsyncMock(return_value=SimpleNamespace(isError=lambda: False))
        controller._client = SimpleNamespace(connected=True, write_registers=write)
        controller._read_input_registers = read
        controller._shared_write_authorized = lambda: valid
        task = asyncio.create_task(controller.set_charging_amps(8))
        await asyncio.wait_for(entered.wait(), 1)
        valid = False
        release.set()
        assert not await task
        write.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["none", "lease_connect", "lease_write", "binding", "selector", "cancel", "timeout", "handoff"])
def test_evac_stop_rechecks_owner_after_connect(monkeypatch, change):
    from unittest.mock import AsyncMock
    async def scenario():
        hass, entry = _Hass(), _Entry()
        entry.options = {**entry.options, "generic_charger_enabled": False, "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac", "sigenergy_charger_host": "charger.invalid"}
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        params = {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a", "dynamic_mode": "battery_target", "owner_mode": "battery_target", "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        monkeypatch.setattr(actions, "_start_sigenergy_charger", AsyncMock(return_value=True))
        monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", AsyncMock(return_value=True))
        assert await actions._action_start_ev_charging_dynamic(hass, entry, params)
        entered, release = asyncio.Event(), asyncio.Event()
        class Controller:
            async def connect(self):
                entered.set()
                await release.wait()
                if change == "timeout":
                    raise asyncio.TimeoutError
                return True
            async def stop_charging(self):
                if change == "lease_write":
                    ownership.claim_ev_ownership(hass, entry, "sigenergy_charger", owner_mode="manual", session_id="replacement")
                if not self._shared_write_authorized():
                    return False
                writes.append("stop")
                return True
            async def disconnect(self):
                pass
        writes = []
        monkeypatch.setattr(actions, "_new_sigenergy_charger", lambda config: Controller())
        async def stop():
            token = None
            if change == "handoff":
                runtime = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]
                capability = {"_shared_handoff_stop_authorization": actions._SHARED_HANDOFF_STOP_AUTHORIZATION,
                              "_shared_handoff_outgoing_profile_id": "shared_ev_profile_a"}
                token = actions._direct_shared_stop_owner.set((asyncio.current_task(), runtime, None, capability))
                hass.states.get("sensor.connected_vehicle").state = "tesla"
            try:
                return await actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "sigenergy_charger", "stop_charging": True})
            finally:
                if token is not None:
                    actions._direct_shared_stop_owner.reset(token)
        task = asyncio.create_task(stop())
        await asyncio.wait_for(entered.wait(), 1)
        if change == "lease_connect":
            ownership.claim_ev_ownership(hass, entry, "sigenergy_charger", owner_mode="manual", session_id="replacement")
        elif change == "binding":
            entry.options["sigenergy_charger_host"] = "other.invalid"
        elif change == "selector":
            hass.states.get("sensor.connected_vehicle").state = "tesla"
        elif change == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert writes == []
            pending = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]["pending_stop"]
            assert pending["status"] == "unconfirmed" and not pending.get("dispatch_at")
            return
        release.set()
        assert not await task
        assert writes == (["stop"] if change in ("none", "handoff") else [])
        pending = actions._dynamic_ev_state[entry.entry_id]["sigenergy_charger"]["pending_stop"]
        assert bool(pending.get("dispatch_at")) == (change in ("none", "handoff"))
    asyncio.run(scenario())


@pytest.mark.parametrize("replacement", ["lease", "runtime"])
def test_generic_stop_rechecks_lease_after_phase_wait(monkeypatch, replacement):
    async def scenario():
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        actions._dynamic_ev_state.clear()
        start = {**_generic_params(), "vehicle_id": "shared_ev_profile_a",
                 "dynamic_mode": "smart_schedule", "owner_mode": "smart_schedule",
                 "fixed_charge_amps": 8, "max_charge_amps": 8, "notify_on_start": False}
        assert await actions._action_start_ev_charging_dynamic(hass, entry, start)
        hass.services.async_call.reset_mock()
        entered, resume = asyncio.Event(), asyncio.Event()
        async def phase(*args):
            entered.set()
            await resume.wait()
            return 0
        monkeypatch.setattr(actions, "_phase_load_management_applies", lambda *a: True)
        monkeypatch.setattr(actions, "_phase_load_managed_target_amps", phase)
        task = asyncio.create_task(actions._action_stop_ev_charging_dynamic(hass, entry, {"vehicle_id": "generic_ev"}))
        await entered.wait()
        if replacement == "lease":
            owners = ownership.get_ev_ownerships(hass, entry)
            owners["generic_ev"] = dict(owners["generic_ev"], session_id="replacement")
        else:
            vehicles = actions._dynamic_ev_state[entry.entry_id]
            vehicles["generic_ev"] = dict(vehicles["generic_ev"])
        resume.set()
        assert not await task
        hass.services.async_call.assert_not_awaited()
    asyncio.run(scenario())

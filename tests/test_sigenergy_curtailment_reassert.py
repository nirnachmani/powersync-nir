"""Focused Sigenergy zero-export reassertion policy tests (no live HA/Modbus)."""

from __future__ import annotations

import ast
import asyncio
import math
import time
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

INIT = Path(__file__).resolve().parents[1] / "custom_components/power_sync/__init__.py"


def _function(name: str, globals_: dict):
    """Execute the shipped helper or setup-entry nested function in isolation."""
    tree = ast.parse(INIT.read_text())
    matches = [node for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == name]
    assert len(matches) == 1, f"expected one real {name} function"
    code = ast.Module(body=[matches[0]], type_ignores=[])
    ast.fix_missing_locations(code)
    namespace = {"math": math, **globals_}
    exec(compile(code, str(INIT), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("age_seconds,slot_matches,expected", [
    (20, True, True),
    (125, True, True),  # Amber's coordinator refreshes every five minutes.
    (325, True, False),
    (20, False, False),
])
def test_event_reassert_requires_current_price_slot(age_seconds, slot_matches, expected):
    now = datetime(2026, 10, 26, 12, 18, tzinfo=timezone(timedelta(hours=10, minutes=30)))
    slot_start = now.replace(minute=15, second=0, microsecond=0)
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={
            "last_update": now - timedelta(seconds=age_seconds),
            "current": [{
                "channelType": "feedIn", "perKwh": 1.67,
                "startTime": (slot_start if slot_matches else slot_start - timedelta(minutes=5)).isoformat(),
                "endTime": (slot_start + timedelta(minutes=5) if slot_matches else slot_start).isoformat(),
            }],
        },
    )
    func = _function("_sigenergy_reassert_price_is_current", {
        "datetime": datetime, "timedelta": timedelta,
    })
    assert func(1.67, "price_coordinator", (coordinator,), now) is expected


def test_event_reassert_rejects_unknown_or_failed_price_source():
    now = datetime(2026, 10, 26, 12, 18, tzinfo=timezone.utc)
    func = _function("_sigenergy_reassert_price_is_current", {
        "datetime": datetime, "timedelta": timedelta,
    })
    assert func(None, None, (), now) is False
    coordinator = SimpleNamespace(
        last_update_success=False,
        data={"last_update": now, "current": [{"channelType": "feedIn", "perKwh": 1.67}]},
    )
    assert func(1.67, "price_coordinator", (coordinator,), now) is False
    coordinator.last_update_success = True
    # AEMO stamps its fetch time even when the dispatch has not advanced.
    # A fresh fetch of an *unbounded* old price is not current price evidence.
    assert func(1.67, "price_coordinator", (coordinator,), now) is False
    assert func(1.67, "tariff_schedule", (), now) is True


def test_localvolts_start_plus_duration_establishes_current_price_interval():
    now = datetime(2026, 10, 26, 12, 18, tzinfo=timezone.utc)
    point = {"channelType": "feedIn", "perKwh": 1.67,
             "startTime": now.replace(minute=15).isoformat(), "duration": 5}
    coord = SimpleNamespace(last_update_success=True,
                            data={"last_update": now, "current": [point]})
    func = _function("_sigenergy_reassert_price_is_current", {
        "datetime": datetime, "timedelta": timedelta,
    })
    assert func(1.67, "price_coordinator", (coord,), now) is True
    point["startTime"] = now.replace(minute=10).isoformat()
    assert func(1.67, "price_coordinator", (coord,), now) is False


def _reassert_runtime(*, feedin=1.67, curtail_state="curtailed", price_age=15):
    now = datetime(2026, 10, 26, 12, 18, tzinfo=timezone(timedelta(hours=10, minutes=30)))
    coord = SimpleNamespace(
        last_update_success=True,
        data={"last_update": now - timedelta(seconds=price_age),
              "current": [{"channelType": "feedIn", "perKwh": feedin,
                           "startTime": now.replace(minute=15).isoformat(),
                           "endTime": now.replace(minute=20).isoformat()}]},
    )
    controller = SimpleNamespace(reassert_zero_export=AsyncMock(return_value=True))
    data = {"sigenergy_curtailment_state": curtail_state,
            "sigenergy_curtail_export_uneconomic": True,
            "sigenergy_coordinator": SimpleNamespace(_controller=controller)}
    entry = SimpleNamespace(entry_id="entry", options={}, data={})
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    async def no_headroom():
        return False
    helpers = {
        "DOMAIN": "power_sync", "hass": hass, "entry": entry,
        "is_sigenergy": True,
        "datetime": datetime, "timedelta": timedelta,
        "dt_util": SimpleNamespace(utcnow=lambda: now),
        "asyncio": asyncio, "time": time,
        "_sigenergy_reassert_lock": asyncio.Lock(),
        "_direct_dc_curtailment_write_allowed": lambda: True,
        "_effective_solar_curtailment_enabled": lambda: True,
        "_active_solar_surplus_ev_needs_inverter_headroom": no_headroom,
        "_optimizer_current_force_action_matches": lambda *_: False,
        "force_charge_state": {"active": False},
        "force_discharge_state": {"active": False},
        "get_current_prices_for_curtailment": lambda *_: (feedin, None, "price_coordinator"),
        "_sigenergy_reassert_price_is_current": _function(
            "_sigenergy_reassert_price_is_current", {"datetime": datetime, "timedelta": timedelta}
        ),
        "export_earnings_are_uneconomic": lambda earnings, *_: earnings < 0,
        "amber_coordinator": coord, "localvolts_coordinator": None,
        "aemo_sensor_coordinator": None, "flow_power_kwatch_coordinator": None,
        "octopus_coordinator": None,
        "_LOGGER": SimpleNamespace(info=lambda *_: None, warning=lambda *_: None, debug=lambda *_: None),
    }
    return _function("_reassert_sigenergy_export_limit", helpers), data, controller, helpers


def test_sapn_register_rise_reasserts_zero_while_current_curtailment_owns_control():
    run, data, controller, _ = _reassert_runtime()
    assert asyncio.run(run()) is True
    controller.reassert_zero_export.assert_awaited_once()
    assert controller.reassert_zero_export.await_args.kwargs["still_eligible"]() is True
    assert len(data["_sigenergy_reassert_attempts"]) == 1


@pytest.mark.parametrize("case", [
    "profitable", "normal", "old_price", "disabled", "monitoring",
    "ev_override", "ev_headroom", "force_charge", "force_discharge",
    "optimizer_export", "unloaded", "releasing", "stopping",
])
def test_reassert_does_not_block_legitimate_export_or_unsafe_control(case):
    run, data, controller, _ = _reassert_runtime()
    env = run.__globals__
    if case == "profitable":
        env["get_current_prices_for_curtailment"] = lambda *_: (-5.0, None, "price_coordinator")
    elif case == "normal":
        data["sigenergy_curtailment_state"] = "normal"
    elif case == "old_price":
        env["amber_coordinator"].data["last_update"] -= timedelta(minutes=5)
    elif case == "disabled":
        env["_direct_dc_curtailment_write_allowed"] = lambda: False
    elif case == "monitoring":
        env["_effective_solar_curtailment_enabled"] = lambda: False
    elif case == "ev_override":
        data["ev_curtailment_override"] = True
    elif case == "ev_headroom":
        env["_active_solar_surplus_ev_needs_inverter_headroom"] = AsyncMock(return_value=True)
    elif case == "force_charge":
        env["force_charge_state"]["active"] = True
    elif case == "force_discharge":
        env["force_discharge_state"]["active"] = True
    elif case == "optimizer_export":
        env["_optimizer_current_force_action_matches"] = lambda action: action == "discharge"
    elif case == "unloaded":
        env["hass"].data["power_sync"].pop("entry")
    elif case == "releasing":
        data["_sigenergy_curtailment_releasing"] = True
    elif case == "stopping":
        data["sigenergy_reassert_stopping"] = True
    assert asyncio.run(run()) is False
    controller.reassert_zero_export.assert_not_awaited()


def test_reassert_rechecks_tariff_at_write_seam():
    run, data, controller, _ = _reassert_runtime()
    env = run.__globals__
    observations = []

    async def change_price_during_modbus_read(*, still_eligible):
        env["get_current_prices_for_curtailment"] = lambda *_: (-5.0, None, "price_coordinator")
        observations.append(still_eligible())
        return False

    controller.reassert_zero_export.side_effect = change_price_during_modbus_read
    assert asyncio.run(run()) is False
    assert observations == [False]
    assert data["sigenergy_curtailment_state"] == "curtailed"


def test_reassert_rechecks_ev_restore_intent_at_write_seam():
    run, data, controller, _ = _reassert_runtime()
    observations = []

    async def ev_restore_starts_during_modbus_read(*, still_eligible):
        data["_sigenergy_curtailment_releasing"] = True
        observations.append(still_eligible())
        return False

    controller.reassert_zero_export.side_effect = ev_restore_starts_during_modbus_read
    assert asyncio.run(run()) is False
    controller.reassert_zero_export.assert_awaited_once()
    assert observations == [False]


def test_periodic_sigenergy_restore_fences_event_reassertion_before_await():
    tree = ast.parse(INIT.read_text())
    handler = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == "handle_sigenergy_curtailment")
    source = ast.get_source_segment(INIT.read_text(), handler)
    assert source is not None
    assert source.count('entry_data["_sigenergy_curtailment_releasing"] = (') == 2
    assert source.count('entry_data.pop("_sigenergy_curtailment_releasing", None)') == 2


def test_reassertion_is_bounded_even_if_external_writer_repeats():
    run, data, controller, _ = _reassert_runtime()
    clock = [1.0]
    run.__globals__["time"] = SimpleNamespace(monotonic=lambda: clock[0])
    for at in (1.0, 2.0, 23.0, 45.0, 67.0, 302.0):
        clock[0] = at
        asyncio.run(run())
    assert controller.reassert_zero_export.await_count == 4
    assert len(data["_sigenergy_reassert_attempts"]) == 3


@pytest.mark.parametrize("old,new,expected", [
    ("0.0", "1.5", True),
    ("0.0", "0.0", False),
    ("1.5", "2.0", False),
    ("unavailable", "1.5", False),
    ("0.0", "unknown", False),
    ("0.0", "nan", False),
])
def test_event_filter_only_fires_on_a_physical_zero_to_positive_rise(old, new, expected):
    func = _function("_sigenergy_limit_rose", {"math": math})
    assert func(SimpleNamespace(state=old), SimpleNamespace(state=new)) is expected


def test_sigen_number_event_schedules_one_guarded_reassertion_not_a_feedback_loop():
    async def scenario():
        data = {"sigenergy_curtailment_state": "curtailed"}
        hass = SimpleNamespace(
            data={"power_sync": {"entry": data}},
            async_create_task=asyncio.create_task,
        )
        reassert = AsyncMock(return_value=True)
        callback = _function("_sigenergy_export_limit_changed", {
            "hass": hass, "entry": SimpleNamespace(entry_id="entry"),
            "DOMAIN": "power_sync", "_reassert_sigenergy_export_limit": reassert,
            "_sigenergy_limit_rose": _function("_sigenergy_limit_rose", {"math": math}),
        })
        def event(old, new):
            return SimpleNamespace(data={
                "old_state": SimpleNamespace(state=old),
                "new_state": SimpleNamespace(state=new),
            })
        callback(event("0.0", "1.5"))
        callback(event("0.0", "2.0"))  # Coalesced while task runs.
        callback(event("1.5", "0.0"))  # Own correction must not loop.
        task = data["sigenergy_reassert_task"]
        assert isinstance(task, asyncio.Task)
        await task
        reassert.assert_awaited_once()
        data["sigenergy_curtailment_state"] = "normal"
        callback(event("0.0", "1.5"))
        reassert.assert_awaited_once()
    asyncio.run(scenario())


def test_reassert_listener_and_task_are_cleared_on_entry_unload():
    tree = ast.parse(INIT.read_text())
    unload = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "async_unload_entry")
    source = ast.get_source_segment(INIT.read_text(), unload)
    assert source is not None
    assert 'entry_data.pop("sigenergy_export_limit_unsub", None)' in source
    assert 'entry_data.pop("sigenergy_reassert_task", None)' in source
    assert "await asyncio.gather(reassert_task, return_exceptions=True)" in source
    assert source.index('entry_data["sigenergy_reassert_stopping"] = True') < source.index("await ai_service.async_shutdown()")
    assert source.index('entry_data.pop("sigenergy_export_limit_unsub", None)') < source.index("await ai_service.async_shutdown()")

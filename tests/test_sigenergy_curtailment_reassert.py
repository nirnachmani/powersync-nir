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
from typing import Any

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
            "sigenergy_export_limit_owner": "dc_zero",
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

        "export_earnings_are_uneconomic": lambda earnings, *_: earnings < 0,
        "amber_coordinator": coord, "localvolts_coordinator": None,
        "aemo_sensor_coordinator": None, "flow_power_kwatch_coordinator": None,
        "octopus_coordinator": None,
        "_LOGGER": SimpleNamespace(info=lambda *_: None, warning=lambda *_: None, debug=lambda *_: None),
    }
    return _function("_reassert_sigenergy_export_limit", helpers), data, controller, helpers


def test_sapn_register_rise_reasserts_only_current_dc_owner_without_rechecking_price_or_ev():
    run, data, controller, _ = _reassert_runtime()
    data["sigenergy_export_limit_owner"] = "dc_zero"
    env = run.__globals__
    env["get_current_prices_for_curtailment"] = lambda *_: pytest.fail("event recalculated price")
    env["_active_solar_surplus_ev_needs_inverter_headroom"] = lambda: pytest.fail("event recalculated EV headroom")
    env["export_earnings_are_uneconomic"] = lambda *_: pytest.fail("event recalculated tariff")
    assert asyncio.run(run()) is True
    controller.reassert_zero_export.assert_awaited_once()
    assert controller.reassert_zero_export.await_args.kwargs["still_eligible"]() is True
    assert len(data["_sigenergy_reassert_attempts"]) == 1


def test_restart_starts_without_assuming_40038_ownership_from_old_state():
    source = INIT.read_text()
    assert '"sigenergy_export_limit_owner": "normal"' in source
    run, data, controller, _ = _reassert_runtime()
    data["sigenergy_curtailment_state"] = "curtailed"  # Historical ACK is not authority.
    data["sigenergy_export_limit_owner"] = "normal"
    assert asyncio.run(run()) is False
    controller.reassert_zero_export.assert_not_awaited()


def test_old_curtailment_ack_without_owner_does_not_reassert():
    run, data, controller, _ = _reassert_runtime()
    data["sigenergy_export_limit_owner"] = "normal"
    assert asyncio.run(run()) is False
    controller.reassert_zero_export.assert_not_awaited()


def test_owner_revoked_during_modbus_read_prevents_queued_zero_write():
    run, data, controller, _ = _reassert_runtime()
    data["sigenergy_export_limit_owner"] = "dc_zero"
    async def release(*, still_eligible):
        data["sigenergy_export_limit_owner"] = None
        assert still_eligible() is False
        return False
    controller.reassert_zero_export.side_effect = release
    assert asyncio.run(run()) is False


@pytest.mark.parametrize("case", [
    "normal", "disabled", "monitoring", "unloaded", "releasing", "stopping",
])
def test_reassert_does_not_block_legitimate_export_or_unsafe_control(case):
    run, data, controller, _ = _reassert_runtime()
    env = run.__globals__
    if case == "normal":
        data["sigenergy_export_limit_owner"] = "normal"
    elif case == "disabled":
        env["_direct_dc_curtailment_write_allowed"] = lambda: False
    elif case == "monitoring":
        env["_effective_solar_curtailment_enabled"] = lambda: False

    elif case == "unloaded":
        env["hass"].data["power_sync"].pop("entry")
    elif case == "releasing":
        data["_sigenergy_curtailment_releasing"] = True
    elif case == "stopping":
        data["sigenergy_reassert_stopping"] = True
    assert asyncio.run(run()) is False
    controller.reassert_zero_export.assert_not_awaited()


@pytest.mark.parametrize("force_flag", ["charge", "discharge", "optimizer"])
def test_fast_repair_uses_current_owner_not_independent_force_flags(force_flag):
    run, data, controller, _ = _reassert_runtime()
    env = run.__globals__
    if force_flag == "charge":
        env["force_charge_state"]["active"] = True
    elif force_flag == "discharge":
        env["force_discharge_state"]["active"] = True
    else:
        env["_optimizer_current_force_action_matches"] = lambda action: action == "discharge"
    assert data["sigenergy_export_limit_owner"] == "dc_zero"
    assert asyncio.run(run()) is True
    controller.reassert_zero_export.assert_awaited_once()


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


def test_scheduled_decision_does_not_write_zero_during_manual_force_then_rearms():
    data = {"sigenergy_curtailment_state": "curtailed", "sigenergy_export_limit_owner": "manual_force"}
    controller = SimpleNamespace(curtail=AsyncMock(return_value=True), restore=AsyncMock(return_value=True))
    force = {"active": True}
    async def no_headroom():
        return False
    handler = _function("handle_sigenergy_curtailment", {
        "entry": SimpleNamespace(entry_id="entry", options={"sigenergy_dc_curtailment_enabled": True}, data={}),
        "CONF_SIGENERGY_DC_CURTAILMENT_ENABLED": "sigenergy_dc_curtailment_enabled",
        "hass": SimpleNamespace(data={"power_sync": {"entry": data}}),
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            debug=lambda *a: None, info=lambda *a: None, warning=lambda *a: None,
            error=lambda *a, **kw: None),
        "get_current_prices_for_curtailment": lambda *a: (1.0, None, "tariff_schedule"),
        "export_earnings_are_uneconomic": lambda *a: True,
        "_active_solar_surplus_ev_needs_inverter_headroom": no_headroom,
        "_direct_dc_curtailment_write_allowed": lambda: True,
        "force_discharge_state": force,
        "sig_coord": None,
    })
    data["sigenergy_coordinator"] = SimpleNamespace(_controller=controller, data={"grid_power": -1})
    asyncio.run(handler(feedin_price=1.0))
    asyncio.run(handler(feedin_price=1.0))
    controller.curtail.assert_not_awaited()
    assert data["sigenergy_export_limit_owner"] == "manual_force"
    force["active"] = False
    asyncio.run(handler(feedin_price=1.0))
    controller.curtail.assert_awaited_once()
    assert data["sigenergy_export_limit_owner"] == "dc_zero"


def test_scheduled_zero_ack_does_not_reclaim_register_after_manual_force_handoff():
    data = {"sigenergy_curtailment_state": "normal", "sigenergy_export_limit_owner": "normal"}
    async def competing_force(*, still_eligible):
        data["sigenergy_export_limit_owner"] = "manual_force"
        assert still_eligible() is False
        return True
    controller = SimpleNamespace(curtail=AsyncMock(side_effect=competing_force))
    data["sigenergy_coordinator"] = SimpleNamespace(_controller=controller, data={})
    handler = _function("handle_sigenergy_curtailment", {
        "entry": SimpleNamespace(entry_id="entry", options={"dc": True}, data={}),
        "CONF_SIGENERGY_DC_CURTAILMENT_ENABLED": "dc",
        "hass": SimpleNamespace(data={"power_sync": {"entry": data}}), "DOMAIN": "power_sync",
        "_LOGGER": SimpleNamespace(info=lambda *a: None, debug=lambda *a: None,
                                    warning=lambda *a: None, error=lambda *a, **kw: None),
        "export_earnings_are_uneconomic": lambda *a: True,
        "_active_solar_surplus_ev_needs_inverter_headroom": AsyncMock(return_value=False),
        "_direct_dc_curtailment_write_allowed": lambda: True,
        "force_discharge_state": {},
    })
    asyncio.run(handler(feedin_price=1.0))
    assert data["sigenergy_export_limit_owner"] == "manual_force"


@pytest.mark.parametrize("readback,restore_expected", [(0, True), (1500, False)])
def test_acked_zero_without_readback_is_reconciled_on_profitable_check(readback, restore_expected):
    data: dict[str, Any] = {"sigenergy_curtailment_state": "normal",
                            "sigenergy_export_limit_owner": "normal"}
    controller = SimpleNamespace(
        _last_curtail_zero_write_ack=True,
        _get_current_export_limit=AsyncMock(return_value=readback),
        EXPORT_LIMIT_ZERO=0,
        curtail=AsyncMock(return_value=False),
        restore=AsyncMock(return_value=True),
    )
    data["sigenergy_coordinator"] = SimpleNamespace(_controller=controller, data={})
    handler = _function("handle_sigenergy_curtailment", {
        "entry": SimpleNamespace(entry_id="entry", options={"dc": True}, data={}),
        "CONF_SIGENERGY_DC_CURTAILMENT_ENABLED": "dc",
        "hass": SimpleNamespace(data={"power_sync": {"entry": data}}),
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            info=lambda *a: None, debug=lambda *a: None,
            warning=lambda *a: None, error=lambda *a, **kw: None),
        "export_earnings_are_uneconomic": lambda earnings, *a: earnings < 0,
        "_active_solar_surplus_ev_needs_inverter_headroom": AsyncMock(return_value=False),
        "_direct_dc_curtailment_write_allowed": lambda: True,
        "force_discharge_state": {},
    })
    asyncio.run(handler(feedin_price=1.0))
    assert data["sigenergy_dc_zero_write_pending"] is True
    assert data["sigenergy_export_limit_owner"] == "normal"
    asyncio.run(handler(feedin_price=-3.0))
    if restore_expected:
        controller.restore.assert_awaited_once()
    else:
        controller.restore.assert_not_awaited()
    controller._get_current_export_limit.assert_awaited_once()
    assert data["sigenergy_curtailment_state"] == "normal"
    assert "sigenergy_dc_zero_write_pending" not in data


def test_profitable_restore_revokes_owner_before_await_and_retries_failure():
    data = {"sigenergy_curtailment_state": "curtailed", "sigenergy_export_limit_owner": "dc_zero"}
    observed = []
    async def failed_restore(*, still_eligible):
        observed.append(data["sigenergy_export_limit_owner"])
        assert still_eligible() is True
        return False
    controller = SimpleNamespace(restore=AsyncMock(side_effect=failed_restore))
    data["sigenergy_coordinator"] = SimpleNamespace(_controller=controller)
    handler = _function("handle_sigenergy_curtailment", {
        "entry": SimpleNamespace(entry_id="entry", options={"dc": True}, data={}),
        "CONF_SIGENERGY_DC_CURTAILMENT_ENABLED": "dc",
        "hass": SimpleNamespace(data={"power_sync": {"entry": data}}), "DOMAIN": "power_sync",
        "_LOGGER": SimpleNamespace(info=lambda *a: None, debug=lambda *a: None,
                                    warning=lambda *a: None, error=lambda *a, **kw: None),
        "export_earnings_are_uneconomic": lambda *a: False,
        "_active_solar_surplus_ev_needs_inverter_headroom": AsyncMock(return_value=False),
        "_direct_dc_curtailment_write_allowed": lambda: True,
        "force_discharge_state": {},
    })
    asyncio.run(handler(feedin_price=-3.0))
    asyncio.run(handler(feedin_price=-3.0))
    assert observed == ["normal", "normal"]


@pytest.mark.parametrize("ac_host,ac_port,expected", [
    ("sig.local", 502, True), ("elsewhere.local", 502, False),
    ("sig.local", 503, False),
])
def test_ac_sigenergy_same_physical_endpoint_has_one_owner(ac_host, ac_port, expected):
    entry = SimpleNamespace(data={"battery_host": "sig.local"}, options={
        "ac_brand": "sigenergy", "ac_host": ac_host, "ac_port": ac_port,
        "battery_host": "sig.local", "battery_port": 502,
    })
    func = _function("ac_inverter_is_same_hybrid", {
        "entry": entry, "is_sigenergy": True, "is_sungrow": False,
        "_solaredge_ac_inverter_matches_battery": lambda _: False,
        "CONF_INVERTER_BRAND": "ac_brand", "CONF_INVERTER_HOST": "ac_host",
        "CONF_INVERTER_PORT": "ac_port", "DEFAULT_INVERTER_PORT": 502,
        "CONF_SIGENERGY_MODBUS_HOST": "battery_host",
        "CONF_SIGENERGY_MODBUS_PORT": "battery_port",
    })
    assert func() is expected


def test_controls_durable_export_cap_uses_current_dc_owner_not_old_ack():
    tree = ast.parse(INIT.read_text())
    view = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == "SigenergySettingsView")
    post = next(n for n in view.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "post")
    source = ast.get_source_segment(INIT.read_text(), post)
    assert source is not None
    expression = source[source.index('if "export_limit_kw" in validated:'):]
    assert 'curtailment_active = export_owner_at_start == "dc_zero"' in expression
    assert 'entry_data.get("sigenergy_curtailment_state") == "curtailed"' not in expression
    assert 'entry_data.get("sigenergy_export_limit_owner") == "manual_force"' in source
    assert "still_eligible=lambda:" in expression
    assert source.index('entry_data.get("sigenergy_export_limit_owner") == "manual_force"') < source.index(
        'if "backup_reserve" in validated:'
    )


def test_explicit_export_action_is_one_shot_and_revokes_event_permission_before_write():
    path = INIT.parent / "automations/actions.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_action_set_export_limit")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_export_limit_owner": "dc_zero"}
    entry = SimpleNamespace(entry_id="entry")
    async def write(limit, *, still_eligible):
        assert data["sigenergy_export_limit_owner"] != "dc_zero"
        assert still_eligible()
        return True
    controller = SimpleNamespace(EXPORT_LIMIT_ZERO=0, set_export_limit=AsyncMock(side_effect=write),
                                 _get_current_export_limit=AsyncMock(return_value=3000),
                                 restore_export_limit=AsyncMock(return_value=True),
                                 disconnect=AsyncMock())
    env = {"DOMAIN": "power_sync", "_is_sigenergy": lambda _: True,
           "_get_sigenergy_controller": AsyncMock(return_value=controller),
           "_LOGGER": SimpleNamespace(info=lambda *a: None, error=lambda *a: None)}
    exec(compile(module, str(path), "exec"), env)
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    assert asyncio.run(env["_action_set_export_limit"](hass, entry, {"limit": 3}))
    assert data["sigenergy_export_limit_owner"] == "explicit"


def test_explicit_cap_action_cannot_take_register_from_active_manual_force():
    path = INIT.parent / "automations/actions.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_action_set_export_limit")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_export_limit_owner": "manual_force"}
    controller = SimpleNamespace(set_export_limit=AsyncMock(),
                                 restore_export_limit=AsyncMock(), disconnect=AsyncMock())
    env = {"DOMAIN": "power_sync", "_is_sigenergy": lambda _: True,
           "_get_sigenergy_controller": AsyncMock(return_value=controller),
           "_LOGGER": SimpleNamespace(info=lambda *a: None, error=lambda *a: None)}
    exec(compile(module, str(path), "exec"), env)
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    assert not asyncio.run(env["_action_set_export_limit"](
        hass, SimpleNamespace(entry_id="entry"), {"limit": 3}))
    assert data["sigenergy_export_limit_owner"] == "manual_force"
    controller.set_export_limit.assert_not_awaited()
    controller.restore_export_limit.assert_not_awaited()


def test_explicit_cap_write_exception_rearms_confirmed_prior_dc_zero():
    path = INIT.parent / "automations/actions.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_action_set_export_limit")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_export_limit_owner": "dc_zero"}
    async def failed_write(limit):
        assert data["sigenergy_export_limit_owner"] == "explicit"
        raise OSError("Modbus unavailable")
    controller = SimpleNamespace(EXPORT_LIMIT_ZERO=0,
                                 set_export_limit=AsyncMock(side_effect=failed_write),
                                 _get_current_export_limit=AsyncMock(return_value=0),
                                 disconnect=AsyncMock())
    env = {"DOMAIN": "power_sync", "_is_sigenergy": lambda _: True,
           "_get_sigenergy_controller": AsyncMock(return_value=controller),
           "_LOGGER": SimpleNamespace(info=lambda *a: None, error=lambda *a: None)}
    exec(compile(module, str(path), "exec"), env)
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    assert not asyncio.run(env["_action_set_export_limit"](
        hass, SimpleNamespace(entry_id="entry"), {"limit": 3}))
    assert data["sigenergy_export_limit_owner"] == "dc_zero"


def test_failed_explicit_cap_rearms_dc_only_after_zero_readback():
    path = INIT.parent / "automations/actions.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_action_set_export_limit")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_export_limit_owner": "dc_zero"}
    controller = SimpleNamespace(EXPORT_LIMIT_ZERO=0, set_export_limit=AsyncMock(return_value=False),
                                 _get_current_export_limit=AsyncMock(return_value=0),
                                 disconnect=AsyncMock())
    env = {"DOMAIN": "power_sync", "_is_sigenergy": lambda _: True,
           "_get_sigenergy_controller": AsyncMock(return_value=controller),
           "_LOGGER": SimpleNamespace(info=lambda *a: None, error=lambda *a: None)}
    exec(compile(module, str(path), "exec"), env)
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    entry = SimpleNamespace(entry_id="entry")
    assert not asyncio.run(env["_action_set_export_limit"](hass, entry, {"limit": 3}))
    assert data["sigenergy_export_limit_owner"] == "dc_zero"
    controller._get_current_export_limit.return_value = 3000
    assert not asyncio.run(env["_action_set_export_limit"](hass, entry, {"limit": 3}))
    assert data["sigenergy_export_limit_owner"] == "explicit"


def test_explicit_cap_ack_without_positive_readback_does_not_release_dc_zero():
    path = INIT.parent / "automations/actions.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_action_set_export_limit")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_export_limit_owner": "dc_zero"}
    controller = SimpleNamespace(EXPORT_LIMIT_ZERO=0,
                                 set_export_limit=AsyncMock(return_value=True),
                                 _get_current_export_limit=AsyncMock(return_value=0),
                                 disconnect=AsyncMock())
    env = {"DOMAIN": "power_sync", "_is_sigenergy": lambda _: True,
           "_get_sigenergy_controller": AsyncMock(return_value=controller),
           "_LOGGER": SimpleNamespace(info=lambda *a: None, error=lambda *a: None)}
    exec(compile(module, str(path), "exec"), env)
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    assert not asyncio.run(env["_action_set_export_limit"](
        hass, SimpleNamespace(entry_id="entry"), {"limit": 3}))
    assert data["sigenergy_export_limit_owner"] == "dc_zero"


def test_explicit_zero_export_cap_is_not_misparsed_as_restore():
    path = INIT.parent / "automations/actions.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_action_set_export_limit")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_export_limit_owner": "normal"}
    controller = SimpleNamespace(set_export_limit=AsyncMock(return_value=True),
                                 restore_export_limit=AsyncMock(return_value=True),
                                 disconnect=AsyncMock())
    env = {"DOMAIN": "power_sync", "_is_sigenergy": lambda _: True,
           "_get_sigenergy_controller": AsyncMock(return_value=controller),
           "_LOGGER": SimpleNamespace(info=lambda *a: None, error=lambda *a: None)}
    exec(compile(module, str(path), "exec"), env)
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    assert asyncio.run(env["_action_set_export_limit"](
        hass, SimpleNamespace(entry_id="entry"), {"limit": 0}))
    controller.set_export_limit.assert_awaited_once()
    assert controller.set_export_limit.await_args.args == (0,)
    assert controller.set_export_limit.await_args.kwargs["still_eligible"]() is True
    controller.restore_export_limit.assert_not_awaited()


def test_invalid_explicit_cap_rearms_dc_only_after_zero_readback():
    path = INIT.parent / "automations/actions.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_action_set_export_limit")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_export_limit_owner": "dc_zero"}
    controller = SimpleNamespace(EXPORT_LIMIT_ZERO=0, set_export_limit=AsyncMock(),
                                 _get_current_export_limit=AsyncMock(return_value=0),
                                 disconnect=AsyncMock())
    env = {"DOMAIN": "power_sync", "_is_sigenergy": lambda _: True,
           "_get_sigenergy_controller": AsyncMock(return_value=controller),
           "_LOGGER": SimpleNamespace(info=lambda *a: None, error=lambda *a: None)}
    exec(compile(module, str(path), "exec"), env)
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    assert not asyncio.run(env["_action_set_export_limit"](
        hass, SimpleNamespace(entry_id="entry"), {"limit": "invalid"}))
    assert data["sigenergy_export_limit_owner"] == "dc_zero"
    controller.set_export_limit.assert_not_awaited()


def test_failed_manual_force_reconciles_prior_dc_owner_without_stale_force_latch():
    func = _function("_reconcile_sigenergy_failed_force_owner", {})
    data = {"sigenergy_export_limit_owner": "manual_force"}
    controller = SimpleNamespace(EXPORT_LIMIT_ZERO=0,
                                 _get_current_export_limit=AsyncMock(return_value=0),
                                 reassert_zero_export=AsyncMock(return_value=True))
    assert asyncio.run(func(controller, data, "dc_zero")) is True
    assert data["sigenergy_export_limit_owner"] == "dc_zero"
    controller.reassert_zero_export.assert_not_awaited()

    data["sigenergy_export_limit_owner"] = "manual_force"
    controller._get_current_export_limit.return_value = 1500
    assert asyncio.run(func(controller, data, "dc_zero")) is True
    controller.reassert_zero_export.assert_awaited_once()
    assert data["sigenergy_export_limit_owner"] == "dc_zero"

    data["sigenergy_export_limit_owner"] = "manual_force"
    controller.reassert_zero_export.return_value = False
    assert asyncio.run(func(controller, data, "dc_zero")) is False
    assert data["sigenergy_export_limit_owner"] == "normal"


def test_failed_manual_force_preserves_prior_non_dc_owner():
    func = _function("_reconcile_sigenergy_failed_force_owner", {})
    data = {"sigenergy_export_limit_owner": "manual_force"}
    controller = SimpleNamespace(_get_current_export_limit=AsyncMock())
    assert asyncio.run(func(controller, data, "explicit")) is True
    assert data["sigenergy_export_limit_owner"] == "explicit"
    controller._get_current_export_limit.assert_not_awaited()


def test_sigenergy_force_service_reconciles_failed_command_and_exception():
    tree = ast.parse(INIT.read_text())
    handler = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_force_discharge")
    source = ast.get_source_segment(INIT.read_text(), handler)
    assert source is not None
    assert source.count("await _reconcile_sigenergy_failed_force_owner(") >= 2
    manual = source[source.index('entry_data["sigenergy_export_limit_owner"] = "manual_force"'):]
    assert manual.index("await _reconcile_sigenergy_failed_force_owner(") < manual.index(
        "await controller.disconnect()"
    )


def test_manual_force_transfers_register_owner_before_hardware_and_successful_end_reassesses():
    source = INIT.read_text()
    force = ast.get_source_segment(source, next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_force_discharge"))
    restore = ast.get_source_segment(source, next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_restore_normal"))
    assert force is not None and restore is not None
    manual = force[force.index("# Check if this is a Sigenergy system"):force.index("# Check if this is a FoxESS system")]
    assert manual.index('entry_data["sigenergy_export_limit_owner"] = "manual_force"') < manual.index(
        "controller.force_discharge(")
    assert 'entry_data["sigenergy_export_limit_owner"] = "normal"' in restore
    assert "await handle_sigenergy_curtailment()" in restore


def test_native_handoff_requires_positive_readback_before_relinquishing_dc_zero():
    source = INIT.read_text()
    restore = ast.get_source_segment(source, next(n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_restore_normal"))
    assert restore is not None
    assert 'if native_released_dc and result:' in restore
    assert 'await controller._get_current_export_limit()' in restore


def test_non_export_cleanup_does_not_default_to_native_handoff_after_visual_state_clears():
    source = INIT.read_text()
    restore = ast.get_source_segment(source, next(n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_restore_normal"))
    assert restore is not None
    assert 'restore_was_self_consumption = bool(self_consumption_state.get("active"))' in restore
    assert 'or restore_was_self_consumption' in restore


def test_reassertion_is_bounded_even_if_external_writer_repeats():
    run, data, controller, _ = _reassert_runtime()
    clock = [1.0]
    run.__globals__["time"] = SimpleNamespace(monotonic=lambda: clock[0])
    for at in (1.0, 2.0, 23.0, 45.0, 67.0, 302.0):
        clock[0] = at
        asyncio.run(run())
    assert controller.reassert_zero_export.await_count == 4
    assert len(data["_sigenergy_reassert_attempts"]) == 3


def test_reassert_accepts_ten_second_gap_but_not_nine():
    run, data, controller, _ = _reassert_runtime()
    clock = [100.0]
    run.__globals__["time"] = SimpleNamespace(monotonic=lambda: clock[0])
    for at in (100.0, 109.0, 110.0):
        clock[0] = at
        asyncio.run(run())
    assert controller.reassert_zero_export.await_count == 2


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
        data = {"sigenergy_curtailment_state": "curtailed", "sigenergy_export_limit_owner": "dc_zero"}
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
        data["sigenergy_export_limit_owner"] = "normal"
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

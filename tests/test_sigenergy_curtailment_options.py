"""Sigenergy DC option transitions must not follow battery-only cleanup."""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "custom_components/power_sync/config_flow.py"


def _options_method_node(name):
    tree = ast.parse(SOURCE.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "PowerSyncOptionsFlow")
    return next(node for node in cls.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name)


def _options_method(name, globals_) -> Any:
    method = _options_method_node(name)
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(globals_)
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace[name]


def _method_source(name: str) -> str:
    text = ast.get_source_segment(SOURCE.read_text(), _options_method_node(name))
    assert text is not None
    return text


def test_battery_only_disable_does_not_restore_sigenergy_dc_limit():
    """The Tesla/battery export-rule cleanup must leave Sigenergy DC zero alone."""
    method = _options_method("_restore_export_rule", {
        "BATTERY_SYSTEM_TESLA": "tesla",
        "CONF_BATTERY_SYSTEM": "battery_system",
    })
    calls = []

    class Flow:
        config_entry = SimpleNamespace(data={"battery_system": "sigenergy"})

        def _get_option(self, key, default=None):
            return self.config_entry.data.get(key, default)

        async def _restore_owned_curtailment_limits(self, *, include_sigenergy=True):
            calls.append(include_sigenergy)

    asyncio.run(method(Flow(), retain_sigenergy_dc=True))
    assert calls == [False]


def test_approved_dc_disable_still_restores_held_sigenergy_zero():
    """Only the DC-option/permission transition releases a held 40038 zero."""
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    controller = SimpleNamespace(restore=AsyncMock(return_value=True))
    data = {"sigenergy_curtailment_state": "curtailed",
            "sigenergy_coordinator": SimpleNamespace(_controller=controller)}
    flow = SimpleNamespace(
        hass=SimpleNamespace(data={"power_sync": {"entry": data}}),
        config_entry=SimpleNamespace(entry_id="entry"),
    )
    skipped = asyncio.run(method(flow, include_sigenergy=False))
    controller.restore.assert_not_awaited()
    assert skipped is True
    assert data["sigenergy_curtailment_state"] == "curtailed"
    restored = asyncio.run(method(flow, include_sigenergy=True))
    controller.restore.assert_awaited_once()
    assert restored is True
    assert data["sigenergy_curtailment_state"] == "normal"


def test_dc_disable_reports_restore_failure_instead_of_saving_bad_state():
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    controller = SimpleNamespace(restore=AsyncMock(return_value=False))
    data = {"sigenergy_curtailment_state": "curtailed",
            "sigenergy_coordinator": SimpleNamespace(_controller=controller)}
    flow = SimpleNamespace(
        hass=SimpleNamespace(data={"power_sync": {"entry": data}}),
        config_entry=SimpleNamespace(entry_id="entry"),
    )
    assert asyncio.run(method(flow, include_sigenergy=True)) is False
    assert data["sigenergy_curtailment_state"] == "curtailed"


def test_dc_disable_refuses_without_live_controller_state():
    method = _options_method("_restore_owned_curtailment_limits", {"DOMAIN": "power_sync"})
    flow = SimpleNamespace(hass=SimpleNamespace(data={"power_sync": {}}),
                           config_entry=SimpleNamespace(entry_id="entry"))
    assert asyncio.run(method(flow, only_sigenergy=True, fence_sigenergy=True)) is False


def test_scheduled_dc_writer_blocks_during_options_transition():
    tree = ast.parse(SOURCE.with_name("__init__.py").read_text())
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "_direct_dc_curtailment_write_allowed")
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    data = {"sigenergy_dc_option_transition": True}
    env = {
        "entry": SimpleNamespace(entry_id="entry"),
        "hass": SimpleNamespace(data={"power_sync": {"entry": data}}),
        "DOMAIN": "power_sync",
        "get_effective_solar_curtailment_configuration": lambda _: (False, True),
        "_monitoring_mode_allows_curtailment": lambda _: True,
    }
    exec(compile(module, str(SOURCE), "exec"), env)
    assert env["_direct_dc_curtailment_write_allowed"]() is False
    data.clear()
    assert env["_direct_dc_curtailment_write_allowed"]() is True


def test_paused_options_restore_blocks_scheduled_write_until_reload():
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    gate_tree = ast.parse(SOURCE.with_name("__init__.py").read_text())
    gate = next(node for node in ast.walk(gate_tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "_direct_dc_curtailment_write_allowed")
    module = ast.Module(body=[gate], type_ignores=[])
    ast.fix_missing_locations(module)
    data: dict[str, Any] = {"sigenergy_curtailment_state": "curtailed",
                            "sigenergy_export_limit_owner": "dc_zero"}
    hass = SimpleNamespace(data={"power_sync": {"entry": data}})
    env = {"entry": SimpleNamespace(entry_id="entry"), "hass": hass,
           "DOMAIN": "power_sync",
           "get_effective_solar_curtailment_configuration": lambda _: (False, True),
           "_monitoring_mode_allows_curtailment": lambda _: True}
    exec(compile(module, str(SOURCE), "exec"), env)

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        async def restore(*, still_eligible):
            entered.set()
            await release.wait()
            assert still_eligible()
            return True
        controller = SimpleNamespace(restore=restore)
        data["sigenergy_coordinator"] = SimpleNamespace(_controller=controller)
        flow = SimpleNamespace(hass=hass, config_entry=SimpleNamespace(entry_id="entry"))
        assert env["_direct_dc_curtailment_write_allowed"]() is True
        restoring = asyncio.create_task(method(
            flow, only_sigenergy=True, fence_sigenergy=True,
        ))
        await entered.wait()
        assert data["sigenergy_export_limit_owner"] == "normal"
        assert env["_direct_dc_curtailment_write_allowed"]() is False
        release.set()
        assert await restoring is True
        assert env["_direct_dc_curtailment_write_allowed"]() is False
    asyncio.run(scenario())


def test_dc_option_transition_fences_scheduled_writes_until_reload_or_rollback():
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    for success in (True, False):
        data: dict[str, Any] = {
            "sigenergy_curtailment_state": "curtailed",
            "sigenergy_export_limit_owner": "dc_zero",
        }
        async def restore(*, still_eligible):
            assert data["sigenergy_dc_option_transition"] is True
            assert data["sigenergy_export_limit_owner"] == "normal"
            assert still_eligible()
            return success
        controller = SimpleNamespace(restore=restore, EXPORT_LIMIT_ZERO=0,
                                     _get_current_export_limit=AsyncMock(return_value=0))
        data["sigenergy_coordinator"] = SimpleNamespace(_controller=controller)
        flow = SimpleNamespace(hass=SimpleNamespace(data={"power_sync": {"entry": data}}),
                               config_entry=SimpleNamespace(entry_id="entry"))
        assert asyncio.run(method(flow, only_sigenergy=True, fence_sigenergy=True)) is success
        if success:
            assert data["sigenergy_dc_option_transition"] is True
            assert data["sigenergy_export_limit_owner"] == "normal"
        else:
            assert "sigenergy_dc_option_transition" not in data
            assert data["sigenergy_export_limit_owner"] == "dc_zero"


@pytest.mark.parametrize("readback,expect_restore,expected_success", [
    (0, True, True), (1500, False, True), (None, False, False),
])
def test_dc_disable_reconciles_ambiguous_zero_ack_before_turning_off(readback, expect_restore, expected_success):
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    controller = SimpleNamespace(EXPORT_LIMIT_ZERO=0,
                                 _get_current_export_limit=AsyncMock(return_value=readback),
                                 restore=AsyncMock(return_value=True))
    data = {"sigenergy_curtailment_state": "normal",
            "sigenergy_export_limit_owner": "normal",
            "sigenergy_dc_zero_write_pending": True,
            "sigenergy_coordinator": SimpleNamespace(_controller=controller)}
    flow = SimpleNamespace(hass=SimpleNamespace(data={"power_sync": {"entry": data}}),
                           config_entry=SimpleNamespace(entry_id="entry"))
    assert asyncio.run(method(flow, only_sigenergy=True, fence_sigenergy=True)) is expected_success
    if expect_restore:
        controller.restore.assert_awaited_once()
    else:
        controller.restore.assert_not_awaited()
    if expected_success:
        assert "sigenergy_dc_zero_write_pending" not in data
    else:
        assert data["sigenergy_dc_zero_write_pending"] is True


def test_dc_disable_fences_queued_zero_before_restore_await():
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    data: dict[str, Any] = {"sigenergy_curtailment_state": "curtailed",
                            "sigenergy_export_limit_owner": "dc_zero"}
    observed = []
    async def restore(*, still_eligible):
        observed.append(still_eligible())
        assert data["sigenergy_export_limit_owner"] == "normal"
        assert still_eligible() is True
        return False
    data["sigenergy_coordinator"] = SimpleNamespace(
        _controller=SimpleNamespace(restore=restore))
    flow = SimpleNamespace(hass=SimpleNamespace(data={"power_sync": {"entry": data}}),
                           config_entry=SimpleNamespace(entry_id="entry"))
    assert asyncio.run(method(flow, only_sigenergy=True)) is False
    assert observed == [True]
    assert data["sigenergy_export_limit_owner"] == "normal"
    assert data["sigenergy_curtailment_state"] == "curtailed"


def test_dc_disable_does_not_override_manual_force_owner():
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    controller = SimpleNamespace(restore=AsyncMock(return_value=True))
    data = {"sigenergy_curtailment_state": "curtailed",
            "sigenergy_export_limit_owner": "manual_force",
            "sigenergy_coordinator": SimpleNamespace(_controller=controller)}
    flow = SimpleNamespace(hass=SimpleNamespace(data={"power_sync": {"entry": data}}),
                           config_entry=SimpleNamespace(entry_id="entry"))
    assert asyncio.run(method(flow, only_sigenergy=True)) is True
    controller.restore.assert_not_awaited()
    assert data["sigenergy_export_limit_owner"] == "manual_force"


def test_dc_only_disable_leaves_separate_ac_inverter_control_alone():
    method = _options_method("_restore_owned_curtailment_limits", {
        "DOMAIN": "power_sync", "_LOGGER": SimpleNamespace(
            error=lambda *args: None, warning=lambda *args: None,
            info=lambda *args: None),
    })
    ac_controller = SimpleNamespace(restore=AsyncMock(return_value=True))
    data = {"inverter_last_state": "curtailed", "inverter_controller": ac_controller}
    flow = SimpleNamespace(hass=SimpleNamespace(data={"power_sync": {"entry": data}}),
                           config_entry=SimpleNamespace(entry_id="entry"))
    assert asyncio.run(method(flow, only_sigenergy=True)) is True
    ac_controller.restore.assert_not_awaited()
    assert data["inverter_last_state"] == "curtailed"


def test_curtailment_option_routes_are_independent():
    """Battery-off with DC-on retains zero; DC-off restores before saving."""
    transition = _method_source("async_step_curtailment_options")
    assert "retain_sigenergy_dc=is_sigenergy" in transition
    assert "new_data[CONF_SIGENERGY_DC_CURTAILMENT_ENABLED] = new_dc_curtailment_enabled" in transition
    assert "if not await self._restore_owned_curtailment_limits(" in transition
    assert "only_sigenergy=True, fence_sigenergy=True" in transition
    assert 'return self.async_abort(reason="sigenergy_curtailment_restore_failed")' in transition
    assert "was_dc_curtailment_enabled and not new_dc_curtailment_enabled" in transition
    assert transition.index("only_sigenergy=True, fence_sigenergy=True") < transition.index(
        "new_data[CONF_SIGENERGY_DC_CURTAILMENT_ENABLED] = new_dc_curtailment_enabled"
    )


def test_dc_restore_failure_has_user_visible_abort_reason():
    for path in (SOURCE.with_name("strings.json"),
                 SOURCE.parent / "translations" / "en.json"):
        abort = json.loads(path.read_text())["options"]["abort"]
        assert "sigenergy_curtailment_restore_failed" in abort
        assert "export" in abort["sigenergy_curtailment_restore_failed"].lower()


def test_init_sigenergy_form_restores_dc_zero_before_disabling():
    """The initial-options Sigenergy form is a second DC-setting write path."""
    body = _method_source("async_step_init_sigenergy")
    assert "was_dc_curtailment_enabled and not dc_curtailment_enabled" in body
    assert "new_data[CONF_SIGENERGY_DC_CURTAILMENT_ENABLED] = dc_curtailment_enabled" in body
    assert "only_sigenergy=True, fence_sigenergy=True" in body
    assert 'return self.async_abort(reason="sigenergy_curtailment_restore_failed")' in body
    assert body.index("only_sigenergy=True, fence_sigenergy=True") < body.index(
        "self.hass.config_entries.async_update_entry("
    )


def test_connection_form_restores_dc_zero_before_disabling_and_reloading():
    """The separate Sigenergy connection form must not strand 40038 at zero."""
    body = _method_source("async_step_sigenergy_connection")
    assert "was_dc_curtailment_enabled and not dc_curtailment_enabled" in body
    assert "new_data[CONF_SIGENERGY_DC_CURTAILMENT_ENABLED] = dc_curtailment_enabled" in body
    assert "only_sigenergy=True, fence_sigenergy=True" in body
    assert 'return self.async_abort(reason="sigenergy_curtailment_restore_failed")' in body
    assert body.index("only_sigenergy=True, fence_sigenergy=True") < body.index(
        "self.hass.config_entries.async_update_entry("
    )

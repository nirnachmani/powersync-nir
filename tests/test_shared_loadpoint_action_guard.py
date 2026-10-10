"""Behavioral guards for direct shared Generic and EVAC commands."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = ROOT / "custom_components" / "powersync_nir"


def _install_ha_stubs() -> None:
    ha = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries", types.ModuleType("homeassistant.config_entries")
    )
    helpers = sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
    event = sys.modules.setdefault("homeassistant.helpers.event", types.ModuleType("homeassistant.helpers.event"))
    entity_registry = sys.modules.setdefault(
        "homeassistant.helpers.entity_registry",
        types.ModuleType("homeassistant.helpers.entity_registry"),
    )
    device_registry = sys.modules.setdefault(
        "homeassistant.helpers.device_registry",
        types.ModuleType("homeassistant.helpers.device_registry"),
    )
    util = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
    util_dt = sys.modules.setdefault("homeassistant.util.dt", types.ModuleType("homeassistant.util.dt"))

    core.HomeAssistant = type("HomeAssistant", (), {})
    config_entries.ConfigEntry = type("ConfigEntry", (), {})
    event.async_track_time_interval = lambda *args, **kwargs: lambda: None
    event.async_track_point_in_time = lambda *args, **kwargs: lambda: None
    entity_registry.async_get = lambda hass: SimpleNamespace(entities={})
    device_registry.async_get = lambda hass: SimpleNamespace(devices={})
    helpers.event = event
    helpers.entity_registry = entity_registry
    helpers.device_registry = device_registry
    util.dt = util_dt
    ha.helpers = helpers
    ha.util = util


_install_ha_stubs()
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

package = types.ModuleType("powersync_nir")
package.__path__ = [str(COMPONENT_ROOT)]
sys.modules["powersync_nir"] = package
automations = types.ModuleType("powersync_nir.automations")
automations.__path__ = [str(COMPONENT_ROOT / "automations")]
sys.modules["powersync_nir.automations"] = automations
for module_name in (
    "powersync_nir.const",
    "powersync_nir.automations.actions",
    "powersync_nir.automations.shared_loadpoint",
):
    sys.modules.pop(module_name, None)
actions = importlib.import_module("powersync_nir.automations.actions")


class _State:
    def __init__(self, state: str) -> None:
        self.state = state
        self.attributes = {}


class _Hass:
    def __init__(self, selector_state: str = "tank") -> None:
        self.states = SimpleNamespace(
            get=lambda entity_id: {
                "sensor.connected_vehicle": _State(selector_state),
                "switch.shared_ev": _State("on"),
            }.get(entity_id)
        )
        self.services = SimpleNamespace(async_call=AsyncMock())
        self.data = {"powersync_nir": {"entry-1": {}}}


class _Entry:
    entry_id = "entry-1"
    data = {}
    options = {
        "generic_charger_enabled": True,
        "shared_loadpoint_connected_vehicle_entity": "sensor.connected_vehicle",
        "shared_loadpoint_profile_a_name": "Tank",
        "shared_loadpoint_profile_a_state": "tank",
        "shared_loadpoint_profile_b_name": "Tesla",
        "shared_loadpoint_profile_b_state": "tesla",
    }


def _generic_params() -> dict:
    return {
        "charger_type": "generic",
        "charger_switch_entity": "switch.shared_ev",
    }


def test_physical_generic_id_cannot_bypass_selected_profile_for_direct_stop():
    hass = _Hass()

    result = asyncio.run(
        actions._action_stop_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "generic_ev"}
        )
    )

    assert result is False
    hass.services.async_call.assert_not_awaited()


def test_physical_generic_id_cannot_bypass_selected_profile_for_direct_start():
    hass = _Hass()

    result = asyncio.run(
        actions._action_start_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "generic_ev"}
        )
    )

    assert result is False
    hass.services.async_call.assert_not_awaited()


def test_selected_logical_generic_id_reaches_canonical_direct_start_command(monkeypatch):
    hass = _Hass()
    seen = []

    def ready(_hass, params):
        seen.append(params)
        return True, None

    monkeypatch.setattr(actions, "_generic_charger_ready_for_start", ready)
    monkeypatch.setattr(actions, "_start_generic_charger_switch", AsyncMock(return_value=True))

    result = asyncio.run(
        actions._action_start_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "shared_ev_profile_a"}
        )
    )

    assert result is True
    assert seen[0]["vehicle_id"] == "generic_ev"
    assert seen[0]["logical_vehicle_id"] == "shared_ev_profile_a"


def test_inactive_logical_generic_id_cannot_issue_direct_start():
    hass = _Hass(selector_state="tank")

    result = asyncio.run(
        actions._action_start_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "shared_ev_profile_b"}
        )
    )

    assert result is False
    hass.services.async_call.assert_not_awaited()


def test_selected_logical_generic_id_reaches_canonical_direct_stop_command():
    hass = _Hass()

    result = asyncio.run(
        actions._action_stop_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "shared_ev_profile_a"}
        )
    )

    assert result is True
    hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {"entity_id": "switch.shared_ev"}, blocking=True
    )


def test_shared_runtime_metadata_canonicalizes_action_loadpoint_identity():
    assert actions._ev_action_loadpoint_id({
        "charger_type": "generic",
        "vehicle_id": "shared_ev_profile_a",
        "logical_vehicle_id": "shared_ev_profile_a",
        "shared_loadpoint_binding": True,
    }) == "generic_ev"
    assert actions._ev_action_loadpoint_id({
        "charger_type": "sigenergy",
        "vehicle_id": "shared_ev_profile_b",
        "active_logical_vehicle_id": "shared_ev_profile_b",
        "shared_loadpoint_binding": True,
    }) == "sigenergy_charger"


def test_physical_generic_id_cannot_bypass_selected_profile_for_current_write():
    hass = _Hass()

    result = asyncio.run(
        actions._set_vehicle_amps(hass, _Entry(), "generic_ev", 0, _generic_params())
    )

    assert result is False
    hass.services.async_call.assert_not_awaited()


def test_physical_generic_id_cannot_bypass_selected_profile_for_direct_current_write(monkeypatch):
    hass = _Hass()
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_generic_charger_amps_entity", set_amps)

    result = asyncio.run(
        actions._action_set_ev_charging_amps(
            hass,
            _Entry(),
            {
                **_generic_params(),
                "vehicle_id": "generic_ev",
                "charger_amps_entity": "number.shared_ev_amps",
                "amps": 8,
            },
        )
    )

    assert result is False
    set_amps.assert_not_awaited()


def test_selected_logical_generic_id_reaches_canonical_current_command(monkeypatch):
    hass = _Hass()
    seen = []

    def ready(_hass, params):
        seen.append(params)
        return True, None

    monkeypatch.setattr(actions, "_generic_charger_ready_for_start", ready)
    monkeypatch.setattr(actions, "_start_generic_charger_switch", AsyncMock(return_value=True))

    result = asyncio.run(
        actions._set_vehicle_amps(hass, _Entry(), "shared_ev_profile_a", 8, _generic_params())
    )

    assert result is True
    assert seen[0]["vehicle_id"] == "generic_ev"
    assert seen[0]["logical_vehicle_id"] == "shared_ev_profile_a"


def test_physical_evac_id_cannot_bypass_selected_profile_for_direct_start(monkeypatch):
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_start_sigenergy_charger", start)

    result = asyncio.run(
        actions._action_start_ev_charging(
            hass, entry, {"charger_type": "sigenergy", "vehicle_id": "sigenergy_charger"}
        )
    )

    assert result is False
    start.assert_not_awaited()


def test_selected_logical_evac_id_reaches_canonical_direct_start_command(monkeypatch):
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_start_sigenergy_charger", start)

    result = asyncio.run(
        actions._action_start_ev_charging(
            hass, entry, {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a"}
        )
    )

    assert result is True
    assert start.await_args is not None
    assert start.await_args.args[2]["vehicle_id"] == "sigenergy_charger"
    assert start.await_args.args[2]["logical_vehicle_id"] == "shared_ev_profile_a"


def test_physical_evac_id_cannot_bypass_selected_profile_for_direct_stop(monkeypatch):
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    stop = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_stop_sigenergy_charger", stop)

    result = asyncio.run(
        actions._action_stop_ev_charging(
            hass, entry, {"charger_type": "sigenergy", "vehicle_id": "sigenergy_charger"}
        )
    )

    assert result is False
    stop.assert_not_awaited()


def test_physical_evac_id_cannot_bypass_selected_profile_for_direct_current_write(monkeypatch):
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", set_amps)

    result = asyncio.run(
        actions._action_set_ev_charging_amps(
            hass,
            entry,
            {"charger_type": "sigenergy", "vehicle_id": "sigenergy_charger", "amps": 8},
        )
    )

    assert result is False
    set_amps.assert_not_awaited()


def test_selected_logical_evac_id_reaches_canonical_direct_current_command(monkeypatch):
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", set_amps)

    result = asyncio.run(
        actions._action_set_ev_charging_amps(
            hass,
            entry,
            {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a", "amps": 8},
        )
    )

    assert result is True
    assert set_amps.await_args is not None
    assert set_amps.await_args.args[2]["vehicle_id"] == "sigenergy_charger"
    assert set_amps.await_args.args[2]["logical_vehicle_id"] == "shared_ev_profile_a"


def test_unknown_selection_cannot_issue_direct_evac_current_write(monkeypatch):
    hass = _Hass(selector_state="unknown")
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", set_amps)

    result = asyncio.run(
        actions._action_set_ev_charging_amps(
            hass,
            entry,
            {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a", "amps": 8},
        )
    )

    assert result is False
    set_amps.assert_not_awaited()


def test_selected_logical_evac_id_reaches_canonical_current_command(monkeypatch):
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    set_amps = AsyncMock(return_value=True)
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", set_amps)
    monkeypatch.setattr(actions, "_start_sigenergy_charger", start)

    result = asyncio.run(
        actions._set_vehicle_amps(
            hass, entry, "shared_ev_profile_a", 8, {"charger_type": "sigenergy"}
        )
    )

    assert result is True
    assert set_amps.await_args.args[2]["vehicle_id"] == "sigenergy_charger"
    assert set_amps.await_args.args[2]["logical_vehicle_id"] == "shared_ev_profile_a"


def test_active_shared_handoff_fences_interleaved_old_periodic_write(monkeypatch):
    """The old callback cannot write after handoff begins but before its stop returns."""
    hass = _Hass()
    entry = _Entry()
    old_params = {
        **_generic_params(),
        "dynamic_mode": "battery_target",
        "fixed_charge_amps": 16,
    }
    timer_cancelled = []
    old_state = {
        "active": True,
        "active_profile_id": "shared_ev_profile_a",
        "params": old_params,
        "current_amps": 8,
        "cancel_timer": lambda: timer_cancelled.append("periodic"),
    }
    actions._dynamic_ev_state.clear()
    actions._dynamic_ev_state[entry.entry_id] = {"generic_ev": old_state}
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_vehicle_amps", set_amps)

    actions._fence_shared_handoff_runtime(
        hass, entry.entry_id, "generic_ev", old_state
    )
    asyncio.run(actions._dynamic_ev_update(hass, entry, entry.entry_id, "generic_ev"))

    assert timer_cancelled == ["periodic"]
    assert old_state["handoff_settling"] is True
    assert old_state["active"] is False
    assert old_state["params"] is old_params
    assert hass.data["powersync_nir"][entry.entry_id]["dynamic_ev_state"]["generic_ev"] is old_state
    set_amps.assert_not_awaited()

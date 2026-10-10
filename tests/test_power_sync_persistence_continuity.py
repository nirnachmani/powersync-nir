"""Runtime persistence continuity coverage for the restored PowerSync package."""

from __future__ import annotations

import asyncio
import copy
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "power_sync"


class _MemoryStore:
    """Small HA Store boundary that records the actual namespace used at runtime."""

    records: dict[str, dict] = {}
    constructed_keys: list[str] = []

    def __init__(self, _hass, _version, key):
        self.key = key
        type(self).constructed_keys.append(key)

    async def async_load(self):
        return copy.deepcopy(type(self).records.get(self.key))

    async def async_save(self, value):
        type(self).records[self.key] = copy.deepcopy(value)


@pytest.fixture
def isolated_power_sync_runtime(monkeypatch):
    """Discard test-only module imports before monkeypatch restores live modules."""
    yield
    for name in tuple(sys.modules):
        if name == "power_sync" or name.startswith("power_sync."):
            sys.modules.pop(name, None)


def _load_runtime_modules(monkeypatch):
    """Load real persistence code with only its HA dependency surface stubbed."""
    for name in tuple(sys.modules):
        if name == "power_sync" or name.startswith("power_sync."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    package = types.ModuleType("power_sync")
    package.__path__ = [str(COMPONENT)]
    optimization = types.ModuleType("power_sync.optimization")
    optimization.__path__ = [str(COMPONENT / "optimization")]
    monkeypatch.setitem(sys.modules, "power_sync", package)
    monkeypatch.setitem(sys.modules, "power_sync.optimization", optimization)

    homeassistant = types.ModuleType("homeassistant")
    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_core.HomeAssistant = object
    homeassistant_helpers = types.ModuleType("homeassistant.helpers")
    homeassistant_storage = types.ModuleType("homeassistant.helpers.storage")
    homeassistant_storage.Store = _MemoryStore
    homeassistant.helpers = homeassistant_helpers
    homeassistant_helpers.storage = homeassistant_storage
    for name, module in {
        "homeassistant": homeassistant,
        "homeassistant.core": homeassistant_core,
        "homeassistant.helpers": homeassistant_helpers,
        "homeassistant.helpers.storage": homeassistant_storage,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    const = types.ModuleType("power_sync.const")
    for name in (
        "CONF_SOLAR_FORECAST_PROVIDER",
        "CONF_SOLCAST_ESTIMATE_TYPE",
        "CONF_ZAPTEC_STANDALONE_ENABLED",
        "CONF_ZAPTEC_USERNAME",
        "DEFAULT_SOLAR_FORECAST_PROVIDER",
        "DEFAULT_SOLCAST_ESTIMATE_TYPE",
        "SOLAR_FORECAST_PROVIDERS",
        "CONF_GENERIC_CHARGER_ENABLED",
        "CONF_SHARED_LOADPOINT_CONNECTED_VEHICLE_ENTITY",
        "CONF_SHARED_LOADPOINT_PROFILE_A_NAME",
        "CONF_SHARED_LOADPOINT_PROFILE_A_STATE",
        "CONF_SHARED_LOADPOINT_PROFILE_B_NAME",
        "CONF_SHARED_LOADPOINT_PROFILE_B_STATE",
        "CONF_SIGENERGY_CHARGER_ENABLED",
        "CONF_SIGENERGY_CHARGER_TYPE",
        "SIGENERGY_CHARGER_EVAC",
    ):
        setattr(const, name, name.lower())
    const.DOMAIN = "power_sync"
    monkeypatch.setitem(sys.modules, "power_sync.const", const)

    load_estimator = types.ModuleType("power_sync.optimization.load_estimator")
    load_estimator.SolcastForecaster = object
    monkeypatch.setitem(sys.modules, "power_sync.optimization.load_estimator", load_estimator)
    ev_load = types.ModuleType("power_sync.ev_load")
    ev_load.is_current_ev_power_observation = lambda *_args, **_kwargs: False
    monkeypatch.setitem(sys.modules, "power_sync.ev_load", ev_load)
    tesla_ble = types.ModuleType("power_sync.tesla_ble")
    tesla_ble.get_tesla_ble_charge_current_state = lambda *_args, **_kwargs: None
    tesla_ble.get_tesla_ble_charge_power_state = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "power_sync.tesla_ble", tesla_ble)
    triggers = types.ModuleType("power_sync.automations.triggers")
    triggers.evaluate_trigger = lambda *_args, **_kwargs: None
    triggers.evaluate_conditions = lambda *_args, **_kwargs: None
    triggers.TriggerResult = object
    monkeypatch.setitem(sys.modules, "power_sync.automations.triggers", triggers)
    actions = types.ModuleType("power_sync.automations.actions")
    actions.execute_actions = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "power_sync.automations.actions", actions)

    return (
        importlib.import_module("power_sync.automations"),
        importlib.import_module("power_sync.automations.shared_loadpoint"),
    )


def test_restored_runtime_loads_saves_and_reloads_original_automation_records(
    monkeypatch, isolated_power_sync_runtime
):
    """The real store boundary keeps legacy records/options under power_sync."""
    automations, shared_loadpoint = _load_runtime_modules(monkeypatch)
    original_record = {
        "id": 42,
        "name": "Legacy solar guard",
        "trigger_runtime": {"above_since": "2026-10-10T04:00:00+00:00"},
    }
    original_profile = {
        "vehicle_id": "shared_ev_profile_a",
        "display_name": "Tank",
        "charger_type": "generic",
        "app_owned_limit": 80,
    }
    _MemoryStore.records = {
        "power_sync.automations": {
            "automations": [original_record],
            "next_id": 43,
            "push_tokens": {"legacy-device": "token"},
            "custom_tariff": {"power_sync_explicit_periods": [{"start": "00:00"}]},
            "vehicle_charging_configs": [original_profile],
        }
    }
    _MemoryStore.constructed_keys = []

    first_runtime = automations.AutomationStore(object())
    asyncio.run(first_runtime.async_load())
    assert first_runtime.get_by_id(42) == original_record
    assert first_runtime.get_custom_tariff()["power_sync_explicit_periods"] == [{"start": "00:00"}]

    entry = SimpleNamespace(
        data={},
        options={
            "conf_generic_charger_enabled": True,
            "conf_shared_loadpoint_connected_vehicle_entity": "sensor.connected_vehicle",
            "conf_shared_loadpoint_profile_a_name": "Tank",
            "conf_shared_loadpoint_profile_a_state": "tank",
            "conf_shared_loadpoint_profile_b_name": "Tesla",
            "conf_shared_loadpoint_profile_b_state": "tesla",
        },
    )
    assert asyncio.run(shared_loadpoint.ensure_shared_logical_vehicle_configs(entry, first_runtime))
    first_runtime.update_trigger_runtime(42, {"above_since": "2026-10-10T04:05:00+00:00"})
    asyncio.run(first_runtime.async_save())

    restored_runtime = automations.AutomationStore(object())
    asyncio.run(restored_runtime.async_load())
    restored = restored_runtime.get_by_id(42)
    assert restored["name"] == "Legacy solar guard"
    assert restored["trigger_runtime"] == {"above_since": "2026-10-10T04:05:00+00:00"}
    assert restored_runtime.get_custom_tariff()["power_sync_explicit_periods"] == [{"start": "00:00"}]
    profiles = restored_runtime._data["vehicle_charging_configs"]
    assert next(profile for profile in profiles if profile["vehicle_id"] == "shared_ev_profile_a")["app_owned_limit"] == 80
    assert {profile["vehicle_id"] for profile in profiles} == {
        "shared_ev_profile_a",
        "shared_ev_profile_b",
    }
    assert _MemoryStore.constructed_keys == ["power_sync.automations", "power_sync.automations"]
    assert "powersync_nir.automations" not in _MemoryStore.records

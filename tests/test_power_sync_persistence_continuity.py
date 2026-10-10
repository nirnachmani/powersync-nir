"""Regression contracts for original PowerSync persistence after the fork reversal."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "power_sync"
INIT = COMPONENT / "__init__.py"
AUTOMATIONS = COMPONENT / "automations" / "__init__.py"
SESSIONS = COMPONENT / "automations" / "ev_charging_session.py"
OPTIMIZER = COMPONENT / "optimization" / "coordinator.py"
CONFIG_FLOW = COMPONENT / "config_flow.py"
SHARED_LOADPOINT = COMPONENT / "automations" / "shared_loadpoint.py"


def _string_constants(path: Path) -> set[str]:
    """Return literal strings without importing the Home Assistant integration."""
    return {
        node.value
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_original_power_sync_persistence_targets_are_retained() -> None:
    """Existing production learning, automation, and session records remain usable."""
    assert 'STORAGE_KEY = "power_sync.automations"' in AUTOMATIONS.read_text()
    assert '"power_sync_ev_sessions.json"' in SESSIONS.read_text()

    optimizer_strings = _string_constants(OPTIMIZER)
    required_store_templates = {
        "power_sync.costs.",
        "power_sync.solar_forecast_learning.",
        "power_sync.battery_efficiency_learning.",
        "power_sync.solar_export_hold.",
    }
    assert required_store_templates <= optimizer_strings


def test_explicit_tariff_periods_and_shared_loadpoint_config_remain_payload_data() -> None:
    """Saved options and shared logical EV configuration retain their original data."""
    config_source = CONFIG_FLOW.read_text()
    assert '"power_sync_explicit_periods"' in config_source
    assert "saved_periods = custom_tariff.get(\"power_sync_explicit_periods\")" in config_source

    shared_source = SHARED_LOADPOINT.read_text()
    assert "{**getattr(config_entry, \"data\", {}), **getattr(config_entry, \"options\", {})}" in shared_source
    assert 'store._data["vehicle_charging_configs"] = existing' in shared_source


def test_setup_has_no_speculative_entity_registry_rename() -> None:
    """Restoring the original domain must not rewrite deployed entity identities."""
    source = INIT.read_text()
    assert "def _migrate_entity_ids(" not in source
    assert "_migrate_entity_ids(hass, entry)" not in source


def test_component_code_never_targets_the_undeployed_nir_persistence_namespace() -> None:
    """Normal setup and evaluation can only read/write the original namespace."""
    offenders = [
        path.relative_to(COMPONENT)
        for path in COMPONENT.rglob("*.py")
        if "powersync_nir" in path.read_text()
    ]
    assert not offenders


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_external_session_reconciliation_preserves_the_physical_loadpoint_id() -> None:
    """The reversal does not rewrite a shared controller's physical identity."""
    reconciler = _load_module(
        "power_sync_persistence_reconciler",
        COMPONENT / "automations" / "external_session_reconciler.py",
    )
    observed_at = datetime(2026, 10, 10, tzinfo=timezone.utc)

    observation = reconciler.generic_power_observation(
        binding_id="generic_ev",
        power_kw=7.2,
        observed_at=observed_at,
        now=observed_at,
    )

    assert observation.binding_id == "generic_ev"
    assert observation.power_kw == 7.2
    assert observation.fresh


def test_ownership_keeps_the_existing_loadpoint_key() -> None:
    """Logical profiles do not cause persistence to rename the physical key."""
    ownership = _load_module(
        "power_sync_persistence_ownership",
        COMPONENT / "automations" / "ev_ownership.py",
    )

    assert ownership.normalize_vehicle_id("generic_ev") == "generic_ev"
    assert ownership.normalize_vehicle_id("sigenergy_charger") == "sigenergy_charger"

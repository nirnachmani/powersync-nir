"""Cycle-level shared-loadpoint observation is policy-free and fail-closed."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = ROOT / "custom_components" / "power_sync"


def _load_module():
    package = types.ModuleType("power_sync")
    package.__path__ = [str(COMPONENT_ROOT)]
    sys.modules["power_sync"] = package
    automations = types.ModuleType("power_sync.automations")
    automations.__path__ = [str(COMPONENT_ROOT / "automations")]
    sys.modules["power_sync.automations"] = automations
    for name in (
        "power_sync.const",
        "power_sync.automations.shared_loadpoint",
        "power_sync.automations.external_session_reconciler",
    ):
        sys.modules.pop(name, None)
    return importlib.import_module("power_sync.automations.external_session_reconciler")


module = _load_module()
UTC = timezone.utc
NOW = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)


class _State:
    def __init__(self, state, *, observed_at=NOW, unit="kW"):
        self.state = state
        self.last_updated = observed_at
        self.attributes = {"unit_of_measurement": unit}


class _Store:
    def __init__(self, configs=None):
        self._data = {"vehicle_charging_configs": configs or []}
        self.saved = 0

    async def async_save(self):
        self.saved += 1


class _Hass:
    def __init__(self, store, selector="tank", power="7.2", observed_at=NOW):
        self.states = SimpleNamespace(
            get=lambda entity_id: {
                "sensor.connected_vehicle": _State(selector),
                "sensor.shared_power": _State(power, observed_at=observed_at),
                "sensor.profile_power": _State("0", observed_at=observed_at),
            }.get(entity_id)
        )
        self.data = {"power_sync": {"entry-1": {"automation_store": store}}}


class _Entry:
    entry_id = "entry-1"
    data = {}
    options = {
        "generic_charger_enabled": True,
        "generic_charger_power_entity": "sensor.shared_power",
        "shared_loadpoint_connected_vehicle_entity": "sensor.connected_vehicle",
        "shared_loadpoint_profile_a_name": "Tank",
        "shared_loadpoint_profile_a_state": "tank",
        "shared_loadpoint_profile_b_name": "Tesla",
        "shared_loadpoint_profile_b_state": "tesla",
    }


def test_cycle_context_reconciles_selected_generic_loadpoint_as_external():
    store = _Store()
    hass = _Hass(store)

    reconcile = getattr(module, "reconcile_selected_shared_loadpoint_cycle", None)
    assert reconcile is not None
    context = asyncio.run(reconcile(hass, _Entry(), now=NOW))

    assert context == {
        "binding_id": "generic_ev",
        "active_profile_id": "shared_ev_profile_a",
        "origin": "external",
        "physical_active": True,
        "observed_at": NOW,
        "evidence": "fresh_power",
    }
    assert hass.data["power_sync"]["entry-1"]["_shared_loadpoint_cycle_context"] == context
    assert store.saved == 1


def test_cycle_context_reads_selected_generic_profile_params():
    store = _Store([
        {
            "vehicle_id": "shared_ev_profile_a",
            "charger_power_entity": "sensor.profile_power",
        }
    ])
    hass = _Hass(store)

    context = asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, _Entry(), now=NOW))

    assert context["physical_active"] is False
    assert context["origin"] == "unknown"


def test_cycle_context_uses_canonical_powersync_command_origin():
    store = _Store()
    hass = _Hass(store)
    hass.data["power_sync"]["entry-1"]["ev_last_command"] = {
        "generic_ev": {"at": NOW.isoformat(), "source": "powersync", "success": True}
    }

    context = asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, _Entry(), now=NOW))

    assert context["binding_id"] == "generic_ev"
    assert context["origin"] == "powersync"


def test_cycle_context_publishes_unknown_for_stale_generic_power():
    store = _Store()
    hass = _Hass(store, observed_at=NOW - timedelta(seconds=91))

    context = asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, _Entry(), now=NOW))

    assert context["physical_active"] is None
    assert context["origin"] == "unknown"
    assert context["observed_at"] == NOW - timedelta(seconds=91)
    assert context["evidence"] == "stale_or_missing_power"


def test_cycle_context_publishes_fresh_evac_observation_provenance():
    store = _Store()
    hass = _Hass(store)
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }

    class _EvacState:
        charger_type = "evac"
        is_connected = True
        is_charging = True
        power_kw = 7.2

    async def read_evac_state():
        return _EvacState()

    context = asyncio.run(
        module.reconcile_selected_shared_loadpoint_cycle(
            hass, entry, now=NOW, read_evac_state=read_evac_state
        )
    )

    assert context is not None
    assert context["physical_active"] is True
    assert context["origin"] == "external"
    assert context["observed_at"] == NOW
    assert context["evidence"] == "fresh_evac_state"


def test_unselected_or_incomplete_binding_publishes_no_cycle_context():
    store = _Store()
    hass = _Hass(store, selector="unmapped")
    entry_data = hass.data["power_sync"]["entry-1"]
    entry_data["_shared_loadpoint_cycle_context"] = {"origin": "external"}

    assert asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, _Entry(), now=NOW)) is None
    assert "_shared_loadpoint_cycle_context" not in entry_data

    incomplete = _Entry()
    incomplete.options = {"generic_charger_enabled": True}
    assert asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, incomplete, now=NOW)) is None


def test_evac_read_failure_publishes_unknown_context():
    store = _Store()
    hass = _Hass(store)
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }

    async def read_evac_state():
        raise RuntimeError("Modbus unavailable")

    context = asyncio.run(
        module.reconcile_selected_shared_loadpoint_cycle(
            hass, entry, now=NOW, read_evac_state=read_evac_state
        )
    )

    assert context == {
        "binding_id": "sigenergy_charger",
        "active_profile_id": "shared_ev_profile_a",
        "origin": "unknown",
        "physical_active": None,
        "observed_at": None,
        "evidence": "failed_or_unknown_evac_read",
    }
    assert store.saved == 1

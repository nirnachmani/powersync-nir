"""Cycle-level shared-loadpoint observation is policy-free and fail-closed."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


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


def test_cycle_observation_persisted_including_stale_state(tmp_path):
    import json
    diagnostics = importlib.import_module('power_sync.decision_diagnostics')
    hass = _Hass(_Store(), observed_at=NOW - timedelta(seconds=91))
    async def run():
        writer = diagnostics.AsyncDecisionWriter(tmp_path)
        writer.start()
        hass.data['power_sync']['entry-1']['decision_diagnostics'] = writer
        await module.reconcile_selected_shared_loadpoint_cycle(hass, _Entry(), now=NOW)
        await writer.close()
    asyncio.run(run())
    row = json.loads(next(tmp_path.glob('ev-*.jsonl')).read_text())
    assert row['event'] == 'shared_observation' and row['charging'] is None
    assert row['evidence'] == 'stale_or_missing_power' and row['profile'] == 'shared_ev_profile_a'
    assert row['observation_age_seconds'] == 91


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


@pytest.mark.parametrize("loadpoint", ["generic_ev", "sigenergy_charger"])
def test_new_shared_start_rearms_stop_warning_without_claiming_idle(monkeypatch, loadpoint):
    """A/B share a physical warning; a later session may alert again, not clear it."""
    from power_sync import action_events

    hass = _Hass(_Store())
    hass.bus = SimpleNamespace(async_fire=Mock())
    notices = Mock()
    monkeypatch.setattr(action_events, "_notification", notices)
    entry = _Entry()

    def command(name, success=True):
        return {"command": name, "success": success, "source": "powersync",
                "at": datetime.now(UTC).isoformat(), "reason": "charger unavailable"}

    action_events.publish_ev_command(hass, entry, loadpoint, command("stop", False))
    action_events.publish_ev_command(hass, entry, loadpoint, command("start", False))
    action_events.publish_ev_command(hass, entry, loadpoint, command("stop", False))
    assert [call.args[0] for call in hass.bus.async_fire.call_args_list].count(
        action_events.EVENT_EV_STOP_FAILED
    ) == 1
    action_events.publish_ev_command(hass, entry, loadpoint, command("start", True))
    assert notices.call_count == 1  # No physical idle proof yet.
    action_events.publish_ev_command(hass, entry, loadpoint, command("stop", False))
    assert [call.args[0] for call in hass.bus.async_fire.call_args_list].count(
        action_events.EVENT_EV_STOP_FAILED
    ) == 2
    assert notices.call_count == 2


@pytest.mark.parametrize("backend,loadpoint", [
    ("generic", "generic_ev"), ("evac", "sigenergy_charger"),
])
def test_shared_failed_stop_warns_once_and_only_newer_physical_idle_settles(
    backend, loadpoint,
):
    """A/B share a warning key, but observations never release A's physical lease."""
    from power_sync.automations import ev_ownership

    entry = _Entry()
    if backend == "evac":
        entry.options = {
            **entry.options, "generic_charger_enabled": False,
            "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac",
        }
    store = _Store()
    hass = _Hass(store, selector="tank")
    bus = Mock()
    hass.bus = SimpleNamespace(async_fire=bus)
    lease = ev_ownership.claim_ev_ownership(
        hass, entry, loadpoint, owner_mode="scheduled",
        extra={"active_profile_id": "shared_ev_profile_a"},
    )
    failed = ev_ownership.record_ev_command(
        hass, entry, loadpoint, command="stop", success=False,
        reason="time window ended; physical stop not confirmed",
    )
    # A successful actuator acknowledgement alone is not physical proof.
    ev_ownership.record_ev_command(
        hass, entry, loadpoint, command="stop", success=True,
        reason="retry accepted",
    )
    current = ev_ownership.get_ev_last_commands(hass, entry)[loadpoint]
    current["at"] = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
    assert failed is not current
    runtime = hass.data["power_sync"][entry.entry_id]
    assert list(runtime["ev_stop_alerts"]) == [loadpoint]
    assert len([c for c in bus.call_args_list
                if c.args[0] == "power_sync_ev_stop_failed"]) == 1

    # B's selector now observes the same hardware. Unknown selection and an
    # idle sample older than the retry must not settle its warning.
    hass.states = _Hass(store, selector="unmapped", power="0").states
    assert asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, entry)) is None
    old = datetime.fromisoformat(current["at"]) - timedelta(seconds=1)
    hass.states = _Hass(store, selector="tesla", power="0", observed_at=old).states

    evac_power = [0.0]

    class _IdleEvac:
        charger_type = "evac"
        is_connected = True
        is_charging = False

        @property
        def power_kw(self):
            return evac_power[0]

    async def read_idle():
        return _IdleEvac()

    kwargs = {"read_evac_state": read_idle} if backend == "evac" else {}
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, entry, now=old, **kwargs))
    assert list(runtime["ev_stop_alerts"]) == [loadpoint]
    assert "settled_at" not in current

    fresh = datetime.now(UTC) - timedelta(milliseconds=100)
    hass.states = _Hass(store, selector="tesla", power="0", observed_at=fresh).states
    if backend == "evac":
        evac_power[0] = 7.2
        asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, entry, now=fresh, **kwargs))
        assert list(runtime["ev_stop_alerts"]) == [loadpoint]
        assert "settled_at" not in current
        evac_power[0] = 0.0
    asyncio.run(module.reconcile_selected_shared_loadpoint_cycle(hass, entry, now=fresh, **kwargs))
    assert runtime["ev_stop_alerts"] == {}
    assert current["success"] is True
    assert current["settled_at"] == fresh.isoformat()
    assert ev_ownership.get_ev_ownership(hass, entry, loadpoint)[1] is lease
    assert lease["active_profile_id"] == "shared_ev_profile_a"
    observations = [c.args[1] for c in bus.call_args_list
                    if c.args[0] == "power_sync_ev_command"
                    and c.args[1]["physical_confirmation"]]
    assert len(observations) == 1
    assert observations[0]["vehicle_id"] == loadpoint
    assert observations[0]["observed_at"] == fresh.isoformat()


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

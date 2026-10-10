"""Behavioral guards for direct shared Generic and EVAC commands."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


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
ownership = importlib.import_module("powersync_nir.automations.ev_ownership")


class _State:
    def __init__(self, state: str) -> None:
        self.state = state
        self.attributes = {}
        self.last_updated = datetime.now(timezone.utc)


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


def _shared_solar_preflight_setup(*, charger_type="generic", physical_id="generic_ev"):
    hass = _Hass()
    entry = _Entry()
    if charger_type == "sigenergy":
        entry.options = {
            **entry.options,
            "generic_charger_enabled": False,
            "sigenergy_charger_enabled": True,
            "sigenergy_charger_type": "evac",
        }
    hass.data["powersync_nir"]["entry-1"].update(
        {
            "automation_store": SimpleNamespace(
                _data={
                    "solar_surplus_config": {"enabled": True},
                    "vehicle_charging_configs": [
                        {
                            "vehicle_id": "shared_ev_profile_a",
                            "charger_type": charger_type,
                            "solar_charging_enabled": True,
                        }
                    ],
                }
            ),
            "_shared_loadpoint_cycle_context": {
                "binding_id": physical_id,
                "active_profile_id": "shared_ev_profile_a",
                "physical_active": True,
            },
        }
    )
    return hass, entry


def _install_preflight_plug_probe(monkeypatch, result=True):
    plugged = AsyncMock(return_value=result)
    planner = types.ModuleType("powersync_nir.automations.ev_charging_planner")
    planner.is_ev_plugged_in = plugged
    monkeypatch.setitem(sys.modules, planner.__name__, planner)
    return plugged


def test_shared_solar_preflight_allows_selected_generic_with_fresh_matched_context(monkeypatch):
    hass, entry = _shared_solar_preflight_setup()
    plugged = _install_preflight_plug_probe(monkeypatch)

    timer_spy = MagicMock()
    monkeypatch.setattr(actions, "async_track_time_interval", timer_spy)
    monkeypatch.setattr(actions, "async_track_point_in_time", timer_spy)
    dynamic_state_before = dict(actions._dynamic_ev_state)
    preflight = getattr(actions, "_preflight_shared_solar_surplus_decision", None)
    assert preflight is not None
    result = asyncio.run(preflight(hass, entry))

    assert result == {"allowed": True, "reason": "", "source": "solar_surplus"}
    plugged.assert_awaited_once_with(hass, entry, vehicle_vin="shared_ev_profile_a")
    hass.services.async_call.assert_not_awaited()
    timer_spy.assert_not_called()
    assert actions._dynamic_ev_state == dynamic_state_before
    assert "_dynamic_ev_state" not in hass.data["powersync_nir"]["entry-1"]
    assert "ev_ownership" not in hass.data["powersync_nir"]["entry-1"]
    assert "ev_manual_stop_holds" not in hass.data["powersync_nir"]["entry-1"]


def test_shared_solar_preflight_allows_selected_evac_with_fresh_matched_context(monkeypatch):
    hass, entry = _shared_solar_preflight_setup(
        charger_type="sigenergy", physical_id="sigenergy_charger"
    )
    plugged = _install_preflight_plug_probe(monkeypatch)

    result = asyncio.run(actions._preflight_shared_solar_surplus_decision(hass, entry))

    assert result == {"allowed": True, "reason": "", "source": "solar_surplus"}
    plugged.assert_awaited_once_with(hass, entry, vehicle_vin="shared_ev_profile_a")
    hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize(
    ("charger_type", "binding_id"),
    [("generic", "generic_ev"), ("sigenergy", "sigenergy_charger")],
)
def test_observed_solar_adoption_creates_one_seeded_runtime_without_hardware_or_timer(
    monkeypatch, charger_type, binding_id
):
    hass, entry = _shared_solar_preflight_setup(
        charger_type=charger_type, physical_id=binding_id
    )
    actions._dynamic_ev_state.clear()
    timer_spy = MagicMock()
    monkeypatch.setattr(actions, "async_track_time_interval", timer_spy)
    monkeypatch.setattr(actions, "async_track_point_in_time", timer_spy)

    class Session:
        id = "adopted-session"

    manager = SimpleNamespace(start_session=AsyncMock(return_value=Session()))
    sessions = types.ModuleType("powersync_nir.automations.ev_charging_session")
    sessions.get_session_manager = lambda: manager
    monkeypatch.setitem(sys.modules, sessions.__name__, sessions)

    adopt = getattr(actions, "_adopt_observed_solar_surplus_shared_session", None)
    assert adopt is not None
    for _ in range(2):
        assert asyncio.run(
            adopt(
                hass,
                entry,
                binding_id=binding_id,
                active_profile_id="shared_ev_profile_a",
                selected_params={"charger_type": charger_type},
                observed_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
            )
        )

    state = actions._dynamic_ev_state["entry-1"][binding_id]
    assert state["active"] is True
    assert state["active_profile_id"] == "shared_ev_profile_a"
    assert state["charging_started"] is True
    assert state["session_id"] == "adopted-session"
    assert state["params"]["dynamic_mode"] == "solar_surplus"
    assert state["params"]["adoption_provenance"] == "observed_external_session"
    assert manager.start_session.await_count == 1
    assert hass.services.async_call.await_count == 0
    timer_spy.assert_not_called()
    lease = ownership.get_ev_ownership(hass, entry, binding_id)[1]
    assert lease["owner"] == "powersync"
    assert lease["active_profile_id"] == "shared_ev_profile_a"


@pytest.mark.parametrize(
    ("charger_type", "binding_id"),
    [("generic", "generic_ev"), ("sigenergy", "sigenergy_charger")],
)
def test_observed_scheduled_adoption_creates_one_runtime_without_hardware_or_timer(
    monkeypatch, charger_type, binding_id
):
    hass, entry = _shared_solar_preflight_setup(
        charger_type=charger_type, physical_id=binding_id
    )
    actions._dynamic_ev_state.clear()
    timer_spy = MagicMock()
    monkeypatch.setattr(actions, "async_track_time_interval", timer_spy)
    monkeypatch.setattr(actions, "async_track_point_in_time", timer_spy)

    class Session:
        id = "adopted-scheduled-session"

    manager = SimpleNamespace(start_session=AsyncMock(return_value=Session()))
    sessions = types.ModuleType("powersync_nir.automations.ev_charging_session")
    sessions.get_session_manager = lambda: manager
    monkeypatch.setitem(sys.modules, sessions.__name__, sessions)

    adopt = getattr(actions, "_adopt_observed_scheduled_shared_session", None)
    assert adopt is not None
    for _ in range(2):
        assert asyncio.run(
            adopt(
                hass,
                entry,
                binding_id=binding_id,
                active_profile_id="shared_ev_profile_a",
                selected_params={"charger_type": charger_type},
                observed_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
            )
        )

    state = actions._dynamic_ev_state["entry-1"][binding_id]
    assert state["active"] is True
    assert state["active_profile_id"] == "shared_ev_profile_a"
    assert state["charging_started"] is True
    assert state["session_id"] == "adopted-scheduled-session"
    assert state["params"]["dynamic_mode"] == "scheduled"
    assert state["params"]["owner_mode"] == "scheduled"
    assert state["params"]["adoption_provenance"] == "observed_external_session"
    assert manager.start_session.await_count == 1
    hass.services.async_call.assert_not_awaited()
    timer_spy.assert_not_called()
    lease = ownership.get_ev_ownership(hass, entry, binding_id)[1]
    assert lease["owner"] == "powersync"
    assert lease["owner_mode"] == "scheduled"
    assert lease["active_profile_id"] == "shared_ev_profile_a"


def test_shared_solar_preflight_excludes_tesla_and_sigenergy_evdc(monkeypatch):
    hass, entry = _shared_solar_preflight_setup()
    entry.options = {**entry.options, "generic_charger_enabled": False}
    _install_preflight_plug_probe(monkeypatch)

    assert asyncio.run(actions._preflight_shared_solar_surplus_decision(hass, entry)) is None

    hass, entry = _shared_solar_preflight_setup()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evdc",
    }
    _install_preflight_plug_probe(monkeypatch)

    assert asyncio.run(actions._preflight_shared_solar_surplus_decision(hass, entry)) is None


@pytest.mark.parametrize(
    ("context", "solar_enabled", "plugged_in", "reason"),
    [
        (None, True, True, "cycle context is unavailable"),
        (
            {"binding_id": "generic_ev", "active_profile_id": "shared_ev_profile_b", "physical_active": True},
            True,
            True,
            "does not match",
        ),
        (
            {"binding_id": "generic_ev", "active_profile_id": "shared_ev_profile_a", "physical_active": None},
            True,
            True,
            "unknown or stale",
        ),
        (None, False, True, "Solar Surplus is disabled"),
        (None, True, False, "vehicle is not plugged in"),
    ],
)
def test_shared_solar_preflight_fails_closed_without_admission(
    monkeypatch, context, solar_enabled, plugged_in, reason
):
    hass, entry = _shared_solar_preflight_setup()
    entry_data = hass.data["powersync_nir"]["entry-1"]
    if context is not None:
        entry_data["_shared_loadpoint_cycle_context"] = context
    elif solar_enabled is False:
        entry_data["automation_store"]._data["solar_surplus_config"] = {"enabled": False}
    elif plugged_in is False:
        pass
    else:
        entry_data.pop("_shared_loadpoint_cycle_context")
    plugged = _install_preflight_plug_probe(monkeypatch, plugged_in)

    result = asyncio.run(actions._preflight_shared_solar_surplus_decision(hass, entry))

    assert result["allowed"] is False
    assert result["source"] == "solar_surplus"
    assert reason in result["reason"]
    hass.services.async_call.assert_not_awaited()
    assert "_dynamic_ev_state" not in entry_data
    assert "ev_ownership" not in entry_data
    if reason != "vehicle is not plugged in":
        plugged.assert_not_awaited()


def test_cycle_decision_ledger_records_selected_shared_generic_schedule_decision():
    hass = _Hass()

    actions._begin_automated_shared_loadpoint_cycle(hass, _Entry())
    actions._record_automated_shared_loadpoint_decision(
        hass,
        _Entry(),
        allowed=True,
        responsible_mode="scheduled",
        reason="Scheduled window",
        source="scheduled",
    )

    assert hass.data["powersync_nir"]["entry-1"][
        "_automated_shared_loadpoint_decision_ledger"
    ] == {
        "generic_ev": {
            "shared_ev_profile_a": {
                "allowed": True,
                "responsible_mode": "scheduled",
                "reason": "Scheduled window",
                "source": "scheduled",
            }
        }
    }


def test_cycle_decision_ledger_records_selected_shared_evac_schedule_decision():
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }

    actions._begin_automated_shared_loadpoint_cycle(hass, entry)
    actions._record_automated_shared_loadpoint_decision(
        hass,
        entry,
        allowed=False,
        responsible_mode="scheduled",
        reason="Outside schedule",
        source="",
    )

    assert hass.data["powersync_nir"]["entry-1"][
        "_automated_shared_loadpoint_decision_ledger"
    ]["sigenergy_charger"]["shared_ev_profile_a"] == {
        "allowed": False,
        "responsible_mode": "scheduled",
        "reason": "Outside schedule",
        "source": "",
    }


def test_cycle_decision_ledger_omits_unselected_and_non_shared_backends():
    hass = _Hass(selector_state="unmapped")

    actions._begin_automated_shared_loadpoint_cycle(hass, _Entry())
    actions._record_automated_shared_loadpoint_decision(
        hass, _Entry(), allowed=False, responsible_mode="scheduled", reason="No", source=""
    )

    entry = _Entry()
    entry.options = {"shared_loadpoint_connected_vehicle_entity": "sensor.connected_vehicle"}
    actions._record_automated_shared_loadpoint_decision(
        hass, entry, allowed=True, responsible_mode="scheduled", reason="No", source="scheduled"
    )

    tesla_hass = _Hass()
    actions._begin_automated_shared_loadpoint_cycle(tesla_hass, _Entry())
    tesla_entry = _Entry()
    tesla_entry.options = {**tesla_entry.options, "generic_charger_enabled": False}
    actions._record_automated_shared_loadpoint_decision(
        tesla_hass,
        tesla_entry,
        allowed=True,
        responsible_mode="scheduled",
        reason="No",
        source="scheduled",
    )

    assert hass.data["powersync_nir"]["entry-1"][
        "_automated_shared_loadpoint_decision_ledger"
    ] == {}
    assert tesla_hass.data["powersync_nir"]["entry-1"][
        "_automated_shared_loadpoint_decision_ledger"
    ] == {}


def test_cycle_decision_ledger_is_cleared_with_sequence_cycle():
    hass = _Hass()
    actions._begin_automated_shared_loadpoint_cycle(hass, _Entry())
    actions._record_automated_shared_loadpoint_decision(
        hass, _Entry(), allowed=True, responsible_mode="scheduled", reason="Yes", source="scheduled"
    )

    actions._clear_automated_shared_loadpoint_cycle(hass, _Entry())

    assert "_automated_shared_loadpoint_decision_ledger" not in hass.data["powersync_nir"]["entry-1"]


def _claim_shared_loadpoint(
    hass, *, profile_id: str, owner_mode: str = "scheduled", owner: str = "powersync"
) -> None:
    ownership.claim_ev_ownership(
        hass,
        _Entry(),
        "generic_ev",
        owner=owner,
        owner_mode=owner_mode,
        extra={"active_profile_id": profile_id},
    )


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


def test_direct_shared_start_claims_physical_lease_before_competing_profile_can_start(monkeypatch):
    """Sequential selector changes cannot let lease-free profiles race the shared switch."""
    hass = _Hass()
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_start_generic_charger_switch", start)

    assert asyncio.run(
        actions._action_start_ev_charging(
            hass,
            _Entry(),
            {**_generic_params(), "vehicle_id": "shared_ev_profile_a"},
        )
    ) is True

    hass.states = SimpleNamespace(
        get=lambda entity_id: {
            "sensor.connected_vehicle": _State("tesla"),
            "switch.shared_ev": _State("on"),
        }.get(entity_id)
    )
    assert asyncio.run(
        actions._action_start_ev_charging(
            hass,
            _Entry(),
            {**_generic_params(), "vehicle_id": "shared_ev_profile_b"},
        )
    ) is False

    _lease_id, lease = ownership.get_ev_ownership(hass, _Entry(), "generic_ev")
    assert lease is not None
    assert lease["active_profile_id"] == "shared_ev_profile_a"
    start.assert_awaited_once()


def test_direct_shared_start_is_blocked_when_physical_lease_belongs_to_other_profile(monkeypatch):
    hass = _Hass(selector_state="tesla")
    _claim_shared_loadpoint(hass, profile_id="shared_ev_profile_a")
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_start_generic_charger_switch", start)

    result = asyncio.run(
        actions._action_start_ev_charging(
            hass,
            _Entry(),
            {
                **_generic_params(),
                "vehicle_id": "shared_ev_profile_b",
                "owner_mode": "scheduled",
            },
        )
    )

    assert result is False
    start.assert_not_awaited()


def test_fresh_idle_direct_lease_transfers_to_newly_selected_profile_without_dynamic_runtime(monkeypatch):
    """A failed direct A command cannot strand an idle physical lease from B."""
    hass = _Hass()
    start = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(actions, "_start_generic_charger_switch", start)
    idle_power = _State("0")
    idle_power.attributes = {"unit_of_measurement": "W"}
    idle_power.last_updated = datetime.now(timezone.utc)

    assert asyncio.run(
        actions._action_start_ev_charging(
            hass,
            _Entry(),
            {
                **_generic_params(),
                "vehicle_id": "shared_ev_profile_a",
                "charger_power_entity": "sensor.shared_ev_power",
            },
        )
    ) is False
    hass.states = SimpleNamespace(
        get=lambda entity_id: {
            "sensor.connected_vehicle": _State("tesla"),
            "switch.shared_ev": _State("on"),
            "sensor.shared_ev_power": idle_power,
        }.get(entity_id)
    )

    assert asyncio.run(
        actions._action_start_ev_charging(
            hass,
            _Entry(),
            {
                **_generic_params(),
                "vehicle_id": "shared_ev_profile_b",
                "charger_power_entity": "sensor.shared_ev_power",
            },
        )
    ) is True

    _lease_id, lease = ownership.get_ev_ownership(hass, _Entry(), "generic_ev")
    assert lease is not None
    assert lease["active_profile_id"] == "shared_ev_profile_b"
    assert start.await_count == 2


def test_non_idle_direct_observation_cannot_transfer_lease_without_dynamic_runtime(monkeypatch):
    hass = _Hass(selector_state="tesla")
    _claim_shared_loadpoint(hass, profile_id="shared_ev_profile_a")
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_start_generic_charger_switch", start)

    for observation in (
        SimpleNamespace(fresh=True, charging=True),
        SimpleNamespace(fresh=True, charging=None),
        SimpleNamespace(fresh=False, charging=False),
    ):
        monkeypatch.setattr(
            actions,
            "_observe_shared_loadpoint_for_direct_lease",
            AsyncMock(return_value=observation),
        )

        assert asyncio.run(
            actions._action_start_ev_charging(
                hass, _Entry(), {**_generic_params(), "vehicle_id": "shared_ev_profile_b"}
            )
        ) is False
        _lease_id, lease = ownership.get_ev_ownership(hass, _Entry(), "generic_ev")
        assert lease is not None
        assert lease["active_profile_id"] == "shared_ev_profile_a"

    start.assert_not_awaited()


def test_fresh_idle_direct_evac_lease_transfers_to_newly_selected_profile(monkeypatch):
    hass = _Hass(selector_state="tesla")
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    ownership.claim_ev_ownership(
        hass,
        entry,
        "sigenergy_charger",
        owner="powersync",
        owner_mode="scheduled",
        extra={"active_profile_id": "shared_ev_profile_a"},
    )
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_start_sigenergy_charger", start)
    monkeypatch.setattr(
        actions,
        "_observe_shared_loadpoint_for_direct_lease",
        AsyncMock(return_value=SimpleNamespace(fresh=True, charging=False)),
    )

    assert asyncio.run(
        actions._action_start_ev_charging(
            hass, entry, {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_b"}
        )
    ) is True
    _lease_id, lease = ownership.get_ev_ownership(hass, entry, "sigenergy_charger")
    assert lease is not None
    assert lease["active_profile_id"] == "shared_ev_profile_b"
    start.assert_awaited_once()


def test_inactive_logical_generic_id_cannot_issue_direct_start():
    hass = _Hass(selector_state="tank")

    result = asyncio.run(
        actions._action_start_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "shared_ev_profile_b"}
        )
    )

    assert result is False
    hass.services.async_call.assert_not_awaited()


def test_selected_logical_generic_id_claims_physical_lease_before_direct_stop_write():
    hass = _Hass()
    leases_at_write = []

    async def capture_lease_at_write(*_args, **_kwargs):
        _lease_id, lease = ownership.get_ev_ownership(hass, _Entry(), "generic_ev")
        leases_at_write.append(lease)

    hass.services.async_call.side_effect = capture_lease_at_write
    result = asyncio.run(
        actions._action_stop_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "shared_ev_profile_a"}
        )
    )

    assert result is True
    hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {"entity_id": "switch.shared_ev"}, blocking=True
    )
    assert len(leases_at_write) == 1
    assert leases_at_write[0] is not None
    assert leases_at_write[0]["owner"] == "powersync"
    assert leases_at_write[0]["active_profile_id"] == "shared_ev_profile_a"


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


def test_direct_shared_current_write_claims_lease_for_selected_profile(monkeypatch):
    hass = _Hass()
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_generic_charger_amps_entity", set_amps)

    assert asyncio.run(
        actions._action_set_ev_charging_amps(
            hass,
            _Entry(),
            {
                **_generic_params(),
                "vehicle_id": "shared_ev_profile_a",
                "charger_amps_entity": "number.shared_ev_amps",
                "amps": 8,
            },
        )
    ) is True

    _lease_id, lease = ownership.get_ev_ownership(hass, _Entry(), "generic_ev")
    assert lease is not None
    assert lease["active_profile_id"] == "shared_ev_profile_a"
    set_amps.assert_awaited_once()


def test_set_vehicle_amps_claims_shared_lease_before_competing_profile_can_write(monkeypatch):
    hass = _Hass()
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_generic_charger_amps_entity", set_amps)

    params = {**_generic_params(), "charger_amps_entity": "number.shared_ev_amps"}

    assert asyncio.run(
        actions._set_vehicle_amps(
            hass, _Entry(), "shared_ev_profile_a", 8, params
        )
    ) is True

    hass.states = SimpleNamespace(
        get=lambda entity_id: {
            "sensor.connected_vehicle": _State("tesla"),
            "switch.shared_ev": _State("on"),
        }.get(entity_id)
    )
    assert asyncio.run(
        actions._set_vehicle_amps(
            hass, _Entry(), "shared_ev_profile_b", 8, _generic_params()
        )
    ) is False

    _lease_id, lease = ownership.get_ev_ownership(hass, _Entry(), "generic_ev")
    assert lease is not None
    assert lease["active_profile_id"] == "shared_ev_profile_a"
    set_amps.assert_awaited_once()


def test_direct_shared_current_write_reaches_current_physical_lease_owner(monkeypatch):
    hass = _Hass()
    _claim_shared_loadpoint(hass, profile_id="shared_ev_profile_a")
    set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_generic_charger_amps_entity", set_amps)

    result = asyncio.run(
        actions._action_set_ev_charging_amps(
            hass,
            _Entry(),
            {
                **_generic_params(),
                "vehicle_id": "shared_ev_profile_a",
                "owner_mode": "scheduled",
                "charger_amps_entity": "number.shared_ev_amps",
                "amps": 8,
            },
        )
    )

    assert result is True
    set_amps.assert_awaited_once()


def test_direct_shared_stop_is_blocked_when_foreign_owner_controls_physical_loadpoint():
    hass = _Hass()
    _claim_shared_loadpoint(
        hass,
        profile_id="shared_ev_profile_a",
        owner_mode="external",
        owner="external",
    )

    result = asyncio.run(
        actions._action_stop_ev_charging(
            hass, _Entry(), {**_generic_params(), "vehicle_id": "shared_ev_profile_a"}
        )
    )

    assert result is False
    hass.services.async_call.assert_not_awaited()


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


def test_selected_logical_evac_stop_claims_physical_lease_before_write(monkeypatch):
    hass = _Hass()
    entry = _Entry()
    entry.options = {
        **entry.options,
        "generic_charger_enabled": False,
        "sigenergy_charger_enabled": True,
        "sigenergy_charger_type": "evac",
    }
    leases_at_write = []

    async def capture_lease_at_write(*_args, **_kwargs):
        _lease_id, lease = ownership.get_ev_ownership(hass, entry, "sigenergy_charger")
        leases_at_write.append(lease)
        return True

    stop = AsyncMock(side_effect=capture_lease_at_write)
    monkeypatch.setattr(actions, "_stop_sigenergy_charger", stop)

    assert asyncio.run(
        actions._action_stop_ev_charging(
            hass, entry, {"charger_type": "sigenergy", "vehicle_id": "shared_ev_profile_a"}
        )
    ) is True

    assert len(leases_at_write) == 1
    assert leases_at_write[0] is not None
    assert leases_at_write[0]["owner"] == "powersync"
    assert leases_at_write[0]["active_profile_id"] == "shared_ev_profile_a"
    assert stop.await_args is not None
    assert stop.await_args.args[2]["vehicle_id"] == "sigenergy_charger"


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


def test_active_shared_handoff_stops_outgoing_profile_before_incoming_profile_can_run(monkeypatch):
    """A selector change authorizes A's physical stop, not B's policy."""
    hass = _Hass(selector_state="tesla")
    entry = _Entry()
    old_params = {
        **_generic_params(),
        "vehicle_id": "generic_ev",
        "vehicle_vin": "generic_ev",
        "logical_vehicle_id": "shared_ev_profile_a",
        "active_logical_vehicle_id": "shared_ev_profile_a",
        "shared_loadpoint_binding": True,
        "dynamic_mode": "battery_target",
        "owner_mode": "scheduled",
    }
    old_state = {
        "active": True,
        "active_profile_id": "shared_ev_profile_a",
        "params": old_params,
        "current_amps": 8,
    }
    actions._dynamic_ev_state.clear()
    actions._dynamic_ev_state[entry.entry_id] = {"generic_ev": old_state}
    _claim_shared_loadpoint(hass, profile_id="shared_ev_profile_a")

    reconciler = importlib.import_module(
        "powersync_nir.automations.external_session_reconciler"
    )
    monkeypatch.setattr(
        reconciler,
        "generic_observation_from_hass",
        lambda *_args, **_kwargs: SimpleNamespace(fresh=True, charging=True),
    )
    monkeypatch.setattr(
        reconciler,
        "reconcile_shared_external_session",
        lambda *_args, **_kwargs: SimpleNamespace(active_profile_id="shared_ev_profile_a"),
    )

    stop_results = []

    async def stop_and_inspect(_reconciliation, *, stop, **_kwargs):
        stop_results.append(await stop())
        return False

    monkeypatch.setattr(reconciler, "stop_and_confirm_shared_handoff", stop_and_inspect)

    result = asyncio.run(
        actions._action_start_ev_charging_dynamic(
            hass,
            entry,
            {
                **_generic_params(),
                "vehicle_id": "shared_ev_profile_b",
                "dynamic_mode": "battery_target",
                "owner_mode": "scheduled",
            },
        )
    )

    assert result is False
    assert stop_results == [True]
    hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {"entity_id": "switch.shared_ev"}, blocking=True
    )


def test_shared_dynamic_session_keeps_logical_identity_for_periodic_rate_and_stop(monkeypatch):
    """A shared runtime carries its selected profile through later physical writes."""
    hass = _Hass()
    entry = _Entry()
    actions._dynamic_ev_state.clear()

    start_set_amps = AsyncMock(return_value=True)
    original_set_amps = actions._set_vehicle_amps
    monkeypatch.setattr(actions, "_set_vehicle_amps", start_set_amps)
    monkeypatch.setattr(actions, "_resolve_teslemetry_bt_prefix", lambda _hass: None)

    assert asyncio.run(
        actions._action_start_ev_charging_dynamic(
            hass,
            entry,
            {
                **_generic_params(),
                "vehicle_id": "shared_ev_profile_a",
                "dynamic_mode": "battery_target",
                "fixed_charge_amps": 8,
                "max_charge_amps": 8,
            },
        )
    ) is True

    state = actions._dynamic_ev_state[entry.entry_id]["generic_ev"]
    runtime_params = state["params"]
    assert runtime_params["logical_vehicle_id"] == "shared_ev_profile_a"
    assert runtime_params["active_logical_vehicle_id"] == "shared_ev_profile_a"
    assert runtime_params["shared_loadpoint_binding"] is True

    # Simulate the later controller tick using the persisted runtime params.
    monkeypatch.setattr(actions, "_set_vehicle_amps", original_set_amps)
    state["current_amps"] = 0
    monkeypatch.setattr(
        actions, "_generic_charger_ready_for_start", lambda _hass, _params: (True, None)
    )
    monkeypatch.setattr(
        actions, "_clear_ble_dynamic_session_if_unplugged", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        actions, "_release_dynamic_tesla_if_away", AsyncMock(return_value=False)
    )
    periodic_set_amps = AsyncMock(return_value=True)
    monkeypatch.setattr(actions, "_set_vehicle_amps", periodic_set_amps)
    assert asyncio.run(
        actions._dynamic_ev_update(hass, entry, entry.entry_id, "generic_ev")
    ) is None
    periodic_set_amps.assert_awaited_once_with(
        hass, entry, "generic_ev", 8, runtime_params
    )

    # Its dynamic stop uses the same persisted identity to reach the physical key.
    monkeypatch.setattr(actions, "_set_vehicle_amps", original_set_amps)
    assert asyncio.run(
        actions._action_stop_ev_charging_dynamic(
            hass,
            entry,
            {"vehicle_id": "generic_ev", "stop_charging": True},
        )
    ) is True
    assert hass.services.async_call.await_args_list[-1].args == (
        "switch", "turn_off", {"entity_id": "switch.shared_ev"}
    )

    # The physical pseudo-ID is still not a substitute for a logical profile.
    assert asyncio.run(
        actions._set_vehicle_amps(hass, entry, "generic_ev", 8, _generic_params())
    ) is False


@pytest.mark.parametrize(
    ("charger_type", "boundary"),
    (
        ("generic", "start"),
        ("generic", "stop"),
        ("generic", "current"),
        ("sigenergy", "start"),
        ("sigenergy", "stop"),
        ("sigenergy", "current"),
    ),
)
def test_active_cycle_budget_blocks_competing_direct_shared_command_before_io(
    monkeypatch, charger_type, boundary
):
    """Every direct Generic/EVAC boundary consumes the active cycle token."""
    hass = _Hass()
    entry = _Entry()
    if charger_type == "sigenergy":
        entry.options = {
            **entry.options,
            "generic_charger_enabled": False,
            "sigenergy_charger_enabled": True,
            "sigenergy_charger_type": "evac",
        }

    physical_id = "generic_ev" if charger_type == "generic" else "sigenergy_charger"
    first = {
        "charger_type": charger_type,
        "shared_loadpoint_binding": True,
        "logical_vehicle_id": "shared_ev_profile_a",
    }
    competitor = {
        "charger_type": charger_type,
        "shared_loadpoint_binding": True,
        "logical_vehicle_id": "shared_ev_profile_b",
        "active_logical_vehicle_id": "shared_ev_profile_b",
        "vehicle_id": physical_id,
    }
    if charger_type == "generic":
        competitor.update(
            charger_switch_entity="switch.shared_ev",
            charger_amps_entity="number.shared_ev_amps",
        )

    async def resolve(*_args, **_kwargs):
        return physical_id, competitor

    monkeypatch.setattr(actions, "_resolve_shared_loadpoint_direct_command", resolve)
    actions._begin_automated_shared_loadpoint_cycle(hass, entry)
    assert actions._reserve_automated_shared_loadpoint_sequence(hass, entry, first) is True

    if charger_type == "generic":
        monkeypatch.setattr(actions, "_generic_charger_ready_for_start", lambda *_args: (True, None))
        monkeypatch.setattr(actions, "_normalize_generic_charger_amps", lambda *_args: 8)
        write = AsyncMock(return_value=True)
        if boundary == "start":
            monkeypatch.setattr(actions, "_start_generic_charger_switch", write)
        elif boundary == "current":
            monkeypatch.setattr(actions, "_set_generic_charger_amps_entity", write)
    else:
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(actions, "_with_sigenergy_charger_capabilities", lambda *_args: competitor)
        if boundary == "start":
            monkeypatch.setattr(actions, "_start_sigenergy_charger", write)
        elif boundary == "stop":
            monkeypatch.setattr(actions, "_stop_sigenergy_charger", write)
        else:
            monkeypatch.setattr(actions, "_set_sigenergy_charger_amps", write)

    if boundary == "start":
        result = asyncio.run(actions._action_start_ev_charging(hass, entry, competitor))
    elif boundary == "stop":
        result = asyncio.run(actions._action_stop_ev_charging(hass, entry, competitor))
    else:
        result = asyncio.run(
            actions._action_set_ev_charging_amps(
                hass, entry, {**competitor, "amps": 8}
            )
        )

    assert result is False
    if boundary == "stop" and charger_type == "generic":
        hass.services.async_call.assert_not_awaited()
    else:
        write.assert_not_awaited()


@pytest.mark.parametrize(("charger_type", "physical_id"), (("generic", "generic_ev"), ("sigenergy", "sigenergy_charger")))
def test_external_session_guarded_stop_uses_selected_profile_route(monkeypatch, charger_type, physical_id):
    hass = _Hass()
    entry = _Entry()
    params = {"charger_type": charger_type, "vehicle_id": "shared_ev_profile_a"}
    if charger_type == "generic":
        params["charger_switch_entity"] = "switch.shared_ev"
    else:
        entry.options = {**entry.options, "generic_charger_enabled": False, "sigenergy_charger_enabled": True, "sigenergy_charger_type": "evac"}
        write = AsyncMock(return_value=True)
        monkeypatch.setattr(actions, "_stop_sigenergy_charger", write)
    ownership.claim_ev_ownership(
        hass,
        entry,
        physical_id,
        owner="external",
        owner_mode="external",
        extra={"active_profile_id": "shared_ev_profile_a"},
    )

    assert asyncio.run(actions._stop_external_shared_session_guarded(hass, entry, params)) is True
    if charger_type == "generic":
        hass.services.async_call.assert_awaited_once_with("switch", "turn_off", {"entity_id": "switch.shared_ev"}, blocking=True)
    else:
        assert write.await_args.args[2]["vehicle_id"] == physical_id
        assert write.await_args.args[2]["active_logical_vehicle_id"] == "shared_ev_profile_a"

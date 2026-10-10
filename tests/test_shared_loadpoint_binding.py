"""Tests for two named profiles bound to one physical loadpoint."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = ROOT / "custom_components" / "powersync_nir"


def _load_shared_loadpoint():
    """Load the pure binding module without importing HA's integration package."""
    for name, path in (
        ("custom_components", ROOT / "custom_components"),
        ("custom_components.powersync_nir", COMPONENT_ROOT),
        ("custom_components.powersync_nir.automations", COMPONENT_ROOT / "automations"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules.setdefault(name, package)
    for name, path in (
        ("custom_components.powersync_nir.const", COMPONENT_ROOT / "const.py"),
        (
            "custom_components.powersync_nir.automations.shared_loadpoint",
            COMPONENT_ROOT / "automations" / "shared_loadpoint.py",
        ),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["custom_components.powersync_nir.automations.shared_loadpoint"]


def _load_session_manager():
    """Load session tracking with the small HA clock surface it uses."""
    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    util = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
    dt = sys.modules.setdefault("homeassistant.util.dt", types.ModuleType("homeassistant.util.dt"))
    dt.now = lambda: datetime.now(timezone.utc)
    dt.DEFAULT_TIME_ZONE = timezone.utc
    homeassistant.util = util
    util.dt = dt

    name = "custom_components.powersync_nir.automations.ev_charging_session"
    spec = importlib.util.spec_from_file_location(
        name, COMPONENT_ROOT / "automations" / "ev_charging_session.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shared_loadpoint = _load_shared_loadpoint()
PROFILE_A_ID = shared_loadpoint.PROFILE_A_ID
PROFILE_B_ID = shared_loadpoint.PROFILE_B_ID
SharedLoadpointBinding = shared_loadpoint.SharedLoadpointBinding
ensure_shared_logical_vehicle_configs = shared_loadpoint.ensure_shared_logical_vehicle_configs
shared_profile_configs = shared_loadpoint.shared_profile_configs


class FakeStore:
    def __init__(self):
        self._data = {"vehicle_charging_configs": []}
        self.saves = 0

    async def async_save(self):
        self.saves += 1


class FakeHass:
    def __init__(self, state):
        self.states = SimpleNamespace(
            get=lambda entity_id: SimpleNamespace(state=state)
            if entity_id == "sensor.connected_vehicle"
            else None
        )


def _entry(**options):
    return SimpleNamespace(data={}, options=options)


def _options(**overrides):
    options = {
        "generic_charger_enabled": True,
        "shared_loadpoint_connected_vehicle_entity": "sensor.connected_vehicle",
        "shared_loadpoint_profile_a_name": "GWM Tank 500",
        "shared_loadpoint_profile_a_state": "tank",
        "shared_loadpoint_profile_b_name": "Tesla Model Y",
        "shared_loadpoint_profile_b_state": "model_y",
    }
    options.update(overrides)
    return options


def test_binding_resolves_two_profiles_and_fails_closed():
    binding = SharedLoadpointBinding.from_options(_options())

    assert binding is not None
    assert binding.resolve_state(" TANK ") == PROFILE_A_ID
    assert binding.resolve_state("MODEL_Y") == PROFILE_B_ID
    assert binding.resolve_state("unknown") is None
    assert binding.resolve_state("unavailable") is None


def test_duplicate_mapping_state_disables_the_binding():
    assert SharedLoadpointBinding.from_options(
        _options(shared_loadpoint_profile_b_state="Tank")
    ) is None


def test_duplicate_profile_names_disable_the_binding():
    assert SharedLoadpointBinding.from_options(
        _options(shared_loadpoint_profile_b_name="  gwm TANK 500 ")
    ) is None


def test_profile_configs_are_named_and_share_one_physical_backend():
    configs = shared_profile_configs(_entry(**_options()))

    assert [(item["vehicle_id"], item["display_name"]) for item in configs] == [
        (PROFILE_A_ID, "GWM Tank 500"),
        (PROFILE_B_ID, "Tesla Model Y"),
    ]
    assert {item["charger_type"] for item in configs} == {"generic"}
    assert all(item["shared_loadpoint"] for item in configs)


def test_two_physical_backends_do_not_create_a_shared_binding():
    configs = shared_profile_configs(
        _entry(**_options(
            sigenergy_charger_enabled=True,
            sigenergy_charger_type="evac",
        ))
    )
    assert configs == []


def test_selected_profile_resolves_to_one_physical_generic_command_target():
    resolver = getattr(shared_loadpoint, "resolve_shared_loadpoint_command", None)
    assert resolver is not None

    resolved = resolver(
        FakeHass("tank"),
        _entry(**_options()),
        PROFILE_A_ID,
        {"charger_type": "generic", "max_charge_amps": 20},
    )

    assert resolved["vehicle_id"] == "generic_ev"
    assert resolved["vehicle_vin"] == "generic_ev"
    assert resolved["active_logical_vehicle_id"] == PROFILE_A_ID
    assert resolved["max_charge_amps"] == 20


def test_inactive_or_unknown_profile_cannot_resolve_a_shared_command():
    resolver = getattr(shared_loadpoint, "resolve_shared_loadpoint_command", None)
    assert resolver is not None

    entry = _entry(**_options())
    assert resolver(FakeHass("tank"), entry, PROFILE_B_ID, {"charger_type": "generic"}) is None
    assert resolver(FakeHass("unknown"), entry, PROFILE_A_ID, {"charger_type": "generic"}) is None


def test_fresh_idle_observation_hands_shared_runtime_to_selected_profile_in_place():
    handoff = getattr(shared_loadpoint, "handoff_idle_shared_profile", None)
    assert handoff is not None

    timer = object()
    session_id = "session-1"
    runtime_state = {
        "active_profile_id": PROFILE_A_ID,
        "params": {
            "active_logical_vehicle_id": PROFILE_A_ID,
            "logical_vehicle_id": PROFILE_A_ID,
            "charger_type": "generic",
        },
        "cancel_timer": timer,
        "session_id": session_id,
        "current_amps": 0,
    }
    lease = {"active_profile_id": PROFILE_A_ID, "session_id": session_id}
    idle_observation = SimpleNamespace(fresh=True, charging=False)

    assert handoff(runtime_state, lease, PROFILE_B_ID, idle_observation) is True
    assert runtime_state["active_profile_id"] == PROFILE_B_ID
    assert runtime_state["params"]["active_logical_vehicle_id"] == PROFILE_B_ID
    assert runtime_state["params"]["logical_vehicle_id"] == PROFILE_B_ID
    assert lease["active_profile_id"] == PROFILE_B_ID
    assert runtime_state["cancel_timer"] is timer
    assert runtime_state["session_id"] == session_id


def test_charging_or_unknown_observation_never_hands_shared_runtime_to_other_profile():
    handoff = getattr(shared_loadpoint, "handoff_idle_shared_profile", None)
    assert handoff is not None

    for observation in (
        SimpleNamespace(fresh=True, charging=True),
        SimpleNamespace(fresh=True, charging=None),
        SimpleNamespace(fresh=False, charging=None),
    ):
        runtime_state = {
            "active_profile_id": PROFILE_A_ID,
            "params": {"active_logical_vehicle_id": PROFILE_A_ID},
            "cancel_timer": object(),
            "session_id": "session-1",
        }
        lease = {"active_profile_id": PROFILE_A_ID, "session_id": "session-1"}

        assert handoff(runtime_state, lease, PROFILE_B_ID, observation) is False
        assert runtime_state["active_profile_id"] == PROFILE_A_ID
        assert runtime_state["params"]["active_logical_vehicle_id"] == PROFILE_A_ID
        assert lease["active_profile_id"] == PROFILE_A_ID


def test_idle_handoff_transfers_active_physical_session_attribution_in_place():
    sessions = _load_session_manager()
    manager = sessions.ChargingSessionManager(SimpleNamespace())
    session = sessions.ChargingSession(
        id="session-1",
        vehicle_id=PROFILE_A_ID,
        loadpoint_id="generic_ev",
        start_time="2026-01-01T00:00:00+00:00",
        total_energy_kwh=4.2,
    )
    manager.active_sessions["generic_ev"] = session

    transferred = asyncio.run(
        manager.transfer_idle_session_attribution(
            loadpoint_id="generic_ev",
            from_vehicle_id=PROFILE_A_ID,
            to_vehicle_id=PROFILE_B_ID,
            fresh_idle=True,
        )
    )

    assert transferred is True
    assert manager.active_sessions == {"generic_ev": session}
    assert session.vehicle_id == PROFILE_B_ID
    assert session.id == "session-1"
    assert session.total_energy_kwh == 4.2


def test_ensure_profiles_preserves_app_owned_config_and_updates_name():
    async def exercise():
        store = FakeStore()
        entry = _entry(**_options())

        assert await ensure_shared_logical_vehicle_configs(entry, store)
        store._data["vehicle_charging_configs"][0]["max_amps"] = 20
        entry.options["shared_loadpoint_profile_a_name"] = "Tank 500"

        assert await ensure_shared_logical_vehicle_configs(entry, store)
        first = store._data["vehicle_charging_configs"][0]
        assert first["display_name"] == "Tank 500"
        assert first["max_amps"] == 20
        assert store.saves == 2

    asyncio.run(exercise())

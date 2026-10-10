"""Behavior tests for pure shared-loadpoint observation reconciliation."""

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "custom_components"
    / "powersync_nir"
    / "automations"
    / "external_session_reconciler.py"
)
SPEC = importlib.util.spec_from_file_location("powersync_external_session_reconciler_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


UTC = timezone.utc
NOW = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)


def test_reconciliation_state_round_trips_through_private_binding_record() -> None:
    class Entry:
        entry_id = "entry-1"

    class Store:
        def __init__(self) -> None:
            self._data = {}
            self.saved = 0

        async def async_save(self) -> None:
            self.saved += 1

    class Hass:
        def __init__(self, store: Store) -> None:
            self.data = {"powersync_nir": {"entry-1": {"automation_store": store}}}

    store = Store()
    hass = Hass(store)
    expected = module.ReconciliationState(
        origin="external",
        physical_active=True,
        active_profile_id="shared_ev_profile_a",
        stop_outcome={"status": "pending"},
        observed_session_token="session-1",
    )

    persist = getattr(module, "persist_reconciliation_state", None)
    load = getattr(module, "load_reconciliation_state", None)
    assert persist is not None
    assert load is not None
    asyncio.run(persist(hass, Entry(), "garage", expected))

    assert store.saved == 1
    assert store._data["_shared_loadpoint_reconciliation_state"] == {
        "binding_id": "garage",
        "origin": "external",
        "physical_active": True,
        "active_profile_id": "shared_ev_profile_a",
        "stop_outcome": {"status": "pending"},
        "observed_session_token": "session-1",
    }
    assert load(hass, Entry(), "garage") == expected


def test_fresh_evac_charging_read_is_physically_active() -> None:
    class EvacState:
        charger_type = "evac"
        is_connected = True
        is_charging = True
        power_kw = 7.2

    async def read_state():
        return EvacState()

    reconcile = getattr(module, "reconcile_evac_session_from_reader", None)
    assert reconcile is not None

    state = asyncio.run(
        reconcile(
            object(),
            object(),
            "shared-garage-loadpoint",
            read_state=read_state,
            now=NOW,
            get_last_commands=lambda hass, entry: {},
        )
    )

    assert state.physical_active is True
    assert state.origin == "external"


def test_fresh_evac_idle_read_is_physically_inactive() -> None:
    class EvacState:
        charger_type = "evac"
        is_connected = True
        is_charging = False
        power_kw = None

    async def read_state():
        return EvacState()

    state = asyncio.run(
        module.reconcile_evac_session_from_reader(
            object(),
            object(),
            "shared-garage-loadpoint",
            read_state=read_state,
            now=NOW,
            get_last_commands=lambda hass, entry: {},
        )
    )

    assert state.physical_active is False
    assert state.origin == "unknown"


@pytest.mark.parametrize("read_fails", [False, True])
def test_failed_or_unknown_evac_read_is_indeterminate(read_fails: bool) -> None:
    async def read_state():
        if read_fails:
            raise RuntimeError("Modbus unavailable")
        return None

    state = asyncio.run(
        module.reconcile_evac_session_from_reader(
            object(),
            object(),
            "shared-garage-loadpoint",
            read_state=read_state,
            now=NOW,
            get_last_commands=lambda hass, entry: {},
        )
    )

    assert state.physical_active is None
    assert state.origin == "unknown"


@pytest.mark.parametrize(
    ("command", "expected_origin"),
    [
        (
            {"at": NOW.isoformat(), "source": "powersync", "success": True},
            "powersync",
        ),
        ({"at": NOW.isoformat(), "source": "external", "success": True}, "external"),
    ],
)
def test_fresh_evac_charging_uses_canonical_command_ledger_origin(
    command: dict[str, object],
    expected_origin: str,
) -> None:
    class EvacState:
        charger_type = "evac"
        is_connected = True
        is_charging = True
        power_kw = 7.2

    async def read_state():
        return EvacState()

    state = asyncio.run(
        module.reconcile_evac_session_from_reader(
            object(),
            object(),
            "shared-garage-loadpoint",
            read_state=read_state,
            now=NOW,
            get_last_commands=lambda hass, entry: {"shared-garage-loadpoint": command},
        )
    )

    assert state.physical_active is True
    assert state.origin == expected_origin


def test_fresh_positive_generic_power_without_powersync_command_is_external() -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=7.2,
        observed_at=NOW,
        now=NOW,
    )

    state = module.reconcile_shared_external_session(observation)

    assert state.physical_active is True
    assert state.origin == "external"


def test_fresh_positive_generic_power_with_powersync_command_is_powersync() -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=7.2,
        observed_at=NOW,
        now=NOW,
    )

    state = module.reconcile_shared_external_session(
        observation,
        powersync_command_observed=True,
    )

    assert state.physical_active is True
    assert state.origin == "powersync"


def test_mark_requested_stop_pending_waits_for_fresh_readback() -> None:
    state = module.ReconciliationState(origin="powersync", physical_active=True)

    mark_pending = getattr(module, "mark_stop_pending", None)
    assert mark_pending is not None
    mark_pending(state)

    assert state.stop_outcome == {"status": "pending"}

    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=7.2,
        observed_at=NOW,
        now=NOW,
    )
    reconciled = module.reconcile_shared_external_session(observation, previous=state)

    assert reconciled.stop_outcome == {"status": "pending"}
    assert reconciled.origin == "settling"


def test_fresh_inactive_readback_confirms_a_failed_stop_request() -> None:
    state = module.ReconciliationState(origin="powersync", physical_active=True)

    mark_failed = getattr(module, "mark_stop_failed", None)
    assert mark_failed is not None
    mark_failed(state)
    assert state.stop_outcome == {"status": "failed"}

    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=0.0,
        observed_at=NOW,
        now=NOW,
    )
    reconciled = module.reconcile_shared_external_session(observation, previous=state)

    assert reconciled.stop_outcome == {"status": "confirmed"}
    assert reconciled.physical_active is False


def test_stale_readback_makes_a_failed_stop_request_indeterminate() -> None:
    state = module.ReconciliationState(origin="powersync", physical_active=True)
    module.mark_stop_failed(state)

    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=7.2,
        observed_at=NOW - timedelta(seconds=91),
        now=NOW,
    )
    reconciled = module.reconcile_shared_external_session(observation, previous=state)

    assert reconciled.stop_outcome == {"status": "indeterminate"}
    assert reconciled.physical_active is None
    assert reconciled.origin == "unknown"


def test_fresh_inactive_readback_confirms_an_indeterminate_stop_request() -> None:
    state = module.ReconciliationState(
        origin="unknown",
        physical_active=None,
        stop_outcome={"status": "indeterminate"},
    )
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=0.0,
        observed_at=NOW,
        now=NOW,
    )

    reconciled = module.reconcile_shared_external_session(observation, previous=state)

    assert reconciled.stop_outcome == {"status": "confirmed"}
    assert reconciled.physical_active is False


@pytest.mark.parametrize(
    ("power_kw", "observed_at"),
    [
        (7.2, NOW - timedelta(seconds=91)),
        (None, NOW),
    ],
)
def test_stale_or_missing_power_makes_pending_stop_indeterminate(
    power_kw: float | None,
    observed_at: datetime,
) -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=power_kw,
        observed_at=observed_at,
        now=NOW,
    )
    previous = module.ReconciliationState(
        origin="powersync",
        physical_active=True,
        stop_outcome={"status": "pending"},
    )

    state = module.reconcile_shared_external_session(observation, previous=previous)

    assert state.physical_active is None
    assert state.origin == "unknown"
    assert state.stop_outcome == {"status": "indeterminate"}


def test_fresh_zero_power_confirms_pending_stop() -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=0.0,
        observed_at=NOW,
        now=NOW,
    )
    previous = module.ReconciliationState(
        origin="powersync",
        physical_active=True,
        stop_outcome={"status": "pending"},
    )

    state = module.reconcile_shared_external_session(observation, previous=previous)

    assert state.physical_active is False
    assert state.stop_outcome == {"status": "confirmed"}


def test_managed_handoff_stops_then_waits_for_fresh_idle_before_finalizing() -> None:
    handoff = getattr(module, "stop_and_confirm_shared_handoff", None)
    assert handoff is not None
    state = module.ReconciliationState(
        origin="powersync",
        physical_active=True,
        active_profile_id="shared_ev_profile_a",
    )
    observations = iter(
        [
            module.generic_power_observation(
                binding_id="garage", power_kw=7.2, observed_at=NOW, now=NOW
            ),
            module.generic_power_observation(
                binding_id="garage", power_kw=0.0, observed_at=NOW, now=NOW
            ),
        ]
    )
    events = []

    async def stop() -> bool:
        events.append("stop")
        return True

    async def observe():
        events.append("observe")
        return next(observations)

    async def persist(updated):
        events.append(("persist", updated.stop_outcome["status"]))

    async def sleep(_seconds):
        events.append("sleep")

    async def finalize():
        events.append("finalize")

    assert asyncio.run(
        handoff(
            state,
            active_profile_id="shared_ev_profile_a",
            stop=stop,
            observe=observe,
            persist=persist,
            finalize=finalize,
            max_polls=2,
            poll_seconds=0,
            sleep=sleep,
        )
    )
    assert events == [
        ("persist", "pending"),
        "stop",
        "observe",
        ("persist", "pending"),
        "sleep",
        "observe",
        ("persist", "confirmed"),
        "finalize",
    ]
    assert state.stop_outcome == {"status": "confirmed"}


def test_managed_handoff_never_finalizes_after_failed_stop_or_unknown_readback() -> None:
    handoff = getattr(module, "stop_and_confirm_shared_handoff", None)
    assert handoff is not None

    async def exercise(stop_result, observation):
        state = module.ReconciliationState(physical_active=True)
        finalized = []

        async def stop():
            return stop_result

        async def observe():
            return observation

        async def persist(_state):
            return None

        async def finalize():
            finalized.append(True)

        result = await handoff(
            state,
            active_profile_id="shared_ev_profile_a",
            stop=stop,
            observe=observe,
            persist=persist,
            finalize=finalize,
            max_polls=1,
            poll_seconds=0,
            sleep=lambda _seconds: None,
        )
        return result, state, finalized

    failed_stop = asyncio.run(exercise(False, None))
    unknown = asyncio.run(
        exercise(
            True,
            module.generic_power_observation(
                binding_id="garage", power_kw=None, observed_at=NOW, now=NOW
            ),
        )
    )
    timed_out = asyncio.run(
        exercise(
            True,
            module.generic_power_observation(
                binding_id="garage", power_kw=7.2, observed_at=NOW, now=NOW
            ),
        )
    )

    assert failed_stop[0] is False
    assert failed_stop[1].stop_outcome == {"status": "failed"}
    assert failed_stop[2] == []
    assert unknown[0] is False
    assert unknown[1].stop_outcome == {"status": "indeterminate"}
    assert unknown[2] == []
    assert timed_out[0] is False
    assert timed_out[1].stop_outcome == {"status": "timed_out"}
    assert timed_out[2] == []


def test_generic_hass_observation_uses_fresh_power_entity() -> None:
    class State:
        state = "7200"
        last_updated = NOW
        attributes = {"unit_of_measurement": "W"}

    class Hass:
        class states:
            @staticmethod
            def get(entity_id):
                return State() if entity_id == "sensor.charger_power" else None

    observe = getattr(module, "generic_observation_from_hass", None)
    assert observe is not None
    observation = observe(
        Hass(),
        binding_id="garage",
        params={"charger_power_entity": "sensor.charger_power"},
        now=NOW,
    )

    assert observation.evidence == "fresh_power"
    assert observation.power_kw == 7.2
    assert observation.charging is True


def test_fresh_generic_power_with_recent_successful_canonical_command_is_powersync() -> None:
    class State:
        state = "7200"
        last_updated = NOW
        attributes = {"unit_of_measurement": "W"}

    class Hass:
        class states:
            @staticmethod
            def get(entity_id):
                return State() if entity_id == "sensor.charger_power" else None

    class Entry:
        entry_id = "entry-1"

    reconcile = getattr(module, "reconcile_generic_session_from_hass", None)
    assert reconcile is not None
    state = reconcile(
        Hass(),
        Entry(),
        "shared-garage-loadpoint",
        {"charger_power_entity": "sensor.charger_power"},
        now=NOW,
        get_last_commands=lambda hass, entry: {
            "shared-garage-loadpoint": {
                "at": (NOW - timedelta(seconds=1)).isoformat(),
                "source": "powersync",
                "success": True,
            }
        },
    )

    assert state.physical_active is True
    assert state.origin == "powersync"


def test_fresh_generic_power_without_canonical_powersync_command_is_external() -> None:
    class State:
        state = "7.2"
        last_updated = NOW
        attributes = {"unit_of_measurement": "kW"}

    class Hass:
        class states:
            @staticmethod
            def get(entity_id):
                return State() if entity_id == "sensor.charger_power" else None

    class Entry:
        entry_id = "entry-1"

    state = module.reconcile_generic_session_from_hass(
        Hass(),
        Entry(),
        "shared-garage-loadpoint",
        {"charger_power_entity": "sensor.charger_power"},
        now=NOW,
        get_last_commands=lambda hass, entry: {
            "logical-profile-a": {
                "at": NOW.isoformat(),
                "source": "powersync",
                "success": True,
            }
        },
    )

    assert state.physical_active is True
    assert state.origin == "external"


def test_fresh_generic_power_with_stale_canonical_command_is_external() -> None:
    class State:
        state = "7.2"
        last_updated = NOW
        attributes = {"unit_of_measurement": "kW"}

    class Hass:
        class states:
            @staticmethod
            def get(entity_id):
                return State() if entity_id == "sensor.charger_power" else None

    class Entry:
        entry_id = "entry-1"

    state = module.reconcile_generic_session_from_hass(
        Hass(),
        Entry(),
        "shared-garage-loadpoint",
        {"charger_power_entity": "sensor.charger_power"},
        now=NOW,
        get_last_commands=lambda hass, entry: {
            "shared-garage-loadpoint": {
                "at": (NOW - timedelta(seconds=91)).isoformat(),
                "source": "powersync",
                "success": True,
            }
        },
    )

    assert state.physical_active is True
    assert state.origin == "external"


def test_stale_generic_power_remains_unknown_despite_recent_command() -> None:
    class State:
        state = "7.2"
        last_updated = NOW - timedelta(seconds=91)
        attributes = {"unit_of_measurement": "kW"}

    class Hass:
        class states:
            @staticmethod
            def get(entity_id):
                return State() if entity_id == "sensor.charger_power" else None

    class Entry:
        entry_id = "entry-1"

    state = module.reconcile_generic_session_from_hass(
        Hass(),
        Entry(),
        "shared-garage-loadpoint",
        {"charger_power_entity": "sensor.charger_power"},
        now=NOW,
        get_last_commands=lambda hass, entry: {
            "shared-garage-loadpoint": {
                "at": NOW.isoformat(),
                "source": "powersync",
                "success": True,
            }
        },
    )

    assert state.physical_active is None
    assert state.origin == "unknown"


def test_missing_generic_power_remains_unknown_despite_recent_command() -> None:
    class Hass:
        class states:
            @staticmethod
            def get(entity_id):
                return None

    class Entry:
        entry_id = "entry-1"

    state = module.reconcile_generic_session_from_hass(
        Hass(),
        Entry(),
        "shared-garage-loadpoint",
        {"charger_power_entity": "sensor.charger_power"},
        now=NOW,
        get_last_commands=lambda hass, entry: {
            "shared-garage-loadpoint": {
                "at": NOW.isoformat(),
                "source": "powersync",
                "success": True,
            }
        },
    )

    assert state.physical_active is None
    assert state.origin == "unknown"

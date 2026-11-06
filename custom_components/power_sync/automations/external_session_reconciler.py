"""Fresh physical observation and origin classification for one shared loadpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Awaitable, Callable, Mapping

try:
    from ..const import DOMAIN
except ImportError:  # Lightweight behavior tests load this module by path.
    DOMAIN = "power_sync"


GENERIC_ACTIVE_POWER_EPSILON_KW = 0.05
DEFAULT_FRESHNESS_SECONDS = 90
DEFAULT_COMMAND_FRESHNESS_SECONDS = 90
_RECONCILIATION_STATE_STORAGE_KEY = "_shared_loadpoint_reconciliation_state"


@dataclass(frozen=True)
class SharedLoadpointObservation:
    """One physical observation; absent freshness is never treated as proof."""

    binding_id: str
    connected: bool | None
    charging: bool | None
    power_kw: float | None
    observed_at: datetime | None
    evidence: str

    @property
    def fresh_power(self) -> bool:
        return self.evidence == "fresh_power" and self.power_kw is not None

    @property
    def fresh(self) -> bool:
        """Return whether this is a successful current physical read."""
        return self.fresh_power or self.evidence == "fresh_evac_state"


@dataclass
class ReconciliationState:
    """Persistable physical session state, separate from policy ownership."""

    origin: str = "unknown"
    physical_active: bool | None = None
    active_profile_id: str | None = None
    stop_outcome: dict[str, Any] | None = None
    observed_session_token: str | None = None
    temporary_external_lease_token: str | None = None
    observed_at: datetime | None = None
    evidence: str | None = None


def mark_stop_pending(state: ReconciliationState) -> ReconciliationState:
    """Record that a stop was requested and needs fresh physical readback."""
    state.stop_outcome = {"status": "pending"}
    return state


def mark_stop_failed(state: ReconciliationState) -> ReconciliationState:
    """Record that issuing the requested stop failed before readback."""
    state.stop_outcome = {"status": "failed"}
    return state


async def stop_and_confirm_shared_handoff(
    state: ReconciliationState,
    *,
    active_profile_id: str,
    stop: Callable[[], Awaitable[bool]],
    observe: Callable[[], Awaitable[SharedLoadpointObservation | None]],
    persist: Callable[[ReconciliationState], Awaitable[None]],
    finalize: Callable[[], Awaitable[None]],
    max_polls: int = 3,
    poll_seconds: float = 1.0,
    sleep: Callable[[float], Awaitable[None]],
) -> bool:
    """Stop one managed physical session and finalize only after fresh idle proof.

    The callbacks deliberately keep this policy-free: callers retain their
    physical stop path and old runtime/session ownership until the reconciler
    has seen a fresh inactive observation.  A failed, unknown, or timed-out
    readback never invokes ``finalize``.
    """
    mark_stop_pending(state)
    state.active_profile_id = active_profile_id
    await persist(state)
    try:
        stopped = await stop()
    except Exception:
        stopped = False
    if not stopped:
        mark_stop_failed(state)
        await persist(state)
        return False

    try:
        attempts = max(1, int(max_polls))
    except (TypeError, ValueError):
        attempts = 3
    try:
        delay = max(0.0, float(poll_seconds))
    except (TypeError, ValueError):
        delay = 1.0

    for attempt in range(attempts):
        try:
            observation = await observe()
        except Exception:
            observation = None
        if observation is None:
            observation = SharedLoadpointObservation(
                binding_id="",
                connected=None,
                charging=None,
                power_kw=None,
                observed_at=None,
                evidence="failed_or_unknown_read",
            )
        reconcile_shared_external_session(
            observation,
            previous=state,
            active_profile_id=active_profile_id,
        )
        await persist(state)
        if state.stop_outcome == {"status": "confirmed"}:
            await finalize()
            return True
        if state.stop_outcome == {"status": "indeterminate"}:
            return False
        if attempt + 1 < attempts:
            await sleep(delay)

    state.stop_outcome = {"status": "timed_out"}
    await persist(state)
    return False


def _automation_store(hass: Any, config_entry: Any) -> Any | None:
    """Return this entry's storage without creating runtime or policy state."""
    entry = getattr(hass, "data", {}).get(DOMAIN, {}).get(config_entry.entry_id, {})
    return entry.get("automation_store") if isinstance(entry, Mapping) else None


async def persist_reconciliation_state(
    hass: Any,
    config_entry: Any,
    binding_id: str,
    state: ReconciliationState,
) -> None:
    """Persist one private physical-session record for this entry's binding."""
    store = _automation_store(hass, config_entry)
    data = getattr(store, "_data", None)
    if not isinstance(data, dict):
        return
    data[_RECONCILIATION_STATE_STORAGE_KEY] = {
        "binding_id": binding_id,
        "origin": state.origin,
        "physical_active": state.physical_active,
        "active_profile_id": state.active_profile_id,
        "stop_outcome": dict(state.stop_outcome) if state.stop_outcome is not None else None,
        "observed_session_token": state.observed_session_token,
    }
    if state.temporary_external_lease_token is not None:
        data[_RECONCILIATION_STATE_STORAGE_KEY]["temporary_external_lease_token"] = (
            state.temporary_external_lease_token
        )
    if state.observed_at is not None:
        data[_RECONCILIATION_STATE_STORAGE_KEY]["observed_at"] = state.observed_at.isoformat()
    save = getattr(store, "async_save", None)
    if save is None:
        return
    result = save()
    if hasattr(result, "__await__"):
        await result


def load_reconciliation_state(
    hass: Any,
    config_entry: Any,
    binding_id: str,
) -> ReconciliationState:
    """Load only the record for this binding; unrelated or malformed data is unknown."""
    store = _automation_store(hass, config_entry)
    data = getattr(store, "_data", None)
    record = data.get(_RECONCILIATION_STATE_STORAGE_KEY) if isinstance(data, Mapping) else None
    if not isinstance(record, Mapping) or record.get("binding_id") != binding_id:
        return ReconciliationState()
    origin = record.get("origin")
    if not isinstance(origin, str):
        origin = "unknown"
    observed_at = record.get("observed_at")
    if isinstance(observed_at, str):
        try:
            observed_at = _as_utc(datetime.fromisoformat(observed_at))
        except ValueError:
            observed_at = None
    elif not isinstance(observed_at, datetime):
        observed_at = None
    return ReconciliationState(
        origin=origin,
        physical_active=(
            record.get("physical_active")
            if isinstance(record.get("physical_active"), bool)
            else None
        ),
        active_profile_id=(
            record.get("active_profile_id")
            if isinstance(record.get("active_profile_id"), str)
            else None
        ),
        stop_outcome=(
            dict(record["stop_outcome"])
            if isinstance(record.get("stop_outcome"), Mapping)
            else None
        ),
        observed_session_token=(
            record.get("observed_session_token")
            if isinstance(record.get("observed_session_token"), str)
            else None
        ),
        temporary_external_lease_token=(
            record.get("temporary_external_lease_token")
            if isinstance(record.get("temporary_external_lease_token"), str)
            else None
        ),
        observed_at=observed_at,
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _stop_observation(binding_id: str, charging: bool | None, power_kw: float | None,
                      observed_at: datetime | None, evidence: str) -> SharedLoadpointObservation:
    return SharedLoadpointObservation(binding_id, None, charging, power_kw, observed_at, evidence)


def _valid_stop_time(observed: Any, stop_at: Any, now: Any) -> bool:
    """Require real HA/read timestamps, strictly after the stop and at most 90s old."""
    if not all(isinstance(value, datetime) and value.utcoffset() is not None
               for value in (observed, stop_at, now)):
        return False
    return stop_at < observed <= now and (now - observed).total_seconds() <= DEFAULT_FRESHNESS_SECONDS


def generic_stop_observation_from_hass(
    hass: Any, *, binding_id: str, params: Mapping[str, Any], stop_at: datetime,
    now: datetime | None = None, charging: bool | None = None,
) -> SharedLoadpointObservation:
    """Classify post-stop HA power; low draw is not contactor/disabled proof.

    The caller supplies the stop timestamp and optionally independent charging
    evidence. No update_entity service or device command is issued.
    """
    unknown = _stop_observation(binding_id, None, None, None, "unknown_stop_observation")
    current = now if now is not None else datetime.now(timezone.utc)
    entity_id = params.get("charger_power_entity")
    state = hass.states.get(entity_id) if isinstance(entity_id, str) and entity_id else None
    if state is None:
        return unknown
    # Attribute-only updates do not establish a fresh power report.
    observed = getattr(state, "last_reported", None)
    if not _valid_stop_time(observed, stop_at, current):
        return unknown
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, Mapping):
        return unknown
    unit = attributes.get("unit_of_measurement")
    if not isinstance(unit, str) or unit.strip().lower() not in ("w", "kw"):
        return unknown
    raw = getattr(state, "state", None)
    if isinstance(raw, bool):
        return unknown
    try:
        power = float(raw)
    except (TypeError, ValueError, OverflowError):
        return unknown
    if not math.isfinite(power) or power < 0:
        return unknown
    if unit.strip().lower() == "w":
        power /= 1000
    active = power > GENERIC_ACTIVE_POWER_EPSILON_KW
    if charging is not None and (not isinstance(charging, bool) or charging != active):
        return unknown
    return _stop_observation(binding_id, active, power, observed,
                             "observed_active_power" if active else "observed_low_power")


async def evac_stop_observation_from_reader(
    *, binding_id: str, stop_at: datetime,
    read_input_registers: Callable[[int, int], Awaitable[Any]],
    clock: Callable[[], datetime] | None = None,
) -> SharedLoadpointObservation:
    """Read raw EVAC input registers after a stop, without issuing any writes.

    The supplied reader must be the charger controller's direct input-register
    reader, not a cached normalized state. A successful read is not proof of
    when the charger itself measured power or that its contactor is open.
    """
    unknown = _stop_observation(binding_id, None, None, None, "unknown_stop_observation")
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = clock()
    if not _valid_stop_time(started, stop_at, started):
        return unknown
    try:
        regs = await read_input_registers(32000, 12)
        finished = clock()
    except Exception:
        return unknown
    if not _valid_stop_time(started, stop_at, finished):
        return unknown
    if not isinstance(regs, (list, tuple)) or len(regs) != 12 or any(
        type(reg) is not int or not 0 <= reg <= 0xffff for reg in regs
    ):
        return unknown
    raw_state = regs[0]
    if raw_state not in (1, 2, 3, 4, 5):
        return unknown
    raw_power = (regs[3] << 16) | regs[4]
    if raw_power & 0x80000000:
        return unknown
    power = raw_power / 1000
    active = raw_state in (4, 5) or power > GENERIC_ACTIVE_POWER_EPSILON_KW
    return _stop_observation(binding_id, active, power, finished,
                             "observed_evac_active" if active else "observed_evac_low_power")


def generic_power_observation(
    *,
    binding_id: str,
    power_kw: float | None,
    observed_at: datetime | None,
    charging: bool | None = None,
    connected: bool | None = None,
    now: datetime | None = None,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
) -> SharedLoadpointObservation:
    """Return a Generic-Charger observation without inventing stale power state."""
    current = _as_utc(now) or datetime.now(timezone.utc)
    observed = _as_utc(observed_at)
    fresh = (
        observed is not None
        and 0 <= (current - observed).total_seconds() <= freshness_seconds
        and power_kw is not None
    )
    if not fresh:
        return SharedLoadpointObservation(
            binding_id=binding_id,
            connected=connected,
            charging=None,
            power_kw=None,
            observed_at=observed,
            evidence="stale_or_missing_power",
        )
    assert power_kw is not None
    numeric_power = max(0.0, float(power_kw))
    physically_charging = numeric_power > GENERIC_ACTIVE_POWER_EPSILON_KW
    if charging is not None:
        physically_charging = physically_charging or charging
    return SharedLoadpointObservation(
        binding_id=binding_id,
        connected=connected,
        charging=physically_charging,
        power_kw=numeric_power,
        observed_at=observed,
        evidence="fresh_power",
    )


def generic_observation_from_hass(
    hass: Any,
    *,
    binding_id: str,
    params: dict[str, Any],
    now: datetime | None = None,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
) -> SharedLoadpointObservation:
    """Read only Generic-Charger power telemetry into the reconciler contract."""
    entity_id = str(params.get("charger_power_entity") or "").strip()
    state = hass.states.get(entity_id) if entity_id else None
    if state is None:
        return generic_power_observation(
            binding_id=binding_id,
            power_kw=None,
            observed_at=None,
            now=now,
            freshness_seconds=freshness_seconds,
        )
    try:
        power = float(getattr(state, "state", ""))
    except (TypeError, ValueError):
        power = None
    unit = str(getattr(state, "attributes", {}).get("unit_of_measurement") or "").lower()
    if power is not None and unit in ("w", "watt", "watts"):
        power /= 1000
    observed_at = (
        getattr(state, "last_reported", None)
        or getattr(state, "last_updated", None)
        or getattr(state, "last_changed", None)
    )
    return generic_power_observation(
        binding_id=binding_id,
        power_kw=power,
        observed_at=observed_at,
        now=now,
        freshness_seconds=freshness_seconds,
    )


def evac_observation_from_state(
    *,
    binding_id: str,
    state: Any | None,
    observed_at: datetime | None = None,
) -> SharedLoadpointObservation:
    """Map one just-read normalized EVAC state into the reconciler contract."""
    if state is None or str(getattr(state, "charger_type", "")).lower() != "evac":
        return SharedLoadpointObservation(
            binding_id=binding_id,
            connected=None,
            charging=None,
            power_kw=None,
            observed_at=None,
            evidence="failed_or_unknown_evac_read",
        )
    try:
        power_kw = getattr(state, "power_kw", None)
        numeric_power = max(0.0, float(power_kw)) if power_kw is not None else None
    except (TypeError, ValueError):
        numeric_power = None
    return SharedLoadpointObservation(
        binding_id=binding_id,
        connected=bool(getattr(state, "is_connected", False)),
        charging=bool(getattr(state, "is_charging", False)),
        power_kw=numeric_power,
        observed_at=_as_utc(observed_at),
        evidence="fresh_evac_state",
    )


def _recent_successful_powersync_command(
    commands: Mapping[str, Mapping[str, Any]],
    *,
    loadpoint_id: str,
    now: datetime,
    freshness_seconds: int,
) -> bool:
    """Return whether the canonical loadpoint has recent successful command evidence."""
    command = commands.get(loadpoint_id)
    if not isinstance(command, Mapping):
        return False
    command_at = command.get("at")
    if isinstance(command_at, str):
        try:
            command_at = datetime.fromisoformat(command_at)
        except ValueError:
            return False
    timestamp = _as_utc(command_at) if isinstance(command_at, datetime) else None
    if timestamp is None:
        return False
    current = _as_utc(now)
    assert current is not None
    age_seconds = (current - timestamp).total_seconds()
    return bool(
        command.get("source") == "powersync"
        and command.get("success")
        and 0 <= age_seconds <= freshness_seconds
    )


def reconcile_generic_session_from_hass(
    hass: Any,
    config_entry: Any,
    loadpoint_id: str,
    params: dict[str, Any],
    *,
    previous: ReconciliationState | None = None,
    active_profile_id: str | None = None,
    now: datetime | None = None,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    command_freshness_seconds: int = DEFAULT_COMMAND_FRESHNESS_SECONDS,
    get_last_commands: Callable[[Any, Any], Mapping[str, Mapping[str, Any]]] | None = None,
) -> ReconciliationState:
    """Reconcile Generic telemetry with the canonical PowerSync command ledger."""
    current = _as_utc(now) or datetime.now(timezone.utc)
    observation = generic_observation_from_hass(
        hass,
        binding_id=loadpoint_id,
        params=params,
        now=current,
        freshness_seconds=freshness_seconds,
    )
    if get_last_commands is None:
        from .ev_ownership import get_ev_last_commands

        get_last_commands = get_ev_last_commands
    powersync_command_observed = _recent_successful_powersync_command(
        get_last_commands(hass, config_entry),
        loadpoint_id=loadpoint_id,
        now=current,
        freshness_seconds=command_freshness_seconds,
    )
    return reconcile_shared_external_session(
        observation,
        previous=previous,
        powersync_command_observed=powersync_command_observed,
        active_profile_id=active_profile_id,
    )


async def reconcile_selected_shared_loadpoint_cycle(
    hass: Any,
    config_entry: Any,
    *,
    now: datetime | None = None,
    read_evac_state: Callable[[], Awaitable[Any | None]] | None = None,
) -> dict[str, Any] | None:
    """Reconcile the selected shared physical loadpoint and publish cycle context.

    This is observation-only: it neither changes ownership nor invokes charging
    policy.  A complete binding and one currently selected logical profile are
    required before any backend telemetry is read.
    """
    entry_data = getattr(hass, "data", {}).get(DOMAIN, {}).get(config_entry.entry_id)

    def clear_cycle_context() -> None:
        if isinstance(entry_data, dict):
            entry_data.pop("_shared_loadpoint_cycle_context", None)

    clear_cycle_context()

    from .shared_loadpoint import (
        canonical_shared_loadpoint_id,
        binding_for_entry,
        resolve_active_shared_profile,
    )

    if binding_for_entry(config_entry) is None:
        clear_cycle_context()
        return None
    active_profile_id = resolve_active_shared_profile(hass, config_entry)
    if active_profile_id is None:
        clear_cycle_context()
        return None
    loadpoint_id = canonical_shared_loadpoint_id(config_entry, active_profile_id)
    if loadpoint_id is None:
        clear_cycle_context()
        return None

    options = {
        **getattr(config_entry, "data", {}),
        **getattr(config_entry, "options", {}),
    }
    store = _automation_store(hass, config_entry)
    stored_configs = getattr(store, "_data", {}).get("vehicle_charging_configs", [])
    selected_params = next(
        (
            dict(candidate)
            for candidate in stored_configs
            if isinstance(candidate, Mapping)
            and str(candidate.get("vehicle_id") or "") == active_profile_id
        ),
        {},
    )
    if not selected_params.get("charger_power_entity"):
        selected_params["charger_power_entity"] = options.get(
            "generic_charger_power_entity"
        )
    evac_idle_power_confirmed = False
    if loadpoint_id == "generic_ev":
        state = reconcile_generic_session_from_hass(
            hass,
            config_entry,
            loadpoint_id,
            selected_params,
            previous=load_reconciliation_state(hass, config_entry, loadpoint_id),
            active_profile_id=active_profile_id,
            now=now,
        )
    elif loadpoint_id == "sigenergy_charger":
        if read_evac_state is None:
            state = ReconciliationState()
        else:
            async def read_evac_for_stop_observation() -> Any | None:
                nonlocal evac_idle_power_confirmed
                raw = await read_evac_state()
                if (
                    str(getattr(raw, "charger_type", "")).lower() == "evac"
                    and getattr(raw, "is_charging", None) is False
                ):
                    try:
                        power_kw = float(getattr(raw, "power_kw"))
                        evac_idle_power_confirmed = 0 <= power_kw <= GENERIC_ACTIVE_POWER_EPSILON_KW
                    except (TypeError, ValueError):
                        pass
                return raw

            state = await reconcile_evac_session_from_reader(
                hass,
                config_entry,
                loadpoint_id,
                read_state=read_evac_for_stop_observation,
                previous=load_reconciliation_state(hass, config_entry, loadpoint_id),
                active_profile_id=active_profile_id,
                now=now,
            )
    else:
        return None

    await persist_reconciliation_state(hass, config_entry, loadpoint_id, state)
    # A fresh physical idle read may settle the latest recorded PowerSync stop
    # warning, even if selection has since moved from A to B. Keep this strictly
    # observational: do not call confirm_powersync_ev_stop (it releases leases)
    # or infer a stop from stale/unknown/charging telemetry.
    observed_time = _as_utc(state.observed_at) if isinstance(state.observed_at, datetime) else None
    # Pending shared stops are settled by the identity-bound lifecycle, not
    # by ordinary reconciliation: even valid idle telemetry must not dismiss
    # a warning belonging to a replaced owner or session.
    fences = entry_data.get("_shared_stop_fences", {}) if isinstance(entry_data, dict) else {}
    pending = fences.get(loadpoint_id) if isinstance(fences, Mapping) else None
    records = getattr(store, "_data", {}).get("_shared_pending_stops", {})
    stored = records.get(loadpoint_id) if isinstance(records, Mapping) else None
    no_pending_stop = pending is None and stored is None
    if (
        no_pending_stop
        and state.physical_active is False
        and state.evidence in ("fresh_power", "fresh_evac_state")
        and (loadpoint_id == "generic_ev" or evac_idle_power_confirmed)
        and observed_time is not None
        and 0 <= (datetime.now(timezone.utc) - observed_time).total_seconds() <= DEFAULT_FRESHNESS_SECONDS
    ):
        from .ev_ownership import get_ev_last_commands, _schedule_runtime_save
        from ..action_events import observe_ev_stop

        command = get_ev_last_commands(hass, config_entry).get(loadpoint_id)
        if isinstance(command, dict):
            was_settled = command.get("settled_at")
            observe_ev_stop(hass, config_entry, loadpoint_id, command,
                            observed_time, charging=False)
            if not was_settled and command.get("settled_at"):
                _schedule_runtime_save(hass, config_entry)
    context = {
        "binding_id": loadpoint_id,
        "active_profile_id": active_profile_id,
        "origin": state.origin,
        "physical_active": state.physical_active,
        "observed_at": state.observed_at,
        "evidence": state.evidence,
    }
    if isinstance(entry_data, dict):
        entry_data["_shared_loadpoint_cycle_context"] = context
    return context


async def reconcile_evac_session_from_reader(
    hass: Any,
    config_entry: Any,
    loadpoint_id: str,
    *,
    read_state: Callable[[], Awaitable[Any | None]],
    previous: ReconciliationState | None = None,
    active_profile_id: str | None = None,
    now: datetime | None = None,
    command_freshness_seconds: int = DEFAULT_COMMAND_FRESHNESS_SECONDS,
    get_last_commands: Callable[[Any, Any], Mapping[str, Mapping[str, Any]]] | None = None,
) -> ReconciliationState:
    """Reconcile a freshly read Sigenergy EVAC state with the command ledger."""
    current = _as_utc(now) or datetime.now(timezone.utc)
    try:
        observation = evac_observation_from_state(
            binding_id=loadpoint_id,
            state=await read_state(),
            observed_at=current,
        )
    except Exception:
        observation = evac_observation_from_state(binding_id=loadpoint_id, state=None)
    if get_last_commands is None:
        from .ev_ownership import get_ev_last_commands

        get_last_commands = get_ev_last_commands
    powersync_command_observed = _recent_successful_powersync_command(
        get_last_commands(hass, config_entry),
        loadpoint_id=loadpoint_id,
        now=current,
        freshness_seconds=command_freshness_seconds,
    )
    return reconcile_shared_external_session(
        observation,
        previous=previous,
        powersync_command_observed=powersync_command_observed,
        active_profile_id=active_profile_id,
    )


def reconcile_shared_external_session(
    observation: SharedLoadpointObservation,
    *,
    previous: ReconciliationState | None = None,
    powersync_command_observed: bool = False,
    active_profile_id: str | None = None,
) -> ReconciliationState:
    """Classify one observed physical state without deciding a charging policy."""
    state = previous or ReconciliationState()
    previous_observed_at = state.observed_at
    state.observed_at = observation.observed_at
    state.evidence = observation.evidence
    if not observation.fresh:
        state.origin = "unknown"
        state.physical_active = None
        if state.stop_outcome and state.stop_outcome.get("status") in {"pending", "failed"}:
            state.stop_outcome = {"status": "indeterminate"}
        return state

    state.physical_active = bool(observation.charging)
    state.active_profile_id = active_profile_id
    if not state.physical_active:
        if state.stop_outcome and state.stop_outcome.get("status") in {
            "pending",
            "failed",
            "indeterminate",
        }:
            state.stop_outcome = {"status": "confirmed"}
        state.origin = "unknown"
        return state

    if state.stop_outcome and state.stop_outcome.get("status") == "pending":
        state.origin = "settling"
        return state
    if (
        state.stop_outcome == {"status": "confirmed"}
        and not powersync_command_observed
        and observation.observed_at is not None
        and previous_observed_at is not None
        and observation.observed_at > previous_observed_at
    ):
        # A confirmed stop fences its observed session only. A later fresh
        # external observation is a new session; stale/unknown data returned
        # above can never re-arm it.
        state.stop_outcome = None
        state.observed_session_token = observation.observed_at.isoformat()
    elif state.observed_session_token is None and observation.observed_at is not None:
        state.observed_session_token = observation.observed_at.isoformat()
    state.origin = "powersync" if powersync_command_observed else "external"
    return state


async def resolve_end_of_cycle_external_shared_session(
    *,
    binding_id: str | None,
    active_profile_id: str | None,
    selected_params: Mapping[str, Any] | None,
    state: ReconciliationState,
    cycle_context: Mapping[str, Any] | None,
    now: datetime | None,
    external_control_policy: str,
    cycle_ledger: Mapping[str, Any] | None,
    get_lease: Callable[[], Mapping[str, Any] | None] | None,
    ensure_external_ownership: Callable[[str], Awaitable[None]],
    stop_and_confirm: Callable[..., Awaitable[bool]],
    release_temporary_external_ownership: Callable[[str], Awaitable[None]] | None = None,
    adopt_solar_session: Callable[..., Awaitable[bool]] | None = None,
    adopt_scheduled_session: Callable[..., Awaitable[bool]] | None = None,
    adopt_smart_schedule_session: Callable[..., Awaitable[bool]] | None = None,
    adopt_price_level_session: Callable[..., Awaitable[bool]] | None = None,
) -> bool:
    """Resolve one proven external selected shared session after a cycle.

    Physical I/O and ownership mechanics are injected so this policy boundary
    stays independent from action dispatch and runtime/session state.
    """
    current = _as_utc(now) or datetime.now(timezone.utc)
    observed_at = (
        _as_utc(cycle_context.get("observed_at"))
        if isinstance(cycle_context, Mapping)
        and isinstance(cycle_context.get("observed_at"), datetime)
        else None
    )
    expected_evidence = (
        "fresh_power" if binding_id == "generic_ev" else "fresh_evac_state"
    )
    context_is_current_fresh_external_session = (
        isinstance(cycle_context, Mapping)
        and cycle_context.get("binding_id") == binding_id
        and cycle_context.get("active_profile_id") == active_profile_id
        and cycle_context.get("origin") == "external"
        and cycle_context.get("physical_active") is True
        and cycle_context.get("evidence") == expected_evidence
        and observed_at is not None
        and 0 <= (current - observed_at).total_seconds() <= DEFAULT_FRESHNESS_SECONDS
    )
    context_is_current_fresh_idle = (
        isinstance(cycle_context, Mapping)
        and cycle_context.get("binding_id") == binding_id
        and cycle_context.get("active_profile_id") == active_profile_id
        and cycle_context.get("physical_active") is False
        and cycle_context.get("evidence") == expected_evidence
        and observed_at is not None
        and 0 <= (current - observed_at).total_seconds() <= DEFAULT_FRESHNESS_SECONDS
    )
    if (
        binding_id not in {"generic_ev", "sigenergy_charger"}
        or not active_profile_id
        or not isinstance(selected_params, Mapping)
        or not (
            context_is_current_fresh_external_session
            or context_is_current_fresh_idle
        )
        or get_lease is None
    ):
        return False

    temporary_lease_token = state.temporary_external_lease_token
    lease = get_lease()
    # A current physical read does not prove that this selected profile still
    # owns an existing external lease.  Do not retag, stop, or release a lease
    # that a newer selector/profile transition attributed elsewhere.
    if (
        isinstance(lease, Mapping)
        and lease.get("active_profile_id") is not None
        and lease.get("active_profile_id") != active_profile_id
    ):
        return False
    if (
        state.stop_outcome == {"status": "confirmed"}
        and temporary_lease_token is not None
        and context_is_current_fresh_idle
        and isinstance(lease, Mapping)
        and lease.get("owner") == "external"
        and lease.get("resolver_stop_lease_token") == temporary_lease_token
        and release_temporary_external_ownership is not None
    ):
        await release_temporary_external_ownership(temporary_lease_token)
        state.temporary_external_lease_token = None
        return False
    if (
        not context_is_current_fresh_external_session
        or state.origin != "external"
        or state.stop_outcome is not None
    ):
        return False

    lease = get_lease()
    if external_control_policy == "yield":
        if lease is None or lease.get("owner") == "external":
            await ensure_external_ownership(active_profile_id)
        return False

    records = cycle_ledger.get(binding_id, {}) if isinstance(cycle_ledger, Mapping) else {}
    selected_record = (
        records.get(active_profile_id)
        if isinstance(records, Mapping)
        else None
    )
    selected_solar_admission = (
        isinstance(selected_record, Mapping)
        and selected_record.get("allowed") is True
        and selected_record.get("responsible_mode") == "solar_surplus"
    )
    selected_scheduled_admission = (
        isinstance(selected_record, Mapping)
        and selected_record.get("allowed") is True
        and selected_record.get("responsible_mode") == "scheduled"
    )
    if selected_solar_admission:
        # An allowed Solar decision owns this cycle even if the runtime adapter
        # declines (or fails): never turn a failed adoption into an immediate
        # physical stop.  A PowerSync lease is a conflict and remains untouched.
        if (
            adopt_solar_session is not None
            and (lease is None or lease.get("owner") != "powersync")
        ):
            try:
                await adopt_solar_session(
                    binding_id=binding_id,
                    active_profile_id=active_profile_id,
                    selected_params=dict(selected_params),
                    observed_at=observed_at,
                )
            except Exception:
                pass
        return False
    if selected_scheduled_admission:
        # An allowed Scheduled decision owns this cycle even if its runtime
        # adapter declines: do not convert an adoption failure into a stop.
        if (
            adopt_scheduled_session is not None
            and (lease is None or lease.get("owner") != "powersync")
        ):
            try:
                await adopt_scheduled_session(
                    binding_id=binding_id,
                    active_profile_id=active_profile_id,
                    selected_params=dict(selected_params),
                    observed_at=observed_at,
                )
            except Exception:
                pass
        return False
    selected_smart_schedule_admission = (
        isinstance(selected_record, Mapping)
        and selected_record.get("allowed") is True
        and selected_record.get("responsible_mode") == "smart_schedule"
    )
    if selected_smart_schedule_admission:
        # Smart Schedule owns this allowed cycle. An adapter decline must not
        # turn external charging into a same-cycle physical stop.
        if (
            adopt_smart_schedule_session is not None
            and (lease is None or lease.get("owner") != "powersync")
        ):
            try:
                await adopt_smart_schedule_session(
                    binding_id=binding_id,
                    active_profile_id=active_profile_id,
                    selected_params=dict(selected_params),
                    observed_at=observed_at,
                )
            except Exception:
                pass
        return False
    selected_price_level_admission = (
        isinstance(selected_record, Mapping)
        and selected_record.get("allowed") is True
        and selected_record.get("responsible_mode") == "price_level"
    )
    if selected_price_level_admission:
        # Price-Level owns this allowed cycle. An adapter decline must not turn
        # external charging into a same-cycle physical stop.
        if (
            adopt_price_level_session is not None
            and (lease is None or lease.get("owner") != "powersync")
        ):
            try:
                await adopt_price_level_session(
                    binding_id=binding_id,
                    active_profile_id=active_profile_id,
                    selected_params=dict(selected_params),
                    observed_at=observed_at,
                )
            except Exception:
                pass
        return False
    if isinstance(records, Mapping) and any(
        isinstance(record, Mapping) and record.get("allowed") is True
        for record in records.values()
    ):
        return False

    # The private guarded stop accepts only the external owner.  Fresh physical
    # observation never displaces a PowerSync lease: when unowned, create the
    # temporary external lease through the ownership API, then read it back.
    created_temporary_lease = lease is None
    if created_temporary_lease:
        await ensure_external_ownership(active_profile_id)
        lease = get_lease()
    if not isinstance(lease, Mapping) or lease.get("owner") != "external":
        return False
    if created_temporary_lease and isinstance(lease, dict):
        lease_token = state.observed_session_token or (
            observed_at.isoformat() if observed_at is not None else None
        )
        if lease_token is None:
            return False
        state.observed_session_token = lease_token
        lease["resolver_stop_lease_token"] = lease_token
        state.temporary_external_lease_token = lease_token

    return await stop_and_confirm(
        binding_id=binding_id,
        active_profile_id=active_profile_id,
        selected_params=dict(selected_params),
        state=state,
    )

"""Fresh physical observation and origin classification for one shared loadpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping

try:
    from ..const import DOMAIN
except ImportError:  # Lightweight behavior tests load this module by path.
    DOMAIN = "powersync_nir"


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
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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
        observed_at=None,
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
    if not observation.fresh:
        state.origin = "unknown"
        state.physical_active = None
        if state.stop_outcome and state.stop_outcome.get("status") == "pending":
            state.stop_outcome = {"status": "indeterminate"}
        return state

    state.physical_active = bool(observation.charging)
    state.active_profile_id = active_profile_id
    if not state.physical_active:
        if state.stop_outcome and state.stop_outcome.get("status") == "pending":
            state.stop_outcome = {"status": "confirmed"}
        state.origin = "unknown"
        return state

    if state.stop_outcome and state.stop_outcome.get("status") == "pending":
        state.origin = "settling"
        return state
    state.origin = "powersync" if powersync_command_observed else "external"
    return state

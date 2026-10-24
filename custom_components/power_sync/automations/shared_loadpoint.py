"""Logical-profile binding for one physical Generic Charger or Sigenergy EVAC."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping

from ..const import (
    CONF_GENERIC_CHARGER_AMPS_ENTITY,
    CONF_GENERIC_CHARGER_ENABLED,
    CONF_GENERIC_CHARGER_POWER_ENTITY,
    CONF_GENERIC_CHARGER_STATUS_ENTITY,
    CONF_GENERIC_CHARGER_SWITCH_ENTITY,
    CONF_SHARED_LOADPOINT_CONNECTED_VEHICLE_ENTITY,
    CONF_SHARED_LOADPOINT_PROFILE_A_NAME,
    CONF_SHARED_LOADPOINT_PROFILE_A_SOC_ENTITY,
    CONF_SHARED_LOADPOINT_PROFILE_A_STATE,
    CONF_SHARED_LOADPOINT_PROFILE_B_NAME,
    CONF_SHARED_LOADPOINT_PROFILE_B_SOC_ENTITY,
    CONF_SHARED_LOADPOINT_PROFILE_B_STATE,
    CONF_SIGENERGY_CHARGER_ENABLED,
    CONF_SIGENERGY_CHARGER_HOST,
    CONF_SIGENERGY_CHARGER_PORT,
    CONF_SIGENERGY_CHARGER_SLAVE_ID,
    CONF_SIGENERGY_CHARGER_CHARGE_POWER_LIMIT_ENTITY,
    CONF_SIGENERGY_CHARGER_DISCHARGE_POWER_LIMIT_ENTITY,
    CONF_SIGENERGY_CHARGER_TYPE,
    CONF_SIGENERGY_MODBUS_HOST,
    DEFAULT_SIGENERGY_CHARGER_PORT,
    DEFAULT_SIGENERGY_CHARGER_SLAVE_ID,
    SIGENERGY_CHARGER_EVAC,
)

PROFILE_A_ID = "shared_ev_profile_a"
PROFILE_B_ID = "shared_ev_profile_b"


def _normalise_state(value: Any) -> str:
    """Normalise an HA state used as a configured profile selector value."""
    return str(value or "").strip().casefold()


@dataclass(frozen=True)
class SharedLoadpointBinding:
    """The explicit mapping from one HA state entity to two logical profiles."""

    connected_vehicle_entity: str
    profile_a_name: str
    profile_a_state: str
    profile_a_soc_entity: str
    profile_b_name: str
    profile_b_state: str
    profile_b_soc_entity: str

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> "SharedLoadpointBinding | None":
        binding = cls(
            connected_vehicle_entity=str(
                options.get(CONF_SHARED_LOADPOINT_CONNECTED_VEHICLE_ENTITY) or ""
            ).strip(),
            profile_a_name=str(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_A_NAME) or ""
            ).strip(),
            profile_a_state=_normalise_state(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_A_STATE)
            ),
            profile_a_soc_entity=str(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_A_SOC_ENTITY) or ""
            ).strip(),
            profile_b_name=str(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_B_NAME) or ""
            ).strip(),
            profile_b_state=_normalise_state(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_B_STATE)
            ),
            profile_b_soc_entity=str(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_B_SOC_ENTITY) or ""
            ).strip(),
        )
        if (
            not binding.connected_vehicle_entity
            or not binding.profile_a_name
            or not binding.profile_b_name
            or not binding.profile_a_state
            or not binding.profile_b_state
            or binding.profile_a_name.casefold() == binding.profile_b_name.casefold()
            or binding.profile_a_state == binding.profile_b_state
        ):
            return None
        return binding

    def resolve_state(self, state: Any) -> str | None:
        """Return the selected profile or None for unavailable/unknown/unmapped state."""
        value = _normalise_state(state)
        if value == self.profile_a_state:
            return PROFILE_A_ID
        if value == self.profile_b_state:
            return PROFILE_B_ID
        return None

    def profile_name(self, profile_id: str) -> str | None:
        if profile_id == PROFILE_A_ID:
            return self.profile_a_name
        if profile_id == PROFILE_B_ID:
            return self.profile_b_name
        return None

    def profile_soc_entity(self, profile_id: str) -> str | None:
        """Return only the configured SoC entity for this logical profile."""
        if profile_id == PROFILE_A_ID:
            return self.profile_a_soc_entity or None
        if profile_id == PROFILE_B_ID:
            return self.profile_b_soc_entity or None
        return None


@dataclass(frozen=True)
class SharedProfileSocSample:
    """A valid logical-profile SoC read from the HA state machine."""

    value: float
    entity_id: str
    source: str
    timestamp: Any


def validate_shared_loadpoint_options(options: Mapping[str, Any]) -> str | None:
    """Return a form error for an attempted shared binding, otherwise ``None``."""
    binding_keys = (
        CONF_SHARED_LOADPOINT_CONNECTED_VEHICLE_ENTITY,
        CONF_SHARED_LOADPOINT_PROFILE_A_NAME,
        CONF_SHARED_LOADPOINT_PROFILE_A_STATE,
        CONF_SHARED_LOADPOINT_PROFILE_B_NAME,
        CONF_SHARED_LOADPOINT_PROFILE_B_STATE,
    )
    values = {key: str(options.get(key) or "").strip() for key in binding_keys}
    soc_a = str(options.get(CONF_SHARED_LOADPOINT_PROFILE_A_SOC_ENTITY) or "").strip()
    soc_b = str(options.get(CONF_SHARED_LOADPOINT_PROFILE_B_SOC_ENTITY) or "").strip()
    if not any(values.values()) and not (soc_a or soc_b):
        return None
    if not all(values.values()):
        return "incomplete_shared_loadpoint_binding"
    if values[CONF_SHARED_LOADPOINT_PROFILE_A_NAME].casefold() == values[
        CONF_SHARED_LOADPOINT_PROFILE_B_NAME
    ].casefold():
        return "duplicate_shared_loadpoint_name"
    if _normalise_state(values[CONF_SHARED_LOADPOINT_PROFILE_A_STATE]) == _normalise_state(
        values[CONF_SHARED_LOADPOINT_PROFILE_B_STATE]
    ):
        return "duplicate_shared_loadpoint_state"
    if soc_a and soc_a.casefold() == soc_b.casefold():
        return "duplicate_shared_loadpoint_soc_entity"
    generic_enabled = bool(options.get(CONF_GENERIC_CHARGER_ENABLED))
    sigenergy_evac_enabled = bool(
        options.get(CONF_SIGENERGY_CHARGER_ENABLED)
        and options.get(CONF_SIGENERGY_CHARGER_TYPE) == SIGENERGY_CHARGER_EVAC
    )
    if generic_enabled and sigenergy_evac_enabled:
        return "shared_loadpoint_multiple_backends"
    if not generic_enabled and not sigenergy_evac_enabled:
        return "shared_loadpoint_no_supported_backend"
    return None


def binding_for_entry(config_entry: Any) -> SharedLoadpointBinding | None:
    """Return the configured binding, without treating incomplete input as active."""
    return SharedLoadpointBinding.from_options(
        {**getattr(config_entry, "data", {}), **getattr(config_entry, "options", {})}
    )


def canonical_shared_loadpoint_id(
    config_entry: Any,
    vehicle_id: Any,
    charger_type: str | None = None,
) -> str | None:
    """Map a logical shared profile to its sole physical runtime identity.

    ``None`` deliberately means either that this is not a logical shared
    profile or that the entry has no unambiguous supported shared backend.
    Callers can therefore preserve their legacy identity in the former case
    and fail closed in the latter where appropriate.
    """
    binding = binding_for_entry(config_entry)
    profile_id = str(vehicle_id or "").strip()
    if binding is None or profile_id not in (PROFILE_A_ID, PROFILE_B_ID):
        return None

    options = {**getattr(config_entry, "data", {}), **getattr(config_entry, "options", {})}
    requested_type = str(charger_type or "").strip().lower()
    generic_enabled = bool(options.get(CONF_GENERIC_CHARGER_ENABLED))
    sigenergy_evac_enabled = bool(
        options.get(CONF_SIGENERGY_CHARGER_ENABLED)
        and options.get(CONF_SIGENERGY_CHARGER_TYPE) == SIGENERGY_CHARGER_EVAC
    )
    if generic_enabled == sigenergy_evac_enabled:
        return None
    if generic_enabled and requested_type in ("", "generic"):
        return "generic_ev"
    if sigenergy_evac_enabled and requested_type in ("", "sigenergy"):
        return "sigenergy_charger"
    return None


def resolve_active_shared_profile(hass: Any, config_entry: Any) -> str | None:
    """Resolve current selected profile; unknown/unavailable/unmapped fails closed."""
    binding = binding_for_entry(config_entry)
    if binding is None:
        return None
    state = hass.states.get(binding.connected_vehicle_entity)
    if state is None:
        return None
    return binding.resolve_state(state.state)


def resolve_shared_profile_soc(
    hass: Any, config_entry: Any, profile_id: str
) -> SharedProfileSocSample | None:
    """Read valid SoC for one logical profile, without any fallback.

    This is deliberately state-machine-only: it never reads charger telemetry,
    calls a service, or consults the sibling/legacy Generic entities.
    """
    options = {**getattr(config_entry, "data", {}), **getattr(config_entry, "options", {})}
    if validate_shared_loadpoint_options(options) is not None:
        return None
    binding = binding_for_entry(config_entry)
    if binding is None:
        return None
    entity_id = binding.profile_soc_entity(profile_id)
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return SharedProfileSocSample(
        value=value,
        entity_id=entity_id,
        source="state",
        timestamp=getattr(state, "last_updated", None),
    )


def project_shared_loadpoint_status(
    hass: Any, config_entry: Any, payload: dict[str, Any],
    *, vehicle_configs: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attribute a physical status row without changing metering or runtime keys."""
    binding = binding_for_entry(config_entry)
    physical_id = canonical_shared_loadpoint_id(config_entry, PROFILE_A_ID)
    if binding is None or physical_id is None:
        return payload

    result = deepcopy(payload)
    selected = resolve_active_shared_profile(hass, config_entry)
    result["shared_loadpoint_active"] = True
    result["shared_loadpoint_id"] = physical_id
    result["selected_vehicle_id"] = selected
    for row in result.get("loadpoints") or ():
        if row.get("loadpoint_id") != physical_id:
            continue
        row["vehicle_id"] = selected
        row["vehicle_name"] = binding.profile_name(selected) if selected else None
        sample = resolve_shared_profile_soc(hass, config_entry, selected) if selected else None
        row["soc"] = sample.value if sample else None
        row["shared_loadpoint"] = True
        if selected:
            from .ev_vehicle_capacity import resolve_ev_battery_capacity

            profile_config = next(
                (item for item in vehicle_configs or [] if item.get("vehicle_id") == selected),
                {},
            )
            capacity = resolve_ev_battery_capacity(
                manual_capacity_kwh=profile_config.get("battery_capacity_kwh"),
                charger_fallback_capacity_kwh=None,
                provider_capacity_kwh=profile_config.get("provider_battery_capacity_kwh"),
                model=profile_config.get("vehicle_model"),
                trim=profile_config.get("vehicle_trim"),
                anonymous_loadpoint=False,
            )
            row.update(capacity.to_dict())
        else:
            row.update({
                "battery_capacity_kwh": None,
                "effective_battery_capacity_kwh": None,
                "battery_capacity_source": None,
            })
    return result


def is_retired_shared_vehicle_id(config_entry: Any, vehicle_id: Any) -> bool:
    """The former EV record is never a selectable target for an active binding."""
    physical_id = canonical_shared_loadpoint_id(config_entry, PROFILE_A_ID)
    return physical_id is not None and str(vehicle_id or "") == physical_id


def shared_physical_charger_fields(config_entry: Any) -> dict[str, Any]:
    """Project the active physical controller's entry settings, never EV copies."""
    if not shared_profile_configs(config_entry):
        return {}
    options = {**config_entry.data, **config_entry.options}
    if options.get(CONF_GENERIC_CHARGER_ENABLED):
        return {
            field: options.get(option) or ""
            for field, option in (
                ("charger_switch_entity", CONF_GENERIC_CHARGER_SWITCH_ENTITY),
                ("charger_amps_entity", CONF_GENERIC_CHARGER_AMPS_ENTITY),
                ("charger_status_entity", CONF_GENERIC_CHARGER_STATUS_ENTITY),
                ("charger_power_entity", CONF_GENERIC_CHARGER_POWER_ENTITY),
            )
        }
    return {
        "sigenergy_charger_host": (
            options.get(CONF_SIGENERGY_CHARGER_HOST)
            or options.get(CONF_SIGENERGY_MODBUS_HOST)
            or ""
        ),
        "sigenergy_charger_port": options.get(
            CONF_SIGENERGY_CHARGER_PORT, DEFAULT_SIGENERGY_CHARGER_PORT
        ),
        "sigenergy_charger_slave_id": options.get(
            CONF_SIGENERGY_CHARGER_SLAVE_ID, DEFAULT_SIGENERGY_CHARGER_SLAVE_ID
        ),
        "sigenergy_charger_type": options.get(
            CONF_SIGENERGY_CHARGER_TYPE, SIGENERGY_CHARGER_EVAC
        ),
        "sigenergy_charger_charge_power_limit_entity": options.get(
            CONF_SIGENERGY_CHARGER_CHARGE_POWER_LIMIT_ENTITY
        ) or "",
        "sigenergy_charger_discharge_power_limit_entity": options.get(
            CONF_SIGENERGY_CHARGER_DISCHARGE_POWER_LIMIT_ENTITY
        ) or "",
    }


def resolve_shared_loadpoint_command(
    hass: Any,
    config_entry: Any,
    requested_vehicle_id: Any,
    params: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Resolve a selected logical profile to its sole physical command identity.

    A configured binding turns profile selection into a mandatory safety gate:
    unknown selection and commands addressed to the non-selected profile are not
    converted into Generic/EVAC hardware commands. Unrelated backends retain
    their existing parameter mapping unchanged.
    """
    binding = binding_for_entry(config_entry)
    if binding is None:
        return dict(params)

    requested_id = str(requested_vehicle_id or "").strip()
    if requested_id not in (PROFILE_A_ID, PROFILE_B_ID):
        # A complete binding replaces the anonymous charger identity for every
        # Generic/EVAC command. Do not let a legacy physical ID bypass it.
        if str(params.get("charger_type") or "").strip().lower() in (
            "generic",
            "sigenergy",
        ):
            return None
        return dict(params)

    active_profile_id = resolve_active_shared_profile(hass, config_entry)
    if active_profile_id != requested_id:
        return None

    charger_type = str(params.get("charger_type") or "").strip().lower()
    physical_id = canonical_shared_loadpoint_id(
        config_entry,
        requested_id,
        charger_type,
    )
    if physical_id is None:
        return None

    return {
        **params,
        **shared_physical_charger_fields(config_entry),
        "vehicle_id": physical_id,
        "vehicle_vin": physical_id,
        "logical_vehicle_id": requested_id,
        "active_logical_vehicle_id": active_profile_id,
        "shared_loadpoint_binding": True,
    }


def handoff_idle_shared_profile(
    runtime_state: dict[str, Any],
    lease: dict[str, Any],
    requested_profile_id: str,
    observation: Any,
) -> bool:
    """Attribute an existing idle shared runtime to the newly selected profile.

    A handoff is deliberately metadata-only: it preserves the controller,
    timer, and session identity.  A fresh physical idle read is the sole proof
    that makes moving the logical attribution safe.
    """
    current_profile_id = runtime_state.get("active_profile_id")
    if (
        not current_profile_id
        or current_profile_id == requested_profile_id
        or not bool(getattr(observation, "fresh", False))
        or getattr(observation, "charging", None) is not False
    ):
        return False

    runtime_state["active_profile_id"] = requested_profile_id
    runtime_params = runtime_state.get("params")
    if not isinstance(runtime_params, dict):
        runtime_params = {}
        runtime_state["params"] = runtime_params
    runtime_params["active_logical_vehicle_id"] = requested_profile_id
    runtime_params["logical_vehicle_id"] = requested_profile_id
    lease["active_profile_id"] = requested_profile_id
    return True


def shared_profile_configs(config_entry: Any) -> list[dict[str, Any]]:
    """Return the two app-visible logical configs when a complete binding exists."""
    binding = binding_for_entry(config_entry)
    if binding is None:
        return []
    options = {**getattr(config_entry, "data", {}), **getattr(config_entry, "options", {})}
    charger_type = ""
    generic_enabled = bool(options.get(CONF_GENERIC_CHARGER_ENABLED))
    sigenergy_evac_enabled = bool(
        options.get(CONF_SIGENERGY_CHARGER_ENABLED)
        and options.get(CONF_SIGENERGY_CHARGER_TYPE) == SIGENERGY_CHARGER_EVAC
    )
    # A shared binding has exactly one physical command target.
    if generic_enabled == sigenergy_evac_enabled:
        return []
    if generic_enabled:
        charger_type = "generic"
    elif sigenergy_evac_enabled:
        charger_type = "sigenergy"
    return [
        {
            "vehicle_id": PROFILE_A_ID,
            "display_name": binding.profile_a_name,
            "charger_type": charger_type,
            "shared_loadpoint": True,
        },
        {
            "vehicle_id": PROFILE_B_ID,
            "display_name": binding.profile_b_name,
            "charger_type": charger_type,
            "shared_loadpoint": True,
        },
    ]


async def save_shared_profile_capacities(
    store: Any, capacities: Mapping[str, Any],
) -> bool:
    """Save Options capacities to the same vehicle records edited by the app."""
    from .ev_vehicle_capacity import validate_ev_battery_capacity

    validated = {
        profile_id: validate_ev_battery_capacity(capacities[profile_id])
        for profile_id in (PROFILE_A_ID, PROFILE_B_ID)
        if profile_id in capacities
    }
    if not validated:
        return False
    original = store._data.get("vehicle_charging_configs", [])
    updated: list[dict[str, Any]] = [dict(item) for item in original]
    for profile_id, value in validated.items():
        row = next((item for item in updated if item.get("vehicle_id") == profile_id), None)
        if row is None:
            if value is None:
                continue
            row = {"vehicle_id": profile_id}
            updated.append(row)
        if value is None:
            row.pop("battery_capacity_kwh", None)
        else:
            row["battery_capacity_kwh"] = value
    if updated == original:
        return False
    store._data["vehicle_charging_configs"] = updated
    try:
        await store.async_save()
    except Exception:
        store._data["vehicle_charging_configs"] = original
        raise
    return True


async def ensure_shared_logical_vehicle_configs(config_entry: Any, store: Any) -> bool:
    """Create/update the app-visible profiles without overwriting app-owned settings."""
    desired = shared_profile_configs(config_entry)
    if not desired:
        return False
    existing = list(getattr(store, "_data", {}).get("vehicle_charging_configs", []))
    by_id = {str(config.get("vehicle_id") or ""): config for config in existing if isinstance(config, dict)}
    changed = False
    for profile in desired:
        previous = by_id.get(profile["vehicle_id"])
        if previous is None:
            existing.append(profile)
            changed = True
            continue
        for key, value in profile.items():
            if previous.get(key) != value:
                previous[key] = value
                changed = True
    if changed:
        store._data["vehicle_charging_configs"] = existing
        await store.async_save()
    return changed

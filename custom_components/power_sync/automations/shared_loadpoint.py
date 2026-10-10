"""Logical-profile binding for one physical Generic Charger or Sigenergy EVAC."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from ..const import (
    CONF_GENERIC_CHARGER_ENABLED,
    CONF_SHARED_LOADPOINT_CONNECTED_VEHICLE_ENTITY,
    CONF_SHARED_LOADPOINT_PROFILE_A_NAME,
    CONF_SHARED_LOADPOINT_PROFILE_A_SOC_ENTITY,
    CONF_SHARED_LOADPOINT_PROFILE_A_STATE,
    CONF_SHARED_LOADPOINT_PROFILE_B_NAME,
    CONF_SHARED_LOADPOINT_PROFILE_B_SOC_ENTITY,
    CONF_SHARED_LOADPOINT_PROFILE_B_STATE,
    CONF_SIGENERGY_CHARGER_ENABLED,
    CONF_SIGENERGY_CHARGER_TYPE,
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

"""Logical-profile binding for one physical Generic Charger or Sigenergy EVAC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..const import (
    CONF_GENERIC_CHARGER_ENABLED,
    CONF_SHARED_LOADPOINT_CONNECTED_VEHICLE_ENTITY,
    CONF_SHARED_LOADPOINT_PROFILE_A_NAME,
    CONF_SHARED_LOADPOINT_PROFILE_A_STATE,
    CONF_SHARED_LOADPOINT_PROFILE_B_NAME,
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
    profile_b_name: str
    profile_b_state: str

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
            profile_b_name=str(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_B_NAME) or ""
            ).strip(),
            profile_b_state=_normalise_state(
                options.get(CONF_SHARED_LOADPOINT_PROFILE_B_STATE)
            ),
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


def binding_for_entry(config_entry: Any) -> SharedLoadpointBinding | None:
    """Return the configured binding, without treating incomplete input as active."""
    return SharedLoadpointBinding.from_options(
        {**getattr(config_entry, "data", {}), **getattr(config_entry, "options", {})}
    )


def resolve_active_shared_profile(hass: Any, config_entry: Any) -> str | None:
    """Resolve current selected profile; unknown/unavailable/unmapped fails closed."""
    binding = binding_for_entry(config_entry)
    if binding is None:
        return None
    state = hass.states.get(binding.connected_vehicle_entity)
    if state is None:
        return None
    return binding.resolve_state(state.state)


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

    options = {**getattr(config_entry, "data", {}), **getattr(config_entry, "options", {})}
    charger_type = str(params.get("charger_type") or "").strip().lower()
    physical_id: str | None = None
    if charger_type == "generic" and options.get(CONF_GENERIC_CHARGER_ENABLED):
        physical_id = "generic_ev"
    elif (
        charger_type == "sigenergy"
        and options.get(CONF_SIGENERGY_CHARGER_ENABLED)
        and options.get(CONF_SIGENERGY_CHARGER_TYPE) == SIGENERGY_CHARGER_EVAC
    ):
        physical_id = "sigenergy_charger"
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

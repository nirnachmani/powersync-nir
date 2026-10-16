"""Read-only diagnostic projection for an optional shared EV loadpoint API."""

from __future__ import annotations

from collections.abc import Mapping
import inspect
from typing import Any


_ADOPTING_MODES = frozenset({"solar_surplus", "scheduled", "smart_schedule", "price_level"})
_FRESH_EVIDENCE = frozenset({"fresh_power", "fresh_evac_state"})
_STORAGE_KEY = "_shared_loadpoint_diagnostic_snapshot"


def _compact_decision(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = value.get("allowed")
    mode = value.get("responsible_mode")
    reason = value.get("reason")
    if not isinstance(allowed, bool) or not isinstance(mode, str) or not isinstance(reason, str):
        return None
    return {"allowed": allowed, "responsible_mode": mode, "reason": reason}


def diagnostic_snapshot_record(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only durable, command-neutral selected-cycle diagnostic evidence."""
    return {
        "binding_id": snapshot.get("binding_id") if isinstance(snapshot.get("binding_id"), str) else None,
        "selected_profile_id": (
            snapshot.get("selected_profile_id")
            if isinstance(snapshot.get("selected_profile_id"), str)
            else None
        ),
        "evidence": snapshot.get("evidence") if isinstance(snapshot.get("evidence"), str) else None,
        "observed_at": snapshot.get("observed_at") if isinstance(snapshot.get("observed_at"), str) else None,
        "physical_active": (
            snapshot.get("physical_active")
            if isinstance(snapshot.get("physical_active"), bool)
            else None
        ),
        "origin": snapshot.get("origin") if isinstance(snapshot.get("origin"), str) else None,
        "decision": _compact_decision(snapshot.get("decision")),
    }


def _compact_ownership(value: Any) -> dict[str, Any] | None:
    """Whitelist non-secret arbitration facts from a physical ownership lease."""
    if not isinstance(value, Mapping):
        return None
    return {
        key: value.get(key)
        for key in ("owner", "owner_mode", "active_profile_id", "updated_at", "stop_settling")
        if isinstance(value.get(key), (str, bool))
    }


def _compact_last_command(value: Any) -> dict[str, Any] | None:
    """Whitelist command outcome facts; do not return stored command parameters."""
    if not isinstance(value, Mapping):
        return None
    return {
        key: value.get(key)
        for key in ("command", "at", "source", "success", "reason")
        if isinstance(value.get(key), (str, bool)) or value.get(key) is None and key == "reason"
    }


def _compact_soc(value: Any, *, cache: bool = False) -> dict[str, Any] | None:
    """Return display-only SoC facts; cached SoC is never control authority."""
    if not isinstance(value, Mapping):
        return None
    soc = value.get("value")
    valid = value.get("valid")
    if (
        soc is not None
        and (not isinstance(soc, (int, float)) or isinstance(soc, bool))
    ) or not isinstance(valid, bool):
        return None
    result = {"value": soc, "valid": valid}
    if cache:
        result.update({
            "updated_at": value.get("updated_at") if isinstance(value.get("updated_at"), str) else None,
            "age_seconds": value.get("age_seconds") if isinstance(value.get("age_seconds"), (int, float)) else None,
            "authorizes_control": False,
        })
    else:
        result.update({
            "entity_id": value.get("entity_id") if isinstance(value.get("entity_id"), str) else None,
            "source": value.get("source") if isinstance(value.get("source"), str) else None,
            "observed_at": value.get("observed_at") if isinstance(value.get("observed_at"), str) else None,
            "age_seconds": value.get("age_seconds") if isinstance(value.get("age_seconds"), (int, float)) else None,
        })
    return result


def _compact_session_provenance(value: Any, selected_profile_id: str | None) -> dict[str, Any] | None:
    """Expose only the selected logical session's harmless SoC provenance."""
    if not selected_profile_id or not isinstance(value, Mapping):
        return None
    if value.get("logical_vehicle_id") != selected_profile_id:
        return None

    def endpoint(name: str) -> dict[str, Any] | None:
        raw = value.get(name)
        if not isinstance(raw, Mapping):
            return None
        return {
            "soc": raw.get("soc") if isinstance(raw.get("soc"), (int, float)) else None,
            "entity_id": raw.get("entity_id") if isinstance(raw.get("entity_id"), str) else None,
            "time": raw.get("time") if isinstance(raw.get("time"), str) else None,
            "source": raw.get("source") if isinstance(raw.get("source"), str) else None,
        }

    return {
        "logical_vehicle_id": selected_profile_id,
        "start": endpoint("start"),
        "end": endpoint("end"),
    }


def _compact_schedule_presentation(
    presentations: Any,
    selected_profile_id: str | None,
) -> dict[str, Any] | None:
    """Expose only the selected profile's advisory plan summary."""
    if not selected_profile_id or not isinstance(presentations, Mapping):
        return None
    value = presentations.get(selected_profile_id)
    if not isinstance(value, Mapping):
        return None
    state = value.get("state")
    if state not in {"active", "next", "no_plan", "stale", "unavailable"}:
        return None
    return {
        key: value.get(key) if isinstance(value.get(key), str) else None
        for key in (
            "window_start",
            "window_end",
            "source",
            "plan_updated_at",
            "plan_snapshot_id",
        )
    } | {"state": state}


def project_shared_loadpoint_diagnostics(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Project persisted diagnostic facts without reading hardware or controlling it."""
    selected_profile_id = snapshot.get("selected_profile_id")
    evidence = snapshot.get("evidence")
    physical_active = snapshot.get("physical_active")
    origin = snapshot.get("origin")
    decision = _compact_decision(snapshot.get("decision"))
    stop_outcome = snapshot.get("stop_outcome")
    desired_action: str | None = None
    reason: str | None = None

    if not isinstance(selected_profile_id, str) or not selected_profile_id:
        reason = "no selected shared profile"
    elif evidence not in _FRESH_EVIDENCE or physical_active is None:
        reason = "shared loadpoint evidence is stale or unknown"
    elif isinstance(stop_outcome, Mapping) and stop_outcome.get("status") in {
        "pending", "failed", "indeterminate", "timed_out"
    }:
        reason = "shared loadpoint stop confirmation is pending or unknown"
    elif physical_active is False:
        reason = "shared loadpoint is physically idle"
    elif origin != "external":
        reason = "shared loadpoint is not a proven external session"
    elif snapshot.get("external_control_policy") == "yield":
        desired_action = "allow"
        reason = "external control policy is yield"
    elif decision is None:
        reason = "selected shared profile has no persisted decision"
    elif decision["allowed"] and decision["responsible_mode"] in _ADOPTING_MODES:
        desired_action = "adopt"
        reason = decision["reason"]
    elif decision["allowed"]:
        desired_action = "allow"
        reason = decision["reason"]
    else:
        desired_action = "stop"
        reason = decision["reason"]

    selected_name = snapshot.get("selected_profile_name")
    selected_profile = selected_profile_id if isinstance(selected_profile_id, str) and selected_profile_id else None
    binding_id = snapshot.get("binding_id") if isinstance(snapshot.get("binding_id"), str) else None
    config_entry_id = snapshot.get("config_entry_id") if isinstance(snapshot.get("config_entry_id"), str) else None
    identity = (
        {
            "config_entry_id": config_entry_id,
            "physical_loadpoint_id": binding_id,
            "logical_profile_id": selected_profile,
        }
        if config_entry_id and binding_id and selected_profile
        else None
    )
    live_soc = _compact_soc(snapshot.get("live_soc")) if selected_profile else None
    cached_soc = _compact_soc(snapshot.get("cached_soc"), cache=True) if selected_profile else None
    return {
        "binding_id": binding_id,
        "identity": identity,
        "selected_profile": {
            "id": selected_profile,
            "name": selected_name if selected_profile and isinstance(selected_name, str) else None,
        },
        "mapping": {
            "logical_profile_id": selected_profile,
            "physical_loadpoint_id": binding_id if selected_profile else None,
        },
        "soc": {
            "live": live_soc,
            "cache": cached_soc,
            "effective_source": "live" if live_soc and live_soc["valid"] else (
                "cache" if cached_soc and cached_soc["valid"] else None
            ),
        },
        "last_block_reason": (
            snapshot.get("last_block_reason")
            if isinstance(snapshot.get("last_block_reason"), str)
            else (decision["reason"] if decision and not decision["allowed"] else None)
        ),
        "last_session": _compact_session_provenance(snapshot.get("last_session"), selected_profile),
        "schedule_presentation": _compact_schedule_presentation(
            snapshot.get("schedule_presentations"),
            selected_profile,
        ),
        "physical_active": physical_active if isinstance(physical_active, bool) else None,
        "origin": origin if isinstance(origin, str) else None,
        "evidence": evidence if isinstance(evidence, str) else None,
        "observed_at": snapshot.get("observed_at") if isinstance(snapshot.get("observed_at"), str) else None,
        "ownership": _compact_ownership(snapshot.get("ownership")),
        "last_command": _compact_last_command(snapshot.get("last_command")),
        "decision": decision,
        "external_control_policy": (
            snapshot.get("external_control_policy")
            if isinstance(snapshot.get("external_control_policy"), str)
            else None
        ),
        "desired_action": desired_action,
        "reason": reason,
    }


def _soc_age_seconds(value: Any) -> float | None:
    """Return a non-negative UTC age for a persisted or state timestamp."""
    from datetime import datetime, timezone

    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    return age if age >= 0 else None


def _live_soc_fact(hass: Any, config_entry: Any, binding: Any, profile_id: str) -> dict[str, Any]:
    """Read only the profile-owned HA state for diagnostic truth."""
    from .shared_loadpoint import resolve_shared_profile_soc

    entity_id = binding.profile_soc_entity(profile_id)
    state = hass.states.get(entity_id) if entity_id else None
    sample = resolve_shared_profile_soc(hass, config_entry, profile_id)
    timestamp = getattr(state, "last_updated", None) if state is not None else None
    return {
        "value": sample.value if sample is not None else None,
        "entity_id": entity_id,
        "source": "state",
        "observed_at": timestamp.isoformat() if timestamp is not None and hasattr(timestamp, "isoformat") else None,
        "age_seconds": _soc_age_seconds(timestamp),
        "valid": sample is not None,
    }


def _cached_soc_fact(store: Any, profile_id: str) -> dict[str, Any] | None:
    """Expose profile-local planner cache facts without treating them as authority."""
    cached = getattr(store, "_data", {}).get("cached_vehicle_soc", {})
    entry = cached.get(profile_id) if isinstance(cached, Mapping) else None
    if not isinstance(entry, Mapping):
        return None
    value = entry.get("soc")
    updated_at = entry.get("updated")
    age_seconds = _soc_age_seconds(updated_at)
    valid = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= 100
        and age_seconds is not None
        and age_seconds <= 24 * 60 * 60
    )
    return {
        "value": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
        "updated_at": updated_at if isinstance(updated_at, str) else None,
        "age_seconds": age_seconds,
        "valid": valid,
    }


def _session_provenance(session: Any, profile_id: str) -> dict[str, Any] | None:
    """Return one profile-attributed session's persisted SoC endpoints."""
    if session is None or (getattr(session, "logical_vehicle_id", None) or getattr(session, "vehicle_id", None)) != profile_id:
        return None
    return {
        "logical_vehicle_id": profile_id,
        "start": {
            "soc": getattr(session, "start_soc", None),
            "entity_id": getattr(session, "start_soc_entity", None),
            "time": getattr(session, "start_soc_time", None),
            "source": getattr(session, "start_soc_source", None),
        },
        "end": {
            "soc": getattr(session, "end_soc", None),
            "entity_id": getattr(session, "end_soc_entity", None),
            "time": getattr(session, "end_soc_time", None),
            "source": getattr(session, "end_soc_source", None),
        },
    }


def _last_profile_session(profile_id: str) -> dict[str, Any] | None:
    """Inspect in-memory session history only; never read hardware or storage."""
    from .ev_charging_session import get_session_manager

    manager = get_session_manager()
    if manager is None:
        return None
    candidates = [
        session for session in manager.active_sessions.values()
        if (getattr(session, "logical_vehicle_id", None) or getattr(session, "vehicle_id", None)) == profile_id
    ]
    candidates.extend(
        session for session in getattr(manager, "_sessions_cache", [])
        if (getattr(session, "logical_vehicle_id", None) or getattr(session, "vehicle_id", None)) == profile_id
    )
    if not candidates:
        return None
    return _session_provenance(max(candidates, key=lambda session: getattr(session, "start_time", "")), profile_id)


async def persist_shared_loadpoint_diagnostic_snapshot(
    hass: Any,
    config_entry: Any,
    snapshot: Mapping[str, Any],
) -> None:
    """Persist only the compact, selected decision before a cycle ledger clears."""
    entry = getattr(hass, "data", {}).get("power_sync", {}).get(
        getattr(config_entry, "entry_id", ""), {}
    )
    store = entry.get("automation_store") if isinstance(entry, Mapping) else None
    data = getattr(store, "_data", None)
    if not isinstance(data, dict):
        return
    data[_STORAGE_KEY] = diagnostic_snapshot_record(snapshot)
    save = getattr(store, "async_save", None)
    if callable(save):
        result = save()
        if inspect.isawaitable(result):
            await result


def persisted_shared_loadpoint_diagnostics(hass: Any, config_entry: Any) -> dict[str, Any]:
    """Build the optional API projection from persisted facts and current selection."""
    from .external_session_reconciler import load_reconciliation_state
    from .ev_ownership import (
        get_ev_last_commands,
        get_ev_ownership,
        get_external_control_policy,
    )
    from .shared_loadpoint import (
        binding_for_entry,
        canonical_shared_loadpoint_id,
        resolve_active_shared_profile,
    )

    binding = binding_for_entry(config_entry)
    selected_profile_id = resolve_active_shared_profile(hass, config_entry) if binding else None
    binding_id = (
        canonical_shared_loadpoint_id(config_entry, selected_profile_id)
        if selected_profile_id is not None
        else None
    )
    selected_name = binding.profile_name(selected_profile_id) if binding and selected_profile_id else None
    evidence: dict[str, Any] = {}
    if binding_id:
        state = load_reconciliation_state(hass, config_entry, binding_id)
        observed_at = state.observed_at.isoformat() if state.observed_at else None
        evidence = {
            "physical_active": state.physical_active,
            "origin": state.origin,
            "evidence": state.evidence,
            "observed_at": observed_at,
            "stop_outcome": state.stop_outcome,
        }
    entry = getattr(hass, "data", {}).get("power_sync", {}).get(
        getattr(config_entry, "entry_id", ""), {}
    )
    store = entry.get("automation_store") if isinstance(entry, Mapping) else None
    stored = getattr(store, "_data", {}).get(_STORAGE_KEY, {})
    stored = stored if isinstance(stored, Mapping) else {}
    decision = (
        stored.get("decision")
        if stored.get("binding_id") == binding_id
        and stored.get("selected_profile_id") == selected_profile_id
        else None
    )
    _lease_id, ownership = get_ev_ownership(hass, config_entry, binding_id) if binding_id else (None, None)
    last_command = get_ev_last_commands(hass, config_entry).get(binding_id) if binding_id else None
    schedule_presentations: dict[str, dict[str, Any]] = {}
    try:
        from .ev_charging_planner import get_auto_schedule_executor

        executor = get_auto_schedule_executor()
        if (
            executor is not None
            and getattr(getattr(executor, "config_entry", None), "entry_id", None)
            == getattr(config_entry, "entry_id", None)
        ):
            schedule_presentations = executor.get_logical_schedule_presentations()
    except Exception:
        # Diagnostics remain available when planner startup or presentation
        # projection is unavailable; this must never affect control paths.
        schedule_presentations = {}
    return project_shared_loadpoint_diagnostics({
        "config_entry_id": getattr(config_entry, "entry_id", None),
        "binding_id": binding_id,
        "selected_profile_id": selected_profile_id,
        "selected_profile_name": selected_name,
        **evidence,
        "ownership": ownership,
        "last_command": last_command,
        "decision": decision,
        "live_soc": _live_soc_fact(hass, config_entry, binding, selected_profile_id)
        if binding and selected_profile_id else None,
        "cached_soc": _cached_soc_fact(store, selected_profile_id)
        if selected_profile_id else None,
        "last_block_reason": (
            decision.get("reason")
            if isinstance(decision, Mapping) and decision.get("allowed") is False
            else None
        ),
        "last_session": _last_profile_session(selected_profile_id)
        if selected_profile_id else None,
        "schedule_presentations": schedule_presentations,
        "external_control_policy": (
            get_external_control_policy(hass, config_entry, selected_profile_id)
            if selected_profile_id is not None
            else None
        ),
    })

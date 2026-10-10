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
    return {
        "binding_id": snapshot.get("binding_id") if isinstance(snapshot.get("binding_id"), str) else None,
        "selected_profile": {
            "id": selected_profile_id if isinstance(selected_profile_id, str) else None,
            "name": selected_name if isinstance(selected_name, str) else None,
        },
        "physical_active": physical_active if isinstance(physical_active, bool) else None,
        "origin": origin if isinstance(origin, str) else None,
        "evidence": evidence if isinstance(evidence, str) else None,
        "observed_at": snapshot.get("observed_at") if isinstance(snapshot.get("observed_at"), str) else None,
        "ownership": dict(snapshot["ownership"]) if isinstance(snapshot.get("ownership"), Mapping) else None,
        "last_command": dict(snapshot["last_command"]) if isinstance(snapshot.get("last_command"), Mapping) else None,
        "decision": decision,
        "external_control_policy": (
            snapshot.get("external_control_policy")
            if isinstance(snapshot.get("external_control_policy"), str)
            else None
        ),
        "desired_action": desired_action,
        "reason": reason,
    }


async def persist_shared_loadpoint_diagnostic_snapshot(
    hass: Any,
    config_entry: Any,
    snapshot: Mapping[str, Any],
) -> None:
    """Persist only the compact, selected decision before a cycle ledger clears."""
    entry = getattr(hass, "data", {}).get("powersync_nir", {}).get(
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
    entry = getattr(hass, "data", {}).get("powersync_nir", {}).get(
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
    return project_shared_loadpoint_diagnostics({
        "binding_id": binding_id,
        "selected_profile_id": selected_profile_id,
        "selected_profile_name": selected_name,
        **evidence,
        "ownership": ownership,
        "last_command": last_command,
        "decision": decision,
        "external_control_policy": (
            get_external_control_policy(hass, config_entry, selected_profile_id)
            if selected_profile_id is not None
            else None
        ),
    })

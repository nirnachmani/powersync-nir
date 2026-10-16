"""Strict projection of solved demand for one logical shared EV profile."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import math
from typing import Any


def _exact_series(values: Any, size: int) -> list[float] | None:
    """Copy a finite-length sequence only when it exactly fits the optimizer grid."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        return None
    if len(values) != size:
        return None
    copied = list(values)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in copied
    ):
        return None
    return copied


def logical_optimizer_planned_demand_series(
    *,
    selected_profile_id: str | None,
    logical_profile_ids: Sequence[str],
    physical_loadpoint_id: str | None,
    physical_by_vehicle: Mapping[str, str],
    optimizer_timestamps: Sequence[str],
    schedule_timestamps: Sequence[str],
    series_timestamps: Sequence[str],
    schedule_plan_snapshot_id: str | None,
    series_plan_snapshot_id: str | None,
    series_by_vehicle_w: Mapping[str, Sequence[float]],
) -> dict[str, Any] | None:
    """Return an exact selected-profile demand series, otherwise nothing.

    This deliberately cannot pad, slice, merge, shift, or relabel solved EV
    output.  The dashboard may present a logical shared EV only when the
    optimizer grid, schedule response, solved series, and solve identity all
    describe the same snapshot and that profile is the physical loadpoint's
    only contributor.
    """
    profiles = tuple(logical_profile_ids)
    if (
        not selected_profile_id
        or selected_profile_id not in profiles
        or not physical_loadpoint_id
        or not isinstance(schedule_plan_snapshot_id, str)
        or not schedule_plan_snapshot_id
        or schedule_plan_snapshot_id != series_plan_snapshot_id
    ):
        return None

    grid = list(optimizer_timestamps)
    if not grid or list(schedule_timestamps) != grid or list(series_timestamps) != grid:
        return None

    contributors = [
        vehicle_id
        for vehicle_id in series_by_vehicle_w
        if physical_by_vehicle.get(vehicle_id) == physical_loadpoint_id
    ]
    if contributors != [selected_profile_id]:
        return None

    series = _exact_series(series_by_vehicle_w.get(selected_profile_id), len(grid))
    if series is None:
        return None

    return {
        "vehicle_id": selected_profile_id,
        "timestamps": grid,
        "planned_demand_w": series,
        "plan_snapshot_id": schedule_plan_snapshot_id,
    }


def shared_logical_optimizer_chart_payload(
    *,
    adopted_schedule_snapshot_id: str | None,
    current_schedule_snapshot_id: str | None,
    selected_profile_id: str | None,
    logical_profile_ids: Sequence[str],
    physical_loadpoint_id: str | None,
    physical_by_vehicle: Mapping[str, str],
    optimizer_timestamps: Sequence[str],
    schedule_timestamps: Sequence[str],
    series_timestamps: Sequence[str],
    plan_snapshot_id: str | None,
    series_by_vehicle_w: Mapping[str, Sequence[float]],
) -> dict[str, Any] | None:
    """Project a solved shared-EV series only from the current solve snapshot."""
    if (
        not isinstance(adopted_schedule_snapshot_id, str)
        or not adopted_schedule_snapshot_id
        or adopted_schedule_snapshot_id != current_schedule_snapshot_id
    ):
        return None
    return logical_optimizer_planned_demand_series(
        selected_profile_id=selected_profile_id,
        logical_profile_ids=logical_profile_ids,
        physical_loadpoint_id=physical_loadpoint_id,
        physical_by_vehicle=physical_by_vehicle,
        optimizer_timestamps=optimizer_timestamps,
        schedule_timestamps=schedule_timestamps,
        series_timestamps=series_timestamps,
        schedule_plan_snapshot_id=plan_snapshot_id,
        series_plan_snapshot_id=plan_snapshot_id,
        series_by_vehicle_w=series_by_vehicle_w,
    )


def shared_logical_optimizer_chart_payload_for_coordinator(
    *,
    coordinator: Any,
    schedule_response: Mapping[str, Any],
    series_by_vehicle_w: Mapping[str, Sequence[float]],
    plan_snapshot_id: str | None,
) -> dict[str, Any] | None:
    """Adapt current coordinator output without touching optimizer decisions."""
    from .shared_loadpoint import (
        PROFILE_A_ID,
        PROFILE_B_ID,
        canonical_shared_loadpoint_id,
        resolve_active_shared_profile,
    )

    schedule = getattr(coordinator, "_current_schedule", None)
    actions = getattr(schedule, "actions", None) or []
    if not all(isinstance(getattr(action, "timestamp", None), datetime) for action in actions):
        return None
    optimizer_timestamps = [action.timestamp.isoformat() for action in actions]
    schedule_timestamps = schedule_response.get("timestamps")
    if not isinstance(schedule_timestamps, Sequence) or isinstance(
        schedule_timestamps, (str, bytes)
    ):
        return None

    selected_profile_id = resolve_active_shared_profile(
        getattr(coordinator, "hass", None), getattr(coordinator, "config_entry", None)
    )
    physical_by_vehicle = {
        profile_id: physical_id
        for profile_id in (PROFILE_A_ID, PROFILE_B_ID)
        if (
            physical_id := canonical_shared_loadpoint_id(
                getattr(coordinator, "config_entry", None), profile_id
            )
        )
    }
    physical_loadpoint_id = (
        physical_by_vehicle.get(selected_profile_id)
        if selected_profile_id is not None
        else None
    )
    if physical_loadpoint_id:
        # A solver row bearing this physical ID is not a logical profile.
        physical_by_vehicle[physical_loadpoint_id] = physical_loadpoint_id

    adopted_updated = getattr(coordinator, "_last_ev_charge_schedule_updated", None)
    current_updated = getattr(schedule, "last_updated", None)
    return shared_logical_optimizer_chart_payload(
        adopted_schedule_snapshot_id=(
            adopted_updated.isoformat() if isinstance(adopted_updated, datetime) else None
        ),
        current_schedule_snapshot_id=(
            current_updated.isoformat() if isinstance(current_updated, datetime) else None
        ),
        selected_profile_id=selected_profile_id,
        logical_profile_ids=(PROFILE_A_ID, PROFILE_B_ID),
        physical_loadpoint_id=physical_loadpoint_id,
        physical_by_vehicle=physical_by_vehicle,
        optimizer_timestamps=optimizer_timestamps,
        schedule_timestamps=schedule_timestamps,
        series_timestamps=optimizer_timestamps,
        plan_snapshot_id=plan_snapshot_id,
        series_by_vehicle_w=series_by_vehicle_w,
    )
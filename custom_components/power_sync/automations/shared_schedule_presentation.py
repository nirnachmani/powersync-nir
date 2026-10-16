"""Read-only Smart Schedule presentation for logical shared EV profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any


_EMPTY_SNAPSHOT = {
    "state": "unavailable",
    "window_start": None,
    "window_end": None,
    "source": None,
    "plan_updated_at": None,
    "plan_snapshot_id": None,
}


def _isoformat(value: Any) -> str | None:
    """Serialize a timestamp only when it is an actual datetime."""
    return value.isoformat() if isinstance(value, datetime) else None


def _parse_window_time(value: Any, now: datetime) -> datetime | None:
    """Parse an ISO window boundary without changing its display representation."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=now.tzinfo or timezone.utc)
    return parsed


def _source_label(source: Any) -> str | None:
    """Return a presentation-only Smart Schedule source label."""
    value = str(source or "").strip().casefold()
    if not value:
        return None
    if value in {"solar", "solar_surplus"}:
        return "Smart Schedule (solar)"
    if value.startswith("grid"):
        return "Smart Schedule (grid)"
    return f"Smart Schedule ({value.replace('_', ' ')})"


def _snapshot_id(profile_id: str, plan_updated_at: str | None, windows: list[Any]) -> str | None:
    """Return a stable ID for one logical profile's in-memory plan snapshot."""
    if not plan_updated_at:
        return None
    material = {
        "profile_id": profile_id,
        "plan_updated_at": plan_updated_at,
        "windows": [
            {
                "start": getattr(window, "start_time", None),
                "end": getattr(window, "end_time", None),
                "source": getattr(window, "source", None),
            }
            for window in windows
        ],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()[:16]


def logical_schedule_snapshot(
    *,
    profile_id: str,
    selected_profile_id: str | None,
    state: Any,
    now: datetime,
) -> dict[str, Any]:
    """Describe a selected logical profile's cached plan without operational I/O.

    The caller supplies selection and in-memory executor state.  This function
    does not inspect charger measurements, acquire a lease, run a timer, issue a
    command, or mutate planner/executor state.
    """
    if not profile_id or selected_profile_id != profile_id:
        return dict(_EMPTY_SNAPSHOT)
    if state is None:
        return dict(_EMPTY_SNAPSHOT)

    plan = getattr(state, "current_plan", None)
    plan_updated_at = _isoformat(getattr(state, "last_plan_update", None))
    if plan is None:
        return {
            "state": "no_plan",
            "window_start": None,
            "window_end": None,
            "source": None,
            "plan_updated_at": plan_updated_at,
            "plan_snapshot_id": None,
        }

    windows = list(getattr(plan, "windows", ()) or ())
    snapshot_id = _snapshot_id(profile_id, plan_updated_at, windows)
    future: list[tuple[datetime, Any]] = []
    for window in windows:
        start_raw = getattr(window, "start_time", None)
        end_raw = getattr(window, "end_time", None)
        start = _parse_window_time(start_raw, now)
        end = _parse_window_time(end_raw, now)
        if start is None or end is None or end <= start:
            continue
        if start <= now < end:
            return {
                "state": "active",
                "window_start": start_raw,
                "window_end": end_raw,
                "source": _source_label(getattr(window, "source", None)),
                "plan_updated_at": plan_updated_at,
                "plan_snapshot_id": snapshot_id,
            }
        if start > now:
            future.append((start, window))

    if future:
        _start, window = min(future, key=lambda item: item[0])
        return {
            "state": "next",
            "window_start": getattr(window, "start_time", None),
            "window_end": getattr(window, "end_time", None),
            "source": _source_label(getattr(window, "source", None)),
            "plan_updated_at": plan_updated_at,
            "plan_snapshot_id": snapshot_id,
        }

    return {
        "state": "stale",
        "window_start": None,
        "window_end": None,
        "source": None,
        "plan_updated_at": plan_updated_at,
        "plan_snapshot_id": snapshot_id,
    }

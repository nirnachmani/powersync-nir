"""Manual charge/discharge timing validation (adapted from upstream 3297a01d, d3a276c8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_FORCE_DISCHARGE_MINUTES = 1440
CUSTOM_DISCHARGE_DURATION = "Custom"
CUSTOM_DISCHARGE_DURATION_KEY = "force_discharge_custom_duration"


def validate_discharge_duration(value: Any) -> int:
    """Reject invalid requests rather than silently starting a default window."""
    try:
        minutes = float(value)
    except (TypeError, ValueError, OverflowError):
        minutes = math.nan
    if (isinstance(value, bool) or not math.isfinite(minutes)
            or not minutes.is_integer() or not 1 <= minutes <= MAX_FORCE_DISCHARGE_MINUTES):
        raise ValueError("Charge/discharge duration must be a whole number from 1 to 1440 minutes (24 hours)")
    return int(minutes)


def selected_discharge_duration(value: Any, options: dict) -> int:
    """Resolve an explicit custom selection without substituting a default."""
    if value == CUSTOM_DISCHARGE_DURATION:
        value = options.get(CUSTOM_DISCHARGE_DURATION_KEY, 30)
    return validate_discharge_duration(value)


def resolve_manual_force_duration(data: Any, options: dict, time_zone: str, *, now: datetime | None = None) -> int:
    """Resolve minutes or the next real HA-local HH:mm (including DST folds).

    UTC round-tripping skips nonexistent spring-forward times. Native force
    lifecycles take whole minutes, so finish-at rounds up by less than 60 s.
    """
    if "until" not in data:
        return selected_discharge_duration(data.get("duration", 30), options)
    if "duration" in data:
        raise ValueError("Choose duration or until, not both")
    value = data["until"]
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("Until must be a clock time in HH:mm format")
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as err:
        raise ValueError("Home Assistant timezone is unavailable") from err
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hour, minute = map(int, value.split(":"))
    local_date = now.astimezone(zone).date()
    candidates = []
    for offset in range(3):
        day = local_date + timedelta(days=offset)
        for fold in (0, 1):
            local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=fold)
            utc = local.astimezone(timezone.utc)
            back = utc.astimezone(zone)
            if back.replace(tzinfo=None) == local.replace(tzinfo=None) and utc > now:
                candidates.append(utc)
    if not candidates:
        raise ValueError("Until has no upcoming valid occurrence")
    return validate_discharge_duration(math.ceil((min(candidates) - now).total_seconds() / 60))
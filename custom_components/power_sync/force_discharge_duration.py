"""Manual discharge duration validation (adapted from upstream 3297a01d)."""
from __future__ import annotations

import math
from typing import Any

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
        raise ValueError("Force Discharge duration must be a whole number from 1 to 1440 minutes (24 hours)")
    return int(minutes)


def selected_discharge_duration(value: Any, options: dict) -> int:
    """Resolve an explicit custom selection without substituting a default."""
    if value == CUSTOM_DISCHARGE_DURATION:
        value = options.get(CUSTOM_DISCHARGE_DURATION_KEY, 30)
    return validate_discharge_duration(value)
"""Pure, cycle-local arbitration for eligible shared EV opportunities.

The caller supplies the results of the existing mode checks; this module does
not infer plug state, run a discovery trial, or authorize charger commands.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from uuid import uuid4


def update_opportunity_request(entry: dict, facts: dict, now):
    """Publish a fresh, identity-bound decision; return (request, changed).

    The caller must withdraw on every ineligible or uncertain evaluation. A
    decision which expired cannot be revived by refreshing the same object: an
    already adopted solver result belongs to the old decision episode.
    """
    old = entry.get('_shared_opportunity_request')
    try:
        fresh = isinstance(old, dict) and 0 <= (now - old['decided_at']).total_seconds() <= 90
    except (KeyError, TypeError, ValueError, OverflowError):
        fresh = False
    previous = {key: value for key, value in old.items()
                if key not in {'generation', 'decided_at'}} if isinstance(old, dict) else None
    if isinstance(old, dict) and fresh and previous == facts:
        old['decided_at'] = now
        return old, False
    request = {**facts, 'generation': uuid4().hex, 'decided_at': now}
    entry['_shared_opportunity_request'] = request
    return request, True


def withdraw_opportunity_request(entry: dict) -> bool:
    """Invalidate the exact request and any result previously bound to it."""
    return entry.pop('_shared_opportunity_request', None) is not None


@dataclass
class SolarBoundary:
    """Sustained evidence at the configured maximum-rate boundary."""

    full: bool = False
    above_since: float | None = None
    below_since: float | None = None


def choose_positive_price_owner(
    state: SolarBoundary, *, now: float, solar_eligible: bool,
    solar_capacity_kw: float, maximum_kw: float, price_cents: float | None,
    opportunity_price_cents: float, price_eligible: bool,
    start_delay_s: float, stop_delay_s: float,
) -> str | None:
    """Select a mode only for known positive import prices.

    ``None`` leaves free/negative or unknown-price handling to its existing
    controller. The mode eligibility and raw sustainable power must be derived
    from the existing live checks before calling this function.
    """
    try:
        values = (now, solar_capacity_kw, maximum_kw, opportunity_price_cents,
                  start_delay_s, stop_delay_s)
        if not all(math.isfinite(float(value)) for value in values):
            return None
        if price_cents is None or not math.isfinite(float(price_cents)) or price_cents <= 0:
            return None
        if maximum_kw <= 0 or solar_capacity_kw < 0 or start_delay_s < 0 or stop_delay_s < 0:
            return None
    except (TypeError, ValueError, OverflowError):
        return None

    if not solar_eligible:
        state.full = False
        state.above_since = state.below_since = None
        return 'price_level' if price_eligible else None

    if solar_capacity_kw >= maximum_kw:
        state.below_since = None
        if state.above_since is None or now < state.above_since:
            state.above_since = now
        if now - state.above_since >= start_delay_s:
            state.full = True
    else:
        state.above_since = None
        if state.below_since is None or now < state.below_since:
            state.below_since = now
        if now - state.below_since >= stop_delay_s:
            state.full = False

    if not price_eligible or price_cents > opportunity_price_cents or state.full:
        return 'solar_surplus'
    return 'price_level'

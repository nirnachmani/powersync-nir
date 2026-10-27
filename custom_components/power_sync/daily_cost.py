"""Display-only fixed site supply costs adapted from upstream ccf8f688.

No GloBird/ZeroHero export bonus or optimizer pricing is involved. The
existing accumulator's priced-energy coverage remains authoritative.
"""
from __future__ import annotations

import calendar
import math
from datetime import datetime
from typing import Any


def _finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def configured_supply_charge(entry: Any, now: datetime) -> float:
    """Resolve configured daily charge or monthly charge by calendar days."""
    settings = dict(getattr(entry, "data", {}) or {})
    settings.update(getattr(entry, "options", {}) or {})
    daily = max(0.0, _finite(settings.get("daily_supply_charge")))
    if daily > 0:
        return daily
    monthly = max(0.0, _finite(settings.get("monthly_supply_charge")))
    return monthly / calendar.monthrange(now.year, now.month)[1]


class SupplyCostTracker:
    """Persist observed daily rates; estimate unobserved days at current rate."""

    def __init__(self, supply_charge: float = 0.0, state: Any = None) -> None:
        self.supply_charge = max(0.0, _finite(supply_charge))
        self.state = dict(state) if isinstance(state, dict) else {}
        self.state["supply_by_day"] = dict(self.state.get("supply_by_day") or {})

    def observe(self, now: datetime) -> None:
        day = now.date().isoformat()
        month = day[:7]
        if self.state.get("month") != month:
            self.state = {"month": month, "supply_by_day": {}}
        self.state["day"] = day
        self.state["supply_by_day"][day] = self.supply_charge

    def summary(self, base: dict) -> dict:
        result = dict(base)
        by_day = self.state.get("supply_by_day", {})
        day = self.state.get("day", "0000-00-00")
        days = int(day[-2:])
        daily = _finite(by_day.get(day))
        monthly = sum(_finite(value) for value in by_day.values())
        monthly += max(0, days - len(by_day)) * self.supply_charge
        cost = result.get("import_cost_today")
        earnings = result.get("export_earnings_today")
        net = round(cost - earnings + daily, 4) if cost is not None and earnings is not None else None
        result.update(daily_supply_charge=round(daily, 4),
                      mtd_supply_charge=round(monthly, 4),
                      supply_charge_days=days, net_cost_today=net)
        result["avg_cost_per_kwh_today"] = (
            round(net / result["load_today_kwh"], 4)
            if net is not None and result.get("avg_cost_per_kwh_today") is not None
            and result.get("load_today_kwh", 0) > 0 else None
        )
        imp, exp = result.get("mtd_import_cost"), result.get("mtd_export_earnings")
        result["avg_cost_per_kwh_mtd"] = (
            round((imp - exp + monthly) / result["mtd_load_kwh"], 4)
            if imp is not None and exp is not None
            and result.get("avg_cost_per_kwh_mtd") is not None
            and result.get("mtd_load_kwh", 0) > 0 else None
        )
        return result


def configure_supply_tracker(hass: Any, entry_id: str, now: datetime,
                             previous: SupplyCostTracker | None, restored: Any) -> SupplyCostTracker:
    entry = hass.config_entries.async_get_entry(entry_id)
    tracker = SupplyCostTracker(
        configured_supply_charge(entry, now),
        previous.state if previous is not None else restored,
    )
    tracker.observe(now)
    return tracker

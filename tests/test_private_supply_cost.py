"""Private Sigenergy site-accounting compatibility for upstream ccf8f688."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from test_energy_accumulator_midnight_persistence import _Clock, _Store, _load_accumulator, _new_accumulator

MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components/power_sync/daily_cost.py"
spec = importlib.util.spec_from_file_location("private_supply_cost", MODULE_PATH)
supply = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = supply
spec.loader.exec_module(supply)


def test_sigenergy_site_cost_keeps_logical_ev_load_separate_and_restores():
    clock = _Clock(datetime(2026, 10, 25, 12, tzinfo=ZoneInfo("Australia/Sydney")))
    entry = SimpleNamespace(data={"daily_supply_charge": 1.2}, options={})
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda key: entry if key == "site" else None))
    accumulator = _new_accumulator(clock, _Store())
    accumulator._supply_cost_tracker = supply.configure_supply_tracker(hass, "site", clock.now(), None, {})
    accumulator.update(0, 3, 0, 1, 0.30, 0.05)  # physical site 3 kW; Home Load excludes EV
    clock.current += timedelta(minutes=5)
    accumulator.update(0, 3, 0, 1, 0.30, 0.05)
    summary = accumulator.as_dict()
    assert summary["import_cost_today"] == pytest.approx(0.075)
    assert summary["net_cost_today"] == pytest.approx(1.275)
    assert summary["avg_cost_per_kwh_today"] == pytest.approx(round(1.275 / summary["load_today_kwh"], 4))
    assert summary["mtd_supply_charge"] == pytest.approx(30)
    asyncio.run(accumulator.async_flush())
    restored = _new_accumulator(clock, accumulator._store)
    asyncio.run(restored.async_restore())
    restored._supply_cost_tracker = supply.configure_supply_tracker(
        hass, "site", clock.now(), None, restored._supply_cost_state,
    )
    assert restored.as_dict()["net_cost_today"] == summary["net_cost_today"]
    assert restored.as_dict()["mtd_supply_charge"] == summary["mtd_supply_charge"]
    # A missing physical-site price cannot become a complete net cost.
    restored.update(0, 3, 0, 1, 0.30, 0.05)  # first post-restart sample integrates nothing
    clock.current += timedelta(minutes=5)
    restored.update(0, 3, 0, 1, None, 0.05)
    assert restored.as_dict()["net_cost_today"] is None


def test_sigenergy_entry_id_activates_only_site_accounting(monkeypatch):
    clock = _Clock(datetime(2026, 10, 25, 12, tzinfo=ZoneInfo("Australia/Sydney")))
    entry = SimpleNamespace(data={"daily_supply_charge": 1.2}, options={})
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: entry))
    monkeypatch.setitem(sys.modules, "custom_components.power_sync.daily_cost", supply)
    accumulator_class = _load_accumulator(clock)
    accumulator_class.update.__globals__["__package__"] = "custom_components.power_sync"
    acc = accumulator_class(hass, entry_id="sigenergy-entry")
    acc.update(0, 0, 0, 1, 0.30, 0.05)
    assert acc.as_dict()["daily_supply_charge"] == 1.2
    assert acc.as_dict()["net_cost_today"] == 1.2
    assert acc.as_dict()["export_earnings_today"] == 0
    assert "export_bonus_today" not in acc.as_dict()


def test_supply_config_and_local_midnight_accounting():
    zone = ZoneInfo("Australia/Sydney")
    first = datetime(2026, 10, 31, 23, 59, tzinfo=zone)
    entry = SimpleNamespace(data={"monthly_supply_charge": 31}, options={})
    assert supply.configured_supply_charge(entry, first) == 1
    entry.options = {"daily_supply_charge": float("nan"), "monthly_supply_charge": float("inf")}
    assert supply.configured_supply_charge(entry, first) == 0
    tracker = supply.SupplyCostTracker(1.2)
    tracker.observe(first)
    clock = _Clock(first)
    accumulator = _new_accumulator(clock)
    accumulator._supply_cost_tracker = tracker
    accumulator.update(0, -6, 0, 1, 0.3, 0.05)
    clock.current = datetime(2026, 11, 1, 0, 1, tzinfo=zone)
    accumulator.update(0, -6, 0, 1, 0.3, 0.05)
    summary = accumulator.as_dict()
    assert summary["grid_export_today_kwh"] == pytest.approx(0.1)
    assert accumulator.mtd_grid_export_kwh == pytest.approx(0.1)
    assert summary["mtd_supply_charge"] == 1.2
    assert summary["supply_charge_days"] == 1

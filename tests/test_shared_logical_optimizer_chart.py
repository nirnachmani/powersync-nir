"""Contracts for logical shared-EV optimizer chart demand."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "custom_components"
    / "power_sync"
    / "automations"
    / "shared_logical_ev_chart.py"
)
SPEC = importlib.util.spec_from_file_location("shared_logical_ev_chart_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

PROFILE_A = "shared_ev_profile_a"
PROFILE_B = "shared_ev_profile_b"
PHYSICAL = "generic_ev"
GRID = (
    "2026-10-16T08:00:00+00:00",
    "2026-10-16T08:05:00+00:00",
)


def _adapt(**overrides):
    kwargs = {
        "selected_profile_id": PROFILE_A,
        "logical_profile_ids": (PROFILE_A, PROFILE_B),
        "physical_loadpoint_id": PHYSICAL,
        "physical_by_vehicle": {PROFILE_A: PHYSICAL, PROFILE_B: PHYSICAL},
        "optimizer_timestamps": GRID,
        "schedule_timestamps": GRID,
        "series_timestamps": GRID,
        "schedule_plan_snapshot_id": "optimizer-plan-1",
        "series_plan_snapshot_id": "optimizer-plan-1",
        "series_by_vehicle_w": {PROFILE_A: (0.0, 7200.0)},
    }
    kwargs.update(overrides)
    return module.logical_optimizer_planned_demand_series(**kwargs)


def test_exactly_aligned_selected_logical_profile_keeps_its_own_series():
    result = _adapt()

    assert result == {
        "vehicle_id": PROFILE_A,
        "timestamps": list(GRID),
        "planned_demand_w": [0.0, 7200.0],
        "plan_snapshot_id": "optimizer-plan-1",
    }


@pytest.mark.parametrize(
    "selected_profile_id,series_by_vehicle_w,expected_vehicle_id",
    [
        (PROFILE_A, {PROFILE_A: (1200.0, 0.0)}, PROFILE_A),
        (PROFILE_B, {PROFILE_B: (0.0, 6400.0)}, PROFILE_B),
        (None, {PROFILE_A: (1200.0, 0.0)}, None),
    ],
)
def test_selector_only_projects_its_sole_logical_contributor(
    selected_profile_id, series_by_vehicle_w, expected_vehicle_id
):
    result = _adapt(
        selected_profile_id=selected_profile_id,
        series_by_vehicle_w=series_by_vehicle_w,
    )

    assert (result or {}).get("vehicle_id") == expected_vehicle_id
    if expected_vehicle_id is None:
        assert result is None


def test_snapshot_mismatch_omits_the_series():
    assert _adapt(series_plan_snapshot_id="older-plan") is None


def test_replaced_optimizer_schedule_omits_a_stale_adopted_series():
    result = module.shared_logical_optimizer_chart_payload(
        adopted_schedule_snapshot_id="solve-1",
        current_schedule_snapshot_id="solve-2",
        **{
            "selected_profile_id": PROFILE_A,
            "logical_profile_ids": (PROFILE_A, PROFILE_B),
            "physical_loadpoint_id": PHYSICAL,
            "physical_by_vehicle": {PROFILE_A: PHYSICAL, PROFILE_B: PHYSICAL},
            "optimizer_timestamps": GRID,
            "schedule_timestamps": GRID,
            "series_timestamps": GRID,
            "plan_snapshot_id": "optimizer-plan-2",
            "series_by_vehicle_w": {PROFILE_A: (0.0, 7200.0)},
        },
    )

    assert result is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("schedule_timestamps", GRID[:1]),
        ("series_timestamps", GRID[:1]),
        ("series_by_vehicle_w", {PROFILE_A: (7200.0,)}),
        (
            "series_timestamps",
            (
                "2026-10-16T08:05:00+00:00",
                "2026-10-16T08:10:00+00:00",
            ),
        ),
    ],
)
def test_unaligned_or_malformed_series_is_omitted_without_truncating_or_shifting(
    field, value
):
    assert _adapt(**{field: value}) is None


@pytest.mark.parametrize("series", [(0.0, "7200"), (0.0, float("nan")), (0.0, -1.0)])
def test_nonfinite_or_invalid_power_values_are_omitted(series):
    assert _adapt(series_by_vehicle_w={PROFILE_A: series}) is None


def test_sibling_or_synthetic_physical_series_is_not_combined_or_relabelled():
    assert _adapt(
        series_by_vehicle_w={
            PROFILE_A: (1200.0, 0.0),
            PROFILE_B: (0.0, 6400.0),
        }
    ) is None
    assert _adapt(
        physical_by_vehicle={
            PROFILE_A: PHYSICAL,
            PROFILE_B: PHYSICAL,
            PHYSICAL: PHYSICAL,
        },
        series_by_vehicle_w={
            PROFILE_A: (1200.0, 0.0),
            PHYSICAL: (0.0, 6400.0),
        },
    ) is None


def test_nonshared_aggregate_input_is_unchanged_and_never_becomes_a_logical_series():
    aggregate = [1200.0, 6400.0]

    result = _adapt(
        selected_profile_id="ordinary-ev",
        physical_by_vehicle={"ordinary-ev": "ordinary-ev"},
        series_by_vehicle_w={"ordinary-ev": aggregate},
    )

    assert result is None
    assert aggregate == [1200.0, 6400.0]


def test_schedule_api_wires_the_checked_logical_series_contract_without_frontend_changes():
    coordinator_source = (
        ROOT / "custom_components" / "power_sync" / "optimization" / "coordinator.py"
    ).read_text()
    api_source = coordinator_source[
        coordinator_source.index("    def get_api_data") : coordinator_source.index(
            "    async def set_settings"
        )
    ]

    assert "shared_logical_optimizer_chart_payload_for_coordinator(" in api_source
    assert 'api_response["logical_ev_planned_demand"]' in api_source

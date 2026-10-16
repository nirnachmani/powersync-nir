"""Read-only Smart Schedule presentation for private logical EV profiles."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "custom_components"
    / "power_sync"
    / "automations"
    / "shared_schedule_presentation.py"
)
SPEC = importlib.util.spec_from_file_location("shared_schedule_presentation_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

NOW = datetime(2026, 10, 16, 8, 30, tzinfo=timezone.utc)
PROFILE_A = "shared_ev_profile_a"
PROFILE_B = "shared_ev_profile_b"


@dataclass
class Window:
    start_time: str
    end_time: str
    source: str = "solar_surplus"


@dataclass
class Plan:
    windows: list[Window]


@dataclass
class State:
    current_plan: Plan | None
    last_plan_update: datetime | None


def _snapshot(profile_id=PROFILE_A, selected_profile_id=PROFILE_A, state=None, now=NOW):
    return module.logical_schedule_snapshot(
        profile_id=profile_id,
        selected_profile_id=selected_profile_id,
        state=state,
        now=now,
    )


def test_selected_profile_projects_active_solar_window_with_advisory_label():
    state = State(
        current_plan=Plan(
            [
                Window(
                    "2026-10-16T19:00:00+10:30",
                    "2026-10-16T20:00:00+10:30",
                )
            ]
        ),
        last_plan_update=datetime(2026, 10, 16, 8, 25, tzinfo=timezone.utc),
    )

    result = _snapshot(state=state)

    assert result["state"] == "active"
    assert result["window_start"] == "2026-10-16T19:00:00+10:30"
    assert result["window_end"] == "2026-10-16T20:00:00+10:30"
    assert result["source"] == "Smart Schedule (solar)"
    assert result["plan_updated_at"] == "2026-10-16T08:25:00+00:00"
    assert result["plan_snapshot_id"]


def test_selected_profile_projects_next_window_across_dst_offset():
    state = State(
        current_plan=Plan(
            [
                Window(
                    "2026-10-04T01:30:00+09:30",
                    "2026-10-04T03:30:00+10:30",
                    "grid_offpeak",
                )
            ]
        ),
        last_plan_update=NOW,
    )

    result = _snapshot(
        state=state,
        now=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert result["state"] == "next"
    assert result["window_start"] == "2026-10-04T01:30:00+09:30"
    assert result["window_end"] == "2026-10-04T03:30:00+10:30"
    assert result["source"] == "Smart Schedule (grid)"


def test_selected_profile_without_plan_reports_no_plan():
    result = _snapshot(state=State(current_plan=None, last_plan_update=None))

    assert result == {
        "state": "no_plan",
        "window_start": None,
        "window_end": None,
        "source": None,
        "plan_updated_at": None,
        "plan_snapshot_id": None,
    }


def test_expired_or_malformed_selected_plan_reports_stale():
    state = State(
        current_plan=Plan(
            [
                Window(
                    (NOW - timedelta(hours=2)).isoformat(),
                    (NOW - timedelta(hours=1)).isoformat(),
                ),
                Window("not-a-timestamp", "also-not-a-timestamp"),
            ]
        ),
        last_plan_update=NOW - timedelta(minutes=1),
    )

    result = _snapshot(state=state)

    assert result["state"] == "stale"
    assert result["window_start"] is None
    assert result["window_end"] is None
    assert result["source"] is None
    assert result["plan_snapshot_id"]


def test_sibling_never_inherits_selected_profiles_window():
    selected_state = State(
        current_plan=Plan(
            [Window("2026-10-16T08:00:00+00:00", "2026-10-16T09:00:00+00:00")]
        ),
        last_plan_update=NOW,
    )

    result = _snapshot(profile_id=PROFILE_B, state=selected_state)

    assert result == {
        "state": "unavailable",
        "window_start": None,
        "window_end": None,
        "source": None,
        "plan_updated_at": None,
        "plan_snapshot_id": None,
    }


def test_unknown_selector_returns_no_identity_derived_schedule():
    state = State(
        current_plan=Plan(
            [Window("2026-10-16T08:00:00+00:00", "2026-10-16T09:00:00+00:00")]
        ),
        last_plan_update=NOW,
    )

    result = _snapshot(selected_profile_id=None, state=state)

    assert result == {
        "state": "unavailable",
        "window_start": None,
        "window_end": None,
        "source": None,
        "plan_updated_at": None,
        "plan_snapshot_id": None,
    }

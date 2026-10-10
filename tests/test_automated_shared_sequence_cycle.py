"""Automated shared command sequences are scoped to one serialized evaluation."""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "powersync_nir"
    / "__init__.py"
)


def _auto_evaluator() -> ast.AsyncFunctionDef:
    setup = next(
        node
        for node in ast.parse(SOURCE.read_text()).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
    )
    return next(
        node
        for node in ast.walk(setup)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "auto_evaluate_automations"
    )


def _unlocked_auto_evaluator() -> ast.AsyncFunctionDef:
    setup = next(
        node
        for node in ast.parse(SOURCE.read_text()).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
    )
    return next(
        node
        for node in ast.walk(setup)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_auto_evaluate_automations_unlocked"
    )


def test_auto_evaluation_serializes_and_cleans_shared_sequence_budget():
    evaluator = _auto_evaluator()
    source = ast.get_source_segment(SOURCE.read_text(), evaluator) or ""

    assert "async with auto_evaluation_lock:" in source
    assert "finally:" in source
    assert "_clear_automated_shared_loadpoint_cycle(hass, entry)" in source
    assert "_begin_automated_shared_loadpoint_cycle(hass, entry)" in SOURCE.read_text()


def test_solar_shared_admission_is_recorded_before_dynamic_start_only_for_selected_candidate():
    """Solar's selected Generic/EVAC decision joins the live cycle ledger."""
    source = ast.get_source_segment(SOURCE.read_text(), _unlocked_auto_evaluator()) or ""

    assert "_preflight_shared_solar_surplus_decision" in source
    assert "_record_automated_shared_loadpoint_decision" in source
    assert 'responsible_mode="solar_surplus"' in source
    assert "selected_shared_profile_id" in source
    assert "selected_shared_loadpoint_id" in source
    assert "vc.get(\"vehicle_id\") == selected_shared_profile_id" in source
    assert "shared_candidate_matches_selected_loadpoint" in source
    assert source.index("_preflight_shared_solar_surplus_decision") < source.index(
        "await _action_start_ev_charging_dynamic(hass, entry, params, context=None)"
    )


def test_solar_periodic_evaluation_does_not_depend_on_previous_cycle_ledger():
    """Cleanup may remove the transient ledger before the next timer callback."""
    source = ast.get_source_segment(SOURCE.read_text(), _unlocked_auto_evaluator()) or ""

    assert "_automated_shared_loadpoint_decision_ledger" not in source


def test_end_of_cycle_external_session_resolution_precedes_shared_cycle_cleanup():
    source = ast.get_source_segment(SOURCE.read_text(), _auto_evaluator()) or ""

    assert "resolve_end_of_cycle_external_shared_session" in source
    assert source.index("resolve_end_of_cycle_external_shared_session") < source.index("_clear_automated_shared_loadpoint_cycle(hass, entry)")

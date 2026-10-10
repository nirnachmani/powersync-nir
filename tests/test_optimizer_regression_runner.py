"""Contract for the reproducible optimizer continuity gate."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "private-fork" / "run_optimizer_regression_tests.sh"


CORE_CORPUS = (
    "tests/test_auto_apply_reserve_relaxed.py",
    "tests/test_cost_neutral_optimizer.py",
    "tests/test_custom_optimizer_telemetry.py",
    "tests/test_ev_plan_clock.py",
    "tests/test_money_event_manager_optimizer_gate.py",
    "tests/test_optimization_enabled_switch.py",
    "tests/test_optimizer_ev_cooptimization.py",
    "tests/test_optimizer_ev_load_plan.py",
    "tests/test_optimizer_hardware_floor_alignment.py",
    "tests/test_optimizer_restore_retry.py",
    "tests/test_profit_max_charge_hold_capabilities.py",
    "tests/test_profit_max_solar_export_guard.py",
    "tests/test_quota_optimizer_constraints.py",
    "tests/test_run_optimization_atomicity.py",
    "tests/test_schedule_soc_export_floor_clamp.py",
    "tests/test_solar_export_hold.py",
    "tests/test_time_window_slots_flooring.py",
    "tests/test_tou_season_boundary_forecast.py",
)


def test_optimizer_continuity_runner_uses_project_venv_and_complete_core_corpus():
    source = RUNNER.read_text(encoding="utf-8")

    assert 'PYTHON="$ROOT/.venv/bin/python"' in source
    assert '"$PYTHON" -m pytest -q' in source
    for test_path in CORE_CORPUS:
        assert test_path in source
    assert "tests/test_home_load_telemetry.py" in source
    assert "tests/test_power_sync_surface_contract.py" in source


def test_private_runner_invokes_optimizer_continuity_gate():
    source = (ROOT / "scripts" / "private-fork" / "run_private_tests.sh").read_text(
        encoding="utf-8"
    )

    assert 'scripts/private-fork/run_optimizer_regression_tests.sh' in source


def test_surface_contract_pins_the_immutable_baseline_and_recurses_symmetrically():
    source = (ROOT / "tests" / "test_power_sync_surface_contract.py").read_text(
        encoding="utf-8"
    )

    assert 'BASELINE_COMMIT = "85f99ea62a174cd9153d5ff2ce71023dda2c9a5c"' in source
    assert "rglob(\"*.py\")" in source
    assert "non-shallow checkout containing tag" in source
    assert "uv pip install --python" in (ROOT / "scripts" / "private-fork" / "run_optimizer_regression_tests.sh").read_text(
        encoding="utf-8"
    )
    assert "import highspy" in (ROOT / "scripts" / "private-fork" / "run_optimizer_regression_tests.sh").read_text(
        encoding="utf-8"
    )

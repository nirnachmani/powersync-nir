#!/usr/bin/env bash
# Run the immutable optimizer continuity corpus in the project virtualenv.
# This is test-only tooling; it does not deploy or modify Home Assistant.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
cd "$ROOT"

if [[ ! -x "$PYTHON" ]]; then
    printf '%s\n' \
        "Missing project virtual environment: $PYTHON" \
        'Create it, then install test dependencies with:' \
        "  uv pip install --python $ROOT/.venv/bin/python -r requirements-test.txt" >&2
    exit 1
fi

if ! "$PYTHON" -c 'import aiohttp; import highspy' >/dev/null 2>&1; then
    printf '%s\n' \
        'Missing required test dependency (aiohttp or highspy).' \
        'Install the declared test dependencies into the project virtual environment:' \
        "  uv pip install --python $PYTHON -r requirements-test.txt" >&2
    exit 1
fi

core_tests=(
    tests/test_auto_apply_reserve_relaxed.py
    tests/test_cost_neutral_optimizer.py
    tests/test_custom_optimizer_telemetry.py
    tests/test_ev_plan_clock.py
    tests/test_money_event_manager_optimizer_gate.py
    tests/test_optimization_enabled_switch.py
    tests/test_optimizer_ev_cooptimization.py
    tests/test_optimizer_ev_load_plan.py
    tests/test_optimizer_hardware_floor_alignment.py
    tests/test_optimizer_restore_retry.py
    tests/test_profit_max_charge_hold_capabilities.py
    tests/test_profit_max_solar_export_guard.py
    tests/test_quota_optimizer_constraints.py
    tests/test_run_optimization_atomicity.py
    tests/test_schedule_soc_export_floor_clamp.py
    tests/test_solar_export_hold.py
    tests/test_time_window_slots_flooring.py
    tests/test_tou_season_boundary_forecast.py
)

printf 'Running optimizer continuity gate: %d core suites plus telemetry and baseline contracts.\n' "${#core_tests[@]}"
"$PYTHON" -m pytest -q \
    "${core_tests[@]}" \
    tests/test_home_load_telemetry.py \
    tests/test_power_sync_surface_contract.py

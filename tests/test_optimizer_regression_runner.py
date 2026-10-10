"""Contract for the reproducible optimizer continuity gate."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


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
    assert '"$PYTHON" -m pytest --version' in source
    assert '"$PYTHON" -m pytest -q' in source
    for test_path in CORE_CORPUS:
        assert test_path in source
    assert "tests/test_home_load_telemetry.py" in source
    assert "tests/test_power_sync_surface_contract.py" in source
    assert "tests/test_optimizer_regression_runner.py" in source


def test_optimizer_gate_test_dependencies_are_exactly_pinned():
    requirements = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")

    assert "aiohttp==3.14.4" in requirements
    assert "cryptography==50.0.2" in requirements
    assert "highspy==1.15.1" in requirements
    assert "pytest==8.4.2" in requirements
    assert "tesla-protocol==4.0.0" in requirements
    assert "aiohttp>=" not in requirements
    assert "cryptography>=" not in requirements
    assert "highspy>=" not in requirements
    assert "pytest>=" not in requirements
    assert "tesla-protocol>=" not in requirements


def test_optimizer_continuity_runner_bootstraps_an_isolated_missing_venv(tmp_path):
    """A clean checkout must bootstrap and use only its own project venv."""
    root = tmp_path / "clean-checkout"
    runner = root / "scripts" / "private-fork" / RUNNER.name
    runner.parent.mkdir(parents=True)
    shutil.copy2(RUNNER, runner)
    (root / "requirements-test.txt").write_text(
        "aiohttp==3.14.4\ncryptography==50.0.2\nhighspy==1.15.1\npytest==8.4.2\ntesla-protocol==4.0.0\n"
    )

    calls = tmp_path / "calls.log"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\\n' "$*" >> "$CALL_LOG"
if [[ "$1" == "venv" ]]; then
    mkdir -p "$2/bin"
    printf '%s\\n' '#!/usr/bin/env bash' 'printf "python %s\\\\n" "$*" >> "$CALL_LOG"' 'exit 0' > "$2/bin/python"
    chmod +x "$2/bin/python"
fi
"""
    )
    fake_uv.chmod(0o755)

    environment = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}", "CALL_LOG": str(calls)}
    result = subprocess.run(
        [str(runner)], cwd=root, env=environment, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "uv venv .venv",
        f"uv pip install --python {root}/.venv/bin/python -r requirements-test.txt",
        "python -c import aiohttp; import cryptography; import highspy; import tesla_protocol",
        "python -m pytest --version",
        "python -m pytest -q tests/test_auto_apply_reserve_relaxed.py tests/test_cost_neutral_optimizer.py tests/test_custom_optimizer_telemetry.py tests/test_ev_plan_clock.py tests/test_money_event_manager_optimizer_gate.py tests/test_optimization_enabled_switch.py tests/test_optimizer_ev_cooptimization.py tests/test_optimizer_ev_load_plan.py tests/test_optimizer_hardware_floor_alignment.py tests/test_optimizer_restore_retry.py tests/test_profit_max_charge_hold_capabilities.py tests/test_profit_max_solar_export_guard.py tests/test_quota_optimizer_constraints.py tests/test_run_optimization_atomicity.py tests/test_schedule_soc_export_floor_clamp.py tests/test_solar_export_hold.py tests/test_time_window_slots_flooring.py tests/test_tou_season_boundary_forecast.py tests/test_home_load_telemetry.py tests/test_power_sync_surface_contract.py tests/test_optimizer_regression_runner.py",
    ]


def test_private_runner_bootstraps_an_isolated_missing_venv(tmp_path):
    """The default private gate must reach the continuity bootstrap on a clean checkout."""
    root = tmp_path / "clean-checkout"
    scripts = root / "scripts" / "private-fork"
    scripts.mkdir(parents=True)
    shutil.copy2(RUNNER, scripts / RUNNER.name)
    shutil.copy2(ROOT / "scripts" / "private-fork" / "run_private_tests.sh", scripts)
    (root / "requirements-test.txt").write_text(
        "aiohttp==3.14.4\ncryptography==50.0.2\nhighspy==1.15.1\npytest==8.4.2\ntesla-protocol==4.0.0\n"
    )

    calls = tmp_path / "private-calls.log"
    fake_bin = tmp_path / "private-fake-bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\\n' "$*" >> "$CALL_LOG"
if [[ "$1" == "venv" ]]; then
    mkdir -p "$2/bin"
    printf '%s\\n' '#!/usr/bin/env bash' 'printf "python %s\\\\n" "$*" >> "$CALL_LOG"' 'exit 0' > "$2/bin/python"
    chmod +x "$2/bin/python"
fi
"""
    )
    fake_uv.chmod(0o755)

    environment = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}", "CALL_LOG": str(calls)}
    result = subprocess.run(
        [str(scripts / "run_private_tests.sh")],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines()[:5] == [
        "uv venv .venv",
        "python scripts/private-fork/validate_local_architecture.py",
        f"uv pip install --python {root}/.venv/bin/python -r requirements-test.txt",
        "python -c import aiohttp; import cryptography; import highspy; import tesla_protocol",
        "python -m pytest --version",
    ]


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
    assert "import cryptography" in (ROOT / "scripts" / "private-fork" / "run_optimizer_regression_tests.sh").read_text(
        encoding="utf-8"
    )
    assert "import tesla_protocol" in (ROOT / "scripts" / "private-fork" / "run_optimizer_regression_tests.sh").read_text(
        encoding="utf-8"
    )
    assert '"$PYTHON" -m pytest --version' in (
        ROOT / "scripts" / "private-fork" / "run_optimizer_regression_tests.sh"
    ).read_text(encoding="utf-8")

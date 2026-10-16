#!/usr/bin/env bash
# Run deterministic private-fork architecture checks and focused contracts.
# This script is intentionally local-only: it does not deploy or modify HA.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
cd "$ROOT"

if [[ ! -x "$PYTHON" ]]; then
    printf 'Bootstrapping project test virtual environment with uv.\n'
    uv venv .venv
fi

if [[ "${1:-}" == "--broader" ]]; then
    if [[ "$#" -ne 1 ]]; then
        printf 'usage: %s [--broader]\n' "$0" >&2
        exit 2
    fi
    broader=1
elif [[ "$#" -eq 0 ]]; then
    broader=0
else
    printf 'usage: %s [--broader]\n' "$0" >&2
    exit 2
fi

"$PYTHON" scripts/private-fork/validate_local_architecture.py
scripts/private-fork/run_optimizer_regression_tests.sh

focused_tests=(
    tests/test_private_architecture_validator.py
    tests/test_private_identity_policy.py
    tests/test_private_fork_upstream_delta.py
    tests/test_maintainer_skill_bootstrap.py
    tests/test_maintainer_cron_installer.py
    tests/test_maintainer_cycle.py
    tests/test_simulated_upstream_maintainer_validation.py
    tests/test_candidate_worktree.py
    tests/test_candidate_integration.py
    tests/test_private_shared_loadpoints.py
    tests/test_shared_loadpoint_binding.py
    tests/test_shared_loadpoint_action_guard.py
    tests/test_shared_loadpoint_cycle_context.py
    tests/test_shared_loadpoint_diagnostics.py
    tests/test_shared_schedule_presentation.py
    tests/test_external_session_reconciler.py
    tests/test_android_app_contract.py
    tests/test_android_app_multi_vehicle_contract.py
)

"$PYTHON" -m pytest -q "${focused_tests[@]}"

if [[ "$broader" -eq 1 ]]; then
    printf '%s\n' \
        'Running the full suite without suppression.' \
        'Known baseline note: three unrelated Tesla/BLE failures may occur; this command reports and returns all failures.'
    "$PYTHON" -m pytest -q tests
fi

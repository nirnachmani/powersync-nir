#!/usr/bin/env bash
# Run deterministic private-fork architecture checks and focused contracts.
# This script is intentionally local-only: it does not deploy or modify HA.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

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

python3 scripts/private-fork/validate_local_architecture.py

focused_tests=(
    tests/test_private_architecture_validator.py
    tests/test_private_fork_upstream_delta.py
    tests/test_maintainer_skill_bootstrap.py
    tests/test_maintainer_cycle.py
    tests/test_candidate_worktree.py
    tests/test_private_shared_loadpoints.py
    tests/test_shared_loadpoint_binding.py
    tests/test_shared_loadpoint_action_guard.py
    tests/test_shared_loadpoint_cycle_context.py
    tests/test_shared_loadpoint_diagnostics.py
    tests/test_external_session_reconciler.py
    tests/test_android_app_contract.py
    tests/test_android_app_multi_vehicle_contract.py
)

pytest -q "${focused_tests[@]}"

if [[ "$broader" -eq 1 ]]; then
    printf '%s\n' \
        'Running the full suite without suppression.' \
        'Known baseline note: three unrelated Tesla/BLE failures may occur; this command reports and returns all failures.'
    pytest -q tests
fi

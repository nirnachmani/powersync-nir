#!/usr/bin/env python3
"""Read-only checks for PowerSync Nir's private shared-loadpoint architecture.

This intentionally uses stable source-level seams rather than importing Home
Assistant. It is deterministic: no network, clock, configuration, or write
operations are used.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable


COMPONENT = Path("custom_components/powersync_nir")
SHARED = COMPONENT / "automations/shared_loadpoint.py"
ACTIONS = COMPONENT / "automations/actions.py"
PLANNER = COMPONENT / "automations/ev_charging_planner.py"
RECONCILER = COMPONENT / "automations/external_session_reconciler.py"
INIT = COMPONENT / "__init__.py"
ANDROID_CONTRACT_TEST = Path("tests/test_android_app_contract.py")
ANDROID_CONTRACT_FIXTURE = Path(
    "tests/contracts/android_app/fixtures/android-1.0.7-336-static-routes.json"
)


def _read(root: Path, relative_path: Path, issues: list[str]) -> str:
    path = root / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        issues.append(f"missing required source: {relative_path}")
        return ""


def _require_all(source: str, relative_path: Path, markers: Iterable[str], issues: list[str], label: str) -> None:
    if source and not all(marker in source for marker in markers):
        issues.append(f"{relative_path}: missing {label}")


def validate_repository(root: Path) -> list[str]:
    """Return deterministic architecture violations for ``root`` without writing."""
    root = Path(root)
    issues: list[str] = []
    shared = _read(root, SHARED, issues)
    actions = _read(root, ACTIONS, issues)
    planner = _read(root, PLANNER, issues)
    reconciler = _read(root, RECONCILER, issues)
    init = _read(root, INIT, issues)

    # Selection is explicit and must fail closed rather than use either profile
    # as a default physical-command identity.
    _require_all(
        shared,
        SHARED,
        ("resolve_active_shared_profile", "resolve_shared_loadpoint_command", "return None"),
        issues,
        "explicit selected-profile resolution",
    )
    if any(pattern in shared for pattern in ("profiles[0]", "profiles [0]", "profiles.get(0)")):
        issues.append(f"{SHARED}: first-profile fallback is forbidden")

    # Every private Generic/EVAC physical command entry boundary resolves through
    # the one guard before hardware-specific work is reached.
    for relative_path, source in ((ACTIONS, actions), (PLANNER, planner), (INIT, init)):
        _require_all(
            source,
            relative_path,
            ("resolve_shared_loadpoint_command",),
            issues,
            "shared command guard for Generic/EVAC physical commands",
        )
    if actions and "_start_generic_charger_switch" in actions and "resolve_shared_loadpoint_command" not in actions:
        issues.append(f"{ACTIONS}: Generic/EVAC command boundary lacks shared command guard")

    # Reconciliation classifies fresh physical evidence and orchestrates injected
    # callbacks. It must not become a hardware dispatcher or mode calculator.
    _require_all(
        reconciler,
        RECONCILER,
        (
            "reconcile_selected_shared_loadpoint_cycle",
            "resolve_end_of_cycle_external_shared_session",
            "reconcile_shared_external_session",
        ),
        issues,
        "reconciliation/override-yield lifecycle",
    )
    dispatcher_markers = ("dispatch_ev_command", "hass.services", ".async_call(")
    if any(marker in reconciler for marker in dispatcher_markers):
        issues.append(f"{RECONCILER}: reconciler must not use a hardware dispatcher")
    mode_calculation_markers = ("calculate_mode", "evaluate_mode", "ChargingMode(")
    if any(marker in reconciler for marker in mode_calculation_markers):
        issues.append(f"{RECONCILER}: reconciliation must not replace mode calculation functions")

    # The released Android client and its private diagnostics route are contract
    # surfaces, so both the test/fixture and registered route are required.
    if not (root / ANDROID_CONTRACT_TEST).is_file() or not (root / ANDROID_CONTRACT_FIXTURE).is_file():
        issues.append("Android contract test and static route fixture must exist")
    _require_all(
        init,
        INIT,
        (
            "class SharedLoadpointDiagnosticsView",
            'url = "/api/power_sync/ev/shared_loadpoints/diagnostics"',
            "requires_auth = True",
        ),
        issues,
        "authenticated shared-loadpoint diagnostic route",
    )
    if init and 'url = "/api/power_sync/ev/shared_loadpoints/diagnostics"' not in init:
        issues.append(f"{INIT}: required shared-loadpoint diagnostic route is missing")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    issues = validate_repository(args.root)
    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1
    print("PASS: private shared-loadpoint architecture invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

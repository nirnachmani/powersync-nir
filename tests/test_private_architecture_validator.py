"""Tests for the read-only private architecture maintenance validator."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/private-fork/validate_local_architecture.py"
SPEC = importlib.util.spec_from_file_location("private_architecture_validator", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _write_fixture(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _valid_fixture(root: Path) -> None:
    _write_fixture(
        root,
        "custom_components/power_sync/automations/shared_loadpoint.py",
        """\ndef resolve_active_shared_profile():\n    return None\n\ndef resolve_shared_loadpoint_command():\n    return None\n""",
    )
    _write_fixture(
        root,
        "custom_components/power_sync/automations/actions.py",
        """\ndef command():\n    resolve_shared_loadpoint_command()\n\ndef ownership():\n    acquire_shared_loadpoint_ownership()\n""",
    )
    _write_fixture(
        root,
        "custom_components/power_sync/automations/ev_charging_planner.py",
        "resolve_shared_loadpoint_command()\n",
    )
    _write_fixture(
        root,
        "custom_components/power_sync/__init__.py",
        """\nresolve_shared_loadpoint_command()\nclass SharedLoadpointDiagnosticsView:\n    url = \"/api/power_sync/ev/shared_loadpoints/diagnostics\"\n    requires_auth = True\n""",
    )
    _write_fixture(
        root,
        "custom_components/power_sync/automations/external_session_reconciler.py",
        """\ndef reconcile_selected_shared_loadpoint_cycle():\n    pass\n\ndef resolve_end_of_cycle_external_shared_session():\n    pass\n\ndef reconcile_shared_external_session():\n    pass\n""",
    )
    _write_fixture(root, "tests/test_android_app_contract.py", "def test_android_contract(): pass\n")
    _write_fixture(
        root,
        "tests/contracts/android_app/fixtures/android-1.0.7-336-static-routes.json",
        "{}\n",
    )


def test_validator_accepts_complete_architecture_fixture(tmp_path):
    _valid_fixture(tmp_path)

    assert validator.validate_repository(tmp_path) == []


def test_validator_rejects_first_profile_fallback(tmp_path):
    _valid_fixture(tmp_path)
    _write_fixture(
        tmp_path,
        "custom_components/power_sync/automations/shared_loadpoint.py",
        "profiles[0]\nresolve_shared_loadpoint_command()\n",
    )

    assert any("first-profile fallback" in issue for issue in validator.validate_repository(tmp_path))


def test_validator_rejects_unguarded_generic_or_evac_command_boundary(tmp_path):
    _valid_fixture(tmp_path)
    _write_fixture(
        tmp_path,
        "custom_components/power_sync/automations/actions.py",
        "async def _start_generic_charger_switch(): pass\n",
    )

    assert any("actions.py" in issue and "shared command guard" in issue for issue in validator.validate_repository(tmp_path))


def test_validator_rejects_reconciler_hardware_dispatcher_coupling(tmp_path):
    _valid_fixture(tmp_path)
    _write_fixture(
        tmp_path,
        "custom_components/power_sync/automations/external_session_reconciler.py",
        "resolve_end_of_cycle_external_shared_session()\nawait dispatch_ev_command()\n",
    )

    assert any("hardware dispatcher" in issue for issue in validator.validate_repository(tmp_path))


def test_validator_rejects_reconciler_mode_calculation_replacement(tmp_path):
    _valid_fixture(tmp_path)
    _write_fixture(
        tmp_path,
        "custom_components/power_sync/automations/external_session_reconciler.py",
        """\ndef reconcile_selected_shared_loadpoint_cycle(): pass\n\ndef resolve_end_of_cycle_external_shared_session(): pass\n\ndef reconcile_shared_external_session(): pass\n\ndef calculate_mode(): pass\n""",
    )

    assert any("mode calculation functions" in issue for issue in validator.validate_repository(tmp_path))


def test_validator_rejects_missing_android_contract_test(tmp_path):
    _valid_fixture(tmp_path)
    (tmp_path / "tests/test_android_app_contract.py").unlink()

    assert any("Android contract test" in issue for issue in validator.validate_repository(tmp_path))


def test_validator_rejects_missing_shared_diagnostics_route(tmp_path):
    _valid_fixture(tmp_path)
    _write_fixture(tmp_path, "custom_components/power_sync/__init__.py", "resolve_shared_loadpoint_command()\n")

    assert any("diagnostic route" in issue for issue in validator.validate_repository(tmp_path))


def test_validator_rejects_no_paywall_paths_and_exact_optimizer_artifacts(tmp_path):
    """Upstream licensing artifacts must not enter the private component."""
    cases = (
        ("custom_components/power_sync/licensing/client.py", "def request(): pass\n", "licensing path"),
        ("custom_components/power_sync/config_flow.py", 'LICENSE_API = "https://api.powersync.cc/ha-license"\n', "hosted licensing API"),
        ("custom_components/power_sync/optimization/coordinator.py", "optimizer_access.check_entitlement()\n", "optimizer access entitlement"),
        ("custom_components/power_sync/optimization/coordinator.py", "optimizer_access.start_pairing()\n", "optimizer entitlement pairing"),
        ("custom_components/power_sync/optimization/coordinator.py", "optimizer_access.finish_pairing()\n", "optimizer entitlement pairing"),
        ("custom_components/power_sync/switch.py", "if subscription_required:\n    return False\n", "subscription-required guard"),
        ("custom_components/power_sync/optimization/battery_controller.py", "controller = LicensedBatteryController()\n", "LicensedBatteryController"),
        ("custom_components/power_sync/optimization/battery_controller.py", "from power_sync.licensing import LicensedBatteryController\n", "licensing import"),
        ("custom_components/power_sync/optimization/battery_controller.py", "from ..licensing import OptimizerAccess\n", "licensing import"),
    )

    for relative_path, content, expected in cases:
        _valid_fixture(tmp_path)
        _write_fixture(tmp_path, relative_path, content)

        assert any(expected in issue for issue in validator.validate_repository(tmp_path))


def test_validator_allows_unrelated_provider_authentication_and_pairing(tmp_path):
    """Provider mechanics are not evidence of an optimizer entitlement paywall."""
    _valid_fixture(tmp_path)
    _write_fixture(
        tmp_path,
        "custom_components/power_sync/providers/powerwall.py",
        """\ndef start_pairing(provider_token):\n    return provider_token\n\ndef finish_pairing(provider_token):\n    return provider_token\n""",
    )

    assert validator.validate_repository(tmp_path) == []

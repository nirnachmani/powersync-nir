"""HA-facing namespace contract for the restored PowerSync component."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "power_sync"
BASELINE = "v2.12.1363"
BASELINE_COMMIT = "85f99ea62a174cd9153d5ff2ce71023dda2c9a5c"
OPTIMIZATION = Path("custom_components/power_sync/optimization")
COORDINATOR = OPTIMIZATION / "coordinator.py"


def _expected_optimizer_coordinator_source() -> str:
    """Return baseline coordinator plus the one reviewed shared-LP guard."""
    baseline = _git_show(BASELINE_COMMIT, COORDINATOR)
    expected = baseline.replace(
        """            from ..automations.ev_charging_planner import (
                get_auto_schedule_executor,
                is_smart_schedule_grid_price_allowed,
            )
            from ..const import DOMAIN
""",
        """            from ..automations.ev_charging_planner import (
                get_auto_schedule_executor,
                is_smart_schedule_grid_price_allowed,
            )
            from ..automations.shared_loadpoint import (
                PROFILE_A_ID,
                PROFILE_B_ID,
                binding_for_entry,
                canonical_shared_loadpoint_id,
                resolve_active_shared_profile,
            )
            from ..const import DOMAIN
""",
        1,
    ).replace(
        """            now = dt_util.now()
            plans = []
            policy_diagnostics: dict[str, dict[str, Any]] = {}
            for vehicle_id, state in (getattr(executor, "_state", {}) or {}).items():
""",
        """            now = dt_util.now()
            plans = []
            policy_diagnostics: dict[str, dict[str, Any]] = {}
            shared_binding = binding_for_entry(executor.config_entry)
            selected_shared_profile = (
                resolve_active_shared_profile(
                    getattr(self, "hass", None), executor.config_entry
                )
                if shared_binding is not None
                else None
            )
            shared_physical_loadpoint = (
                canonical_shared_loadpoint_id(
                    executor.config_entry, PROFILE_A_ID
                )
                if shared_binding is not None
                else None
            )
            for vehicle_id, state in (getattr(executor, "_state", {}) or {}).items():
                if (
                    shared_binding is not None
                    and (
                        vehicle_id == shared_physical_loadpoint
                        or (
                            vehicle_id in (PROFILE_A_ID, PROFILE_B_ID)
                            and vehicle_id != selected_shared_profile
                        )
                    )
                ):
                    # The planner normally clears this at its availability
                    # boundary. Keep this narrow read-side guard for restored
                    # or selector-race state so two logical profiles cannot
                    # reach the LP as one physical Generic/EVAC loadpoint.
                    continue
""",
        1,
    )
    assert expected != baseline
    return expected


def _git(*args: str) -> str:
    """Run git with a direct failure for a checkout missing the baseline tag."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.fail(
            "optimizer continuity baseline requires a non-shallow checkout containing tag "
            f"{BASELINE}",
            pytrace=False,
        )
    if completed.returncode:
        pytest.fail(
            "optimizer continuity baseline requires a non-shallow checkout containing "
            f"tag {BASELINE} at {BASELINE_COMMIT}; git {' '.join(args)!r} failed: "
            f"{completed.stderr.strip() or completed.stdout.strip()}",
            pytrace=False,
        )
    return completed.stdout.replace("\r\n", "\n")


def _git_show(revision: str, relative_path: Path) -> str:
    """Read a tracked baseline source file with normalized newlines."""
    return _git("show", f"{revision}:{relative_path.as_posix()}")


def test_core_optimizer_sources_match_the_pre_rename_baseline():
    """Domain restoration must not alter grid/PV/battery optimizer behavior."""
    assert _git("rev-parse", f"{BASELINE}^{{}}").strip() == BASELINE_COMMIT

    baseline_files = sorted(
        _git("ls-tree", "-r", "--name-only", BASELINE, "--", OPTIMIZATION.as_posix()).splitlines()
    )
    restored_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / OPTIMIZATION).rglob("*.py")
    )

    assert restored_files == baseline_files
    for relative_name in baseline_files:
        relative_path = Path(relative_name)
        actual = (ROOT / relative_path).read_text(encoding="utf-8").replace(
            "\r\n", "\n"
        )
        expected = (
            _expected_optimizer_coordinator_source()
            if relative_path == COORDINATOR
            else _git_show(BASELINE_COMMIT, relative_path)
        )
        assert actual == expected


def test_dashboard_assets_are_served_from_restored_power_sync_namespace():
    """Existing Lovelace resources must keep their original public URLs."""
    init_source = (COMPONENT / "__init__.py").read_text()
    strategy_source = (COMPONENT / "frontend" / "power-sync-strategy.js").read_text()

    assert (COMPONENT / "frontend" / "power-sync-strategy.js").is_file()
    assert (COMPONENT / "frontend" / "power-sync-energy-flow.js").is_file()
    assert 'StaticPathConfig("/power_sync/frontend", frontend_dir, True)' in init_source
    assert 'hass.http.register_static_path("/power_sync/frontend", frontend_dir, True)' in init_source
    assert '"/power_sync/frontend/power-sync-strategy.js"' in init_source
    assert '"/power_sync/frontend/power-sync-energy-flow.js"' in init_source
    assert "service: 'power_sync.force_charge'" in strategy_source
    assert "service: 'power_sync.force_discharge'" in strategy_source
    assert "powersync_nir" not in init_source
    assert "powersync_nir" not in strategy_source

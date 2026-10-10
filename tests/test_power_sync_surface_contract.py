"""HA-facing namespace contract for the restored PowerSync component."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "power_sync"
BASELINE = "v2.12.1363"
OPTIMIZATION = Path("custom_components/power_sync/optimization")


def _git_show(revision: str, relative_path: Path) -> str:
    """Read a tracked baseline source file with normalized newlines."""
    completed = subprocess.run(
        ["git", "show", f"{revision}:{relative_path.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.replace("\r\n", "\n")


def test_core_optimizer_sources_match_the_pre_rename_baseline():
    """Domain restoration must not alter grid/PV/battery optimizer behavior."""
    baseline_files = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", BASELINE, "--", OPTIMIZATION.as_posix()],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    restored_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / OPTIMIZATION).glob("*.py")
    )

    assert restored_files == baseline_files
    for relative_name in baseline_files:
        relative_path = Path(relative_name)
        assert (ROOT / relative_path).read_text().replace("\r\n", "\n") == _git_show(
            BASELINE, relative_path
        )


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

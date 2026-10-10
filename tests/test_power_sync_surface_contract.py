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
        assert (ROOT / relative_path).read_text(encoding="utf-8").replace(
            "\r\n", "\n"
        ) == _git_show(BASELINE_COMMIT, relative_path)


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

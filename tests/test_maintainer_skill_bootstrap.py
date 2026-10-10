"""Tests for the portable maintainer skill bootstrap script and source skill."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/private-fork/install_maintainer_skill.sh"
SOURCE_SKILL = ROOT / "docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md"


def _run_installer(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INSTALLER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_installer_refuses_a_missing_destination_argument():
    completed = _run_installer()

    assert completed.returncode != 0
    assert "Usage:" in completed.stderr


def test_installer_refuses_a_destination_that_is_not_maintainer_profile(tmp_path):
    wrong_profile = tmp_path / "other-profile"
    wrong_profile.mkdir()

    completed = _run_installer(str(wrong_profile))

    assert completed.returncode != 0
    assert "powersync-maintainer" in completed.stderr
    assert not (wrong_profile / "skills").exists()


def test_installer_refuses_the_default_profile_home(tmp_path):
    default_profile = tmp_path / ".hermes"
    default_profile.mkdir()

    completed = _run_installer(str(default_profile))

    assert completed.returncode != 0
    assert "powersync-maintainer" in completed.stderr
    assert not (default_profile / "skills").exists()


def test_installer_copies_skill_only_to_explicit_maintainer_profile(tmp_path):
    maintainer_profile = tmp_path / "powersync-maintainer"
    maintainer_profile.mkdir()

    completed = _run_installer(str(maintainer_profile))

    installed_skill = maintainer_profile / "skills/powersync-private-updates/SKILL.md"
    assert completed.returncode == 0, completed.stderr
    assert installed_skill.read_text(encoding="utf-8") == SOURCE_SKILL.read_text(encoding="utf-8")


def test_skill_requires_separate_authorisation_before_deployment():
    skill = SOURCE_SKILL.read_text(encoding="utf-8").lower()

    assert "deployment" in skill
    assert "separate authorisation" in skill
    assert "never deploy" in skill


def test_private_fork_runner_includes_maintainer_bootstrap_and_cycle_tests():
    runner = (ROOT / "scripts/private-fork/run_private_tests.sh").read_text(encoding="utf-8")

    assert "tests/test_maintainer_skill_bootstrap.py" in runner
    assert "tests/test_maintainer_cycle.py" in runner
    assert "tests/test_maintainer_cron_installer.py" in runner

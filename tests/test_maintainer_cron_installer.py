"""Safety and invocation tests for the portable paused maintainer-cron installer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/private-fork/install_maintainer_cron.sh"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    repo = tmp_path / "private-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:example/powersync-private.git"], cwd=repo, check=True)

    profile = tmp_path / "profiles" / "powersync-maintainer"
    skill = profile / "skills" / "powersync-private-updates"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# installed fixture skill\n", encoding="utf-8")
    reports = profile / "reports"
    reports.mkdir()
    state = profile / "state" / "review.json"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "hermes.log"
    _write_executable(
        bin_dir / "hermes",
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HERMES_LOG\"\n"
        "if [ \"$3 $4 $5\" = \"cron list --all\" ]; then printf '%s\\n' \"${HERMES_LIST_OUTPUT:-}\"; fi\n",
    )
    _write_executable(
        bin_dir / "gh",
        "#!/bin/sh\nprintf '%s\\n' \"${GH_VISIBILITY:-PRIVATE}\"\n",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HERMES_LOG": str(log),
        "GH_VISIBILITY": "PRIVATE",
    }
    return repo, profile, state, env


def _run(tmp_path: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INSTALLER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _valid_args(repo: Path, profile: Path, state: Path) -> list[str]:
    return [
        "--repo", str(repo),
        "--profile-home", str(profile),
        "--state", str(state),
        "--reports-dir", str(profile / "reports"),
    ]


def test_refuses_without_apply_and_never_calls_hermes(tmp_path):
    repo, profile, state, env = _fixture(tmp_path)

    completed = _run(tmp_path, *_valid_args(repo, profile, state), env=env)

    assert completed.returncode != 0
    assert "--apply" in completed.stderr
    assert not Path(env["HERMES_LOG"]).exists()


def test_dry_run_validates_and_prints_exact_resume_command_without_scheduler_change(tmp_path):
    repo, profile, state, env = _fixture(tmp_path)

    completed = _run(tmp_path, "--dry-run", *_valid_args(repo, profile, state), env=env)

    assert completed.returncode == 0, completed.stderr
    assert "hermes --profile powersync-maintainer cron resume powersync-private-upstream-review" in completed.stdout
    assert "hermes --profile powersync-maintainer cron create 3d" in completed.stdout
    assert not Path(env["HERMES_LOG"]).exists()


def test_apply_creates_one_paused_local_report_only_job_with_fixed_workdir(tmp_path):
    repo, profile, state, env = _fixture(tmp_path)

    completed = _run(tmp_path, "--apply", *_valid_args(repo, profile, state), env=env)

    assert completed.returncode == 0, completed.stderr
    invocation = Path(env["HERMES_LOG"]).read_text(encoding="utf-8")
    assert invocation.count("cron create") == 1
    assert "--profile powersync-maintainer cron create 3d" in invocation
    assert "--name powersync-private-upstream-review" in invocation
    assert "--skill powersync-private-updates" in invocation
    assert f"--workdir {repo.resolve()}" in invocation
    assert "--deliver local --failure-deliver local" in invocation
    assert "--paused" in invocation
    assert "maintainer_cycle.py" in invocation
    assert "--state " + str(state.resolve()) in invocation
    assert "--report-json " + str((profile / "reports/latest.json").resolve()) in invocation
    assert "--report-markdown " + str((profile / "reports/latest.md").resolve()) in invocation
    assert " cron resume " not in invocation


def test_refuses_an_existing_active_job_before_create(tmp_path):
    repo, profile, state, env = _fixture(tmp_path)
    env["HERMES_LIST_OUTPUT"] = "job-1 [active]\n    Name:      powersync-private-upstream-review"

    completed = _run(tmp_path, "--apply", *_valid_args(repo, profile, state), env=env)

    assert completed.returncode != 0
    assert "active" in completed.stderr.lower()
    invocation = Path(env["HERMES_LOG"]).read_text(encoding="utf-8")
    assert "cron list --all" in invocation
    assert "cron create" not in invocation


def test_refuses_default_or_wrong_profile_and_paths_outside_profile_boundary(tmp_path):
    repo, profile, state, env = _fixture(tmp_path)
    wrong_profile = tmp_path / "profiles" / "default"
    wrong_profile.mkdir()

    completed = _run(tmp_path, "--dry-run", "--repo", str(repo), "--profile-home", str(wrong_profile), "--state", str(state), "--reports-dir", str(profile / "reports"), env=env)
    assert completed.returncode != 0
    assert "powersync-maintainer" in completed.stderr

    outside = tmp_path / "outside.json"
    completed = _run(tmp_path, "--dry-run", "--repo", str(repo), "--profile-home", str(profile), "--state", str(outside), "--reports-dir", str(profile / "reports"), env=env)
    assert completed.returncode != 0
    assert "profile-home boundary" in completed.stderr


def test_refuses_non_private_origin_and_missing_installed_skill(tmp_path):
    repo, profile, state, env = _fixture(tmp_path)
    env["GH_VISIBILITY"] = "PUBLIC"

    completed = _run(tmp_path, "--dry-run", *_valid_args(repo, profile, state), env=env)
    assert completed.returncode != 0
    assert "private" in completed.stderr.lower()

    env["GH_VISIBILITY"] = "PRIVATE"
    (profile / "skills/powersync-private-updates/SKILL.md").unlink()
    completed = _run(tmp_path, "--dry-run", *_valid_args(repo, profile, state), env=env)
    assert completed.returncode != 0
    assert "powersync-private-updates" in completed.stderr

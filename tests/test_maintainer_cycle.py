"""Behavioral and safety tests for the read-only maintainer review cycle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "scripts/private-fork/maintainer_cycle.py"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def _commit(repo: Path, filename: str, contents: str, message: str) -> str:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def upstream_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    inventory = repo / "docs/private-fork/local-change-inventory.md"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("# Fixture inventory\n", encoding="utf-8")
    baseline = _commit(repo, "README.md", "base\n", "base")
    target = _commit(repo, "README.md", "target\n", "target")
    remote = tmp_path / "upstream.git"
    _git(tmp_path, "init", "--bare", "-q", str(remote))
    _git(repo, "remote", "add", "upstream", str(remote))
    return repo, baseline, target


def _run_cycle(
    repo: Path,
    baseline: str,
    target: str,
    state: Path,
    report_json: Path,
    report_markdown: Path,
    *extra: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CYCLE),
            "--repo",
            str(repo),
            "--upstream-remote",
            "upstream",
            "--baseline",
            baseline,
            "--target",
            target,
            "--report-state",
            str(state),
            "--report-json",
            str(report_json),
            "--report-markdown",
            str(report_markdown),
            *extra,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_fresh_run_writes_deterministic_reports_and_review_state(upstream_repo, tmp_path):
    repo, baseline, target = upstream_repo
    state = tmp_path / "state/review.json"
    report_json = tmp_path / "reports/review.json"
    report_markdown = tmp_path / "reports/review.md"

    completed = _run_cycle(repo, baseline, target, state, report_json, report_markdown)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_json.read_text(encoding="utf-8"))
    saved_state = json.loads(state.read_text(encoding="utf-8"))
    assert report["classification"] == "no-overlap"
    assert report["requires_candidate"] is True
    assert report["action"] == "report-only"
    assert report["delta"]["baseline"]["resolved"] == baseline
    assert saved_state["reviewed_range"] == {
        "baseline": baseline,
        "target": target,
        "classification": "no-overlap",
    }
    assert "Deployment: forbidden" in report_markdown.read_text(encoding="utf-8")


def test_no_delta_is_reported_without_a_candidate(upstream_repo, tmp_path):
    repo, baseline, _target = upstream_repo
    state = tmp_path / "state.json"
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"

    completed = _run_cycle(repo, baseline, baseline, state, report_json, report_markdown)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["delta"]["commits"] == []
    assert report["classification"] == "no-overlap"
    assert report["requires_candidate"] is False


def test_malformed_existing_state_fails_without_replacing_it(upstream_repo, tmp_path):
    repo, baseline, target = upstream_repo
    state = tmp_path / "state.json"
    state.write_text("not json", encoding="utf-8")
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"

    completed = _run_cycle(repo, baseline, target, state, report_json, report_markdown)

    assert completed.returncode != 0
    assert "state" in completed.stderr.lower()
    assert state.read_text(encoding="utf-8") == "not json"
    assert not report_json.exists()
    assert not report_markdown.exists()


def test_missing_upstream_reference_fails_without_writing_artifacts(upstream_repo, tmp_path):
    repo, baseline, _target = upstream_repo
    state = tmp_path / "state.json"
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"

    completed = _run_cycle(repo, baseline, "upstream/missing", state, report_json, report_markdown)

    assert completed.returncode != 0
    assert "target" in completed.stderr.lower()
    assert not state.exists()
    assert not report_json.exists()
    assert not report_markdown.exists()


def test_report_cycle_refuses_to_overwrite_a_maintainer_ledger(upstream_repo, tmp_path):
    repo, baseline, target = upstream_repo
    state = tmp_path / "maintainer_ledger.json"
    ledger = {
        "schema_version": 1,
        "checkpoint": baseline,
        "migration": {"boundary": "v2.12.1418", "references": ["legacy backup"]},
        "entries": [],
    }
    state.write_text(json.dumps(ledger), encoding="utf-8")
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"

    completed = _run_cycle(repo, baseline, target, state, report_json, report_markdown)

    assert completed.returncode != 0
    assert "ledger" in completed.stderr.lower()
    assert json.loads(state.read_text(encoding="utf-8")) == ledger
    assert not report_json.exists()
    assert not report_markdown.exists()


def test_fetch_is_never_run_without_explicit_flag_and_runs_only_with_it(upstream_repo, tmp_path):
    repo, baseline, target = upstream_repo
    log = tmp_path / "git.log"
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$GIT_CALL_LOG\"\nexec \"$REAL_GIT\" \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = {**os.environ, "PATH": f"{wrapper_dir}:{os.environ['PATH']}", "GIT_CALL_LOG": str(log), "REAL_GIT": _git_path()}
    paths = [tmp_path / name for name in ("state.json", "report.json", "report.md")]

    completed = _run_cycle(repo, baseline, target, *paths, env=env)
    assert completed.returncode == 0, completed.stderr
    assert not any(line.startswith("fetch ") for line in log.read_text(encoding="utf-8").splitlines())

    log.unlink()
    completed = _run_cycle(repo, baseline, target, *paths, "--fetch", env=env)
    assert completed.returncode == 0, completed.stderr
    assert log.read_text(encoding="utf-8").splitlines().count("fetch upstream") == 1


def _git_path() -> str:
    return subprocess.run(["sh", "-c", "command -v git"], text=True, capture_output=True, check=True).stdout.strip()


def test_cycle_and_cron_spec_forbid_mutating_git_home_assistant_and_deployment_commands():
    source = CYCLE.read_text(encoding="utf-8").lower()
    cron_spec = (ROOT / "docs/private-fork/maintainer-cycle-cron-spec.md").read_text(encoding="utf-8").lower()

    for forbidden in (" merge", " rebase", " cherry-pick", " push", " tag", "homeassistant", "ha core", "docker restart"):
        assert forbidden not in source
    assert "--fetch" in source
    assert "every 3 days" in cron_spec
    assert "jitter" in cron_spec
    assert "deployment" in cron_spec
    assert "forbid" in cron_spec


def test_cron_spec_keeps_legacy_upstream_state_and_ledger_state_separate():
    cron_spec = (ROOT / "docs/private-fork/maintainer-cycle-cron-spec.md").read_text(encoding="utf-8")

    assert "maintainer_ledger.json" in cron_spec
    assert "upstream.json" in cron_spec
    assert "maintainer_cycle.py" in cron_spec
    assert "--report-state" in cron_spec

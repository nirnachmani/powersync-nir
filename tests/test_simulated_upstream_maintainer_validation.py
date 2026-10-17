"""Deterministic local simulations of the private-fork maintainer safety path."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "scripts/private-fork/maintainer_cycle.py"
PREPARE = ROOT / "scripts/private-fork/candidate_worktree.py"
INTEGRATE = ROOT / "scripts/private-fork/integrate_candidate.py"
PRIVATE_ORIGIN = "git@github.com:nirnachmani/powersync-nir.git"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


def _commit(repo: Path, path: str, contents: str, message: str) -> str:
    destination = repo / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contents, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _new_repo(tmp_path: Path, inventory: str) -> tuple[Path, str]:
    repo = tmp_path / "private"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Simulation")
    _git(repo, "remote", "add", "origin", PRIVATE_ORIGIN)
    _git(repo, "remote", "add", "upstream", str(tmp_path / "upstream.git"))
    _git(tmp_path, "init", "--bare", "-q", str(tmp_path / "upstream.git"))
    _commit(repo, "docs/private-fork/local-change-inventory.md", inventory, "inventory")
    _commit(repo, "deploy-state.json", '{"deployed":"source"}\n', "deploy sentinel")
    _commit(repo, "scripts/private-fork/validate_local_architecture.py", "print('architecture gate')\n", "add architecture gate")
    _commit(repo, "scripts/private-fork/run_private_tests.sh", "#!/bin/sh\nexit 0\n", "add focused runner")
    _git(repo, "update-index", "--chmod=+x", "scripts/private-fork/run_private_tests.sh")
    (repo / "scripts/private-fork/run_private_tests.sh").chmod(0o755)
    _git(repo, "commit", "-m", "make focused runner executable")
    return repo, _git(repo, "rev-parse", "HEAD")


def _run_cycle(repo: Path, baseline: str, target: str, artifacts: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable, str(CYCLE), "--repo", str(repo), "--upstream-remote", "upstream",
            "--baseline", baseline, "--target", target,
            "--report-state", str(artifacts / "state.json"),
            "--report-json", str(artifacts / "report.json"),
            "--report-markdown", str(artifacts / "report.md"),
        ],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def _source_snapshot(repo: Path) -> tuple[str, str, str]:
    return (
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        (repo / "deploy-state.json").read_text(encoding="utf-8"),
    )


def _prepare_and_integrate(repo: Path, source: str, target: str, artifacts: Path) -> subprocess.CompletedProcess[str]:
    manifest = artifacts / "candidate.json"
    candidate_root = artifacts / "candidates"
    prepared = subprocess.run(
        [
            sys.executable, str(PREPARE), "prepare", "--private-repo", str(repo),
            "--candidate-root", str(candidate_root), "--private-source-ref", source,
            "--upstream-target-ref", target, "--manifest", str(manifest),
        ], cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    candidate = json.loads(manifest.read_text(encoding="utf-8"))["candidate_worktree"]
    return subprocess.run(
        [
            sys.executable, str(INTEGRATE), "--manifest", str(manifest),
            "--candidate-worktree", candidate, "--upstream-target-ref", target,
            "--classification", "no_overlap", "--report", str(artifacts / "candidate-report.txt"),
        ], cwd=ROOT, text=True, capture_output=True, check=False,
    )


@pytest.mark.parametrize("path, contents", [("docs/upstream.md", "documentation only\n"), ("tests/test_upstream_only.py", "def test_upstream_only():\n    assert True\n")])
def test_no_overlap_documentation_and_test_only_deltas_merge_only_a_candidate(tmp_path: Path, path: str, contents: str):
    repo, baseline = _new_repo(tmp_path, "# inventory\n`private/module.py`\n")
    target = _commit(repo, path, contents, "upstream no-overlap")
    _git(repo, "reset", "--hard", baseline)
    before = _source_snapshot(repo)
    artifacts = tmp_path / "artifacts"

    reviewed = _run_cycle(repo, baseline, target, artifacts)
    integrated = _prepare_and_integrate(repo, baseline, target, artifacts)

    assert reviewed.returncode == 0, reviewed.stderr
    assert json.loads((artifacts / "report.json").read_text(encoding="utf-8"))["classification"] == "no-overlap"
    assert integrated.returncode == 0, integrated.stderr
    assert _source_snapshot(repo) == before
    assert "Result: passed" in (artifacts / "candidate-report.txt").read_text(encoding="utf-8")


def test_external_session_overlap_is_compatible_and_requires_human_resolution_without_source_mutation(tmp_path: Path):
    inventory = "# inventory\n`private/external_session.py`\n"
    repo, baseline = _new_repo(tmp_path, inventory)
    _commit(repo, "private/external_session.py", "def reconcile_external_session(mode='base'):\n    return mode\n", "private external session")
    baseline = _git(repo, "rev-parse", "HEAD")
    target = _commit(repo, "private/external_session.py", "def reconcile_external_session(mode='upstream'):\n    return mode\n", "upstream external session")
    _commit(repo, "tests/test_upstream_external.py", "def test_upstream_external():\n    assert True\n", "upstream evidence")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--hard", baseline)
    before = _source_snapshot(repo)

    completed = _run_cycle(repo, baseline, target, tmp_path / "artifacts")

    report = json.loads((tmp_path / "artifacts/report.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, completed.stderr
    assert report["classification"] == "compatible"
    assert report["requires_candidate"] is True
    assert report["classifier"]["classification"] == "compatible-semantic-overlap"
    assert _source_snapshot(repo) == before


def test_redundant_private_coverage_is_recorded_without_a_candidate(tmp_path: Path):
    inventory = "# inventory\n`private/coverage.py`\n`tests/test_private_coverage.py`\n"
    repo, baseline = _new_repo(tmp_path, inventory)
    _commit(repo, "private/coverage.py", "def covered_behavior(mode='base'):\n    return mode\n", "private behavior")
    _commit(repo, "tests/test_private_coverage.py", "def test_covered_behavior():\n    assert True\n", "private coverage")
    baseline = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "private/coverage.py", "def covered_behavior(mode='upstream'):\n    return mode\n", "upstream behavior")
    target = _commit(repo, "tests/test_private_coverage.py", "def test_covered_behavior():\n    assert 'upstream' == 'upstream'\n", "upstream coverage")
    _git(repo, "reset", "--hard", baseline)
    before = _source_snapshot(repo)

    completed = _run_cycle(repo, baseline, target, tmp_path / "artifacts")

    report = json.loads((tmp_path / "artifacts/report.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, completed.stderr
    assert report["classification"] == "redundant"
    assert report["requires_candidate"] is False
    assert report["classifier"]["classification"] == "redundant-private-coverage"
    assert _source_snapshot(repo) == before


@pytest.mark.parametrize("path", ["private/config.py", "private/ownership.py"])
def test_deleted_private_config_or_ownership_symbol_is_held_as_incompatible(tmp_path: Path, path: str):
    inventory = f"# inventory\n`{path}`\n"
    repo, baseline = _new_repo(tmp_path, inventory)
    _commit(repo, path, "def private_guard():\n    return True\n", "private guard")
    baseline = _git(repo, "rev-parse", "HEAD")
    _commit(repo, path, "", "upstream removes private guard")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--hard", baseline)
    before = _source_snapshot(repo)

    completed = _run_cycle(repo, baseline, target, tmp_path / "artifacts")

    report = json.loads((tmp_path / "artifacts/report.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, completed.stderr
    assert report["classification"] == "incompatible"
    assert report["requires_candidate"] is False
    assert report["classifier"]["classification"] == "incompatible-semantic-conflict"
    assert _source_snapshot(repo) == before


def test_failed_gate_candidate_is_not_promoted_and_interrupted_cycle_leaves_state_for_resume(tmp_path: Path):
    repo, baseline = _new_repo(tmp_path, "# inventory\n`private/module.py`\n")
    _commit(repo, "scripts/private-fork/run_private_tests.sh", "#!/bin/sh\nexit 1\n", "upstream breaks gate")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--hard", baseline)
    before = _source_snapshot(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prior_state = '{"reviewed_range":{"target":"previous"}}\n'
    (artifacts / "state.json").write_text(prior_state, encoding="utf-8")

    interrupted = _run_cycle(repo, baseline, "missing-target", artifacts)
    assert interrupted.returncode != 0
    assert (artifacts / "state.json").read_text(encoding="utf-8") == prior_state
    resumed = _run_cycle(repo, baseline, target, artifacts)
    integrated = _prepare_and_integrate(repo, baseline, target, artifacts)
    assert resumed.returncode == 0, resumed.stderr
    assert integrated.returncode != 0
    assert _source_snapshot(repo) == before
    assert (artifacts / "candidate-report.txt").exists(), integrated.stderr
    assert "gates failed" in (artifacts / "candidate-report.txt").read_text(encoding="utf-8")


def test_focused_runner_and_validation_template_include_the_simulated_coverage():
    runner = (ROOT / "scripts/private-fork/run_private_tests.sh").read_text(encoding="utf-8")
    template = ROOT / "docs/private-fork/simulated-upstream-validation-report-template.md"

    assert "tests/test_simulated_upstream_maintainer_validation.py" in runner
    assert template.is_file()
    text = template.read_text(encoding="utf-8")
    assert "Source checkout/deploy state" in text
    assert "Interrupted/resumed" in text

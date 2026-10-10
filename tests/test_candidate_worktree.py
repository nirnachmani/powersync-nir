"""Safety tests for disposable private-fork candidate worktree preparation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/private-fork/candidate_worktree.py"
PRIVATE_ORIGIN = "git@github.com:nirnachmani/powersync-nir.git"
PUBLIC_ORIGIN = "https://github.com/PowerSync/powersync.git"


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


@pytest.fixture
def private_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "private"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    source = _commit(repo, "private.txt", "private source\n", "private source")
    target = _commit(repo, "upstream.txt", "upstream target\n", "upstream target")
    _git(repo, "remote", "add", "origin", PRIVATE_ORIGIN)
    return repo, source, target


def _prepare(
    repo: Path, candidate_root: Path, source: str, target: str, manifest: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--private-repo",
            str(repo),
            "--candidate-root",
            str(candidate_root),
            "--private-source-ref",
            source,
            "--upstream-target-ref",
            target,
            "--manifest",
            str(manifest),
            *extra,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _cleanup(repo: Path, candidate_root: Path, worktree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "cleanup",
            "--private-repo",
            str(repo),
            "--candidate-root",
            str(candidate_root),
            "--worktree",
            str(worktree),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_prepare_creates_isolated_detached_candidate_and_atomic_manifest(private_repo, tmp_path):
    repo, source, target = private_repo
    candidate_root = tmp_path / "candidates"
    manifest = tmp_path / "artifacts/candidate.json"

    completed = _prepare(repo, candidate_root, source, target, manifest)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    worktree = Path(saved["candidate_worktree"])
    assert saved == result
    assert saved["private_source"]["resolved"] == source
    assert saved["upstream_target"]["resolved"] == target
    assert saved["classification"] == "candidate-prepared-no-integration"
    assert saved["integration"] == "not-performed"
    assert worktree.is_relative_to(candidate_root.resolve())
    assert worktree.is_dir()
    assert _git(worktree, "rev-parse", "HEAD") == source
    assert subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=worktree, capture_output=True
    ).returncode != 0
    assert _git(repo, "rev-parse", "HEAD") == target
    assert not list(manifest.parent.glob(f".{manifest.name}.*.tmp"))


def test_prepare_rejects_dirty_private_source_without_creating_artifacts(private_repo, tmp_path):
    repo, source, target = private_repo
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    candidate_root = tmp_path / "candidates"
    manifest = tmp_path / "manifest.json"

    completed = _prepare(repo, candidate_root, source, target, manifest)

    assert completed.returncode != 0
    assert "clean" in completed.stderr.lower()
    assert not candidate_root.exists()
    assert not manifest.exists()


def test_prepare_rejects_public_origin_without_creating_worktree(private_repo, tmp_path):
    repo, source, target = private_repo
    _git(repo, "remote", "set-url", "origin", PUBLIC_ORIGIN)
    candidate_root = tmp_path / "candidates"
    manifest = tmp_path / "manifest.json"

    completed = _prepare(repo, candidate_root, source, target, manifest)

    assert completed.returncode != 0
    assert "origin" in completed.stderr.lower()
    assert not candidate_root.exists()
    assert not manifest.exists()


def test_prepare_requires_explicit_private_origin_policy_for_other_private_repository(private_repo, tmp_path):
    repo, source, target = private_repo
    _git(repo, "remote", "set-url", "origin", "https://github.com:443/example/private-fork.git")
    candidate_root = tmp_path / "candidates"
    manifest = tmp_path / "manifest.json"

    rejected = _prepare(repo, candidate_root, source, target, manifest)
    accepted = _prepare(
        repo,
        candidate_root,
        source,
        target,
        manifest,
        "--private-owner-repo",
        "example/private-fork",
    )

    assert rejected.returncode != 0
    assert accepted.returncode == 0, accepted.stderr


def test_prepare_failure_after_worktree_creation_cleans_the_disposable_candidate(private_repo, tmp_path):
    repo, source, target = private_repo
    candidate_root = tmp_path / "candidates"
    manifest = tmp_path / "manifest-parent-is-a-file"
    manifest.write_text("block directory creation", encoding="utf-8")
    requested_worktree = candidate_root / "known-candidate"

    completed = _prepare(
        repo,
        candidate_root,
        source,
        target,
        manifest / "candidate.json",
        "--candidate-name",
        requested_worktree.name,
    )

    assert completed.returncode != 0
    assert "traceback" not in completed.stderr.lower()
    assert not requested_worktree.exists()
    assert not list(candidate_root.glob("*")) if candidate_root.exists() else True


def test_cleanup_rejects_path_outside_candidate_root(private_repo, tmp_path):
    repo, _source, _target = private_repo
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    completed = _cleanup(repo, candidate_root, outside)

    assert completed.returncode != 0
    assert outside.is_dir()


def test_cleanup_removes_only_an_explicit_registered_candidate(private_repo, tmp_path):
    repo, source, target = private_repo
    candidate_root = tmp_path / "candidates"
    manifest = tmp_path / "manifest.json"
    prepared = _prepare(repo, candidate_root, source, target, manifest)
    assert prepared.returncode == 0, prepared.stderr
    worktree = Path(json.loads(manifest.read_text(encoding="utf-8"))["candidate_worktree"])

    completed = _cleanup(repo, candidate_root, worktree)

    assert completed.returncode == 0, completed.stderr
    assert not worktree.exists()
    assert _git(repo, "rev-parse", "HEAD") == target


def test_focused_runner_and_policy_document_candidate_preparation():
    runner = (ROOT / "scripts/private-fork/run_private_tests.sh").read_text(encoding="utf-8")
    policy = (ROOT / "docs/private-fork/upstream-update-policy.md").read_text(encoding="utf-8")

    assert "tests/test_candidate_worktree.py" in runner
    assert "candidate_worktree.py" in policy
    assert "cleanup" in policy.lower()

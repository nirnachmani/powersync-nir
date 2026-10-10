"""Safety tests for isolated no-overlap candidate integration."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts/private-fork/candidate_worktree.py"
SCRIPT = ROOT / "scripts/private-fork/integrate_candidate.py"
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
def candidate(tmp_path: Path) -> tuple[Path, Path, Path, Path, str]:
    repo = tmp_path / "private"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    _git(repo, "remote", "add", "origin", PRIVATE_ORIGIN)
    _commit(repo, "private.txt", "private\n", "private base")
    _commit(repo, "scripts/private-fork/validate_local_architecture.py", "print('architecture gate')\n", "add gate")
    _commit(repo, "scripts/private-fork/run_private_tests.sh", "#!/bin/sh\nexit 0\n", "add runner")
    _git(repo, "update-index", "--chmod=+x", "scripts/private-fork/run_private_tests.sh")
    _git(repo, "commit", "-m", "make runner executable")
    source = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "upstream.txt", "upstream\n", "upstream target")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--hard", source)
    candidate_root = tmp_path / "candidates"
    manifest = tmp_path / "candidate.json"
    prepared = subprocess.run(
        [sys.executable, str(PREPARE), "prepare", "--private-repo", str(repo), "--candidate-root", str(candidate_root), "--private-source-ref", source, "--upstream-target-ref", target, "--manifest", str(manifest)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    worktree = Path(json.loads(manifest.read_text(encoding="utf-8"))["candidate_worktree"])
    return repo, worktree, manifest, tmp_path / "report.txt", target


def _run(manifest: Path, worktree: Path, target: str, report: Path, classification: str = "no_overlap") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(manifest), "--candidate-worktree", str(worktree), "--upstream-target-ref", target, "--classification", classification, "--report", str(report)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def test_no_overlap_merges_and_commits_only_the_registered_candidate(candidate):
    repo, worktree, manifest, report, target = candidate
    source = _git(repo, "rev-parse", "HEAD")

    completed = _run(manifest, worktree, target, report)

    assert completed.returncode == 0, completed.stderr
    assert _git(repo, "rev-parse", "HEAD") == source
    assert _git(worktree, "rev-parse", "HEAD") != source
    assert _git(worktree, "show", "HEAD:upstream.txt") == "upstream"
    assert "Classification: no_overlap" in report.read_text(encoding="utf-8")
    assert "Commit/candidate: " in report.read_text(encoding="utf-8")


def test_overlap_never_merges_and_reports_human_resolution(candidate):
    repo, worktree, manifest, report, target = candidate
    before = _git(worktree, "rev-parse", "HEAD")

    completed = _run(manifest, worktree, target, report, "mechanical_overlap")

    assert completed.returncode != 0
    assert _git(worktree, "rev-parse", "HEAD") == before
    text = report.read_text(encoding="utf-8")
    assert "compatible-resolution" in text
    assert "Commit/candidate: not created" in text


def test_conflicting_merge_aborts_candidate_without_mutating_source(candidate):
    repo, worktree, manifest, report, target = candidate
    _git(repo, "worktree", "remove", "--force", str(worktree))
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "conflict.txt", "private\n", "private conflict")
    source = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "upstream-test", base)
    _git(repo, "checkout", "-q", "upstream-test")
    _commit(repo, "conflict.txt", "upstream\n", "upstream conflict")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "master")
    assert _git(repo, "rev-parse", "HEAD") == source
    candidate_root = worktree.parent
    prepared = subprocess.run(
        [sys.executable, str(PREPARE), "prepare", "--private-repo", str(repo), "--candidate-root", str(candidate_root), "--private-source-ref", source, "--upstream-target-ref", target, "--manifest", str(manifest)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    worktree = Path(json.loads(manifest.read_text(encoding="utf-8"))["candidate_worktree"])

    completed = _run(manifest, worktree, target, report)

    assert completed.returncode != 0
    assert _git(repo, "rev-parse", "HEAD") == source
    assert _git(worktree, "rev-parse", "HEAD") == source
    assert not (worktree / ".git" / "MERGE_HEAD").exists()
    assert "merge failed" in report.read_text(encoding="utf-8")


def test_gate_failure_resets_candidate_and_creates_no_commit(candidate):
    repo, worktree, manifest, report, target = candidate
    _git(repo, "worktree", "remove", "--force", str(worktree))
    source = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "scripts/private-fork/run_private_tests.sh", "#!/bin/sh\nexit 1\n", "break gate upstream")
    target = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--hard", source)
    prepared = subprocess.run(
        [sys.executable, str(PREPARE), "prepare", "--private-repo", str(repo), "--candidate-root", str(worktree.parent), "--private-source-ref", source, "--upstream-target-ref", target, "--manifest", str(manifest)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    worktree = Path(json.loads(manifest.read_text(encoding="utf-8"))["candidate_worktree"])
    before = _git(worktree, "rev-parse", "HEAD")

    completed = _run(manifest, worktree, target, report)

    assert completed.returncode != 0
    assert _git(worktree, "rev-parse", "HEAD") == before
    assert "gates failed" in report.read_text(encoding="utf-8")


def test_rejects_candidate_path_escape_before_git_mutation(candidate):
    repo, worktree, manifest, report, target = candidate
    before = _git(worktree, "rev-parse", "HEAD")

    completed = _run(manifest, repo, target, report)

    assert completed.returncode != 0
    assert _git(worktree, "rev-parse", "HEAD") == before
    assert "candidate path" in completed.stderr.lower()


def test_rejects_a_modified_manifest_before_git_mutation(candidate):
    _repo, worktree, manifest, report, target = candidate
    before = _git(worktree, "rev-parse", "HEAD")
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    saved["classification"] = "tampered"
    manifest.write_text(json.dumps(saved), encoding="utf-8")

    completed = _run(manifest, worktree, target, report)

    assert completed.returncode != 0
    assert _git(worktree, "rev-parse", "HEAD") == before
    assert "manifest" in completed.stderr.lower()


def test_static_guard_prohibits_push_tag_and_home_assistant_control():
    source = SCRIPT.read_text(encoding="utf-8")

    assert not __import__("re").search(r"\bgit\b[^\n]*\bpush\b", source, __import__("re").I)
    assert not __import__("re").search(r"\bgit\b[^\n]*\btag\b", source, __import__("re").I)
    assert "hass.services" not in source.lower()

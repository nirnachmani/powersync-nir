"""Behavioral contracts for the enforced sequential upstream ledger."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "scripts/private-fork/maintainer_ledger.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


def _commit(repo: Path, number: int, subject: str) -> str:
    path = repo / "commits.txt"
    path.write_text(path.read_text(encoding="utf-8") + f"{number}\n" if path.exists() else f"{number}\n", encoding="utf-8")
    _git(repo, "add", "commits.txt")
    _git(repo, "commit", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    baseline = _commit(repo, 0, "baseline")
    first = _commit(repo, 1, "first upstream change")
    second = _commit(repo, 2, "second upstream change")
    return repo, baseline, first, second


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LEDGER), "--repo", str(repo), *args],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def _initialize(repo: Path, state: Path, baseline: str) -> None:
    completed = _run(
        repo, "init", "--state", str(state), "--baseline", baseline,
        "--migration-boundary", "v2.12.1418",
        "--migration-reference", "docs/private-fork/upstream-1363-1408-port-manifest.md",
    )
    assert completed.returncode == 0, completed.stderr


def test_init_records_explicit_baseline_and_honest_preledger_boundary(tmp_path):
    repo, baseline, _first, _second = _repo(tmp_path)
    state = tmp_path / "state/upstream.json"

    _initialize(repo, state, baseline)

    ledger = json.loads(state.read_text(encoding="utf-8"))
    assert ledger["schema_version"] == 1
    assert ledger["checkpoint"] == baseline
    assert ledger["entries"] == []
    assert ledger["migration"] == {
        "boundary": "v2.12.1418",
        "references": ["docs/private-fork/upstream-1363-1408-port-manifest.md"],
    }


def test_next_reports_exact_oldest_unresolved_commit(tmp_path):
    repo, baseline, first, second = _repo(tmp_path)
    state = tmp_path / "state.json"
    _initialize(repo, state, baseline)

    completed = _run(repo, "next", "--state", str(state), "--target", second)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["next"] == {"sha": first, "subject": "first upstream change"}
    assert payload["remaining"] == 2


def test_record_only_accepts_next_terminal_outcome_and_advances_atomically(tmp_path):
    repo, baseline, first, second = _repo(tmp_path)
    state = tmp_path / "state.json"
    _initialize(repo, state, baseline)

    rejected = _run(repo, "record", "--state", str(state), "--target", second,
                    "--sha", second, "--outcome", "rejected", "--reason", "excluded backend")
    assert rejected.returncode != 0
    assert json.loads(state.read_text(encoding="utf-8"))["checkpoint"] == baseline

    accepted = _run(repo, "record", "--state", str(state), "--target", second,
                    "--sha", first, "--outcome", "ported", "--reason", "compatible fix",
                    "--private-commit", baseline, "--upstream-version", "v2.12.1419")
    assert accepted.returncode == 0, accepted.stderr
    ledger = json.loads(state.read_text(encoding="utf-8"))
    assert ledger["checkpoint"] == first
    assert ledger["entries"][0]["upstream"] == {"version": "v2.12.1419", "sha": first, "subject": "first upstream change"}
    assert ledger["entries"][0]["private_commits"] == [baseline]
    assert ledger["entries"][0]["outcome"] == "ported"
    assert ledger["entries"][0]["timestamp"].endswith("Z")


def test_record_rejects_deferred_unknown_sha_and_missing_required_details(tmp_path):
    repo, baseline, first, second = _repo(tmp_path)
    state = tmp_path / "state.json"
    _initialize(repo, state, baseline)

    cases = (
        ("--sha", first, "--outcome", "deferred", "--reason", "wait"),
        ("--sha", "b" * 40, "--outcome", "rejected", "--reason", "unknown"),
        ("--sha", first, "--outcome", "rejected"),
        ("--sha", first, "--outcome", "amended", "--reason", "private overlap"),
    )
    for case in cases:
        completed = _run(repo, "record", "--state", str(state), "--target", second, *case)
        assert completed.returncode != 0
        assert json.loads(state.read_text(encoding="utf-8"))["checkpoint"] == baseline


def test_record_rejects_a_private_commit_sha_missing_from_the_private_repo(tmp_path):
    repo, baseline, first, second = _repo(tmp_path)
    state = tmp_path / "state.json"
    _initialize(repo, state, baseline)

    completed = _run(
        repo, "record", "--state", str(state), "--target", second,
        "--sha", first, "--outcome", "ported", "--reason", "compatible fix",
        "--private-commit", "a" * 40, "--upstream-version", "v2.12.1419",
    )

    assert completed.returncode != 0
    assert "private commit" in completed.stderr.lower()
    assert json.loads(state.read_text(encoding="utf-8"))["checkpoint"] == baseline


def test_summary_is_cron_usable_and_migration_requires_matching_legacy_checkpoint(tmp_path):
    repo, baseline, first, second = _repo(tmp_path)
    state = tmp_path / "state.json"
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"last_reviewed_upstream": baseline}), encoding="utf-8")

    migrated = _run(repo, "migrate", "--state", str(state), "--legacy-state", str(legacy),
                    "--baseline", baseline, "--migration-boundary", "v2.12.1418",
                    "--migration-reference", "pre-ledger history only")
    assert migrated.returncode == 0, migrated.stderr
    assert json.loads(legacy.read_text(encoding="utf-8")) == {"last_reviewed_upstream": baseline}

    summary = _run(repo, "summary", "--state", str(state), "--target", second)
    assert summary.returncode == 0, summary.stderr
    payload = json.loads(summary.stdout)
    assert payload["checkpoint"] == baseline
    assert payload["next"] == {"sha": first, "subject": "first upstream change"}
    assert payload["pending_count"] == 2
    assert payload["outcomes"] == {"ported": 0, "amended": 0, "rejected": 0, "admin/no-port": 0}


def test_migration_uses_a_distinct_ledger_output_and_preserves_legacy_upstream_state(tmp_path):
    repo, baseline, _first, _second = _repo(tmp_path)
    legacy = tmp_path / "state/upstream.json"
    ledger_state = tmp_path / "state/maintainer_ledger.json"
    legacy_payload = {"last_reviewed_upstream": baseline}
    legacy.parent.mkdir()
    legacy.write_text(json.dumps(legacy_payload), encoding="utf-8")

    migrated = _run(
        repo, "migrate", "--state", str(ledger_state), "--legacy-state", str(legacy),
        "--baseline", baseline, "--migration-boundary", "v2.12.1418",
        "--migration-reference", "pre-ledger history only",
    )

    assert migrated.returncode == 0, migrated.stderr
    assert ledger_state != legacy
    assert json.loads(legacy.read_text(encoding="utf-8")) == legacy_payload
    assert json.loads(ledger_state.read_text(encoding="utf-8"))["checkpoint"] == baseline

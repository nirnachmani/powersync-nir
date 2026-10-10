"""Tests for read-only private-fork upstream delta tools."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts/private-fork/collect_upstream_delta.py"
CLASSIFIER_PATH = ROOT / "scripts/private-fork/classify_delta.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def _commit(repo: Path, path: str, content: str, message: str) -> str:
    file_path = repo / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _git_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    baseline = _commit(repo, "docs/readme.md", "before\n", "docs: baseline")
    target = _commit(
        repo,
        "tests/test_widget.py",
        "def test_widget_sync():\n    assert True\n",
        "test: add widget coverage",
    )
    _commit(
        repo,
        "src/widget.py",
        "def sync_widget():\n    return 'ok'\n",
        "feat: add widget sync",
    )
    return repo, baseline, _git(repo, "rev-parse", "HEAD")


def _write_inventory(root: Path) -> Path:
    inventory = root / "docs/private-fork/local-change-inventory.md"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(
        """# Inventory
- `custom_components/power_sync/automations/actions.py`
- `tests/test_shared_loadpoint_action_guard.py`
""",
        encoding="utf-8",
    )
    source = root / "custom_components/power_sync/automations/actions.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def resolve_shared_loadpoint_command():\n    return None\n",
        encoding="utf-8",
    )
    test = root / "tests/test_shared_loadpoint_action_guard.py"
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text(
        "def test_shared_command_guard():\n    assert True\n",
        encoding="utf-8",
    )
    return inventory


def test_collector_returns_structured_git_delta(tmp_path):
    collector = _load_module("collect_upstream_delta", COLLECTOR_PATH)
    repo, baseline, target = _git_fixture(tmp_path)

    result = collector.collect_delta(repo, baseline, target)

    assert result["schema_version"] == 1
    assert result["baseline"]["resolved"] == baseline
    assert result["target"]["resolved"] == target
    assert result["changed_paths"] == ["src/widget.py", "tests/test_widget.py"]
    assert result["changed_tests"] == [
        {"path": "tests/test_widget.py", "names": ["test_widget_sync"]}
    ]
    assert result["changed_symbols"] == [
        {"name": "sync_widget", "path": "src/widget.py", "status": "added"}
    ]
    assert [commit["subject"] for commit in result["commits"]] == [
        "test: add widget coverage",
        "feat: add widget sync",
    ]


@pytest.mark.parametrize("baseline, target", [("does-not-exist", "HEAD"), ("", "HEAD"), ("HEAD", "")])
def test_collector_rejects_invalid_or_missing_refs(tmp_path, baseline, target):
    collector = _load_module("collect_upstream_delta_invalid", COLLECTOR_PATH)
    repo, _baseline, _target = _git_fixture(tmp_path)

    with pytest.raises(collector.DeltaCollectionError):
        collector.collect_delta(repo, baseline, target)


def test_collector_rejects_reverse_or_unrelated_range(tmp_path):
    collector = _load_module("collect_upstream_delta_range", COLLECTOR_PATH)
    repo, baseline, target = _git_fixture(tmp_path)

    with pytest.raises(collector.DeltaCollectionError, match="ancestor"):
        collector.collect_delta(repo, target, baseline)


@pytest.mark.parametrize(
    ("name", "delta", "expected"),
    [
        (
            "no-overlap",
            {"changed_paths": ["docs/release-notes.md"], "changed_symbols": [], "changed_tests": []},
            "no-overlap",
        ),
        (
            "mechanical-overlap",
            {
                "changed_paths": ["custom_components/power_sync/automations/actions.py"],
                "changed_symbols": [{"name": "format_log_line", "path": "custom_components/power_sync/automations/actions.py", "status": "modified"}],
                "changed_tests": [],
            },
            "mechanical-overlap",
        ),
        (
            "compatible-semantic-overlap",
            {
                "changed_paths": ["custom_components/power_sync/automations/actions.py", "tests/test_widget.py"],
                "changed_symbols": [{"name": "resolve_shared_loadpoint_command", "path": "custom_components/power_sync/automations/actions.py", "status": "modified"}],
                "changed_tests": [{"path": "tests/test_widget.py", "names": ["test_widget_sync"]}],
            },
            "compatible-semantic-overlap",
        ),
        (
            "redundant-private-coverage",
            {
                "changed_paths": ["custom_components/power_sync/automations/actions.py", "tests/test_shared_loadpoint_action_guard.py"],
                "changed_symbols": [{"name": "resolve_shared_loadpoint_command", "path": "custom_components/power_sync/automations/actions.py", "status": "modified"}],
                "changed_tests": [{"path": "tests/test_shared_loadpoint_action_guard.py", "names": ["test_shared_command_guard"]}],
            },
            "redundant-private-coverage",
        ),
        (
            "incompatible-semantic-conflict",
            {
                "changed_paths": ["custom_components/power_sync/automations/actions.py"],
                "changed_symbols": [{"name": "resolve_shared_loadpoint_command", "path": "custom_components/power_sync/automations/actions.py", "status": "deleted"}],
                "changed_tests": [],
            },
            "incompatible-semantic-conflict",
        ),
    ],
)
def test_classifier_assigns_every_deterministic_category(tmp_path, name, delta, expected):
    classifier = _load_module(f"classify_delta_{name}", CLASSIFIER_PATH)
    inventory = _write_inventory(tmp_path)

    result = classifier.classify_delta(delta, tmp_path, inventory)

    assert result["classification"] == expected
    assert result["evidence"]


def test_classifier_rejects_missing_required_delta_fields(tmp_path):
    classifier = _load_module("classify_delta_invalid", CLASSIFIER_PATH)
    inventory = _write_inventory(tmp_path)

    with pytest.raises(classifier.DeltaClassificationError, match="changed_paths"):
        classifier.classify_delta({}, tmp_path, inventory)


def test_tools_emit_json_and_never_include_mutating_git_commands(tmp_path):
    collector = _load_module("collect_upstream_delta_cli", COLLECTOR_PATH)
    repo, baseline, target = _git_fixture(tmp_path)
    completed = subprocess.run(
        [str(Path(".venv/bin/python")), str(COLLECTOR_PATH), baseline, target, "--repo", str(repo)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert json.loads(completed.stdout)["target"]["resolved"] == target
    forbidden = r"git\s+(?:add|am|apply|bisect|checkout|cherry-pick|clean|commit|merge|mv|push|rebase|reset|restore|rm|stash|switch|tag|worktree)\b"
    for script in (COLLECTOR_PATH, CLASSIFIER_PATH):
        assert not __import__("re").search(forbidden, script.read_text(encoding="utf-8"), __import__("re").I)


def test_private_fork_runner_includes_delta_tool_tests():
    runner = (ROOT / "scripts/private-fork/run_private_tests.sh").read_text(encoding="utf-8")

    assert "tests/test_private_fork_upstream_delta.py" in runner

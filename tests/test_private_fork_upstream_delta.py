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


MANIFEST_PATH = ROOT / "docs/private-fork/upstream-1363-1408-port-manifest.md"
MANIFEST_BASELINE = "85f99ea62a174cd9153d5ff2ce71023dda2c9a5c"
MANIFEST_TARGET = "e3e107409b18add2213a9de617cc23591e73c873"
MANIFEST_CLASSIFICATIONS = {
    "low-risk compatible port",
    "manual semantic review",
    "redundant/incompatible private shared-EV",
    "paywall/subscription reject",
    "excluded backend reject",
    "admin/no-port",
}


def _manifest_records(document: str) -> dict[str, str]:
    pattern = r"^### `([0-9a-f]{40})` — .+?(?=^### `|\Z)"
    return {match.group(1): match.group(0) for match in __import__("re").finditer(pattern, document, __import__("re").M | __import__("re").S)}


def test_1363_1408_manifest_is_exhaustive_and_matches_git_range():
    document = MANIFEST_PATH.read_text(encoding="utf-8")
    collector = _load_module("collect_upstream_delta_manifest", COLLECTOR_PATH)
    delta = collector.collect_delta(ROOT, MANIFEST_BASELINE, MANIFEST_TARGET)
    expected = {commit["sha"]: commit["subject"] for commit in delta["commits"]}
    records = _manifest_records(document)

    assert "v2.12.1363" in document and MANIFEST_BASELINE in document
    assert "v2.12.1408" in document and MANIFEST_TARGET in document
    assert set(records) == set(expected)
    for sha, subject in expected.items():
        record = records[sha]
        assert subject in record
        assert any(f"**Classification:** {classification}" in record for classification in MANIFEST_CLASSIFICATIONS)
        assert "**Key files:**" in record
        assert "**Rationale:**" in record
        assert "**Intended gate:**" in record


def test_1363_1408_manifest_preserves_private_rejects_and_review_gates():
    document = MANIFEST_PATH.read_text(encoding="utf-8")
    records = _manifest_records(document)

    for sha in (
        "854fdf67af4a95387edd10b2ab7fb7c60a291e4a",
        "9e9eb36845686cecb9858add14a0f17e1d4265e9",
        "a1df6d70f7628baf5cc3addb62457371ad3964ff",
        "297bada9f54a72d2833ca50c7c0f45fb10d13afb",
        "59d8618c1eac952cb88ee4b25bae2511085bcecc",
    ):
        assert sha in records
    assert "**Classification:** paywall/subscription reject" in records["854fdf67af4a95387edd10b2ab7fb7c60a291e4a"]
    assert "**Classification:** paywall/subscription reject" in records["9e9eb36845686cecb9858add14a0f17e1d4265e9"]
    assert "**Classification:** manual semantic review" in records["a1df6d70f7628baf5cc3addb62457371ad3964ff"]
    assert "**Classification:** admin/no-port" in records["297bada9f54a72d2833ca50c7c0f45fb10d13afb"]
    assert "**Classification:** redundant/incompatible private shared-EV" in records["59d8618c1eac952cb88ee4b25bae2511085bcecc"]
    assert "ev_loadpoint_profiles.py" in records["59d8618c1eac952cb88ee4b25bae2511085bcecc"]
    assert "**Classification:** manual semantic review" in records[MANIFEST_TARGET]
    assert "presentation" in records[MANIFEST_TARGET].lower()

    for required in (
        "resolve_shared_loadpoint_command()",
        "no first-profile fallback",
        "one physical ownership lease",
        "validate_local_architecture.py",
        "run_private_tests.sh",
        "licensing/",
        "ChatGPT plan-explanation sign-in",
    ):
        assert required in document

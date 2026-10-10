"""Repository-policy contracts for the private fork and restored HA domain."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_REPOSITORY = "nirnachmani/powersync-nir"
COMPONENT_PATH = "custom_components/power_sync"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _markdown_section(document: str, heading: str) -> str:
    """Return a level-two Markdown section without depending on separators."""
    match = re.search(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\Z)",
        document,
        flags=re.MULTILINE,
    )
    assert match, f"Missing ## {heading} section"
    return match.group(1)


def _readme_title(document: str) -> str:
    match = re.search(r"^\s*#\s+(.+?)\s*$", document, flags=re.MULTILINE)
    assert match, "README must have a Markdown title"
    return match.group(1)


def test_private_repository_metadata_uses_restored_component_path_and_private_slug():
    workflow = _read(".github/workflows/release.yml")
    hacs = json.loads(_read("hacs.json"))
    readme = _read("README.md")
    private_readme = _read("README_PRIVATE_FORK.md")
    agents = _read("AGENTS.md")

    assert f"{COMPONENT_PATH}/manifest.json" in workflow
    assert "custom_components/powersync_nir" not in workflow
    manifest = json.loads(_read(f"{COMPONENT_PATH}/manifest.json"))

    assert hacs["name"] == "PowerSync"
    assert manifest["domain"] == "power_sync"
    assert manifest["name"] == "PowerSync"
    title = _readme_title(readme).lower()
    assert title.startswith("powersync")
    assert "private fork" in title
    assert " nir" not in title
    for source in (readme, private_readme, agents):
        assert PRIVATE_REPOSITORY in source

    assert (
        "https://my.home-assistant.io/redirect/hacs_repository/"
        "?owner=nirnachmani&repository=powersync-nir&category=integration"
    ) in readme
    installation = _markdown_section(readme, "Installation")
    assert "https://github.com/nirnachmani/powersync-nir" in installation
    assert "https://github.com/bolagnaise/PowerSync" not in installation

    assert "HA domain/package: `power_sync`" in private_readme
    assert "Home Assistant domain/package `power_sync`" in agents
    agents_policy = agents.lower()
    assert "deployment" in agents_policy
    assert "separate explicit authorization" in agents_policy
    assert "not deployment authorization" in agents_policy
    deployment = _markdown_section(private_readme, "Deployment").lower()
    assert "separately authorized" in deployment
    assert "private `main` branch" in deployment
    assert "updater gates" in deployment


def test_private_updater_material_uses_restored_component_path_and_never_authorises_deployment():
    material = {
        "docs/private-fork/local-change-inventory.md": _read("docs/private-fork/local-change-inventory.md"),
        "docs/private-fork/upstream-update-policy.md": _read("docs/private-fork/upstream-update-policy.md"),
        "docs/private-fork/maintainer-server-bootstrap.md": _read("docs/private-fork/maintainer-server-bootstrap.md"),
        "docs/private-fork/maintainer-cycle-cron-spec.md": _read("docs/private-fork/maintainer-cycle-cron-spec.md"),
        "docs/private-fork/powersync-private-updates-reference.md": _read("docs/private-fork/powersync-private-updates-reference.md"),
        "docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md": _read("docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md"),
        "scripts/private-fork/validate_local_architecture.py": _read("scripts/private-fork/validate_local_architecture.py"),
        "scripts/private-fork/run_private_tests.sh": _read("scripts/private-fork/run_private_tests.sh"),
        "scripts/private-fork/candidate_worktree.py": _read("scripts/private-fork/candidate_worktree.py"),
        "scripts/private-fork/integrate_candidate.py": _read("scripts/private-fork/integrate_candidate.py"),
        "scripts/private-fork/maintainer_cycle.py": _read("scripts/private-fork/maintainer_cycle.py"),
        "scripts/private-fork/install_maintainer_skill.sh": _read("scripts/private-fork/install_maintainer_skill.sh"),
        "scripts/private-fork/install_maintainer_cron.sh": _read("scripts/private-fork/install_maintainer_cron.sh"),
    }

    assert all("custom_components/powersync_nir" not in source for source in material.values())
    assert any(COMPONENT_PATH in source for source in material.values())
    assert all(PRIVATE_REPOSITORY in source for source in (
        material["docs/private-fork/upstream-update-policy.md"],
        material["scripts/private-fork/candidate_worktree.py"],
        material["scripts/private-fork/integrate_candidate.py"],
    ))
    skill = material["docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md"].lower()
    assert "separate authorisation" in skill
    assert "never deploy" in skill

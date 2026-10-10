"""Repository-policy contracts for the private fork and restored HA domain."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_REPOSITORY = "nirnachmani/powersync-nir"
COMPONENT_PATH = "custom_components/power_sync"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_private_repository_metadata_uses_restored_component_path_and_private_slug():
    workflow = _read(".github/workflows/release.yml")
    hacs = json.loads(_read("hacs.json"))
    readme = _read("README.md")
    private_readme = _read("README_PRIVATE_FORK.md")
    agents = _read("AGENTS.md")

    assert f"{COMPONENT_PATH}/manifest.json" in workflow
    assert "custom_components/powersync_nir" not in workflow
    assert hacs["name"] == "PowerSync"
    for source in (readme, private_readme, agents):
        assert PRIVATE_REPOSITORY in source
    assert "HA domain/package: `power_sync`" in private_readme
    assert "Home Assistant domain/package `power_sync`" in agents


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

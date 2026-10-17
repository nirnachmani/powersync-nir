"""Repository-policy contracts for the private fork and restored HA domain."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_REPOSITORY = "nirnachmani/powersync-nir"
COMPONENT_PATH = "custom_components/power_sync"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _has_nearby_terms(document: str, *term_groups: tuple[str, ...]) -> bool:
    """Whether each term group occurs in one prose-sized window.

    This deliberately tests policy concepts rather than Markdown layout or one
    prescribed sentence.  The alternatives cover ordinary inflections while
    keeping the required repository and deployment distinctions meaningful.
    """
    terms = ["(?:" + "|".join(group) + ")" for group in term_groups]
    pattern = r".{0,180}?".join(rf"\b{term}\b" for term in terms)
    reverse_pattern = r".{0,180}?".join(rf"\b{term}\b" for term in reversed(terms))
    return bool(
        re.search(pattern, document, flags=re.IGNORECASE | re.DOTALL)
        or re.search(reverse_pattern, document, flags=re.IGNORECASE | re.DOTALL)
    )


def _assert_readme_identity(document: str) -> None:
    assert _has_nearby_terms(document, ("private",), ("repository", "repo", "fork"))
    assert _has_nearby_terms(
        document,
        ("installed", "installation", "integration"),
        ("PowerSync",),
        ("power_sync",),
    )


def _assert_deployment_policy(document: str) -> None:
    """Require authorization and updater gates to remain distinct concepts."""
    policy_concepts = (
        r"\b(?:deploy|deployment)\w*\b",
        r"\b(?:explicit(?:ly)?|separate(?:ly)?)\b",
        r"\bauthori[sz](?:e|ed|ation)\b",
        r"\bupdat(?:e|er|ing)\w*\b",
        r"\bgates?\b",
        r"\b(?:not|never|cannot|isn't|aren't)\b",
    )
    prose_blocks = re.split(r"\n\s*\n", document)
    assert any(
        all(re.search(concept, block, flags=re.IGNORECASE) for concept in policy_concepts)
        for block in prose_blocks
    ), "deployment policy must require explicit authorization and deny updater gates that authority"


def _assert_no_paywall_maintenance_policy(document: str) -> None:
    """Require the maintainer guidance to reject, rather than merge, paywall code."""
    lowered = document.lower()
    assert "1404+" in document and "rebase" in lowered and "wholesale" in lowered
    assert _has_nearby_terms(document, ("licensing",), ("import", "guard", "pairing"))
    assert _has_nearby_terms(document, ("hosted",), ("api",), ("entitlement", "permission"))
    assert _has_nearby_terms(document, ("subscription",), ("ui", "storage", "recovery", "fence"))
    assert _has_nearby_terms(document, ("optimizer", "optimiser"), ("manual(?:ly)?",), ("hunk",))
    assert _has_nearby_terms(document, ("incompatible",), ("licensing",))
    assert _has_nearby_terms(document, ("source attribution",), ("noncommercial",))
    assert "validate_local_architecture.py" in document
    assert "run_private_tests.sh" in document


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
    for source in (readme, private_readme, agents):
        assert PRIVATE_REPOSITORY in source

    _assert_readme_identity(readme)

    assert (
        "https://my.home-assistant.io/redirect/hacs_repository/"
        "?owner=nirnachmani&repository=powersync-nir&category=integration"
    ) in readme
    assert "https://github.com/nirnachmani/powersync-nir" in readme

    _assert_readme_identity(private_readme)
    _assert_deployment_policy(agents)
    _assert_deployment_policy(private_readme)


def test_private_deployment_policy_rejects_updater_authorisation_mutation():
    private_readme = _read("README_PRIVATE_FORK.md")
    mutated = private_readme.replace("not an updater outcome", "an updater outcome", 1)
    assert mutated != private_readme

    with pytest.raises(AssertionError):
        _assert_deployment_policy(mutated)


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


def test_private_maintainer_guidance_permanently_rejects_optimizer_paywall_imports():
    for relative_path in (
        "docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md",
        "docs/private-fork/powersync-private-updates-reference.md",
    ):
        _assert_no_paywall_maintenance_policy(_read(relative_path))


def test_default_private_gate_runs_identity_policy_contract():
    runner = _read("scripts/private-fork/run_private_tests.sh")

    assert "tests/test_private_identity_policy.py" in runner
    assert "tests/test_maintainer_ledger.py" in runner


def test_private_maintainer_material_requires_the_sequential_ledger():
    for relative_path in (
        "docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md",
        "docs/private-fork/powersync-private-updates-reference.md",
        "scripts/private-fork/install_maintainer_cron.sh",
        "docs/private-fork/maintainer-cycle-cron-spec.md",
    ):
        material = _read(relative_path)
        assert "maintainer_ledger.py" in material
        assert "strictly oldest to newest" in material
        assert "freeform last_reviewed_upstream checkpoint" in material or "last_reviewed_upstream" not in material

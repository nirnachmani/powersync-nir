#!/usr/bin/env python3
"""Integrate one reviewed no-overlap revision in its disposable candidate only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_PRIVATE_OWNER_REPO = "nirnachmani/powersync-nir"


class IntegrationError(ValueError):
    """Raised before an unsafe candidate operation."""


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        raise IntegrationError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def _owner_repo(url: str) -> str | None:
    ssh = re.fullmatch(r"(?:[^@/]+@)?github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?/?", url)
    if ssh:
        return f"{ssh.group(1)}/{ssh.group(2)}"
    parsed = urlparse(url)
    if parsed.hostname != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return None
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def _require_private_origin(repo: Path, allowed: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", allowed):
        raise IntegrationError("private owner/repository policy is invalid")
    origin = _owner_repo(_git(repo, "remote", "get-url", "origin"))
    if origin is None or origin.casefold() != allowed.casefold():
        raise IntegrationError("origin is not the policy-approved private repository")


def _require_clean(repo: Path, label: str) -> None:
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise IntegrationError(f"{label} must be clean")


def _registered(source: Path) -> set[Path]:
    return {
        Path(line.removeprefix("worktree ")).resolve()
        for line in _git(source, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    }


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrationError(f"manifest is missing or invalid: {error}") from error
    if not isinstance(value, dict):
        raise IntegrationError("manifest must be a JSON object")
    digest = value.get("manifest_digest")
    contents = {key: item for key, item in value.items() if key != "manifest_digest"}
    expected = hashlib.sha256(
        json.dumps(contents, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not isinstance(digest, str) or digest != expected:
        raise IntegrationError("manifest integrity verification failed")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise IntegrationError(f"manifest {field} is missing")
    return value


def _manifest_ref(manifest: dict[str, object], name: str) -> str:
    value = manifest.get(name)
    if not isinstance(value, dict):
        raise IntegrationError(f"manifest {name} is missing")
    return _text(value.get("resolved"), f"{name}.resolved")


def _verify_candidate(manifest: dict[str, object], expected: Path, target: str, allowed: str) -> tuple[Path, Path, str]:
    candidate = expected.resolve()
    recorded = Path(_text(manifest.get("candidate_worktree"), "candidate_worktree")).resolve()
    if candidate != recorded:
        raise IntegrationError("candidate path does not match the manifest")
    source = Path(_text(manifest.get("private_repo"), "private_repo")).resolve()
    if candidate == source or source in candidate.parents or candidate in source.parents:
        raise IntegrationError("candidate path must be isolated from the source checkout")
    if candidate not in _registered(source):
        raise IntegrationError("candidate path is not a registered disposable worktree")
    _require_private_origin(source, allowed)
    _require_private_origin(candidate, allowed)
    _require_clean(source, "private source checkout")
    _require_clean(candidate, "candidate worktree")
    expected_head = _text(manifest.get("candidate_head_sha"), "candidate_head_sha")
    if _git(candidate, "rev-parse", "HEAD") != expected_head:
        raise IntegrationError("candidate HEAD no longer matches the manifest")
    expected_target = _manifest_ref(manifest, "upstream_target")
    actual_target = _git(candidate, "rev-parse", "--verify", f"{target}^{{commit}}")
    if actual_target != expected_target:
        raise IntegrationError("upstream target does not match the manifest")
    return source, candidate, actual_target


def _write_report(path: Path, classification: str, result: str, candidate: Path, detail: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            (
                f"Classification: {classification}",
                f"Candidate: {candidate}",
                f"Result: {result}",
                f"Commit/candidate: {detail}",
                "Deployment: not attempted",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def _run_gates(candidate: Path) -> tuple[bool, str]:
    commands = (
        [sys.executable, "scripts/private-fork/validate_local_architecture.py"],
        ["scripts/private-fork/run_private_tests.sh"],
    )
    failures: list[str] = []
    for command in commands:
        completed = subprocess.run(command, cwd=candidate, text=True, capture_output=True, check=False)
        if completed.returncode:
            failures.append(f"{' '.join(command)} exited {completed.returncode}")
    return not failures, "; ".join(failures)


def integrate(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.manifest)
    source, candidate, target = _verify_candidate(
        manifest, args.candidate_worktree, args.upstream_target_ref, args.private_owner_repo
    )
    del source
    if args.classification != "no_overlap":
        _write_report(args.report, args.classification, "stopped", candidate, "not created; compatible-resolution work required")
        return 1
    before = _git(candidate, "rev-parse", "HEAD")
    merged = subprocess.run(
        ["git", "merge", "--no-commit", "--no-ff", target],
        cwd=candidate,
        text=True,
        capture_output=True,
        check=False,
    )
    if merged.returncode:
        subprocess.run(["git", "merge", "--abort"], cwd=candidate, text=True, capture_output=True, check=False)
        _git(candidate, "reset", "--hard", before)
        _write_report(args.report, args.classification, "failed", candidate, "not created; merge failed and candidate reset")
        return 1
    gates_passed, gate_detail = _run_gates(candidate)
    if not gates_passed:
        subprocess.run(["git", "merge", "--abort"], cwd=candidate, text=True, capture_output=True, check=False)
        _git(candidate, "reset", "--hard", before)
        _write_report(args.report, args.classification, "failed", candidate, f"not created; gates failed: {gate_detail}")
        return 1
    _git(candidate, "commit", "-m", f"merge reviewed upstream candidate {target}")
    commit = _git(candidate, "rev-parse", "HEAD")
    _write_report(args.report, args.classification, "passed", candidate, commit)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-worktree", type=Path, required=True)
    parser.add_argument("--upstream-target-ref", required=True)
    parser.add_argument("--classification", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--private-owner-repo", default=DEFAULT_PRIVATE_OWNER_REPO)
    args = parser.parse_args()
    try:
        return integrate(args)
    except IntegrationError as error:
        parser.error(str(error))
    except OSError as error:
        parser.error(f"candidate integration failed: {error}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

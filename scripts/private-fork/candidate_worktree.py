#!/usr/bin/env python3
"""Prepare or safely remove a disposable, detached private-fork candidate worktree."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_PRIVATE_OWNER_REPO = "nirnachmani/powersync-nir"


class CandidateWorktreeError(ValueError):
    """Raised when a candidate worktree operation is unsafe or incomplete."""


def _git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=repo, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise CandidateWorktreeError(detail.strip()) from error
    return completed.stdout.strip()


def _repo_root(repo: Path) -> Path:
    resolved = repo.resolve()
    root = Path(_git(resolved, "rev-parse", "--show-toplevel")).resolve()
    if root != resolved:
        raise CandidateWorktreeError("--private-repo must name the checkout root")
    return root


def _resolve_ref(repo: Path, reference: str, label: str) -> str:
    if not reference:
        raise CandidateWorktreeError(f"{label} is required")
    try:
        return _git(repo, "rev-parse", "--verify", f"{reference}^{{commit}}")
    except CandidateWorktreeError as error:
        raise CandidateWorktreeError(f"invalid {label} {reference!r}: {error}") from error


def _github_owner_repo(url: str) -> str | None:
    ssh_match = re.fullmatch(r"(?:[^@/]+@)?github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?/?", url)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"
    parsed = urlparse(url)
    if parsed.hostname != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return None
    return f"{parts[0]}/{parts[1][:-4] if parts[1].endswith('.git') else parts[1]}"


def _verify_private_origin(repo: Path, allowed_owner_repo: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", allowed_owner_repo):
        raise CandidateWorktreeError("--private-owner-repo must be an owner/repository pair")
    origin = _git(repo, "remote", "get-url", "origin")
    actual = _github_owner_repo(origin)
    if actual is None or actual.casefold() != allowed_owner_repo.casefold():
        raise CandidateWorktreeError(
            "origin must be the explicitly permitted private GitHub repository "
            f"{allowed_owner_repo!r}; found {origin!r}"
        )
    return origin


def _require_clean(repo: Path) -> None:
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise CandidateWorktreeError("private source checkout must be clean")


def _require_candidate_root(repo: Path, candidate_root: Path) -> Path:
    root = candidate_root.resolve()
    if root == repo or repo in root.parents or root in repo.parents:
        raise CandidateWorktreeError("candidate root must be outside the private source checkout")
    return root


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(contents, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _registered_worktrees(repo: Path) -> set[Path]:
    worktrees: set[Path] = set()
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            worktrees.add(Path(line.removeprefix("worktree ")).resolve())
    return worktrees


def prepare_candidate(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.private_repo)
    candidate_root = _require_candidate_root(repo, args.candidate_root)
    _require_clean(repo)
    origin = _verify_private_origin(repo, args.private_owner_repo)
    private_start_sha = _resolve_ref(repo, "HEAD", "private starting ref")
    source_sha = _resolve_ref(repo, args.private_source_ref, "private source ref")
    target_sha = _resolve_ref(repo, args.upstream_target_ref, "upstream target ref")
    candidate_root.mkdir(parents=True, exist_ok=True)
    name = args.candidate_name or f"candidate-{source_sha[:12]}-{uuid.uuid4().hex[:12]}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise CandidateWorktreeError("candidate name contains unsupported characters")
    worktree = (candidate_root / name).resolve()
    if worktree.parent != candidate_root or worktree.exists():
        raise CandidateWorktreeError("candidate worktree path must be a new direct child of candidate root")

    created = False
    try:
        _git(repo, "worktree", "add", "--detach", str(worktree), source_sha)
        created = True
        manifest = {
            "schema_version": 1,
            "classification": "candidate-prepared-no-integration",
            "integration": "not-performed",
            "private_repo": str(repo),
            "private_origin": origin,
            "private_start_sha": private_start_sha,
            "private_source": {"requested": args.private_source_ref, "resolved": source_sha},
            "upstream_target": {"requested": args.upstream_target_ref, "resolved": target_sha},
            "candidate_worktree": str(worktree),
            "candidate_head_sha": source_sha,
            "head_mode": "detached",
        }
        _atomic_write(args.manifest.resolve(), json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return manifest
    except Exception:
        if created and worktree in _registered_worktrees(repo):
            try:
                _git(repo, "worktree", "remove", "--force", str(worktree))
            except CandidateWorktreeError:
                pass
        raise


def cleanup_candidate(args: argparse.Namespace) -> None:
    repo = _repo_root(args.private_repo)
    candidate_root = _require_candidate_root(repo, args.candidate_root)
    worktree = args.worktree.resolve()
    if worktree == candidate_root or worktree.parent != candidate_root:
        raise CandidateWorktreeError("--worktree must be an exact direct child beneath --candidate-root")
    if worktree not in _registered_worktrees(repo):
        raise CandidateWorktreeError("--worktree is not a registered worktree of the private repository")
    _git(repo, "worktree", "remove", "--force", str(worktree))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="create a detached disposable candidate")
    prepare.add_argument("--private-repo", type=Path, required=True)
    prepare.add_argument("--candidate-root", type=Path, required=True)
    prepare.add_argument("--private-source-ref", required=True)
    prepare.add_argument("--upstream-target-ref", required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--private-owner-repo", default=DEFAULT_PRIVATE_OWNER_REPO)
    prepare.add_argument("--candidate-name")
    cleanup = subparsers.add_parser("cleanup", help="remove one explicit disposable candidate")
    cleanup.add_argument("--private-repo", type=Path, required=True)
    cleanup.add_argument("--candidate-root", type=Path, required=True)
    cleanup.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(json.dumps(prepare_candidate(args), sort_keys=True))
        else:
            cleanup_candidate(args)
    except CandidateWorktreeError as error:
        parser.error(str(error))
    except OSError as error:
        parser.error(f"candidate worktree operation failed: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

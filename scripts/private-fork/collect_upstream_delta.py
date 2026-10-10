#!/usr/bin/env python3
"""Collect a structured, read-only Git delta between two explicit revisions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


class DeltaCollectionError(ValueError):
    """Raised when an explicit comparison cannot be collected safely."""


def _git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise DeltaCollectionError(detail.strip()) from error
    return completed.stdout


def _resolve(repo: Path, reference: str, label: str) -> str:
    if not reference:
        raise DeltaCollectionError(f"{label} reference is required")
    try:
        return _git(repo, "rev-parse", "--verify", f"{reference}^{{commit}}").strip()
    except DeltaCollectionError as error:
        raise DeltaCollectionError(f"invalid {label} reference {reference!r}: {error}") from error


def _changed_symbols(repo: Path, baseline: str, target: str) -> list[dict[str, str]]:
    diff = _git(repo, "diff", "--unified=0", "--no-ext-diff", baseline, target, "--", "*.py")
    current_path: str | None = None
    statuses: dict[tuple[str, str], set[str]] = {}
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            continue
        if not current_path or current_path.startswith("tests/") or line.startswith(("+++", "---")) or not line[:1] in {"+", "-"}:
            continue
        match = re.match(r"[+-]\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)", line)
        if match:
            statuses.setdefault((current_path, match.group(1)), set()).add(
                "added" if line[0] == "+" else "deleted"
            )
    result = []
    for (path, name), states in sorted(statuses.items()):
        status = "modified" if states == {"added", "deleted"} else next(iter(states))
        result.append({"name": name, "path": path, "status": status})
    return result


def _test_names(repo: Path, baseline: str, target: str, paths: list[str]) -> list[dict[str, Any]]:
    changed_tests = []
    for path in paths:
        if not path.startswith("tests/") or not path.endswith(".py"):
            continue
        content = _git(repo, "show", f"{target}:{path}") if _path_exists(repo, target, path) else ""
        names = sorted(set(re.findall(r"^\s*def\s+(test_[A-Za-z_]\w*)\s*\(", content, re.M)))
        changed_tests.append({"path": path, "names": names})
    return changed_tests


def _path_exists(repo: Path, revision: str, path: str) -> bool:
    try:
        _git(repo, "cat-file", "-e", f"{revision}:{path}")
    except DeltaCollectionError:
        return False
    return True


def collect_delta(repo: Path, baseline_ref: str, target_ref: str) -> dict[str, Any]:
    """Return JSON-compatible evidence for one explicit, forward Git range."""
    repo = Path(repo).resolve()
    _git(repo, "rev-parse", "--is-inside-work-tree")
    baseline = _resolve(repo, baseline_ref, "baseline")
    target = _resolve(repo, target_ref, "target")
    try:
        _git(repo, "merge-base", "--is-ancestor", baseline, target)
    except DeltaCollectionError as error:
        raise DeltaCollectionError("baseline must be an ancestor of target") from error

    name_status = _git(repo, "diff", "--name-status", "--no-ext-diff", baseline, target)
    changes = []
    for row in filter(None, name_status.splitlines()):
        columns = row.split("\t")
        status = columns[0]
        if status.startswith("R") or status.startswith("C"):
            changes.append({"status": status, "old_path": columns[1], "path": columns[2]})
        else:
            changes.append({"status": status, "path": columns[1]})
    paths = sorted(change["path"] for change in changes)
    commits = []
    for row in filter(None, _git(repo, "log", "--format=%H%x1f%s", "--reverse", f"{baseline}..{target}").splitlines()):
        sha, subject = row.split("\x1f", 1)
        commits.append({"sha": sha, "subject": subject})
    release_notes = [path for path in paths if re.search(r"(?:^|/)(?:changelog|release.?notes?)", path, re.I)]
    return {
        "schema_version": 1,
        "baseline": {"requested": baseline_ref, "resolved": baseline},
        "target": {"requested": target_ref, "resolved": target},
        "commits": commits,
        "changes": changes,
        "changed_paths": paths,
        "changed_symbols": _changed_symbols(repo, baseline, target),
        "changed_tests": _test_names(repo, baseline, target, paths),
        "release_notes": release_notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", help="last reviewed upstream SHA or tag")
    parser.add_argument("target", help="target upstream SHA or tag")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository to inspect")
    args = parser.parse_args()
    try:
        print(json.dumps(collect_delta(args.repo, args.baseline, args.target), indent=2, sort_keys=True))
    except DeltaCollectionError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create read-only, deterministic upstream-review artifacts for one explicit range."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from classify_delta import DeltaClassificationError, classify_delta
from collect_upstream_delta import DeltaCollectionError, collect_delta


class MaintainerCycleError(ValueError):
    """Raised when a review cycle cannot safely produce artifacts."""


CLASSIFICATIONS = {
    "no-overlap": "no-overlap",
    "mechanical-overlap": "mechanical",
    "compatible-semantic-overlap": "compatible",
    "redundant-private-coverage": "redundant",
    "incompatible-semantic-conflict": "incompatible",
}
CANDIDATE_CLASSIFICATIONS = {"no-overlap", "mechanical", "compatible"}


def _git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=repo, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise MaintainerCycleError(detail.strip()) from error
    return completed.stdout


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MaintainerCycleError(f"invalid state file {path}: {error}") from error
    if not isinstance(state, dict):
        raise MaintainerCycleError(f"invalid state file {path}: expected a JSON object")
    return state


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(contents, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _markdown(report: dict[str, Any]) -> str:
    delta = report["delta"]
    return "\n".join(
        (
            "# PowerSync maintainer review",
            "",
            f"Upstream remote: `{report['upstream_remote']}`",
            f"Range: `{delta['baseline']['resolved']}..{delta['target']['resolved']}`",
            f"Classification: `{report['classification']}`",
            f"Requires candidate: `{str(report['requires_candidate']).lower()}`",
            "Action: report-only",
            "Deployment: forbidden; no candidate or deployment operation is performed.",
            "",
            "## Evidence",
            *[f"- {item}" for item in report["classifier"]["evidence"]],
            "",
        )
    )


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve()
    state_path = args.state.resolve()
    report_json_path = args.report_json.resolve()
    report_markdown_path = args.report_markdown.resolve()
    artifact_paths = (state_path, report_json_path, report_markdown_path)
    if len(set(artifact_paths)) != len(artifact_paths):
        raise MaintainerCycleError("state and report paths must be distinct")

    _load_state(state_path)
    _git(repo, "remote", "get-url", args.upstream_remote)
    if args.fetch:
        _git(repo, "fetch", args.upstream_remote)

    delta = collect_delta(repo, args.baseline, args.target)
    inventory = args.inventory.resolve() if args.inventory else repo / "docs/private-fork/local-change-inventory.md"
    classifier = classify_delta(delta, repo, inventory)
    classification = CLASSIFICATIONS[classifier["classification"]]
    requires_candidate = bool(delta["commits"]) and classification in CANDIDATE_CLASSIFICATIONS
    report = {
        "schema_version": 1,
        "upstream_remote": args.upstream_remote,
        "delta": delta,
        "classifier": classifier,
        "classification": classification,
        "requires_candidate": requires_candidate,
        "action": "report-only",
    }
    state = {
        "schema_version": 1,
        "reviewed_range": {
            "baseline": delta["baseline"]["resolved"],
            "target": delta["target"]["resolved"],
            "classification": classification,
        },
    }
    _atomic_write(report_json_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _atomic_write(report_markdown_path, _markdown(report))
    _atomic_write(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="private-fork checkout")
    parser.add_argument("--upstream-remote", required=True, help="read-only remote name")
    parser.add_argument("--baseline", required=True, help="explicit reviewed revision")
    parser.add_argument("--target", required=True, help="explicit target revision")
    parser.add_argument("--state", type=Path, required=True, help="review-state JSON path")
    parser.add_argument("--report-json", type=Path, required=True, help="JSON report path")
    parser.add_argument("--report-markdown", type=Path, required=True, help="Markdown report path")
    parser.add_argument("--inventory", type=Path, help="explicit local-change inventory path")
    parser.add_argument("--fetch", action="store_true", help="fetch the named remote before collection")
    args = parser.parse_args()
    try:
        report = run_cycle(args)
    except (MaintainerCycleError, DeltaCollectionError, DeltaClassificationError) as error:
        parser.error(str(error))
    print(json.dumps({"classification": report["classification"], "requires_candidate": report["requires_candidate"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

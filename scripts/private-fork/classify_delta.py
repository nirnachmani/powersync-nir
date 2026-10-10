#!/usr/bin/env python3
"""Classify a collected upstream delta without changing a repository."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
from pathlib import Path
from typing import Any


class DeltaClassificationError(ValueError):
    """Raised for incomplete or invalid collector JSON."""


def _inventory_paths(inventory: Path) -> set[str]:
    try:
        text = inventory.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise DeltaClassificationError(f"missing inventory: {inventory}") from error
    return set(re.findall(r"`([^`]+)`", text))


def _defined_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, SyntaxError):
        return set()
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _matches(path: str, candidates: set[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, candidate) for candidate in candidates)


def _validate(delta: dict[str, Any]) -> None:
    for field in ("changed_paths", "changed_symbols", "changed_tests"):
        if not isinstance(delta.get(field), list):
            raise DeltaClassificationError(f"delta field {field!r} must be a list")


def classify_delta(delta: dict[str, Any], root: Path, inventory: Path) -> dict[str, Any]:
    """Return deterministic triage based on recorded private coupling evidence.

    The result is a review classification only. It neither validates a semantic
    resolution nor authorises a repository or deployment action.
    """
    _validate(delta)
    root = Path(root)
    inventory_paths = _inventory_paths(Path(inventory))
    source_paths = {path for path in inventory_paths if not path.startswith("tests/")}
    test_paths = {path for path in inventory_paths if path.startswith("tests/")}
    paths = sorted(set(delta["changed_paths"]))
    overlapping_sources = sorted(path for path in paths if _matches(path, source_paths))
    overlapping_tests = sorted(path for path in paths if _matches(path, test_paths))
    private_symbols = set()
    for relative in source_paths:
        if "*" not in relative:
            private_symbols.update(_defined_names(root / relative))
    private_test_names = set()
    for relative in test_paths:
        if "*" not in relative:
            private_test_names.update(_defined_names(root / relative))

    symbols = [item for item in delta["changed_symbols"] if isinstance(item, dict)]
    touched_private_symbols = sorted(
        item["name"] for item in symbols if item.get("name") in private_symbols
    )
    deleted_private_symbols = sorted(
        item["name"]
        for item in symbols
        if item.get("name") in private_symbols and item.get("status") == "deleted"
    )
    test_names = {
        name
        for item in delta["changed_tests"]
        if isinstance(item, dict)
        for name in item.get("names", [])
        if isinstance(name, str)
    }
    covered_tests = sorted(test_names & private_test_names)
    overlap = bool(overlapping_sources or overlapping_tests)

    if not overlap:
        classification = "no-overlap"
        evidence = ["no changed path matches a documented private coupling path"]
    elif deleted_private_symbols:
        classification = "incompatible-semantic-conflict"
        evidence = [f"deleted private symbol: {name}" for name in deleted_private_symbols]
    elif touched_private_symbols and overlapping_tests and covered_tests:
        classification = "redundant-private-coverage"
        evidence = [
            "upstream changed documented private tests already cover documented private symbols",
            *[f"covered test: {name}" for name in covered_tests],
        ]
    elif touched_private_symbols and test_names:
        classification = "compatible-semantic-overlap"
        evidence = [
            "upstream changes a documented private symbol and includes test evidence",
            *[f"private symbol: {name}" for name in touched_private_symbols],
        ]
    else:
        classification = "mechanical-overlap"
        evidence = [
            "documented private path overlaps, but no documented private symbol has a semantic change",
        ]

    return {
        "schema_version": 1,
        "classification": classification,
        "evidence": evidence,
        "overlapping_source_paths": overlapping_sources,
        "overlapping_test_paths": overlapping_tests,
        "touched_private_symbols": touched_private_symbols,
        "covered_private_tests": covered_tests,
        "required_review": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delta", type=Path, help="JSON emitted by collect_upstream_delta.py")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--inventory",
        type=Path,
        default=None,
        help="local-change inventory (defaults beneath --root)",
    )
    args = parser.parse_args()
    try:
        delta = json.loads(args.delta.read_text(encoding="utf-8"))
        inventory = args.inventory or args.root / "docs/private-fork/local-change-inventory.md"
        print(json.dumps(classify_delta(delta, args.root, inventory), indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, DeltaClassificationError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

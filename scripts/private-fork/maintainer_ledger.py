#!/usr/bin/env python3
"""Durable, sequential ledger for private-fork upstream commit processing."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
TERMINAL_OUTCOMES = ("ported", "amended", "rejected", "admin/no-port")
PRIVATE_COMMIT_OUTCOMES = {"ported", "amended"}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class LedgerError(ValueError):
    """Raised when a ledger action would break the sequential audit trail."""


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, check=True, text=True, capture_output=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise LedgerError(detail.strip()) from error
    return result.stdout.strip()


def _resolve_commit(repo: Path, revision: str, label: str) -> str:
    try:
        resolved = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")
    except LedgerError as error:
        raise LedgerError(f"invalid {label} revision {revision!r}: {error}") from error
    if not FULL_SHA.fullmatch(resolved):
        raise LedgerError(f"could not resolve {label} to a full commit SHA")
    return resolved


def _resolve_named_private_ref(repo: Path, private_ref: str) -> str:
    """Resolve only the intended private branch through a local or remote ref."""
    branch_name = "feature/shared-logical-evs"
    local_ref = f"refs/heads/{branch_name}"
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").splitlines()
    permitted_refs = {
        ref
        for ref in refs
        if ref == local_ref or ref.endswith(f"/{branch_name}") and ref.startswith("refs/remotes/")
    }
    aliases = {
        alias
        for ref in permitted_refs
        for alias in (
            ref,
            ref.removeprefix("refs/heads/"),
            ref.removeprefix("refs/remotes/"),
        )
    }
    if private_ref not in aliases:
        raise LedgerError(
            f"private ref must be a permitted named private ref (a local or remote ref) for {branch_name!r}, not {private_ref!r}"
        )
    return _resolve_commit(repo, private_ref, "private ref")


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(ledger, indent=2, sort_keys=True) + "\n")


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LedgerError(f"ledger does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise LedgerError(f"invalid ledger {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError(f"invalid ledger {path}: unsupported schema")
    if not FULL_SHA.fullmatch(value.get("checkpoint", "")):
        raise LedgerError(f"invalid ledger {path}: checkpoint must be a full SHA")
    if not isinstance(value.get("entries"), list):
        raise LedgerError(f"invalid ledger {path}: entries must be a list")
    migration = value.get("migration")
    if not isinstance(migration, dict) or not isinstance(migration.get("boundary"), str) or not migration["boundary"]:
        raise LedgerError(f"invalid ledger {path}: migration boundary is required")
    if not isinstance(migration.get("references"), list) or not all(isinstance(item, str) and item for item in migration["references"]):
        raise LedgerError(f"invalid ledger {path}: migration references are required")
    return value


def _new_ledger(baseline: str, boundary: str, references: list[str]) -> dict[str, Any]:
    if not boundary:
        raise LedgerError("migration boundary is required; do not invent pre-ledger outcomes")
    if not references or any(not reference for reference in references):
        raise LedgerError("at least one migration reference is required")
    return {
        "schema_version": SCHEMA_VERSION,
        "checkpoint": baseline,
        "migration": {"boundary": boundary, "references": references},
        "entries": [],
    }


def _range(repo: Path, checkpoint: str, target: str) -> list[dict[str, str]]:
    _git(repo, "merge-base", "--is-ancestor", checkpoint, target)
    raw = _git(repo, "log", "--format=%H%x00%s", "--reverse", f"{checkpoint}..{target}")
    if not raw:
        return []
    commits: list[dict[str, str]] = []
    for line in raw.splitlines():
        sha, subject = line.split("\x00", 1)
        commits.append({"sha": sha, "subject": subject})
    return commits


def _pending(repo: Path, ledger: dict[str, Any], target_revision: str) -> tuple[str, list[dict[str, str]]]:
    target = _resolve_commit(repo, target_revision, "target")
    return target, _range(repo, ledger["checkpoint"], target)


def _next_payload(repo: Path, ledger: dict[str, Any], target: str) -> dict[str, Any]:
    resolved_target, commits = _pending(repo, ledger, target)
    return {
        "checkpoint": ledger["checkpoint"],
        "target": resolved_target,
        "next": commits[0] if commits else None,
        "remaining": len(commits),
    }


def initialize(args: argparse.Namespace) -> dict[str, Any]:
    if args.state.exists():
        raise LedgerError(f"refusing to overwrite existing ledger: {args.state}")
    baseline = _resolve_commit(args.repo, args.baseline, "baseline")
    ledger = _new_ledger(baseline, args.migration_boundary, args.migration_reference)
    _write_ledger(args.state, ledger)
    return ledger


def migrate(args: argparse.Namespace) -> dict[str, Any]:
    if args.state.exists():
        raise LedgerError(f"refusing to overwrite existing ledger: {args.state}")
    try:
        legacy = json.loads(args.legacy_state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LedgerError(f"invalid legacy state {args.legacy_state}: {error}") from error
    if not isinstance(legacy, dict) or not isinstance(legacy.get("last_reviewed_upstream"), str):
        raise LedgerError("legacy state must contain last_reviewed_upstream; inspect it before migration")
    baseline = _resolve_commit(args.repo, args.baseline, "baseline")
    legacy_checkpoint = _resolve_commit(args.repo, legacy["last_reviewed_upstream"], "legacy checkpoint")
    if baseline != legacy_checkpoint:
        raise LedgerError("--baseline must exactly resolve to legacy last_reviewed_upstream")
    ledger = _new_ledger(baseline, args.migration_boundary, args.migration_reference)
    _write_ledger(args.state, ledger)
    return ledger


def record(args: argparse.Namespace) -> dict[str, Any]:
    ledger = _load_ledger(args.state)
    if args.outcome not in TERMINAL_OUTCOMES:
        raise LedgerError(f"outcome must be terminal: {', '.join(TERMINAL_OUTCOMES)}")
    if not args.reason or not args.reason.strip():
        raise LedgerError("a non-empty reason is required for every terminal outcome")
    if not args.upstream_version or not args.upstream_version.strip():
        raise LedgerError("a non-empty --upstream-version is required")
    if not FULL_SHA.fullmatch(args.sha):
        raise LedgerError("--sha must be an exact full 40-character upstream SHA")
    if args.outcome in PRIVATE_COMMIT_OUTCOMES and not args.private_commit:
        raise LedgerError(f"{args.outcome} requires at least one --private-commit")
    if args.outcome not in PRIVATE_COMMIT_OUTCOMES and args.private_commit:
        raise LedgerError(f"{args.outcome} must not claim private commits")
    if any(not FULL_SHA.fullmatch(commit) for commit in args.private_commit):
        raise LedgerError("every --private-commit must be a full 40-character SHA")
    if args.private_commit:
        private_ref = _resolve_named_private_ref(args.repo, args.private_ref)
        for private_commit in args.private_commit:
            _resolve_commit(args.repo, private_commit, "private commit")
            try:
                _git(args.repo, "merge-base", "--is-ancestor", private_commit, private_ref)
            except LedgerError as error:
                raise LedgerError(
                    f"private commit {private_commit} is not reachable from private ref {args.private_ref!r}"
                ) from error

    _target, commits = _pending(args.repo, ledger, args.target)
    if not commits:
        raise LedgerError("no unresolved upstream commit remains for this target")
    expected = commits[0]
    if args.sha != expected["sha"]:
        raise LedgerError(f"out-of-order or unknown upstream SHA; next required commit is {expected['sha']}")

    entry = {
        "upstream": {"version": args.upstream_version.strip(), **expected},
        "outcome": args.outcome,
        "reason": args.reason.strip(),
        "private_commits": args.private_commit,
        "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    # One atomic replacement makes the durable history entry and checkpoint inseparable.
    ledger["entries"].append(entry)
    ledger["checkpoint"] = expected["sha"]
    _write_ledger(args.state, ledger)
    return entry


def summary(args: argparse.Namespace) -> dict[str, Any]:
    ledger = _load_ledger(args.state)
    payload = _next_payload(args.repo, ledger, args.target)
    counts = {outcome: 0 for outcome in TERMINAL_OUTCOMES}
    for entry in ledger["entries"]:
        outcome = entry.get("outcome")
        if outcome in counts:
            counts[outcome] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "checkpoint": payload["checkpoint"],
        "target": payload["target"],
        "next": payload["next"],
        "pending_count": payload["remaining"],
        "outcomes": counts,
        "entries": ledger["entries"],
        "migration": ledger["migration"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="checkout containing upstream commits")
    commands = parser.add_subparsers(dest="command", required=True)

    def state_argument(command: argparse.ArgumentParser) -> None:
        command.add_argument("--state", type=Path, required=True, help="durable ledger JSON path")

    def migration_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--baseline", required=True, help="explicit pre-ledger checkpoint")
        command.add_argument("--migration-boundary", required=True, help="honest pre-ledger history boundary")
        command.add_argument("--migration-reference", action="append", required=True, help="reference for pre-ledger history (repeatable)")

    init = commands.add_parser("init", help="create an empty ledger from an explicit baseline")
    state_argument(init)
    migration_arguments(init)

    migration = commands.add_parser("migrate", help="safely seed a new ledger from legacy state")
    state_argument(migration)
    migration.add_argument("--legacy-state", type=Path, required=True, help="read-only legacy state containing last_reviewed_upstream")
    migration_arguments(migration)

    next_command = commands.add_parser("next", help="report the exact oldest unresolved upstream commit")
    state_argument(next_command)
    next_command.add_argument("--target", required=True, help="upstream target revision")

    record_command = commands.add_parser("record", help="atomically record only the next terminal outcome")
    state_argument(record_command)
    record_command.add_argument("--target", required=True, help="upstream target revision")
    record_command.add_argument("--sha", required=True, help="exact next upstream full SHA")
    record_command.add_argument("--outcome", required=True, help="terminal outcome")
    record_command.add_argument("--upstream-version", required=True, help="upstream release/version containing this commit")
    record_command.add_argument("--reason", help="factual terminal-outcome reason")
    record_command.add_argument("--private-commit", action="append", default=[], help="private full SHA for ported/amended outcomes")
    record_command.add_argument("--private-ref", default="feature/shared-logical-evs", help="private branch/ref that must reach every --private-commit")

    summary_command = commands.add_parser("summary", help="emit cron-consumable JSON ledger status")
    state_argument(summary_command)
    summary_command.add_argument("--target", required=True, help="upstream target revision")

    args = parser.parse_args()
    args.repo = args.repo.resolve()
    try:
        if args.command == "init":
            result = initialize(args)
        elif args.command == "migrate":
            result = migrate(args)
        elif args.command == "next":
            result = _next_payload(args.repo, _load_ledger(args.state), args.target)
        elif args.command == "record":
            result = record(args)
        else:
            result = summary(args)
    except LedgerError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

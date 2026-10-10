"""Regression coverage for module-level test stubs."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_shared_test_stubs_do_not_block_currency_module_collection():
    """Shared test imports must restore their lightweight package stubs."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/test_auto_update.py",
            "tests/test_cloud_flow_reporter.py",
            "tests/test_currency.py",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr

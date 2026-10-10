"""Automated shared command sequences are scoped to one serialized evaluation."""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "powersync_nir"
    / "__init__.py"
)


def _auto_evaluator() -> ast.AsyncFunctionDef:
    setup = next(
        node
        for node in ast.parse(SOURCE.read_text()).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
    )
    return next(
        node
        for node in ast.walk(setup)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "auto_evaluate_automations"
    )


def test_auto_evaluation_serializes_and_cleans_shared_sequence_budget():
    evaluator = _auto_evaluator()
    source = ast.get_source_segment(SOURCE.read_text(), evaluator) or ""

    assert "async with auto_evaluation_lock:" in source
    assert "finally:" in source
    assert "_clear_automated_shared_loadpoint_cycle(hass, entry)" in source
    assert "_begin_automated_shared_loadpoint_cycle(hass, entry)" in SOURCE.read_text()

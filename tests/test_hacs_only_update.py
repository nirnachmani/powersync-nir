"""Retiring PowerSync's notification-only update entity leaves HACS in charge."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "power_sync"
INIT = COMPONENT / "__init__.py"


def _init_tree() -> ast.Module:
    return ast.parse(INIT.read_text())


def test_only_hacs_exposes_an_installable_powersync_update():
    tree = _init_tree()
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "PLATFORMS"
    )
    assert isinstance(assignment.value, ast.List)
    platforms = {
        node.attr for node in assignment.value.elts
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Platform"
    }
    assert "SENSOR" in platforms
    assert "UPDATE" not in platforms
    assert not (COMPONENT / "update.py").exists()


def test_retired_update_registry_cleanup_is_scoped_to_current_entry():
    tree = _init_tree()
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_remove_retired_power_sync_update_entity"
    )
    setup = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "async_setup_entry"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == helper.name
        for node in ast.walk(setup)
    )

    owned = SimpleNamespace(config_entry_id="entry-a")
    foreign = SimpleNamespace(config_entry_id="entry-b")
    class Registry:
        def __init__(self):
            self.record = owned
            self.removed = []
            self.lookups = []
        def async_get_entity_id(self, domain, platform, unique_id):
            self.lookups.append((domain, platform, unique_id))
            return "update.power_sync_update"
        def async_get(self, entity_id):
            return self.record
        def async_remove(self, entity_id):
            self.removed.append(entity_id)

    registry = Registry()
    namespace = {
        "er": SimpleNamespace(async_get=lambda hass: registry),
        "DOMAIN": "power_sync",
    }
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(INIT), "exec"), namespace)
    cleanup = namespace[helper.name]
    cleanup(SimpleNamespace(), SimpleNamespace(entry_id="entry-a"))
    assert registry.lookups == [("update", "power_sync", "entry-a_update")]
    assert registry.removed == ["update.power_sync_update"]
    registry.record = foreign
    cleanup(SimpleNamespace(), SimpleNamespace(entry_id="entry-a"))
    assert registry.removed == ["update.power_sync_update"]

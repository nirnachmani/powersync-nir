"""The integration option controls both output and expensive capture setup."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/power_sync'


def load_diagnostics():
    spec = importlib.util.spec_from_file_location('decision_diagnostics_option_test', ROOT / 'decision_diagnostics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_disabled_diagnostics_do_not_create_writer_or_solver_capture(monkeypatch):
    module = load_diagnostics()
    monkeypatch.setattr(module, 'AsyncDecisionWriter', lambda *a, **k: (_ for _ in ()).throw(AssertionError('writer started')))
    assert module.start_entry_diagnostics(None, 'entry', '1', enabled=False) is None


def test_option_form_saves_value_without_erasing_other_options():
    tree = ast.parse((ROOT / 'config_flow.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PowerSyncOptionsFlow')
    node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'async_step_decision_logging')
    save = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_save_and_finish')
    source = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node, save], type_ignores=[])
    ast.fix_missing_locations(source)
    ns = {'vol': vol, 'BooleanSelector': lambda: bool, 'CONF_DECISION_LOGGING_ENABLED': 'decision_logging_enabled'}
    exec(compile(source, str(ROOT / 'config_flow.py'), 'exec'), ns)
    class Flow:
        config_entry = SimpleNamespace(options={'unrelated': 'kept'})
        def _get_option(self, key, default): return self.config_entry.options.get(key, default)
        _save_and_finish = ns['_save_and_finish']
        def _apply_legacy_data_key_removals(self): pass
        def async_create_entry(self, *, title, data): return data
        def async_show_form(self, **kwargs): return kwargs
    flow = Flow()
    form = asyncio.run(ns['async_step_decision_logging'](flow))
    assert form['data_schema']({}) == {'decision_logging_enabled': True}
    assert asyncio.run(ns['async_step_decision_logging'](flow, {'decision_logging_enabled': False})) == {'unrelated': 'kept', 'decision_logging_enabled': False}
    flow.config_entry.options = {'decision_logging_enabled': False}
    assert asyncio.run(ns['async_step_decision_logging'](flow))['data_schema']({}) == {'decision_logging_enabled': False}


def test_entry_setup_uses_option_and_skips_observer_registration_when_disabled():
    source = (ROOT / '__init__.py').read_text()
    tree = ast.parse(source)
    setup = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'async_setup_entry')
    call = next(n for n in ast.walk(setup) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'start_entry_diagnostics')
    enabled = next(k.value for k in call.keywords if k.arg == 'enabled')
    assert ast.unparse(enabled) == 'entry.options.get(CONF_DECISION_LOGGING_ENABLED, True)'
    guards = [n for n in ast.walk(setup) if isinstance(n, ast.If) and ast.unparse(n.test) == 'diagnostics is not None']
    assert guards and any('decision_diagnostics' in ast.unparse(n) for n in guards[0].body)


def test_option_translations_exist():
    for filename in ('strings.json', 'translations/en.json'):
        data = json.loads((ROOT / filename).read_text())
        advanced = data['options']['step']['advanced']['menu_options']
        assert 'decision_logging' in advanced
        assert 'decision_logging_enabled' in data['options']['step']['decision_logging']['data']

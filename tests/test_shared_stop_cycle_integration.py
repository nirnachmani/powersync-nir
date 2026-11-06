"""Startup and serialized-cycle wiring for durable shared stop fences."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / 'custom_components/power_sync/__init__.py'


def setup_node():
    return next(n for n in ast.parse(SOURCE.read_text()).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == 'async_setup_entry')


def nested(name):
    return next(n for n in setup_node().body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def test_startup_load_is_awaited_after_store_and_before_setup_work():
    setup = setup_node()
    loads = calls(setup, 'async_load_pending_shared_stops')
    assert len(loads) == 1
    load = loads[0]
    assert len(load.args) == 2
    store_load = next(n for n in ast.walk(setup) if isinstance(n, ast.Await)
                      and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                      and n.value.func.attr == 'async_load'
                      and isinstance(n.value.func.value, ast.Name)
                      and n.value.func.value.id == 'automation_store')
    assert store_load.lineno < load.lineno
    assert any(isinstance(n, ast.Await) and n.value is load for n in ast.walk(setup))
    assert load.lineno < min(n.lineno for n in calls(setup, 'async_forward_entry_setups'))
    # The load cannot be wrapped in a handler that lets setup proceed on failure.
    assert not any(isinstance(n, ast.Try) and n.lineno <= load.lineno <= n.end_lineno
                   for n in ast.walk(setup))
    # The later replacement of entry data must carry the restored fence/runtime.
    replacement = next(n for n in setup.body if isinstance(n, ast.Assign)
                       and any(ast.unparse(t) == 'hass.data[DOMAIN][entry.entry_id]' for t in n.targets)
                       and isinstance(n.value, ast.Dict))
    keys = {k.value for k in replacement.value.keys if isinstance(k, ast.Constant)}
    assert {'_shared_stop_fences', 'dynamic_ev_state'} <= keys


@pytest.mark.parametrize('failure', [False, True])
def test_startup_recovers_against_loaded_store_or_aborts(monkeypatch, failure):
    import sys
    setup = setup_node()
    start = next(i for i, n in enumerate(setup.body)
                 if isinstance(n, ast.Assign) and any(
                     isinstance(t, ast.Name) and t.id == 'automation_store'
                     for t in n.targets))
    end = next(i for i, n in enumerate(setup.body)
               if calls(n, 'async_load_pending_shared_stops'))
    body = setup.body[start:end + 1]
    func = ast.AsyncFunctionDef(name='startup', args=ast.arguments(
        posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=body, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[]))
    events = []
    class Store:
        def __init__(self, hass):
            pass
        async def async_load(self):
            events.append('store')
    hass = SimpleNamespace(data={})
    entry = SimpleNamespace(entry_id='entry')
    async def load(hass_arg, entry_arg):
        assert events == ['store']
        assert isinstance(hass_arg.data['power_sync']['entry']['automation_store'], Store)
        assert entry_arg is entry
        events.append('fence')
        if failure:
            raise RuntimeError('recovery failed')
        hass_arg.data['power_sync']['entry']['_shared_stop_fences'] = {'generic_ev': True}
    monkeypatch.setitem(sys.modules, 'custom_components.power_sync.automations.actions',
                        SimpleNamespace(async_load_pending_shared_stops=load))
    env = {'__name__': 'custom_components.power_sync', '__package__': 'custom_components.power_sync',
           'hass': hass, 'entry': entry, 'DOMAIN': 'power_sync', 'AutomationStore': Store}
    exec(compile(module, str(SOURCE), 'exec'), env)
    if failure:
        with pytest.raises(RuntimeError, match='recovery failed'):
            asyncio.run(env['startup']())
    else:
        asyncio.run(env['startup']())
        assert hass.data['power_sync']['entry']['_shared_stop_fences']['generic_ev']
    assert events == ['store', 'fence']


def cycle_harness(monkeypatch, reconcile):
    node = nested('auto_evaluate_automations')
    # Retain the real lock and body; replace unrelated cleanup with a marker.
    lock = node.body[1] if isinstance(node.body[0], ast.Expr) else node.body[0]
    assert isinstance(lock, ast.AsyncWith)
    for item in lock.body:
        if isinstance(item, ast.Try):
            item.finalbody = ast.parse('events.append("cleanup")').body
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    import sys
    fake = SimpleNamespace(async_reconcile_pending_shared_stops=reconcile)
    monkeypatch.setitem(sys.modules, 'custom_components.power_sync.automations.actions', fake)
    events = []
    async def evaluate(now):
        events.append('evaluate')
    env = {'__name__': 'custom_components.power_sync', '__package__': 'custom_components.power_sync',
           'auto_evaluation_lock': asyncio.Lock(), 'hass': object(), 'entry': object(),
           '_auto_evaluate_automations_unlocked': evaluate, 'events': events}
    exec(compile(module, str(SOURCE), 'exec'), env)
    return env['auto_evaluate_automations'], events


def test_settlement_precedes_cycle_even_without_enabled_modes(monkeypatch):
    seen = []
    async def reconcile(hass, entry):
        seen.append('settle')
    cycle, events = cycle_harness(monkeypatch, reconcile)
    # The reconciliation sits in the outer lock, before entering any of the
    # mode-dependent evaluation branches or the final handoff.
    asyncio.run(cycle(None))
    assert seen == ['settle']
    assert events == ['evaluate', 'cleanup']
    assert calls(nested('auto_evaluate_automations'), 'async_reconcile_pending_shared_stops')


def test_settlement_failure_cannot_reach_evaluation_or_final_handoff(monkeypatch):
    async def reconcile(hass, entry):
        raise RuntimeError('settlement failed')
    cycle, events = cycle_harness(monkeypatch, reconcile)
    with pytest.raises(RuntimeError, match='settlement failed'):
        asyncio.run(cycle(None))
    assert events == []

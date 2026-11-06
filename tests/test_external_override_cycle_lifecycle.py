"""Exercise the actual setup-entry cycle callback with real stop transactions.

HA setup and physical I/O are replaced; the extracted, unmodified cycle body,
policy resolver, ownership and transaction implementations are production code.
"""
import ast
import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_shared_loadpoint_action_guard import _Entry, _Hass, _generic_params, actions, ownership
from test_shared_stop_storage import Store
from power_sync.automations import external_session_reconciler as reconciler

SOURCE = Path(__file__).parents[1] / 'custom_components/power_sync/__init__.py'
PROFILE = 'shared_ev_profile_a'


def cycle_callback(hass, entry, evaluate):
    setup = next(n for n in ast.parse(SOURCE.read_text()).body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == 'async_setup_entry')
    node = next(n for n in setup.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == 'auto_evaluate_automations')
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    env = {'__name__': 'power_sync', '__package__': 'power_sync',
           'hass': hass, 'entry': entry, 'DOMAIN': 'power_sync', 'Mapping': Mapping,
           'auto_evaluation_lock': asyncio.Lock(), '_LOGGER': logging.getLogger(__name__),
           '_auto_evaluate_automations_unlocked': evaluate}
    exec(compile(module, str(SOURCE), 'exec'), env)
    return env['auto_evaluate_automations']


@pytest.mark.parametrize('backend', ['generic', 'evac'])
@pytest.mark.parametrize('policy', ['override', 'yield'])
def test_external_override_cycle_stop_lifecycle(monkeypatch, backend, policy):
    async def run():
        actions._dynamic_ev_state.clear()
        hass, entry = _Hass(), _Entry()
        hass.states.async_all = lambda: []
        binding = 'generic_ev' if backend == 'generic' else 'sigenergy_charger'
        params = {**_generic_params(), 'vehicle_id': PROFILE, 'external_control_policy': policy}
        if backend == 'evac':
            entry.options = {**entry.options, 'generic_charger_enabled': False,
                             'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac',
                             'sigenergy_charger_host': 'charger.invalid'}
            params = {'charger_type': 'sigenergy', 'vehicle_id': PROFILE, 'external_control_policy': policy}
        store = Store({'automations': [], 'vehicle_charging_configs': [params]})
        data = hass.data['power_sync'][entry.entry_id]
        data['automation_store'] = store
        states = {}
        original_get = hass.states.get
        hass.states.get = lambda key: states.get(key) or original_get(key)
        states['sensor.shared_ev_power'] = SimpleNamespace(state='0', attributes={'unit_of_measurement': 'W'}, last_reported=datetime.now(timezone.utc))
        stops = []
        class Controller:
            async def connect(self): return True
            async def stop_charging(self):
                assert self._shared_write_authorized()
                stops.append('stop')
                return True
            async def disconnect(self): pass
            _read_input_registers = AsyncMock(return_value=None)
        controller = Controller()
        monkeypatch.setattr(actions, '_new_sigenergy_charger', lambda config: controller)
        count = lambda: hass.services.async_call.await_count if backend == 'generic' else len(stops)
        active = True
        async def evaluate(now):
            # Simulate the unlocked evaluator's fresh observation, retaining the
            # real reconciliation transition and production end-of-cycle logic.
            previous = reconciler.load_reconciliation_state(hass, entry, binding)
            if backend == 'generic':
                obs = reconciler.generic_power_observation(binding_id=binding, power_kw=7.2 if active else 0, observed_at=now, now=now)
            else:
                obs = reconciler.evac_observation_from_state(binding_id=binding, state=SimpleNamespace(charger_type='evac', is_connected=True, is_charging=active, power_kw=7.2 if active else 0), observed_at=now)
            state = reconciler.reconcile_shared_external_session(obs, previous=previous)
            state.active_profile_id = PROFILE
            await reconciler.persist_reconciliation_state(hass, entry, binding, state)
            data['_shared_loadpoint_cycle_context'] = {'binding_id': binding, 'active_profile_id': PROFILE,
                'origin': state.origin, 'physical_active': state.physical_active,
                'observed_at': now, 'evidence': state.evidence}
        cycle = cycle_callback(hass, entry, evaluate)
        await cycle(datetime.now(timezone.utc))
        lease = ownership.get_ev_ownership(hass, entry, binding)[1]
        assert lease and lease['owner'] == 'external' and lease['active_profile_id'] == PROFILE
        if policy == 'yield':
            assert count() == 0
            assert not actions.is_shared_stop_fenced(hass, entry, binding)
            return
        assert count() == 1
        assert actions.is_shared_stop_fenced(hass, entry, binding)
        assert reconciler.load_reconciliation_state(hass, entry, binding).stop_outcome != {'status': 'confirmed'}
        token = lease.get('resolver_stop_lease_token')
        assert token
        # Age the actual transaction clock; the cycle's now argument alone
        # does not drive the settlement/alert timeout.
        pending = actions._dynamic_ev_state[entry.entry_id][binding]['pending_stop']
        pending['requested_at'] -= timedelta(seconds=121)
        from power_sync import action_events
        monkeypatch.setattr(action_events, '_notification', lambda *args, **kwargs: True)
        data.setdefault('ev_unverified_stop_alerts', {})[(binding, pending['record']['generation'])] = {
            'entry_id': entry.entry_id, 'loadpoint_id': binding,
            'episode_id': pending['record']['generation'],
            'first_stop_at': pending['requested_at'].isoformat(),
            'warned': False, 'cleared': False,
        }
        await cycle(datetime.now(timezone.utc))
        assert pending['record']['alerted'] is True
        assert count() == 1
        assert actions.is_shared_stop_fenced(hass, entry, binding)
        assert ownership.get_ev_ownership(hass, entry, binding)[1] is lease
        assert lease['resolver_stop_lease_token'] == token
        active = False
        states['sensor.shared_ev_power'].last_reported = datetime.now(timezone.utc)
        controller._read_input_registers.return_value = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        await cycle(datetime.now(timezone.utc))
        assert count() == 1
        assert not actions.is_shared_stop_fenced(hass, entry, binding)
        assert ownership.get_ev_ownership(hass, entry, binding)[1] is None
        assert reconciler.load_reconciliation_state(hass, entry, binding).stop_outcome == {'status': 'confirmed'}
        active = True
        controller._read_input_registers.return_value = None
        await cycle(datetime.now(timezone.utc) + timedelta(seconds=1))
        assert count() == 2
        assert actions.is_shared_stop_fenced(hass, entry, binding)
        new_lease = ownership.get_ev_ownership(hass, entry, binding)[1]
        assert new_lease and new_lease.get('resolver_stop_lease_token') != token
    try:
        asyncio.run(run())
    finally:
        actions._dynamic_ev_state.clear()

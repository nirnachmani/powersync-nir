"""Headroom permission never outlives the shared EV selector or lease."""
import pytest

from test_shared_loadpoint_action_guard import _Entry, _Hass, ownership
from power_sync.solar_ev_headroom import candidate_token, shared_candidate_current


@pytest.mark.parametrize('backend,physical', [('generic', 'generic_ev'), ('sigenergy', 'sigenergy_charger')])
def test_discovery_requires_current_selected_profile_and_physical_lease(backend, physical):
    hass, entry = _Hass(), _Entry()
    if backend == 'sigenergy':
        entry.options = {**entry.options, 'generic_charger_enabled': False,
                         'sigenergy_charger_enabled': True, 'sigenergy_charger_type': 'evac'}
    params = {'charger_type': backend, 'shared_loadpoint_binding': True,
              'active_logical_vehicle_id': 'shared_ev_profile_a',
              'logical_vehicle_id': 'shared_ev_profile_a',
              'owner_mode': 'solar_surplus', 'dynamic_mode': 'solar_surplus'}
    state = {'params': params}
    ownership.claim_ev_ownership(hass, entry, physical, owner_mode='solar_surplus',
                                 extra={'active_profile_id': 'shared_ev_profile_a'})
    assert shared_candidate_current(hass, entry, physical, state)
    token = candidate_token(state)
    hass.states.get('sensor.connected_vehicle').state = 'tesla'
    assert not shared_candidate_current(hass, entry, physical, state)
    hass.states.get('sensor.connected_vehicle').state = 'tank'
    ownership.claim_ev_ownership(hass, entry, physical, owner_mode='solar_surplus',
                                 extra={'active_profile_id': 'shared_ev_profile_b'})
    assert not shared_candidate_current(hass, entry, physical, state)
    params['active_logical_vehicle_id'] = 'shared_ev_profile_b'
    assert candidate_token(state) != token

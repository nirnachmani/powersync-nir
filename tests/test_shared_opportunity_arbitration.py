"""Revised positive-price Solar vs Price-Level arbitration."""
import importlib.util
import sys
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'custom_components/power_sync/automations/shared_opportunity.py'
spec = importlib.util.spec_from_file_location('test_shared_opportunity', path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
SolarBoundary, choose_positive_price_owner = module.SolarBoundary, module.choose_positive_price_owner


def test_low_price_prefers_price_until_solar_capacity_is_sustained():
    state = SolarBoundary()
    def choose(t, capacity):
        return choose_positive_price_owner(state, now=t, solar_eligible=True,
            solar_capacity_kw=capacity, maximum_kw=7.0, price_cents=8,
            opportunity_price_cents=10, price_eligible=True, start_delay_s=180, stop_delay_s=180)
    assert choose(0, 7) == 'price_level'
    assert choose(179, 7) == 'price_level'
    assert choose(180, 7) == 'solar_surplus'
    assert choose(181, 6) == 'solar_surplus'
    assert choose(360, 6) == 'solar_surplus'
    assert choose(361, 6) == 'price_level'


def test_solar_boundary_resets_when_evidence_changes():
    state = SolarBoundary()
    def choose(t, capacity):
        return choose_positive_price_owner(state, now=t, solar_eligible=True,
            solar_capacity_kw=capacity, maximum_kw=7, price_cents=8,
            opportunity_price_cents=10, price_eligible=True, start_delay_s=180, stop_delay_s=180)
    assert choose(0, 7) == 'price_level'
    assert choose(100, 6) == 'price_level'
    assert choose(101, 7) == 'price_level'
    assert choose(280, 7) == 'price_level'
    assert choose(281, 7) == 'solar_surplus'
    assert choose(300, 6) == 'solar_surplus'
    assert choose(400, 7) == 'solar_surplus'
    assert choose(401, 6) == 'solar_surplus'
    assert choose(580, 6) == 'solar_surplus'
    assert choose(581, 6) == 'price_level'


def test_recovery_label_does_not_override_opportunity_price_rule():
    state = SolarBoundary()
    result = choose_positive_price_owner(state, now=0, solar_eligible=True,
        solar_capacity_kw=3, maximum_kw=7, price_cents=15,
        opportunity_price_cents=10, price_eligible=True, start_delay_s=180, stop_delay_s=180)
    assert result == 'solar_surplus'


def test_request_identity_is_stable_only_while_policy_facts_match():
    from datetime import datetime, timedelta, timezone
    entry = {}
    now = datetime.now(timezone.utc)
    facts = {'profile': 'shared_ev_profile_a', 'mode': 'price_level_opportunity',
             'selection_changed': now, 'power_kw': 4.0, 'min_power_kw': 1.4,
             'allow_grid': True, 'allow_battery': False}
    first, changed = module.update_opportunity_request(entry, facts, now)
    assert changed and first['generation'] is not None
    same, changed = module.update_opportunity_request(entry, facts, now + timedelta(seconds=30))
    assert not changed and same is first
    assert same['decided_at'] == now + timedelta(seconds=30)
    changed_request, changed = module.update_opportunity_request(entry, {**facts, 'allow_grid': False}, now)
    assert changed and changed_request is not first
    assert changed_request['generation'] is not first['generation']
    expired, changed = module.update_opportunity_request(entry, {**facts, 'allow_grid': False}, now + timedelta(seconds=91))
    assert changed and expired is not changed_request
    assert module.withdraw_opportunity_request(entry)
    assert not module.withdraw_opportunity_request(entry)


def test_loss_of_solar_eligibility_does_not_wait_for_boundary_timer():
    state = SolarBoundary(full=True)
    result = choose_positive_price_owner(state, now=10, solar_eligible=False,
        solar_capacity_kw=6, maximum_kw=7, price_cents=15,
        opportunity_price_cents=10, price_eligible=True, start_delay_s=180, stop_delay_s=180)
    assert result == 'price_level'
    assert not state.full


def test_no_solar_allows_price_and_nonpositive_price_is_not_reclassified():
    state = SolarBoundary()
    kwargs = dict(solar_eligible=False, solar_capacity_kw=0, maximum_kw=7,
        opportunity_price_cents=10, price_eligible=True, start_delay_s=180, stop_delay_s=180)
    assert choose_positive_price_owner(state, now=0, price_cents=8, **kwargs) == 'price_level'
    assert choose_positive_price_owner(state, now=1, price_cents=0, **kwargs) is None
    assert choose_positive_price_owner(state, now=2, price_cents=None, **kwargs) is None

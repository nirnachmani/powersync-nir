"""Tests for profile-owned state of charge on a shared physical loadpoint."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from test_shared_loadpoint_binding import (
    PROFILE_A_ID,
    PROFILE_B_ID,
    _entry,
    _load_shared_loadpoint,
    _options,
)


shared_loadpoint = _load_shared_loadpoint()


class FakeHass:
    def __init__(self, states: dict[str, object]):
        self.states = SimpleNamespace(
            get=lambda entity_id: (
                SimpleNamespace(
                    state=states[entity_id],
                    last_updated=f"updated:{entity_id}",
                )
                if entity_id in states
                else None
            )
        )


def test_profile_soc_resolver_returns_each_profiles_own_valid_state():
    resolver = getattr(shared_loadpoint, "resolve_shared_profile_soc", None)
    assert resolver is not None
    entry = _entry(
        **_options(
            shared_loadpoint_profile_a_soc_entity="sensor.tank_soc",
            shared_loadpoint_profile_b_soc_entity="sensor.tesla_soc",
        )
    )
    hass = FakeHass({"sensor.tank_soc": "0", "sensor.tesla_soc": "64.25"})

    a_sample = resolver(hass, entry, PROFILE_A_ID)
    b_sample = resolver(hass, entry, PROFILE_B_ID)

    assert (a_sample.value, a_sample.entity_id, a_sample.source, a_sample.timestamp) == (
        0.0,
        "sensor.tank_soc",
        "state",
        "updated:sensor.tank_soc",
    )
    assert (b_sample.value, b_sample.entity_id, b_sample.source, b_sample.timestamp) == (
        64.25,
        "sensor.tesla_soc",
        "state",
        "updated:sensor.tesla_soc",
    )


def test_profile_soc_resolver_fails_closed_without_cross_profile_or_legacy_fallback():
    resolver = getattr(shared_loadpoint, "resolve_shared_profile_soc", None)
    assert resolver is not None
    entry = _entry(
        **_options(
            shared_loadpoint_profile_a_soc_entity="sensor.a_soc",
            shared_loadpoint_profile_b_soc_entity="sensor.b_soc",
            generic_charger_soc_entity="sensor.legacy_primary",
            generic_charger_soc_entity_2="sensor.legacy_fallback",
        )
    )

    assert resolver(
        FakeHass({
            "sensor.b_soc": "73",
            "sensor.legacy_primary": "44",
            "sensor.legacy_fallback": "45",
        }),
        entry,
        PROFILE_A_ID,
    ) is None


@pytest.mark.parametrize("state", [None, "", "unknown", "unavailable", "wat", "nan", "inf", "-inf", "-0.1", "100.1"])
def test_profile_soc_resolver_rejects_invalid_state(state):
    resolver = getattr(shared_loadpoint, "resolve_shared_profile_soc", None)
    assert resolver is not None
    entry = _entry(**_options(shared_loadpoint_profile_a_soc_entity="sensor.a_soc"))

    assert resolver(FakeHass({"sensor.a_soc": state}), entry, PROFILE_A_ID) is None


def test_profile_soc_resolver_is_disabled_without_a_complete_shared_binding():
    resolver = getattr(shared_loadpoint, "resolve_shared_profile_soc", None)
    assert resolver is not None
    entry = _entry(
        generic_charger_enabled=True,
        shared_loadpoint_profile_a_soc_entity="sensor.a_soc",
    )

    assert resolver(FakeHass({"sensor.a_soc": "55"}), entry, PROFILE_A_ID) is None


def test_shared_binding_validation_requires_one_supported_backend_and_unique_soc_entities():
    validate = getattr(shared_loadpoint, "validate_shared_loadpoint_options", None)
    assert validate is not None

    assert validate(_options(generic_charger_enabled=False)) == "shared_loadpoint_no_supported_backend"
    assert validate(
        _options(sigenergy_charger_enabled=True, sigenergy_charger_type="evac")
    ) == "shared_loadpoint_multiple_backends"
    assert validate(
        _options(
            generic_charger_enabled=False,
            sigenergy_charger_enabled=True,
            sigenergy_charger_type="evdc",
        )
    ) == "shared_loadpoint_no_supported_backend"
    assert validate(
        _options(
            shared_loadpoint_profile_a_soc_entity="sensor.same_soc",
            shared_loadpoint_profile_b_soc_entity=" sensor.same_soc ",
        )
    ) == "duplicate_shared_loadpoint_soc_entity"
    assert validate(
        _options(
            shared_loadpoint_profile_a_soc_entity="",
            shared_loadpoint_profile_b_soc_entity="",
        )
    ) is None

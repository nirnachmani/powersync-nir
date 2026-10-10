"""Behavior specification for the optional shared-loadpoint diagnostics surface."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "custom_components" / "power_sync" / "automations" / "shared_loadpoint_diagnostics.py"
)
SPEC = importlib.util.spec_from_file_location("shared_loadpoint_diagnostics_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

NOW = datetime(2026, 10, 10, 4, 0, tzinfo=timezone.utc)


def _snapshot(**overrides):
    snapshot = {
        "binding_id": "generic_ev",
        "selected_profile_id": "shared_ev_profile_a",
        "selected_profile_name": "Tank",
        "physical_active": True,
        "origin": "external",
        "evidence": "fresh_power",
        "observed_at": NOW.isoformat(),
        "stop_outcome": None,
        "ownership": None,
        "last_command": None,
        "decision": {"allowed": False, "responsible_mode": "scheduled", "reason": "outside window"},
        "external_control_policy": "override",
    }
    snapshot.update(overrides)
    return snapshot


def test_generic_external_override_without_allowed_decision_projects_stop():
    result = module.project_shared_loadpoint_diagnostics(_snapshot())

    assert result["desired_action"] == "stop"
    assert result["reason"] == "outside window"
    assert result["binding_id"] == "generic_ev"
    assert result["selected_profile"] == {"id": "shared_ev_profile_a", "name": "Tank"}


def test_evac_external_yield_projects_allow_without_control_side_effects():
    result = module.project_shared_loadpoint_diagnostics(
        _snapshot(binding_id="sigenergy_charger", external_control_policy="yield")
    )

    assert result["desired_action"] == "allow"
    assert result["reason"] == "external control policy is yield"


@pytest.mark.parametrize("mode", ["solar_surplus", "scheduled", "smart_schedule", "price_level"])
def test_allowed_responsible_modes_project_adopt(mode):
    result = module.project_shared_loadpoint_diagnostics(
        _snapshot(decision={"allowed": True, "responsible_mode": mode, "reason": "admitted"})
    )

    assert result["desired_action"] == "adopt"
    assert result["reason"] == "admitted"


@pytest.mark.parametrize(
    ("selected_profile_id", "evidence", "observed_at", "expected_reason"),
    [
        (None, "fresh_power", NOW.isoformat(), "no selected shared profile"),
        ("shared_ev_profile_a", "stale_or_missing_power", (NOW - timedelta(seconds=91)).isoformat(), "shared loadpoint evidence is stale or unknown"),
    ],
)
def test_missing_or_stale_control_context_fails_safe(selected_profile_id, evidence, observed_at, expected_reason):
    result = module.project_shared_loadpoint_diagnostics(
        _snapshot(selected_profile_id=selected_profile_id, evidence=evidence, observed_at=observed_at)
    )

    assert result["desired_action"] is None
    assert result["reason"] == expected_reason


def test_projection_exposes_logical_mapping_soc_truth_and_session_provenance_without_cache_authority():
    result = module.project_shared_loadpoint_diagnostics(
        _snapshot(
            live_soc={
                "value": 42,
                "entity_id": "sensor.tank_soc",
                "source": "state",
                "observed_at": NOW.isoformat(),
                "age_seconds": 2.0,
                "valid": True,
            },
            cached_soc={
                "value": 41,
                "updated_at": (NOW - timedelta(minutes=3)).isoformat(),
                "age_seconds": 180.0,
                "valid": True,
            },
            last_block_reason="outside window",
            last_session={
                "logical_vehicle_id": "shared_ev_profile_a",
                "start": {"soc": 40, "entity_id": "sensor.tank_soc", "source": "state"},
                "end": {"soc": 42, "entity_id": "sensor.tank_soc", "source": "state"},
            },
            secret="must-not-appear",
        )
    )

    assert result["mapping"] == {
        "logical_profile_id": "shared_ev_profile_a",
        "physical_loadpoint_id": "generic_ev",
    }
    assert result["soc"]["live"]["value"] == 42
    assert result["soc"]["live"]["valid"] is True
    assert result["soc"]["cache"] == {
        "value": 41,
        "updated_at": (NOW - timedelta(minutes=3)).isoformat(),
        "age_seconds": 180.0,
        "valid": True,
        "authorizes_control": False,
    }
    assert result["soc"]["effective_source"] == "live"
    assert result["last_block_reason"] == "outside window"
    assert result["last_session"]["start"]["entity_id"] == "sensor.tank_soc"
    assert result["last_session"]["end"]["soc"] == 42
    assert "secret" not in result


def test_unknown_selector_clears_mapping_soc_and_session_identity_instead_of_reusing_stale_profile():
    result = module.project_shared_loadpoint_diagnostics(
        _snapshot(
            binding_id=None,
            selected_profile_id=None,
            selected_profile_name="Tank",
            live_soc={"value": 42, "valid": True},
            cached_soc={"value": 41, "valid": True},
            last_session={"logical_vehicle_id": "shared_ev_profile_a"},
        )
    )

    assert result["selected_profile"] == {"id": None, "name": None}
    assert result["mapping"] == {
        "logical_profile_id": None,
        "physical_loadpoint_id": None,
    }
    assert result["soc"] == {"live": None, "cache": None, "effective_source": None}
    assert result["last_session"] is None


def test_projection_preserves_truthful_nulls_and_never_invents_ownership():
    result = module.project_shared_loadpoint_diagnostics(
        _snapshot(
            physical_active=None,
            origin="unknown",
            evidence="failed_or_unknown_evac_read",
            observed_at=None,
            ownership=None,
            last_command=None,
            decision=None,
        )
    )

    assert result["physical_active"] is None
    assert result["observed_at"] is None
    assert result["ownership"] is None
    assert result["last_command"] is None
    assert result["decision"] is None
    assert result["desired_action"] is None


def test_diagnostic_snapshot_persists_evidence_and_compact_selected_decision():
    record = module.diagnostic_snapshot_record(
        _snapshot(decision={"allowed": True, "responsible_mode": "solar_surplus", "reason": "admitted", "ignored": "no"})
    )

    assert record == {
        "binding_id": "generic_ev",
        "selected_profile_id": "shared_ev_profile_a",
        "evidence": "fresh_power",
        "observed_at": NOW.isoformat(),
        "physical_active": True,
        "origin": "external",
        "decision": {"allowed": True, "responsible_mode": "solar_surplus", "reason": "admitted"},
    }


def test_persisted_snapshot_survives_the_transient_cycle_ledger_clear():
    class Store:
        def __init__(self):
            self._data = {"_automated_shared_loadpoint_decision_ledger": {}}
            self.saved = 0

        async def async_save(self):
            self.saved += 1

    class Entry:
        entry_id = "entry-1"

    store = Store()
    hass = type("Hass", (), {"data": {"power_sync": {"entry-1": {"automation_store": store}}}})()

    import asyncio
    asyncio.run(module.persist_shared_loadpoint_diagnostic_snapshot(hass, Entry(), _snapshot()))
    store._data.pop("_automated_shared_loadpoint_decision_ledger")

    assert store.saved == 1
    assert store._data["_shared_loadpoint_diagnostic_snapshot"]["evidence"] == "fresh_power"
    assert store._data["_shared_loadpoint_diagnostic_snapshot"]["decision"] == {
        "allowed": False, "responsible_mode": "scheduled", "reason": "outside window"
    }


def test_endpoint_contract_is_authenticated_and_status_endpoint_is_unchanged():
    source = (ROOT / "custom_components" / "power_sync" / "__init__.py").read_text()

    assert 'url = "/api/power_sync/ev/shared_loadpoints/diagnostics"' in source
    assert 'name = "api:power_sync:ev:shared_loadpoints:diagnostics"' in source
    assert "class SharedLoadpointDiagnosticsView(HomeAssistantView):" in source
    assert "requires_auth = True" in source[source.index("class SharedLoadpointDiagnosticsView"):]
    assert 'return web.json_response({"success": True, "diagnostics": diagnostics})' in source
    status = source[source.index("class EVStatusView(HomeAssistantView):"):source.index("class SharedLoadpointDiagnosticsView(HomeAssistantView):")]
    assert 'url = "/api/power_sync/ev/status"' in status
    assert "shared_loadpoints/diagnostics" not in status

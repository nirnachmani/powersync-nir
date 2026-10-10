"""Behavior tests for truthful logical-EV session SoC attribution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from test_shared_loadpoint_binding import (
    PROFILE_A_ID,
    PROFILE_B_ID,
    _load_session_manager,
)


class _Hass:
    config = SimpleNamespace(config_dir=".")

    async def async_add_executor_job(self, target):
        return target()


def test_managed_logical_session_persists_profile_owned_start_soc_provenance(tmp_path):
    sessions = _load_session_manager()
    manager = sessions.ChargingSessionManager(_Hass(), storage_path=tmp_path / "sessions.json")
    manager._cache_loaded = True

    session = asyncio.run(
        manager.start_session(
            vehicle_id=PROFILE_A_ID,
            logical_vehicle_id=PROFILE_A_ID,
            loadpoint_id="generic_ev",
            mode="scheduled",
            start_soc=42,
            start_soc_entity="sensor.tank_soc",
            start_soc_time="2026-10-10T04:00:00+00:00",
            start_soc_source="state",
        )
    )

    stored = session.to_dict()
    assert stored["vehicle_id"] == PROFILE_A_ID
    assert stored["logical_vehicle_id"] == PROFILE_A_ID
    assert stored["loadpoint_id"] == "generic_ev"
    assert stored["start_soc"] == 42
    assert stored["start_soc_entity"] == "sensor.tank_soc"
    assert stored["start_soc_time"] == "2026-10-10T04:00:00+00:00"
    assert stored["start_soc_source"] == "state"

    asyncio.run(
        manager.end_session(
            "generic_ev",
            "stopped",
            end_soc=47,
            end_soc_entity="sensor.tank_soc",
            end_soc_time="2026-10-10T05:00:00+00:00",
            end_soc_source="state",
        )
    )
    assert session.end_soc == 47
    assert session.end_soc_entity == "sensor.tank_soc"
    assert session.end_soc_time == "2026-10-10T05:00:00+00:00"
    assert session.end_soc_source == "state"


def test_idle_handoff_finalizes_outgoing_logical_session_without_creating_incoming_session(tmp_path):
    sessions = _load_session_manager()
    manager = sessions.ChargingSessionManager(_Hass(), storage_path=tmp_path / "sessions.json")
    manager._cache_loaded = True
    outgoing = asyncio.run(
        manager.start_session(
            vehicle_id=PROFILE_A_ID,
            logical_vehicle_id=PROFILE_A_ID,
            loadpoint_id="generic_ev",
            mode="solar_surplus",
            start_soc=31,
            start_soc_entity="sensor.tank_soc",
            start_soc_time="2026-10-10T03:00:00+00:00",
            start_soc_source="state",
        )
    )
    outgoing.total_energy_kwh = 4.2
    outgoing.start_time = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc).isoformat()

    split = asyncio.run(
        manager.transfer_idle_session_attribution(
            loadpoint_id="generic_ev",
            from_vehicle_id=PROFILE_A_ID,
            to_vehicle_id=PROFILE_B_ID,
            fresh_idle=True,
        )
    )

    assert split is True
    assert manager.active_sessions == {}
    assert outgoing.completed is True
    assert outgoing.vehicle_id == PROFILE_A_ID
    assert outgoing.logical_vehicle_id == PROFILE_A_ID
    assert outgoing.end_soc is None
    assert outgoing.total_energy_kwh == 4.2
    assert len(manager._sessions_cache) == 1
    assert manager._sessions_cache[0] is outgoing


def test_idle_handoff_records_outgoing_profile_live_soc_provenance(tmp_path):
    sessions = _load_session_manager()
    manager = sessions.ChargingSessionManager(_Hass(), storage_path=tmp_path / "sessions.json")
    manager._cache_loaded = True
    outgoing = asyncio.run(
        manager.start_session(
            vehicle_id=PROFILE_A_ID,
            logical_vehicle_id=PROFILE_A_ID,
            loadpoint_id="generic_ev",
            mode="solar_surplus",
        )
    )

    ended = asyncio.run(
        manager.transfer_idle_session_attribution(
            loadpoint_id="generic_ev",
            from_vehicle_id=PROFILE_A_ID,
            to_vehicle_id=PROFILE_B_ID,
            fresh_idle=True,
            end_soc=46,
            end_soc_entity="sensor.tank_soc",
            end_soc_time="2026-10-10T06:00:00+00:00",
            end_soc_source="state",
        )
    )

    assert ended is True
    assert outgoing.completed is True
    assert outgoing.stopped_reason == "profile_handoff_idle"
    assert outgoing.end_soc == 46
    assert outgoing.end_soc_entity == "sensor.tank_soc"
    assert outgoing.end_soc_time == "2026-10-10T06:00:00+00:00"
    assert outgoing.end_soc_source == "state"


def test_idle_handoff_leaves_end_soc_null_when_outgoing_profile_sample_is_unavailable(tmp_path):
    sessions = _load_session_manager()
    manager = sessions.ChargingSessionManager(_Hass(), storage_path=tmp_path / "sessions.json")
    manager._cache_loaded = True
    outgoing = asyncio.run(
        manager.start_session(
            vehicle_id=PROFILE_A_ID,
            logical_vehicle_id=PROFILE_A_ID,
            loadpoint_id="generic_ev",
            mode="solar_surplus",
        )
    )

    ended = asyncio.run(
        manager.transfer_idle_session_attribution(
            loadpoint_id="generic_ev",
            from_vehicle_id=PROFILE_A_ID,
            to_vehicle_id=PROFILE_B_ID,
            fresh_idle=True,
        )
    )

    assert ended is True
    assert outgoing.completed is True
    assert outgoing.end_soc is None
    assert outgoing.end_soc_entity is None
    assert outgoing.end_soc_time is None
    assert outgoing.end_soc_source is None


def test_shared_logical_finalization_rejects_unproven_soc_value(tmp_path):
    sessions = _load_session_manager()
    manager = sessions.ChargingSessionManager(_Hass(), storage_path=tmp_path / "sessions.json")
    manager._cache_loaded = True
    asyncio.run(
        manager.start_session(
            vehicle_id=PROFILE_A_ID,
            logical_vehicle_id=PROFILE_A_ID,
            loadpoint_id="generic_ev",
            mode="scheduled",
        )
    )

    ended = asyncio.run(manager.end_session("generic_ev", "stopped", end_soc=91))

    assert ended is not None
    assert ended.end_soc is None
    assert ended.end_soc_entity is None
    assert ended.end_soc_source is None

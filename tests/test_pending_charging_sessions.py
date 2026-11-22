"""Pending session lifecycle and identity fencing."""
import asyncio
from types import SimpleNamespace

from test_shared_loadpoint_binding import PROFILE_A_ID, PROFILE_B_ID, _load_session_manager


def _manager(tmp_path):
    module = _load_session_manager()
    async def run_job(func):
        return func()

    manager = module.ChargingSessionManager(
        SimpleNamespace(config=SimpleNamespace(config_dir="."), async_add_executor_job=run_job),
        storage_path=tmp_path / "sessions.json",
    )
    manager._cache_loaded = True
    return module, manager


def test_promotion_requires_exact_key_profile_and_session_id(tmp_path):
    _, manager = _manager(tmp_path)

    async def run():
        session = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev", pending=True)
        for key, profile, sid in [("other", PROFILE_A_ID, session.id), ("generic_ev", PROFILE_B_ID, session.id), ("generic_ev", PROFILE_A_ID, "wrong")]:
            assert not await manager.promote_pending_session(key, profile, sid)
            assert session.pending
        assert await manager.promote_pending_session("generic_ev", PROFILE_A_ID, session.id)
        assert not session.pending
        assert manager.active_sessions["generic_ev"] is session
        other = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev", pending=True)
        assert not await manager.promote_pending_session("generic_ev", PROFILE_A_ID, other.id, still_selected=lambda: False)
        assert other.pending

    asyncio.run(run())


def test_selection_change_while_promotion_waits_on_lock_is_rechecked(tmp_path):
    _, manager = _manager(tmp_path)

    async def run():
        session = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev", pending=True)
        selected = [True]
        await manager._session_lock.acquire()
        task = asyncio.create_task(manager.promote_pending_session(
            "generic_ev", PROFILE_A_ID, session.id, still_selected=lambda: selected[0]))
        await asyncio.sleep(0)
        selected[0] = False
        manager._session_lock.release()
        assert not await task
        assert session.pending

    asyncio.run(run())


def test_unknown_end_retains_uncertain_pending_record(tmp_path):
    _, manager = _manager(tmp_path)

    async def run():
        session = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev", pending=True)
        assert await manager.end_session("generic_ev", "unknown") is session
        assert session.pending and session.completed
        assert manager._sessions_cache == [session]
        assert manager._pending_history[session.id] is session
        assert await manager.async_flush_history()
        reloaded = type(manager)(manager.hass, storage_path=manager.storage_path)
        history = await reloaded.get_session_history()
        assert len(history) == 1
        assert history[0].id == session.id and history[0].pending

    asyncio.run(run())


def test_verified_idle_discards_pending_but_not_confirmed(tmp_path):
    _, manager = _manager(tmp_path)

    async def run():
        pending = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev", pending=True)
        await manager.end_session("generic_ev", "idle", fresh_idle=True)
        assert pending not in manager._sessions_cache
        confirmed = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev")
        await manager.end_session("generic_ev", "idle", fresh_idle=True)
        assert manager._sessions_cache == [confirmed]
        manager._history_retry_handle.cancel()

    asyncio.run(run())


def test_pending_session_does_not_account_commanded_power(tmp_path):
    _, manager = _manager(tmp_path)

    async def run():
        session = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev", pending=True)
        await manager.update_session("generic_ev", 7.0, 32, False)
        assert session.last_reading_time is None
        assert session.total_energy_kwh == 0

    asyncio.run(run())


def test_stale_cleanup_keeps_pending_session_for_live_controller(tmp_path):
    from datetime import timedelta
    module, manager = _manager(tmp_path)

    async def run():
        session = await manager.start_session(PROFILE_A_ID, "solar_surplus", loadpoint_id="generic_ev", pending=True)
        session.start_time = (module.dt_util.now() - timedelta(minutes=31)).isoformat()
        assert await manager.cleanup_stale_sessions() == []
        assert manager.active_sessions["generic_ev"] is session
        assert not manager._sessions_cache

    asyncio.run(run())


def test_stale_cleanup_does_not_close_new_pending_replacement(tmp_path):
    from datetime import timedelta
    module, manager = _manager(tmp_path)

    async def run():
        old = await manager.start_session(PROFILE_A_ID, "boost", loadpoint_id="generic_ev")
        old.start_time = (module.dt_util.now() - timedelta(minutes=31)).isoformat()
        await manager._session_lock.acquire()
        task = asyncio.create_task(manager.cleanup_stale_sessions())
        await asyncio.sleep(0)
        replacement = module.ChargingSession(id="replacement", vehicle_id=PROFILE_A_ID,
            logical_vehicle_id=PROFILE_A_ID, start_time=module.dt_util.now().isoformat(),
            loadpoint_id="generic_ev", pending=True)
        manager.active_sessions["generic_ev"] = replacement
        manager._session_lock.release()
        assert await task == []
        assert manager.active_sessions["generic_ev"] is replacement

    asyncio.run(run())


def test_handoff_with_weak_idle_preserves_pending_as_uncertain(tmp_path):
    _, manager = _manager(tmp_path)

    async def run():
        session = await manager.start_session(PROFILE_A_ID, "solar_surplus", loadpoint_id="generic_ev", pending=True)
        assert await manager.transfer_idle_session_attribution("generic_ev", PROFILE_A_ID, PROFILE_B_ID, fresh_idle=True)
        assert session.completed and session.pending
        assert manager._sessions_cache == [session]
        manager._history_retry_handle.cancel()

    asyncio.run(run())


def test_pending_roundtrip_and_legacy_default(tmp_path):
    module, _ = _manager(tmp_path)
    data = {"id": "old", "vehicle_id": "VIN", "start_time": "2026-01-01T00:00:00+00:00"}
    session = module.ChargingSession.from_dict(data)
    assert session.pending is False
    session.pending = True
    assert module.ChargingSession.from_dict(session.to_dict()).pending is True

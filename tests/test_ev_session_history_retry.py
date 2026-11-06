"""Focused regression tests for EV session history persistence."""
import asyncio
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def sessions(monkeypatch):
    ha = types.ModuleType("homeassistant")
    util = types.ModuleType("homeassistant.util")
    util.dt = types.SimpleNamespace(now=lambda: datetime.now(timezone.utc), DEFAULT_TIME_ZONE=timezone.utc)
    monkeypatch.setitem(sys.modules, "homeassistant", ha)
    monkeypatch.setitem(sys.modules, "homeassistant.util", util)
    name = "ev_history_retry_test_module"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "custom_components/power_sync/automations/ev_charging_session.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class Hass:
    async def async_add_executor_job(self, job):
        return await asyncio.to_thread(job)


def test_failure_retries_finished_session_without_touching_successor(sessions, tmp_path, monkeypatch):
    async def scenario():
        path = tmp_path / "sessions.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        first = await manager.start_session("car", "solar", loadpoint_id="charger")
        original = os.replace
        monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
        finished = await manager.end_session("charger", "stopped")
        assert finished is first and finished.completed
        successor = await manager.start_session("car2", "solar", loadpoint_id="charger")
        await manager._save_sessions()
        assert manager.history_dirty
        assert manager._history_retry_handle is not None
        monkeypatch.setattr(os, "replace", original)
        await manager._save_sessions()
        assert not manager.history_dirty
        assert manager.active_sessions["charger"] is successor
        assert [s["id"] for s in json.loads(path.read_text())["sessions"]] == [first.id]
        if manager._history_retry_handle:
            manager._history_retry_handle.cancel()
    asyncio.run(scenario())


def test_atomic_failure_preserves_old_history_and_real_timer_recovers(sessions, tmp_path, monkeypatch):
    async def scenario():
        path = tmp_path / "sessions.json"
        old = sessions.ChargingSession(id="old", vehicle_id="old", start_time=datetime.now(timezone.utc).isoformat(), completed=True)
        original_bytes = json.dumps({"sessions": [old.to_dict()]}).encode()
        path.write_bytes(original_bytes)
        manager = sessions.ChargingSessionManager(Hass(), path)
        started = await manager.start_session("car", "solar")
        real_replace = os.replace
        attempts = 0

        def fail_once(*args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("failed replace")
            return real_replace(*args)

        monkeypatch.setattr(os, "replace", fail_once)
        await manager.end_session("car", "stopped")
        # Run an explicit attempt; the timer will be replaced with a short one below.
        await manager._save_sessions()
        assert path.read_bytes() == original_bytes
        assert manager.history_dirty and manager.history_last_error
        manager._history_retry_handle.cancel()
        manager._history_retry_handle = None
        manager._schedule_history_save(0.001)
        for _ in range(100):
            if not manager.history_dirty:
                break
            await asyncio.sleep(0.01)
        assert not manager.history_dirty
        assert attempts == 2
        assert [s["id"] for s in json.loads(path.read_text())["sessions"]] == ["old", started.id]
    asyncio.run(scenario())


def test_load_failure_never_overwrites_existing_history(sessions, tmp_path):
    async def scenario():
        path = tmp_path / "sessions.json"
        path.write_text("not json")
        manager = sessions.ChargingSessionManager(Hass(), path)
        session = await manager.start_session("car", "solar")
        await manager.end_session("car", "stopped")
        await manager._save_sessions()
        assert path.read_text() == "not json"
        assert manager.history_dirty and manager.history_last_error
        assert manager._sessions_cache == [session]
        old = sessions.ChargingSession(id="old", vehicle_id="old", start_time=session.start_time, completed=True)
        path.write_text(json.dumps({"sessions": [old.to_dict()]}))
        await manager._save_sessions()
        assert not manager.history_dirty
        assert [s["id"] for s in json.loads(path.read_text())["sessions"]] == ["old", session.id]
    asyncio.run(scenario())


def test_old_inflight_snapshot_cannot_clear_newer_finalization(sessions, tmp_path):
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        second_entered = asyncio.Event()
        release_second = asyncio.Event()
        writes = 0

        class BlockingHass(Hass):
            async def async_add_executor_job(self, job):
                nonlocal writes
                if job.__name__ == "_write_file":
                    writes += 1
                    if writes == 1:
                        entered.set()
                        await release.wait()
                    else:
                        second_entered.set()
                        await release_second.wait()
                return await super().async_add_executor_job(job)

        path = tmp_path / "sessions.json"
        manager = sessions.ChargingSessionManager(BlockingHass(), path)
        one = await manager.start_session("one", "solar")
        await manager.end_session("one", "stopped")
        await entered.wait()
        two = await manager.start_session("two", "solar")
        await asyncio.wait_for(manager.end_session("two", "stopped"), timeout=1)
        release.set()
        # The first write completes before a queued second write; neither can
        # clear generation two until its own snapshot is written.
        save = asyncio.create_task(manager._save_sessions())
        await asyncio.wait_for(second_entered.wait(), timeout=1)
        assert manager.history_dirty
        assert {s.id for s in await manager.get_session_history()} == {one.id, two.id}
        assert [s["id"] for s in json.loads(path.read_text())["sessions"]] == [one.id]
        release_second.set()
        await save
        assert not manager.history_dirty
        assert [s["id"] for s in json.loads(path.read_text())["sessions"]] == [one.id, two.id]
        if manager._history_retry_handle:
            manager._history_retry_handle.cancel()
    asyncio.run(scenario())


def test_stale_manager_retry_merges_other_manager_history(sessions, tmp_path):
    async def scenario():
        path = tmp_path / "sessions.json"
        first = sessions.ChargingSessionManager(Hass(), path)
        second = sessions.ChargingSessionManager(Hass(), path)
        a = await first.start_session("a", "solar")
        b = await second.start_session("b", "solar")
        await first.end_session("a", "stop")
        await first._save_sessions()
        await second.end_session("b", "stop")
        await second._save_sessions()
        assert {s["id"] for s in json.loads(path.read_text())["sessions"]} == {a.id, b.id}
        assert {s.id for s in await second.get_session_history()} == {a.id, b.id}
    asyncio.run(scenario())


def test_replacement_history_refreshes_after_old_manager_retry(sessions, tmp_path):
    async def scenario():
        path = tmp_path / "history.json"
        old = sessions.ChargingSessionManager(Hass(), path)
        replacement = sessions.ChargingSessionManager(Hass(), path)
        a = await old.start_session("a", "solar")
        await old.end_session("a", "stop")
        old._history_retry_handle.cancel()
        old._history_retry_handle = None
        b = await replacement.start_session("b", "solar")
        await replacement.end_session("b", "stop")
        replacement._history_retry_handle.cancel()
        replacement._history_retry_handle = None
        await old._save_sessions()
        assert {s.id for s in await replacement.get_session_history()} == {a.id, b.id}
        assert await replacement.async_flush_history()
        assert {s['id'] for s in json.loads(path.read_text())['sessions']} == {a.id, b.id}
    asyncio.run(scenario())


def test_shutdown_flushes_and_reports_failed_retry(sessions, tmp_path, monkeypatch):
    async def scenario():
        path = tmp_path / "sessions.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        one = await manager.start_session("a", "solar")
        await manager.end_session("a", "stop")
        real_replace = os.replace
        monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
        assert await manager.async_flush_history() is False
        assert manager.history_dirty and manager.history_last_error
        monkeypatch.setattr(os, "replace", real_replace)
        assert await manager.async_flush_history() is True
        assert [s["id"] for s in json.loads(path.read_text())["sessions"]] == [one.id]
    asyncio.run(scenario())


def test_cancelled_save_drains_executor_before_return_and_preserves_other_manager(sessions, tmp_path, monkeypatch):
    import threading

    async def scenario():
        path = tmp_path / "sessions.json"
        first = sessions.ChargingSessionManager(Hass(), path)
        second = sessions.ChargingSessionManager(Hass(), path)
        a = await first.start_session("a", "solar")
        b = await second.start_session("b", "solar")
        entered, release = threading.Event(), threading.Event()
        real_replace = os.replace
        def blocked_replace(*args):
            if not entered.is_set():
                entered.set()
                assert release.wait(3)
            return real_replace(*args)
        monkeypatch.setattr(os, "replace", blocked_replace)
        await first.end_session("a", "stop")
        first._history_retry_handle.cancel()
        first._history_retry_handle = None
        save = asyncio.create_task(first._save_sessions())
        assert await asyncio.to_thread(entered.wait, 2)
        save.cancel()
        await asyncio.sleep(0.01)
        assert not save.done()
        save.cancel()
        await asyncio.sleep(0.01)
        assert not save.done()
        await second.end_session("b", "stop")
        other = asyncio.create_task(second._save_sessions())
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await save
        await other
        assert first.history_dirty
        assert await first.async_flush_history()
        assert {s["id"] for s in json.loads(path.read_text())["sessions"]} == {a.id, b.id}
    asyncio.run(scenario())


def test_cancelled_save_while_waiting_for_lock_keeps_retry_armed(sessions, tmp_path):
    async def scenario():
        manager = sessions.ChargingSessionManager(Hass(), tmp_path / "history.json")
        await manager.start_session("a", "solar")
        await manager.end_session("a", "stop")
        manager._history_retry_handle.cancel()
        manager._history_retry_handle = None
        await manager._history_save_lock.acquire()
        save = asyncio.create_task(manager._save_sessions())
        await asyncio.sleep(0)
        save.cancel()
        with pytest.raises(asyncio.CancelledError):
            await save
        manager._history_save_lock.release()
        assert manager.history_dirty and manager._history_retry_handle is not None
        assert await manager.async_flush_history()
    asyncio.run(scenario())


def test_unload_finalizes_and_reports_persistence_failure(sessions, tmp_path, monkeypatch):
    import ast
    import logging

    source = (Path(__file__).parents[1] / "custom_components/power_sync/__init__.py").read_text()
    module = ast.parse(source)
    unload = next(n for n in module.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_unload_entry")
    block = next(n for n in unload.body if isinstance(n, ast.If) and isinstance(n.test, ast.NamedExpr)
                 and isinstance(n.test.target, ast.Name) and n.test.target.id == "session_manager")
    wrapper = ast.parse("async def run(entry_data):\n    pass\n")
    wrapper.body[0].body = [block]
    ast.fix_missing_locations(wrapper)
    records = []
    class Logger:
        def info(self, *args): pass
        def debug(self, *args): pass
        def error(self, *args): records.append(args)
        def exception(self, *args): records.append(args)
    namespace = {"_LOGGER": Logger()}
    exec(compile(wrapper, "<unload-history-block>", "exec"), namespace)

    async def scenario():
        manager = sessions.ChargingSessionManager(Hass(), tmp_path / "history.json")
        session = await manager.start_session("a", "solar")
        real_replace = os.replace
        monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
        await namespace["run"]({"session_manager": manager})
        assert session.completed and manager.history_dirty and records
        assert manager._history_retry_handle is not None
        monkeypatch.setattr(os, "replace", real_replace)
        assert await manager.async_flush_history()
    asyncio.run(scenario())


def test_close_flushes_after_managed_task_cancelled_without_swallowing_caller_cancel(sessions, tmp_path):
    async def scenario():
        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        session = await manager.start_session("car", "solar")
        await manager.end_session("car", "stop")
        manager._history_retry_handle.cancel()
        manager._history_retry_handle = None
        await manager._history_save_lock.acquire()
        task = asyncio.create_task(manager._save_sessions())
        manager._history_task = task
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        manager._history_save_lock.release()
        assert await manager.async_close()
        assert [s['id'] for s in json.loads(path.read_text())['sessions']] == [session.id]

        entered = asyncio.Event()
        async def blocked():
            entered.set()
            await asyncio.Event().wait()
        manager._history_task = asyncio.create_task(blocked())
        await entered.wait()
        close = asyncio.create_task(manager.async_close())
        await asyncio.sleep(0)
        close.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close
        manager._history_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await manager._history_task
    asyncio.run(scenario())


def test_close_fences_new_start_while_write_is_in_flight(sessions, tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class BlockingHass(Hass):
            async def async_add_executor_job(self, job):
                if job.__name__ == "_write_file":
                    entered.set()
                    await release.wait()
                return await super().async_add_executor_job(job)

        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(BlockingHass(), path)
        old = await manager.start_session("old", "solar")
        await manager.end_session("old", "stop")
        await asyncio.wait_for(entered.wait(), 1)
        active = await manager.start_session("active", "solar")
        close = asyncio.create_task(manager.async_close())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="clos"):
            await manager.start_session("late", "solar")
        assert not close.done()
        release.set()
        assert await asyncio.wait_for(close, 1)
        assert active.completed and not manager.active_sessions
        assert {s["id"] for s in json.loads(path.read_text())["sessions"]} == {old.id, active.id}
    asyncio.run(scenario())


def test_close_fences_start_already_waiting_for_history_load(sessions, tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class BlockingHass(Hass):
            async def async_add_executor_job(self, job):
                if job.__name__ == "_read_file":
                    entered.set()
                    await release.wait()
                return await super().async_add_executor_job(job)

        manager = sessions.ChargingSessionManager(BlockingHass(), tmp_path / "history.json")
        start = asyncio.create_task(manager.start_session("car", "solar"))
        await asyncio.wait_for(entered.wait(), 1)
        close = asyncio.create_task(manager.async_close())
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(RuntimeError, match="clos"):
            await start
        assert await asyncio.wait_for(close, 1)
        assert not manager.active_sessions
    asyncio.run(scenario())


def test_close_logs_failure_and_preserves_retry(sessions, tmp_path, monkeypatch, caplog):
    async def scenario():
        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        session = await manager.start_session("car", "solar")
        real_replace = os.replace
        monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
        assert not await manager.async_close()
        assert session.completed and manager.history_dirty and manager._history_retry_handle
        assert "not saved on unload" in caplog.text
        monkeypatch.setattr(os, "replace", real_replace)
        assert await manager.async_close()
        assert [item["id"] for item in json.loads(path.read_text())["sessions"]] == [session.id]
    asyncio.run(scenario())


def test_flush_waits_for_managed_background_write(sessions, tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        class BlockingHass(Hass):
            async def async_add_executor_job(self, job):
                if job.__name__ == "_write_file":
                    entered.set()
                    await release.wait()
                return await super().async_add_executor_job(job)
        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(BlockingHass(), path)
        session = await manager.start_session("a", "solar")
        await manager.end_session("a", "stop")
        await asyncio.wait_for(entered.wait(), 1)
        assert manager._history_task is not None
        flush = asyncio.create_task(manager.async_flush_history())
        await asyncio.sleep(0)
        assert not flush.done()
        release.set()
        assert await asyncio.wait_for(flush, 1)
        assert [s["id"] for s in json.loads(path.read_text())["sessions"]] == [session.id]
    asyncio.run(scenario())

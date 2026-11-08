"""EV history saves with the Future returned by Home Assistant's executor API."""
import asyncio
import importlib.util
import json
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
    name = "ev_session_future_test_module"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "custom_components/power_sync/automations/ev_charging_session.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class Hass:
    def async_add_executor_job(self, job):
        return asyncio.get_running_loop().run_in_executor(None, job)


def test_future_executor_flush_persists_finished_session(sessions, tmp_path):
    async def scenario():
        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        session = await manager.start_session("car", "solar")
        await manager.end_session("car", "stop")
        assert await manager.async_flush_history(), manager.history_last_error
        assert not manager.history_dirty
        assert [item["id"] for item in json.loads(path.read_text())["sessions"]] == [session.id]
    asyncio.run(scenario())


def test_future_concurrent_saves_and_close_preserve_all_sessions(sessions, tmp_path, monkeypatch):
    import os
    import threading

    async def scenario():
        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        first = await manager.start_session("first", "solar")
        await manager.end_session("first", "stop")
        manager._history_retry_handle.cancel()
        manager._history_retry_handle = None
        entered, release = threading.Event(), threading.Event()
        real_replace = os.replace
        def blocked_replace(*args):
            if not entered.is_set():
                entered.set()
                assert release.wait(5)
            return real_replace(*args)
        monkeypatch.setattr(os, "replace", blocked_replace)
        save = asyncio.create_task(manager._save_sessions())
        assert await asyncio.to_thread(entered.wait, 2)
        second = await manager.start_session("second", "solar")
        close = asyncio.create_task(manager.async_close())
        await asyncio.sleep(0)
        assert not close.done()
        with pytest.raises(RuntimeError, match="clos"):
            await manager.start_session("late", "solar")
        release.set()
        await asyncio.wait_for(save, 2)
        assert await asyncio.wait_for(close, 2)
        assert second.completed and not manager.active_sessions and not manager.history_dirty
        assert {item["id"] for item in json.loads(path.read_text())["sessions"]} == {first.id, second.id}
    asyncio.run(scenario())


def test_future_failure_retains_retry_then_unload_flushes(sessions, tmp_path, monkeypatch):
    import os

    async def scenario():
        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        session = await manager.start_session("car", "solar")
        real_replace = os.replace
        def fail(*args):
            raise OSError("disk unavailable")
        monkeypatch.setattr(os, "replace", fail)
        assert not await manager.async_close()
        assert session.completed and manager.history_dirty and manager._history_retry_handle
        assert "disk unavailable" in manager.history_last_error
        monkeypatch.setattr(os, "replace", real_replace)
        assert await manager.async_close()
        assert not manager.history_dirty and manager.history_last_error is None
        assert [item["id"] for item in json.loads(path.read_text())["sessions"]] == [session.id]
    asyncio.run(scenario())


def test_future_cancelled_save_drains_write_before_retry(sessions, tmp_path, monkeypatch):
    import os
    import threading

    async def scenario():
        path = tmp_path / "history.json"
        manager = sessions.ChargingSessionManager(Hass(), path)
        session = await manager.start_session("car", "solar")
        await manager.end_session("car", "stop")
        manager._history_retry_handle.cancel()
        manager._history_retry_handle = None
        entered, release = threading.Event(), threading.Event()
        real_replace = os.replace
        def blocked_replace(*args):
            entered.set()
            assert release.wait(5)
            return real_replace(*args)
        monkeypatch.setattr(os, "replace", blocked_replace)
        save = asyncio.create_task(manager._save_sessions())
        assert await asyncio.to_thread(entered.wait, 2)
        save.cancel()
        await asyncio.sleep(0.01)
        assert not save.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await save
        assert manager.history_dirty and manager._history_retry_handle
        assert await manager.async_flush_history()
        assert [item["id"] for item in json.loads(path.read_text())["sessions"]] == [session.id]
    asyncio.run(scenario())

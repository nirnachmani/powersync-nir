"""Boost expiry on the private shared physical Generic/EVAC loadpoint."""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from test_ev_vehicle_status import _Hass, _State, _power_sync_module
from test_shared_logical_vehicle_api import _shared_entry


class _BoostHarness:
    def __init__(self, monkeypatch, backend):
        self.power_sync = _power_sync_module()
        self.actions = importlib.import_module("power_sync.automations.actions")
        # Each asyncio.run test owns a fresh event loop, unlike HA's single loop.
        monkeypatch.setattr(self.actions, "_start_dynamic_lock", asyncio.Lock())
        self.ownership = importlib.import_module("power_sync.automations.ev_ownership")
        self.shared = importlib.import_module("power_sync.automations.shared_loadpoint")
        self.entry = _shared_entry(backend=backend)
        self.physical = "generic_ev" if backend == "generic" else "sigenergy_charger"
        self.charger_type = "generic" if backend == "generic" else "sigenergy"
        self.hass = _Hass([_State("select.connected_ev", "tank")], config_entries=[self.entry])
        self.states = self.actions._dynamic_ev_state
        self.states.pop(self.entry.entry_id, None)
        self.timers = []
        self.stops = []
        self.fail_start = False
        self.now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(self.power_sync.dt_util, "utcnow", lambda: self.now)
        monkeypatch.setattr(self.power_sync.web, "json_response", lambda body, **kwargs: {
            **body, "status": kwargs.get("status", 200),
        })
        monkeypatch.setattr(self.power_sync, "async_track_point_in_utc_time", self.track)
        monkeypatch.setattr(self.actions, "execute_actions", self.execute)
        monkeypatch.setattr(
            self.power_sync.EVVehicleCommandView,
            "_get_vehicle_charging_config",
            lambda _view, vehicle_id, *_ids: {
                "vehicle_id": vehicle_id,
                "charger_type": self.charger_type,
                "display_name": vehicle_id,
            },
        )

    def track(self, _hass, callback, deadline):
        timer = SimpleNamespace(callback=callback, deadline=deadline, cancelled=False)
        def cancel():
            timer.cancelled = True
        self.timers.append(timer)
        return cancel

    async def execute(self, hass, entry, instructions):
        for instruction in instructions:
            params = instruction["parameters"]
            kind = instruction["action_type"]
            profile = params.get("active_logical_vehicle_id")
            resolved = self.shared.resolve_shared_loadpoint_command(
                hass, entry, profile, params,
            )
            if resolved is None or resolved["vehicle_id"] != self.physical:
                return False
            if kind == "start_ev_charging_dynamic":
                if self.fail_start:
                    return False
                state = {
                    "active": True,
                    "active_profile_id": profile,
                    "current_amps": 16,
                    "params": dict(params),
                }
                self.states.setdefault(entry.entry_id, {})[self.physical] = state
                state["ownership"] = self.ownership.claim_ev_ownership(
                    hass, entry, self.physical, owner_mode="boost",
                    extra={"active_profile_id": profile},
                )
            elif kind == "stop_ev_charging_dynamic":
                state = self.states.get(entry.entry_id, {}).get(self.physical)
                _id, lease = self.ownership.get_ev_ownership(hass, entry, self.physical)
                if (
                    state is not params.get("_expected_state")
                    or not lease or lease.get("active_profile_id") != profile
                ):
                    return False
                self.stops.append((profile, self.physical, dict(params)))
                self.states[entry.entry_id].pop(self.physical)
                self.ownership.release_ev_ownership(hass, entry, self.physical)
            else:
                raise AssertionError(kind)
        return True

    async def start(self, profile, minutes=1):
        async def payload():
            return {"vehicle_id": profile, "duration_minutes": minutes}
        return await self.power_sync.ChargingBoostView(self.hass, self.entry).post(
            SimpleNamespace(json=payload)
        )

    def select(self, selector):
        self.hass.states._states["select.connected_ev"] = _State(
            "select.connected_ev", selector,
        )

    @property
    def runtime(self):
        return self.hass.data["power_sync"][self.entry.entry_id]


@pytest.mark.parametrize("backend", ["generic", "evac"])
def test_shared_boost_handoff_old_expiry_never_stops_new_profile(monkeypatch, backend):
    async def scenario():
        h = _BoostHarness(monkeypatch, backend)
        a = await h.start("shared_ev_profile_a", 1)
        assert a["success"] is True and a["status"] == 200
        assert a["message"] == "Boost charge started"
        assert a["duration_minutes"] == 1 and a["target_soc"] is None
        assert a["warnings"] == ["Boost limited to 16A by per-phase load management"]
        assert datetime.fromisoformat(a["stops_at"]) == h.timers[0].deadline
        assert h.runtime["ev_boost_timers"][h.physical]["active_profile_id"] == "shared_ev_profile_a"

        # An expiry already queued at the dynamic-start gate must recheck the
        # replacement even if cancelling its event callback is too late.
        async with h.actions._start_dynamic_lock:
            waiting = asyncio.create_task(h.timers[0].callback(h.timers[0].deadline))
            await asyncio.sleep(0)
            assert not waiting.done()
            h.select("tesla")
            b = await h.start("shared_ev_profile_b", 3)
            assert b["success"] and b["status"] == 200
            assert h.timers[0].cancelled and not h.timers[1].cancelled
        await waiting
        await h.timers[0].callback(h.timers[0].deadline)  # late cancelled event
        assert h.stops == []
        assert set(h.runtime["ev_boost_timers"]) == {h.physical}
        assert h.runtime["ev_boost_timers"][h.physical]["active_profile_id"] == "shared_ev_profile_b"
        state = h.states[h.entry.entry_id][h.physical]
        _id, lease = h.ownership.get_ev_ownership(h.hass, h.entry, h.physical)
        assert state["active_profile_id"] == lease["active_profile_id"] == "shared_ev_profile_b"
        await h.timers[1].callback(h.timers[1].deadline)
        assert len(h.stops) == 1
        assert h.stops[0][0:2] == ("shared_ev_profile_b", h.physical)
        assert h.stops[0][2]["_expected_state"] is state
        assert h.runtime["ev_boost_timers"] == {}
    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["generic", "evac"])
def test_failed_replacement_keeps_original_deadline_and_owner(monkeypatch, backend):
    async def scenario():
        h = _BoostHarness(monkeypatch, backend)
        await h.start("shared_ev_profile_a")
        original_timer = h.runtime["ev_boost_timers"][h.physical]
        original_state = h.states[h.entry.entry_id][h.physical]
        _id, original_lease = h.ownership.get_ev_ownership(h.hass, h.entry, h.physical)
        h.fail_start = True
        response = await h.start("shared_ev_profile_a", 2)
        assert response["success"] is False and response["stops_at"] is None
        assert len(h.timers) == 1 and not h.timers[0].cancelled
        assert h.runtime["ev_boost_timers"][h.physical] is original_timer
        assert h.states[h.entry.entry_id][h.physical] is original_state
        assert h.ownership.get_ev_ownership(h.hass, h.entry, h.physical)[1] is original_lease
        await h.timers[0].callback(h.timers[0].deadline)
        assert len(h.stops) == 1 and h.stops[0][0] == "shared_ev_profile_a"
    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["generic", "evac"])
def test_shared_boost_fails_closed_on_selector_or_lease_change(monkeypatch, backend):
    async def scenario():
        h = _BoostHarness(monkeypatch, backend)
        await h.start("shared_ev_profile_a")
        h.select("unknown")
        rejected = await h.start("shared_ev_profile_b")
        assert rejected["success"] is False and rejected["status"] == 409
        assert len(h.timers) == 1 and not h.timers[0].cancelled
        await h.timers[0].callback(h.timers[0].deadline)
        assert h.stops == []
        assert h.states[h.entry.entry_id][h.physical]["active_profile_id"] == "shared_ev_profile_a"

        h.select("tank")
        await h.start("shared_ev_profile_a", 2)
        _id, lease = h.ownership.get_ev_ownership(h.hass, h.entry, h.physical)
        lease["active_profile_id"] = "shared_ev_profile_b"
        await h.timers[1].callback(h.timers[1].deadline)
        assert h.stops == []
        assert h.states[h.entry.entry_id][h.physical]["active_profile_id"] == "shared_ev_profile_a"
    asyncio.run(scenario())


def test_unload_boost_timer_cleanup_is_per_vehicle_and_legacy_compatible():
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "custom_components/power_sync/__init__.py"
    node = next(item for item in ast.parse(source.read_text()).body
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_unload_entry")
    cleanup = [item for item in node.body if isinstance(item, (ast.For, ast.If))
               and any(isinstance(child, ast.Constant)
                       and child.value in ("ev_boost_timers", "ev_boost_cancel")
                       for child in ast.walk(item))]
    assert len(cleanup) == 2
    cancelled = []
    entry_data = {"ev_boost_timers": {
        "generic_ev": {"cancel": lambda: cancelled.append("generic_ev")},
        "sigenergy_charger": {"cancel": lambda: cancelled.append("sigenergy_charger")},
    }, "ev_boost_cancel": lambda: cancelled.append("legacy")}
    code = compile(ast.fix_missing_locations(ast.Module(body=cleanup, type_ignores=[])),
                   str(source), "exec")
    exec(code, {"entry_data": entry_data, "_LOGGER": SimpleNamespace(debug=lambda *_: None)})
    assert cancelled == ["generic_ev", "sigenergy_charger", "legacy"]
    assert "ev_boost_timers" not in entry_data and "ev_boost_cancel" not in entry_data

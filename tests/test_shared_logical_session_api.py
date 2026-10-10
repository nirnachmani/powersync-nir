"""Behavior tests for logical shared-loadpoint session history API filtering."""

from __future__ import annotations

import ast
import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from test_shared_loadpoint_binding import PROFILE_A_ID, PROFILE_B_ID, _load_session_manager


ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = ROOT / "custom_components" / "power_sync" / "__init__.py"


def _sessions_get_method():
    """Compile the sessions GET handler against a small HTTP test surface."""
    tree = ast.parse(INIT_PATH.read_text())
    view = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ChargingSessionsView"
    )
    method = copy.deepcopy(next(
        node for node in view.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get"
    ))
    method.decorator_list = []
    method.returns = None
    for arg in [*method.args.args, *method.args.kwonlyargs]:
        arg.annotation = None
    compiled = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(compiled)
    namespace = {"web": SimpleNamespace(json_response=lambda data, **_kwargs: data)}
    exec(compile(compiled, str(INIT_PATH), "exec"), namespace)
    return namespace["get"]


class _Session:
    def __init__(self, vehicle_id: str, logical_vehicle_id: str | None = None):
        self.vehicle_id = vehicle_id
        self.logical_vehicle_id = logical_vehicle_id

    def to_dict(self):
        return {
            "vehicle_id": self.vehicle_id,
            "logical_vehicle_id": self.logical_vehicle_id,
            "start_soc_entity": "sensor.profile_soc",
            "start_soc_source": "state",
        }


class _Manager:
    def __init__(self, completed, active):
        self.completed = completed
        self.active_sessions = active
        self.calls = []

    async def get_session_history(self, **kwargs):
        self.calls.append(kwargs)
        return self.completed


def test_logical_profile_session_route_includes_only_that_profiles_completed_and_active_records():
    get = _sessions_get_method()
    manager = _Manager(
        completed=[_Session(PROFILE_A_ID, PROFILE_A_ID)],
        active={
            "generic_ev": _Session("generic_ev", PROFILE_A_ID),
            "other_physical": _Session("other_physical", PROFILE_B_ID),
        },
    )

    class View:
        _get_session_manager = staticmethod(lambda: manager)

    response = asyncio.run(
        get(View(), SimpleNamespace(query={"vehicle_id": PROFILE_A_ID}))
    )

    assert manager.calls == [{"vehicle_id": PROFILE_A_ID, "days": 30, "limit": 100}]
    assert [record["logical_vehicle_id"] for record in response["sessions"]] == [PROFILE_A_ID]
    assert [record["logical_vehicle_id"] for record in response["active_sessions"]] == [PROFILE_A_ID]
    assert response["active_sessions"][0]["vehicle_id"] == "generic_ev"
    assert response["active_sessions"][0]["is_active"] is True


def test_completed_history_filters_shared_records_by_logical_attribution_not_physical_key(tmp_path):
    sessions = _load_session_manager()
    manager = sessions.ChargingSessionManager(
        SimpleNamespace(config=SimpleNamespace(config_dir=".")),
        storage_path=tmp_path / "sessions.json",
    )
    manager._cache_loaded = True
    manager._sessions_cache = [
        sessions.ChargingSession(
            id="a", vehicle_id="generic_ev", logical_vehicle_id=PROFILE_A_ID,
            start_time=datetime.now(timezone.utc).isoformat(), completed=True,
        ),
        sessions.ChargingSession(
            id="b", vehicle_id="generic_ev", logical_vehicle_id=PROFILE_B_ID,
            start_time=datetime.now(timezone.utc).isoformat(), completed=True,
        ),
    ]

    history = asyncio.run(manager.get_session_history(vehicle_id=PROFILE_A_ID))

    assert [session.id for session in history] == ["a"]
    assert history[0].logical_vehicle_id == PROFILE_A_ID


def test_nonshared_session_route_remains_keyed_by_existing_vehicle_id():
    get = _sessions_get_method()
    manager = _Manager(
        completed=[_Session("VIN-1", "VIN-1")],
        active={"VIN-1": _Session("VIN-1", "VIN-1")},
    )

    class View:
        _get_session_manager = staticmethod(lambda: manager)

    response = asyncio.run(get(View(), SimpleNamespace(query={"vehicle_id": "VIN-1"})))

    assert [record["vehicle_id"] for record in response["sessions"]] == ["VIN-1"]
    assert [record["vehicle_id"] for record in response["active_sessions"]] == ["VIN-1"]

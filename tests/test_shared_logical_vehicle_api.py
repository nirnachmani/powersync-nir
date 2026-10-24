"""Logical shared-loadpoint records preserve the Android vehicle shape."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

from test_ev_vehicle_status import _Hass, _State, _power_sync_module


_REQUIRED_ANDROID_FIELDS = {
    "id",
    "vehicle_id",
    "vin",
    "display_name",
    "model",
    "battery_level",
    "charging_state",
    "charge_limit_soc",
    "charger_power",
    "is_online",
    "is_plugged_in",
    "data_updated_at",
}


def _shared_entry(*, backend: str = "generic"):
    options = {
        "ev_provider": "tesla_ble",
        "shared_loadpoint_connected_vehicle_entity": "select.connected_ev",
        "shared_loadpoint_profile_a_name": "Tank",
        "shared_loadpoint_profile_a_state": "tank",
        "shared_loadpoint_profile_a_soc_entity": "sensor.tank_soc",
        "shared_loadpoint_profile_b_name": "Tesla",
        "shared_loadpoint_profile_b_state": "tesla",
        "shared_loadpoint_profile_b_soc_entity": "sensor.tesla_soc",
    }
    if backend == "generic":
        options.update({"generic_charger_enabled": True})
    else:
        options.update(
            {
                "sigenergy_charger_enabled": True,
                "sigenergy_charger_type": "evac",
            }
        )
    return SimpleNamespace(entry_id="entry-1", data={}, options=options)


def test_shared_generic_projection_replaces_physical_record_with_selected_profile():
    power_sync = _power_sync_module()
    entry = _shared_entry()
    hass = _Hass(
        [
            _State("select.connected_ev", "tank"),
            _State("sensor.tank_soc", "64"),
            _State("sensor.tesla_soc", "31"),
        ],
        config_entries=[entry],
    )
    physical = {
        "id": "generic_ev",
        "vehicle_id": "generic_ev",
        "vin": None,
        "display_name": "EV",
        "model": None,
        "battery_level": 99,
        "charging_state": "Charging",
        "charge_limit_soc": None,
        "charger_power": 7.2,
        "is_online": True,
        "is_plugged_in": True,
        "data_updated_at": "2026-10-11T00:00:00+00:00",
        "source": "generic_charger",
        "brand": "generic",
    }

    records = power_sync._project_shared_logical_vehicles(hass, entry, physical)

    assert [record["id"] for record in records] == [
        "shared_ev_profile_a",
        "shared_ev_profile_b",
    ]
    assert [record["vehicle_id"] for record in records] == [
        "shared_ev_profile_a",
        "shared_ev_profile_b",
    ]
    assert [record["display_name"] for record in records] == ["Tank", "Tesla"]
    assert all(_REQUIRED_ANDROID_FIELDS <= record.keys() for record in records)
    assert records[0]["battery_level"] == 64
    assert records[1]["battery_level"] == 31
    assert records[0]["is_plugged_in"] is True
    assert records[0]["charging_state"] == "Charging"
    assert records[0]["charger_power"] == 7.2
    assert records[1]["is_plugged_in"] is False
    assert records[1]["charging_state"] == "Disconnected"
    assert records[1]["charger_power"] is None


def test_shared_evac_projection_keeps_both_soc_when_selection_is_unknown():
    power_sync = _power_sync_module()
    entry = _shared_entry(backend="evac")
    hass = _Hass(
        [
            _State("select.connected_ev", "unknown"),
            _State("sensor.tank_soc", "unavailable"),
            _State("sensor.tesla_soc", "47.5"),
        ],
        config_entries=[entry],
    )
    physical = {
        "id": "sigenergy_charger",
        "vehicle_id": "sigenergy_charger",
        "vin": None,
        "display_name": "Sigenergy EVAC",
        "model": "EVAC",
        "battery_level": 80,
        "charging_state": "Charging",
        "charge_limit_soc": None,
        "charger_power": 11.0,
        "is_online": True,
        "is_plugged_in": True,
        "data_updated_at": "2026-10-11T00:00:00+00:00",
        "source": "sigenergy_charger",
    }

    records = power_sync._project_shared_logical_vehicles(hass, entry, physical)

    assert [record["battery_level"] for record in records] == [None, 47.5]
    assert all(record["is_plugged_in"] is False for record in records)
    assert all(record["charging_state"] == "Disconnected" for record in records)
    assert all(record["charger_power"] is None for record in records)


def test_shared_profile_projection_does_not_claim_unselected_physical_status_when_idle():
    power_sync = _power_sync_module()
    entry = _shared_entry()
    hass = _Hass(
        [
            _State("select.connected_ev", "tesla"),
            _State("sensor.tank_soc", "55"),
            _State("sensor.tesla_soc", "bad"),
        ],
        config_entries=[entry],
    )
    physical = {
        "id": "generic_ev",
        "vehicle_id": "generic_ev",
        "charging_state": "Disconnected",
        "charger_power": 0.0,
        "is_online": True,
        "is_plugged_in": False,
        "data_updated_at": "2026-10-11T00:00:00+00:00",
    }

    records = power_sync._project_shared_logical_vehicles(hass, entry, physical)

    assert records[0]["battery_level"] == 55
    assert records[1]["battery_level"] is None
    assert records[0]["is_plugged_in"] is False
    assert records[1]["is_plugged_in"] is False
    assert records[1]["charging_state"] == "Disconnected"


def test_vehicle_list_route_replaces_shared_generic_row_without_a_third_record():
    power_sync = _power_sync_module()
    entry = _shared_entry()
    hass = _Hass(
        [
            _State("select.connected_ev", "tank"),
            _State("sensor.tank_soc", "64"),
            _State("sensor.tesla_soc", "31"),
        ],
        entry_data={
            "automation_store": SimpleNamespace(
                _data={
                    "vehicle_charging_configs": [
                        {"vehicle_id": "shared_ev_profile_a", "battery_capacity_kwh": 82},
                        {"vehicle_id": "shared_ev_profile_b", "battery_capacity_kwh": 57},
                    ]
                }
            )
        },
        config_entries=[entry],
    )
    power_sync._generic_charger_observation_from_config = lambda *_args, **_kwargs: {
        "ev_power_kw": 7.2,
        "ev_soc": 99,
        "is_connected": True,
        "is_charging": True,
    }
    power_sync._configured_sigenergy_charger_state = lambda _entry: None
    power_sync.web.json_response = lambda data, **_kwargs: data

    response = asyncio.run(power_sync.EVVehiclesView(hass).get(None))

    vehicles = response["vehicles"]
    assert [vehicle["vehicle_id"] for vehicle in vehicles] == [
        "shared_ev_profile_a",
        "shared_ev_profile_b",
    ]
    assert all(vehicle["vehicle_id"] != "generic_ev" for vehicle in vehicles)
    assert vehicles[0]["battery_level"] == 64
    assert vehicles[1]["battery_level"] == 31
    assert vehicles[0]["charger_power"] == 7.2
    assert vehicles[1]["charger_power"] is None
    assert [vehicle["effective_battery_capacity_kwh"] for vehicle in vehicles] == [82, 57]
    assert [vehicle["battery_capacity_source"] for vehicle in vehicles] == ["manual", "manual"]


def test_stale_generic_manual_ev_id_is_rejected_before_config_lookup():
    power_sync = _power_sync_module()
    entry = _shared_entry()
    hass = _Hass([_State("select.connected_ev", "tank")], config_entries=[entry])
    view = power_sync.EVVehicleCommandView(hass)
    view._get_vehicle_charging_config = lambda *_ids: None
    assert view._manual_action_params("generic_ev") == {"_shared_loadpoint_rejected": True}
    assert view._manual_action_params(None) == {"_shared_loadpoint_rejected": True}
    assert view._manual_action_params("shared_ev_profile_a") == {"_shared_loadpoint_rejected": True}


def test_command_route_resolves_selected_logical_path_and_rejects_stale_url(monkeypatch):
    power_sync = _power_sync_module()
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **_kwargs: body)
    entry = _shared_entry()
    calls = []
    async def stop(_self, identity):
        calls.append(identity)
        return True, "stopped"
    monkeypatch.setattr(power_sync.EVVehicleCommandView, "_stop_charging", stop)
    class Request:
        def __init__(self, vin=None):
            self.vin = vin
        async def json(self):
            return {"command": "stop_charging", "vin": self.vin}

    hass = _Hass([_State("select.connected_ev", "tank")], config_entries=[entry])
    view = power_sync.EVVehicleCommandView(hass)
    assert asyncio.run(view.post(Request(), "shared_ev_profile_a"))["success"] is True
    assert calls == ["shared_ev_profile_a"]
    for path, body in (("generic_ev", None), ("generic_ev", "shared_ev_profile_a"),
                       ("shared_ev_profile_b", None), ("_default", None),
                       ("1", "generic_ev"),
                       ("shared_ev_profile_a", "generic_ev")):
        assert asyncio.run(view.post(Request(body), path))["success"] is False
    assert calls == ["shared_ev_profile_a"]
    unknown = _Hass([_State("select.connected_ev", "unknown")], config_entries=[entry])
    assert asyncio.run(power_sync.EVVehicleCommandView(unknown).post(
        Request(), "shared_ev_profile_a"))["success"] is False
    assert calls == ["shared_ev_profile_a"]


def test_vehicle_settings_view_parks_old_ev_record_but_keeps_stored_data(monkeypatch):
    power_sync = _power_sync_module()
    stored = [
        {"vehicle_id": "generic_ev", "charger_type": "generic", "active_charging_mode": "solar"},
        {"vehicle_id": "shared_ev_profile_a", "charger_type": "generic", "display_name": "GWM Tank 500"},
        {"vehicle_id": "shared_ev_profile_b", "charger_type": "generic", "display_name": "Future EV"},
    ]
    store = SimpleNamespace(_data={"vehicle_charging_configs": stored})
    hass = _Hass([], entry_data={"automation_store": store}, config_entries=[_shared_entry()])
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **_kwargs: body)
    result = asyncio.run(power_sync.VehicleChargingConfigView(hass).get(None))
    assert result["success"] is True
    assert [item["vehicle_id"] for item in result["configs"]] == [
        "shared_ev_profile_a", "shared_ev_profile_b",
    ]
    assert stored[0]["active_charging_mode"] == "solar"

    class OldVehicleRequest:
        async def json(self):
            return {"vehicle_id": "generic_ev", "active_charging_mode": "boost"}
    rejected = asyncio.run(power_sync.VehicleChargingConfigView(hass).post(OldVehicleRequest()))
    assert rejected["success"] is False
    assert stored[0]["active_charging_mode"] == "solar"


def test_logical_profile_capacity_does_not_inherit_shared_charger_fallback(monkeypatch):
    power_sync = _power_sync_module()
    entry = _shared_entry()
    entry.options["generic_charger_battery_capacity_kwh"] = 37.1
    store = SimpleNamespace(_data={"vehicle_charging_configs": [
        {"vehicle_id": "generic_ev", "charger_type": "generic",
         "charger_fallback_battery_capacity_kwh": 37.1},
        {"vehicle_id": "shared_ev_profile_a", "charger_type": "generic",
         "battery_capacity_kwh": 37.1},
        {"vehicle_id": "shared_ev_profile_b", "charger_type": "generic",
         "battery_capacity_kwh": None,
         "charger_fallback_battery_capacity_kwh": 37.1},
    ]})
    hass = _Hass([_State("select.connected_ev", "tesla")],
                 entry_data={"automation_store": store}, config_entries=[entry])
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **_kwargs: body)
    configs = asyncio.run(power_sync.VehicleChargingConfigView(hass).get(None))["configs"]
    by_id = {item["vehicle_id"]: item for item in configs}
    assert by_id["shared_ev_profile_a"]["effective_battery_capacity_kwh"] == 37.1
    assert by_id["shared_ev_profile_a"]["battery_capacity_source"] == "manual"
    assert by_id["shared_ev_profile_b"]["effective_battery_capacity_kwh"] != 37.1
    assert by_id["shared_ev_profile_b"]["battery_capacity_source"] == "default_estimate"
    assert by_id["shared_ev_profile_b"]["charger_fallback_battery_capacity_kwh"] is None
    assert store._data["vehicle_charging_configs"][0]["charger_fallback_battery_capacity_kwh"] == 37.1
    shared = importlib.import_module("power_sync.automations.shared_loadpoint")
    status = shared.project_shared_loadpoint_status(
        hass, entry, {"loadpoints": [{"loadpoint_id": "generic_ev"}]},
        vehicle_configs=store._data["vehicle_charging_configs"],
    )["loadpoints"][0]
    assert status["vehicle_id"] == "shared_ev_profile_b"
    assert status["effective_battery_capacity_kwh"] != 37.1
    assert status["battery_capacity_source"] == "default_estimate"


def test_logical_capacity_post_round_trip_and_selected_status_are_per_profile(monkeypatch):
    power_sync = _power_sync_module()
    shared = importlib.import_module("power_sync.automations.shared_loadpoint")
    entry = _shared_entry()
    entry.options["generic_charger_battery_capacity_kwh"] = 37.1
    class Store:
        _data = {"vehicle_charging_configs": [
            {"vehicle_id": "generic_ev", "charger_type": "generic",
             "charger_fallback_battery_capacity_kwh": 37.1},
            {"vehicle_id": "shared_ev_profile_a", "charger_type": "generic"},
            {"vehicle_id": "shared_ev_profile_b", "charger_type": "generic",
             "charger_fallback_battery_capacity_kwh": 37.1},
        ]}
        async def async_save(self):
            pass
    store = Store()
    hass = _Hass([_State("select.connected_ev", "tesla")],
                 entry_data={"automation_store": store}, config_entries=[entry])
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **_kwargs: body)
    view = power_sync.VehicleChargingConfigView(hass)
    class Request:
        async def json(self):
            return {"vehicle_id": "shared_ev_profile_b", "battery_capacity_kwh": 71}

    assert asyncio.run(view.post(Request()))["success"] is True
    configs = {c["vehicle_id"]: c for c in store._data["vehicle_charging_configs"]}
    assert configs["shared_ev_profile_b"]["battery_capacity_kwh"] == 71
    assert configs["shared_ev_profile_b"].get("charger_fallback_battery_capacity_kwh") is None
    assert configs["generic_ev"]["charger_fallback_battery_capacity_kwh"] == 37.1
    response = {c["vehicle_id"]: c for c in asyncio.run(view.get(None))["configs"]}
    assert response["shared_ev_profile_b"]["effective_battery_capacity_kwh"] == 71
    assert response["shared_ev_profile_b"]["battery_capacity_source"] == "manual"
    assert response["shared_ev_profile_a"]["battery_capacity_source"] == "default_estimate"
    status = shared.project_shared_loadpoint_status(
        hass, entry, {"loadpoints": [{"loadpoint_id": "generic_ev", "vehicle_id": "generic_ev"}]},
        vehicle_configs=store._data["vehicle_charging_configs"],
    )["loadpoints"][0]
    assert status["vehicle_id"] == "shared_ev_profile_b"
    assert status["effective_battery_capacity_kwh"] == 71
    assert status["battery_capacity_source"] == "manual"


def test_auto_schedule_keeps_stored_legacy_record_but_refuses_edits(monkeypatch):
    power_sync = _power_sync_module()
    planner = importlib.import_module("power_sync.automations.ev_charging_planner")
    old_settings = SimpleNamespace(to_dict=lambda: {"enabled": False})
    executor = SimpleNamespace(
        _settings={"generic_ev": old_settings},
        resolve_vehicle_capacity=lambda *_args: None,
        update_settings=lambda *_args: (_ for _ in ()).throw(AssertionError("old EV changed")),
    )
    monkeypatch.setattr(planner, "get_auto_schedule_executor", lambda: executor)
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **_kwargs: body)
    entry = _shared_entry()
    hass = _Hass([], config_entries=[entry])
    settings = asyncio.run(power_sync.AutoScheduleSettingsView(hass, entry).get(None))
    assert settings["settings"] == {"generic_ev": {"enabled": False}}
    class OldVehicleRequest:
        async def json(self):
            return {"vehicle_id": "generic_ev", "enabled": True}
    result = asyncio.run(power_sync.AutoScheduleSettingsView(hass, entry).post(OldVehicleRequest()))
    assert result["success"] is False
    toggled = asyncio.run(power_sync.AutoScheduleToggleView(hass, entry).post(OldVehicleRequest()))
    assert toggled["success"] is False
    assert executor._settings["generic_ev"] is old_settings


def test_enabled_legacy_plan_does_not_execute_when_shared_binding_is_active():
    _power_sync_module()
    planner = importlib.import_module("power_sync.automations.ev_charging_planner")
    calls = []
    async def evaluate_vehicle(vehicle_id, *_args):
        calls.append(vehicle_id)
    async def save_soc():
        return None
    fake = SimpleNamespace(
        config_entry=_shared_entry(),
        _settings={"generic_ev": SimpleNamespace(enabled=True),
                   "shared_ev_profile_a": SimpleNamespace(enabled=True)},
        _evaluate_vehicle=evaluate_vehicle,
        _sync_inactive_smart_schedule_preserve_intent=lambda: None,
        _save_cached_soc_if_needed=save_soc,
    )
    asyncio.run(planner.AutoScheduleExecutor.evaluate(fake, {}, None))
    assert calls == ["shared_ev_profile_a"]
    assert fake._settings["generic_ev"].enabled is True  # Preserved for rollback.


def test_parked_plan_cannot_reserve_capacity_for_selected_profile():
    _power_sync_module()
    planner = importlib.import_module("power_sync.automations.ev_charging_planner")
    state = SimpleNamespace(
        last_decision="charging",
        current_plan=SimpleNamespace(windows=[SimpleNamespace(
            start_time="2026-10-25T02:00:00", end_time="2026-10-25T03:00:00",
            estimated_power_kw=7.2,
        )]),
    )
    fake = SimpleNamespace(
        config_entry=_shared_entry(),
        _state={"generic_ev": state},
        _settings={"generic_ev": SimpleNamespace(enabled=True)},
    )
    reserved = planner.AutoScheduleExecutor._other_planned_ev_power_schedule(
        fake, "shared_ev_profile_a",
    )
    assert reserved == {}
    fake.config_entry = SimpleNamespace(data={}, options={})
    legacy = planner.AutoScheduleExecutor._other_planned_ev_power_schedule(fake, "other_ev")
    assert legacy == {"2026-10-25T02:00:00": 7.2}


def test_boost_request_requires_selected_logical_ev_before_any_actions(monkeypatch):
    power_sync = _power_sync_module()
    actions = importlib.import_module("power_sync.automations.actions")
    entry = _shared_entry()
    calls = []
    async def fake_execute(_hass, _entry, instructions):
        calls.extend(instructions)
        return False
    monkeypatch.setattr(actions, "execute_actions", fake_execute)
    monkeypatch.setattr(power_sync.web, "json_response", lambda body, **_kwargs: body)
    monkeypatch.setattr(
        power_sync.EVVehicleCommandView,
        "_get_vehicle_charging_config",
        lambda _self, *_ids: {
            "vehicle_id": "shared_ev_profile_a", "charger_type": "generic",
            "display_name": "GWM Tank 500",
        },
    )
    class Request:
        def __init__(self, vehicle_id):
            self.vehicle_id = vehicle_id
        async def json(self):
            return {"vehicle_id": self.vehicle_id, "duration_minutes": 60}
    for vehicle_id, selector in (("generic_ev", "tank"),
                                 ("shared_ev_profile_b", "tank"),
                                 ("shared_ev_profile_a", "unknown"),
                                 (None, "tank")):
        hass = _Hass([_State("select.connected_ev", selector)], config_entries=[entry])
        response = asyncio.run(power_sync.ChargingBoostView(hass, entry).post(Request(vehicle_id)))
        assert response["success"] is False
        assert not calls, (vehicle_id, selector, calls)

    hass = _Hass([_State("select.connected_ev", "tank")], config_entries=[entry])
    response = asyncio.run(power_sync.ChargingBoostView(hass, entry).post(Request("shared_ev_profile_a")))
    assert response["success"] is False  # Fake executor does not touch the charger.
    assert len(calls) == 1
    params = calls[0]["parameters"]
    assert params["charger_type"] == "generic"
    assert params["vehicle_id"] == "generic_ev"
    assert params["logical_vehicle_id"] == "shared_ev_profile_a"

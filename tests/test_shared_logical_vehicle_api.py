"""Logical shared-loadpoint records preserve the Android vehicle shape."""

from __future__ import annotations

import asyncio
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

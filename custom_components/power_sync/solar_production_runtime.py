"""Home Assistant wiring for negative-import PV production controls.

Adapted from upstream 24fcc7d for Amber, Sigenergy, and explicitly configured
vendor-neutral PV entities only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import asyncio

from homeassistant.helpers.storage import Store
from .solar_production import (
    ENABLED, ENTITIES, ALL_PV, EntityProductionTarget, ProductionStopManager,
    current_import_price, finite_number, _datetime,
)
from .solar_production_native import NATIVE_BRANDS, NativeProductionTarget

_LOGGER = logging.getLogger(__name__)
POWER_ENTITY = "solar_production_power_entity"
PRICE_ENTITY = "solar_production_import_price_entity"


class SolarProductionRuntime:
    def __init__(self, hass, entry, data, permitted, amber_coordinator):
        self.hass, self.entry, self.data = hass, entry, data
        self.amber_coordinator = amber_coordinator
        self.controllers = {}
        self._permission = permitted
        self.manager = ProductionStopManager(
            Store(hass, 1, f"power_sync.solar_production.{entry.entry_id}"),
            self.target, permitted,
            data.setdefault("inverter_control_lock", asyncio.Lock()),
            stop_permitted=self.can_stop,
        )
        self.paused = False
        self.after_restore = None
        self._tick_running = False

    def option(self, key, default=None):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def price(self):
        # A configured retail-price entity extends this to every tariff provider.
        # It must carry explicit interval bounds; last_changed alone is not a
        # tariff validity period (a price can remain unchanged across slots).
        entity = self.option(PRICE_ENTITY)
        if entity:
            state = self.hass.states.get(entity)
            if state is None:
                return None
            attrs = state.attributes
            unit = str(attrs.get("unit_of_measurement", "")).lower()
            factor = 100 if unit in ("$/kwh", "eur/kwh", "gbp/kwh", "aud/kwh", "€/kwh", "£/kwh") else 1 if unit in ("c/kwh", "¢/kwh", "p/kwh") else None
            price = finite_number(state.state)
            if price is None or factor is None:
                return None
            from types import SimpleNamespace
            coordinator = SimpleNamespace(data={"current": [{
                "type": "CurrentInterval", "channelType": "general", "perKwh": price * factor,
                "startTime": attrs.get("startTime") or attrs.get("valid_from"),
                "endTime": attrs.get("endTime") or attrs.get("valid_to"),
            }]})
            return current_import_price((coordinator,), datetime.now(timezone.utc))
        # This private port admits only configured Amber retail intervals.
        if self.option("electricity_provider", "amber") != "amber":
            return None
        return current_import_price(
            (self.amber_coordinator,), datetime.now(timezone.utc)
        )

    def grid_connected(self):
        now = datetime.now(timezone.utc)
        entity = self.option("solar_production_grid_connected_entity")
        if entity:
            state = self.hass.states.get(entity)
            value = str(state.state).lower() if state else ""
            stamp = _datetime(getattr(state, "last_reported", None) or getattr(state, "last_updated", None))
            connected = value == "on" if str(entity).startswith("binary_sensor.") else value in ("active", "connected", "systemgridconnected", "on-grid")
        else:
            return False
        return bool(connected and stamp and timedelta(0) <= now - stamp <= timedelta(seconds=90))

    def wants_import(self):
        price = self.price()
        return not self.paused and self.option(ENABLED, False) and price is not None and price < 0 and self._permission()

    def can_project(self):
        return bool(
            self.option(ENABLED, False) and self.option(ALL_PV, False)
            and self.manager.device_confirmed and not self.manager.suspended
            and self.manager.physical_converged is not False
            and self._permission() and not self.paused and self.grid_connected()
        )

    def can_stop(self):
        return self.wants_import() and self.grid_connected()

    def identities(self):
        entities = self.option(ENTITIES, [])
        if entities:
            if not isinstance(entities, list):
                return []
            if any(not isinstance(entity, str) or entity.split(".")[0] not in ("switch", "number") for entity in entities):
                return []
            return [{"entity_id": entity} for entity in dict.fromkeys(entities)]
        identities = []
        sigenergy = self.data.get("sigenergy_coordinator")
        if self.option("battery_system") == "sigenergy" and sigenergy is not None:
            identities.append({"brand": "sigenergy", "host": sigenergy.host,
                               "port": sigenergy.port, "slave_id": sigenergy.slave_id,
                               "model": "sigenstor"})
        return identities

    def target(self, identity):
        if "entity_id" in identity:
            return EntityProductionTarget(self.hass, identity["entity_id"])
        if identity.get("brand") not in NATIVE_BRANDS:
            return None
        key = tuple(sorted(identity.items()))
        if key not in self.controllers:
            from .inverters import get_inverter_controller
            self.controllers[key] = get_inverter_controller(
                **identity, hass=self.hass, entry_id=self.entry.entry_id
            )
        controller = self.controllers[key]
        return NativeProductionTarget(controller, identity) if controller else None

    @property
    def blocks_export_control(self):
        # Loading the journal precedes legacy callbacks even after a restart.
        return (
            self.paused or not self.manager.loaded or self.manager.owns_control
            or (self.manager.status == "external_control" and not self.manager.suspended and self.wants_import())
        )

    async def tick(self):
        if self.paused or self._tick_running:
            return
        self._tick_running = True
        try:
            sensor = self.option(POWER_ENTITY)
            state = self.hass.states.get(sensor) if sensor else None
            power = finite_number(state.state) if state else None
            if power is not None:
                unit = state.attributes.get("unit_of_measurement")
                power = power * 1000 if unit == "kW" else power if unit == "W" else None
            self.manager.observe_power(power, state.last_updated if state else None)
            was_owned = self.manager.owns_control
            await self.manager.update(self.price() if self.grid_connected() else None, self.identities(), enabled=self.option(ENABLED, False))
            if self.wants_import() and not self.grid_connected() and not self.manager.owns_control:
                self.manager.status = "grid_unavailable"
            if was_owned and not self.manager.owns_control and not self.manager.suspended and self.after_restore and self._permission() and self.grid_connected() and self.price() is not None and self.price() >= 0:
                await self.after_restore()
            sensor = self.option(POWER_ENTITY)
            state = self.hass.states.get(sensor) if sensor else None
            power = finite_number(state.state) if state else None
            if power is not None:
                unit = state.attributes.get("unit_of_measurement")
                power = power * 1000 if unit == "kW" else power if unit == "W" else None
            self.manager.observe_power(power, state.last_updated if state else None)
        except Exception:
            self.manager.status = "control_error"
            self.manager.device_confirmed = False
            self.manager.physical_converged = None
            _LOGGER.exception("Negative import solar control failed; restore journal retained")
        finally:
            self._tick_running = False
        self.publish()

    def publish(self):
        before = self.data.get("solar_production_stop", {})
        self.data["solar_production_stop"] = self.manager.as_dict()
        self.data["solar_production_stop"]["enabled"] = bool(self.option(ENABLED, False))
        self.data["solar_production_stop"]["import_price_cents"] = self.price()
        self.data["solar_production_stop"]["grid_connected"] = self.grid_connected()
        self.data["solar_production_stop"]["controls_all_pv"] = bool(self.option(ALL_PV, False))

        current = self.data["solar_production_stop"]
        keys = ("device_limit_confirmed", "physical_converged", "restore_required", "state", "grid_connected")
        if not self.paused and any(before.get(key) != current.get(key) for key in keys):
            coordinator = self.data.get("optimization_coordinator")
            replan = getattr(coordinator, "_schedule_settings_reoptimization", None)
            if callable(replan):
                replan()

    async def manual_handoff(self):
        if self.manager.loaded and not self.option(ENABLED, False) and not self.manager.owns_control:
            return True
        ok = await self.manager.release(suspend=True)
        self.publish()
        return ok

    async def shutdown(self):
        self.paused = True
        try:
            await self.manager.shutdown()
        finally:
            self.publish()
            for controller in self.controllers.values():
                if controller:
                    await controller.disconnect()
        return not self.manager.owns_control

"""Sigenergy PV production control for negative import prices.

Adapted from upstream 24fcc7d. Other inverter-native implementations from that
change are intentionally excluded; explicitly selected PV entities remain the
vendor-neutral control surface.
"""
from __future__ import annotations

from copy import deepcopy

NATIVE_BRANDS = frozenset({"sigenergy"})


class NativeProductionTarget:
    """Control only Sigenergy's PV maximum-power register."""

    refresh = False

    def __init__(self, controller, identity):
        self.controller = controller
        self.identity = identity
        self.brand = identity["brand"]

    @property
    def effective(self):
        return getattr(self, "_pv_limit_effective", False)

    async def read(self):
        if self.brand != "sigenergy":
            return None
        controller = self.controller
        if not await controller.connect():
            return None
        async with controller._modbus_transaction():
            value = await controller._get_current_pv_limit()
            enabled = await controller._read_holding_registers(
                controller.REG_REMOTE_EMS_ENABLE, 1
            )
            mode = await controller._read_holding_registers(
                controller.REG_REMOTE_EMS_CONTROL_MODE, 1
            )
            self._pv_limit_effective = bool(
                enabled == [1] and mode and mode[0] in (3, 4, 5, 6)
            )
            return (
                {"pv_limit": value}
                if value is not None and 0 <= value < 0xFFFFFFFF
                else None
            )

    def stopped(self, original):
        if self.brand != "sigenergy" or not getattr(
            self, "_pv_limit_effective", False
        ):
            return None
        state = deepcopy(original)
        state["pv_limit"] = 0
        return state

    async def write(self, state):
        if self.brand != "sigenergy":
            return False
        controller = self.controller
        if not await controller.connect() or not getattr(
            self, "allowed", lambda: True
        )():
            return False
        async with controller._modbus_transaction():
            if state["pv_limit"] == 0:
                enabled = await controller._read_holding_registers(
                    controller.REG_REMOTE_EMS_ENABLE, 1
                )
                mode = await controller._read_holding_registers(
                    controller.REG_REMOTE_EMS_CONTROL_MODE, 1
                )
                if enabled != [1] or not mode or mode[0] not in (3, 4, 5, 6):
                    return False
            if not getattr(self, "allowed", lambda: True)():
                return False
            return await controller._write_holding_registers(
                controller.REG_PV_MAX_POWER_LIMIT,
                controller._from_unsigned32(state["pv_limit"]),
            )

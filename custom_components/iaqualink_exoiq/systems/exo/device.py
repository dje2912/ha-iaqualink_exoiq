from __future__ import annotations

import logging
from enum import Enum, unique
from typing import TYPE_CHECKING, Any, cast


from ...const import MANUFACTURER

from ...device import (
    AqualinkDevice,
    AqualinkSensor,
    AqualinkSwitch,
    AqualinkThermostat,
)
from ...exception import AqualinkInvalidParameterException

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from .systems.exo.system import ExoSystem
    from .typing import DeviceData

_LOGGER = logging.getLogger(__name__)

@unique
class ExoState(Enum):
    OFF = 0
    ON = 1
    LOW = 2

class ExoDevice(AqualinkDevice):
    def __init__(self, system: ExoSystem, data: DeviceData):
        super().__init__(system, data)

        # This silences mypy errors due to AqualinkDevice type annotations.
        self.system: ExoSystem = system

    @property
    def label(self) -> str:
        name = self.name
        return " ".join([x.capitalize() for x in name.split("_")])

    @property
    def state(self) -> str:
#        return str(self.data["state"])
        return str(self.data.get("state", ""))
    
    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def manufacturer(self) -> str:
        return MANUFACTURER

    @property
    def model(self) -> str:
        return self.__class__.__name__.replace("Exo", "")

    @classmethod
    def from_data(cls, system: ExoSystem, data: DeviceData) -> ExoDevice:
        class_: type[ExoDevice]

        if data["name"].startswith("schedule_"):
            class_ = ExoAttributeSensor
        elif data["name"].startswith("aux_"):
            class_ = ExoAuxSwitch
        elif data["name"].startswith("sns_"):
            class_ = ExoSensor
        elif data["name"] == "heating":
            class_ = ExoThermostat
        elif data["name"] in ["production", "boost", "low"]:
            class_ = ExoAttributeSwitch
        else:
            class_ = ExoAttributeSensor

        return class_(system, data)


class ExoSensor(ExoDevice, AqualinkSensor):
    """These sensors are called sns_#."""

    @property
    def is_on(self) -> bool:
        return ExoState(self.data["state"]) == ExoState.ON

    @property
    def state(self) -> str:
        if self.is_on:
            return str(self.data["value"])
        return ""

    @property
    def label(self) -> str:
        return self.data["sensor_type"]

    @property
    def name(self) -> str:
        # XXX: We're using the label as name rather than "sns_#".
        # Might revisit later.
        return self.data["sensor_type"].lower().replace(" ", "_")


class ExoAttributeSensor(ExoDevice, AqualinkSensor):
    """These sensors are a simple key/value in equipment->swc_0."""


# This is an abstract class, not to be instantiated directly.
class ExoSwitch(ExoDevice, AqualinkSwitch):
    @property
    def label(self) -> str:
        return self.name.replace("_", " ").capitalize()

    @property
    def is_on(self) -> bool:
        #return ExoState(self.data["state"]) == ExoState.ON
        state = int(self.data.get("state", 0))
        #return state == ExoState.ON.value
        return state != 0

    @property
    def _command(self) -> Callable[[str, int], Coroutine[Any, Any, None]]:
        raise NotImplementedError

    async def turn_on(self) -> None:
        _LOGGER.debug("iAQUALINK_eXO-IQ - EXO DEVICE turn_on called name=%s state=%s is_on=%s", self.name, self.data.get("state"), self.is_on)
        if not self.is_on:
            cmd = self._command
            _LOGGER.debug("iAQUALINK_eXO-IQ - EXO DEVICE turn_on will call %s(%s, 1)", getattr(cmd, "__name__", str(cmd)), self.name)
            await cmd(self.name, 1)
        else:
            _LOGGER.debug("iAQUALINK_eXO-IQ - EXO DEVICE turn_on skipped (already on) name=%s", self.name)

    async def turn_off(self) -> None:
        _LOGGER.debug("iAQUALINK_eXO-IQ - EXO DEVICE turn_off called name=%s state=%s is_on=%s", self.name, self.data.get("state"), self.is_on)
        if self.is_on:
            cmd = self._command
            _LOGGER.debug("iAQUALINK_eXO-IQ - EXO DEVICE turn_off will call %s(%s, 0)", getattr(cmd, "__name__", str(cmd)), self.name)
            await cmd(self.name, 0)
        else:
            _LOGGER.debug("iAQUALINK_eXO-IQ - EXO DEVICE turn_off skipped (already off) name=%s", self.name)


class ExoAuxSwitch(ExoSwitch):
    @property
    def _command(self) -> Callable[[str, int], Coroutine[Any, Any, None]]:
        return self.system.set_aux

class ExoAttributeSwitch(ExoSwitch):
    @property
    def _command(self) -> Callable[[str, int], Coroutine[Any, Any, None]]:
        return self.system.set_toggle

class ExoScheduleSensor(ExoDevice, AqualinkSensor):
    """Schedule sensor: exposes timer and status via attributes."""

class ExoThermostat(ExoSwitch, AqualinkThermostat):
    @property
    def state(self) -> str:
        return str(self.data["sp"])

    @property
    def unit(self) -> str:
        return "C"

    @property
    def _sensor(self) -> ExoSensor:
        return cast(ExoSensor, self.system.devices["sns_3"])

    @property
    def current_temperature(self) -> str:
        return self._sensor.state

    @property
    def target_temperature(self) -> str:
        return str(self.data["sp"])

    @property
    def min_temperature(self) -> int:
        return int(self.data["sp_min"])

    @property
    def max_temperature(self) -> int:
        return int(self.data["sp_max"])

    async def set_temperature(self, temperature: int) -> None:
        unit = self.unit
        low = self.min_temperature
        high = self.max_temperature

        if temperature not in range(low, high + 1):
            msg = f"{temperature}{unit} isn't a valid temperature"
            msg += f" ({low}-{high}{unit})."
            raise AqualinkInvalidParameterException(msg)

        await self.system.set_heating("sp", temperature)

    @property
    def is_on(self) -> bool:
        state = int(self.data.get("state", 0))
        return state != 0

    async def turn_on(self) -> None:
        if self.is_on is False:
            await self.system.set_heating("enabled", 1)

    async def turn_off(self) -> None:
        if self.is_on is True:
            await self.system.set_heating("enabled", 0)

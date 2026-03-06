"""Support for Aqualink Thermostats."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AqualinkEntity, refresh_system
from .const import (
    AQUALINK_TEMP_CELSIUS_HIGH,
    AQUALINK_TEMP_CELSIUS_LOW,
    AQUALINK_TEMP_FAHRENHEIT_HIGH,
    AQUALINK_TEMP_FAHRENHEIT_LOW,
    DOMAIN as AQUALINK_DOMAIN,
)
from .device import AqualinkHeater, AqualinkPump, AqualinkSensor, AqualinkThermostat
from .utils import await_or_reraise

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs = entry_data["platform_devices"][CLIMATE_DOMAIN]

    entities = []
    seen: set[str] = set()

    for aux_dev in devs:
        aux_name = (getattr(aux_dev, "name", "") or "").lower()
        aux_data = getattr(aux_dev, "data", None)
        if not isinstance(aux_data, dict):
            continue

        # STRICT: on ne crée un climate QUE pour aux_* type heat
        if not aux_name.startswith("aux_"):
            continue
        if str(aux_data.get("type", "")).lower() != "heat":
            continue

        # On doit avoir le bloc "heating" dans system.devices
        heating_dev = aux_dev.system.devices.get("heating")
        if heating_dev is None:
            _LOGGER.debug("Skip %s: missing system.devices['heating']", aux_name)
            continue

        heating_data = getattr(heating_dev, "data", None)
        heating_data = heating_data if isinstance(heating_data, dict) else {}

        # STRICT: on exige sp/sp_min/sp_max dans heating
        required = ("sp", "sp_min", "sp_max")
        if not all(k in heating_data for k in required):
            _LOGGER.debug(
                "Skip %s: heating missing required keys (%s), keys=%s",
                aux_name, required, list(heating_data.keys())[:20]
            )
            continue

        ent = AuxHeatingClimateEntity(coordinator, aux_dev, heating_dev)

        if ent.unique_id in seen:
            continue
        seen.add(ent.unique_id)
        entities.append(ent)

    async_add_entities(entities, True)


class AuxHeatingClimateEntity(AqualinkEntity, ClimateEntity):
    # Heating ExoIQ
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator, aux_dev: AqualinkThermostat, heating_dev: AqualinkThermostat):
        super().__init__(coordinator, aux_dev)
        self._aux = aux_dev
        self._heating = heating_dev

        # Friendly name
        if (getattr(aux_dev, "name", "") or "").lower() == "aux_2":
            self._attr_name = "Aux2-Heating"
        else:
            self._attr_name = f"{getattr(aux_dev, 'label', 'Aux Heating')}"

        serial = getattr(aux_dev.system, "serial", "unknown")
        self._attr_unique_id = f"{serial}_{getattr(aux_dev, 'name', 'aux')}_heating"

        # Optimistic UI state
        self._optimistic_hvac_mode: HVACMode | None = None
        self._optimistic_target_temperature: float | None = None

    @property
    def temperature_unit(self) -> UnitOfTemperature:
        return UnitOfTemperature.FAHRENHEIT if getattr(self.dev.system, "temp_unit", "C") == "F" else UnitOfTemperature.CELSIUS

    @property
    def min_temp(self) -> float:
        try:
            return float(self._heating.data.get("sp_min"))
        except Exception:
            return float(AQUALINK_TEMP_CELSIUS_LOW)

    @property
    def max_temp(self) -> float:
        try:
            return float(self._heating.data.get("sp_max"))
        except Exception:
            return float(AQUALINK_TEMP_CELSIUS_HIGH)

    @property
    def target_temperature(self) -> float | None:
        # Optimistic target temperature first
        if self._optimistic_target_temperature is not None:
            return self._optimistic_target_temperature

        try:
            return float(self._heating.data.get("sp"))
        except Exception:
            return None

    @property
    def current_temperature(self) -> float | None:
        # sns_3 preferred
        devices = getattr(self.dev.system, "devices", {}) or {}
        s = devices.get("sns_3") or devices.get("water_temp") or devices.get("temp")
        if s is None:
            return None
        val = getattr(s, "state", None)
        if val in ("", None):
            return None
        try:
            return float(val)
        except Exception:
            return None

    def _enabled_val(self) -> int:
        d = getattr(self._heating, "data", {}) or {}
        try:
            return int(d.get("enabled", 0) or 0)
        except Exception:
            return 0

    @property
    def hvac_mode(self):
        # Optimistic hvac mode first
        if self._optimistic_hvac_mode is not None:
            return self._optimistic_hvac_mode

        return HVACMode.HEAT if self._enabled_val() == 1 else HVACMode.OFF

    @refresh_system
    async def async_set_hvac_mode(self, hvac_mode):
        # IMPORTANT: drive "heating.enabled" through the heating object
        previous_mode = self._optimistic_hvac_mode
        self._optimistic_hvac_mode = hvac_mode

        try:
            if hvac_mode == HVACMode.OFF:
                await self._heating.turn_off()
            elif hvac_mode == HVACMode.HEAT:
                await self._heating.turn_on()
            else:
                _LOGGER.warning("Unsupported HVAC mode requested: %s", hvac_mode)
        except Exception:
            # Rollback optimistic state if command failed
            self._optimistic_hvac_mode = previous_mode
            raise

    @refresh_system
    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        previous_target = self._optimistic_target_temperature
        self._optimistic_target_temperature = float(temperature)

        try:
            await await_or_reraise(self._heating.set_temperature(int(float(temperature))))
        except Exception:
            # Rollback optimistic state if command failed
            self._optimistic_target_temperature = previous_target
            raise

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Real API data has arrived -> clear optimistic overrides
        self._optimistic_hvac_mode = None
        self._optimistic_target_temperature = None
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes or {}
        d = getattr(self._heating, "data", {}) or {}

        # Attributes exposed from heating block
        for k in ("enabled", "sp", "sp_min", "sp_max", "priority_enabled", "state"):
            if k in d:
                attrs[k] = d.get(k)

        # Useful debug
        attrs["aux_name"] = getattr(self._aux, "name", None)
        attrs["heating_name"] = getattr(self._heating, "name", None)
        return attrs


class AqualinkThermostatEntity(AqualinkEntity, ClimateEntity):
    # Thermostat legacy

    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator, dev: AqualinkThermostat) -> None:
        super().__init__(coordinator, dev)
    
        # Friendly name
        if getattr(dev, "name", "") in ("heating", "aux_2"):
            self._attr_name = "Aux2-Heating"
        else:
            self._attr_name = dev.label
    
        # Unique_id stable (NE PAS utiliser le label)
        dev_key = getattr(dev, "name", None) or dev.label.lower().replace(" ", "_")
        self._attr_unique_id = f"{dev.system.serial}_{dev_key}"

    @property
    def temperature_unit(self) -> UnitOfTemperature:
        if getattr(self.dev.system, "temp_unit", "C") == "F":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def min_temp(self) -> float:
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return float(AQUALINK_TEMP_FAHRENHEIT_LOW)
        return float(AQUALINK_TEMP_CELSIUS_LOW)

    @property
    def max_temp(self) -> float:
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return float(AQUALINK_TEMP_FAHRENHEIT_HIGH)
        return float(AQUALINK_TEMP_CELSIUS_HIGH)

    @property
    def target_temperature(self) -> float | None:
        try:
            return float(self.dev.state)
        except (TypeError, ValueError):
            return None

    @property
    def sensor(self) -> AqualinkSensor | None:
        #Return the linked sensor (never raise).
        dev_name = (getattr(self.dev, "name", "") or "").lower()

        # ExoIQ: heating & aux_2 use water temperature (sns_3 preferred)
        if dev_name in ("heating", "aux_2"):
            if "sns_3" in self.dev.system.devices:
                return self.dev.system.devices["sns_3"]
            if "temp" in self.dev.system.devices:
                return self.dev.system.devices["temp"]
            _LOGGER.debug("No water temp sensor found for %s (sns_3/temp missing)", dev_name)
            return None

        # Generic rule (other thermostats)
        key = f"{dev_name}_temp"
        return self.dev.system.devices.get(key)

    @property
    def current_temperature(self) -> float | None:
        s = self.sensor
        if s is None:
            return None

        val = getattr(s, "state", None)
        if val in ("", None):
            return None

        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    @property
    def heater(self) -> AqualinkHeater:
        dev_name = getattr(self.dev, "name", "").lower()

        # ExoIQ : switch linked to Heating
        if dev_name == "heating":
            return self.dev.system.devices["heater"]

        # fallback old behaviour
        heater_key = f"{self.name.lower()}_heater"
        return self.dev.system.devices[heater_key]

    @property
    def pump(self) -> AqualinkPump:
        pump = f"{self.name.lower()}_pump"
        return self.dev.system.devices[pump]

    def _enabled_val(self) -> int:
        d = getattr(self.dev, "data", {}) or {}
        v = d.get("enabled", None)
        if v is None:
            v = d.get("state", 0)  # aux_2 souvent = state
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    
    @property
    def hvac_mode(self):
        return HVACMode.HEAT if self._enabled_val() == 1 else HVACMode.OFF

    @refresh_system
    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode == HVACMode.OFF:
            await self.dev.turn_off()
    
        elif hvac_mode == HVACMode.HEAT:
            await self.dev.turn_on()
    
        else:
            _LOGGER.warning("Unsupported HVAC mode requested: %s", hvac_mode)

    @refresh_system
    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await await_or_reraise(self.dev.set_temperature(int(float(temperature))))
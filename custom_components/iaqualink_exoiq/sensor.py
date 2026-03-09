"""Support for Aqualink sensors."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AqualinkEntity
from .const import DOMAIN as AQUALINK_DOMAIN
from .device import AqualinkSensor

PARALLEL_UPDATES = 0
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    _LOGGER.debug("IAQUALINK_EXOIQ - sensor.py async_setup_entry CALLED")

    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs = entry_data["platform_devices"][SENSOR_DOMAIN]

    _LOGGER.debug(
        "IAQUALINK_EXOIQ - sensor.py devs count=%s schedule_devs=%s",
        len(devs),
        [getattr(d, "name", "") for d in devs if getattr(d, "name", "").startswith("schedule_")][:20],
    )

    entities = []
    for dev in devs:
        try:
            entities.append(AqualinkSensorEntity(coordinator, dev))
        except Exception:
            _LOGGER.exception(
                "IAQUALINK_EXOIQ - sensor.py FAILED to create entity for dev=%s class=%s data=%s",
                getattr(dev, "name", None),
                dev.__class__.__name__,
                getattr(dev, "data", None),
            )

    _LOGGER.debug("IAQUALINK_EXOIQ - sensor.py about to async_add_entities count=%s", len(entities))
    async_add_entities(entities, True)
    _LOGGER.debug("IAQUALINK sensor.py async_add_entities DONE")


class AqualinkSensorEntity(AqualinkEntity, SensorEntity):
    """Representation of a sensor."""

    def __init__(self, coordinator, dev: AqualinkSensor) -> None:
        super().__init__(coordinator, dev)

        _LOGGER.debug("IAQUALINK_EXOIQ - sensor entity init dev=%s label=%s", dev.name, dev.label)

        # Default Name
        #name = dev.label
        label = getattr(dev, "label", None)
        try:
            default_name = label if isinstance(label, str) else dev.name
        except Exception:
            default_name = dev.name
        name = default_name

        # Friendly name for schedules
        if dev.name.startswith("schedule_"):
            sched_name = dev.data.get("schedule_name")
            if sched_name:
                if dev.name.endswith("_rpm"):
                    name = f"Sch {sched_name} - Speed"
                else:
                    name = f"Sch {sched_name}"

        self._attr_name = name
        self._attr_unique_id = f"{dev.system.serial}_{dev.name}"

        # Entity "diagnostic" (infos appareil)
        exo_diag_names = {
            "sn": "Exo Serial Number",
            "vr": "Exo Firmware Version",
            "version": "Exo Software Version",
            "error_state": "Exo Error State",
            "error_code": "Exo Error Code",
            "exo_rssi": "Exo RSSI",
            "exo_fw_version": "Exo Cloud Firmware Version",
            "exo_cloud_timestamp": "Exo Cloud Timestamp",
        }

        if self.dev.name in exo_diag_names:
            self._attr_name = exo_diag_names[self.dev.name]
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Temperature
        if self.dev.name.endswith("_temp"):
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
        
        #Cache value for refersh feezing when Production == 0
        self._last_good_value = None
        self._is_frozen = False

    def _production_is_off(self) -> bool:
        """True si production == 0. If unknown -> False (don't freeze)."""
        try:
            prod_dev = self.dev.system.devices.get("production")
            if not prod_dev:
                return False
    
            prod_state = getattr(prod_dev, "state", None)
            if prod_state is None and hasattr(prod_dev, "data"):
                prod_state = prod_dev.data.get("state")
    
            # normalise
            if isinstance(prod_state, str):
                s = prod_state.strip()
                if s.isdigit():
                    prod_state = int(s)
    
            return prod_state == 0
        except Exception:
            return False


    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the measurement unit for the sensor."""
        # Temperatures
        if self.dev.name.endswith("_temp"):
            return (
                UnitOfTemperature.FAHRENHEIT
                if self.dev.system.temp_unit == "F"
                else UnitOfTemperature.CELSIUS
            )

        # Pourcentages (chlorinateur)
        if self.dev.name in ("swc", "swc_low"):
            return "%"

        # Voltage (ORP)
        if self.dev.name in ("orp", "orp_sp"):
            return "mV"

        # Pump Speed (RPM)
        if self.dev.name.endswith("_rpm"):
            return "rpm"

        # RSSI (dBm)
        if self.dev.name == "exo_rssi":
            return "dBm"

        return None
    
    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes or {}
    
        # --- Frozen sensors ---
        if self.dev.name in {"ph", "orp", "water_temp", "sns_1", "sns_2", "sns_3"}:
            attrs["frozen"] = getattr(self, "_is_frozen", False)
    
        # --- Schedule main sensor ---
        if (
            self.dev.name.startswith("schedule_")
            and not self.dev.name.endswith(("_rpm", "_enabled", "_active"))
        ):
            attrs.update(
                {
                    "schedule_id": self.dev.data.get("schedule_id"),
                    "schedule_name": self.dev.data.get("schedule_name"),
                    "endpoint": self.dev.data.get("endpoint"),
                    "start": self.dev.data.get("start"),
                    "end": self.dev.data.get("end"),
                }
            )
    
        return attrs

    @property
    def native_value(self):
        # ----- Return the state of the sensor. -----
        raw = self.dev.state
        if raw in ("", None):
            return None

        freeze_targets = {"ph", "orp", "water_temp", "sns_1", "sns_2", "sns_3"}
        is_freeze_target = self.dev.name in freeze_targets
        should_freeze = is_freeze_target and (self._production_is_off() or not self.available)

        # 1) Value deinition "val" normally
        val = None

        # ----- Schedule RPM sensor (must be numeric) -----
        if self.dev.name.endswith("_rpm"):
            try:
                val = int(raw)
            except (TypeError, ValueError):
                val = None

        # ----- Schedule (readable string) -----
        elif self.dev.name.startswith("schedule_"):
            start = self.dev.data.get("start")
            end = self.dev.data.get("end")
            val = f"{start} → {end}" if start and end else None

        # ----- pH : API return 72 -> 7.2 -----
        elif self.dev.name in ("ph", "ph_sp"):
            try:
                val = float(raw) / 10
            except (TypeError, ValueError):
                val = None

        # ----- Timestamp ----- 
        elif self.dev.name == "exo_cloud_timestamp":
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        # ----- Default: int / float sinon string -----
        else:
            try:
                val = int(raw)
            except (TypeError, ValueError):
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    val = raw
                
        # ----- FREEZE LOGIC -----
        if should_freeze:
            if not self._is_frozen:
                _LOGGER.debug(
                    "IAQUALINK_EXOIQ - Freezing %s (production=0) last=%s",
                    self.dev.name,
                    self._last_good_value,
                )
    
            self._is_frozen = True
    
            # Au reboot, si pas de cache -> initialise une fois
            if self._last_good_value is None and val is not None:
                self._last_good_value = val
    
            return self._last_good_value

        # ----- NOT FREEZE -----
        if self._is_frozen:
            _LOGGER.debug(
                "IAQUALINK_EXOIQ - Unfreezing %s (production resumed)",
                self.dev.name,
            )
    
        self._is_frozen = False
    
        if is_freeze_target and val is not None:
            self._last_good_value = val
    
        return val
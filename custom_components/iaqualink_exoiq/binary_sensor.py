"""Support for Aqualink binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    DOMAIN as BINARY_SENSOR_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AqualinkEntity
from .const import DOMAIN as AQUALINK_DOMAIN
from .device import AqualinkBinarySensor

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up discovered binary sensors."""
    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs: list[AqualinkBinarySensor] = entry_data["platform_devices"][BINARY_SENSOR_DOMAIN]

    async_add_entities(
        (AqualinkBinarySensorEntity(coordinator, dev) for dev in devs),
        True,
    )


class AqualinkBinarySensorEntity(AqualinkEntity, BinarySensorEntity):
    """Representation of a binary sensor."""

    def __init__(self, coordinator, dev) -> None:
        super().__init__(coordinator, dev)

        dev_name = getattr(dev, "name", "") or ""
        dev_label = getattr(dev, "label", None)

        self._attr_name = dev_label if isinstance(dev_label, str) else dev_name
        self._attr_unique_id = f"{dev.system.serial}_{dev_name}"

        # --- SCHEDULE binary sensors ---
        if dev_name.startswith("schedule_"):
            sched_name = (getattr(dev, "data", {}) or {}).get("schedule_name")
            if sched_name:
                if dev_name.endswith("_enabled"):
                    self._attr_name = f"Sch {sched_name} - Enabled"
                    self._attr_device_class = BinarySensorDeviceClass.POWER
                elif dev_name.endswith("_active"):
                    self._attr_name = f"Sch {sched_name} - Active"
                    self._attr_device_class = BinarySensorDeviceClass.RUNNING
            return  # important: to leave and avoid other rules

        # --- Pump / connectivity / freeze protection ---
        if dev_name == "filter_pump":
            self._attr_device_class = BinarySensorDeviceClass.RUNNING

        elif dev_name == "exo_state":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

        elif self._attr_name == "Freeze Protection":
            self._attr_device_class = BinarySensorDeviceClass.COLD

        # --- MQTT binary sensor ---
        exo_diag_binary_names = {
            "exo_mqtt_status": "Exo MQTT Status",
            "exo_mqtt_connection": "Exo MQTT Connection",
        }

        if dev_name in exo_diag_binary_names:
            self._attr_name = exo_diag_binary_names[dev_name]
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        raw = getattr(self.dev, "state", None)
    
        if raw is None:
            return False
    
        # Bool direct
        if isinstance(raw, bool):
            return raw
    
        # Numéric
        if isinstance(raw, (int, float)):
            return raw != 0
    
        # String
        s = str(raw).strip().lower()
    
        if s in ("", "0", "false", "off", "none", "null"):
            return False
    
        if s in ("1", "true", "on"):
            return True
    
        # Try numeric conversion 
        try:
            return float(s) != 0
        except ValueError:
            # fallback : all non empty value = ON
            return True
        
        

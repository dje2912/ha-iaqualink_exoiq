"""Support for Aqualink timer number entities."""

from __future__ import annotations

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN as AQUALINK_DOMAIN
from .timer_group import AqualinkTimerGroupEntity
from .timer_helpers import get_timer_unique_id

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Aqualink timer number entities."""
    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs = entry_data["platform_devices"][NUMBER_DOMAIN]

    entities = []
    for dev in devs:
        dev_name = getattr(dev, "name", "") or ""

        if not dev_name.startswith("schedule_"):
            continue

        if not dev_name.endswith("_rpm"):
            continue

        entities.append(AqualinkTimerSpeedEntity(coordinator, dev))

    async_add_entities(entities, True)


class AqualinkTimerSpeedEntity(AqualinkTimerGroupEntity, NumberEntity):
    """Representation of a grouped timer pump speed setting."""

    _attr_native_min_value = 600
    _attr_native_max_value = 3450
    _attr_native_step = 50
    _attr_native_unit_of_measurement = "rpm"
    _attr_mode = "slider"
    _attr_has_entity_name = True

    def __init__(self, coordinator, dev) -> None:
        super().__init__(coordinator, dev)

        self._attr_name = "Pump Speed"
        role = self.timer_role.lower()
        self._attr_unique_id = get_timer_unique_id(
            dev.system.serial,
            "number",
            self.group_id,
            self.schedule_endpoint,
            "speed",
        )
        self._attr_suggested_object_id = self._build_timer_object_id()
        self._attr_icon = "mdi:pump"

    def _build_timer_object_id(self) -> str:
        """Build timer-based object id."""
        role = self.timer_role.lower()
        return f"{self.group_id}_{role}_speed"

    @property
    def native_value(self) -> float | None:
        raw = self.dev.system.get_timer_editor_rpm(self.schedule_dev_name)
        if raw in ("", None):
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        self.dev.system.stage_timer_change(
            self.schedule_dev_name,
            {"rpm": int(value)},
        )
        self.async_write_ha_state()
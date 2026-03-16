"""Support for Aqualink timer time entities."""

from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import DOMAIN as TIME_DOMAIN, TimeEntity
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
    """Set up Aqualink timer time entities."""
    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs = entry_data["platform_devices"][TIME_DOMAIN]

    entities = []
    for dev in devs:
        dev_name = getattr(dev, "name", "") or ""

        if not dev_name.startswith("schedule_"):
            continue
        if dev_name.endswith(("_rpm", "_enabled", "_active")):
            continue

        entities.append(AqualinkTimerTimeEntity(coordinator, dev, "start"))
        entities.append(AqualinkTimerTimeEntity(coordinator, dev, "end"))

    async_add_entities(entities, True)


class AqualinkTimerTimeEntity(AqualinkTimerGroupEntity, TimeEntity):
    """Representation of a grouped timer time field."""

    def __init__(self, coordinator, dev, time_kind: str) -> None:
        super().__init__(coordinator, dev)

        self._time_kind = time_kind
        self._attr_name = (
            f"{self.timer_role} Start"
            if time_kind == "start"
            else f"{self.timer_role} End"
        )
        role = self.timer_role.lower()
        self._attr_unique_id = get_timer_unique_id(
            dev.system.serial,
            "time",
            self.group_id,
            self.schedule_endpoint,
            time_kind,
        )
        self._attr_suggested_object_id = self._build_timer_object_id()

    def _build_timer_object_id(self) -> str:
        """Build timer-based object id."""
        role = self.timer_role.lower()
        return f"{self.group_id}_timer_time_{role}_{self._time_kind}"

    @property
    def native_value(self) -> dt_time | None:
        raw = self.dev.system.get_timer_editor_value(
            self.schedule_dev_name,
            self._time_kind,
        )

        if not raw or not isinstance(raw, str):
            return None

        try:
            hh, mm = raw.split(":")
            return dt_time(hour=int(hh), minute=int(mm))
        except (ValueError, TypeError):
            return None

    async def async_set_value(self, value: dt_time) -> None:
        hhmm = f"{value.hour:02d}:{value.minute:02d}"

        self.dev.system.stage_timer_change(
            self.schedule_dev_name,
            {self._time_kind: hhmm},
        )
        self.async_write_ha_state()
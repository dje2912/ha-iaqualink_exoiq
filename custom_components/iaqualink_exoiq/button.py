"""Support for Aqualink timer action buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, DOMAIN as BUTTON_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN as AQUALINK_DOMAIN
from .timer_group import AqualinkTimerGroupEntity
from .timer_helpers import get_timer_unique_id
from .exception import AqualinkServiceException

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Aqualink timer buttons."""
    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs = entry_data["platform_devices"][BUTTON_DOMAIN]

    group_candidates: dict[str, list] = {}

    for dev in devs:
        dev_name = getattr(dev, "name", "") or ""

        if not dev_name.startswith("schedule_"):
            continue

        if dev_name.endswith(("_rpm", "_enabled", "_active")):
            continue

        tmp = AqualinkTimerGroupButtonProbe(coordinator, dev)
        group_candidates.setdefault(tmp.group_id, []).append(dev)

    entities = []

    for _group_id, candidates in group_candidates.items():
        representative = None

        # Prefer Pump timer when group contains Pump + SWC
        for dev in candidates:
            endpoint = ((dev.data or {}).get("endpoint") or "").lower()
            if endpoint.startswith("vsp_"):
                representative = dev
                break

        if representative is None:
            representative = candidates[0]

        entities.append(AqualinkTimerSaveButton(coordinator, representative))
        entities.append(AqualinkTimerClearButton(coordinator, representative))

    async_add_entities(entities, True)


class AqualinkTimerGroupButtonProbe(AqualinkTimerGroupEntity):
    """Helper class used only to resolve timer group id."""
    pass


class AqualinkTimerSaveButton(AqualinkTimerGroupEntity, ButtonEntity):
    """Save all staged changes for one timer group."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, dev) -> None:
        super().__init__(coordinator, dev)

        self._attr_name = "Save"
        self._attr_unique_id = get_timer_unique_id(
            dev.system.serial,
            "action",
            self.group_id,
            self.schedule_endpoint,
            "save",
        )
        self._attr_suggested_object_id = f"{self.group_id}_save"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:content-save-outline"

    async def async_press(self) -> None:
        try:
            await self.dev.system.save_timer_group(self.group_id)
        except AqualinkServiceException as err:
            raise HomeAssistantError(str(err)) from err

        self.coordinator.async_update_listeners()


class AqualinkTimerClearButton(AqualinkTimerGroupEntity, ButtonEntity):
    """Clear and disable one timer group."""

    _attr_has_entity_name = True
    
    def __init__(self, coordinator, dev) -> None:
        super().__init__(coordinator, dev)

        self._attr_name = "Clear"
        self._attr_unique_id = get_timer_unique_id(
            dev.system.serial,
            "action",
            self.group_id,
            self.schedule_endpoint,
            "clear",
        )
        self._attr_suggested_object_id = f"{self.group_id}_clear"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:timer-off-outline"

    async def async_press(self) -> None:
        try:
            await self.dev.system.clear_timer_group(self.group_id)
        except AqualinkServiceException as err:
            raise HomeAssistantError(str(err)) from err

        self.coordinator.async_update_listeners()
"""Support for Aqualink binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    DOMAIN as BINARY_SENSOR_DOMAIN,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import AqualinkEntity
from .const import (
    DOMAIN as AQUALINK_DOMAIN,
    ENTITY_DIAG_BINARY_SENSOR_NAMES,
    ENTITY_ICONS,
)
from .device import AqualinkBinarySensor
from .timer_helpers import (
    get_timer_group_from_endpoint,
    get_timer_role_from_endpoint,
    get_timer_unique_id,
)

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

        if dev_name.startswith("schedule_"):
            endpoint = (getattr(dev, "data", {}) or {}).get("endpoint")
            group = get_timer_group_from_endpoint(endpoint)

            if group is not None:
                group_id = group[0]
                role = get_timer_role_from_endpoint(endpoint).lower()

                if dev_name.endswith("_enabled"):
                    self._attr_name = (
                        f"{role.upper() if role == 'swc' else role.capitalize()} Enabled"
                    )
                    self._attr_device_class = BinarySensorDeviceClass.POWER

                    self._attr_unique_id = get_timer_unique_id(
                        dev.system.serial,
                        "binary",
                        group_id,
                        endpoint,
                        "enabled",
                    )

                    self._attr_suggested_object_id = f"{group_id}_{role}_enabled"

                elif dev_name.endswith("_active"):
                    self._attr_name = (
                        f"{role.upper() if role == 'swc' else role.capitalize()} Active"
                    )
                    self._attr_device_class = BinarySensorDeviceClass.RUNNING

                    self._attr_unique_id = get_timer_unique_id(
                        dev.system.serial,
                        "binary",
                        group_id,
                        endpoint,
                        "active",
                    )

                    self._attr_suggested_object_id = f"{group_id}_{role}_active"

            return

        # --- Icon for all binary sensor entities ---
        if dev_name in ENTITY_ICONS:
            self._attr_icon = ENTITY_ICONS[dev_name]

        # --- Class for system binary sensors ---
        if dev_name == "filter_pump":
            self._attr_device_class = BinarySensorDeviceClass.RUNNING
        elif dev_name == "exo_state":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        elif self._attr_name == "Freeze Protection":
            self._attr_device_class = BinarySensorDeviceClass.COLD

        # --- Friendly name + category + class for diagnostic binary sensors ---
        if dev_name in ENTITY_DIAG_BINARY_SENSOR_NAMES:
            self._attr_name = ENTITY_DIAG_BINARY_SENSOR_NAMES[dev_name]
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        raw = getattr(self.dev, "state", None)

        if raw is None:
            return False

        if isinstance(raw, bool):
            return raw

        if isinstance(raw, (int, float)):
            return raw != 0

        s = str(raw).strip().lower()

        if s in ("", "0", "false", "off", "none", "null"):
            return False

        if s in ("1", "true", "on"):
            return True

        try:
            return float(s) != 0
        except ValueError:
            return True
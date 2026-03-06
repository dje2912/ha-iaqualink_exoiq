"""Support for Aqualink switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AqualinkEntity, refresh_system
from .const import DOMAIN as AQUALINK_DOMAIN
from .device import AqualinkToggle

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger("iaqualink")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Aqualink switches."""
    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs: list[AqualinkToggle] = entry_data["platform_devices"][SWITCH_DOMAIN]

    async_add_entities(
        (AqualinkSwitchEntity(coordinator, dev) for dev in devs),
        True,
    )


class AqualinkSwitchEntity(AqualinkEntity, SwitchEntity):
    """Representation of an Aqualink switch."""

    def __init__(self, coordinator, dev: AqualinkToggle) -> None:
        super().__init__(coordinator, dev)
        self._attr_name = dev.label
        self._attr_unique_id = f"{dev.system.serial}_{dev.name}"

        # Optimistic UI state
        self._optimistic_state: bool | None = None  # None = not in optimistic mode

        # Keep display toggle responsive
        self._attr_assumed_state = False

    def _read_is_on_from_device(self) -> bool:
        """Read switch state from device data."""
        # Exo: state can be 0/1/2 => 0 OFF, 1 ON, 2 LOW (considered ON)
        data = getattr(self.dev, "data", None)
        if isinstance(data, dict):
            state = data.get("state")
            if state is not None:
                try:
                    return int(state) != 0
                except (TypeError, ValueError):
                    return False

        raw = getattr(self.dev, "state", None)
        if raw is not None:
            try:
                return int(raw) != 0
            except (TypeError, ValueError):
                return bool(raw)

        is_on_attr = getattr(self.dev, "is_on", False)
        return bool(is_on_attr() if callable(is_on_attr) else is_on_attr)

    @property
    def is_on(self) -> bool:
        """Return True if switch is on."""
        # Optimistic state first
        if self._optimistic_state is not None:
            return self._optimistic_state

        return self._read_is_on_from_device()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Real API data has arrived -> clear optimistic override
        self._optimistic_state = None
        super()._handle_coordinator_update()

    @refresh_system
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        _LOGGER.debug("HA async_turn_on %s dev=%s", self.entity_id, self.dev.name)
        _LOGGER.debug("HA dev class=%s data=%s", self.dev.__class__.__name__, getattr(self.dev, "data", None))

        # Optimistic UI
        self._optimistic_state = True
        await self.dev.turn_on()

    @refresh_system
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        _LOGGER.debug("HA async_turn_off %s dev=%s", self.entity_id, self.dev.name)
        _LOGGER.debug("HA dev class=%s data=%s", self.dev.__class__.__name__, getattr(self.dev, "data", None))

        # Optimistic UI
        self._optimistic_state = False
        await self.dev.turn_off()
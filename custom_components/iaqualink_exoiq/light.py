"""Support for Aqualink lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AqualinkEntity, refresh_system
from .const import DOMAIN as AQUALINK_DOMAIN
from .device import AqualinkLight

try:
    from .exception import AqualinkOperationNotSupportedException
except Exception:  # pragma: no cover
    AqualinkOperationNotSupportedException = Exception

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up discovered lights."""
    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs: list[AqualinkLight] = entry_data["platform_devices"][LIGHT_DOMAIN]

    async_add_entities(
        (AqualinkLightEntity(coordinator, dev) for dev in devs),
        True,
    )


class AqualinkLightEntity(AqualinkEntity, LightEntity):
    """Representation of Aqualink light."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator, dev: AqualinkLight) -> None:
        super().__init__(coordinator, dev)

        dev_name = getattr(dev, "name", "") or ""
        dev_data = getattr(dev, "data", {}) or {}
        dev_type = str(dev_data.get("type", "")).lower()

        # Strict: only AUX lights (aux_1 type=light) or real AqualinkLight devices
        if dev_name.startswith("aux_"):
            if dev_type != "light":
                # normalement ça n'arrive pas si ta classification est bonne
                raise ValueError(f"Not a light aux: {dev_name} type={dev_type}")

            # Friendly specific name
            if dev_name == "aux_1":
                self._attr_name = "Aux1-Light"
                # IMPORTANT: change unique_id to force a new entity
                self._attr_unique_id = f"{dev.system.serial}_aux1_light"
            else:
                # in case of other AUX light later on
                self._attr_name = f"{dev_name.replace('_', '').upper()}-Light"
                self._attr_unique_id = f"{dev.system.serial}_{dev_name}_light"
        else:
            # non-AUX lights
            self._attr_name = dev.label
            self._attr_unique_id = f"{dev.system.serial}_{dev.name}"

        # Optimistic UI state
        self._optimistic_state: bool | None = None

    def _raw_state(self) -> int:
        data = getattr(self.dev, "data", None)
        if isinstance(data, dict) and data.get("state") is not None:
            try:
                return int(data.get("state") or 0)
            except (TypeError, ValueError):
                return 0
        # fallback
        is_on_attr = getattr(self.dev, "is_on", None)
        try:
            return 1 if (is_on_attr() if callable(is_on_attr) else bool(is_on_attr)) else 0
        except Exception:
            return 0

    @property
    def is_on(self) -> bool:
        # optimistic state first
        if self._optimistic_state is not None:
            return self._optimistic_state
        return self._raw_state() != 0

    @property
    def brightness(self) -> int | None:
        """HA brightness is 0..255."""
        data = getattr(self.dev, "data", None)
        if isinstance(data, dict):
            b = data.get("brightness")
            if isinstance(b, (int, float)):
                if 0 <= b <= 100:
                    return int(b * 2.55)
                if 0 <= b <= 255:
                    return int(b)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # On conserve aussi tes attrs de base (coordinator timestamps, etc.)
        attrs = super().extra_state_attributes or {}

        data = getattr(self.dev, "data", None)
        if isinstance(data, dict):
            exo_color = data.get("color")
            exo_type = data.get("type")
            exo_mode = data.get("mode")

            # “color mode” (au sens Exo)
            # Ajuste si tu découvres d’autres valeurs que 0.
            if exo_color == 0:
                exo_color_mode = "standard_onoff"
            elif exo_color is None:
                exo_color_mode = None
            else:
                exo_color_mode = "rgb_or_programmable"

            attrs.update(
                {
                    "exo_type": exo_type,
                    "exo_mode": exo_mode,
                    "exo_color": exo_color,
                    "exo_color_mode": exo_color_mode,
                }
            )

        return attrs

    @refresh_system
    async def async_turn_on(self, **kwargs: Any) -> None:
        # optimistic UI
        self._optimistic_state = True

        if ATTR_BRIGHTNESS in kwargs and kwargs[ATTR_BRIGHTNESS] is not None:
            level_100 = max(1, min(100, int(kwargs[ATTR_BRIGHTNESS] / 2.55)))
            try:
                await self.dev.set_brightness(level_100)
            except (AqualinkOperationNotSupportedException, AttributeError):
                await self.dev.turn_on()
        else:
            await self.dev.turn_on()

    @refresh_system
    async def async_turn_off(self, **kwargs: Any) -> None:
        # optimistic UI
        self._optimistic_state = False
        await self.dev.turn_off()

    def _handle_coordinator_update(self) -> None:
        # Real API data has arrived -> clear optimistic override
        self._optimistic_state = None
        super()._handle_coordinator_update()
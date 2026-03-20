"""Support for Aqualink sensors."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AqualinkEntity
from .const import (
    DOMAIN as AQUALINK_DOMAIN,
    ENTITY_DIAG_SENSOR_NAMES,
    ENTITY_ICONS,
    ENTITY_SYSTEM_SENSOR_NAMES,
)
from .device import AqualinkSensor
from .timer_helpers import (
    get_timer_entity_name,
    get_timer_group_from_endpoint,
    get_timer_object_id,
    get_timer_role_from_endpoint,
    get_timer_unique_id,
)

PARALLEL_UPDATES = 0
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Aqualink sensors."""
    _LOGGER.debug("iAQUALINK_eXO-IQ - sensor.py async_setup_entry CALLED")

    entry_data = hass.data[AQUALINK_DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    devs = entry_data["platform_devices"][SENSOR_DOMAIN]

    _LOGGER.debug(
        "iAQUALINK_eXO-IQ - sensor.py devs count=%s timer_devs=%s",
        len(devs),
        [
            getattr(d, "name", "")
            for d in devs
            if getattr(d, "name", "").startswith("schedule_")
        ][:20],
    )

    entities = []
    for dev in devs:
        try:
            entities.append(AqualinkSensorEntity(coordinator, dev))
        except Exception:
            _LOGGER.exception(
                "iAQUALINK_eXO-IQ - sensor.py FAILED to create entity for dev=%s class=%s data=%s",
                getattr(dev, "name", None),
                dev.__class__.__name__,
                getattr(dev, "data", None),
            )

    _LOGGER.debug(
        "iAQUALINK_eXO-IQ - sensor.py about to async_add_entities count=%s",
        len(entities),
    )
    async_add_entities(entities, True)
    _LOGGER.debug("IAQUALINK sensor.py async_add_entities DONE")


class AqualinkSensorEntity(AqualinkEntity, SensorEntity):
    """Representation of a sensor."""

    def __init__(self, coordinator, dev: AqualinkSensor) -> None:
        super().__init__(coordinator, dev)

        dev_name = getattr(dev, "name", "") or ""
        dev_label = getattr(dev, "label", None)

        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - sensor entity init dev=%s label=%s",
            dev_name,
            dev_label,
        )

        try:
            default_name = dev_label if isinstance(dev_label, str) else dev_name
        except Exception:
            default_name = dev_name

        self._attr_name = default_name
        self._attr_unique_id = f"{dev.system.serial}_{dev_name}"

        # --- Timer-based naming for grouped timer sensors ---
        if dev_name.startswith("schedule_"):
            endpoint = (getattr(dev, "data", {}) or {}).get("endpoint")
            group = get_timer_group_from_endpoint(endpoint)

            if group is not None:
                group_id = group[0]
                kind = "speed" if dev_name.endswith("_rpm") else "sensor"

                self._attr_name = get_timer_entity_name(endpoint, kind)
                self._attr_unique_id = get_timer_unique_id(
                    dev.system.serial,
                    "sensor",
                    group_id,
                    endpoint,
                    kind,
                )
                self._attr_suggested_object_id = get_timer_object_id(
                    group_id,
                    endpoint,
                    kind,
                )

        # --- Friendly name for system sensor entities ---
        if dev_name in ENTITY_SYSTEM_SENSOR_NAMES:
            self._attr_name = ENTITY_SYSTEM_SENSOR_NAMES[dev_name]

        # --- Friendly name and category for diagnostic sensor entities ---
        if dev_name in ENTITY_DIAG_SENSOR_NAMES:
            self._attr_name = ENTITY_DIAG_SENSOR_NAMES[dev_name]
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # --- Icon for all sensor entities ---
        if dev_name in ENTITY_ICONS:
            self._attr_icon = ENTITY_ICONS[dev_name]

        # --- Class for timestamp / last refresh ---
        if dev_name in ("cloud_timestamp", "cloud_status", "last_refresh"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

        # --- Class for temperature ---
        if dev_name.endswith("_temp"):
            self._attr_device_class = SensorDeviceClass.TEMPERATURE

        # Cache value for refresh freezing when Production == 0
        self._last_good_value = None
        self._is_frozen = False

    def _production_is_off(self) -> bool:
        """True if production == 0. If unknown -> False."""
        try:
            prod_dev = self.dev.system.devices.get("production")
            if not prod_dev:
                return False

            prod_state = getattr(prod_dev, "state", None)
            if prod_state is None and hasattr(prod_dev, "data"):
                prod_state = prod_dev.data.get("state")

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
        dev_name = getattr(self.dev, "name", "") or ""

        if dev_name.endswith("_temp"):
            return (
                UnitOfTemperature.FAHRENHEIT
                if self.dev.system.temp_unit == "F"
                else UnitOfTemperature.CELSIUS
            )

        if dev_name in ("swc", "swc_low"):
            return "%"

        if dev_name in ("orp", "orp_sp"):
            return "mV"

        if dev_name.endswith("_rpm"):
            return "rpm"

        if dev_name == "rssi":
            return "dBm"

        return None

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes or {}
        dev_name = getattr(self.dev, "name", "") or ""

        # --- Frozen sensors ---
        if dev_name in {"ph", "orp", "water_temp", "sns_1", "sns_2", "sns_3"}:
            attrs["frozen"] = getattr(self, "_is_frozen", False)

        # --- Main timer sensor ---
        if (
            dev_name.startswith("schedule_")
            and not dev_name.endswith(("_rpm", "_enabled", "_active"))
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
        dev_name = getattr(self.dev, "name", "") or ""
        raw = self.dev.state
        if raw in ("", None):
            return None

        freeze_targets = {"ph", "orp", "water_temp", "sns_1", "sns_2", "sns_3"}
        is_freeze_target = dev_name in freeze_targets
        should_freeze = is_freeze_target and (
            self._production_is_off() or not self.available
        )

        val = None

        # --- Timer speed sensor (must be numeric) ---
        if dev_name.endswith("_rpm"):
            try:
                val = int(raw)
            except (TypeError, ValueError):
                val = None

        # --- Main timer sensor (readable time range) ---
        elif dev_name.startswith("schedule_"):
            start = self.dev.data.get("start")
            end = self.dev.data.get("end")
            val = f"{start} → {end}" if start and end else None

        # --- pH: API returns 72 -> 7.2 ---
        elif dev_name in ("ph", "ph_sp"):
            try:
                val = float(raw) / 10
            except (TypeError, ValueError):
                val = None

        # --- Cloud timestamp ---
        elif dev_name == "cloud_timestamp":
            try:
                return datetime.fromtimestamp(int(raw) / 1000, timezone.utc)
            except (TypeError, ValueError):
                return None

        # --- Last refresh ---
        elif dev_name == "last_refresh":
            try:
                return datetime.fromtimestamp(int(raw), timezone.utc)
            except (TypeError, ValueError):
                return None

        # --- Default: int / float / string ---
        else:
            try:
                val = int(raw)
            except (TypeError, ValueError):
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    val = raw

        # --- Freeze logic ---
        if should_freeze:
            if not self._is_frozen:
                _LOGGER.debug(
                    "iAQUALINK_eXO-IQ - Freezing %s (production=0) last=%s",
                    dev_name,
                    self._last_good_value,
                )

            self._is_frozen = True

            if self._last_good_value is None and val is not None:
                self._last_good_value = val

            return self._last_good_value

        # --- Normal mode ---
        if self._is_frozen:
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - Unfreezing %s (production resumed)",
                dev_name,
            )

        self._is_frozen = False

        if is_freeze_target and val is not None:
            self._last_good_value = val

        return val
"""Aqualink ExoIQ Fork Integration"""

import logging
import httpx
import asyncio
from datetime import timezone
from functools import wraps

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD

from .const import DOMAIN, UPDATE_INTERVAL, KEEPALIVE_EXPIRY, MANUFACTURER
from .client import AqualinkClient

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [SWITCH_DOMAIN, SENSOR_DOMAIN, CLIMATE_DOMAIN, LIGHT_DOMAIN, BINARY_SENSOR_DOMAIN]
PARALLEL_UPDATES = 0

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the iAqualink component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("IAQUALINK_EXOIQ - async_setup_entry START entry_id=%s", entry.entry_id)
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    hass.data.setdefault(DOMAIN, {})

    httpx_client = httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(keepalive_expiry=KEEPALIVE_EXPIRY),
    )

    client = AqualinkClient(username, password, httpx_client)

    try:
        await client.login()
        systems = list((await client.get_systems()).values())
        if not systems:
            raise ConfigEntryNotReady("No systems returned by API")
        
        system = systems[0]
        # ---- Bootstrap update: must have devices at least once to create entities ----
        max_bootstrap_tries = 6
        base_sleep = 5
        last_err = None
        devices = getattr(system, "devices", None) or {}
        
        for attempt in range(1, max_bootstrap_tries + 1):
            try:
                await system.update(force=True)
                devices = getattr(system, "devices", None) or {}
                if devices:
                    break
            except Exception as e:
                last_err = e
        
            sleep_s = min(base_sleep * (2 ** (attempt - 1)), 30)  # 5,10,20,30,30,30
            _LOGGER.warning(
                "IAQUALINK_EXOIQ - Bootstrap update: no devices (attempt %s/%s) -> sleep %ss",
                attempt, max_bootstrap_tries, sleep_s
            )
            await asyncio.sleep(sleep_s)
        
        if not devices:
            raise ConfigEntryNotReady(
                f"No devices returned after bootstrap tries (last_err={last_err!r})"
            )
        
        # Debug uniquement après bootstrap OK
        schedule_keys = [k for k in devices.keys() if k.startswith("schedule_")]
        _LOGGER.debug(
            "IAQUALINK_EXOIQ - got devices count=%s schedule_count=%s schedule_keys_sample=%s keys_sample=%s",
            len(devices),
            len(schedule_keys),
            schedule_keys[:10],
            list(devices.keys())[:10],
        )
        
        schedule_keys = [k for k in devices.keys() if k.startswith("schedule_")]
        system.online = True


        platform_devices = {
            SWITCH_DOMAIN: [],
            SENSOR_DOMAIN: [],
            CLIMATE_DOMAIN: [],
            LIGHT_DOMAIN: [],
            BINARY_SENSOR_DOMAIN: [],
        }
        
        _LOGGER.debug(
            "IAQUALINK_EXOIQ - DEVICES AUX: %s",
            [(d.name, getattr(d, "data", {}).get("type")) for d in devices.values() if getattr(d, "name", "").startswith("aux_")]
        )
        
        # ---- Classification loop (robust) ----
        for dev in devices.values():
            cls = dev.__class__.__name__
            dev_name = getattr(dev, "name", "") or ""
            data = getattr(dev, "data", None)
            dev_type = data.get("type") if isinstance(data, dict) else None
            
            # --- SCHEDULE ---
            if dev_name.startswith("schedule_") and dev_name.endswith(("_enabled", "_active")):
                platform_devices[BINARY_SENSOR_DOMAIN].append(dev)      #SCHEDULE Binary sensors 
            elif dev_name.startswith("schedule_") and dev_name.endswith("_rpm"):
                platform_devices[SENSOR_DOMAIN].append(dev)             #SCHEDULE RPM
            elif dev_name.startswith("schedule_"):
                platform_devices[SENSOR_DOMAIN].append(dev)             #SCHEDULE main
            
            # --- AUX ---
            elif dev_name.startswith("aux_"):
                data = getattr(dev, "data", None)
                if not isinstance(data, dict):
                    continue
            
                dev_type = str(data.get("type", "")).lower()
            
                if dev_type == "light":
                    platform_devices[LIGHT_DOMAIN].append(dev)
                elif dev_type == "heat":
                    platform_devices[CLIMATE_DOMAIN].append(dev)
            
                # strict: if no type then ignore (ex: aux230 without type)
                continue
        
            # --- SWITCH ---
            elif cls in ("AqualinkToggle", "ExoAttributeSwitch"):
                platform_devices[SWITCH_DOMAIN].append(dev)
        
            # --- CLIMATE ---
            elif cls in ("AqualinkThermostat", "ExoThermostat", "ExoHeating"):
                platform_devices[CLIMATE_DOMAIN].append(dev)
        
            # --- LIGHT ---
            elif cls == "AqualinkLight":
                platform_devices[LIGHT_DOMAIN].append(dev)
        
            # --- BINARY SENSOR ---
            elif cls == "AqualinkBinarySensor":
                platform_devices[BINARY_SENSOR_DOMAIN].append(dev)
            
            #---PUMP & MQTT Special Case
            elif dev_name in ("filter_pump", "exo_state", "exo_mqtt_status", "exo_mqtt_connection"):
                platform_devices[BINARY_SENSOR_DOMAIN].append(dev)
        
            # --- SENSOR ---
            elif cls in ("AqualinkSensor", "ExoSensor", "ExoAttributeSensor"):
                platform_devices[SENSOR_DOMAIN].append(dev)
        
            # --- FALLBACK ---
            else:
                platform_devices[SENSOR_DOMAIN].append(dev)
        
        _LOGGER.debug(
            "IAQUALINK_EXOIQ - platform_devices: switches=%s sensors=%s climates=%s lights=%s binary=%s",
            len(platform_devices[SWITCH_DOMAIN]),
            len(platform_devices[SENSOR_DOMAIN]),
            len(platform_devices[CLIMATE_DOMAIN]),
            len(platform_devices[LIGHT_DOMAIN]),
            len(platform_devices[BINARY_SENSOR_DOMAIN]),
        )

        sched_in_sensors = [d.name for d in platform_devices[SENSOR_DOMAIN] if d.name.startswith("schedule_")]
        _LOGGER.debug("IAQUALINK_EXOIQ - SCHEDULES classified as SENSOR = %s", sched_in_sensors)

    except Exception as e:
        await httpx_client.aclose()
        raise ConfigEntryNotReady from e

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "system": system,
        "httpx_client": httpx_client,
        "platform_devices": platform_devices,
    }

    async def async_update():
        #_LOGGER.debug("IAQUALINK_EXOIQ - COORD UPDATE: online=%s last_refresh=%s", system.online, getattr(system, "last_refresh", None))
        #_LOGGER.debug("IAQUALINK_EXOIQ - COORD tick")
        await system.update()
        return {"online": getattr(system, "online", None), "ts": getattr(system, "last_refresh", None)}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update,
        update_interval=UPDATE_INTERVAL,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as e:
        _LOGGER.warning("IAQUALINK_EXOIQ - First refresh failed (will retry later): %s", e)
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data and "httpx_client" in data:
        await data["httpx_client"].aclose()

    return unload_ok


def refresh_system(func):
    """Force update all entities after state change."""
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        await func(self, *args, **kwargs)

        # 1) UI optimistic: The button stay Yellow
        self.async_write_ha_state()

        # 2) After 30s, we repoll the API (by bypassing MIN_SECS_TO_REFRESH)
        await asyncio.sleep(UPDATE_INTERVAL.total_seconds())
        await self.dev.system.update(force=True)

        # 3) Push the update to all entities without launching update_method (important)
        self.coordinator.async_set_updated_data(
            {"online": getattr(self.dev.system, "online", None), "ts": getattr(self.dev.system, "last_refresh", None)}
        )

    return wrapper

class AqualinkEntity(CoordinatorEntity):
    """Base class for all Aqualink platforms (coordinator-backed)."""

    def __init__(self, coordinator, dev) -> None:
        super().__init__(coordinator)
        self.dev = dev
        self._prod_dev = None
        self._last_state = object()
        self._last_attrs = object()
        self._last_available = object()

    def _handle_coordinator_update(self) -> None:
        #_LOGGER.debug("IAQUALINK_EXOIQ - ENTITY UPDATE: %s", self.entity_id)
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        online = getattr(self.dev.system, "online", None)
        # None = "unknown" => no display if unavailable
        return online is not False

    @property
    def extra_state_attributes(self):
        attrs = {}
    
        # 1) timestamp HA : last successful refresh of the coordinator
        dt = getattr(self.coordinator, "last_update_success_time", None)
        if dt:
            attrs["coordinator_last_update"] = dt.astimezone(timezone.utc).isoformat()
    
        # 2) timestamp "integration" : the last_refresh (epoch seconds)
        ts = getattr(self.dev.system, "last_refresh", None)
        if ts:
            attrs["api_last_refresh_epoch"] = int(ts)
    
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        dev_name = getattr(self.dev, "name", "") or ""
        serial = getattr(self.dev.system, "serial", None) or "unknown"
        sys_name = getattr(self.dev.system, "name", None) or f"ExoIQ {serial}"

        # ---- SCHEDULES: child device ----
        if dev_name.startswith("schedule_"):
            schedule_id = (
                self.dev.data.get("schedule_id")
                or self.dev.data.get("schedule_key")
                or dev_name
            )
            schedule_name = self.dev.data.get("schedule_name") or self.dev.label

            return DeviceInfo(
                identifiers={(DOMAIN, f"{serial}_{schedule_id}")},
                name=f"Schedule {schedule_name}",
                manufacturer=MANUFACTURER,
                model="Exo Schedule",
                via_device=(DOMAIN, serial),   # parent
            )
        
        # ---- Exo system: child device ----
         exo_system_names = {
            "sn",
            "vr",
            "version",
            "error_state",
            "error_code",
            "exo_rssi",
            "exo_fw_version",
            "exo_cloud_timestamp",
            "exo_mqtt_status",
        }

        if dev_name in exo_system_names:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{serial}_exo_system")},
                name="Exo System",
                manufacturer=MANUFACTURER,
                model="ExoIQ Diagnostics",
                via_device=(DOMAIN, serial),
            )

        # ---- ALL OTHER ENTITIES: Parent device ----
        return DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=sys_name,
            manufacturer=MANUFACTURER,
            model=self.dev.system.__class__.__name__,
        )

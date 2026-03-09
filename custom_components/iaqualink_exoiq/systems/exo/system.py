from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ...const import MIN_SECS_TO_REFRESH
from ...exception import (
    AqualinkServiceException,
    AqualinkServiceUnauthorizedException,
    AqualinkSystemOfflineException,
)
from ...system import AqualinkSystem
from .device import ExoDevice

if TYPE_CHECKING:
    import httpx

    from ...client import AqualinkClient
    from ...typing import Payload

EXO_DEVICES_URL = "https://prod.zodiac-io.com/devices/v1"

_LOGGER = logging.getLogger(__name__)

class ExoSystem(AqualinkSystem):
    NAME = "exo"

    def __init__(self, aqualink: AqualinkClient, data: Payload):
        super().__init__(aqualink, data)
        # This lives in the parent class but mypy complains.
        self.last_refresh: int = 0
        self.temp_unit = "C"  # TODO: check if unit can be changed on panel?
        #self.raw_shadow: dict[str, Any] = {}
        self.raw_shadow = data
        
    def __repr__(self) -> str:
        attrs = ["name", "serial", "data"]
        attrs = [f"{i}={getattr(self, i)!r}" for i in attrs]
        return f"{self.__class__.__name__}({' '.join(attrs)})"

    async def send_devices_request(self, **kwargs: Any) -> httpx.Response:
        url = f"{EXO_DEVICES_URL}/{self.serial}/shadow"
        headers = {"Authorization": self.aqualink.id_token}

        try:
            r = await self.aqualink.send_request(url, headers=headers, **kwargs)
        except AqualinkServiceUnauthorizedException:
            # token expired so refresh the token and try again
            await self.aqualink.login()
            headers = {"Authorization": self.aqualink.id_token}
            r = await self.aqualink.send_request(url, headers=headers, **kwargs)

        return r

    async def send_reported_state_request(self) -> httpx.Response:
        return await self.send_devices_request()

    async def send_desired_state_request(
        self, state: dict[str, Any]
    ) -> httpx.Response:
        return await self.send_devices_request(
            method="post", json={"state": {"desired": state}}
        )
    
    async def get_shadow(self) -> httpx.Response:
        """Fetch AWS IoT shadow (reported state)."""
        return await self.send_reported_state_request()
    
    
    async def update(self, force: bool = False) -> None:
        _LOGGER.debug("IAQUALINK_EXOIQ - EXO UPDATE CALLED force=%s", force)
    
        if not force and (int(time.time()) - self.last_refresh) < MIN_SECS_TO_REFRESH:
            _LOGGER.debug(
                "IAQUALINK_EXOIQ - Only %ss since last refresh.",
                int(time.time()) - self.last_refresh,
            )
            return
    
        try:
            resp = await self.send_reported_state_request()
    
            self._parse_shadow_response(resp)
    
            self.online = True
            self.last_refresh = int(time.time())
    
        except Exception as e:
            # Important: nothing is deleted, we keep the existing devices
            self.online = False
            _LOGGER.exception("IAQUALINK_EXOIQ - EXO update failed: %s", e)
            
            return

    def _parse_shadow_response(self, response: httpx.Response) -> None:
        data = response.json()
        self.raw_shadow = data 

        _LOGGER.debug("IAQUALINK_EXOIQ - RAW EXO JSON: %s", data)
        _LOGGER.debug("IAQUALINK_EXOIQ - PARSE SHADOW EXO system.py LOADED FROM: %s", __file__)
    
        devices: dict[str, dict] = {}
    
        # --- Equipment (swc_0) ---
        root = data["state"]["reported"]["equipment"]["swc_0"]
        for name, state in root.items():
            attrs = {"name": name}
        
            if isinstance(state, dict):
                attrs.update(state)
            else:
                attrs["state"] = state
        
            devices[name] = attrs
    
        # --- Heating ---
        if "heating" in data["state"]["reported"]:
            name = "heating"
            attrs = {"name": name}
            attrs.update(data["state"]["reported"]["heating"])
            attrs["state"] = 1 if attrs.get("enabled", 0) == 1 else 0
            devices[name] = attrs
    
            name = "heater"
            devices[name] = {
                "name": name,
                "state": data["state"]["reported"]["heating"]["state"],
            }

        # --- Diagnostic / Health data ---
        reported = data.get("state", {}).get("reported", {}) or {}
        debug = reported.get("debug", {}) or {}
        aws = reported.get("aws", {}) or {}

        # Root firmware / cloud status
        if "vr" in reported:
            devices["exo_fw_version"] = {
                "name": "exo_fw_version",
                "state": reported.get("vr"),
            }

        if "status" in aws:
            devices["exo_mqtt_status"] = {
                "name": "exo_mqtt_status",
                "state": 1 if aws.get("status") == "connected" else 0,
                "status": aws.get("status"),
            }

        if "timestamp" in aws:
            devices["exo_cloud_timestamp"] = {
                "name": "exo_cloud_timestamp",
                "state": aws.get("timestamp"),
            }

        # Debug values
        if "RSSI" in debug:
            devices["exo_rssi"] = {
                "name": "exo_rssi",
                "state": debug.get("RSSI"),
            }

        if "MQTT connection" in debug:
            devices["exo_mqtt_connection"] = {
                "name": "exo_mqtt_connection",
                "state": int(debug.get("MQTT connection") or 0),
            }

        # --- Schedules (timers) ---
        schedules = data["state"]["reported"].get("schedules", {}) or {}
        #_LOGGER.debug(
        #    "IAQUALINK_EXOIQ - ### schedules keys=%s",
        #    list(schedules.keys()),
        #)
    
        for key, sch in schedules.items():
            if not isinstance(sch, dict):
                continue
            if key in ("supported", "programmed"):
                continue
    
            name_prefix = f"schedule_{key}"     # schedule_sch5
            schedule_id = sch.get("id")         # sch_5
            schedule_name = sch.get("name")     # "Filter Pump 1"
            endpoint = sch.get("endpoint")      # "vsp_1"
            timer = sch.get("timer") or {}
            start = timer.get("start")
            end = timer.get("end")
    
            # 1) Main schedule sensor (start/end)
            devices[name_prefix] = {
                "name": name_prefix,
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "endpoint": endpoint,
                "start": start,
                "end": end,
                "state": int(sch.get("enabled", 0) or 0),
            }
    
            # 2) RPM sensor (if exists)
            if "rpm" in sch:
                devices[f"{name_prefix}_rpm"] = {
                    "name": f"{name_prefix}_rpm",
                    "schedule_id": schedule_id,
                    "schedule_name": schedule_name,
                    "endpoint": endpoint,
                    "state": int(sch.get("rpm") or 0),
                }
    
            # 3) Enabled binary_sensor
            devices[f"{name_prefix}_enabled"] = {
                "name": f"{name_prefix}_enabled",
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "endpoint": endpoint,
                "state": int(sch.get("enabled", 0) or 0),
            }
    
            # 4) Active binary_sensor
            devices[f"{name_prefix}_active"] = {
                "name": f"{name_prefix}_active",
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "endpoint": endpoint,
                "state": int(sch.get("active", 0) or 0),
            }

        # ---- APPLY devices dict into self.devices (IMPORTANT) ----
        for k, v in devices.items():
            if k in self.devices:
                for dk, dv in v.items():
                    self.devices[k].data[dk] = dv
            else:
                self.devices[k] = ExoDevice.from_data(self, v)
        
        _LOGGER.info(
            "EXO refresh OK: devices=%s (schedules=%s) online=%s",
            len(self.devices),
            len([k for k in self.devices if k.startswith("schedule_")]),
            self.online,
        )
    
    async def set_heating(self, name: str, state: int) -> None:
        r = await self.send_desired_state_request({"heating": {name: state}})
        r.raise_for_status()

    async def set_aux(self, aux: str, state: int) -> None:
        r = await self.send_desired_state_request(
            {"equipment": {"swc_0": {aux: {"state": state}}}}
        )
        r.raise_for_status()

    async def set_toggle(self, name: str, state: int) -> None:
        _LOGGER.debug("IAQUALINK_EXOIQ - ### HIT ExoSystem.set_toggle name=%s state=%s ###", name, state)
        try:
            _LOGGER.debug("IAQUALINK_EXOIQ - TEST set_toggle ENTER name=%s state=%s", name, state)
    
            snap = self.devices.get(name).data if name in self.devices else {}
            if isinstance(snap, dict) and ("type" in snap):
                payload = {"equipment": {"swc_0": {name: {"state": state, "type": snap.get("type")}}}}
            else:
                payload = {"equipment": {"swc_0": {name: state}}}
    
            _LOGGER.debug("IAQUALINK_EXOIQ - TEST set_toggle payload=%s", payload)
            r = await self.send_desired_state_request(payload)
            _LOGGER.debug("IAQUALINK_EXOIQ - TEST set_toggle HTTP status=%s body=%s", r.status_code, r.text)
            r.raise_for_status()
    
        except Exception:
            _LOGGER.debug("IAQUALINK_EXOIQ - TEST set_toggle FAILED name=%s state=%s", name, state)
            raise

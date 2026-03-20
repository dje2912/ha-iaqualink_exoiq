from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from ...const import MIN_SECS_TO_REFRESH
from ...exception import (
    AqualinkServiceException,
    AqualinkServiceUnauthorizedException,
)
from ...system import AqualinkSystem
from ...timer_helpers import get_timer_group_id_from_endpoint
from .device import ExoDevice

if TYPE_CHECKING:
    import httpx

    from ...client import AqualinkClient
    from ...typing import Payload

EXO_DEVICES_URL = "https://prod.zodiac-io.com/devices/v1"

_LOGGER = logging.getLogger(__name__)


class ExoSystem(AqualinkSystem):
    NAME = "exo"

    # -------------------------------------------------------------------------
    # System lifecycle and local state
    # -------------------------------------------------------------------------
    def __init__(self, aqualink: AqualinkClient, data: Payload):
        super().__init__(aqualink, data)
        self.last_refresh: int = 0
        self.temp_unit = "C"  # TODO: check if unit can be changed on panel?
        self.raw_shadow: dict[str, Any] = data if isinstance(data, dict) else {}

        # Kept for compatibility during migration to timer-based naming.
        self.pending_schedule_groups: dict[str, dict[str, dict[str, Any]]] = {}
        self._schedule_refresh_block_until: float = 0

    def __repr__(self) -> str:
        attrs = ["name", "serial", "data"]
        attrs = [f"{i}={getattr(self, i)!r}" for i in attrs]
        return f"{self.__class__.__name__}({' '.join(attrs)})"

    # -------------------------------------------------------------------------
    # Poll skip logic for timer editing / cooldown
    # -------------------------------------------------------------------------
    def should_skip_poll_for_timer_edit(self) -> bool:
        """Return True if polling should be skipped during timer edit/save window."""
        now = time.time()

        if self.pending_schedule_groups:
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - Skip coordinator poll: pending timer edits exist (%s)",
                list(self.pending_schedule_groups.keys()),
            )
            return True

        if now < self._schedule_refresh_block_until:
            remaining = int(self._schedule_refresh_block_until - now)
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - Skip coordinator poll: timer cooldown active (%ss remaining)",
                remaining,
            )
            return True

        return False

    # Backward-compatible alias
    def should_skip_poll_for_schedule_edit(self) -> bool:
        """Backward-compatible alias for timer-based poll skip logic."""
        return self.should_skip_poll_for_timer_edit()

    # -------------------------------------------------------------------------
    # Raw shadow helpers and write guards
    # -------------------------------------------------------------------------
    def _reported_root(self) -> dict[str, Any]:
        """Return reported root from last known shadow."""
        return (self.raw_shadow.get("state", {}) or {}).get("reported", {}) or {}

    def _aws_status(self) -> str | None:
        """Return AWS reported connection status."""
        aws = self._reported_root().get("aws", {}) or {}
        status = aws.get("status")
        return str(status).lower() if status is not None else None

    def _mqtt_connection_value(self) -> int | None:
        """Return debug MQTT connection value if available."""
        debug = self._reported_root().get("debug", {}) or {}
        value = debug.get("MQTT connection")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def can_send_commands(self) -> tuple[bool, str]:
        """Tell whether the system is in a state suitable for writes."""
        aws_status = self._aws_status()
        mqtt_connection = self._mqtt_connection_value()

        if aws_status not in ("connected",):
            return False, f"AWS status is {aws_status!r}"

        if mqtt_connection is not None and mqtt_connection < 1:
            return False, f"MQTT connection is {mqtt_connection!r}"

        return True, "ok"

    def _ensure_can_send_commands(self, operation: str) -> None:
        """Raise if the Exo cloud/device status is not suitable for writes."""
        ok, reason = self.can_send_commands()
        if ok:
            return

        _LOGGER.warning(
            "iAQUALINK_eXO-IQ - Block command %s: device not ready for writes (%s)",
            operation,
            reason,
        )
        raise AqualinkServiceException(
            f"Cannot send command '{operation}': device not ready for writes ({reason})"
        )

    # -------------------------------------------------------------------------
    # HTTP requests to AWS IoT shadow
    # -------------------------------------------------------------------------
    async def send_devices_request(self, **kwargs: Any) -> httpx.Response:
        url = f"{EXO_DEVICES_URL}/{self.serial}/shadow"
        headers = {"Authorization": self.aqualink.id_token}

        try:
            response = await self.aqualink.send_request(url, headers=headers, **kwargs)
        except AqualinkServiceUnauthorizedException:
            await self.aqualink.login()
            headers = {"Authorization": self.aqualink.id_token}
            response = await self.aqualink.send_request(url, headers=headers, **kwargs)

        return response

    async def send_reported_state_request(self) -> httpx.Response:
        """Fetch reported shadow state."""
        return await self.send_devices_request()

    async def send_desired_state_request(self, state: dict[str, Any]) -> httpx.Response:
        """Send desired shadow state."""
        self._ensure_can_send_commands("send_desired_state_request")
        return await self.send_devices_request(
            method="post",
            json={"state": {"desired": state}},
        )

    async def get_shadow(self) -> httpx.Response:
        """Fetch AWS IoT shadow."""
        return await self.send_reported_state_request()

    # -------------------------------------------------------------------------
    # Periodic refresh and shadow parsing
    # -------------------------------------------------------------------------
    async def update(self, force: bool = False) -> None:
        _LOGGER.debug("iAQUALINK_eXO-IQ - EXO UPDATE CALLED force=%s", force)

        if not force and (int(time.time()) - self.last_refresh) < MIN_SECS_TO_REFRESH:
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - Only %ss since last refresh.",
                int(time.time()) - self.last_refresh,
            )
            return

        try:
            response = await self.send_reported_state_request()
            self._parse_shadow_response(response)
            self.online = True
            self.last_refresh = int(time.time())
        except Exception as err:
            self.online = False
            _LOGGER.exception("iAQUALINK_eXO-IQ - EXO update failed: %s", err)

    def _should_expose_timer_endpoint(self, endpoint: str | None) -> bool:
        """Return whether a timer endpoint should be exposed in Home Assistant based on the type."""
        endpoint = (endpoint or "").lower()

        # Non-AUX timer endpoints are always exposed.
        if not endpoint.startswith("aux"):
            return True

        suffix = endpoint.removeprefix("aux")
        if not suffix.isdigit():
            return True

        aux_key = f"aux_{suffix}"

        equipment = self._reported_root().get("equipment", {}).get("swc_0", {}) or {}
        aux_data = equipment.get(aux_key, {}) or {}
        aux_type = str(aux_data.get("type", "")).lower()

        # Do not expose AUX timers configured as heating.
        if aux_type == "heat":
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - Skip timer creation for %s: %s.type=%s",
                endpoint,
                aux_key,
                aux_type,
            )
            return False

        return True
    
    def _parse_shadow_response(self, response: httpx.Response, *, source: str = "remote") -> None:
        data = response.json()
        self.raw_shadow = data if isinstance(data, dict) else {}

        _LOGGER.debug("iAQUALINK_eXO-IQ - RAW EXO JSON (%s): %s", source, data)
        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - PARSE SHADOW EXO system.py LOADED FROM: %s (%s)",
            __file__,
            source,
        )

        devices: dict[str, dict[str, Any]] = {}

        reported = data.get("state", {}).get("reported", {}) or {}
        equipment = reported.get("equipment", {}).get("swc_0", {}) or {}
        heating = reported.get("heating", {}) or {}
        schedules = reported.get("schedules", {}) or {}
        debug = reported.get("debug", {}) or {}
        aws = reported.get("aws", {}) or {}

        # --- Last refresh synthetic device ---
        devices["last_refresh"] = {
            "name": "last_refresh",
            "state": int(self.last_refresh),
        }

        # --- Main equipment devices from swc_0 ---
        for name, state in equipment.items():
            attrs: dict[str, Any] = {"name": name}

            if isinstance(state, dict):
                attrs.update(state)
            else:
                attrs["state"] = state

            devices[name] = attrs

        # --- Heating device block ---
        if heating:
            attrs = {"name": "heating"}
            attrs.update(heating)
            attrs["state"] = 1 if attrs.get("enabled", 0) == 1 else 0
            devices["heating"] = attrs

        # --- Diagnostic / health devices ---
        if "vr" in reported:
            devices["fw_version"] = {
                "name": "fw_version",
                "state": reported.get("vr"),
            }

        if "timestamp" in aws:
            devices["cloud_timestamp"] = {
                "name": "cloud_timestamp",
                "state": aws.get("timestamp"),
            }

        if "status" in aws:
            devices["cloud_status"] = {
                "name": "cloud_status",
                "state": aws.get("status"),
            }

        if "RSSI" in debug:
            devices["rssi"] = {
                "name": "rssi",
                "state": debug.get("RSSI"),
            }

        if "MQTT connection" in debug:
            devices["mqtt_connection"] = {
                "name": "mqtt_connection",
                "state": debug.get("MQTT connection"),
            }

        # --- Schedule devices derived from shadow schedules ---
        # The backend still uses "schedules", so this part keeps schedule naming.
        for key, sch in schedules.items():
            if not isinstance(sch, dict):
                continue
            if key in ("supported", "programmed"):
                continue

            endpoint = sch.get("endpoint")
            if not self._should_expose_timer_endpoint(endpoint):
                continue

            name_prefix = f"schedule_{key}"
            schedule_id = sch.get("id")
            schedule_name = sch.get("name")
            endpoint = sch.get("endpoint")
            timer = sch.get("timer") or {}
            start = timer.get("start")
            end = timer.get("end")

            devices[name_prefix] = {
                "name": name_prefix,
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "endpoint": endpoint,
                "start": start,
                "end": end,
                "state": int(sch.get("enabled", 0) or 0),
            }

            if "rpm" in sch:
                devices[f"{name_prefix}_rpm"] = {
                    "name": f"{name_prefix}_rpm",
                    "schedule_id": schedule_id,
                    "schedule_name": schedule_name,
                    "endpoint": endpoint,
                    "state": int(sch.get("rpm") or 0),
                }

            devices[f"{name_prefix}_enabled"] = {
                "name": f"{name_prefix}_enabled",
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "endpoint": endpoint,
                "state": int(sch.get("enabled", 0) or 0),
            }

            devices[f"{name_prefix}_active"] = {
                "name": f"{name_prefix}_active",
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "endpoint": endpoint,
                "state": int(sch.get("active", 0) or 0),
            }

        # --- Remove stale schedule-derived devices no longer present in shadow ---
        stale_schedule_keys = [
            key
            for key in self.devices
            if key.startswith("schedule_") and key not in devices
        ]

        for key in stale_schedule_keys:
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - Removing stale timer device/entity source: %s",
                key,
            )
            self.devices.pop(key, None)

        # --- Apply parsed devices into self.devices ---
        for key, value in devices.items():
            if key in self.devices:
                for dev_key, dev_value in value.items():
                    self.devices[key].data[dev_key] = dev_value
            else:
                self.devices[key] = ExoDevice.from_data(self, value)

        _LOGGER.info(
            "EXO refresh OK: devices=%s (schedules=%s) online=%s",
            len(self.devices),
            len([k for k in self.devices if k.startswith("schedule_")]),
            self.online,
        )

    # -------------------------------------------------------------------------
    # Direct command helpers for non-timer features
    # -------------------------------------------------------------------------
    async def set_heating(self, name: str, state: int) -> None:
        response = await self.send_desired_state_request({"heating": {name: state}})
        response.raise_for_status()

    async def set_aux(self, aux: str, state: int) -> None:
        response = await self.send_desired_state_request(
            {"equipment": {"swc_0": {aux: {"state": state}}}}
        )
        response.raise_for_status()

    async def set_toggle(self, name: str, state: int) -> None:
        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - ### HIT ExoSystem.set_toggle name=%s state=%s ###",
            name,
            state,
        )

        try:
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - TEST set_toggle ENTER name=%s state=%s",
                name,
                state,
            )

            snap = self.devices.get(name).data if name in self.devices else {}
            if isinstance(snap, dict) and "type" in snap:
                payload = {
                    "equipment": {
                        "swc_0": {
                            name: {"state": state, "type": snap.get("type")}
                        }
                    }
                }
            else:
                payload = {"equipment": {"swc_0": {name: state}}}

            _LOGGER.debug("iAQUALINK_eXO-IQ - TEST set_toggle payload=%s", payload)
            response = await self.send_desired_state_request(payload)
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - TEST set_toggle HTTP status=%s body=%s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        except Exception:
            _LOGGER.debug(
                "iAQUALINK_eXO-IQ - TEST set_toggle FAILED name=%s state=%s",
                name,
                state,
            )
            raise

    # -------------------------------------------------------------------------
    # Timer name and device resolution helpers
    # -------------------------------------------------------------------------
    def _normalize_timer_key(self, schedule_dev_name: str) -> str:
        """Convert schedule device name to API schedule key."""
        name = schedule_dev_name.removeprefix("schedule_")
        if name.endswith("_rpm"):
            name = name[:-4]
        if name.endswith("_enabled"):
            name = name[:-8]
        if name.endswith("_active"):
            name = name[:-7]
        return name

    def _get_timer_base_dev_name(self, schedule_dev_name: str) -> str:
        """Return the main schedule device name for a derived timer entity."""
        base_name = schedule_dev_name

        for suffix in ("_rpm", "_enabled", "_active"):
            if base_name.endswith(suffix):
                base_name = base_name[: -len(suffix)]
                break

        return base_name

    def _get_timer_group_id_from_endpoint(self, endpoint: str | None) -> str | None:
        """Map an endpoint to a logical grouped timer id."""
        return get_timer_group_id_from_endpoint(endpoint)

    def _get_timer_members(self, group_id: str) -> list[str]:
        """Return main schedule devices belonging to one grouped timer."""
        members: list[str] = []

        for dev_name, dev in self.devices.items():
            if not dev_name.startswith("schedule_"):
                continue
            if dev_name.endswith(("_rpm", "_enabled", "_active")):
                continue

            endpoint = (getattr(dev, "data", {}) or {}).get("endpoint")
            dev_group = self._get_timer_group_id_from_endpoint(endpoint)
            if dev_group == group_id:
                members.append(dev_name)

        return sorted(members)

    # -------------------------------------------------------------------------
    # Schedule payload snapshot helpers
    # Backend still uses schedule keys and schedule payload structure.
    # -------------------------------------------------------------------------
    def _get_schedule_payload_snapshot(self, schedule_dev_name: str) -> dict[str, Any]:
        """Build current schedule payload from loaded devices."""
        base_dev_name = self._get_timer_base_dev_name(schedule_dev_name)
        base_dev = self.devices.get(base_dev_name)

        if base_dev is None:
            raise AqualinkServiceException(f"Unknown schedule device: {schedule_dev_name}")

        data = getattr(base_dev, "data", {}) or {}

        payload: dict[str, Any] = {
            "enabled": int(data.get("state", 0) or 0),
            "timer": {
                "start": data.get("start", "00:00"),
                "end": data.get("end", "00:00"),
            },
        }

        rpm_dev = self.devices.get(f"{base_dev_name}_rpm")
        if rpm_dev is not None:
            try:
                payload["rpm"] = int(getattr(rpm_dev, "state", 0) or 0)
            except (TypeError, ValueError):
                payload["rpm"] = 0

        enabled_dev = self.devices.get(f"{base_dev_name}_enabled")
        if enabled_dev is not None:
            try:
                payload["enabled"] = int(getattr(enabled_dev, "state", 0) or 0)
            except (TypeError, ValueError):
                payload["enabled"] = 0

        return payload

    # -------------------------------------------------------------------------
    # Legacy direct per-schedule write helpers kept for compatibility
    # -------------------------------------------------------------------------
    async def set_schedule(self, schedule_dev_name: str, changes: dict[str, Any]) -> None:
        """Update one schedule in AWS shadow desired state."""
        schedule_key = self._normalize_timer_key(schedule_dev_name)
        current = self._get_schedule_payload_snapshot(schedule_dev_name)

        if "timer" in changes:
            current_timer = current.get("timer", {}) or {}
            new_timer = changes["timer"] or {}
            current["timer"] = {
                "start": new_timer.get("start", current_timer.get("start")),
                "end": new_timer.get("end", current_timer.get("end")),
            }

        for key, value in changes.items():
            if key == "timer":
                continue
            current[key] = value

        payload = {"schedules": {schedule_key: current}}

        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - set_schedule dev=%s key=%s changes=%s payload=%s",
            schedule_dev_name,
            schedule_key,
            changes,
            payload,
        )

        response = await self.send_desired_state_request(payload)
        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - set_schedule HTTP status=%s body=%s",
            response.status_code,
            response.text,
        )
        response.raise_for_status()

    async def set_schedule_time(
        self,
        schedule_dev_name: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> None:
        """Update schedule start/end time."""
        timer_changes: dict[str, str] = {}
        if start is not None:
            timer_changes["start"] = start
        if end is not None:
            timer_changes["end"] = end

        await self.set_schedule(schedule_dev_name, {"timer": timer_changes})

    async def set_schedule_rpm(self, schedule_dev_name: str, rpm: int) -> None:
        """Update schedule RPM."""
        await self.set_schedule(schedule_dev_name, {"rpm": int(rpm)})

    # -------------------------------------------------------------------------
    # Pending grouped timer editor state
    # -------------------------------------------------------------------------
    def get_pending_timer_group(self, group_id: str) -> dict[str, dict[str, Any]]:
        """Return staged values for one grouped timer."""
        return self.pending_schedule_groups.setdefault(group_id, {})

    def clear_pending_timer_group(self, group_id: str) -> None:
        """Clear all staged values for one grouped timer."""
        self.pending_schedule_groups.pop(group_id, None)

    def get_timer_editor_value(
        self,
        schedule_dev_name: str,
        field: str,
        default: Any = None,
    ) -> Any:
        """Return staged or current value for a timer editor field."""
        base_dev_name = self._get_timer_base_dev_name(schedule_dev_name)
        dev = self.devices.get(base_dev_name)
        if dev is None:
            return default

        data = getattr(dev, "data", {}) or {}
        endpoint = data.get("endpoint")
        group_id = self._get_timer_group_id_from_endpoint(endpoint)

        if not group_id:
            return data.get(field, default)

        pending_group = self.pending_schedule_groups.get(group_id, {})
        pending_schedule = pending_group.get(base_dev_name, {})

        if field in pending_schedule:
            return pending_schedule[field]

        return data.get(field, default)

    def get_timer_editor_rpm(self, schedule_dev_name: str, default: Any = None) -> Any:
        """Return staged or current RPM value for a timer editor."""
        base_dev_name = self._get_timer_base_dev_name(schedule_dev_name)
        main_dev = self.devices.get(base_dev_name)
        if main_dev is None:
            return default

        data = getattr(main_dev, "data", {}) or {}
        endpoint = data.get("endpoint")
        group_id = self._get_timer_group_id_from_endpoint(endpoint)

        rpm_dev_name = f"{base_dev_name}_rpm"
        rpm_dev = self.devices.get(rpm_dev_name)

        current_rpm = default
        if rpm_dev is not None:
            current_rpm = getattr(rpm_dev, "state", default)

        if not group_id:
            return current_rpm

        pending_group = self.pending_schedule_groups.get(group_id, {})
        pending_schedule = pending_group.get(base_dev_name, {})
        if "rpm" in pending_schedule:
            return pending_schedule["rpm"]

        return current_rpm

    def stage_timer_change(self, schedule_dev_name: str, changes: dict[str, Any]) -> None:
        """Stage a local grouped timer change without sending it yet."""
        base_dev_name = self._get_timer_base_dev_name(schedule_dev_name)
        dev = self.devices.get(base_dev_name)
        if dev is None:
            raise AqualinkServiceException(f"Unknown schedule device: {schedule_dev_name}")

        data = getattr(dev, "data", {}) or {}
        endpoint = data.get("endpoint")
        group_id = self._get_timer_group_id_from_endpoint(endpoint)
        if not group_id:
            raise AqualinkServiceException(
                f"No group mapping for schedule device: {schedule_dev_name}"
            )

        pending_group = self.pending_schedule_groups.setdefault(group_id, {})
        pending_schedule = pending_group.setdefault(base_dev_name, {})

        pending_schedule.update(changes)

        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - stage_timer_change group=%s dev=%s changes=%s pending=%s",
            group_id,
            base_dev_name,
            changes,
            pending_group,
        )

    # Backward-compatible aliases
    def get_pending_schedule_group(self, group_id: str) -> dict[str, dict[str, Any]]:
        return self.get_pending_timer_group(group_id)

    def get_schedule_editor_value(
        self,
        schedule_dev_name: str,
        field: str,
        default: Any = None,
    ) -> Any:
        return self.get_timer_editor_value(schedule_dev_name, field, default)

    def get_schedule_editor_rpm(self, schedule_dev_name: str, default: Any = None) -> Any:
        return self.get_timer_editor_rpm(schedule_dev_name, default)

    def stage_schedule_change(self, schedule_dev_name: str, changes: dict[str, Any]) -> None:
        self.stage_timer_change(schedule_dev_name, changes)

    def clear_pending_schedule_group(self, group_id: str) -> None:
        self.clear_pending_timer_group(group_id)

    # -------------------------------------------------------------------------
    # Reported schedule entry helpers
    # -------------------------------------------------------------------------
    def _get_reported_schedule_entry(self, schedule_key: str) -> dict[str, Any]:
        """Return a deep copy of one reported schedule entry from raw shadow."""
        schedules = self._reported_root().get("schedules", {}) or {}
        entry = schedules.get(schedule_key)
        if isinstance(entry, dict):
            return deepcopy(entry)
        return {}

    # -------------------------------------------------------------------------
    # Grouped schedule payload builders and validation
    # Backend still uses schedule payloads.
    # -------------------------------------------------------------------------
    def _build_group_schedule_payload(self, schedule_dev_name: str) -> dict[str, Any]:
        """Build one final grouped schedule payload from staged values."""
        base_dev_name = self._get_timer_base_dev_name(schedule_dev_name)
        current = self._get_schedule_payload_snapshot(base_dev_name)

        start = self.get_timer_editor_value(
            base_dev_name,
            "start",
            current.get("timer", {}).get("start", "00:00"),
        )
        end = self.get_timer_editor_value(
            base_dev_name,
            "end",
            current.get("timer", {}).get("end", "00:00"),
        )
        rpm = self.get_timer_editor_rpm(base_dev_name, current.get("rpm", 0))

        payload: dict[str, Any] = {
            "enabled": 0 if (start == "00:00" and end == "00:00") else 1,
            "timer": {
                "start": start,
                "end": end,
            },
        }

        if "rpm" in current:
            payload["rpm"] = int(rpm or 0)

        return payload

    # -------------------------------------------------------------------------
    # Timer group save / clear actions
    # -------------------------------------------------------------------------
    def _validate_timer_range(
        self,
        *,
        group_id: str,
        schedule_key: str,
        start: str,
        end: str,
    ) -> None:
        """Validate one timer range before sending it to the backend."""
        if not start or not end:
            raise AqualinkServiceException(
                f"Invalid timer range for {group_id}/{schedule_key}: missing start or end"
            )

        # Only same-day forward ranges are supported here.
        if start >= end:
            raise AqualinkServiceException(
                f"Invalid timer range for {group_id}/{schedule_key}: start ({start}) must be earlier than end ({end})"
            )

    def _validate_group_timer_payload(
        self,
        *,
        group_id: str,
        members: list[str],
        payload_schedules: dict[str, Any],
    ) -> None:
        """Validate grouped timer payload before sending it."""
        # --- Rule 1: every enabled timer must satisfy start < end ---
        for schedule_key, schedule_payload in payload_schedules.items():
            if int(schedule_payload.get("enabled", 0) or 0) != 1:
                continue

            timer = schedule_payload.get("timer", {}) or {}
            start = timer.get("start")
            end = timer.get("end")

            self._validate_timer_range(
                group_id=group_id,
                schedule_key=schedule_key,
                start=start,
                end=end,
            )

        # --- Rule 2: SWC must stay inside Pump window for Timer 1 / Timer 2 ---
        if group_id not in ("timer_1", "timer_2"):
            return

        pump_dev = next(
            (
                member
                for member in members
                if (getattr(self.devices[member], "data", {}) or {})
                .get("endpoint", "")
                .startswith("vsp_")
            ),
            None,
        )
        swc_dev = next(
            (
                member
                for member in members
                if (getattr(self.devices[member], "data", {}) or {})
                .get("endpoint", "")
                .startswith("swc_")
            ),
            None,
        )

        if not pump_dev or not swc_dev:
            return

        pump_payload = payload_schedules.get(self._normalize_timer_key(pump_dev))
        swc_payload = payload_schedules.get(self._normalize_timer_key(swc_dev))

        if not pump_payload or not swc_payload:
            return

        # Validate SWC only when it is enabled.
        if int(swc_payload.get("enabled", 0) or 0) != 1:
            return

        # Pump must also be enabled if SWC is enabled.
        if int(pump_payload.get("enabled", 0) or 0) != 1:
            raise AqualinkServiceException(
                f"Invalid timer group {group_id}: SWC cannot be enabled while Pump is disabled"
            )

        p_timer = pump_payload.get("timer", {}) or {}
        s_timer = swc_payload.get("timer", {}) or {}

        p_start = p_timer.get("start")
        p_end = p_timer.get("end")
        s_start = s_timer.get("start")
        s_end = s_timer.get("end")

        if not p_start or not p_end or not s_start or not s_end:
            raise AqualinkServiceException(
                f"Invalid timer group {group_id}: missing Pump or SWC timer values"
            )

        # Inclusive inclusion:
        # start_pump <= start_swc and end_swc <= end_pump
        if s_start < p_start or s_end > p_end:
            raise AqualinkServiceException(
                f"Invalid timer group {group_id}: SWC window ({s_start}-{s_end}) must stay inside Pump window ({p_start}-{p_end})"
            )

    async def save_timer_group(self, group_id: str) -> None:
        """Save all staged values for one grouped timer."""
        members = self._get_timer_members(group_id)
        if not members:
            raise AqualinkServiceException(f"No schedules found for group {group_id}")

        payload_schedules: dict[str, Any] = {}

        for base_dev_name in members:
            dev = self.devices.get(base_dev_name)
            if dev is None:
                continue

            key = self._normalize_timer_key(base_dev_name)
            payload_schedules[key] = self._build_group_schedule_payload(base_dev_name)

        if group_id in ("timer_1", "timer_2"):
            pump_dev = next(
                (
                    member
                    for member in members
                    if (getattr(self.devices[member], "data", {}) or {})
                    .get("endpoint", "")
                    .startswith("vsp_")
                ),
                None,
            )
            swc_dev = next(
                (
                    member
                    for member in members
                    if (getattr(self.devices[member], "data", {}) or {})
                    .get("endpoint", "")
                    .startswith("swc_")
                ),
                None,
            )

            if pump_dev and swc_dev:
                pump_payload = payload_schedules[self._normalize_timer_key(pump_dev)]
                swc_payload = payload_schedules[self._normalize_timer_key(swc_dev)]

                p_start = pump_payload["timer"]["start"]
                p_end = pump_payload["timer"]["end"]
                s_start = swc_payload["timer"]["start"]
                s_end = swc_payload["timer"]["end"]

                if (s_start, s_end) != ("00:00", "00:00"):
                    if s_start < p_start or s_end > p_end:
                        raise AqualinkServiceException(
                            f"SWC schedule must stay inside Pump schedule window for {group_id}"
                        )

        self._validate_group_timer_payload(
            group_id=group_id,
            members=members,
            payload_schedules=payload_schedules,
        )
        
        payload = {"schedules": payload_schedules}

        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - save_timer_group group=%s payload=%s",
            group_id,
            payload,
        )

        response = await self.send_desired_state_request(payload)
        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - save_timer_group HTTP status=%s body=%s",
            response.status_code,
            response.text,
        )
        response.raise_for_status()

        self._apply_schedule_payload_locally(payload_schedules)
        self._reparse_local_shadow()

        self.clear_pending_timer_group(group_id)
        self._set_schedule_refresh_cooldown(180)

    async def clear_timer_group(self, group_id: str) -> None:
        """Disable and clear all schedules in one group."""
        members = self._get_timer_members(group_id)
        if not members:
            raise AqualinkServiceException(f"No schedules found for group {group_id}")

        payload_schedules: dict[str, Any] = {}

        for base_dev_name in members:
            key = self._normalize_timer_key(base_dev_name)
            payload_schedules[key] = {
                "enabled": 0,
                "timer": {
                    "start": "00:00",
                    "end": "00:00",
                },
            }

        payload = {"schedules": payload_schedules}

        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - clear_timer_group group=%s payload=%s",
            group_id,
            payload,
        )

        response = await self.send_desired_state_request(payload)
        _LOGGER.debug(
            "iAQUALINK_eXO-IQ - clear_timer_group HTTP status=%s body=%s",
            response.status_code,
            response.text,
        )
        response.raise_for_status()

        self._apply_schedule_payload_locally(payload_schedules)
        self._reparse_local_shadow()

        self.clear_pending_timer_group(group_id)
        self._set_schedule_refresh_cooldown(180)

    # -------------------------------------------------------------------------
    # Local shadow update helpers after successful writes
    # -------------------------------------------------------------------------
    def _set_schedule_refresh_cooldown(self, seconds: int = 180) -> None:
        """Block refresh for a cooldown period after schedule writes."""
        self._schedule_refresh_block_until = max(
            self._schedule_refresh_block_until,
            time.time() + seconds,
        )

    def _apply_schedule_payload_locally(self, payload_schedules: dict[str, Any]) -> None:
        """Apply written schedule values to local reported shadow cache."""
        state = self.raw_shadow.setdefault("state", {})
        reported = state.setdefault("reported", {})
        schedules = reported.setdefault("schedules", {})

        if not isinstance(schedules, dict):
            return

        for schedule_key, new_value in payload_schedules.items():
            current = schedules.get(schedule_key, {})
            if not isinstance(current, dict):
                current = {}

            merged = dict(current)
            merged.update(new_value)

            if "timer" in new_value:
                current_timer = current.get("timer", {})
                if not isinstance(current_timer, dict):
                    current_timer = {}
                new_timer = new_value.get("timer", {})
                if not isinstance(new_timer, dict):
                    new_timer = {}

                merged["timer"] = {
                    **current_timer,
                    **new_timer,
                }

            schedules[schedule_key] = merged

    def _reparse_local_shadow(self) -> None:
        """Re-parse locally cached shadow into devices."""

        class _LocalShadowResponse:
            def __init__(self, data: dict[str, Any]) -> None:
                self._data = data

            def json(self) -> dict[str, Any]:
                return self._data

        self._parse_shadow_response(
            _LocalShadowResponse(self.raw_shadow),
            source="local-cache",
        )
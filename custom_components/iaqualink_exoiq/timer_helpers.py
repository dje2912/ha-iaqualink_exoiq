"""Helpers for Exo grouped timers."""

from __future__ import annotations


def get_timer_group_from_endpoint(endpoint: str | None) -> tuple[str, str] | None:
    """Map Exo endpoint to grouped Home Assistant timer device."""
    endpoint = (endpoint or "").lower()

    if endpoint in ("vsp_1", "swc_1"):
        return ("timer_1", "Timer 1")
    if endpoint in ("vsp_2", "swc_2"):
        return ("timer_2", "Timer 2")
    if endpoint == "vsp_3":
        return ("timer_3", "Timer 3")
    if endpoint == "vsp_4":
        return ("timer_4", "Timer 4")
    if endpoint == "aux1":
        return ("timer_aux_1", "Timer Aux 1")
    if endpoint == "aux2":
        return ("timer_aux_2", "Timer Aux 2")

    return None


def get_timer_group_id_from_endpoint(
    endpoint: str | None,
    fallback: str | None = None,
) -> str | None:
    """Return only the grouped timer id."""
    group = get_timer_group_from_endpoint(endpoint)
    if group is None:
        return fallback
    return group[0]


def get_timer_role_from_endpoint(endpoint: str | None) -> str:
    """Return user-friendly role for grouped timer entities."""
    endpoint = (endpoint or "").lower()

    if endpoint.startswith("vsp_"):
        return "Pump"
    if endpoint.startswith("swc_"):
        return "SWC"
    if endpoint.startswith("aux"):
        return "Aux"

    return "Timer"


def get_timer_entity_name(endpoint: str | None, kind: str) -> str:
    """Return friendly display name for grouped timer entities."""
    role = get_timer_role_from_endpoint(endpoint)

    if kind == "sensor":
        return role
    if kind == "speed":
        return "Pump Speed" if role == "Pump" else f"{role} Speed"
    if kind == "start":
        return f"{role} Start"
    if kind == "end":
        return f"{role} End"
    if kind == "enabled":
        return f"{role} Enabled"
    if kind == "active":
        return f"{role} Active"
    if kind == "save":
        return "Save"
    if kind == "clear":
        return "Clear"

    return role


def get_timer_object_id(group_id: str, endpoint: str | None, kind: str) -> str:
    """Return timer-based object_id for grouped timer entities."""
    role = get_timer_role_from_endpoint(endpoint).lower()

    if kind == "sensor":
        return f"{group_id}_{role}"
    if kind == "speed":
        return f"{group_id}_{role}_speed"
    if kind == "start":
        return f"{group_id}_{role}_start"
    if kind == "end":
        return f"{group_id}_{role}_end"
    if kind == "enabled":
        return f"{group_id}_{role}_enabled"
    if kind == "active":
        return f"{group_id}_{role}_active"
    if kind == "save":
        return f"{group_id}_save"
    if kind == "clear":
        return f"{group_id}_clear"

    return f"{group_id}_{role}"


def get_timer_unique_id(
    serial: str,
    family: str,
    group_id: str,
    endpoint: str | None,
    kind: str,
) -> str:
    """Return a stable unique_id for grouped timer entities."""
    role = get_timer_role_from_endpoint(endpoint).lower()

    if kind == "sensor":
        return f"{serial}_timer_{family}_{group_id}_{role}_main"
    if kind == "speed":
        return f"{serial}_timer_{family}_{group_id}_{role}_speed"
    if kind == "start":
        return f"{serial}_timer_{family}_{group_id}_{role}_start"
    if kind == "end":
        return f"{serial}_timer_{family}_{group_id}_{role}_end"
    if kind == "enabled":
        return f"{serial}_timer_{family}_{group_id}_{role}_enabled"
    if kind == "active":
        return f"{serial}_timer_{family}_{group_id}_{role}_active"
    if kind == "save":
        return f"{serial}_timer_{family}_{group_id}_save"
    if kind == "clear":
        return f"{serial}_timer_{family}_{group_id}_clear"

    return f"{serial}_timer_{family}_{group_id}_{role}_{kind}"
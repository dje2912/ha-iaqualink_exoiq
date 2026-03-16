"""Helpers for Aqualink grouped timer editing."""

from __future__ import annotations

from .schedule import AqualinkScheduleEntity
from .timer_helpers import (
    get_timer_group_from_endpoint,
    get_timer_group_id_from_endpoint,
    get_timer_role_from_endpoint,
)


class AqualinkTimerGroupEntity(AqualinkScheduleEntity):
    """Base class for grouped timer editor entities."""

    def __init__(self, coordinator, dev) -> None:
        super().__init__(coordinator, dev)
        self._group_id = get_timer_group_id_from_endpoint(
            self.schedule_endpoint,
            self.schedule_dev_name,
        )
        self._group = get_timer_group_from_endpoint(self.schedule_endpoint)

    @property
    def group_id(self) -> str:
        return self._group_id

    @property
    def group_name(self) -> str:
        if self._group is None:
            return self.schedule_name
        return self._group[1]

    @property
    def timer_role(self) -> str:
        return get_timer_role_from_endpoint(self.schedule_endpoint)
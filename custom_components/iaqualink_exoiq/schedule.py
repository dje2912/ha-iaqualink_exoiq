"""Helpers for Aqualink schedule entities."""

from __future__ import annotations

from . import AqualinkEntity


class AqualinkScheduleEntity(AqualinkEntity):
    """Base class for all schedule entities."""

    def __init__(self, coordinator, dev) -> None:
        super().__init__(coordinator, dev)

        data = getattr(dev, "data", {}) or {}

        self._schedule_name = data.get("schedule_name") or getattr(dev, "label", dev.name)
        self._schedule_id = data.get("schedule_id") or dev.name
        self._schedule_endpoint = data.get("endpoint")
        self._schedule_dev_name = getattr(dev, "name", "") or ""

    @property
    def schedule_name(self) -> str:
        return self._schedule_name

    @property
    def schedule_id(self) -> str:
        return self._schedule_id

    @property
    def schedule_endpoint(self) -> str | None:
        return self._schedule_endpoint

    @property
    def schedule_dev_name(self) -> str:
        return self._schedule_dev_name

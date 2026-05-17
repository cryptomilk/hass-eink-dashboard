"""Battery sensor HA platform entry point."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .battery_sensor import EinkDashboardBatterySensor
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Create and register the battery sensor entity."""
    _LOGGER.debug("sensor async_setup_entry: %s", entry.entry_id)
    sensor = EinkDashboardBatterySensor(entry)
    async_add_entities([sensor])
    hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

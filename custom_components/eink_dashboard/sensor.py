"""Battery sensor entity for eink_dashboard."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Create and register the battery sensor entity."""
    sensor = EinkDashboardBatterySensor(entry)
    async_add_entities([sensor])
    hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor


class EinkDashboardBatterySensor(RestoreSensor):
    """Battery level sensor, updated on each Kindle image poll."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_has_entity_name = True
    _attr_name = "Battery"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialise from the config entry."""
        self._attr_unique_id = f"{entry.entry_id}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )
        self._attr_native_value: int | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore last known battery state after HA restart."""
        await super().async_added_to_hass()
        last_data = await self.async_get_last_sensor_data()
        if last_data is None:
            return
        self._attr_native_value = last_data.native_value

    def update_battery(self, level: int, is_charging: bool) -> None:
        """Update battery level and charging state, then push to HA."""
        self._attr_native_value = level
        self._attr_extra_state_attributes = {"is_charging": is_charging}
        self.async_write_ha_state()

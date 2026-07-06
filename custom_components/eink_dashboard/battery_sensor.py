# Copyright 2026 Andreas Schneider
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""EinkDashboardBatterySensor entity definition."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
            _LOGGER.debug("sensor async_added_to_hass: no previous data")
            return
        self._attr_native_value = last_data.native_value
        last_state = await self.async_get_last_state()
        if last_state is not None:
            is_charging = last_state.attributes.get("is_charging")
            if is_charging is not None:
                self._attr_extra_state_attributes = {
                    "is_charging": is_charging
                }
        _LOGGER.debug(
            "sensor async_added_to_hass: restored battery=%s",
            self._attr_native_value,
        )

    def update_battery(self, level: int, is_charging: bool) -> None:
        """Update battery level and charging state, then push to HA."""
        self._attr_native_value = level
        self._attr_extra_state_attributes = {"is_charging": is_charging}
        self.async_write_ha_state()

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

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.eink_dashboard.battery_sensor import (
    EinkDashboardBatterySensor,
)
from custom_components.eink_dashboard.const import DOMAIN
from custom_components.eink_dashboard.sensor import async_setup_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class TestEinkDashboardBatterySensor:
    def test_sensor_attrs(self) -> None:
        # All fixed attributes are set correctly on construction.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="my_entry")
        sensor = EinkDashboardBatterySensor(entry)
        assert sensor._attr_device_class == "battery"
        assert sensor._attr_state_class == "measurement"
        assert sensor._attr_native_unit_of_measurement == "%"
        assert sensor._attr_has_entity_name is True
        assert sensor._attr_name == "Battery"
        assert sensor._attr_unique_id == "my_entry_battery"
        assert sensor._attr_device_info == {
            "identifiers": {(DOMAIN, "my_entry")}
        }

    def test_initial_value_is_none(self) -> None:
        # Native value and extra attributes start empty before any update.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        assert sensor._attr_native_value is None
        assert sensor._attr_extra_state_attributes == {}

    def test_update_battery_sets_value_and_attrs(self) -> None:
        # update_battery stores the level and charging flag.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(78, False)
        assert sensor._attr_native_value == 78
        assert sensor._attr_extra_state_attributes == {"is_charging": False}

    def test_update_battery_charging_true(self) -> None:
        # Charging flag is stored when is_charging=True.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(42, True)
        assert sensor._attr_extra_state_attributes == {"is_charging": True}

    def test_update_battery_zero(self) -> None:
        # Zero is a valid battery level (not treated as falsy).
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(0, False)
        assert sensor._attr_native_value == 0

    def test_update_battery_hundred(self) -> None:
        # 100% is a valid battery level.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(100, True)
        assert sensor._attr_native_value == 100

    def test_update_battery_calls_write_ha_state(self) -> None:
        # async_write_ha_state is called exactly once per update_battery call.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        called = []
        sensor.async_write_ha_state = lambda: called.append(True)
        sensor.update_battery(50, False)
        assert called


class TestBatterySensorRestore:
    async def test_restore_from_last_sensor_data(
        self, hass: HomeAssistant
    ) -> None:
        # async_added_to_hass restores native_value from the extra stored data.
        from homeassistant.core import State

        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.hass = hass
        sensor.entity_id = "sensor.eink_dashboard_battery"

        mock_restore_cache_with_extra_data(
            hass,
            [
                (
                    State("sensor.eink_dashboard_battery", "65"),
                    {"native_value": 65, "native_unit_of_measurement": "%"},
                )
            ],
        )

        await sensor.async_added_to_hass()

        assert sensor._attr_native_value == 65

    async def test_restore_no_last_data(self, hass: HomeAssistant) -> None:
        # When the restore cache has no entry, native_value stays None.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.hass = hass
        sensor.entity_id = "sensor.eink_dashboard_battery"

        await sensor.async_added_to_hass()

        assert sensor._attr_native_value is None

    async def test_restore_is_charging(self, hass: HomeAssistant) -> None:
        # is_charging attribute is restored from the State attributes dict.
        from homeassistant.core import State

        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.hass = hass
        sensor.entity_id = "sensor.eink_dashboard_battery"

        mock_restore_cache_with_extra_data(
            hass,
            [
                (
                    State(
                        "sensor.eink_dashboard_battery",
                        "42",
                        {"is_charging": True},
                    ),
                    {"native_value": 42, "native_unit_of_measurement": "%"},
                )
            ],
        )

        await sensor.async_added_to_hass()

        assert sensor._attr_extra_state_attributes == {"is_charging": True}

    async def test_restore_is_charging_absent_leaves_attrs_empty(
        self, hass: HomeAssistant
    ) -> None:
        # When is_charging is absent from last state attributes,
        # extra_state_attributes stays {}.
        from homeassistant.core import State

        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        sensor = EinkDashboardBatterySensor(entry)
        sensor.hass = hass
        sensor.entity_id = "sensor.eink_dashboard_battery"

        mock_restore_cache_with_extra_data(
            hass,
            [
                (
                    State("sensor.eink_dashboard_battery", "42"),
                    {"native_value": 42, "native_unit_of_measurement": "%"},
                )
            ],
        )

        await sensor.async_added_to_hass()

        assert sensor._attr_extra_state_attributes == {}


class TestSensorPlatformSetup:
    async def test_async_setup_entry_creates_sensor(
        self, hass: HomeAssistant
    ) -> None:
        # async_setup_entry calls async_add_entities with one battery sensor.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        entry.add_to_hass(hass)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
        added: list = []

        await async_setup_entry(hass, entry, added.append)

        assert len(added) == 1
        sensors = list(added[0])
        assert len(sensors) == 1
        assert isinstance(sensors[0], EinkDashboardBatterySensor)

    async def test_async_setup_entry_stores_sensor(
        self, hass: HomeAssistant
    ) -> None:
        # The sensor is stored in hass.data under the "battery_sensor" key.
        entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry_id")
        entry.add_to_hass(hass)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}

        await async_setup_entry(hass, entry, lambda entities: None)

        sensor = hass.data[DOMAIN][entry.entry_id]["battery_sensor"]
        assert isinstance(sensor, EinkDashboardBatterySensor)

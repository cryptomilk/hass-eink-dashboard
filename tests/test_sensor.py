from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.eink_dashboard.battery_sensor import (
    EinkDashboardBatterySensor,
)
from custom_components.eink_dashboard.const import DOMAIN
from custom_components.eink_dashboard.sensor import async_setup_entry


def _make_entry(entry_id: str = "test_entry_id") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


class TestEinkDashboardBatterySensor:
    def test_sensor_attrs(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry("my_entry"))
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
        sensor = EinkDashboardBatterySensor(_make_entry())
        assert sensor._attr_native_value is None
        assert sensor._attr_extra_state_attributes == {}

    def test_update_battery_sets_value_and_attrs(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(78, False)
        assert sensor._attr_native_value == 78
        assert sensor._attr_extra_state_attributes == {"is_charging": False}

    def test_update_battery_charging_true(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(42, True)
        assert sensor._attr_extra_state_attributes == {"is_charging": True}

    def test_update_battery_zero(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(0, False)
        assert sensor._attr_native_value == 0

    def test_update_battery_hundred(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        sensor.async_write_ha_state = MagicMock()
        sensor.update_battery(100, True)
        assert sensor._attr_native_value == 100

    def test_update_battery_calls_write_ha_state(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        called = []
        sensor.async_write_ha_state = lambda: called.append(True)
        sensor.update_battery(50, False)
        assert called


class TestBatterySensorRestore:
    async def test_restore_from_last_sensor_data(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        last_data = MagicMock()
        last_data.native_value = 65
        sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)
        sensor.async_get_last_state = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        assert sensor._attr_native_value == 65

    async def test_restore_no_last_data(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        sensor.async_get_last_sensor_data = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        assert sensor._attr_native_value is None

    async def test_restore_is_charging(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        last_data = MagicMock()
        last_data.native_value = 42
        last_state = MagicMock()
        last_state.attributes = {"is_charging": True}
        sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)
        sensor.async_get_last_state = AsyncMock(return_value=last_state)

        await sensor.async_added_to_hass()

        assert sensor._attr_extra_state_attributes == {"is_charging": True}

    async def test_restore_is_charging_absent_leaves_attrs_empty(self) -> None:
        sensor = EinkDashboardBatterySensor(_make_entry())
        last_data = MagicMock()
        last_data.native_value = 42
        last_state = MagicMock()
        last_state.attributes = {}
        sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)
        sensor.async_get_last_state = AsyncMock(return_value=last_state)

        await sensor.async_added_to_hass()

        assert sensor._attr_extra_state_attributes == {}


class TestSensorPlatformSetup:
    async def test_async_setup_entry_creates_sensor(self) -> None:
        entry = _make_entry()
        hass = MagicMock()
        hass.data = {DOMAIN: {entry.entry_id: {}}}
        added: list = []

        await async_setup_entry(hass, entry, added.append)

        assert len(added) == 1
        sensors = list(added[0])
        assert len(sensors) == 1
        assert isinstance(sensors[0], EinkDashboardBatterySensor)

    async def test_async_setup_entry_stores_sensor(self) -> None:
        entry = _make_entry()
        hass = MagicMock()
        hass.data = {DOMAIN: {entry.entry_id: {}}}

        await async_setup_entry(hass, entry, lambda entities: None)

        sensor = hass.data[DOMAIN][entry.entry_id]["battery_sensor"]
        assert isinstance(sensor, EinkDashboardBatterySensor)

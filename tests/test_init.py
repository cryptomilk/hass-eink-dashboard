from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.eink_dashboard import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.eink_dashboard.battery import resolve_battery_level
from custom_components.eink_dashboard.const import DOMAIN
from custom_components.eink_dashboard.http import (
    EinkLayoutView,
    EinkPublicImageView,
)


def _make_entry(
    entry_id: str = "entry1",
    data: dict | None = None,
    options: dict | None = None,
    title: str = "My Dashboard",
) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = title
    entry.data = data or {}
    entry.options = options or {}
    return entry


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.http.async_register_static_paths = AsyncMock()
    return hass


class TestAsyncSetup:
    async def test_registers_http_views(self) -> None:
        hass = _make_hass()

        await async_setup(hass, {})

        assert hass.http.register_view.call_count == 2
        view_types = {
            type(call.args[0])
            for call in hass.http.register_view.call_args_list
        }
        assert EinkPublicImageView in view_types
        assert EinkLayoutView in view_types

    async def test_registers_static_path(self) -> None:
        hass = _make_hass()

        await async_setup(hass, {})

        hass.http.async_register_static_paths.assert_called_once()
        configs = hass.http.async_register_static_paths.call_args.args[0]
        assert len(configs) == 3
        assert configs[0].url_path == "/eink_dashboard/frontend"
        assert configs[0].path.endswith("frontend")
        assert configs[1].url_path == "/eink_dashboard/fonts"
        assert configs[1].path.endswith("fonts")
        assert configs[2].url_path == "/eink_dashboard/icons"
        assert configs[2].path.endswith("icons")

    async def test_returns_true(self) -> None:
        hass = _make_hass()

        result = await async_setup(hass, {})

        assert result is True


class TestAsyncSetupEntry:
    async def test_populates_hass_data(self) -> None:
        hass = _make_hass()
        hass.data[DOMAIN] = {}
        entry = _make_entry()
        widgets = [{"type": "separator", "y": 10}]

        with patch(
            "custom_components.eink_dashboard.EinkDashboardStore"
        ) as MockStore:
            MockStore.return_value.async_load = AsyncMock(return_value=widgets)
            await async_setup_entry(hass, entry)

        assert entry.entry_id in hass.data[DOMAIN]
        data = hass.data[DOMAIN][entry.entry_id]
        assert "store" in data
        assert data["widgets"] == widgets

    async def test_stores_entry_reference(self) -> None:
        hass = _make_hass()
        hass.data[DOMAIN] = {}
        entry = _make_entry()

        with patch(
            "custom_components.eink_dashboard.EinkDashboardStore"
        ) as MockStore:
            MockStore.return_value.async_load = AsyncMock(return_value=[])
            await async_setup_entry(hass, entry)

        assert hass.data[DOMAIN][entry.entry_id]["entry"] is entry

    async def test_forwards_to_image_platform(self) -> None:
        hass = _make_hass()
        hass.data[DOMAIN] = {}
        entry = _make_entry()

        with patch(
            "custom_components.eink_dashboard.EinkDashboardStore"
        ) as MockStore:
            MockStore.return_value.async_load = AsyncMock(return_value=[])
            await async_setup_entry(hass, entry)

        hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            entry, ["image", "sensor"]
        )

    async def test_returns_true(self) -> None:
        hass = _make_hass()
        hass.data[DOMAIN] = {}
        entry = _make_entry()

        with patch(
            "custom_components.eink_dashboard.EinkDashboardStore"
        ) as MockStore:
            MockStore.return_value.async_load = AsyncMock(return_value=[])
            result = await async_setup_entry(hass, entry)

        assert result is True

    async def test_registers_device_with_preset(self) -> None:
        hass = _make_hass()
        hass.data[DOMAIN] = {}
        entry = _make_entry(
            options={"device_model": "kindle_pw4", "area_id": "kitchen"}
        )
        mock_area = MagicMock()
        mock_area.name = "Kitchen"
        mock_area_reg = MagicMock()
        mock_area_reg.async_get_area.return_value = mock_area
        mock_dev_reg = MagicMock()

        with (
            patch(
                "custom_components.eink_dashboard.EinkDashboardStore"
            ) as MockStore,
            patch(
                "custom_components.eink_dashboard.ar.async_get",
                return_value=mock_area_reg,
            ),
            patch(
                "custom_components.eink_dashboard.dr.async_get",
                return_value=mock_dev_reg,
            ),
        ):
            MockStore.return_value.async_load = AsyncMock(return_value=[])
            await async_setup_entry(hass, entry)

        mock_dev_reg.async_get_or_create.assert_called_once_with(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Amazon",
            model="Kindle Paperwhite 4",
            suggested_area="Kitchen",
        )

    async def test_registers_device_custom_no_area(self) -> None:
        hass = _make_hass()
        hass.data[DOMAIN] = {}
        entry = _make_entry(options={"device_model": "custom"})
        mock_dev_reg = MagicMock()

        with (
            patch(
                "custom_components.eink_dashboard.EinkDashboardStore"
            ) as MockStore,
            patch(
                "custom_components.eink_dashboard.dr.async_get",
                return_value=mock_dev_reg,
            ),
        ):
            MockStore.return_value.async_load = AsyncMock(return_value=[])
            await async_setup_entry(hass, entry)

        mock_dev_reg.async_get_or_create.assert_called_once_with(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=None,
            model="Custom",
            suggested_area=None,
        )

    async def test_registers_device_no_model_key(self) -> None:
        hass = _make_hass()
        hass.data[DOMAIN] = {}
        entry = _make_entry(data={})
        mock_dev_reg = MagicMock()

        with (
            patch(
                "custom_components.eink_dashboard.EinkDashboardStore"
            ) as MockStore,
            patch(
                "custom_components.eink_dashboard.dr.async_get",
                return_value=mock_dev_reg,
            ),
        ):
            MockStore.return_value.async_load = AsyncMock(return_value=[])
            await async_setup_entry(hass, entry)

        call_kwargs = mock_dev_reg.async_get_or_create.call_args.kwargs
        assert call_kwargs["manufacturer"] is None
        assert call_kwargs["model"] == "Custom"


class TestAsyncUpdateListener:
    async def test_update_listener_re_registers_device(self) -> None:
        from custom_components.eink_dashboard import _async_update_listener

        hass = _make_hass()
        entry = _make_entry(
            options={"device_model": "kindle_pw4", "area_id": "kitchen"}
        )
        mock_area = MagicMock()
        mock_area.name = "Kitchen"
        mock_area_reg = MagicMock()
        mock_area_reg.async_get_area.return_value = mock_area
        mock_dev_reg = MagicMock()

        with (
            patch(
                "custom_components.eink_dashboard.ar.async_get",
                return_value=mock_area_reg,
            ),
            patch(
                "custom_components.eink_dashboard.dr.async_get",
                return_value=mock_dev_reg,
            ),
        ):
            await _async_update_listener(hass, entry)

        mock_dev_reg.async_get_or_create.assert_called_once_with(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Amazon",
            model="Kindle Paperwhite 4",
            suggested_area="Kitchen",
        )


class TestResolveBatteryLevel:
    def _make_sensor(
        self, level: int | None, is_charging: bool = False
    ) -> MagicMock:
        sensor = MagicMock()
        sensor.native_value = level
        sensor.extra_state_attributes = {"is_charging": is_charging}
        return sensor

    def test_entity_id_takes_priority_over_sensor(self) -> None:
        # battery_entity_id wins even when internal sensor has a value.
        sensor = self._make_sensor(50)
        states = {"sensor.trmnl_battery": {"state": "85", "attributes": {}}}
        level, is_charging = resolve_battery_level(
            "sensor.trmnl_battery", states, sensor
        )
        assert level == 85
        assert is_charging is False

    def test_falls_back_to_sensor_when_no_entity_id(self) -> None:
        # No entity_id configured → internal sensor is used.
        sensor = self._make_sensor(42, is_charging=True)
        level, is_charging = resolve_battery_level(None, {}, sensor)
        assert level == 42
        assert is_charging is True

    def test_entity_id_state_clamped_to_0_100(self) -> None:
        # Values outside 0–100 are clamped.
        states = {"sensor.trmnl_battery": {"state": "150", "attributes": {}}}
        level, _ = resolve_battery_level("sensor.trmnl_battery", states, None)
        assert level == 100

        states = {"sensor.trmnl_battery": {"state": "-5", "attributes": {}}}
        level, _ = resolve_battery_level("sensor.trmnl_battery", states, None)
        assert level == 0

    def test_entity_id_missing_from_states_falls_through_to_sensor(
        self,
    ) -> None:
        # Entity ID configured but not present in states → sensor is used.
        sensor = self._make_sensor(30)
        level, _ = resolve_battery_level("sensor.trmnl_battery", {}, sensor)
        assert level == 30

    def test_entity_id_invalid_state_falls_through_to_sensor(self) -> None:
        # Entity present but unparseable state → sensor is used.
        sensor = self._make_sensor(25)
        states = {
            "sensor.trmnl_battery": {"state": "unavailable", "attributes": {}}
        }
        level, _ = resolve_battery_level(
            "sensor.trmnl_battery", states, sensor
        )
        assert level == 25

    def test_no_entity_no_sensor_returns_none(self) -> None:
        # No data source → (None, False).
        level, is_charging = resolve_battery_level(None, {}, None)
        assert level is None
        assert is_charging is False

    def test_sensor_with_none_value_returns_none(self) -> None:
        # Internal sensor exists but has no reading yet → (None, False).
        sensor = self._make_sensor(None)
        level, is_charging = resolve_battery_level(None, {}, sensor)
        assert level is None
        assert is_charging is False

    def test_entity_id_float_state_truncated(self) -> None:
        # Float state strings are truncated (not rounded) to int.
        states = {
            "sensor.trmnl_battery": {
                "state": "78.9",
                "attributes": {},
            }
        }
        level, _ = resolve_battery_level("sensor.trmnl_battery", states, None)
        assert level == 78

    def test_entity_id_is_charging_read_from_attributes(self) -> None:
        # is_charging is read from the entity's attributes, not hardcoded.
        states = {
            "sensor.trmnl_battery": {
                "state": "50",
                "attributes": {"is_charging": True},
            }
        }
        level, is_charging = resolve_battery_level(
            "sensor.trmnl_battery", states, None
        )
        assert level == 50
        assert is_charging is True


class TestAsyncUnloadEntry:
    async def test_unloads_platforms(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        hass.data = {DOMAIN: {entry.entry_id: {"store": MagicMock()}}}

        result = await async_unload_entry(hass, entry)

        hass.config_entries.async_unload_platforms.assert_called_once_with(
            entry, ["image", "sensor"]
        )
        assert result is True

    async def test_removes_entry_data_on_success(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        hass.data = {DOMAIN: {entry.entry_id: {"store": MagicMock()}}}

        await async_unload_entry(hass, entry)

        assert entry.entry_id not in hass.data[DOMAIN]

    async def test_keeps_entry_data_on_failure(self) -> None:
        hass = _make_hass()
        hass.config_entries.async_unload_platforms = AsyncMock(
            return_value=False
        )
        entry = _make_entry()
        hass.data = {DOMAIN: {entry.entry_id: {"store": MagicMock()}}}

        result = await async_unload_entry(hass, entry)

        assert result is False
        assert entry.entry_id in hass.data[DOMAIN]

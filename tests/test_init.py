from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.eink_dashboard import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
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

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


def _make_entry(entry_id: str = "entry1") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
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
        assert len(configs) == 2
        assert configs[0].url_path == "/eink_dashboard/frontend"
        assert configs[0].path.endswith("frontend")
        assert configs[1].url_path == "/eink_dashboard/fonts"
        assert configs[1].path.endswith("fonts")

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
            entry, ["image"]
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


class TestAsyncUnloadEntry:
    async def test_unloads_platforms(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        hass.data = {DOMAIN: {entry.entry_id: {"store": MagicMock()}}}

        result = await async_unload_entry(hass, entry)

        hass.config_entries.async_unload_platforms.assert_called_once_with(
            entry, ["image"]
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

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.eink_dashboard.store import (
    EinkDashboardStore,
)


def _make_hass() -> MagicMock:
    return MagicMock()


class TestEinkDashboardStore:
    async def test_load_returns_empty_list_when_no_data(
        self,
    ) -> None:
        hass = _make_hass()
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)

        with patch(
            "custom_components.eink_dashboard.store.Store",
            return_value=mock_store,
        ):
            store = EinkDashboardStore(hass, "entry1")
            result = await store.async_load()

        assert result == []

    async def test_load_returns_stored_widgets(
        self,
    ) -> None:
        hass = _make_hass()
        widgets = [{"type": "heading", "x": 10, "y": 10, "heading": "Hi"}]
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=widgets)

        with patch(
            "custom_components.eink_dashboard.store.Store",
            return_value=mock_store,
        ):
            store = EinkDashboardStore(hass, "entry1")
            result = await store.async_load()

        assert result == widgets

    async def test_save_delegates_to_ha_store(
        self,
    ) -> None:
        hass = _make_hass()
        widgets = [{"type": "heading", "x": 0, "y": 0}]
        mock_store = MagicMock()
        mock_store.async_save = AsyncMock()

        with patch(
            "custom_components.eink_dashboard.store.Store",
            return_value=mock_store,
        ):
            store = EinkDashboardStore(hass, "entry1")
            await store.async_save(widgets)

        mock_store.async_save.assert_called_once_with(widgets)

    async def test_store_key_includes_entry_id(
        self,
    ) -> None:
        hass = _make_hass()
        with patch(
            "custom_components.eink_dashboard.store.Store",
        ) as mock_cls:
            EinkDashboardStore(hass, "my_entry")
            mock_cls.assert_called_once()
            assert mock_cls.call_args.args[1] == 1
            assert mock_cls.call_args.args[2] == "eink_dashboard.my_entry"

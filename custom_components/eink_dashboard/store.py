"""Persistent storage for the widget list via HA's Store helper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_STORAGE_VERSION = 1


class EinkDashboardStore:
    """Wraps HA's Store to persist and load the widget list."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise storage keyed by config entry ID."""
        self._store: Store[list[dict[str, Any]]] = Store(
            hass, _STORAGE_VERSION, f"eink_dashboard.{entry_id}"
        )

    async def async_load(self) -> list[dict[str, Any]]:
        """Load widgets from storage, returning an empty list if absent."""
        data = await self._store.async_load()
        if data is None:
            return []
        return data

    async def async_save(self, widgets: list[dict[str, Any]]) -> None:
        """Persist the widget list to storage."""
        await self._store.async_save(widgets)

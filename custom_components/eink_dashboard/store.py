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

"""Persistent storage for the widget list via HA's Store helper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_STORAGE_VERSION = 2

# Widget types whose legacy ``bold_value`` boolean flag maps to a bold
# weight on one or more font roles.  Consulted once, by the v1 -> v2
# migration; the flag itself is gone from the renderers.
_BOLD_VALUE_ROLES: dict[str, tuple[str, ...]] = {
    "entity": ("value",),
    "tile": ("secondary",),
    "calendar": ("value",),
    "entities": ("value",),
    "waste_schedule": ("value", "secondary"),
    "gauge": ("value",),
    "device_battery": ("label",),
    "graph": ("value",),
    "sensor": ("value",),
}


def _migrate_bold_value(
    widgets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fold the legacy ``bold_value`` flag into each widget's ``fonts``.

    ``bold_value`` was a boolean that made one or more text roles bold.
    It is superseded by the per-role ``fonts.<role>.weight`` override,
    so a stored ``true`` becomes an explicit ``"bold"`` weight for the
    roles that flag used to affect, and the key is dropped either way.
    An existing explicit weight is left untouched, so a widget that
    already carries both keeps the more specific setting.

    Args:
        widgets: Widget list as persisted at storage version 1.

    Returns:
        The same list, with ``bold_value`` removed and its effect folded
        into ``fonts``.
    """
    for widget in widgets:
        if not isinstance(widget, dict) or "bold_value" not in widget:
            continue
        is_bold = bool(widget.pop("bold_value"))
        roles = _BOLD_VALUE_ROLES.get(str(widget.get("type")), ())
        # Nothing to preserve for a false flag or a type that never
        # honoured the flag (e.g. separator), so leave no empty
        # ``fonts`` object behind.
        if not is_bold or not roles:
            continue
        fonts = widget.get("fonts")
        if not isinstance(fonts, dict):
            fonts = {}
            widget["fonts"] = fonts
        for role in roles:
            spec = fonts.get(role)
            if not isinstance(spec, dict):
                spec = {}
                fonts[role] = spec
            spec.setdefault("weight", "bold")
    return widgets


class _WidgetStore(Store[list[dict[str, Any]]]):
    """Store for the widget list, with schema migration.

    Home Assistant calls ``_async_migrate_func`` when the persisted
    version is older than the current one, then writes the result back.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Migrate a stored widget list to the current version.

        Args:
            old_major_version: Version the data was stored at.
            old_minor_version: Minor version the data was stored at.
            old_data: The persisted widget list.

        Returns:
            The widget list at the current storage version.
        """
        if old_major_version < 2:
            return _migrate_bold_value(old_data)
        return old_data


class EinkDashboardStore:
    """Wraps HA's Store to persist and load the widget list."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise storage keyed by config entry ID."""
        self._store: Store[list[dict[str, Any]]] = _WidgetStore(
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

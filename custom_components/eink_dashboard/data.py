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

"""Typed runtime data stored on each config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .battery_sensor import EinkDashboardBatterySensor
    from .const import Widget
    from .image import EinkDashboardImage
    from .store import EinkDashboardStore


@dataclass
class EinkDashboardRuntimeData:
    """Per-entry runtime state, held on ``ConfigEntry.runtime_data``.

    ``entity`` and ``battery_sensor`` start as ``None`` because the
    image and sensor platforms populate them after
    ``async_setup_entry`` has already assigned this object to the
    entry; platform load order is not guaranteed.
    """

    store: EinkDashboardStore
    """Persists and loads the widget list."""
    widgets: list[Widget]
    """Current widget list, loaded from ``store`` at setup."""
    entity: EinkDashboardImage | None = None
    """The dashboard image entity, set by the image platform."""
    battery_sensor: EinkDashboardBatterySensor | None = None
    """The battery sensor entity, set by the sensor platform."""


type EinkDashboardConfigEntry = ConfigEntry[EinkDashboardRuntimeData]
"""A config entry carrying this integration's typed runtime data."""


def get_loaded_entry(
    hass: HomeAssistant,
    entry_id: str,
) -> EinkDashboardConfigEntry | None:
    """Look up a config entry and verify it has finished loading.

    ``runtime_data`` has no default on ``ConfigEntry`` and is only
    assigned once ``async_setup_entry`` has run, so ``hasattr`` is
    the canonical way to check whether an entry is loaded (mirrors
    the check Home Assistant core uses at unload time).

    Args:
        hass: Home Assistant instance.
        entry_id: The config entry ID to look up.

    Returns:
        The typed config entry, or ``None`` if the entry does not
        exist or has not finished loading.
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or not hasattr(entry, "runtime_data"):
        return None
    return cast("EinkDashboardConfigEntry", entry)

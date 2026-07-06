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

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from custom_components.eink_dashboard.store import (
    EinkDashboardStore,
)


class TestEinkDashboardStore:
    async def test_load_returns_empty_list_when_no_data(
        self,
        hass: HomeAssistant,
        hass_storage: dict,  # activates the in-memory Store interceptor
    ) -> None:
        # No pre-populated storage entry — async_load should return [].
        store = EinkDashboardStore(hass, "entry1")
        result = await store.async_load()

        assert result == []

    async def test_load_returns_stored_widgets(
        self,
        hass: HomeAssistant,
        hass_storage: dict,
    ) -> None:
        # Pre-populate storage so async_load returns the existing widget list.
        widgets = [{"type": "heading", "x": 10, "y": 10, "heading": "Hi"}]
        hass_storage["eink_dashboard.entry1"] = {
            "version": 1,
            "minor_version": 1,
            "data": widgets,
        }

        store = EinkDashboardStore(hass, "entry1")
        result = await store.async_load()

        assert result == widgets

    async def test_save_delegates_to_ha_store(
        self,
        hass: HomeAssistant,
        hass_storage: dict,
    ) -> None:
        # async_save should write through to hass_storage under the right key.
        widgets = [{"type": "heading", "x": 0, "y": 0}]

        store = EinkDashboardStore(hass, "entry1")
        await store.async_save(widgets)

        assert hass_storage["eink_dashboard.entry1"]["data"] == widgets
        assert hass_storage["eink_dashboard.entry1"]["version"] == 1

    async def test_round_trip_save_then_load(
        self,
        hass: HomeAssistant,
        hass_storage: dict,  # activates the in-memory Store interceptor
    ) -> None:
        # Data saved by one store instance must be returned by a second
        # instance for the same entry ID.
        widgets = [
            {"type": "separator", "x": 0, "y": 0},
            {"type": "heading", "x": 0, "y": 60, "heading": "Test"},
        ]

        await EinkDashboardStore(hass, "entry_rt").async_save(widgets)
        result = await EinkDashboardStore(hass, "entry_rt").async_load()

        assert result == widgets

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
    _migrate_bold_value,
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
        assert hass_storage["eink_dashboard.entry1"]["version"] == 2

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


class TestMigrateBoldValue:
    def test_true_becomes_bold_weight_on_value_role(self) -> None:
        # A stored bold_value=true becomes an explicit bold weight on
        # the role that flag used to affect, and the key is dropped.
        widgets = [{"type": "entity", "bold_value": True}]

        result = _migrate_bold_value(widgets)

        assert result == [
            {"type": "entity", "fonts": {"value": {"weight": "bold"}}}
        ]

    def test_waste_schedule_bolds_both_date_roles(self) -> None:
        # waste_schedule's flag bolded the value in list layout and the
        # secondary line in card layout, so both roles are migrated.
        widgets = [{"type": "waste_schedule", "bold_value": True}]

        result = _migrate_bold_value(widgets)

        assert result[0]["fonts"] == {
            "value": {"weight": "bold"},
            "secondary": {"weight": "bold"},
        }

    def test_false_is_dropped_without_adding_fonts(self) -> None:
        # A stored bold_value=false has no effect to preserve; the key
        # is still removed so the renderers never see it again.
        widgets = [{"type": "entity", "bold_value": False}]

        result = _migrate_bold_value(widgets)

        assert result == [{"type": "entity"}]

    def test_explicit_weight_wins(self) -> None:
        # A widget carrying both an explicit weight and the flag keeps
        # the more specific setting.
        widgets = [
            {
                "type": "entity",
                "bold_value": True,
                "fonts": {"value": {"weight": "regular", "size": 40}},
            }
        ]

        result = _migrate_bold_value(widgets)

        assert result[0]["fonts"] == {
            "value": {"weight": "regular", "size": 40}
        }

    def test_unknown_type_and_odd_entries_are_safe(self) -> None:
        # Widget types with no role mapping, non-dict entries, and a
        # malformed fonts value must not raise.
        widgets = [
            {"type": "separator", "bold_value": True},
            {"type": "entity", "bold_value": True, "fonts": "nonsense"},
            "not a dict",
        ]

        result = _migrate_bold_value(widgets)

        assert result[0] == {"type": "separator"}
        assert result[1]["fonts"] == {"value": {"weight": "bold"}}
        assert result[2] == "not a dict"


class TestStoreMigration:
    async def test_v1_storage_is_migrated_on_load(
        self, hass: HomeAssistant, hass_storage: dict
    ) -> None:
        # Widgets persisted at version 1 lose bold_value and gain the
        # equivalent fonts weight.
        hass_storage["eink_dashboard.entry1"] = {
            "version": 1,
            "minor_version": 1,
            "data": [{"type": "entity", "bold_value": True}],
        }

        result = await EinkDashboardStore(hass, "entry1").async_load()

        assert result == [
            {"type": "entity", "fonts": {"value": {"weight": "bold"}}}
        ]

    async def test_migrated_data_is_written_back_at_v2(
        self, hass: HomeAssistant, hass_storage: dict
    ) -> None:
        # Home Assistant persists the migrated result, so the widget
        # list is only rewritten once.
        hass_storage["eink_dashboard.entry1"] = {
            "version": 1,
            "minor_version": 1,
            "data": [{"type": "entity", "bold_value": True}],
        }

        await EinkDashboardStore(hass, "entry1").async_load()

        stored = hass_storage["eink_dashboard.entry1"]
        assert stored["version"] == 2
        assert "bold_value" not in stored["data"][0]

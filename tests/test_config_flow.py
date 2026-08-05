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

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import voluptuous as vol
import yaml  # via homeassistant -> pyyaml
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eink_dashboard.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.eink_dashboard.config_flow import (
        EinkDashboardConfigFlow,
        EinkDashboardOptionsFlow,
    )

_USER_INPUT_KINDLE = {
    "name": "Kitchen",
    "device_model": "kindle_pw",
    "orientation": "portrait",
    "update_interval": 60,
}

_USER_INPUT_TRMNL = {
    "name": "Hallway",
    "device_model": "trmnl_og",
    "orientation": "landscape",
    "update_interval": 60,
}

_USER_INPUT_CUSTOM = {
    "name": "Custom Display",
    "device_model": "custom",
    "orientation": "portrait",
    "update_interval": 60,
}


async def _make_config_flow(hass: HomeAssistant) -> EinkDashboardConfigFlow:
    """Start a real config flow and return the in-progress instance."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # Reach into _progress to get the raw FlowHandler so tests
    # can call async_step_*() directly.  See the *_full_flow_*
    # tests for the async_configure() path that exercises
    # async_finish_flow and real entry creation.
    return hass.config_entries.flow._progress[result["flow_id"]]


async def _make_options_flow(
    hass: HomeAssistant,
    options: dict[str, Any],
    **entry_kwargs: Any,
) -> EinkDashboardOptionsFlow:
    """Create a MockConfigEntry and return its in-progress options flow."""
    entry = MockConfigEntry(domain=DOMAIN, options=options, **entry_kwargs)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    # Reach into _progress to get the raw FlowHandler so tests
    # can call async_step_*() directly.  See the
    # *_persists_entry_options tests for the async_configure()
    # path that exercises async_finish_flow and real
    # async_update_entry.
    return hass.config_entries.options._progress[result["flow_id"]]


class TestEinkDashboardConfigFlow:
    async def test_step_user_shows_form(self, hass: HomeAssistant) -> None:
        # Calling user step with no input returns the setup form.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["data_schema"] is not None

    async def test_kindle_creates_entry(self, hass: HomeAssistant) -> None:
        # Kindle skips screen_portion and creates entry directly.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(_USER_INPUT_KINDLE)

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Kitchen"
        assert result["data"] == {}
        opts = result["options"]
        assert opts["device_model"] == "kindle_pw"
        assert opts["orientation"] == "portrait"
        assert opts["width"] == 758
        assert opts["height"] == 1024
        assert opts["rotation"] == 0
        assert opts["optimize"] is True
        assert opts["display_levels"] == 16
        assert opts["dither_algorithm"] == "floyd_steinberg"
        assert opts["update_interval"] == 60
        assert opts["webhook_urls"] == []

    async def test_kindle_landscape_rotation(
        self, hass: HomeAssistant
    ) -> None:
        # Landscape orientation uses rotated dimensions and rotation=90.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "orientation": "landscape"},
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        opts = result["options"]
        assert opts["width"] == 1024
        assert opts["height"] == 758
        assert opts["rotation"] == 90

    async def test_kindle_pw4_dimensions(self, hass: HomeAssistant) -> None:
        # Different device preset produces correct canvas size.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "device_model": "kindle_pw4"},
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        opts = result["options"]
        assert opts["width"] == 1072
        assert opts["height"] == 1448

    async def test_user_with_area(self, hass: HomeAssistant) -> None:
        # Area selection is preserved in the created entry options.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "area": "kitchen"},
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["options"]["area_id"] == "kitchen"

    async def test_user_without_area(self, hass: HomeAssistant) -> None:
        # Omitting area means area_id is absent from the entry options.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(_USER_INPUT_KINDLE)

        assert "area_id" not in result["options"]

    async def test_reterminal_e1001_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        # reTerminal E1001 preset must have optimize=False to avoid
        # double-dithering with HA Core's OpenDisplay integration.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(
            {
                "name": "Office",
                "device_model": "reterminal_e1001",
                "orientation": "landscape",
                "update_interval": 60,
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        opts = result["options"]
        assert opts["optimize"] is False
        assert opts["display_levels"] == 4
        # Native landscape device in landscape orientation: no rotation.
        assert opts["width"] == 800
        assert opts["height"] == 480
        assert opts["rotation"] == 0

    async def test_reterminal_e1003_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        # reTerminal E1003 preset must have optimize=False to avoid
        # double-dithering with HA Core's OpenDisplay integration.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(
            {
                "name": "Office",
                "device_model": "reterminal_e1003",
                "orientation": "portrait",
                "update_interval": 60,
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        opts = result["options"]
        assert opts["optimize"] is False
        assert opts["display_levels"] == 16
        # Panel is native landscape (OpenDisplay firmware), so portrait
        # orientation is achieved by rotating the rendered canvas.
        assert opts["width"] == 1404
        assert opts["height"] == 1872
        assert opts["rotation"] == 90

    async def test_reterminal_e1003_landscape_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        # Native landscape device in landscape orientation (the
        # default): no rotation, and dimensions match the panel's
        # native landscape buffer.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(
            {
                "name": "Office",
                "device_model": "reterminal_e1003",
                "orientation": "landscape",
                "update_interval": 60,
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        opts = result["options"]
        assert opts["width"] == 1872
        assert opts["height"] == 1404
        assert opts["rotation"] == 0

    async def test_screen_portion_shows_form_for_trmnl(
        self, hass: HomeAssistant
    ) -> None:
        # TRMNL devices get a screen_portion form after the user step.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(_USER_INPUT_TRMNL)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "screen_portion"

    async def test_screen_portion_full_stores_portion(
        self, hass: HomeAssistant
    ) -> None:
        # "full" preserves native dimensions and stores screen_portion.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})

        assert flow._data["width"] == 800
        assert flow._data["height"] == 480
        assert flow._data["screen_portion"] == "full"

    async def test_screen_portion_half_halves_width(
        self, hass: HomeAssistant
    ) -> None:
        # "half" halves the width while keeping the full height.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "half"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "trmnl_setup"
        assert flow._data["width"] == 400
        assert flow._data["height"] == 480
        assert flow._data["screen_portion"] == "half"

    async def test_screen_portion_quarter_halves_both(
        self, hass: HomeAssistant
    ) -> None:
        # "quarter" halves both width and height.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "quarter"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "trmnl_setup"
        assert flow._data["width"] == 400
        assert flow._data["height"] == 240
        assert flow._data["screen_portion"] == "quarter"

    async def test_screen_portion_custom_advances_to_resolution(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Selecting "custom" routes to the custom_resolution step.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "custom"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_resolution"

    async def test_trmnl_advances_to_setup(self, hass: HomeAssistant) -> None:
        # TRMNL flow goes user → screen_portion → trmnl_setup.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_og_dimensions(self, hass: HomeAssistant) -> None:
        # TRMNL OG preset produces 800×480 with no rotation.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})

        assert flow._data["width"] == 800
        assert flow._data["height"] == 480
        assert flow._data["rotation"] == 0
        assert flow._data["display_levels"] == 2

    async def test_trmnl_portrait_rotation(self, hass: HomeAssistant) -> None:
        # TRMNL in portrait orientation swaps dimensions and sets
        # rotation=90.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(
            {**_USER_INPUT_TRMNL, "orientation": "portrait"},
        )
        await flow.async_step_screen_portion({"screen_portion": "full"})

        assert flow._data["width"] == 480
        assert flow._data["height"] == 800
        assert flow._data["rotation"] == 90

    async def test_trmnl_setup_shows_form(self, hass: HomeAssistant) -> None:
        # async_step_trmnl_setup(None) returns the form without submitting.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        result = await flow.async_step_trmnl_setup(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_setup_advances_to_webhook(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting the trmnl_setup step opens the webhook entry form.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        result = await flow.async_step_trmnl_setup({})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "trmnl_webhook"

    async def test_trmnl_screen_portion_full_advances_to_setup(
        self, hass: HomeAssistant
    ) -> None:
        # Selecting "full" screen portion for a TRMNL device goes to setup.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_webhook_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        # Full TRMNL flow produces a correctly-shaped config entry.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {
                "webhook_url": "https://trmnl.com/api/custom_plugins/abc",
                "label": "Hallway TRMNL",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Hallway"
        assert result["data"] == {}
        opts = result["options"]
        assert opts["device_model"] == "trmnl_og"
        assert opts["width"] == 800
        assert opts["height"] == 480
        assert opts["webhook_urls"] == [
            {
                "name": "Hallway TRMNL",
                "url": "https://trmnl.com/api/custom_plugins/abc",
            }
        ]

    async def test_trmnl_webhook_defaults_label_to_device_name(
        self, hass: HomeAssistant
    ) -> None:
        # Omitting the label defaults the webhook name to the device name.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {"webhook_url": "https://trmnl.com/api/custom_plugins/abc"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["options"]["webhook_urls"][0]["name"] == "Hallway"

    async def test_trmnl_webhook_rejects_invalid_url(
        self, hass: HomeAssistant
    ) -> None:
        # A non-URL value triggers an inline validation error.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {"webhook_url": "not-a-url"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"webhook_url": "invalid_url"}

    async def test_custom_advances_to_resolution(
        self, hass: HomeAssistant
    ) -> None:
        # Selecting "custom" device routes to custom_resolution step.
        flow = await _make_config_flow(hass)
        result = await flow.async_step_user(_USER_INPUT_CUSTOM)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_resolution"

    async def test_custom_resolution_shows_form(
        self, hass: HomeAssistant
    ) -> None:
        # Calling custom_resolution with no input returns the form.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        result = await flow.async_step_custom_resolution(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_resolution"

    async def test_custom_resolution_advances_to_menu(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Submitting custom dimensions shows the push-target menu.
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        result = await flow.async_step_custom_resolution(
            {"width": 600, "height": 800},
        )

        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "push_target"
        assert "pull_only" in result["menu_options"]
        assert "trmnl_setup" in result["menu_options"]

    async def test_custom_pull_only_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        await flow.async_step_custom_resolution(
            {"width": 600, "height": 800},
        )
        result = await flow.async_step_pull_only(None)

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Custom Display"
        opts = result["options"]
        assert opts["device_model"] == "custom"
        assert opts["width"] == 600
        assert opts["height"] == 800
        assert opts["rotation"] == 0
        assert opts["optimize"] is False
        assert opts["webhook_urls"] == []

    async def test_custom_trmnl_webhook_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        flow = await _make_config_flow(hass)
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        await flow.async_step_custom_resolution({"width": 600, "height": 800})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/xyz",
                "label": "Custom TRMNL",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Custom Display"
        opts = result["options"]
        assert opts["device_model"] == "custom"
        assert opts["width"] == 600
        assert opts["height"] == 800
        assert opts["rotation"] == 0
        assert opts["optimize"] is False
        assert opts["webhook_urls"] == [
            {
                "name": "Custom TRMNL",
                "url": "https://usetrmnl.com/api/custom_plugins/xyz",
            }
        ]

    async def test_kindle_full_flow_creates_config_entry(
        self, hass: HomeAssistant
    ) -> None:
        # Full flow via async_configure() creates a real
        # ConfigEntry registered in hass.config_entries.
        with patch(
            "custom_components.eink_dashboard.async_setup_entry",
            return_value=True,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input=_USER_INPUT_KINDLE,
            )
            await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        entries = hass.config_entries.async_entries(DOMAIN)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.title == "Kitchen"
        assert entry.options["device_model"] == "kindle_pw"
        assert entry.options["width"] == 758
        assert entry.options["height"] == 1024


class TestEinkDashboardOptionsFlow:
    async def test_init_menu_no_webhooks(self, hass: HomeAssistant) -> None:
        # Init menu omits remove_webhook when no webhooks exist.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        result = await flow.async_step_init(None)

        assert result["type"] is FlowResultType.MENU
        assert "device_settings" in result["menu_options"]
        assert "display_settings" in result["menu_options"]
        assert "add_webhook" in result["menu_options"]
        assert "remove_webhook" not in result["menu_options"]
        assert "settings" not in result["menu_options"]

    async def test_init_menu_with_webhooks(self, hass: HomeAssistant) -> None:
        # Init menu includes remove_webhook when webhooks exist.
        flow = await _make_options_flow(
            hass,
            {
                "webhook_urls": [
                    {"name": "Test", "url": "https://example.com"},
                ],
            },
        )
        result = await flow.async_step_init(None)

        assert result["type"] is FlowResultType.MENU
        assert "device_settings" in result["menu_options"]
        assert "display_settings" in result["menu_options"]
        assert "remove_webhook" in result["menu_options"]

    async def test_add_webhook_shows_form(self, hass: HomeAssistant) -> None:
        # Calling add_webhook with no input returns the form.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        result = await flow.async_step_add_webhook(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "add_webhook"

    async def test_add_webhook_appends_to_list(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting a valid webhook URL appends it to the list.
        flow = await _make_options_flow(
            hass, {"width": 800, "height": 480, "webhook_urls": []}
        )
        result = await flow.async_step_add_webhook(
            {
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/abc",
                "label": "Kitchen TRMNL",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["webhook_urls"] == [
            {
                "name": "Kitchen TRMNL",
                "url": "https://usetrmnl.com/api/custom_plugins/abc",
            }
        ]

    async def test_add_webhook_defaults_label_to_entry_title(
        self, hass: HomeAssistant
    ) -> None:
        # Omitting label defaults webhook name to the entry title.
        flow = await _make_options_flow(
            hass, {"webhook_urls": []}, title="My Device"
        )
        result = await flow.async_step_add_webhook(
            {"webhook_url": "https://usetrmnl.com/api/custom_plugins/abc"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["webhook_urls"][0]["name"] == "My Device"

    async def test_add_webhook_preserves_existing(
        self, hass: HomeAssistant
    ) -> None:
        # Adding a second webhook preserves the existing one.
        existing = {
            "name": "Existing",
            "url": "https://example.com/1",
        }
        flow = await _make_options_flow(hass, {"webhook_urls": [existing]})
        result = await flow.async_step_add_webhook(
            {
                "webhook_url": "https://example.com/2",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert len(result["data"]["webhook_urls"]) == 2

    async def test_add_webhook_rejects_duplicate_url(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Duplicate webhook URL shows an already_configured error.
        existing = {
            "name": "Existing",
            "url": "https://example.com/1",
        }
        flow = await _make_options_flow(hass, {"webhook_urls": [existing]})
        result = await flow.async_step_add_webhook(
            {
                "webhook_url": "https://example.com/1",
            }
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {
            "webhook_url": "already_configured",
        }

    async def test_add_webhook_rejects_invalid_url(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Non-HTTP URL is rejected with an invalid_url error.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        result = await flow.async_step_add_webhook(
            {"webhook_url": "ftp://invalid"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"webhook_url": "invalid_url"}

    async def test_remove_webhook_shows_form(
        self, hass: HomeAssistant
    ) -> None:
        # Calling remove_webhook with no input returns the form.
        flow = await _make_options_flow(
            hass,
            {
                "webhook_urls": [
                    {"name": "Test", "url": "https://example.com"},
                ],
            },
        )
        result = await flow.async_step_remove_webhook(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "remove_webhook"

    async def test_remove_webhook_removes_selected(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Selecting a webhook URL removes it from the list.
        webhooks = [
            {"name": "Keep", "url": "https://example.com/1"},
            {"name": "Remove", "url": "https://example.com/2"},
        ]
        flow = await _make_options_flow(hass, {"webhook_urls": webhooks})
        result = await flow.async_step_remove_webhook(
            {"webhook_url": "https://example.com/2"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        remaining = result["data"]["webhook_urls"]
        assert len(remaining) == 1
        assert remaining[0]["name"] == "Keep"

    async def test_display_settings_shows_form(
        self, hass: HomeAssistant
    ) -> None:
        # Calling display_settings with no input returns the form.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "display_settings"

    async def test_display_settings_saves_values(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting update_interval merges all values into the stored
        # options. advanced_section is optional, so omitting it from
        # the submission is fine.
        flow = await _make_options_flow(
            hass,
            {
                "width": 800,
                "height": 480,
                "update_interval": 60,
                "webhook_urls": [],
            },
        )
        result = await flow.async_step_display_settings(
            {"update_interval": 120}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["update_interval"] == 120
        assert result["data"]["width"] == 800
        assert result["data"]["webhook_urls"] == []

    async def test_display_settings_saves_optimize_values(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting optimize settings via the advanced_section persists
        # them. The eink-only fields (dither_algorithm, exposure,
        # saturation) are only present in the section's schema once
        # optimize is already enabled in the stored options.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": True}
        )
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "optimize": True,
                "display_levels": "2",
                "advanced_section": {
                    "dither_algorithm": "floyd_steinberg",
                    "exposure": "1.5",
                    "saturation": "0.8",
                },
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["optimize"] is True
        assert result["data"]["display_levels"] == 2
        assert result["data"]["exposure"] == 1.5
        assert result["data"]["saturation"] == 0.8

    async def test_display_settings_hides_exposure_at_256_levels(
        self,
        hass: HomeAssistant,
    ) -> None:
        # When display_levels==256 is saved in opts, exposure/saturation
        # are excluded from the advanced_section schema because
        # dither_image() is not called on the 256-level passthrough
        # path. Submitting those keys raises vol.Invalid.
        flow = await _make_options_flow(
            hass,
            {
                "update_interval": 60,
                "optimize": True,
                "display_levels": 256,
            },
        )
        with pytest.raises(vol.Invalid):
            await flow.async_step_display_settings(
                {
                    "update_interval": 60,
                    "optimize": True,
                    "display_levels": 256,
                    "advanced_section": {"exposure": "1.5"},
                }
            )

    async def test_display_settings_rejects_invalid_display_levels(
        self,
        hass: HomeAssistant,
    ) -> None:
        # An invalid display_levels value raises vol.Invalid.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        with pytest.raises(vol.Invalid):
            await flow.async_step_display_settings(
                {"update_interval": 60, "display_levels": 7}
            )

    async def test_display_settings_saves_font_dir(
        self,
        hass: HomeAssistant,
        tmp_path,
    ) -> None:
        # A valid existing directory path submitted via the Advanced
        # section is stored as a top-level font_dir option.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "advanced_section": {"font_dir": str(tmp_path)},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["font_dir"] == str(tmp_path)

    async def test_display_settings_empty_font_dir(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Leaving font_dir empty is accepted; no directory is required.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "advanced_section": {"font_dir": ""},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["font_dir"] == ""

    async def test_display_settings_rejects_missing_font_dir(
        self,
        hass: HomeAssistant,
    ) -> None:
        # A font_dir path that does not exist on disk returns the form
        # again with a base-level font_dir_not_found error instead of
        # saving. The error is reported as "base" (not "font_dir")
        # because HA's section renderer does not forward field-level
        # errors into nested section forms.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "advanced_section": {"font_dir": "/no/such/directory/at/all"},
            }
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "display_settings"
        assert result["errors"] == {"base": "font_dir_not_found"}

    async def test_display_settings_saves_use_system_fonts_on(
        self, hass: HomeAssistant
    ) -> None:
        # Enabling use_system_fonts persists it as a top-level option.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(
            {"update_interval": 60, "use_system_fonts": True}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["use_system_fonts"] is True

    async def test_display_settings_default_use_system_fonts_is_false(
        self, hass: HomeAssistant
    ) -> None:
        # Omitting use_system_fonts on a fresh entry defaults to False
        # so rendering stays reproducible across environments.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(None)

        markers = {
            k.schema: k
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert markers["use_system_fonts"].default() is False

    async def test_display_settings_use_system_fonts_before_font_dir(
        self, hass: HomeAssistant
    ) -> None:
        # use_system_fonts is a top-level field shown above the
        # Advanced section (where font_dir now lives), so it appears
        # earlier in the form.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(None)

        field_order = [
            k.schema
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        ]
        assert field_order.index("use_system_fonts") < field_order.index(
            "advanced_section"
        )

    async def test_display_settings_shows_optimize_note_for_reterminal(
        self,
        hass: HomeAssistant,
    ) -> None:
        # OpenDisplay devices show a note explaining HA Core dithers.
        flow = await _make_options_flow(
            hass,
            {"update_interval": 60, "device_model": "reterminal_e1001"},
        )
        result = await flow.async_step_display_settings(None)

        assert result["type"] is FlowResultType.FORM
        placeholders = result.get("description_placeholders", {})
        assert "double processing" in placeholders.get("optimize_note", "")

    async def test_display_settings_no_optimize_note_for_kindle(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Non-OpenDisplay devices have no optimize note.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "device_model": "kindle_pw"}
        )
        result = await flow.async_step_display_settings(None)

        assert result["type"] is FlowResultType.FORM
        placeholders = result.get("description_placeholders", {})
        assert placeholders.get("optimize_note", "") == ""

    async def test_display_settings_no_optimize_note_for_legacy_entry(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Legacy entries without a device_model key must not show the
        # note.
        flow = await _make_options_flow(hass, {"update_interval": 60})
        result = await flow.async_step_display_settings(None)

        assert result["type"] is FlowResultType.FORM
        placeholders = result.get("description_placeholders", {})
        assert placeholders.get("optimize_note", "") == ""

    async def test_display_settings_has_advanced_section_when_optimize_on(
        self, hass: HomeAssistant
    ) -> None:
        # The advanced_section's eink-only fields (dither_algorithm
        # etc.) join font_dir once optimize is already enabled in the
        # stored options.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": True}
        )
        result = await flow.async_step_display_settings(None)

        top_level = {
            k.schema: v
            for k, v in result["data_schema"].schema.items()
            if hasattr(k, "schema")
        }
        assert "advanced_section" in top_level
        section_field_names = {
            k.schema
            for k in top_level["advanced_section"].schema.schema
            if hasattr(k, "schema")
        }
        assert "dither_algorithm" in section_field_names
        assert "font_dir" in section_field_names

    async def test_display_settings_hides_eink_fields_when_off(
        self, hass: HomeAssistant
    ) -> None:
        # The advanced_section is always present (font_dir lives there
        # and is unrelated to optimize), but its eink-only fields
        # (dither/palette/exposure/saturation) are omitted when
        # optimize is disabled, since they have no effect until
        # optimize is turned on.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": False}
        )
        result = await flow.async_step_display_settings(None)

        top_level = {
            k.schema: v
            for k, v in result["data_schema"].schema.items()
            if hasattr(k, "schema")
        }
        assert "advanced_section" in top_level
        section_field_names = {
            k.schema
            for k in top_level["advanced_section"].schema.schema
            if hasattr(k, "schema")
        }
        assert section_field_names == {"font_dir"}

    async def test_display_settings_has_top_level_display_levels(
        self, hass: HomeAssistant
    ) -> None:
        # display_levels affects widget rendering regardless of
        # optimize, so it is a top-level field, shown even when
        # optimize (and therefore advanced_section) is off.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": False}
        )
        result = await flow.async_step_display_settings(None)

        field_names = {
            k.schema
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert "display_levels" in field_names

    async def test_display_settings_defaults_to_device_preset_levels(
        self, hass: HomeAssistant
    ) -> None:
        # When display_levels has never been saved, the field default
        # should come from the device's preset instead of the global
        # DEFAULT_DISPLAY_LEVELS constant, so devices like the
        # reterminal_e1002 (256 levels) show their own capability
        # pre-selected rather than an unrelated fallback.
        flow = await _make_options_flow(
            hass,
            {
                "update_interval": 60,
                "device_model": "reterminal_e1002",
            },
        )
        result = await flow.async_step_display_settings(None)

        markers = {
            k.schema: k
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert markers["display_levels"].default() == "256"

    async def test_display_settings_prefers_stored_levels_over_preset(
        self, hass: HomeAssistant
    ) -> None:
        # A previously saved display_levels value always wins over the
        # device preset's default.
        flow = await _make_options_flow(
            hass,
            {
                "update_interval": 60,
                "device_model": "reterminal_e1002",
                "display_levels": 16,
            },
        )
        result = await flow.async_step_display_settings(None)

        markers = {
            k.schema: k
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert markers["display_levels"].default() == "16"

    async def test_display_settings_saves_optimize_toggle_on(
        self, hass: HomeAssistant
    ) -> None:
        # Turning optimize on in the same submission where it was
        # previously off must succeed even though the eink-only
        # fields are absent from the schema built from the stale
        # stored value (only font_dir was available to submit).
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": False}
        )
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "optimize": True,
                "display_levels": "16",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["optimize"] is True
        assert "dither_algorithm" not in result["data"]
        assert "exposure" not in result["data"]
        assert "saturation" not in result["data"]

    async def test_display_settings_preserves_advanced_when_optimize_off(
        self, hass: HomeAssistant
    ) -> None:
        # Saving with optimize off omits the eink-only fields from the
        # advanced_section schema, so previously-stored advanced
        # values must survive the {**opts, **validated, **section}
        # merge rather than being dropped or reset to defaults.
        flow = await _make_options_flow(
            hass,
            {
                "update_interval": 60,
                "optimize": False,
                "dither_algorithm": "atkinson",
                "exposure": 2.0,
                "saturation": 1.5,
            },
        )
        result = await flow.async_step_display_settings(
            {"update_interval": 120, "display_levels": "16"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["update_interval"] == 120
        assert result["data"]["dither_algorithm"] == "atkinson"
        assert result["data"]["exposure"] == 2.0
        assert result["data"]["saturation"] == 1.5

    async def test_display_settings_saves_dither_algorithm(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting dither_algorithm via advanced_section persists it.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": True}
        )
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "optimize": True,
                "display_levels": "16",
                "advanced_section": {
                    "dither_algorithm": "atkinson",
                    "exposure": "1.0",
                    "saturation": "1.0",
                },
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["dither_algorithm"] == "atkinson"

    async def test_display_settings_default_dither_algorithm(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Legacy entries without dither_algorithm default to
        # floyd_steinberg.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": True}
        )
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "optimize": True,
                "advanced_section": {},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["dither_algorithm"] == "floyd_steinberg"

    async def test_display_settings_saves_measured_palette(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting measured_palette via advanced_section persists it.
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": True}
        )
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "optimize": True,
                "display_levels": "16",
                "advanced_section": {
                    "dither_algorithm": "floyd_steinberg",
                    "measured_palette": "spectra_7_3_6color",
                    "exposure": "1.0",
                    "saturation": "1.0",
                },
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["measured_palette"] == "spectra_7_3_6color"

    async def test_display_settings_default_measured_palette(
        self, hass: HomeAssistant
    ) -> None:
        # Legacy entries without measured_palette default to "auto".
        flow = await _make_options_flow(
            hass, {"update_interval": 60, "optimize": True}
        )
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "optimize": True,
                "advanced_section": {},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["measured_palette"] == "auto"

    async def test_device_settings_shows_form(
        self, hass: HomeAssistant
    ) -> None:
        # Calling device_settings with no input returns the form.
        flow = await _make_options_flow(
            hass, {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_device_settings(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "device_settings"

    async def test_device_settings_preset_recomputes_dimensions(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Changing Kindle model recomputes dimensions directly.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
                "webhook_urls": [],
            },
        )
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw4", "orientation": "portrait"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["device_model"] == "kindle_pw4"
        assert result["data"]["width"] == 1072
        assert result["data"]["height"] == 1448
        assert result["data"]["rotation"] == 0
        assert result["data"]["optimize"] is True
        assert result["data"]["display_levels"] == 16
        assert result["data"]["dither_algorithm"] == "floyd_steinberg"
        assert result["data"]["webhook_urls"] == []

    async def test_device_settings_orientation_change_recomputes(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Changing orientation swaps dimensions and updates rotation.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
            },
        )
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "landscape"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["orientation"] == "landscape"
        assert result["data"]["width"] == 1024
        assert result["data"]["height"] == 758
        assert result["data"]["rotation"] == 90

    async def test_device_settings_area_saved(
        self, hass: HomeAssistant
    ) -> None:
        # Area selection from device_settings is preserved in saved
        # options.
        flow = await _make_options_flow(
            hass, {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area": "kitchen",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["area_id"] == "kitchen"

    async def test_device_settings_area_removed(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting without area removes a previously-stored area_id.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area_id": "kitchen",
            },
        )
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "area_id" not in result["data"]

    async def test_device_settings_battery_entity_id_saved(
        self, hass: HomeAssistant
    ) -> None:
        # battery_entity_id submitted via device_settings is saved for
        # non-Kindle devices (custom stays custom → immediate entry).
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "custom",
                "orientation": "portrait",
                "width": 600,
                "height": 800,
                "rotation": 0,
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "custom",
                "orientation": "portrait",
                "battery_entity_id": "sensor.trmnl_battery",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["battery_entity_id"] == "sensor.trmnl_battery"

    async def test_device_settings_battery_entity_id_removed(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting without battery_entity_id removes a
        # previously-stored value.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "battery_entity_id": "sensor.trmnl_battery",
            },
        )
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "battery_entity_id" not in result["data"]

    async def test_device_settings_battery_entity_id_propagated_trmnl(
        self,
        hass: HomeAssistant,
    ) -> None:
        # battery_entity_id survives inline screen_portion_section save.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "battery_entity_id": "sensor.trmnl_battery",
                "screen_portion_section": {"screen_portion": "full"},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["battery_entity_id"] == "sensor.trmnl_battery"

    async def test_device_settings_battery_entity_id_removed_trmnl(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Clearing battery_entity_id on TRMNL removes it through
        # inline section save.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "battery_entity_id": "sensor.trmnl_battery",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "screen_portion_section": {"screen_portion": "full"},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "battery_entity_id" not in result["data"]

    async def test_device_settings_switch_to_kindle_removes_battery_entity_id(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Switching from a TRMNL device to Kindle removes
        # battery_entity_id because Kindle pushes battery via query
        # params (no picker shown).
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "battery_entity_id": "sensor.trmnl_battery",
            },
        )
        # The form includes screen_portion_section because opts was
        # TRMNL; HA always submits all fields even from collapsed
        # sections.
        result = await flow.async_step_device_settings(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "screen_portion_section": {"screen_portion": "full"},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "battery_entity_id" not in result["data"]

    async def test_device_settings_kindle_has_no_battery_picker(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Kindle devices report battery via query params, so the
        # external battery entity picker must not appear in the form
        # schema.
        flow = await _make_options_flow(
            hass, {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_device_settings(None)

        field_names = {
            k.schema
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert "battery_entity_id" not in field_names

    async def test_device_settings_trmnl_has_battery_picker(
        self, hass: HomeAssistant
    ) -> None:
        # TRMNL devices show the external battery entity picker.
        flow = await _make_options_flow(
            hass, {"device_model": "trmnl_og", "orientation": "landscape"}
        )
        result = await flow.async_step_device_settings(None)

        field_names = {
            k.schema
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert "battery_entity_id" in field_names

    async def test_device_settings_battery_picker_excludes_own_sensor(
        self,
        hass: HomeAssistant,
    ) -> None:
        # When the entity registry maps the own sensor, it is excluded
        # from the EntitySelector to prevent the user picking it.
        entry_id = "test_entry"
        er.async_get(hass).async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry_id}_battery",
            suggested_object_id="eink_battery",
        )
        flow = await _make_options_flow(
            hass,
            {"device_model": "trmnl_og", "orientation": "landscape"},
            entry_id=entry_id,
        )
        result = await flow.async_step_device_settings(None)

        battery_key = next(
            k
            for k in result["data_schema"].schema
            if hasattr(k, "schema") and k.schema == "battery_entity_id"
        )
        selector = result["data_schema"].schema[battery_key]
        assert selector.config.get("exclude_entities") == [
            "sensor.eink_battery"
        ]

    async def test_screen_portion_options_shows_form_on_fallback(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Switching from Kindle to TRMNL has no section in the form, so
        # device_settings falls back to the screen_portion_options step.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
            },
        )
        result = await flow.async_step_device_settings(
            {"device_model": "trmnl_og", "orientation": "landscape"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "screen_portion_options"

    async def test_inline_section_full_saves(
        self, hass: HomeAssistant
    ) -> None:
        # "full" saves via inline section when model/orientation
        # unchanged.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "screen_portion": "half",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "screen_portion_section": {"screen_portion": "full"},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["width"] == 800
        assert result["data"]["height"] == 480
        assert result["data"]["screen_portion"] == "full"

    async def test_inline_section_half_halves_width(
        self,
        hass: HomeAssistant,
    ) -> None:
        # "half" saves via inline section, halving the width.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "screen_portion_section": {"screen_portion": "half"},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["width"] == 400
        assert result["data"]["height"] == 480

    async def test_inline_section_quarter_halves_both(
        self,
        hass: HomeAssistant,
    ) -> None:
        # "quarter" saves via inline section, halving both dimensions.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "screen_portion_section": {"screen_portion": "quarter"},
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["width"] == 400
        assert result["data"]["height"] == 240

    async def test_inline_section_custom_routes_to_resolution(
        self,
        hass: HomeAssistant,
    ) -> None:
        # "custom" via inline section routes to custom_resolution step.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
                "screen_portion_section": {"screen_portion": "custom"},
            }
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_resolution"

    async def test_section_in_schema_for_trmnl_device(
        self, hass: HomeAssistant
    ) -> None:
        # Form for an existing TRMNL device includes
        # screen_portion_section.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
            },
        )
        result = await flow.async_step_device_settings(None)

        field_names = {
            k.schema
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert "screen_portion_section" in field_names

    async def test_section_absent_for_kindle_device(
        self, hass: HomeAssistant
    ) -> None:
        # Form for a Kindle device omits the screen_portion_section.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
            },
        )
        result = await flow.async_step_device_settings(None)

        field_names = {
            k.schema
            for k in result["data_schema"].schema
            if hasattr(k, "schema")
        }
        assert "screen_portion_section" not in field_names

    async def test_trmnl_model_change_falls_back(
        self, hass: HomeAssistant
    ) -> None:
        # Changing TRMNL model falls back to separate step so labels
        # for the new model's dimensions are shown correctly.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_x",
                "orientation": "landscape",
                "screen_portion_section": {"screen_portion": "full"},
            }
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "screen_portion_options"

    async def test_trmnl_orientation_change_falls_back(
        self, hass: HomeAssistant
    ) -> None:
        # Changing orientation falls back to the separate step so the
        # dimension labels shown reflect the new orientation.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "trmnl_og",
                "orientation": "landscape",
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "trmnl_og",
                "orientation": "portrait",
                "screen_portion_section": {"screen_portion": "full"},
            }
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "screen_portion_options"

    async def test_device_settings_custom_routes_to_resolution(
        self, hass: HomeAssistant
    ) -> None:
        # Switching to "custom" device opens the resolution form.
        flow = await _make_options_flow(
            hass, {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_resolution"

    async def test_options_custom_resolution_shows_form(
        self, hass: HomeAssistant
    ) -> None:
        # Calling custom_resolution with no input returns the form.
        flow = await _make_options_flow(
            hass, {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )
        result = await flow.async_step_custom_resolution(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_resolution"

    async def test_options_custom_resolution_saves(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting custom dimensions saves them with defaults.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
                "webhook_urls": [],
            },
        )
        await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )
        result = await flow.async_step_custom_resolution(
            {"width": 600, "height": 800}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["device_model"] == "custom"
        assert result["data"]["width"] == 600
        assert result["data"]["height"] == 800
        assert result["data"]["rotation"] == 0
        assert result["data"]["optimize"] is False
        assert result["data"]["display_levels"] == 16
        assert result["data"]["webhook_urls"] == []

    async def test_options_custom_resolution_preserves_area(
        self, hass: HomeAssistant
    ) -> None:
        # Area from device_settings survives custom resolution save.
        flow = await _make_options_flow(
            hass, {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {
                "device_model": "custom",
                "orientation": "portrait",
                "area": "kitchen",
            }
        )
        result = await flow.async_step_custom_resolution(
            {"width": 600, "height": 800}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["area_id"] == "kitchen"

    async def test_options_custom_resolution_removes_area(
        self, hass: HomeAssistant
    ) -> None:
        # Omitting area in device_settings removes stored area_id.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area_id": "kitchen",
            },
        )
        await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )
        result = await flow.async_step_custom_resolution(
            {"width": 600, "height": 800}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "area_id" not in result["data"]

    async def test_device_settings_custom_to_preset(
        self, hass: HomeAssistant
    ) -> None:
        # Switching from custom to a Kindle preset creates entry
        # directly.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "custom",
                "orientation": "portrait",
                "width": 600,
                "height": 800,
                "rotation": 0,
            },
        )
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw4", "orientation": "portrait"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["device_model"] == "kindle_pw4"
        assert result["data"]["width"] == 1072
        assert result["data"]["height"] == 1448
        assert result["data"]["rotation"] == 0
        assert result["data"]["optimize"] is True
        assert result["data"]["display_levels"] == 16

    async def test_device_settings_custom_stays_custom_skips_resolution(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Keeping "custom" model skips the custom_resolution step.
        flow = await _make_options_flow(
            hass,
            {
                "device_model": "custom",
                "orientation": "portrait",
                "width": 600,
                "height": 800,
                "rotation": 0,
            },
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "custom",
                "orientation": "portrait",
                "area": "kitchen",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["width"] == 600
        assert result["data"]["height"] == 800
        assert result["data"]["rotation"] == 0
        assert result["data"]["area_id"] == "kitchen"

    async def test_copy_card_yaml_shows_entry_id(
        self, hass: HomeAssistant
    ) -> None:
        # Card YAML step shows a snippet containing the entry ID.
        flow = await _make_options_flow(
            hass, {"webhook_urls": []}, entry_id="abc123"
        )
        result = await flow.async_step_copy_card_yaml(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "copy_card_yaml"
        placeholders = result["description_placeholders"]
        assert "abc123" in placeholders["yaml"]
        assert "eink-dashboard-card" in placeholders["yaml"]

    async def test_copy_card_yaml_submit_returns_to_init(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting the card YAML form returns to init menu.
        flow = await _make_options_flow(
            hass, {"webhook_urls": []}, entry_id="abc123"
        )
        result = await flow.async_step_copy_card_yaml({})

        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "init"

    async def test_copy_dashboard_yaml_shows_all_entries(
        self, hass: HomeAssistant
    ) -> None:
        # Dashboard YAML step lists all domain config entries.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        entry_a = MockConfigEntry(domain=DOMAIN, entry_id="aaa111")
        entry_a.add_to_hass(hass)
        entry_b = MockConfigEntry(domain=DOMAIN, entry_id="bbb222")
        entry_b.add_to_hass(hass)
        result = await flow.async_step_copy_dashboard_yaml(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "copy_dashboard_yaml"
        yaml = result["description_placeholders"]["yaml"]
        assert "aaa111" in yaml
        assert "bbb222" in yaml
        assert "eink-dashboard-card" in yaml
        assert "type: sections" in yaml

    async def test_copy_dashboard_yaml_groups_similar_sizes_together(
        self, hass: HomeAssistant
    ) -> None:
        # Entries with similar card sizes share one grid section and
        # get no explicit grid_options, since the default sizing
        # already fits them side by side. _make_options_flow's own
        # backing entry (default 758x1024) is also included in the
        # entries list and contributes to the baseline calculation.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        entry_a = MockConfigEntry(
            domain=DOMAIN,
            entry_id="kindle_pw",
            options={"width": 758, "height": 1024},
        )
        entry_a.add_to_hass(hass)
        entry_b = MockConfigEntry(
            domain=DOMAIN,
            entry_id="kindle_pw4",
            options={"width": 1072, "height": 1448},
        )
        entry_b.add_to_hass(hass)
        result = await flow.async_step_copy_dashboard_yaml(None)

        yaml = result["description_placeholders"]["yaml"]
        assert yaml.count("type: grid") == 1
        assert "grid_options" not in yaml

    async def test_copy_dashboard_yaml_isolates_oversized_entry(
        self, hass: HomeAssistant
    ) -> None:
        # An entry much larger than the others (e.g. a landscape
        # reTerminal E1003 next to portrait Kindles) gets its own
        # full-width grid section instead of sharing a row.
        # _make_options_flow's own backing entry (default 758x1024)
        # is also included in the entries list and contributes to
        # the median baseline, making this a 4-entry median.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        entry_a = MockConfigEntry(
            domain=DOMAIN,
            entry_id="kindle_pw",
            options={"width": 758, "height": 1024},
        )
        entry_a.add_to_hass(hass)
        entry_b = MockConfigEntry(
            domain=DOMAIN,
            entry_id="kindle_oasis",
            options={"width": 1264, "height": 1680},
        )
        entry_b.add_to_hass(hass)
        entry_huge = MockConfigEntry(
            domain=DOMAIN,
            entry_id="reterminal_e1003",
            options={"width": 1872, "height": 1404},
        )
        entry_huge.add_to_hass(hass)
        result = await flow.async_step_copy_dashboard_yaml(None)

        yaml = result["description_placeholders"]["yaml"]
        assert yaml.count("type: grid") == 2
        assert yaml.count("grid_options") == 1
        assert yaml.count("columns: full") == 1
        sections = yaml.split("type: grid")[1:]
        huge_section = next(s for s in sections if "reterminal_e1003" in s)
        assert "kindle_pw" not in huge_section
        assert "kindle_oasis" not in huge_section

    async def test_copy_dashboard_yaml_submit_returns_to_init(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting dashboard YAML form returns to init menu.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        result = await flow.async_step_copy_dashboard_yaml({})

        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "init"

    async def test_copy_dashboard_yaml_parses_to_valid_structure(
        self, hass: HomeAssistant
    ) -> None:
        # Generated YAML is syntactically valid and matches the
        # expected Lovelace sections-view structure: a shared grid
        # for normal-sized entries and a full-width grid per
        # oversized entry, each holding the right card config.
        # _make_options_flow's own backing entry (default
        # 758x1024) is also included in the entries list.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        entry_a = MockConfigEntry(
            domain=DOMAIN,
            entry_id="kindle_pw",
            options={"width": 758, "height": 1024},
        )
        entry_a.add_to_hass(hass)
        entry_huge = MockConfigEntry(
            domain=DOMAIN,
            entry_id="reterminal_e1003",
            options={"width": 1872, "height": 1404},
        )
        entry_huge.add_to_hass(hass)
        result = await flow.async_step_copy_dashboard_yaml(None)

        raw = result["description_placeholders"]["yaml"]
        doc = yaml.safe_load(raw)
        view = doc["views"][0]
        assert view["type"] == "sections"
        assert view["max_columns"] == 10
        assert view["title"] == "E-Ink Dashboards"
        assert "path" not in view
        sections = view["sections"]
        assert len(sections) == 2

        normal_section = sections[0]
        assert normal_section["type"] == "grid"
        assert normal_section["column_span"] == 10
        assert len(normal_section["cards"]) == 2
        assert all(
            c["type"] == "custom:eink-dashboard-card"
            for c in normal_section["cards"]
        )

        large_section = sections[1]
        assert large_section["type"] == "grid"
        assert len(large_section["cards"]) == 1
        large_card = large_section["cards"][0]
        assert large_card["config_entry"] == "reterminal_e1003"
        assert large_card["grid_options"] == {"columns": "full"}

    async def test_copy_dashboard_yaml_isolates_multiple_oversized(
        self, hass: HomeAssistant
    ) -> None:
        # Two entries much larger than the normals each get their
        # own full-width grid section rather than sharing one.
        # _make_options_flow's own backing entry (default
        # 758x1024) is also included in the entries list.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        for entry_id in ("normal_a", "normal_b"):
            entry = MockConfigEntry(
                domain=DOMAIN,
                entry_id=entry_id,
                options={"width": 758, "height": 1024},
            )
            entry.add_to_hass(hass)
        for entry_id, width, height in (
            ("large_a", 1872, 1404),
            ("large_b", 2560, 1600),
        ):
            entry = MockConfigEntry(
                domain=DOMAIN,
                entry_id=entry_id,
                options={"width": width, "height": height},
            )
            entry.add_to_hass(hass)
        result = await flow.async_step_copy_dashboard_yaml(None)

        raw = result["description_placeholders"]["yaml"]
        assert raw.count("type: grid") == 3
        assert raw.count("grid_options") == 2
        assert raw.count("columns: full") == 2

    async def test_copy_dashboard_yaml_exact_threshold_is_normal(
        self, hass: HomeAssistant
    ) -> None:
        # An entry at exactly 1.5x the baseline stays in the normal
        # group, since _split_large_entries uses a strict > compare.
        # _make_options_flow's own backing entry (default
        # 758x1024) is also included in the entries list.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        entry_anchor = MockConfigEntry(
            domain=DOMAIN,
            entry_id="anchor",
            options={"width": 758, "height": 1024},
        )
        entry_anchor.add_to_hass(hass)
        # Exactly 1.5x the 758x1024 baseline: 758*1.5=1137,
        # 1024*1.5=1536.
        entry_boundary = MockConfigEntry(
            domain=DOMAIN,
            entry_id="boundary",
            options={"width": 1137, "height": 1536},
        )
        entry_boundary.add_to_hass(hass)
        result = await flow.async_step_copy_dashboard_yaml(None)

        raw = result["description_placeholders"]["yaml"]
        assert raw.count("type: grid") == 1
        assert "grid_options" not in raw

    async def test_display_settings_persists_entry_options(
        self, hass: HomeAssistant
    ) -> None:
        # Full flow via async_configure() persists updated
        # options on the real config entry.
        entry = MockConfigEntry(
            domain=DOMAIN,
            options={
                "width": 800,
                "height": 480,
                "update_interval": 60,
                "webhook_urls": [],
            },
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.MENU

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"next_step_id": "display_settings"},
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"update_interval": 120},
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options["update_interval"] == 120
        assert entry.options["width"] == 800
        assert entry.options["webhook_urls"] == []


class TestMigrateEntry:
    async def test_migration_removes_sharpness_contrast(
        self, hass: HomeAssistant
    ) -> None:
        # Migration from minor_version<2 removes sharpness/contrast and
        # adds exposure/saturation with their defaults. The entry then
        # cascades through the 2->3 and 3->4 migrations too, ending at 4.
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=1,
            entry_id="test-entry",
            options={
                "update_interval": 60,
                "optimize": True,
                "sharpness": 2.0,
                "contrast": 1.5,
            },
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.minor_version == 4
        assert "sharpness" not in entry.options
        assert "contrast" not in entry.options
        assert entry.options["exposure"] == 1.0
        assert entry.options["saturation"] == 1.0

    async def test_migration_preserves_other_options(
        self, hass: HomeAssistant
    ) -> None:
        # Migration leaves unrelated options untouched.
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=1,
            entry_id="test-entry",
            options={
                "update_interval": 120,
                "optimize": True,
                "display_levels": 4,
                "sharpness": 1.0,
                "contrast": 1.0,
            },
        )
        entry.add_to_hass(hass)

        await async_migrate_entry(hass, entry)

        assert entry.options["update_interval"] == 120
        assert entry.options["optimize"] is True
        assert entry.options["display_levels"] == 4

    async def test_migration_renames_grayscale_levels(
        self, hass: HomeAssistant
    ) -> None:
        # Migration from minor_version<3 renames the stored
        # grayscale_levels option key to display_levels. The entry
        # then cascades through the 3->4 migration too, ending at 4.
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=2,
            entry_id="test-entry",
            options={
                "update_interval": 60,
                "exposure": 1.0,
                "saturation": 1.0,
                "grayscale_levels": 4,
            },
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.minor_version == 4
        assert "grayscale_levels" not in entry.options
        assert entry.options["display_levels"] == 4

    async def test_migration_fixes_reterminal_e1003_landscape_rotation(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Migration from minor_version<4 recomputes width/height/
        # rotation for reterminal_e1003 entries created under the old,
        # buggy preset. A landscape entry had a stale rotation=90
        # baked in; the fix clears it to 0.
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=3,
            entry_id="test-entry",
            options={
                "device_model": "reterminal_e1003",
                "orientation": "landscape",
                "width": 1872,
                "height": 1404,
                "rotation": 90,
            },
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.minor_version == 4
        assert entry.options["width"] == 1872
        assert entry.options["height"] == 1404
        assert entry.options["rotation"] == 0

    async def test_migration_fixes_reterminal_e1003_portrait_rotation(
        self,
        hass: HomeAssistant,
    ) -> None:
        # A portrait reterminal_e1003 entry had a stale rotation=0
        # baked in under the old preset; the fix sets it to 90.
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=3,
            entry_id="test-entry",
            options={
                "device_model": "reterminal_e1003",
                "orientation": "portrait",
                "width": 1404,
                "height": 1872,
                "rotation": 0,
            },
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.minor_version == 4
        assert entry.options["width"] == 1404
        assert entry.options["height"] == 1872
        assert entry.options["rotation"] == 90

    async def test_migration_skips_non_e1003_devices(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Entries for other device models must not have their
        # width/height/rotation touched by the 3->4 migration.
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=3,
            entry_id="test-entry",
            options={
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
            },
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.minor_version == 4
        assert entry.options["width"] == 758
        assert entry.options["height"] == 1024
        assert entry.options["rotation"] == 0

    async def test_migration_skipped_when_already_at_minor_version_4(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Entries already at minor_version=4 are not migrated again.
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=4,
            entry_id="test-entry",
            options={
                "update_interval": 60,
                "exposure": 1.0,
                "saturation": 1.0,
                "display_levels": 16,
            },
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_update_entry",
            wraps=hass.config_entries.async_update_entry,
        ) as mock_update:
            result = await async_migrate_entry(hass, entry)

        assert result is True
        mock_update.assert_not_called()

    async def test_migration_preserves_existing_exposure_saturation(
        self,
        hass: HomeAssistant,
    ) -> None:
        # setdefault must not overwrite exposure/saturation values that
        # are already present in the entry options (e.g., hand-edited
        # configs).
        from custom_components.eink_dashboard import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            minor_version=1,
            entry_id="test-entry",
            options={
                "update_interval": 60,
                "sharpness": 1.0,
                "contrast": 1.0,
                "exposure": 2.0,
                "saturation": 0.5,
            },
        )
        entry.add_to_hass(hass)

        await async_migrate_entry(hass, entry)

        assert entry.options["exposure"] == 2.0
        assert entry.options["saturation"] == 0.5


class TestLocaleSettingsOptionsFlow:
    async def test_locale_settings_in_menu_no_webhooks(
        self, hass: HomeAssistant
    ) -> None:
        # locale_settings must appear in the init menu.
        flow = await _make_options_flow(hass, {"webhook_urls": []})
        result = await flow.async_step_init(None)

        assert "locale_settings" in result["menu_options"]

    async def test_locale_settings_in_menu_with_webhooks(
        self, hass: HomeAssistant
    ) -> None:
        # locale_settings must appear in the menu when webhooks are set.
        flow = await _make_options_flow(
            hass,
            {"webhook_urls": [{"name": "T", "url": "https://x.com"}]},
        )
        result = await flow.async_step_init(None)

        assert "locale_settings" in result["menu_options"]

    async def test_locale_settings_shows_form(
        self, hass: HomeAssistant
    ) -> None:
        # Step returns a form with the correct step_id.
        flow = await _make_options_flow(hass, {})
        result = await flow.async_step_locale_settings(None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "locale_settings"

    async def test_locale_settings_stores_language_override(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting a language stores it; default number_format is
        # stripped.
        flow = await _make_options_flow(hass, {"width": 800, "height": 480})
        result = await flow.async_step_locale_settings(
            {"locale_language": "de", "locale_number_format": "ha_default"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["locale_language"] == "de"
        assert "locale_number_format" not in result["data"]

    async def test_locale_settings_stores_number_format_override(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Submitting a number_format stores it; empty language is
        # stripped.
        flow = await _make_options_flow(hass, {})
        result = await flow.async_step_locale_settings(
            {
                "locale_language": "",
                "locale_number_format": "decimal_comma",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["locale_number_format"] == "decimal_comma"
        assert "locale_language" not in result["data"]

    async def test_locale_settings_stores_first_weekday_override(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Submitting first_weekday stores it; default other fields are
        # stripped.
        flow = await _make_options_flow(hass, {})
        result = await flow.async_step_locale_settings(
            {
                "locale_language": "",
                "locale_number_format": "ha_default",
                "locale_first_weekday": "sunday",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["locale_first_weekday"] == "sunday"
        assert "locale_language" not in result["data"]
        assert "locale_number_format" not in result["data"]

    async def test_locale_settings_stores_date_format_override(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting date_format stores it; default time_format and
        # other default fields are stripped from the result data.
        flow = await _make_options_flow(hass, {})
        result = await flow.async_step_locale_settings(
            {
                "locale_language": "",
                "locale_number_format": "ha_default",
                "locale_first_weekday": "ha_default",
                "locale_date_format": "dmy",
                "locale_time_format": "ha_default",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["locale_date_format"] == "dmy"
        assert "locale_time_format" not in result["data"]

    async def test_locale_settings_stores_time_format_override(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting time_format stores it; default date_format and
        # other default fields are stripped from the result data.
        flow = await _make_options_flow(hass, {})
        result = await flow.async_step_locale_settings(
            {
                "locale_language": "",
                "locale_number_format": "ha_default",
                "locale_first_weekday": "ha_default",
                "locale_date_format": "ha_default",
                "locale_time_format": "24",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["locale_time_format"] == "24"
        assert "locale_date_format" not in result["data"]

    async def test_locale_settings_stores_all_overrides(
        self, hass: HomeAssistant
    ) -> None:
        # All five non-empty fields are stored when submitted together.
        flow = await _make_options_flow(hass, {})
        result = await flow.async_step_locale_settings(
            {
                "locale_language": "fr",
                "locale_number_format": "space_comma",
                "locale_first_weekday": "monday",
                "locale_date_format": "dmy",
                "locale_time_format": "24",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["locale_language"] == "fr"
        assert result["data"]["locale_number_format"] == "space_comma"
        assert result["data"]["locale_first_weekday"] == "monday"
        assert result["data"]["locale_date_format"] == "dmy"
        assert result["data"]["locale_time_format"] == "24"

    async def test_locale_settings_clears_existing_overrides(
        self, hass: HomeAssistant
    ) -> None:
        # Submitting default/empty values removes previously stored
        # override keys.
        flow = await _make_options_flow(
            hass,
            {
                "locale_language": "de",
                "locale_number_format": "decimal_comma",
                "locale_first_weekday": "monday",
                "locale_date_format": "dmy",
                "locale_time_format": "24",
            },
        )
        result = await flow.async_step_locale_settings(
            {
                "locale_language": "",
                "locale_number_format": "ha_default",
                "locale_first_weekday": "ha_default",
                "locale_date_format": "ha_default",
                "locale_time_format": "ha_default",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "locale_language" not in result["data"]
        assert "locale_number_format" not in result["data"]
        assert "locale_first_weekday" not in result["data"]
        assert "locale_date_format" not in result["data"]
        assert "locale_time_format" not in result["data"]

    async def test_locale_settings_preserves_other_options(
        self, hass: HomeAssistant
    ) -> None:
        # Saving locale settings must not drop device/display options.
        flow = await _make_options_flow(
            hass,
            {
                "width": 758,
                "height": 1024,
                "update_interval": 60,
                "webhook_urls": [],
            },
        )
        result = await flow.async_step_locale_settings(
            {"locale_language": "de"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["width"] == 758
        assert result["data"]["height"] == 1024
        assert result["data"]["update_interval"] == 60
        assert result["data"]["webhook_urls"] == []
        assert result["data"]["locale_language"] == "de"

    async def test_locale_settings_persists_entry_options(
        self, hass: HomeAssistant
    ) -> None:
        # Full flow via async_configure() persists locale
        # overrides on the real config entry.
        entry = MockConfigEntry(
            domain=DOMAIN,
            options={"width": 800, "height": 480},
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.MENU

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"next_step_id": "locale_settings"},
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "locale_language": "de",
                "locale_number_format": "ha_default",
            },
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options["locale_language"] == "de"
        assert "locale_number_format" not in entry.options
        assert entry.options["width"] == 800


class TestApplyScreenPortion:
    def test_full_returns_original_dimensions(self) -> None:
        # "full" leaves width and height unchanged.
        from custom_components.eink_dashboard.const import apply_screen_portion

        assert apply_screen_portion(800, 480, "full") == (800, 480)

    def test_half_halves_width(self) -> None:
        # "half" halves the width while preserving height.
        from custom_components.eink_dashboard.const import apply_screen_portion

        assert apply_screen_portion(800, 480, "half") == (400, 480)

    def test_quarter_halves_both_dimensions(self) -> None:
        # "quarter" halves both width and height.
        from custom_components.eink_dashboard.const import apply_screen_portion

        assert apply_screen_portion(800, 480, "quarter") == (400, 240)

    def test_unknown_portion_raises(self) -> None:
        # An unrecognised portion string raises ValueError immediately.
        from custom_components.eink_dashboard.const import apply_screen_portion

        with pytest.raises(ValueError, match="Unknown screen portion"):
            apply_screen_portion(800, 480, "third")

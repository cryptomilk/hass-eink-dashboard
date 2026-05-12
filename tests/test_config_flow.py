from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import voluptuous as vol

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


def _make_options_flow(options: dict) -> EinkDashboardOptionsFlow:
    _entry = MagicMock()
    _entry.options = options

    class _Flow(EinkDashboardOptionsFlow):
        @property
        def config_entry(self):  # type: ignore[override]
            return _entry

    return _Flow()


class TestEinkDashboardConfigFlow:
    async def test_step_user_shows_form(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["data_schema"] is not None

    async def test_kindle_creates_entry(self) -> None:
        # Full happy path: user step → screen_portion step → create_entry.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_KINDLE)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "Kitchen"
        assert result["data"] == {}
        opts = result["options"]
        assert opts["device_model"] == "kindle_pw"
        assert opts["orientation"] == "portrait"
        assert opts["width"] == 758
        assert opts["height"] == 1024
        assert opts["rotation"] == 0
        assert opts["optimize"] is True
        assert opts["grayscale_levels"] == 16
        assert opts["update_interval"] == 60
        assert opts["webhook_urls"] == []

    async def test_kindle_landscape_rotation(self) -> None:
        # Landscape orientation uses rotated dimensions and rotation=90.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "orientation": "landscape"},
        )
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        opts = result["options"]
        assert opts["width"] == 1024
        assert opts["height"] == 758
        assert opts["rotation"] == 90

    async def test_kindle_pw4_dimensions(self) -> None:
        # Different device preset produces correct canvas size.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "device_model": "kindle_pw4"},
        )
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        opts = result["options"]
        assert opts["width"] == 1072
        assert opts["height"] == 1448

    async def test_user_with_area(self) -> None:
        # Area selection is preserved in the created entry options.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "area": "kitchen"},
        )
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert result["options"]["area_id"] == "kitchen"

    async def test_user_without_area(self) -> None:
        # Omitting area means area_id is absent from the entry options.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_KINDLE)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert "area_id" not in result["options"]

    async def test_screen_portion_shows_form(self) -> None:
        # After the user step, a screen_portion form is presented.
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(_USER_INPUT_KINDLE)

        assert result["type"] == "form"
        assert result["step_id"] == "screen_portion"

    async def test_screen_portion_full_creates_entry(self) -> None:
        # Selecting "full" preserves the preset's native dimensions.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_KINDLE)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        opts = result["options"]
        assert opts["width"] == 758
        assert opts["height"] == 1024
        assert opts["screen_portion"] == "full"

    async def test_screen_portion_half_halves_width(self) -> None:
        # Selecting "half" halves the width while keeping the full height.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_KINDLE)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "half"}
        )

        assert result["type"] == "create_entry"
        opts = result["options"]
        assert opts["width"] == 379
        assert opts["height"] == 1024
        assert opts["screen_portion"] == "half"

    async def test_screen_portion_quarter_halves_both(self) -> None:
        # Selecting "quarter" halves both width and height.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_KINDLE)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "quarter"}
        )

        assert result["type"] == "create_entry"
        opts = result["options"]
        assert opts["width"] == 379
        assert opts["height"] == 512
        assert opts["screen_portion"] == "quarter"

    async def test_screen_portion_custom_advances_to_resolution(self) -> None:
        # Selecting "custom" routes to the custom_resolution step.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_KINDLE)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "custom"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "custom_resolution"

    async def test_trmnl_advances_to_setup(self) -> None:
        # TRMNL flow goes user → screen_portion → trmnl_setup.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_og_dimensions(self) -> None:
        # TRMNL OG preset produces 800×480 with no rotation.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})

        assert flow._data["width"] == 800
        assert flow._data["height"] == 480
        assert flow._data["rotation"] == 0
        assert flow._data["grayscale_levels"] == 2

    async def test_trmnl_portrait_rotation(self) -> None:
        # TRMNL in portrait orientation swaps dimensions and sets rotation=90.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(
            {**_USER_INPUT_TRMNL, "orientation": "portrait"},
        )
        await flow.async_step_screen_portion({"screen_portion": "full"})

        assert flow._data["width"] == 480
        assert flow._data["height"] == 800
        assert flow._data["rotation"] == 90

    async def test_trmnl_setup_shows_form(self) -> None:
        # async_step_trmnl_setup(None) returns the form without submitting.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        result = await flow.async_step_trmnl_setup(None)

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_setup_advances_to_webhook(self) -> None:
        # Submitting the trmnl_setup step opens the webhook entry form.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        result = await flow.async_step_trmnl_setup({})

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_webhook"

    async def test_trmnl_screen_portion_full_advances_to_setup(self) -> None:
        # Selecting "full" screen portion for a TRMNL device goes to setup.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_screen_portion(
            {"screen_portion": "full"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_webhook_creates_entry(self) -> None:
        # Full TRMNL flow produces a correctly-shaped config entry.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {
                "webhook_url": "https://trmnl.com/api/custom_plugins/abc",
                "label": "Hallway TRMNL",
            }
        )

        assert result["type"] == "create_entry"
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

    async def test_trmnl_webhook_defaults_label_to_device_name(self) -> None:
        # Omitting the label defaults the webhook name to the device name.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {"webhook_url": "https://trmnl.com/api/custom_plugins/abc"}
        )

        assert result["type"] == "create_entry"
        assert result["options"]["webhook_urls"][0]["name"] == "Hallway"

    async def test_trmnl_webhook_rejects_invalid_url(self) -> None:
        # A non-URL value triggers an inline validation error.
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_screen_portion({"screen_portion": "full"})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {"webhook_url": "not-a-url"}
        )
        assert result["type"] == "form"
        assert result["errors"] == {"webhook_url": "invalid_url"}

    async def test_custom_advances_to_resolution(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(_USER_INPUT_CUSTOM)

        assert result["type"] == "form"
        assert result["step_id"] == "custom_resolution"

    async def test_custom_resolution_shows_form(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        result = await flow.async_step_custom_resolution(None)

        assert result["type"] == "form"
        assert result["step_id"] == "custom_resolution"

    async def test_custom_resolution_advances_to_menu(
        self,
    ) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        result = await flow.async_step_custom_resolution(
            {"width": 600, "height": 800},
        )

        assert result["type"] == "menu"
        assert result["step_id"] == "push_target"
        assert "pull_only" in result["menu_options"]
        assert "trmnl_setup" in result["menu_options"]

    async def test_custom_pull_only_creates_entry(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        await flow.async_step_custom_resolution(
            {"width": 600, "height": 800},
        )
        result = await flow.async_step_pull_only(None)

        assert result["type"] == "create_entry"
        assert result["title"] == "Custom Display"
        opts = result["options"]
        assert opts["device_model"] == "custom"
        assert opts["width"] == 600
        assert opts["height"] == 800
        assert opts["rotation"] == 0
        assert opts["optimize"] is False
        assert opts["webhook_urls"] == []

    async def test_custom_trmnl_webhook_creates_entry(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_CUSTOM)
        await flow.async_step_custom_resolution({"width": 600, "height": 800})
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/xyz",
                "label": "Custom TRMNL",
            }
        )

        assert result["type"] == "create_entry"
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


class TestEinkDashboardOptionsFlow:
    async def test_init_menu_no_webhooks(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        result = await flow.async_step_init(None)

        assert result["type"] == "menu"
        assert "device_settings" in result["menu_options"]
        assert "display_settings" in result["menu_options"]
        assert "add_webhook" in result["menu_options"]
        assert "remove_webhook" not in result["menu_options"]
        assert "settings" not in result["menu_options"]

    async def test_init_menu_with_webhooks(self) -> None:
        flow = _make_options_flow(
            {
                "webhook_urls": [
                    {"name": "Test", "url": "https://example.com"},
                ],
            }
        )
        result = await flow.async_step_init(None)

        assert result["type"] == "menu"
        assert "device_settings" in result["menu_options"]
        assert "display_settings" in result["menu_options"]
        assert "remove_webhook" in result["menu_options"]

    async def test_add_webhook_shows_form(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        result = await flow.async_step_add_webhook(None)

        assert result["type"] == "form"
        assert result["step_id"] == "add_webhook"

    async def test_add_webhook_appends_to_list(self) -> None:
        flow = _make_options_flow(
            {"width": 800, "height": 480, "webhook_urls": []}
        )
        result = await flow.async_step_add_webhook(
            {
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/abc",
                "label": "Kitchen TRMNL",
            }
        )

        assert result["type"] == "create_entry"
        assert result["data"]["webhook_urls"] == [
            {
                "name": "Kitchen TRMNL",
                "url": "https://usetrmnl.com/api/custom_plugins/abc",
            }
        ]

    async def test_add_webhook_defaults_label_to_entry_title(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        flow.config_entry.title = "My Device"
        result = await flow.async_step_add_webhook(
            {"webhook_url": "https://usetrmnl.com/api/custom_plugins/abc"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["webhook_urls"][0]["name"] == "My Device"

    async def test_add_webhook_preserves_existing(self) -> None:
        existing = {
            "name": "Existing",
            "url": "https://example.com/1",
        }
        flow = _make_options_flow({"webhook_urls": [existing]})
        result = await flow.async_step_add_webhook(
            {
                "webhook_url": "https://example.com/2",
            }
        )

        assert result["type"] == "create_entry"
        assert len(result["data"]["webhook_urls"]) == 2

    async def test_add_webhook_rejects_duplicate_url(
        self,
    ) -> None:
        existing = {
            "name": "Existing",
            "url": "https://example.com/1",
        }
        flow = _make_options_flow({"webhook_urls": [existing]})
        result = await flow.async_step_add_webhook(
            {
                "webhook_url": "https://example.com/1",
            }
        )

        assert result["type"] == "form"
        assert result["errors"] == {
            "webhook_url": "already_configured",
        }

    async def test_add_webhook_rejects_invalid_url(
        self,
    ) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        result = await flow.async_step_add_webhook(
            {"webhook_url": "ftp://invalid"}
        )
        assert result["type"] == "form"
        assert result["errors"] == {"webhook_url": "invalid_url"}

    async def test_remove_webhook_shows_form(self) -> None:
        flow = _make_options_flow(
            {
                "webhook_urls": [
                    {"name": "Test", "url": "https://example.com"},
                ],
            }
        )
        result = await flow.async_step_remove_webhook(None)

        assert result["type"] == "form"
        assert result["step_id"] == "remove_webhook"

    async def test_remove_webhook_removes_selected(
        self,
    ) -> None:
        webhooks = [
            {"name": "Keep", "url": "https://example.com/1"},
            {"name": "Remove", "url": "https://example.com/2"},
        ]
        flow = _make_options_flow({"webhook_urls": webhooks})
        result = await flow.async_step_remove_webhook(
            {"webhook_url": "https://example.com/2"}
        )

        assert result["type"] == "create_entry"
        remaining = result["data"]["webhook_urls"]
        assert len(remaining) == 1
        assert remaining[0]["name"] == "Keep"

    async def test_display_settings_shows_form(self) -> None:
        flow = _make_options_flow({"update_interval": 60})
        result = await flow.async_step_display_settings(None)

        assert result["type"] == "form"
        assert result["step_id"] == "display_settings"

    async def test_display_settings_saves_values(self) -> None:
        flow = _make_options_flow(
            {
                "width": 800,
                "height": 480,
                "update_interval": 60,
                "webhook_urls": [],
            }
        )
        result = await flow.async_step_display_settings(
            {"update_interval": 120}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["update_interval"] == 120
        assert result["data"]["width"] == 800
        assert result["data"]["webhook_urls"] == []

    async def test_display_settings_saves_optimize_values(self) -> None:
        flow = _make_options_flow({"update_interval": 60})
        result = await flow.async_step_display_settings(
            {
                "update_interval": 60,
                "optimize": True,
                "grayscale_levels": 2,
                "sharpness": 2.0,
                "contrast": 1.5,
            }
        )

        assert result["type"] == "create_entry"
        assert result["data"]["optimize"] is True
        assert result["data"]["grayscale_levels"] == 2
        assert result["data"]["sharpness"] == 2.0
        assert result["data"]["contrast"] == 1.5

    async def test_display_settings_rejects_invalid_grayscale_levels(
        self,
    ) -> None:
        flow = _make_options_flow({"update_interval": 60})
        with pytest.raises(vol.Invalid):
            await flow.async_step_display_settings(
                {"update_interval": 60, "grayscale_levels": 7}
            )

    async def test_device_settings_shows_form(self) -> None:
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_device_settings(None)

        assert result["type"] == "form"
        assert result["step_id"] == "device_settings"

    async def test_device_settings_preset_recomputes_dimensions(
        self,
    ) -> None:
        # Changing device model recomputes width, height, and rotation.
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
                "webhook_urls": [],
            }
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw4", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["device_model"] == "kindle_pw4"
        assert result["data"]["width"] == 1072
        assert result["data"]["height"] == 1448
        assert result["data"]["rotation"] == 0
        assert result["data"]["optimize"] is True
        assert result["data"]["grayscale_levels"] == 16
        assert result["data"]["webhook_urls"] == []

    async def test_device_settings_orientation_change_recomputes(
        self,
    ) -> None:
        # Changing orientation swaps dimensions and updates rotation.
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
            }
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "landscape"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["orientation"] == "landscape"
        assert result["data"]["width"] == 1024
        assert result["data"]["height"] == 758
        assert result["data"]["rotation"] == 90

    async def test_device_settings_area_saved(self) -> None:
        # Area selection from device_settings is preserved in saved options.
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area": "kitchen",
            }
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["area_id"] == "kitchen"

    async def test_device_settings_area_removed(self) -> None:
        # Submitting without area removes a previously-stored area_id.
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area_id": "kitchen",
            }
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert "area_id" not in result["data"]

    async def test_screen_portion_options_shows_form(self) -> None:
        # After device_settings, a screen_portion_options form is presented.
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(None)

        assert result["type"] == "form"
        assert result["step_id"] == "screen_portion_options"

    async def test_screen_portion_options_full_saves(self) -> None:
        # "full" in options flow saves the preset's native dimensions.
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "screen_portion": "half",
            }
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["width"] == 758
        assert result["data"]["height"] == 1024
        assert result["data"]["screen_portion"] == "full"

    async def test_screen_portion_options_half_halves_width(self) -> None:
        # Selecting "half" in options flow halves the width.
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "half"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["width"] == 379
        assert result["data"]["height"] == 1024

    async def test_screen_portion_options_quarter_halves_both(self) -> None:
        # Selecting "quarter" in options flow halves both dimensions.
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "quarter"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["width"] == 379
        assert result["data"]["height"] == 512

    async def test_screen_portion_options_custom_routes_to_resolution(
        self,
    ) -> None:
        # Selecting "custom" in options flow routes to custom_resolution.
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "custom"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "custom_resolution"

    async def test_device_settings_custom_routes_to_resolution(
        self,
    ) -> None:
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "custom_resolution"

    async def test_options_custom_resolution_shows_form(self) -> None:
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )
        result = await flow.async_step_custom_resolution(None)

        assert result["type"] == "form"
        assert result["step_id"] == "custom_resolution"

    async def test_options_custom_resolution_saves(self) -> None:
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
                "webhook_urls": [],
            }
        )
        await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )
        result = await flow.async_step_custom_resolution(
            {"width": 600, "height": 800}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["device_model"] == "custom"
        assert result["data"]["width"] == 600
        assert result["data"]["height"] == 800
        assert result["data"]["rotation"] == 0
        assert result["data"]["optimize"] is False
        assert result["data"]["grayscale_levels"] == 16
        assert result["data"]["webhook_urls"] == []

    async def test_options_custom_resolution_preserves_area(self) -> None:
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
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

        assert result["type"] == "create_entry"
        assert result["data"]["area_id"] == "kitchen"

    async def test_options_custom_resolution_removes_area(self) -> None:
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area_id": "kitchen",
            }
        )
        await flow.async_step_device_settings(
            {"device_model": "custom", "orientation": "portrait"}
        )
        result = await flow.async_step_custom_resolution(
            {"width": 600, "height": 800}
        )

        assert result["type"] == "create_entry"
        assert "area_id" not in result["data"]

    async def test_device_settings_custom_to_preset(self) -> None:
        # Switching from custom to a preset routes via screen_portion_options.
        flow = _make_options_flow(
            {
                "device_model": "custom",
                "orientation": "portrait",
                "width": 600,
                "height": 800,
                "rotation": 0,
            }
        )
        await flow.async_step_device_settings(
            {"device_model": "kindle_pw4", "orientation": "portrait"}
        )
        result = await flow.async_step_screen_portion_options(
            {"screen_portion": "full"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["device_model"] == "kindle_pw4"
        assert result["data"]["width"] == 1072
        assert result["data"]["height"] == 1448
        assert result["data"]["rotation"] == 0
        assert result["data"]["optimize"] is True
        assert result["data"]["grayscale_levels"] == 16

    async def test_device_settings_custom_stays_custom_skips_resolution(
        self,
    ) -> None:
        flow = _make_options_flow(
            {
                "device_model": "custom",
                "orientation": "portrait",
                "width": 600,
                "height": 800,
                "rotation": 0,
            }
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "custom",
                "orientation": "portrait",
                "area": "kitchen",
            }
        )

        assert result["type"] == "create_entry"
        assert result["data"]["width"] == 600
        assert result["data"]["height"] == 800
        assert result["data"]["rotation"] == 0
        assert result["data"]["area_id"] == "kitchen"

    async def test_copy_card_yaml_shows_entry_id(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        flow.config_entry.entry_id = "abc123"
        result = await flow.async_step_copy_card_yaml(None)

        assert result["type"] == "form"
        assert result["step_id"] == "copy_card_yaml"
        placeholders = result["description_placeholders"]
        assert "abc123" in placeholders["yaml"]
        assert "eink-dashboard-card" in placeholders["yaml"]

    async def test_copy_card_yaml_submit_returns_to_init(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        flow.config_entry.entry_id = "abc123"
        result = await flow.async_step_copy_card_yaml({})

        assert result["type"] == "menu"
        assert result["step_id"] == "init"

    async def test_copy_dashboard_yaml_shows_all_entries(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        entry_a = MagicMock()
        entry_a.entry_id = "aaa111"
        entry_b = MagicMock()
        entry_b.entry_id = "bbb222"
        flow.hass = MagicMock()
        flow.hass.config_entries.async_entries.return_value = [
            entry_a,
            entry_b,
        ]
        result = await flow.async_step_copy_dashboard_yaml(None)

        assert result["type"] == "form"
        assert result["step_id"] == "copy_dashboard_yaml"
        yaml = result["description_placeholders"]["yaml"]
        assert "aaa111" in yaml
        assert "bbb222" in yaml
        assert "eink-dashboard-card" in yaml

    async def test_copy_dashboard_yaml_submit_returns_to_init(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        result = await flow.async_step_copy_dashboard_yaml({})

        assert result["type"] == "menu"
        assert result["step_id"] == "init"


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

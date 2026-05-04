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
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(_USER_INPUT_KINDLE)

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
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "orientation": "landscape"},
        )

        assert result["type"] == "create_entry"
        opts = result["options"]
        assert opts["width"] == 1024
        assert opts["height"] == 758
        assert opts["rotation"] == 90

    async def test_kindle_pw4_dimensions(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "device_model": "kindle_pw4"},
        )

        assert result["type"] == "create_entry"
        opts = result["options"]
        assert opts["width"] == 1072
        assert opts["height"] == 1448

    async def test_user_with_area(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(
            {**_USER_INPUT_KINDLE, "area": "kitchen"},
        )

        assert result["type"] == "create_entry"
        assert result["options"]["area_id"] == "kitchen"

    async def test_user_without_area(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(_USER_INPUT_KINDLE)

        assert "area_id" not in result["options"]

    async def test_trmnl_advances_to_setup(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(_USER_INPUT_TRMNL)

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_og_dimensions(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)

        assert flow._data["width"] == 800
        assert flow._data["height"] == 480
        assert flow._data["rotation"] == 0
        assert flow._data["grayscale_levels"] == 2

    async def test_trmnl_portrait_rotation(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(
            {**_USER_INPUT_TRMNL, "orientation": "portrait"},
        )

        assert flow._data["width"] == 480
        assert flow._data["height"] == 800
        assert flow._data["rotation"] == 90

    async def test_trmnl_setup_shows_form(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_trmnl_setup(None)

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_setup"

    async def test_trmnl_setup_advances_to_webhook(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        result = await flow.async_step_trmnl_setup({})

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_webhook"

    async def test_trmnl_webhook_creates_entry(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {
                "name": "Hallway TRMNL",
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/abc",
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
                "url": "https://usetrmnl.com/api/custom_plugins/abc",
            }
        ]

    async def test_trmnl_webhook_rejects_invalid_url(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT_TRMNL)
        await flow.async_step_trmnl_setup({})
        result = await flow.async_step_trmnl_webhook(
            {"name": "Bad", "webhook_url": "not-a-url"}
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
                "name": "Custom TRMNL",
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/xyz",
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
                "name": "Kitchen TRMNL",
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/abc",
            }
        )

        assert result["type"] == "create_entry"
        assert result["data"]["webhook_urls"] == [
            {
                "name": "Kitchen TRMNL",
                "url": "https://usetrmnl.com/api/custom_plugins/abc",
            }
        ]

    async def test_add_webhook_preserves_existing(self) -> None:
        existing = {
            "name": "Existing",
            "url": "https://example.com/1",
        }
        flow = _make_options_flow({"webhook_urls": [existing]})
        result = await flow.async_step_add_webhook(
            {
                "name": "New",
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
                "name": "Duplicate",
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
            {"name": "Bad", "webhook_url": "ftp://invalid"}
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
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw4", "orientation": "portrait"}
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
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "width": 758,
                "height": 1024,
                "rotation": 0,
            }
        )
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "landscape"}
        )

        assert result["type"] == "create_entry"
        assert result["data"]["orientation"] == "landscape"
        assert result["data"]["width"] == 1024
        assert result["data"]["height"] == 758
        assert result["data"]["rotation"] == 90

    async def test_device_settings_area_saved(self) -> None:
        flow = _make_options_flow(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )
        result = await flow.async_step_device_settings(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area": "kitchen",
            }
        )

        assert result["type"] == "create_entry"
        assert result["data"]["area_id"] == "kitchen"

    async def test_device_settings_area_removed(self) -> None:
        flow = _make_options_flow(
            {
                "device_model": "kindle_pw",
                "orientation": "portrait",
                "area_id": "kitchen",
            }
        )
        result = await flow.async_step_device_settings(
            {"device_model": "kindle_pw", "orientation": "portrait"}
        )

        assert result["type"] == "create_entry"
        assert "area_id" not in result["data"]

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
            {"device_model": "kindle_pw4", "orientation": "portrait"}
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

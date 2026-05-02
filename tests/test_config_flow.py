from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from custom_components.eink_dashboard.config_flow import (
    EinkDashboardConfigFlow,
    EinkDashboardOptionsFlow,
)

_USER_INPUT = {
    "name": "Kitchen",
    "width": 758,
    "height": 1024,
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

    async def test_step_user_advances_to_menu(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(_USER_INPUT)

        assert result["type"] == "menu"
        assert result["step_id"] == "push_target"
        assert "pull_only" in result["menu_options"]
        assert "trmnl_webhook" in result["menu_options"]

    async def test_pull_only_creates_entry(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT)
        result = await flow.async_step_pull_only(None)

        assert result["type"] == "create_entry"
        assert result["title"] == "Kitchen"
        assert result["data"] == {}
        assert result["options"] == {
            "width": 758,
            "height": 1024,
            "update_interval": 60,
            "webhook_urls": [],
        }

    async def test_trmnl_webhook_shows_form(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT)
        result = await flow.async_step_trmnl_webhook(None)

        assert result["type"] == "form"
        assert result["step_id"] == "trmnl_webhook"

    async def test_trmnl_webhook_creates_entry(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT)
        result = await flow.async_step_trmnl_webhook(
            {
                "name": "Kitchen TRMNL",
                "webhook_url": "https://usetrmnl.com/api/custom_plugins/abc",
            }
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "Kitchen"
        assert result["data"] == {}
        assert result["options"]["webhook_urls"] == [
            {
                "name": "Kitchen TRMNL",
                "url": "https://usetrmnl.com/api/custom_plugins/abc",
            }
        ]
        assert result["options"]["width"] == 758

    async def test_trmnl_webhook_rejects_invalid_url(self) -> None:
        flow = EinkDashboardConfigFlow()
        await flow.async_step_user(_USER_INPUT)
        with pytest.raises(vol.Invalid):
            await flow.async_step_trmnl_webhook(
                {"name": "Bad", "webhook_url": "not-a-url"}
            )


class TestEinkDashboardOptionsFlow:
    async def test_init_menu_no_webhooks(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        result = await flow.async_step_init(None)

        assert result["type"] == "menu"
        assert "add_webhook" in result["menu_options"]
        assert "remove_webhook" not in result["menu_options"]
        assert "settings" in result["menu_options"]

    async def test_init_menu_with_webhooks(self) -> None:
        flow = _make_options_flow(
            {"webhook_urls": [{"name": "Test", "url": "https://example.com"}]}
        )
        result = await flow.async_step_init(None)

        assert result["type"] == "menu"
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
        existing = {"name": "Existing", "url": "https://example.com/1"}
        flow = _make_options_flow({"webhook_urls": [existing]})
        result = await flow.async_step_add_webhook(
            {
                "name": "New",
                "webhook_url": "https://example.com/2",
            }
        )

        assert result["type"] == "create_entry"
        assert len(result["data"]["webhook_urls"]) == 2

    async def test_add_webhook_rejects_duplicate_url(self) -> None:
        existing = {"name": "Existing", "url": "https://example.com/1"}
        flow = _make_options_flow({"webhook_urls": [existing]})
        result = await flow.async_step_add_webhook(
            {"name": "Duplicate", "webhook_url": "https://example.com/1"}
        )

        assert result["type"] == "form"
        assert result["errors"] == {"webhook_url": "already_configured"}

    async def test_add_webhook_rejects_invalid_url(self) -> None:
        flow = _make_options_flow({"webhook_urls": []})
        with pytest.raises(vol.Invalid):
            await flow.async_step_add_webhook(
                {"name": "Bad", "webhook_url": "ftp://invalid"}
            )

    async def test_remove_webhook_shows_form(self) -> None:
        flow = _make_options_flow(
            {"webhook_urls": [{"name": "Test", "url": "https://example.com"}]}
        )
        result = await flow.async_step_remove_webhook(None)

        assert result["type"] == "form"
        assert result["step_id"] == "remove_webhook"

    async def test_remove_webhook_removes_selected(self) -> None:
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

    async def test_settings_shows_form(self) -> None:
        flow = _make_options_flow(
            {"width": 800, "height": 480, "update_interval": 60}
        )
        result = await flow.async_step_settings(None)

        assert result["type"] == "form"
        assert result["step_id"] == "settings"

    async def test_settings_saves_values(self) -> None:
        flow = _make_options_flow(
            {
                "width": 800,
                "height": 480,
                "update_interval": 60,
                "webhook_urls": [],
            }
        )
        result = await flow.async_step_settings(
            {
                "width": 758,
                "height": 1024,
                "update_interval": 120,
            }
        )

        assert result["type"] == "create_entry"
        assert result["data"]["width"] == 758
        assert result["data"]["height"] == 1024
        assert result["data"]["update_interval"] == 120
        assert result["data"]["webhook_urls"] == []

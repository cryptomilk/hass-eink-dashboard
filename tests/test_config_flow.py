from __future__ import annotations

from custom_components.eink_dashboard.config_flow import (
    EinkDashboardConfigFlow,
)


class TestEinkDashboardConfigFlow:
    async def test_step_user_shows_form(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["data_schema"] is not None

    async def test_step_user_creates_entry(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(
            {
                "name": "Kitchen",
                "width": 600,
                "height": 800,
                "update_interval": 120,
            }
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "Kitchen"
        assert result["data"] == {}
        assert result["options"] == {
            "width": 600,
            "height": 800,
            "update_interval": 120,
            "webhook_url": "",
        }

    async def test_step_user_stores_webhook_url(self) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(
            {
                "name": "TRMNL",
                "width": 800,
                "height": 480,
                "update_interval": 60,
                "webhook_url": "https://trmnl.com/api/custom_plugins/abc",
            }
        )

        assert result["type"] == "create_entry"
        assert result["options"]["webhook_url"] == (
            "https://trmnl.com/api/custom_plugins/abc"
        )

    async def test_step_user_webhook_url_defaults_to_empty(
        self,
    ) -> None:
        flow = EinkDashboardConfigFlow()
        result = await flow.async_step_user(
            {
                "name": "Kindle",
                "width": 758,
                "height": 1024,
                "update_interval": 60,
            }
        )

        assert result["type"] == "create_entry"
        assert result["options"]["webhook_url"] == ""

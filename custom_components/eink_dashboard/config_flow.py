from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    DEFAULT_HEIGHT,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WIDTH,
    DOMAIN,
)

_POSITIVE_INT = vol.All(int, vol.Range(min=1))

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("name", default="E-Ink Dashboard"): str,
        vol.Required("width", default=DEFAULT_WIDTH): _POSITIVE_INT,
        vol.Required("height", default=DEFAULT_HEIGHT): _POSITIVE_INT,
        vol.Required(
            "update_interval", default=DEFAULT_UPDATE_INTERVAL
        ): _POSITIVE_INT,
        vol.Optional("webhook_url", default=""): str,
    }
)


class EinkDashboardConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            validated = _STEP_USER_SCHEMA(user_input)
            name = validated["name"]
            return self.async_create_entry(
                title=name,
                data={},
                options={k: v for k, v in validated.items() if k != "name"},
            )
        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_USER_SCHEMA,
        )

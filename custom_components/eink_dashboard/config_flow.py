from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DEFAULT_CONTRAST,
    DEFAULT_GRAYSCALE_LEVELS,
    DEFAULT_HEIGHT,
    DEFAULT_OPTIMIZE,
    DEFAULT_SHARPNESS,
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
    }
)

_STEP_WEBHOOK_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("webhook_url"): cv.url,
    }
)


class EinkDashboardConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}
        self._name: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> EinkDashboardOptionsFlow:
        return EinkDashboardOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            validated = _STEP_USER_SCHEMA(user_input)
            self._name = validated["name"]
            self._data = {k: v for k, v in validated.items() if k != "name"}
            return await self.async_step_push_target()
        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_USER_SCHEMA,
        )

    async def async_step_push_target(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="push_target",
            menu_options=["pull_only", "trmnl_setup"],
        )

    async def async_step_pull_only(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        name = self._name
        return self.async_create_entry(
            title=name,
            data={},
            options={**self._data, "webhook_urls": []},
        )

    async def async_step_trmnl_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_trmnl_webhook()
        return self.async_show_form(
            step_id="trmnl_setup",
            data_schema=vol.Schema({}),
        )

    async def async_step_trmnl_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            validated = _STEP_WEBHOOK_SCHEMA(user_input)
            name = self._name
            return self.async_create_entry(
                title=name,
                data={},
                options={
                    **self._data,
                    "webhook_urls": [
                        {
                            "name": validated["name"],
                            "url": validated["webhook_url"],
                        }
                    ],
                },
            )
        return self.async_show_form(
            step_id="trmnl_webhook",
            data_schema=_STEP_WEBHOOK_SCHEMA,
        )


class EinkDashboardOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        webhooks = self.config_entry.options.get("webhook_urls", [])
        menu_options: list[str] = ["add_webhook", "settings"]
        if webhooks:
            menu_options = ["add_webhook", "remove_webhook", "settings"]
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
        )

    async def async_step_add_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            validated = _STEP_WEBHOOK_SCHEMA(user_input)
            existing = self.config_entry.options.get("webhook_urls", [])
            if any(wh["url"] == validated["webhook_url"] for wh in existing):
                return self.async_show_form(
                    step_id="add_webhook",
                    data_schema=_STEP_WEBHOOK_SCHEMA,
                    errors={"webhook_url": "already_configured"},
                )
            opts = deepcopy(dict(self.config_entry.options))
            opts.setdefault("webhook_urls", []).append(
                {
                    "name": validated["name"],
                    "url": validated["webhook_url"],
                }
            )
            return self.async_create_entry(data=opts)
        return self.async_show_form(
            step_id="add_webhook",
            data_schema=_STEP_WEBHOOK_SCHEMA,
        )

    async def async_step_remove_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            url_to_remove = user_input["webhook_url"]
            opts = deepcopy(dict(self.config_entry.options))
            opts["webhook_urls"] = [
                wh for wh in opts["webhook_urls"] if wh["url"] != url_to_remove
            ]
            return self.async_create_entry(data=opts)
        webhooks = self.config_entry.options.get("webhook_urls", [])
        options = [
            {"value": wh["url"], "label": wh["name"]} for wh in webhooks
        ]
        schema = vol.Schema(
            {
                vol.Required("webhook_url"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="remove_webhook", data_schema=schema
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    "width", default=opts.get("width", DEFAULT_WIDTH)
                ): _POSITIVE_INT,
                vol.Required(
                    "height",
                    default=opts.get("height", DEFAULT_HEIGHT),
                ): _POSITIVE_INT,
                vol.Required(
                    "update_interval",
                    default=opts.get(
                        "update_interval", DEFAULT_UPDATE_INTERVAL
                    ),
                ): _POSITIVE_INT,
                vol.Optional(
                    "optimize",
                    default=opts.get("optimize", DEFAULT_OPTIMIZE),
                ): bool,
                vol.Optional(
                    "grayscale_levels",
                    default=opts.get(
                        "grayscale_levels", DEFAULT_GRAYSCALE_LEVELS
                    ),
                ): vol.In([2, 4, 16, 256]),
                vol.Optional(
                    "sharpness",
                    default=opts.get("sharpness", DEFAULT_SHARPNESS),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=10.0)),
                vol.Optional(
                    "contrast",
                    default=opts.get("contrast", DEFAULT_CONTRAST),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=10.0)),
            }
        )
        if user_input is not None:
            validated = schema(user_input)
            return self.async_create_entry(data={**opts, **validated})
        return self.async_show_form(step_id="settings", data_schema=schema)

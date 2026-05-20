"""Config and options flows for the e-ink dashboard integration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import (
    section as flow_section,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    AreaSelector,
    EntitySelector,
    EntitySelectorConfig,
    LanguageSelector,
    LanguageSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DEFAULT_CONTRAST,
    DEFAULT_GRAYSCALE_LEVELS,
    DEFAULT_HEIGHT,
    DEFAULT_OPTIMIZE,
    DEFAULT_SHARPNESS,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WIDTH,
    DEVICE_PRESETS,
    DOMAIN,
    DateFormat,
    NumberFormat,
    TimeFormat,
    apply_screen_portion,
    resolve_display,
)

_POSITIVE_INT = vol.All(int, vol.Range(min=1))

# Static option lists for the locale settings form.  Defined at module
# level so they are not reconstructed on every call to
# async_step_locale_settings.  Each list starts with "" meaning
# "no override / use the owner's preference".
_NF_OPTIONS = [
    "",
    NumberFormat.LANGUAGE,
    NumberFormat.COMMA_DECIMAL,
    NumberFormat.DECIMAL_COMMA,
    NumberFormat.SPACE_COMMA,
    NumberFormat.QUOTE_DECIMAL,
    NumberFormat.NONE,
]
_FW_OPTIONS = [
    "",
    "language",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
_DF_OPTIONS = [
    "",
    DateFormat.LANGUAGE,
    DateFormat.DMY,
    DateFormat.MDY,
    DateFormat.YMD,
]
_TF_OPTIONS = [
    "",
    TimeFormat.LANGUAGE,
    TimeFormat.AM_PM,
    TimeFormat.TWENTY_FOUR,
]


def _is_valid_url(value: str) -> bool:
    """Return True if value is an http or https URL with a netloc."""
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _build_user_schema(
    default_model: str = "kindle_pw",
    default_orientation: str = "landscape",
) -> vol.Schema:
    """Build the voluptuous schema for the initial user setup step.

    Args:
        default_model: Pre-selected device model value in the form.
        default_orientation: Pre-selected orientation value in the form.

    Returns:
        A voluptuous Schema covering name, device_model, orientation,
        optional area, and update_interval.
    """
    return vol.Schema(
        {
            vol.Required("name", default="My E-Ink Display"): str,
            vol.Required(
                "device_model", default=default_model
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(DEVICE_PRESETS.keys()),
                    translation_key="device_model",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "orientation", default=default_orientation
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["portrait", "landscape"],
                    translation_key="orientation",
                )
            ),
            vol.Optional("area"): AreaSelector(),
            vol.Required(
                "update_interval", default=DEFAULT_UPDATE_INTERVAL
            ): _POSITIVE_INT,
        }
    )


_STEP_CUSTOM_RESOLUTION_SCHEMA = vol.Schema(
    {
        vol.Required("width", default=DEFAULT_WIDTH): _POSITIVE_INT,
        vol.Required("height", default=DEFAULT_HEIGHT): _POSITIVE_INT,
    }
)

_STEP_WEBHOOK_SCHEMA = vol.Schema(
    {
        vol.Required("webhook_url"): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Optional("label", default=""): str,
    }
)


def _screen_portion_options(
    width: int,
    height: int,
) -> list[SelectOptionDict]:
    """Build screen-portion selector options for given dimensions.

    Args:
        width: Display width in pixels.
        height: Display height in pixels.

    Returns:
        Option dicts for full, half, quarter, and custom.
    """
    return [
        SelectOptionDict(
            value="full",
            label=f"Full screen ({width}x{height})",
        ),
        SelectOptionDict(
            value="half",
            label=f"Half screen ({width // 2}x{height})",
        ),
        SelectOptionDict(
            value="quarter",
            label=f"Quarter screen ({width // 2}x{height // 2})",
        ),
        SelectOptionDict(value="custom", label="Custom"),
    ]


class EinkDashboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Multi-step config flow for creating a new dashboard entry."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._name: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> EinkDashboardOptionsFlow:
        """Return the options flow handler."""
        return EinkDashboardOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step: name, model, and orientation."""
        existing = self.hass.config_entries.async_entries(DOMAIN)
        if existing:
            last_opts = existing[-1].options
            default_model = last_opts.get("device_model", "kindle_pw")
            default_orientation = last_opts.get("orientation", "landscape")
        else:
            default_model = "kindle_pw"
            default_orientation = "landscape"

        schema = _build_user_schema(default_model, default_orientation)

        if user_input is not None:
            validated = schema(user_input)
            self._name = validated["name"]
            device_model = validated["device_model"]
            orientation = validated["orientation"]

            self._data = {
                "device_model": device_model,
                "orientation": orientation,
                "update_interval": validated["update_interval"],
            }
            area_id = validated.get("area")
            if area_id:
                self._data["area_id"] = area_id

            if device_model == "custom":
                return await self.async_step_custom_resolution()

            width, height, rotation, preset = resolve_display(
                device_model,
                orientation,
            )

            if device_model.startswith("trmnl_"):
                return await self.async_step_screen_portion()

            self._data.update(
                {
                    "width": width,
                    "height": height,
                    "rotation": rotation,
                    "optimize": preset.optimize,
                    "grayscale_levels": preset.grayscale_levels,
                }
            )
            return self._create_pull_entry()

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
        )

    async def async_step_screen_portion(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select how much of the screen this dashboard occupies."""
        device_model = self._data["device_model"]
        orientation = self._data["orientation"]
        width, height, rotation, preset = resolve_display(
            device_model, orientation
        )

        orientation_indicator = "Landscape" if width > height else "Portrait"

        options = _screen_portion_options(width, height)
        schema = vol.Schema(
            {
                vol.Required("screen_portion", default="full"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        if user_input is not None:
            portion = user_input["screen_portion"]
            if portion == "custom":
                self._data.update(
                    {
                        "rotation": rotation,
                        "optimize": preset.optimize,
                        "grayscale_levels": preset.grayscale_levels,
                        "screen_portion": "custom",
                    }
                )
                return await self.async_step_custom_resolution()
            final_width, final_height = apply_screen_portion(
                width, height, portion
            )
            self._data.update(
                {
                    "width": final_width,
                    "height": final_height,
                    "rotation": rotation,
                    "optimize": preset.optimize,
                    "grayscale_levels": preset.grayscale_levels,
                    "screen_portion": portion,
                }
            )
            if device_model.startswith("trmnl_"):
                return await self.async_step_trmnl_setup()
            return self._create_pull_entry()

        return self.async_show_form(
            step_id="screen_portion",
            data_schema=schema,
            description_placeholders={
                "orientation_info": orientation_indicator
            },
        )

    async def async_step_custom_resolution(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect width and height for a custom or custom-portion device."""
        if user_input is not None:
            validated = _STEP_CUSTOM_RESOLUTION_SCHEMA(user_input)
            self._data.update(
                {
                    "width": validated["width"],
                    "height": validated["height"],
                }
            )
            if "rotation" not in self._data:
                self._data.update(
                    {
                        "rotation": 0,
                        "optimize": DEFAULT_OPTIMIZE,
                        "grayscale_levels": DEFAULT_GRAYSCALE_LEVELS,
                    }
                )
            device_model = self._data.get("device_model", "")
            if device_model.startswith("trmnl_"):
                return await self.async_step_trmnl_setup()
            if device_model == "custom":
                return await self.async_step_push_target()
            return self._create_pull_entry()
        return self.async_show_form(
            step_id="custom_resolution",
            data_schema=_STEP_CUSTOM_RESOLUTION_SCHEMA,
        )

    async def async_step_push_target(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a menu to choose pull-only or TRMNL webhook delivery."""
        return self.async_show_menu(
            step_id="push_target",
            menu_options=["pull_only", "trmnl_setup"],
        )

    def _create_pull_entry(self) -> ConfigFlowResult:
        """Create a config entry with no webhook URLs (pull-only mode)."""
        return self.async_create_entry(
            title=self._name,
            data={},
            options={
                **self._data,
                "sharpness": DEFAULT_SHARPNESS,
                "contrast": DEFAULT_CONTRAST,
                "webhook_urls": [],
            },
        )

    async def async_step_pull_only(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish setup without adding a webhook target."""
        return self._create_pull_entry()

    async def async_step_trmnl_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the TRMNL intro screen before collecting the webhook URL."""
        if user_input is not None:
            return await self.async_step_trmnl_webhook()
        return self.async_show_form(
            step_id="trmnl_setup",
            data_schema=vol.Schema({}),
            description_placeholders={
                "trmnl_plugin_url": (
                    "https://trmnl.com/plugin_settings?keyname=webhook_image"
                ),
                "trmnl_integration_url": (
                    "https://www.home-assistant.io/integrations/trmnl"
                ),
                "trmnl_docs_url": (
                    "https://github.com/cryptomilk/hass-eink-dashboard"
                    "/blob/main/docs/trmnl.md"
                ),
            },
        )

    async def async_step_trmnl_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate the TRMNL webhook URL, then create the
        entry.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            validated = _STEP_WEBHOOK_SCHEMA(user_input)
            if not _is_valid_url(validated["webhook_url"]):
                errors["webhook_url"] = "invalid_url"
            else:
                name = validated["label"] or self._name
                return self.async_create_entry(
                    title=self._name,
                    data={},
                    options={
                        **self._data,
                        "sharpness": DEFAULT_SHARPNESS,
                        "contrast": DEFAULT_CONTRAST,
                        "webhook_urls": [
                            {
                                "name": name,
                                "url": validated["webhook_url"],
                            }
                        ],
                    },
                )
        return self.async_show_form(
            step_id="trmnl_webhook",
            data_schema=_STEP_WEBHOOK_SCHEMA,
            errors=errors or None,
        )


class EinkDashboardOptionsFlow(OptionsFlow):
    """Options flow for modifying an existing dashboard config entry."""

    def __init__(self) -> None:
        """Initialise options flow state."""
        super().__init__()
        self._data: dict[str, Any] = {}

    def _save_display_entry(
        self,
        extra: dict[str, Any],
    ) -> ConfigFlowResult:
        """Merge display keys into stored opts and create entry.

        Combines the stored options with ``self._data`` and any
        display-specific overrides in *extra*, then strips
        optional fields that were cleared.

        Args:
            extra: Display-specific keys (width, height,
                rotation, optimize, grayscale_levels, and
                optionally screen_portion) merged after
                ``self._data``.

        Returns:
            A create_entry ConfigFlowResult.
        """
        opts = deepcopy(dict(self.config_entry.options))
        opts.update({**self._data, **extra})
        if "area_id" not in self._data:
            opts.pop("area_id", None)
        if "battery_entity_id" not in self._data:
            opts.pop("battery_entity_id", None)
        return self.async_create_entry(data=opts)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu, adding remove_webhook if webhooks exist."""
        webhooks = self.config_entry.options.get("webhook_urls", [])
        menu_options: list[str] = [
            "device_settings",
            "display_settings",
            "locale_settings",
            "add_webhook",
            "copy_card_yaml",
            "copy_dashboard_yaml",
        ]
        if webhooks:
            menu_options = [
                "device_settings",
                "display_settings",
                "locale_settings",
                "add_webhook",
                "remove_webhook",
                "copy_card_yaml",
                "copy_dashboard_yaml",
            ]
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
        )

    async def async_step_copy_card_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display the Lovelace card YAML snippet for this entry."""
        if user_input is not None:
            return await self.async_step_init()
        yaml = (
            f"type: custom:eink-dashboard-card\n"
            f"config_entry: {self.config_entry.entry_id}"
        )
        return self.async_show_form(
            step_id="copy_card_yaml",
            data_schema=vol.Schema({}),
            description_placeholders={"yaml": yaml},
        )

    async def async_step_copy_dashboard_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display a full dashboard YAML view containing all e-ink cards."""
        if user_input is not None:
            return await self.async_step_init()
        entries = self.hass.config_entries.async_entries(DOMAIN)
        cards = "\n".join(
            f"      - type: custom:eink-dashboard-card\n"
            f"        config_entry: {e.entry_id}"
            for e in entries
        )
        yaml = f"views:\n  - title: E-Ink Dashboards\n    cards:\n{cards}"
        return self.async_show_form(
            step_id="copy_dashboard_yaml",
            data_schema=vol.Schema({}),
            description_placeholders={"yaml": yaml},
        )

    async def async_step_add_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and append a new webhook URL to the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            validated = _STEP_WEBHOOK_SCHEMA(user_input)
            if not _is_valid_url(validated["webhook_url"]):
                errors["webhook_url"] = "invalid_url"
            else:
                existing = self.config_entry.options.get("webhook_urls", [])
                url = validated["webhook_url"]
                if any(wh["url"] == url for wh in existing):
                    errors["webhook_url"] = "already_configured"
                else:
                    opts = deepcopy(dict(self.config_entry.options))
                    name = validated["label"] or self.config_entry.title
                    opts.setdefault("webhook_urls", []).append(
                        {
                            "name": name,
                            "url": url,
                        }
                    )
                    return self.async_create_entry(data=opts)
        return self.async_show_form(
            step_id="add_webhook",
            data_schema=_STEP_WEBHOOK_SCHEMA,
            errors=errors or None,
        )

    async def async_step_remove_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a selected webhook URL from the options."""
        if user_input is not None:
            url_to_remove = user_input["webhook_url"]
            opts = deepcopy(dict(self.config_entry.options))
            opts["webhook_urls"] = [
                wh for wh in opts["webhook_urls"] if wh["url"] != url_to_remove
            ]
            return self.async_create_entry(data=opts)
        webhooks = self.config_entry.options.get("webhook_urls", [])
        options: list[SelectOptionDict] = [
            SelectOptionDict(value=wh["url"], label=wh["name"])
            for wh in webhooks
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

    async def async_step_device_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update device model, orientation, and area assignment."""
        opts = self.config_entry.options
        # Kindle devices push battery via HTTP query params; all other
        # devices need an explicit HA entity configured.
        has_push_battery = opts.get("device_model", "").startswith("kindle_")
        schema_dict: dict[Any, Any] = {
            vol.Required(
                "device_model",
                default=opts.get("device_model", "kindle_pw"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(DEVICE_PRESETS.keys()),
                    translation_key="device_model",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "orientation",
                default=opts.get("orientation", "portrait"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["portrait", "landscape"],
                    translation_key="orientation",
                )
            ),
            vol.Optional(
                "area",
                description={"suggested_value": opts.get("area_id")},
            ): AreaSelector(),
        }
        if not has_push_battery:
            ent_reg = er.async_get(self.hass)
            own_id = ent_reg.async_get_entity_id(
                "sensor",
                DOMAIN,
                f"{self.config_entry.entry_id}_battery",
            )
            exclude = [own_id] if own_id else []
            schema_dict[
                vol.Optional(
                    "battery_entity_id",
                    description={
                        "suggested_value": opts.get("battery_entity_id")
                    },
                )
            ] = EntitySelector(
                EntitySelectorConfig(
                    domain="sensor",
                    device_class="battery",
                    exclude_entities=exclude,
                )
            )
        # When the stored device is already TRMNL, include screen_portion
        # as a collapsed section so the user can update it in one step.
        # Labels are computed from the current stored model/orientation;
        # when the user changes either, we fall back to the separate step
        # so they see correct dimension labels for the new config.
        is_trmnl = opts.get("device_model", "").startswith("trmnl_")
        if is_trmnl:
            sp_w, sp_h, _, _ = resolve_display(
                opts["device_model"],
                opts.get("orientation", "landscape"),
            )
            stored_portion = opts.get("screen_portion", "full")
            schema_dict[vol.Required("screen_portion_section")] = flow_section(
                vol.Schema(
                    {
                        vol.Required(
                            "screen_portion",
                            default=stored_portion,
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=_screen_portion_options(sp_w, sp_h),
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                    }
                ),
                {"collapsed": True},
            )
        schema = vol.Schema(schema_dict)
        if user_input is not None:
            validated = schema(user_input)
            device_model = validated["device_model"]
            orientation = validated["orientation"]
            area_id = validated.get("area")
            battery_entity_id = validated.get("battery_entity_id")

            self._data = {
                "device_model": device_model,
                "orientation": orientation,
            }
            if area_id:
                self._data["area_id"] = area_id
            if battery_entity_id:
                self._data["battery_entity_id"] = battery_entity_id

            if device_model == "custom":
                if opts.get("device_model") == "custom":
                    return self._save_display_entry({})
                return await self.async_step_custom_resolution()

            if device_model.startswith("trmnl_"):
                section_data = validated.get("screen_portion_section")
                model_same = device_model == opts.get("device_model")
                orient_same = orientation == opts.get("orientation")
                if section_data and model_same and orient_same:
                    portion = section_data["screen_portion"]
                    if portion == "custom":
                        return await self.async_step_custom_resolution()
                    w, h, rot, preset = resolve_display(
                        device_model, orientation
                    )
                    fw, fh = apply_screen_portion(w, h, portion)
                    return self._save_display_entry(
                        {
                            "width": fw,
                            "height": fh,
                            "rotation": rot,
                            "optimize": preset.optimize,
                            "grayscale_levels": preset.grayscale_levels,
                            "screen_portion": portion,
                        }
                    )
                return await self.async_step_screen_portion_options()

            width, height, rotation, preset = resolve_display(
                device_model, orientation
            )
            return self._save_display_entry(
                {
                    "width": width,
                    "height": height,
                    "rotation": rotation,
                    "optimize": preset.optimize,
                    "grayscale_levels": preset.grayscale_levels,
                }
            )

        return self.async_show_form(
            step_id="device_settings",
            data_schema=schema,
            description_placeholders={
                "trmnl_docs_url": (
                    "https://github.com/cryptomilk/hass-eink-dashboard"
                    "/blob/main/docs/trmnl.md"
                ),
            },
        )

    async def async_step_screen_portion_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update screen portion for a non-custom device model."""
        if not self._data:
            return await self.async_step_device_settings()

        device_model = self._data["device_model"]
        orientation = self._data["orientation"]
        width, height, rotation, preset = resolve_display(
            device_model, orientation
        )
        opts = self.config_entry.options

        orientation_indicator = "Landscape" if width > height else "Portrait"

        options = _screen_portion_options(width, height)
        stored_portion = opts.get("screen_portion", "full")
        schema = vol.Schema(
            {
                vol.Required(
                    "screen_portion",
                    default=stored_portion,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        if user_input is not None:
            portion = user_input["screen_portion"]
            if portion == "custom":
                return await self.async_step_custom_resolution()
            final_width, final_height = apply_screen_portion(
                width, height, portion
            )
            return self._save_display_entry(
                {
                    "width": final_width,
                    "height": final_height,
                    "rotation": rotation,
                    "optimize": preset.optimize,
                    "grayscale_levels": preset.grayscale_levels,
                    "screen_portion": portion,
                }
            )

        return self.async_show_form(
            step_id="screen_portion_options",
            data_schema=schema,
            description_placeholders={
                "orientation_info": orientation_indicator
            },
        )

    async def async_step_custom_resolution(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update canvas dimensions for the custom device model."""
        if not self._data:
            return await self.async_step_device_settings()
        if user_input is not None:
            validated = _STEP_CUSTOM_RESOLUTION_SCHEMA(user_input)
            return self._save_display_entry(
                {
                    "width": validated["width"],
                    "height": validated["height"],
                    "rotation": 0,
                    "optimize": DEFAULT_OPTIMIZE,
                    "grayscale_levels": DEFAULT_GRAYSCALE_LEVELS,
                }
            )
        return self.async_show_form(
            step_id="custom_resolution",
            data_schema=_STEP_CUSTOM_RESOLUTION_SCHEMA,
        )

    async def async_step_locale_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Override locale settings for this display.

        All fields are optional.  An empty value means "use the Home
        Assistant owner's preference" (i.e. no per-device override).
        Non-empty values are stored in ``entry.options`` under the
        ``locale_language``, ``locale_number_format``,
        ``locale_first_weekday``, ``locale_date_format``, and
        ``locale_time_format`` keys and applied at render time
        before the owner's preferences.
        """
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    "locale_language",
                    description={
                        "suggested_value": opts.get("locale_language", "")
                    },
                ): LanguageSelector(LanguageSelectorConfig(native_name=True)),
                vol.Optional(
                    "locale_number_format",
                    default=opts.get("locale_number_format", ""),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_NF_OPTIONS,
                        translation_key="locale_number_format",
                    )
                ),
                vol.Optional(
                    "locale_first_weekday",
                    default=opts.get("locale_first_weekday", ""),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_FW_OPTIONS,
                        translation_key="locale_first_weekday",
                    )
                ),
                vol.Optional(
                    "locale_date_format",
                    default=opts.get("locale_date_format", ""),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_DF_OPTIONS,
                        translation_key="locale_date_format",
                    )
                ),
                vol.Optional(
                    "locale_time_format",
                    default=opts.get("locale_time_format", ""),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_TF_OPTIONS,
                        translation_key="locale_time_format",
                    )
                ),
            }
        )
        if user_input is not None:
            validated = schema(user_input)
            new_opts = deepcopy(dict(opts))
            # Store non-empty overrides; remove the key entirely when
            # cleared so absent keys are treated as "no override".
            for key in (
                "locale_language",
                "locale_number_format",
                "locale_first_weekday",
                "locale_date_format",
                "locale_time_format",
            ):
                value = validated.get(key, "")
                if value:
                    new_opts[key] = value
                else:
                    new_opts.pop(key, None)
            return self.async_create_entry(data=new_opts)
        return self.async_show_form(
            step_id="locale_settings",
            data_schema=schema,
        )

    async def async_step_display_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update refresh interval, optimize, and image quality settings."""
        opts = self.config_entry.options
        schema = vol.Schema(
            {
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
            return self.async_create_entry(
                data={**opts, **validated},
            )
        return self.async_show_form(
            step_id="display_settings",
            data_schema=schema,
        )

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _stub_module(name: str) -> ModuleType:
    mod = ModuleType(name)
    mod.__dict__.setdefault("__path__", [])
    return mod


_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.frontend",
    "homeassistant.components.http",
    "homeassistant.components.image",
    "homeassistant.components.media_player",
    "homeassistant.components.media_source",
    "homeassistant.components.sensor",
    "homeassistant.components.websocket_api",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.template",
    "homeassistant.util",
    "homeassistant.util.dt",
]

for _mod_name in _HA_MODULES:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _stub_module(_mod_name)

frontend_mod = sys.modules["homeassistant.components.frontend"]
frontend_mod.add_extra_js_url = MagicMock()  # type: ignore[attr-defined]

http_mod = sys.modules["homeassistant.components.http"]


class _StaticPathConfig:
    def __init__(
        self, url_path: str, path: str, cache_headers: bool = True
    ) -> None:
        self.url_path = url_path
        self.path = path
        self.cache_headers = cache_headers


http_mod.StaticPathConfig = _StaticPathConfig  # type: ignore[attr-defined]
http_mod.HomeAssistantView = type(  # type: ignore[attr-defined]
    "HomeAssistantView",
    (),
    {
        "url": None,
        "requires_auth": True,
    },
)

image_mod = sys.modules["homeassistant.components.image"]
image_mod.ImageEntity = type(  # type: ignore[attr-defined]
    "ImageEntity",
    (),
    {
        "__init__": lambda self, hass: setattr(self, "hass", hass),
        "_attr_image_last_updated": None,
        "async_write_ha_state": lambda self: None,
    },
)

media_player_mod = sys.modules["homeassistant.components.media_player"]


class _BrowseError(Exception):
    pass


class _MediaClass:
    APP = "app"
    IMAGE = "image"


media_player_mod.BrowseError = _BrowseError  # type: ignore[attr-defined]
media_player_mod.MediaClass = _MediaClass  # type: ignore[attr-defined]

media_source_mod = sys.modules["homeassistant.components.media_source"]


class _PlayMedia:
    def __init__(self, url: str, mime_type: str) -> None:
        self.url = url
        self.mime_type = mime_type


class _BrowseMediaSource:
    def __init__(
        self,
        *,
        domain: str | None,
        identifier: str | None,
        media_class: str,
        media_content_type: str,
        title: str,
        can_play: bool,
        can_expand: bool,
        children: list | None = None,
        children_media_class: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        self.domain = domain
        self.identifier = identifier
        self.media_class = media_class
        self.media_content_type = media_content_type
        self.title = title
        self.can_play = can_play
        self.can_expand = can_expand
        self.children = children
        self.children_media_class = children_media_class
        self.thumbnail = thumbnail


class _MediaSource:
    name: str | None = None

    def __init__(self, domain: str) -> None:
        self.domain = domain
        if not self.name:
            self.name = domain


class _MediaSourceItem:
    # Mirrors the real MediaSourceItem dataclass signature.
    def __init__(
        self,
        hass: object,
        domain: str | None,
        identifier: str,
        target_media_player: str | None = None,
    ) -> None:
        self.hass = hass
        self.domain = domain
        self.identifier = identifier
        self.target_media_player = target_media_player


class _Unresolvable(Exception):
    pass


media_source_mod.BrowseMediaSource = _BrowseMediaSource  # type: ignore[attr-defined]
media_source_mod.MediaSource = _MediaSource  # type: ignore[attr-defined]
media_source_mod.MediaSourceItem = _MediaSourceItem  # type: ignore[attr-defined]
media_source_mod.PlayMedia = _PlayMedia  # type: ignore[attr-defined]
media_source_mod.Unresolvable = _Unresolvable  # type: ignore[attr-defined]

config_entries = sys.modules["homeassistant.config_entries"]
config_entries.ConfigEntry = MagicMock  # type: ignore[attr-defined]
config_entries.ConfigFlowResult = dict  # type: ignore[attr-defined]


class _StubFlowBase:
    def async_show_form(
        self,
        *,
        step_id: str | None = None,
        data_schema: object = None,
        errors: dict | None = None,
        description_placeholders: dict | None = None,
        **kw: object,
    ) -> dict:
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors,
            "description_placeholders": description_placeholders,
        }

    def async_show_menu(
        self,
        *,
        step_id: str | None = None,
        menu_options: object = None,
        **kw: object,
    ) -> dict:
        return {
            "type": "menu",
            "step_id": step_id,
            "menu_options": menu_options,
        }


class _StubConfigFlow(_StubFlowBase):
    # Provide a stub hass so async_step_user can call
    # self.hass.config_entries.async_entries() without raising AttributeError.
    hass: object = MagicMock(
        config_entries=MagicMock(async_entries=MagicMock(return_value=[]))
    )

    def __init_subclass__(
        cls, *, domain: str | None = None, **kw: object
    ) -> None:
        super().__init_subclass__(**kw)

    def async_create_entry(
        self,
        *,
        title: str,
        data: object,
        options: object = None,
        **kw: object,
    ) -> dict:
        return {
            "type": "create_entry",
            "title": title,
            "data": data,
            "options": options,
        }


class _StubOptionsFlow(_StubFlowBase):
    def async_create_entry(
        self,
        *,
        data: object = None,
        **kw: object,
    ) -> dict:
        return {
            "type": "create_entry",
            "data": data,
        }


config_entries.ConfigFlow = _StubConfigFlow  # type: ignore[attr-defined]
config_entries.OptionsFlow = _StubOptionsFlow  # type: ignore[attr-defined]

core_mod = sys.modules["homeassistant.core"]
core_mod.HomeAssistant = MagicMock  # type: ignore[attr-defined]
core_mod.callback = lambda f: f  # type: ignore[attr-defined]

aiohttp_client_mod = sys.modules["homeassistant.helpers.aiohttp_client"]
aiohttp_client_mod.async_get_clientsession = MagicMock()  # type: ignore[attr-defined]

event_mod = sys.modules["homeassistant.helpers.event"]
event_mod.async_track_time_interval = MagicMock()  # type: ignore[attr-defined]

cv_mod = sys.modules["homeassistant.helpers.config_validation"]
cv_mod.config_entry_only_config_schema = lambda domain: None  # type: ignore[attr-defined]

area_reg_mod = sys.modules["homeassistant.helpers.area_registry"]
area_reg_mod.async_get = MagicMock()  # type: ignore[attr-defined]

device_reg_mod = sys.modules["homeassistant.helpers.device_registry"]
device_reg_mod.async_get = MagicMock()  # type: ignore[attr-defined]
device_reg_mod.DeviceInfo = lambda **kw: kw  # type: ignore[attr-defined]

storage_mod = sys.modules["homeassistant.helpers.storage"]
storage_mod.Store = MagicMock  # type: ignore[attr-defined]

dt_mod = sys.modules["homeassistant.util.dt"]
dt_mod.utcnow = MagicMock()  # type: ignore[attr-defined]


class _SelectSelectorMode:
    LIST = "list"
    DROPDOWN = "dropdown"


class _SelectSelectorConfig(dict):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(kwargs)


class _SelectOptionDict(dict):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(kwargs)


class _SelectSelector:
    def __init__(self, config: object) -> None:
        pass

    def __call__(self, value: object) -> object:
        return value


class _AreaSelector:
    def __init__(self, config: object = None) -> None:
        pass

    def __call__(self, value: object) -> object:
        return value


class _TextSelectorType:
    URL = "url"
    TEXT = "text"


class _TextSelectorConfig(dict):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(kwargs)


class _TextSelector:
    def __init__(self, config: object = None) -> None:
        pass

    def __call__(self, value: object) -> object:
        return value


selector_mod = sys.modules["homeassistant.helpers.selector"]
selector_mod.SelectSelectorMode = _SelectSelectorMode  # type: ignore[attr-defined]
selector_mod.SelectSelectorConfig = _SelectSelectorConfig  # type: ignore[attr-defined]
selector_mod.SelectOptionDict = _SelectOptionDict  # type: ignore[attr-defined]
selector_mod.SelectSelector = _SelectSelector  # type: ignore[attr-defined]
selector_mod.AreaSelector = _AreaSelector  # type: ignore[attr-defined]
selector_mod.TextSelectorType = _TextSelectorType  # type: ignore[attr-defined]
selector_mod.TextSelectorConfig = _TextSelectorConfig  # type: ignore[attr-defined]
selector_mod.TextSelector = _TextSelector  # type: ignore[attr-defined]

template_mod = sys.modules["homeassistant.helpers.template"]


class _TemplateError(Exception):
    pass


template_mod.TemplateError = _TemplateError  # type: ignore[attr-defined]


class _StubTemplate:
    def __init__(self, template: str, hass: object = None) -> None:
        self.template = template
        self.hass = hass
        self.is_static = not (
            "{{" in template or "{%" in template or "{#" in template
        )

    def async_render(
        self, parse_result: bool = False, **kwargs: object
    ) -> str:
        return self.template


template_mod.Template = _StubTemplate  # type: ignore[attr-defined]

ws_api_mod = sys.modules["homeassistant.components.websocket_api"]


def _ws_command(
    schema: dict,
) -> object:
    """Stub for @websocket_command -- records command name on the handler."""

    def decorator(func: object) -> object:
        # vol.Required("type") has the same hash as "type", so
        # schema["type"] works even when the key is vol.Required.
        func._ws_command = schema["type"]  # type: ignore[attr-defined]
        func._ws_schema = schema  # type: ignore[attr-defined]
        return func

    return decorator


ws_api_mod.websocket_command = _ws_command  # type: ignore[attr-defined]
# Pass-through so tests can await the handler directly.
ws_api_mod.async_response = lambda f: f  # type: ignore[attr-defined]
ws_api_mod.async_register_command = MagicMock()  # type: ignore[attr-defined]
ws_api_mod.ActiveConnection = type(  # type: ignore[attr-defined]
    "ActiveConnection", (), {}
)
ws_api_mod.ERR_NOT_FOUND = "not_found"  # type: ignore[attr-defined]
ws_api_mod.ERR_UNKNOWN_ERROR = "unknown_error"  # type: ignore[attr-defined]

sensor_mod = sys.modules["homeassistant.components.sensor"]


class _SensorDeviceClass:
    BATTERY = "battery"


class _SensorStateClass:
    MEASUREMENT = "measurement"


class _RestoreSensor:
    def async_write_ha_state(self) -> None:
        pass

    async def async_added_to_hass(self) -> None:
        pass

    async def async_get_last_sensor_data(self) -> None:
        return None

    async def async_get_last_state(self) -> None:
        return None


sensor_mod.SensorDeviceClass = _SensorDeviceClass  # type: ignore[attr-defined]
sensor_mod.SensorStateClass = _SensorStateClass  # type: ignore[attr-defined]
sensor_mod.RestoreSensor = _RestoreSensor  # type: ignore[attr-defined]

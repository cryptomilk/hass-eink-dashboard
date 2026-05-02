from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import (
    async_get_clientsession,
)
from homeassistant.helpers.event import (
    async_track_time_interval,
)
from homeassistant.helpers.template import Template, TemplateError
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_HEIGHT,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WIDTH,
    DOMAIN,
    WidgetType,
)
from .push import async_push_image
from .render import render_dashboard

_LOGGER = logging.getLogger(__name__)

PUSH_MIN_INTERVAL = 60


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    entity = EinkDashboardImage(hass, entry)
    widgets = hass.data[DOMAIN][entry.entry_id]["widgets"]
    entity.set_widgets(widgets)
    hass.data[DOMAIN][entry.entry_id]["entity"] = entity
    async_add_entities([entity])


class EinkDashboardImage(ImageEntity):
    _attr_content_type = "image/png"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(hass)
        self._entry = entry
        self._widgets: list[dict[str, Any]] = []
        self._rendered: bytes | None = None
        self._etag: str | None = None
        self._unsub: Callable[[], None] | None = None
        self._refresh_lock = asyncio.Lock()
        self._last_push: float = 0.0
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id

    async def async_added_to_hass(self) -> None:
        interval = self._entry.options.get(
            "update_interval", DEFAULT_UPDATE_INTERVAL
        )
        self._unsub = async_track_time_interval(
            self.hass,
            self._async_refresh,
            timedelta(seconds=interval),
        )
        await self._async_refresh(None)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    def set_widgets(self, widgets: list[dict[str, Any]]) -> None:
        self._widgets = widgets

    def _resolve_templates(  # must be called from the event loop
        self, widgets: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        resolved = []
        for widget in widgets:
            if widget.get("type") == WidgetType.TEXT and "text" in widget:
                tpl = Template(widget["text"], self.hass)
                if not tpl.is_static:
                    try:
                        rendered = tpl.async_render(parse_result=False)
                    except TemplateError as err:
                        _LOGGER.warning(
                            "Failed to render template %r: %s",
                            widget["text"],
                            err,
                        )
                        rendered = widget["text"]
                    widget = {**widget, "text": str(rendered)}
            resolved.append(widget)
        return resolved

    async def _async_refresh(self, _now: Any) -> None:
        push_args: tuple | None = None
        async with self._refresh_lock:
            config = {
                "width": self._entry.options.get("width", DEFAULT_WIDTH),
                "height": self._entry.options.get("height", DEFAULT_HEIGHT),
                "rotation": self._entry.options.get("rotation", 0),
                "states": self._build_states(),
            }
            widgets = self._resolve_templates(self._widgets)
            new_bytes = await self.hass.async_add_executor_job(
                render_dashboard, widgets, config
            )
            if new_bytes != self._rendered:
                self._rendered = new_bytes
                self._etag = f'"{hashlib.sha256(new_bytes).hexdigest()}"'
                self._attr_image_last_updated = dt_util.utcnow()
                self.async_write_ha_state()
                webhook_url = self._entry.options.get("webhook_url", "")
                now = time.monotonic()
                if webhook_url and now - self._last_push >= PUSH_MIN_INTERVAL:
                    self._last_push = now
                    session = async_get_clientsession(self.hass)
                    push_args = (session, webhook_url, new_bytes)
        if push_args:
            await async_push_image(*push_args)

    def _build_states(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for state in self.hass.states.async_all():
            result[state.entity_id] = {
                "state": state.state,
                "attributes": dict(state.attributes),
            }
        return result

    @property
    def etag(self) -> str | None:
        return self._etag

    async def async_image(self) -> bytes | None:
        return self._rendered

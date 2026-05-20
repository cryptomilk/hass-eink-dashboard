"""ImageEntity that renders and refreshes the e-ink dashboard PNG."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.image import ImageEntity
from homeassistant.helpers.aiohttp_client import (
    async_get_clientsession,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import (
    async_track_time_interval,
)
from homeassistant.helpers.template import Template, TemplateError
from homeassistant.util import dt as dt_util
from PIL import Image

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from . import _async_get_locale, _fetch_forecasts, _fetch_history
from .battery import resolve_battery_level
from .const import (
    DEFAULT_CONTRAST,
    DEFAULT_GRAYSCALE_LEVELS,
    DEFAULT_HEIGHT,
    DEFAULT_OPTIMIZE,
    DEFAULT_SHARPNESS,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WIDTH,
    DOMAIN,
    WidgetType,
)
from .push import async_push_image
from .render import render_dashboard

_LOGGER = logging.getLogger(__name__)

PUSH_MIN_INTERVAL = 300
PUSH_MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Maps widget type to the field name that supports Jinja2 templates.
# Add new entries here when a new widget type gains a templatable field.
_TEMPLATE_FIELDS: dict[str, str] = {
    WidgetType.HEADING: "heading",
}


def _is_image_blank(image_bytes: bytes) -> bool:
    """Return True if the image has no dark pixels (appears all-white)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "L":
            img = img.convert("L")
        return not any(b < 200 for b in img.tobytes())
    except Exception:  # noqa: BLE001
        return False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Create and register the EinkDashboardImage entity."""
    _LOGGER.debug("image async_setup_entry: %s", entry.entry_id)
    entity = EinkDashboardImage(hass, entry)
    widgets = hass.data[DOMAIN][entry.entry_id]["widgets"]
    entity.set_widgets(widgets)
    hass.data[DOMAIN][entry.entry_id]["entity"] = entity
    async_add_entities([entity])
    _LOGGER.debug(
        "image async_setup_entry: entity added for %s", entry.entry_id
    )


class EinkDashboardImage(ImageEntity):
    """HA image entity that renders the dashboard and pushes to webhooks."""

    _attr_content_type = "image/png"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the entity from the config entry."""
        super().__init__(hass)
        self._entry = entry
        self._widgets: list[dict[str, Any]] = []
        self._rendered: bytes | None = None
        self._etag: str | None = None
        self._unsub: Callable[[], None] | None = None
        self._refresh_lock = asyncio.Lock()
        self._last_push: float | None = None
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    async def async_added_to_hass(self) -> None:
        """Schedule periodic refresh and render the first frame."""
        interval = self._entry.options.get(
            "update_interval", DEFAULT_UPDATE_INTERVAL
        )
        _LOGGER.debug(
            "async_added_to_hass: %s interval=%ds widgets=%d",
            self._entry.entry_id,
            interval,
            len(self._widgets),
        )
        self._unsub = async_track_time_interval(
            self.hass,
            self._async_refresh,
            timedelta(seconds=interval),
        )
        await self._async_refresh(None)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the periodic refresh subscription."""
        if self._unsub:
            self._unsub()

    def set_widgets(self, widgets: list[dict[str, Any]]) -> None:
        """Replace the current widget list without triggering a refresh."""
        self._widgets = widgets

    async def async_request_refresh(
        self, widgets: list[dict[str, Any]] | None = None
    ) -> None:
        """Update widgets (if provided) and trigger an immediate re-render."""
        if widgets is not None:
            self._widgets = widgets
        await self._async_refresh(None)

    def _render_field(self, raw: str) -> str:
        """Render a single Jinja2 template string, returning raw on error.

        Must be called from the HA event loop (same as
        ``_resolve_templates``).

        Args:
            raw: Template source string.

        Returns:
            Rendered string, or ``raw`` unchanged if the template is
            static or rendering fails.
        """
        tpl = Template(raw, self.hass)
        if not tpl.is_static:
            try:
                return str(tpl.async_render(parse_result=False))
            except TemplateError as err:
                _LOGGER.warning("Failed to render template %r: %s", raw, err)
        return raw

    def _resolve_templates(  # must be called from the event loop
        self, widgets: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Render Jinja2 templates in widget text fields.

        Processes every widget type registered in ``_TEMPLATE_FIELDS``.
        Static strings pass through unchanged.  Template errors are
        logged as warnings and fall back to the original string.

        Args:
            widgets: Widget config list from the dashboard store.

        Returns:
            New list with template fields replaced by rendered values.
        """
        resolved = []
        for widget in widgets:
            wtype = widget.get("type")
            field = _TEMPLATE_FIELDS.get(wtype) if wtype else None
            if field and field in widget:
                widget = {**widget, field: self._render_field(widget[field])}
            resolved.append(widget)
        return resolved

    async def _async_refresh(self, _now: Any) -> None:
        """Re-render the dashboard and push to webhooks if the image
        changed.
        """
        if self.hass.is_stopping:
            _LOGGER.debug(
                "_async_refresh: skipping render during HA shutdown for %s",
                self._entry.entry_id,
            )
            return
        _LOGGER.debug("_async_refresh: start for %s", self._entry.entry_id)
        push_targets: list[tuple[Any, str, bytes]] = []
        # Fetch locale before acquiring the lock so that async store
        # access does not extend the lock's critical section.
        (
            number_format,
            language,
            first_weekday,
            date_format,
            time_format,
        ) = await _async_get_locale(self.hass, self._entry.options)
        try:
            async with self._refresh_lock:
                states = self._build_states()
                await self._async_fetch_forecasts(states)
                await self._async_fetch_history(states)
                config = {
                    "width": self._entry.options.get("width", DEFAULT_WIDTH),
                    "height": self._entry.options.get(
                        "height", DEFAULT_HEIGHT
                    ),
                    "rotation": self._entry.options.get("rotation", 0),
                    "optimize": self._entry.options.get(
                        "optimize", DEFAULT_OPTIMIZE
                    ),
                    "grayscale_levels": self._entry.options.get(
                        "grayscale_levels", DEFAULT_GRAYSCALE_LEVELS
                    ),
                    "sharpness": self._entry.options.get(
                        "sharpness", DEFAULT_SHARPNESS
                    ),
                    "contrast": self._entry.options.get(
                        "contrast", DEFAULT_CONTRAST
                    ),
                    "number_format": number_format,
                    "language": language,
                    "first_weekday": first_weekday,
                    "date_format": date_format,
                    "time_format": time_format,
                    "states": states,
                }
                level, is_charging = resolve_battery_level(
                    self._entry.options.get("battery_entity_id"),
                    states,
                    self.hass.data[DOMAIN][self._entry.entry_id].get(
                        "battery_sensor"
                    ),
                )
                if level is not None:
                    config["device_battery_level"] = level
                    config["device_battery_charging"] = is_charging
                widgets = self._resolve_templates(self._widgets)
                _LOGGER.debug(
                    "_async_refresh: rendering %d widgets at %dx%d",
                    len(widgets),
                    config["width"],
                    config["height"],
                )
                new_bytes = await self.hass.async_add_executor_job(
                    render_dashboard, widgets, config
                )
                is_blank = await self.hass.async_add_executor_job(
                    _is_image_blank, new_bytes
                )
                if is_blank:
                    _LOGGER.warning(
                        "_async_refresh: rendered image is blank for %s,"
                        " skipping webhook push",
                        self._entry.entry_id,
                    )
                if new_bytes != self._rendered:
                    first_render = self._rendered is None
                    _LOGGER.debug(
                        "_async_refresh: image changed, %d bytes"
                        " (first_render=%s)",
                        len(new_bytes),
                        first_render,
                    )
                    self._rendered = new_bytes
                    self._etag = f'"{hashlib.sha256(new_bytes).hexdigest()}"'
                    self._attr_image_last_updated = dt_util.utcnow()
                    self.async_write_ha_state()
                    webhook_urls = self._entry.options.get("webhook_urls", [])
                    now = time.monotonic()
                    if (
                        not first_render
                        and not is_blank
                        and webhook_urls
                        and (
                            self._last_push is None
                            or now - self._last_push >= PUSH_MIN_INTERVAL
                        )
                    ):
                        if len(new_bytes) > PUSH_MAX_IMAGE_BYTES:
                            _LOGGER.warning(
                                "Rendered image is %d bytes, exceeds %d"
                                " byte webhook limit; skipping push",
                                len(new_bytes),
                                PUSH_MAX_IMAGE_BYTES,
                            )
                        else:
                            self._last_push = now
                            session = async_get_clientsession(self.hass)
                            push_targets = [
                                (session, wh["url"], new_bytes)
                                for wh in webhook_urls
                            ]
                    elif first_render and webhook_urls:
                        _LOGGER.info(
                            "_async_refresh: skipping push on initial render"
                        )
                else:
                    _LOGGER.debug("_async_refresh: image unchanged")
        except RuntimeError as exc:
            # Executor shut down between the is_stopping check and the
            # executor call — normal during HA shutdown, not an error.
            if "Executor shutdown" in str(exc):
                _LOGGER.debug(
                    "_async_refresh: executor already shut down for %s",
                    self._entry.entry_id,
                )
                return
            _LOGGER.exception(
                "_async_refresh: failed for %s", self._entry.entry_id
            )
            return
        except Exception:
            _LOGGER.exception(
                "_async_refresh: failed for %s", self._entry.entry_id
            )
            return
        if push_targets:
            await asyncio.gather(
                *(async_push_image(*args) for args in push_targets)
            )

    async def _async_fetch_forecasts(self, states: dict[str, Any]) -> None:
        """Fetch daily forecasts for weather widgets and inject into states.

        Delegates to the module-level ``_fetch_forecasts`` so the
        logic is shared with the WebSocket preview handlers.
        """
        await _fetch_forecasts(self.hass, self._widgets, states)

    async def _async_fetch_history(self, states: dict[str, Any]) -> None:
        """Fetch state history for sensor widgets and inject into states.

        Delegates to the module-level ``_fetch_history`` so the logic
        is shared with the WebSocket preview handlers.

        Args:
            states: Mutable states dict; history data is injected
                in-place for sensor entities.
        """
        await _fetch_history(self.hass, self._widgets, states)

    def _build_states(self) -> dict[str, Any]:
        """Snapshot all HA states as a plain dict for the renderer."""
        result: dict[str, Any] = {}
        for state in self.hass.states.async_all():
            result[state.entity_id] = {
                "state": state.state,
                "attributes": dict(state.attributes),
            }
        return result

    @property
    def etag(self) -> str | None:
        """SHA-256 ETag of the last rendered image, or None if not
        yet rendered.
        """
        return self._etag

    async def async_image(self) -> bytes | None:
        """Return the latest rendered PNG bytes."""
        return self._rendered

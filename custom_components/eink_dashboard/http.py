# Copyright 2026 Andreas Schneider
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Authenticated layout API and public image HTTP views."""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .battery import build_entity_state, resolve_battery_level
from .const import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DEVICE_PRESETS,
    DOMAIN,
    MAX_WIDGETS,
    WidgetType,
)

_LOGGER = logging.getLogger(__name__)


class EinkLayoutView(HomeAssistantView):
    """Authenticated API view to read and write the widget layout."""

    url = "/api/eink_dashboard/{entry_id}/layout"
    name = "api:eink_dashboard:layout"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Return the current widget list and display config as JSON."""
        hass = request.app["hass"]
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            raise web.HTTPNotFound()

        widgets = entry_data["widgets"]
        entry = entry_data["entry"]
        width = entry.options.get("width", DEFAULT_WIDTH)
        height = entry.options.get("height", DEFAULT_HEIGHT)

        device_model = entry.options.get("device_model", "custom")
        preset = DEVICE_PRESETS.get(device_model, DEVICE_PRESETS["custom"])

        battery_entity_id = entry.options.get("battery_entity_id")
        states: dict = {}
        if battery_entity_id:
            entity_state = build_entity_state(hass, battery_entity_id)
            if entity_state is not None:
                states[battery_entity_id] = entity_state
        device_battery_level, _ = resolve_battery_level(
            battery_entity_id,
            states,
            entry_data.get("battery_sensor"),
        )

        return web.json_response(
            {
                "widgets": widgets,
                "display": {
                    "width": width,
                    "height": height,
                    "grayscale_levels": preset.grayscale_levels,
                },
                "device": {
                    "name": entry.title,
                    "model": device_model,
                    "model_label": preset.label,
                    "orientation": entry.options.get(
                        "orientation", "portrait"
                    ),
                    "area_id": entry.options.get("area_id"),
                    "has_webhooks": bool(
                        entry.options.get("webhook_urls", [])
                    ),
                    "device_battery_level": device_battery_level,
                },
            }
        )

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Validate and persist a new widget list, then trigger a refresh."""
        hass = request.app["hass"]
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            raise web.HTTPNotFound()

        try:
            body = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid JSON") from None

        if not isinstance(body, list):
            raise web.HTTPBadRequest(text="Body must be a list")

        if len(body) > MAX_WIDGETS:
            raise web.HTTPBadRequest(text="Too many widgets")

        valid_types = {t.value for t in WidgetType}
        _allowed_field_types = (str, int, float, bool, list, type(None))
        for widget in body:
            if not isinstance(widget, dict):
                raise web.HTTPBadRequest(text="Each widget must be an object")
            if widget.get("type") not in valid_types:
                raise web.HTTPBadRequest(
                    text=f"Invalid widget type: {widget.get('type')}"
                )
            for key, val in widget.items():
                if key != "type" and not isinstance(val, _allowed_field_types):
                    raise web.HTTPBadRequest(
                        text=f"Invalid value type for field '{key}'"
                    )

        await entry_data["store"].async_save(body)
        entry_data["widgets"] = body
        entity = entry_data["entity"]
        await entity.async_request_refresh(body)

        return web.json_response({"status": "ok"})


class EinkPublicImageView(HomeAssistantView):
    """Unauthenticated view serving the rendered PNG with ETag/304 support."""

    url = "/api/eink_dashboard/{entry_id}/image.png"
    name = "api:eink_dashboard:image"
    requires_auth = False

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Serve the latest rendered PNG, honouring If-None-Match."""
        hass = request.app["hass"]
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            raise web.HTTPNotFound()

        entity = entry_data["entity"]
        image_bytes = await entity.async_image()
        if image_bytes is None:
            raise web.HTTPServiceUnavailable()

        # Battery arrives on every poll, even when returning 304.
        battery_str = request.query.get("batteryLevel")
        if battery_str is not None:
            try:
                level = max(0, min(100, int(float(battery_str))))
            except (ValueError, TypeError):
                level = None
            if level is not None:
                sensor = entry_data.get("battery_sensor")
                if sensor is not None:
                    is_charging = request.query.get("isCharging") == "1"
                    sensor.update_battery(level, is_charging)
                    _LOGGER.info(
                        "E-Ink device request: battery=%d%%, charging=%s",
                        level,
                        is_charging,
                    )

        etag = entity.etag

        if_none_match = request.headers.get("If-None-Match")
        if if_none_match is not None and if_none_match in ("*", etag):
            _LOGGER.info("ETag hit (%s), returning 304", etag)
            resp = web.Response(status=304)
            resp.headers["ETag"] = etag
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        _LOGGER.info(
            "Serving image: %d bytes, etag=%s", len(image_bytes), etag
        )
        response = web.Response(
            body=image_bytes,
            content_type="image/png",
        )
        response.headers["Cache-Control"] = "no-cache"
        if etag is not None:
            response.headers["ETag"] = etag
        return response

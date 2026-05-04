from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DEVICE_PRESETS,
    DOMAIN,
    MAX_WIDGETS,
    WidgetType,
)


class EinkLayoutView(HomeAssistantView):
    url = "/api/eink_dashboard/{entry_id}/layout"
    name = "api:eink_dashboard:layout"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        hass = request.app["hass"]
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            raise web.HTTPNotFound()

        widgets = entry_data["widgets"]
        entry = entry_data["entry"]
        width = entry.options.get("width", DEFAULT_WIDTH)
        height = entry.options.get("height", DEFAULT_HEIGHT)

        device_model = entry.data.get("device_model", "custom")
        preset = DEVICE_PRESETS.get(device_model, DEVICE_PRESETS["custom"])

        return web.json_response(
            {
                "widgets": widgets,
                "display": {"width": width, "height": height},
                "device": {
                    "model": device_model,
                    "model_label": preset.label,
                    "orientation": entry.data.get("orientation", "portrait"),
                    "area_id": entry.data.get("area_id"),
                    "has_webhooks": bool(
                        entry.options.get("webhook_urls", [])
                    ),
                },
            }
        )

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
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
    url = "/api/eink_dashboard/{entry_id}/image.png"
    name = "api:eink_dashboard:image"
    requires_auth = False

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        hass = request.app["hass"]
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            raise web.HTTPNotFound()

        entity = entry_data["entity"]
        image_bytes = await entity.async_image()
        if image_bytes is None:
            raise web.HTTPServiceUnavailable()

        etag = entity.etag

        if_none_match = request.headers.get("If-None-Match")
        if if_none_match in ("*", etag):
            resp = web.Response(status=304)
            resp.headers["ETag"] = etag
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        response = web.Response(
            body=image_bytes,
            content_type="image/png",
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["ETag"] = etag
        return response

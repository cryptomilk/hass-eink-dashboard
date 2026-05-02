from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DEFAULT_HEIGHT, DEFAULT_WIDTH, DOMAIN


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

        return web.json_response(
            {"widgets": widgets, "display": {"width": width, "height": height}}
        )


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

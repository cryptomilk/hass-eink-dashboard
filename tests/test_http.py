from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from custom_components.eink_dashboard.const import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
)
from custom_components.eink_dashboard.http import (
    EinkLayoutView,
    EinkPublicImageView,
)

PNG_STUB = b"\x89PNG_STUB_DATA"
PNG_ETAG = f'"{hashlib.sha256(PNG_STUB).hexdigest()}"'


def _make_entity(image_bytes: bytes | None = PNG_STUB) -> MagicMock:
    entity = MagicMock()
    entity.async_image = AsyncMock(return_value=image_bytes)
    if image_bytes:
        entity.etag = f'"{hashlib.sha256(image_bytes).hexdigest()}"'
    else:
        entity.etag = None
    return entity


def _make_request(
    entry_id: str = "test_entry",
    entity: MagicMock | None = None,
    headers: dict[str, str] | None = None,
    *,
    entry_missing: bool = False,
) -> web.Request:
    request = MagicMock(spec=web.Request)
    request.headers = headers or {}

    hass = MagicMock()
    if entry_missing:
        hass.data = {}
    else:
        ent = entity if entity is not None else _make_entity()
        hass.data = {
            "eink_dashboard": {
                entry_id: {"entity": ent},
            },
        }

    request.app = {"hass": hass}
    return request


class TestEinkPublicImageView:
    def test_view_attributes(self) -> None:
        view = EinkPublicImageView()
        assert "eink_dashboard" in view.url
        assert "image.png" in view.url
        assert view.requires_auth is False

    async def test_returns_png_with_etag(self) -> None:
        view = EinkPublicImageView()
        request = _make_request()

        response = await view.get(request, "test_entry")

        assert response.status == 200
        assert response.content_type == "image/png"
        assert response.body == PNG_STUB
        assert "ETag" in response.headers
        assert response.headers["Cache-Control"] == "no-cache"

    async def test_etag_is_sha256(self) -> None:
        view = EinkPublicImageView()
        request = _make_request()

        response = await view.get(request, "test_entry")

        assert response.headers["ETag"] == PNG_ETAG

    async def test_304_on_matching_etag(self) -> None:
        view = EinkPublicImageView()
        request = _make_request(headers={"If-None-Match": PNG_ETAG})

        response = await view.get(request, "test_entry")

        assert response.status == 304
        assert response.body is None
        assert response.headers["ETag"] == PNG_ETAG
        assert response.headers["Cache-Control"] == "no-cache"

    async def test_304_on_wildcard_etag(self) -> None:
        view = EinkPublicImageView()
        request = _make_request(headers={"If-None-Match": "*"})

        response = await view.get(request, "test_entry")

        assert response.status == 304
        assert response.headers["ETag"] == PNG_ETAG

    async def test_200_on_mismatched_etag(self) -> None:
        view = EinkPublicImageView()
        request = _make_request(headers={"If-None-Match": '"stale"'})

        response = await view.get(request, "test_entry")

        assert response.status == 200
        assert response.body == PNG_STUB

    async def test_missing_entry_raises_404(self) -> None:
        view = EinkPublicImageView()
        request = _make_request(entry_missing=True)

        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "test_entry")

    async def test_no_image_raises_503(self) -> None:
        view = EinkPublicImageView()
        entity = _make_entity(image_bytes=None)
        request = _make_request(entity=entity)

        with pytest.raises(web.HTTPServiceUnavailable):
            await view.get(request, "test_entry")


def _make_layout_request(
    entry_id: str = "test_entry",
    widgets: list | None = None,
    options: dict | None = None,
    *,
    entry_missing: bool = False,
) -> web.Request:
    request = MagicMock(spec=web.Request)
    hass = MagicMock()
    if entry_missing:
        hass.data = {}
    else:
        entry = MagicMock()
        entry.options = options or {"width": 758, "height": 1024}
        hass.data = {
            "eink_dashboard": {
                entry_id: {
                    "widgets": widgets or [],
                    "entry": entry,
                },
            },
        }
    request.app = {"hass": hass}
    return request


class TestEinkLayoutView:
    def test_layout_view_attributes(self) -> None:
        view = EinkLayoutView()
        assert "eink_dashboard" in view.url
        assert "layout" in view.url
        assert view.requires_auth is True

    async def test_returns_layout_json(self) -> None:
        widgets = [{"type": "separator", "y": 50}]
        view = EinkLayoutView()
        request = _make_layout_request(widgets=widgets)

        response = await view.get(request, "test_entry")

        assert response.status == 200
        body = json.loads(response.text)
        assert body["widgets"] == widgets
        assert body["display"] == {"width": 758, "height": 1024}

    async def test_missing_entry_raises_404(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(entry_missing=True)

        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "test_entry")

    async def test_default_dimensions(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(options={})

        response = await view.get(request, "test_entry")

        body = json.loads(response.text)
        assert body["display"]["width"] == DEFAULT_WIDTH
        assert body["display"]["height"] == DEFAULT_HEIGHT

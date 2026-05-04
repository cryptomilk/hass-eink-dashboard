from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from custom_components.eink_dashboard.const import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    WidgetType,
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
    query: dict[str, str] | None = None,
    battery_sensor: MagicMock | None = None,
) -> web.Request:
    request = MagicMock(spec=web.Request)
    request.headers = headers or {}
    request.query = query if query is not None else {}

    hass = MagicMock()
    if entry_missing:
        hass.data = {}
    else:
        ent = entity if entity is not None else _make_entity()
        entry_data: dict = {"entity": ent}
        if battery_sensor is not None:
            entry_data["battery_sensor"] = battery_sensor
        hass.data = {
            "eink_dashboard": {
                entry_id: entry_data,
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

    async def test_200_on_no_etag_header(self) -> None:
        view = EinkPublicImageView()
        request = _make_request()  # no If-None-Match header

        response = await view.get(request, "test_entry")

        assert response.status == 200
        assert response.body == PNG_STUB

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

    async def test_battery_params_update_sensor(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            query={"batteryLevel": "78", "isCharging": "1"},
            battery_sensor=sensor,
        )

        await view.get(request, "test_entry")

        sensor.update_battery.assert_called_once_with(78, True)

    async def test_battery_not_charging(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            query={"batteryLevel": "50", "isCharging": "0"},
            battery_sensor=sensor,
        )

        await view.get(request, "test_entry")

        sensor.update_battery.assert_called_once_with(50, False)

    async def test_battery_no_params_no_sensor_call(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(query={}, battery_sensor=sensor)

        await view.get(request, "test_entry")

        sensor.update_battery.assert_not_called()

    async def test_battery_invalid_value_ignored(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            query={"batteryLevel": "abc"}, battery_sensor=sensor
        )

        await view.get(request, "test_entry")

        sensor.update_battery.assert_not_called()

    async def test_battery_no_sensor_registered(self) -> None:
        view = EinkPublicImageView()
        request = _make_request(query={"batteryLevel": "50"})

        response = await view.get(request, "test_entry")

        assert response.status == 200

    async def test_battery_missing_is_charging_defaults_false(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            query={"batteryLevel": "50"}, battery_sensor=sensor
        )

        await view.get(request, "test_entry")

        sensor.update_battery.assert_called_once_with(50, False)

    async def test_battery_clamped_above_100(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            query={"batteryLevel": "150"}, battery_sensor=sensor
        )

        await view.get(request, "test_entry")

        sensor.update_battery.assert_called_once_with(100, False)

    async def test_battery_clamped_below_0(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            query={"batteryLevel": "-5"}, battery_sensor=sensor
        )

        await view.get(request, "test_entry")

        sensor.update_battery.assert_called_once_with(0, False)

    async def test_battery_float_truncated(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            query={"batteryLevel": "78.9"}, battery_sensor=sensor
        )

        await view.get(request, "test_entry")

        sensor.update_battery.assert_called_once_with(78, False)

    async def test_battery_updated_on_304(self) -> None:
        view = EinkPublicImageView()
        sensor = MagicMock()
        request = _make_request(
            headers={"If-None-Match": PNG_ETAG},
            query={"batteryLevel": "78", "isCharging": "1"},
            battery_sensor=sensor,
        )

        response = await view.get(request, "test_entry")

        assert response.status == 304
        sensor.update_battery.assert_called_once_with(78, True)


def _make_layout_request(
    entry_id: str = "test_entry",
    widgets: list | None = None,
    options: dict | None = None,
    data: dict | None = None,
    *,
    entry_missing: bool = False,
    body: object = None,
    store: MagicMock | None = None,
    entity: MagicMock | None = None,
    json_error: bool = False,
) -> web.Request:
    request = MagicMock(spec=web.Request)
    hass = MagicMock()
    if json_error:
        request.json = AsyncMock(side_effect=ValueError("bad json"))
    elif body is not None:
        request.json = AsyncMock(return_value=body)
    if entry_missing:
        hass.data = {}
    else:
        ha_entry = MagicMock()
        ha_entry.title = "Test Dashboard"
        ha_entry.options = options or {"width": 758, "height": 1024}
        ha_entry.data = data or {}
        entry_data: dict = {
            "widgets": widgets or [],
            "entry": ha_entry,
        }
        if store is not None:
            entry_data["store"] = store
        if entity is not None:
            entry_data["entity"] = entity
        hass.data = {"eink_dashboard": {entry_id: entry_data}}
    request.app = {"hass": hass}
    return request


def _make_store() -> MagicMock:
    store = MagicMock()
    store.async_save = AsyncMock()
    return store


def _make_post_entity() -> MagicMock:
    entity = MagicMock()
    entity.async_request_refresh = AsyncMock()
    return entity


class TestEinkLayoutView:
    def test_layout_view_attributes(self) -> None:
        view = EinkLayoutView()
        assert "eink_dashboard" in view.url
        assert "layout" in view.url
        assert view.requires_auth is True

    async def test_returns_layout_json(self) -> None:
        widgets = [{"type": "separator", "y": 50}]
        view = EinkLayoutView()
        request = _make_layout_request(
            widgets=widgets,
            options={
                "width": 758,
                "height": 1024,
                "device_model": "kindle_pw",
            },
        )

        response = await view.get(request, "test_entry")

        assert response.status == 200
        body = json.loads(response.text)
        assert body["widgets"] == widgets
        assert body["display"] == {"width": 758, "height": 1024}
        assert body["device"]["name"] == "Test Dashboard"
        assert body["device"]["model"] == "kindle_pw"
        assert body["device"]["model_label"] == "Kindle Paperwhite 1/2/3"
        assert body["device"]["orientation"] == "portrait"
        assert body["device"]["area_id"] is None
        assert body["device"]["has_webhooks"] is False

    async def test_device_metadata_from_entry_options(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(
            options={
                "width": 758,
                "height": 1024,
                "device_model": "kindle_pw4",
                "orientation": "landscape",
                "area_id": "kitchen",
            }
        )

        response = await view.get(request, "test_entry")

        device = json.loads(response.text)["device"]
        assert device["model"] == "kindle_pw4"
        assert device["model_label"] == "Kindle Paperwhite 4"
        assert device["orientation"] == "landscape"
        assert device["area_id"] == "kitchen"

    async def test_device_metadata_defaults(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(data={})

        response = await view.get(request, "test_entry")

        device = json.loads(response.text)["device"]
        assert device["model"] == "custom"
        assert device["model_label"] == "Custom"
        assert device["orientation"] == "portrait"
        assert device["area_id"] is None
        assert device["has_webhooks"] is False

    async def test_has_webhooks_true(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(
            options={
                "width": 758,
                "height": 1024,
                "webhook_urls": [
                    {"name": "trmnl", "url": "https://example.com"}
                ],
            },
            data={},
        )

        response = await view.get(request, "test_entry")

        device = json.loads(response.text)["device"]
        assert device["has_webhooks"] is True

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


class TestEinkLayoutViewPost:
    async def test_post_saves_and_returns_ok(self) -> None:
        widgets = [{"type": "separator", "y": 50}]
        store = _make_store()
        entity = _make_post_entity()
        view = EinkLayoutView()
        request = _make_layout_request(
            body=widgets, store=store, entity=entity
        )

        response = await view.post(request, "test_entry")

        assert response.status == 200
        assert json.loads(response.text) == {"status": "ok"}
        store.async_save.assert_called_once_with(widgets)
        entity.async_request_refresh.assert_called_once_with(widgets)

    async def test_post_updates_in_memory_widgets(self) -> None:
        new_widgets = [{"type": "text", "text": "hi"}]
        store = _make_store()
        entity = _make_post_entity()
        view = EinkLayoutView()
        request = _make_layout_request(
            widgets=[], body=new_widgets, store=store, entity=entity
        )
        hass = request.app["hass"]

        await view.post(request, "test_entry")

        assert hass.data["eink_dashboard"]["test_entry"]["widgets"] == (
            new_widgets
        )

    async def test_post_missing_entry_raises_404(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(entry_missing=True, body=[])

        with pytest.raises(web.HTTPNotFound):
            await view.post(request, "test_entry")

    async def test_post_invalid_json_raises_400(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(
            body=None,
            json_error=True,
            store=_make_store(),
            entity=_make_post_entity(),
        )

        with pytest.raises(web.HTTPBadRequest):
            await view.post(request, "test_entry")

    async def test_post_non_list_raises_400(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(
            body={"type": "text"},
            store=_make_store(),
            entity=_make_post_entity(),
        )

        with pytest.raises(web.HTTPBadRequest):
            await view.post(request, "test_entry")

    async def test_post_invalid_widget_type_raises_400(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(
            body=[{"type": "bogus"}],
            store=_make_store(),
            entity=_make_post_entity(),
        )

        with pytest.raises(web.HTTPBadRequest):
            await view.post(request, "test_entry")

    async def test_post_missing_type_key_raises_400(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(
            body=[{"x": 10}],
            store=_make_store(),
            entity=_make_post_entity(),
        )

        with pytest.raises(web.HTTPBadRequest):
            await view.post(request, "test_entry")

    async def test_post_non_dict_widget_raises_400(self) -> None:
        view = EinkLayoutView()
        request = _make_layout_request(
            body=["not a dict"],
            store=_make_store(),
            entity=_make_post_entity(),
        )

        with pytest.raises(web.HTTPBadRequest):
            await view.post(request, "test_entry")

    async def test_post_empty_list_succeeds(self) -> None:
        store = _make_store()
        entity = _make_post_entity()
        view = EinkLayoutView()
        request = _make_layout_request(body=[], store=store, entity=entity)

        response = await view.post(request, "test_entry")

        assert response.status == 200
        store.async_save.assert_called_once_with([])

    async def test_post_all_valid_widget_types(self) -> None:
        widgets = [{"type": t.value} for t in WidgetType]
        store = _make_store()
        entity = _make_post_entity()
        view = EinkLayoutView()
        request = _make_layout_request(
            body=widgets, store=store, entity=entity
        )

        response = await view.post(request, "test_entry")

        assert response.status == 200
        store.async_save.assert_called_once_with(widgets)

    async def test_post_too_many_widgets_raises_400(self) -> None:
        widgets = [{"type": "separator", "y": i} for i in range(201)]
        view = EinkLayoutView()
        request = _make_layout_request(
            body=widgets, store=_make_store(), entity=_make_post_entity()
        )

        with pytest.raises(web.HTTPBadRequest):
            await view.post(request, "test_entry")

    async def test_post_nested_dict_field_raises_400(self) -> None:
        widgets = [{"type": "text", "text": {"nested": "bad"}}]
        view = EinkLayoutView()
        request = _make_layout_request(
            body=widgets, store=_make_store(), entity=_make_post_entity()
        )

        with pytest.raises(web.HTTPBadRequest):
            await view.post(request, "test_entry")

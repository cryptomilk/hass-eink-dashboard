from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.frontend import (
    DATA_EXTRA_MODULE_URL,
    UrlManager,
)
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eink_dashboard.const import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DOMAIN,
    WidgetType,
)
from custom_components.eink_dashboard.http import (
    EinkLayoutView,
    EinkPublicImageView,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import (
        ClientSessionGenerator,
    )

    from custom_components.eink_dashboard.image import EinkDashboardImage

PNG_STUB = b"\x89PNG_STUB_DATA"
PNG_ETAG = f'"{hashlib.sha256(PNG_STUB).hexdigest()}"'

_DEFAULT_OPTIONS = {
    "device_model": "custom",
    "width": 758,
    "height": 1024,
}


def _image_url(entry_id: str) -> str:
    return f"/api/eink_dashboard/{entry_id}/image.png"


def _layout_url(entry_id: str) -> str:
    return f"/api/eink_dashboard/{entry_id}/layout"


async def _setup_entry(
    hass: HomeAssistant,
    *,
    options: dict[str, Any] | None = None,
    widgets: list[dict[str, Any]] | None = None,
) -> MockConfigEntry:
    """Set up the integration with a config entry via the real HA machinery.

    Brings up the ``http`` component, registers a config entry, and
    forwards platform setup so the real image and battery sensor
    entities exist at ``hass.data[DOMAIN][entry.entry_id]``.

    Args:
        hass: Home Assistant instance.
        options: Config entry options, or None for a default preset.
        widgets: Widget list to expose to the views, or None to leave
            the store-loaded (empty) list untouched.

    Returns:
        The registered config entry.
    """
    assert await async_setup_component(hass, "http", {})
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(
        lambda _event, _url: None, []
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Dashboard",
        options=options or _DEFAULT_OPTIONS,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if widgets is not None:
        hass.data[DOMAIN][entry.entry_id]["widgets"] = widgets
    return entry


def _seed_rendered(
    entity: EinkDashboardImage,
    image: bytes = PNG_STUB,
    etag: str = PNG_ETAG,
) -> None:
    """Seed a rendered image and ETag directly onto the entity.

    Bypasses the render pipeline so HTTP-layer tests don't depend on
    a real SVG render having happened first.

    Args:
        entity: The image entity to seed.
        image: Rendered PNG bytes to store.
        etag: ETag string matching ``image``.
    """
    entity._rendered = image
    entity._etag = etag


class TestViewAttributes:
    def test_image_view_attributes(self) -> None:
        # Public image view has no auth requirement.
        view = EinkPublicImageView()
        assert "eink_dashboard" in view.url
        assert "image.png" in view.url
        assert view.requires_auth is False

    def test_layout_view_attributes(self) -> None:
        # Layout view requires authentication.
        view = EinkLayoutView()
        assert "eink_dashboard" in view.url
        assert "layout" in view.url
        assert view.requires_auth is True


class TestEinkPublicImageView:
    async def test_returns_png_with_etag(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # Image endpoint serves the rendered PNG with an ETag header.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)

        client = await hass_client_no_auth()
        resp = await client.get(_image_url(entry.entry_id))

        assert resp.status == 200
        assert resp.content_type == "image/png"
        assert await resp.read() == PNG_STUB
        assert "ETag" in resp.headers
        assert resp.headers["Cache-Control"] == "no-cache"

    async def test_etag_is_sha256(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # ETag value matches the sha256 hash of the image bytes.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)

        client = await hass_client_no_auth()
        resp = await client.get(_image_url(entry.entry_id))

        assert resp.headers["ETag"] == PNG_ETAG

    async def test_304_on_matching_etag(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # A matching If-None-Match returns 304 with no body.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)

        client = await hass_client_no_auth()
        resp = await client.get(
            _image_url(entry.entry_id),
            headers={"If-None-Match": PNG_ETAG},
        )

        assert resp.status == 304
        assert await resp.read() == b""
        assert resp.headers["ETag"] == PNG_ETAG
        assert resp.headers["Cache-Control"] == "no-cache"

    async def test_304_on_wildcard_etag(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # A wildcard If-None-Match always returns 304.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)

        client = await hass_client_no_auth()
        resp = await client.get(
            _image_url(entry.entry_id), headers={"If-None-Match": "*"}
        )

        assert resp.status == 304
        assert resp.headers["ETag"] == PNG_ETAG

    async def test_200_on_no_etag_header(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # No If-None-Match header means a full 200 response.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)

        client = await hass_client_no_auth()
        resp = await client.get(_image_url(entry.entry_id))

        assert resp.status == 200
        assert await resp.read() == PNG_STUB

    async def test_200_on_mismatched_etag(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # A stale If-None-Match means a full 200 response.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)

        client = await hass_client_no_auth()
        resp = await client.get(
            _image_url(entry.entry_id),
            headers={"If-None-Match": '"stale"'},
        )

        assert resp.status == 200
        assert await resp.read() == PNG_STUB

    async def test_missing_entry_raises_404(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # Unknown entry_id in the URL returns 404.
        await _setup_entry(hass)

        client = await hass_client_no_auth()
        resp = await client.get(_image_url("nonexistent_entry"))

        assert resp.status == 404

    async def test_no_image_raises_503(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # No rendered image yet means 503.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        entity._rendered = None

        client = await hass_client_no_auth()
        resp = await client.get(_image_url(entry.entry_id))

        assert resp.status == 503

    async def test_battery_params_update_sensor(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # Battery query params call update_battery on the sensor.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(
            _image_url(entry.entry_id),
            params={"batteryLevel": "78", "isCharging": "1"},
        )

        sensor.update_battery.assert_called_once_with(78, True)

    async def test_battery_not_charging(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # isCharging=0 maps to False.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(
            _image_url(entry.entry_id),
            params={"batteryLevel": "50", "isCharging": "0"},
        )

        sensor.update_battery.assert_called_once_with(50, False)

    async def test_battery_no_params_no_sensor_call(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # No battery query params means update_battery is not called.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(_image_url(entry.entry_id))

        sensor.update_battery.assert_not_called()

    async def test_battery_invalid_value_ignored(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # Non-numeric batteryLevel is silently ignored.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(
            _image_url(entry.entry_id), params={"batteryLevel": "abc"}
        )

        sensor.update_battery.assert_not_called()

    async def test_battery_no_sensor_registered(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # Missing sensor does not crash; still returns 200.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        del hass.data[DOMAIN][entry.entry_id]["battery_sensor"]

        client = await hass_client_no_auth()
        resp = await client.get(
            _image_url(entry.entry_id), params={"batteryLevel": "50"}
        )

        assert resp.status == 200

    async def test_battery_missing_is_charging_defaults_false(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # Missing isCharging defaults to False.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(
            _image_url(entry.entry_id), params={"batteryLevel": "50"}
        )

        sensor.update_battery.assert_called_once_with(50, False)

    async def test_battery_clamped_above_100(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # batteryLevel=150 is clamped to 100.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(
            _image_url(entry.entry_id), params={"batteryLevel": "150"}
        )

        sensor.update_battery.assert_called_once_with(100, False)

    async def test_battery_clamped_below_0(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # batteryLevel=-5 is clamped to 0.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(
            _image_url(entry.entry_id), params={"batteryLevel": "-5"}
        )

        sensor.update_battery.assert_called_once_with(0, False)

    async def test_battery_float_truncated(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # batteryLevel=78.9 is truncated to 78.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        await client.get(
            _image_url(entry.entry_id), params={"batteryLevel": "78.9"}
        )

        sensor.update_battery.assert_called_once_with(78, False)

    async def test_battery_updated_on_304(
        self, hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
    ) -> None:
        # Battery is still updated even on a 304 response.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        _seed_rendered(entity)
        sensor = MagicMock()
        hass.data[DOMAIN][entry.entry_id]["battery_sensor"] = sensor

        client = await hass_client_no_auth()
        resp = await client.get(
            _image_url(entry.entry_id),
            headers={"If-None-Match": PNG_ETAG},
            params={"batteryLevel": "78", "isCharging": "1"},
        )

        assert resp.status == 304
        sensor.update_battery.assert_called_once_with(78, True)


class TestEinkLayoutView:
    async def test_returns_layout_json(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Widgets, display config, and device metadata all round-trip.
        widgets = [{"type": "separator", "y": 50}]
        entry = await _setup_entry(
            hass,
            options={
                "width": 758,
                "height": 1024,
                "device_model": "kindle_pw",
            },
            widgets=widgets,
        )

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        assert resp.status == 200
        body = await resp.json()
        assert body["widgets"] == widgets
        assert body["display"] == {
            "width": 758,
            "height": 1024,
            "grayscale_levels": 16,
        }
        assert body["device"]["name"] == "Test Dashboard"
        assert body["device"]["model"] == "kindle_pw"
        assert body["device"]["model_label"] == "Kindle Paperwhite 1/2/3"
        assert body["device"]["orientation"] == "portrait"
        assert body["device"]["area_id"] is None
        assert body["device"]["has_webhooks"] is False

    async def test_device_metadata_from_entry_options(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Device metadata is read from entry options.
        entry = await _setup_entry(
            hass,
            options={
                "width": 758,
                "height": 1024,
                "device_model": "kindle_pw4",
                "orientation": "landscape",
                "area_id": "kitchen",
            },
        )

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["model"] == "kindle_pw4"
        assert device["model_label"] == "Kindle Paperwhite 4"
        assert device["orientation"] == "landscape"
        assert device["area_id"] == "kitchen"

    async def test_device_metadata_defaults(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Default model is "custom", default orientation is "portrait".
        entry = await _setup_entry(hass, options={})

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["model"] == "custom"
        assert device["model_label"] == "Custom"
        assert device["orientation"] == "portrait"
        assert device["area_id"] is None
        assert device["has_webhooks"] is False

    async def test_has_webhooks_true(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # has_webhooks is True when webhook_urls is non-empty.
        entry = await _setup_entry(
            hass,
            options={
                "width": 758,
                "height": 1024,
                "webhook_urls": [
                    {"name": "trmnl", "url": "https://example.com"}
                ],
            },
        )

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["has_webhooks"] is True

    async def test_missing_entry_raises_404(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Unknown entry_id in the URL returns 404.
        await _setup_entry(hass)

        client = await hass_client()
        resp = await client.get(_layout_url("nonexistent_entry"))

        assert resp.status == 404

    async def test_default_dimensions(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Empty options fall back to DEFAULT_WIDTH / DEFAULT_HEIGHT.
        entry = await _setup_entry(hass, options={})

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        body = await resp.json()
        assert body["display"]["width"] == DEFAULT_WIDTH
        assert body["display"]["height"] == DEFAULT_HEIGHT

    async def test_layout_includes_device_battery_level(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Battery level from the internal sensor appears in device metadata.
        entry = await _setup_entry(hass)
        sensor = hass.data[DOMAIN][entry.entry_id]["battery_sensor"]
        sensor.update_battery(72, True)

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["device_battery_level"] == 72

    async def test_layout_battery_level_none_without_sensor(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Battery is None when the sensor has never been updated.
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["device_battery_level"] is None

    async def test_layout_battery_from_entity_id(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # battery_entity_id option reads from real HA state.
        entry = await _setup_entry(
            hass,
            options={
                **_DEFAULT_OPTIONS,
                "battery_entity_id": "sensor.trmnl_battery",
            },
        )
        hass.states.async_set("sensor.trmnl_battery", "63")

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["device_battery_level"] == 63

    async def test_layout_battery_entity_id_priority_over_sensor(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # battery_entity_id wins even when the internal sensor also has
        # a value.
        entry = await _setup_entry(
            hass,
            options={
                **_DEFAULT_OPTIONS,
                "battery_entity_id": "sensor.trmnl_battery",
            },
        )
        sensor = hass.data[DOMAIN][entry.entry_id]["battery_sensor"]
        sensor.update_battery(50, False)
        hass.states.async_set("sensor.trmnl_battery", "77")

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["device_battery_level"] == 77

    async def test_layout_battery_entity_id_missing_state_falls_through(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Entity ID configured but no state exists: falls back to sensor.
        entry = await _setup_entry(
            hass,
            options={
                **_DEFAULT_OPTIONS,
                "battery_entity_id": "sensor.trmnl_battery",
            },
        )
        sensor = hass.data[DOMAIN][entry.entry_id]["battery_sensor"]
        sensor.update_battery(40, False)

        client = await hass_client()
        resp = await client.get(_layout_url(entry.entry_id))

        device = (await resp.json())["device"]
        assert device["device_battery_level"] == 40

    async def test_layout_get_rejects_unauthenticated(
        self,
        hass: HomeAssistant,
        hass_client_no_auth: ClientSessionGenerator,
    ) -> None:
        # Layout GET requires authentication.
        entry = await _setup_entry(hass)

        client = await hass_client_no_auth()
        resp = await client.get(_layout_url(entry.entry_id))

        assert resp.status == 401


class TestEinkLayoutViewPost:
    async def test_post_saves_and_returns_ok(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # POST persists widgets, refreshes the entity, and returns ok.
        widgets = [{"type": "separator", "y": 50}]
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        entity.async_request_refresh = AsyncMock()
        store = hass.data[DOMAIN][entry.entry_id]["store"]
        store.async_save = AsyncMock()

        client = await hass_client()
        resp = await client.post(_layout_url(entry.entry_id), json=widgets)

        assert resp.status == 200
        assert await resp.json() == {"status": "ok"}
        store.async_save.assert_called_once_with(widgets)
        entity.async_request_refresh.assert_called_once_with(widgets)

    async def test_post_updates_in_memory_widgets(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # The in-memory widgets list is updated after a successful POST.
        new_widgets = [{"type": "heading", "heading": "hi"}]
        entry = await _setup_entry(hass, widgets=[])
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        entity.async_request_refresh = AsyncMock()

        client = await hass_client()
        await client.post(_layout_url(entry.entry_id), json=new_widgets)

        assert hass.data[DOMAIN][entry.entry_id]["widgets"] == new_widgets

    async def test_post_missing_entry_raises_404(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Unknown entry_id in the URL returns 404.
        await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(_layout_url("nonexistent_entry"), json=[])

        assert resp.status == 404

    async def test_post_invalid_json_raises_400(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Malformed JSON body returns 400.
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(
            _layout_url(entry.entry_id),
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert resp.status == 400

    async def test_post_non_list_raises_400(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Body must be a list, not a dict.
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(
            _layout_url(entry.entry_id), json={"type": "heading"}
        )

        assert resp.status == 400

    async def test_post_invalid_widget_type_raises_400(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Unknown widget type returns 400.
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(
            _layout_url(entry.entry_id), json=[{"type": "bogus"}]
        )

        assert resp.status == 400

    async def test_post_missing_type_key_raises_400(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # A widget dict with no "type" key returns 400.
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(_layout_url(entry.entry_id), json=[{"x": 10}])

        assert resp.status == 400

    async def test_post_non_dict_widget_raises_400(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # A widget list item that is not a dict returns 400.
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(
            _layout_url(entry.entry_id), json=["not a dict"]
        )

        assert resp.status == 400

    async def test_post_empty_list_succeeds(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # An empty widget list is valid.
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        entity.async_request_refresh = AsyncMock()
        store = hass.data[DOMAIN][entry.entry_id]["store"]
        store.async_save = AsyncMock()

        client = await hass_client()
        resp = await client.post(_layout_url(entry.entry_id), json=[])

        assert resp.status == 200
        store.async_save.assert_called_once_with([])

    async def test_post_all_valid_widget_types(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # Every WidgetType enum value is accepted.
        widgets = [{"type": t.value} for t in WidgetType]
        entry = await _setup_entry(hass)
        entity = hass.data[DOMAIN][entry.entry_id]["entity"]
        entity.async_request_refresh = AsyncMock()
        store = hass.data[DOMAIN][entry.entry_id]["store"]
        store.async_save = AsyncMock()

        client = await hass_client()
        resp = await client.post(_layout_url(entry.entry_id), json=widgets)

        assert resp.status == 200
        store.async_save.assert_called_once_with(widgets)

    async def test_post_too_many_widgets_raises_400(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # More than MAX_WIDGETS (200) entries returns 400.
        widgets = [{"type": "separator", "y": i} for i in range(201)]
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(_layout_url(entry.entry_id), json=widgets)

        assert resp.status == 400

    async def test_post_nested_dict_field_raises_400(
        self, hass: HomeAssistant, hass_client: ClientSessionGenerator
    ) -> None:
        # A widget field value that is a nested dict returns 400.
        widgets = [{"type": "heading", "heading": {"nested": "bad"}}]
        entry = await _setup_entry(hass)

        client = await hass_client()
        resp = await client.post(_layout_url(entry.entry_id), json=widgets)

        assert resp.status == 400

    async def test_post_rejects_unauthenticated(
        self,
        hass: HomeAssistant,
        hass_client_no_auth: ClientSessionGenerator,
    ) -> None:
        # Layout POST requires authentication.
        entry = await _setup_entry(hass)

        client = await hass_client_no_auth()
        resp = await client.post(_layout_url(entry.entry_id), json=[])

        assert resp.status == 401

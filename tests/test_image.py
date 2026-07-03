from __future__ import annotations

import io
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.template import TemplateError
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eink_dashboard.const import (
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.eink_dashboard.image import (
    PUSH_MAX_IMAGE_BYTES,
    EinkDashboardImage,
    async_setup_entry,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant


def _make_entry(
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Dashboard",
        options=options or {"width": 200, "height": 100},
    )


def _png_from_bytes(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


@pytest.fixture(autouse=True)
def _patch_eink_image_hass():
    """Set entity.hass after EinkDashboardImage.__init__.

    Verified against HA core: Entity.hass is a class-level attribute
    initialised to None; ImageEntity.__init__ receives hass but does
    not store it (only passes it to get_async_client).  The entity
    platform sets self.hass during add_to_platform_start — tests that
    instantiate EinkDashboardImage directly need this workaround so
    that self.hass.is_stopping does not raise AttributeError.
    """
    _orig_init = EinkDashboardImage.__init__

    def _new_init(
        self: EinkDashboardImage, hass: object, entry: object
    ) -> None:
        _orig_init(self, hass, entry)
        self.hass = hass  # type: ignore[assignment]

    with patch.object(EinkDashboardImage, "__init__", _new_init):
        yield


@pytest.fixture
def make_entity(
    hass: HomeAssistant,
) -> Callable[
    [dict[str, Any] | None], tuple[EinkDashboardImage, MockConfigEntry]
]:
    """Build an EinkDashboardImage backed by a registered config entry.

    Returns a factory that creates a MockConfigEntry (registered via
    add_to_hass), seeds hass.data[DOMAIN][entry.entry_id], and
    constructs an EinkDashboardImage with async_write_ha_state mocked.
    """

    def _make(
        options: dict[str, Any] | None = None,
    ) -> tuple[EinkDashboardImage, MockConfigEntry]:
        entry = _make_entry(options)
        entry.add_to_hass(hass)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()
        return entity, entry

    return _make


class TestEinkDashboardImage:
    async def test_attributes_set_from_entry(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, entry = make_entity()

        assert entity._attr_name == "Test Dashboard"
        assert entity._attr_unique_id == entry.entry_id
        assert entity._attr_content_type == "image/png"

    async def test_device_info_set_from_entry(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, entry = make_entity()

        assert entity._attr_device_info == {
            "identifiers": {(DOMAIN, entry.entry_id)}
        }

    async def test_async_image_returns_none_before_refresh(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()

        result = await entity.async_image()
        assert result is None

    async def test_refresh_renders_png(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()

        await entity._async_refresh(None)

        result = await entity.async_image()
        assert result is not None
        img = _png_from_bytes(result)
        assert img.size == (200, 100)
        assert img.mode == "L"

    async def test_refresh_updates_timestamp(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()

        assert entity._attr_image_last_updated is None
        await entity._async_refresh(None)
        assert entity._attr_image_last_updated is not None

    async def test_refresh_skips_write_when_unchanged(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()

        await entity._async_refresh(None)
        entity.async_write_ha_state.reset_mock()

        await entity._async_refresh(None)
        entity.async_write_ha_state.assert_not_called()

    async def test_added_to_hass_sets_up_interval(
        self, hass: HomeAssistant, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()

        unsub = MagicMock()
        with patch(
            "custom_components.eink_dashboard.image.async_track_time_interval",
            return_value=unsub,
        ) as mock_track:
            await entity.async_added_to_hass()
            mock_track.assert_called_once()
            args = mock_track.call_args
            assert args[0][0] is hass
            assert args[0][2] == timedelta(seconds=DEFAULT_UPDATE_INTERVAL)

    async def test_remove_from_hass_cancels_interval(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()

        unsub = MagicMock()
        with patch(
            "custom_components.eink_dashboard.image.async_track_time_interval",
            return_value=unsub,
        ):
            await entity.async_added_to_hass()

        await entity.async_will_remove_from_hass()
        unsub.assert_called_once()

    async def test_set_widgets_affects_render(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()

        entity.set_widgets(
            [
                {
                    "type": "heading",
                    "x": 10,
                    "y": 10,
                    "heading": "Hello",
                }
            ]
        )
        await entity._async_refresh(None)

        result = await entity.async_image()
        assert result is not None
        img = _png_from_bytes(result)
        has_dark = any(
            img.getpixel((x, y)) < 128  # type: ignore[operator]
            for x in range(10, 100)
            for y in range(10, 40)
        )
        assert has_dark

    async def test_build_states_from_hass(
        self, hass: HomeAssistant, make_entity: Callable[..., Any]
    ) -> None:
        hass.states.async_set(
            "sensor.temp", "22", {"unit_of_measurement": "°C"}
        )

        entity, _entry = make_entity()

        states = entity._build_states()
        assert "sensor.temp" in states
        assert states["sensor.temp"]["state"] == "22"
        assert (
            states["sensor.temp"]["attributes"]["unit_of_measurement"] == "°C"
        )

    async def test_fetch_forecasts_merges_into_states(
        self, make_entity: Callable[..., Any]
    ) -> None:
        forecast_data = [
            {"datetime": "2025-05-04", "temperature": 18, "templow": 8},
        ]
        entity, _entry = make_entity()
        entity.set_widgets([{"type": "weather", "entity": "weather.home"}])

        states = {
            "weather.home": {
                "state": "sunny",
                "attributes": {"temperature": 20},
            }
        }
        # ServiceRegistry uses __slots__; patch the class, not the
        # instance.
        with patch(
            "homeassistant.core.ServiceRegistry.async_call",
            AsyncMock(
                return_value={
                    "weather.home": {"forecast": forecast_data},
                }
            ),
        ) as mock_call:
            await entity._async_fetch_forecasts(states)

        assert (
            states["weather.home"]["attributes"]["forecast"] == forecast_data
        )
        mock_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )

    async def test_fetch_forecasts_skips_missing_entity(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()
        entity.set_widgets([{"type": "weather", "entity": "weather.missing"}])

        states: dict[str, Any] = {}
        with patch(
            "homeassistant.core.ServiceRegistry.async_call", AsyncMock()
        ) as mock_call:
            await entity._async_fetch_forecasts(states)

        mock_call.assert_not_called()

    async def test_fetch_forecasts_handles_service_error(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()
        entity.set_widgets([{"type": "weather", "entity": "weather.home"}])

        states = {
            "weather.home": {
                "state": "sunny",
                "attributes": {"temperature": 20},
            }
        }
        with patch(
            "homeassistant.core.ServiceRegistry.async_call",
            AsyncMock(side_effect=Exception("service unavailable")),
        ):
            await entity._async_fetch_forecasts(states)

        assert "forecast" not in states["weather.home"]["attributes"]

    async def test_custom_update_interval(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(
            {"width": 200, "height": 100, "update_interval": 30}
        )

        with patch(
            "custom_components.eink_dashboard.image.async_track_time_interval",
            return_value=MagicMock(),
        ) as mock_track:
            await entity.async_added_to_hass()
            args = mock_track.call_args
            assert args[0][2] == timedelta(seconds=30)

    async def test_rotation_applied(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(
            {"width": 200, "height": 100, "rotation": 90}
        )

        await entity._async_refresh(None)

        result = await entity.async_image()
        assert result is not None
        img = _png_from_bytes(result)
        assert img.size == (100, 200)

    async def test_template_in_text_widget_is_resolved(
        self, hass: HomeAssistant, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()
        entity.set_widgets(
            [
                {
                    "type": "heading",
                    "x": 10,
                    "y": 10,
                    "heading": "{{ states('sensor.temp') }}",
                }
            ]
        )

        with patch(
            "custom_components.eink_dashboard.image.Template"
        ) as MockTemplate:
            instance = MockTemplate.return_value
            instance.is_static = False
            instance.async_render.return_value = "22"
            await entity._async_refresh(None)
            MockTemplate.assert_called_once_with(
                "{{ states('sensor.temp') }}", hass
            )
            instance.async_render.assert_called_once_with(parse_result=False)

        result = await entity.async_image()
        assert result is not None
        img = _png_from_bytes(result)
        has_dark = any(
            img.getpixel((x, y)) < 128  # type: ignore[operator]
            for x in range(10, 60)
            for y in range(10, 40)
        )
        assert has_dark

    async def test_static_text_skips_template_render(
        self, hass: HomeAssistant, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()
        entity.set_widgets(
            [
                {
                    "type": "heading",
                    "x": 10,
                    "y": 10,
                    "heading": "Hello",
                }
            ]
        )

        with patch(
            "custom_components.eink_dashboard.image.Template"
        ) as MockTemplate:
            instance = MockTemplate.return_value
            instance.is_static = True
            await entity._async_refresh(None)
            instance.async_render.assert_not_called()
            MockTemplate.assert_called_once_with("Hello", hass)

    async def test_template_error_falls_back_to_raw(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()
        entity.set_widgets(
            [
                {
                    "type": "heading",
                    "x": 10,
                    "y": 10,
                    "heading": "{{ bad }}",
                }
            ]
        )

        with patch(
            "custom_components.eink_dashboard.image.Template"
        ) as MockTemplate:
            instance = MockTemplate.return_value
            instance.is_static = False
            instance.async_render.side_effect = TemplateError("undefined")
            await entity._async_refresh(None)

        result = await entity.async_image()
        assert result is not None
        img = _png_from_bytes(result)
        has_dark = any(
            img.getpixel((x, y)) < 128  # type: ignore[operator]
            for x in range(10, 100)
            for y in range(10, 40)
        )
        assert has_dark

    async def test_non_text_widget_unaffected_by_templates(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity()
        entity.set_widgets([{"type": "separator", "y": 50}])

        with patch(
            "custom_components.eink_dashboard.image.Template"
        ) as MockTemplate:
            await entity._async_refresh(None)
            MockTemplate.assert_not_called()

    async def test_optimize_options_forwarded_to_render(
        self, make_entity: Callable[..., Any]
    ) -> None:
        from custom_components.eink_dashboard.render import render_dashboard

        entity, _entry = make_entity(
            {
                "width": 200,
                "height": 100,
                "optimize": True,
                "grayscale_levels": 4,
                "exposure": 1.5,
                "saturation": 0.8,
            }
        )

        with patch(
            "custom_components.eink_dashboard.image.render_dashboard",
            wraps=render_dashboard,
        ) as mock_render:
            await entity._async_refresh(None)
            config = mock_render.call_args[0][1]
            assert config["optimize"] is True
            assert config["grayscale_levels"] == 4
            assert config["exposure"] == 1.5
            assert config["saturation"] == 0.8

    async def test_locale_options_forwarded_to_render(
        self, make_entity: Callable[..., Any]
    ) -> None:
        # Locale values returned by _async_get_locale are placed in the
        # config dict passed to render_dashboard.
        from custom_components.eink_dashboard.render import render_dashboard

        entity, _entry = make_entity({"width": 200, "height": 100})

        locale_tuple = (
            "decimal_comma",
            "de",
            "monday",
            "dmy",
            "24",
        )
        with (
            patch(
                "custom_components.eink_dashboard.image._async_get_locale",
                return_value=locale_tuple,
            ),
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                wraps=render_dashboard,
            ) as mock_render,
        ):
            await entity._async_refresh(None)
            config = mock_render.call_args[0][1]
            assert config["number_format"] == "decimal_comma"
            assert config["language"] == "de"
            assert config["first_weekday"] == "monday"
            assert config["date_format"] == "dmy"
            assert config["time_format"] == "24"


class TestImagePlatformSetup:
    async def test_async_setup_entry(self, hass: HomeAssistant) -> None:
        entry = _make_entry()
        entry.add_to_hass(hass)
        widgets = [{"type": "separator", "y": 50}]
        hass.data[DOMAIN] = {entry.entry_id: {"widgets": widgets}}

        async_add_entities = MagicMock()
        await async_setup_entry(hass, entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities = async_add_entities.call_args[0][0]
        assert len(entities) == 1
        assert isinstance(entities[0], EinkDashboardImage)
        assert hass.data[DOMAIN][entry.entry_id]["entity"] is entities[0]
        assert entities[0]._widgets == widgets


_WEBHOOK_URL = "https://trmnl.com/api/x"
_WEBHOOK_OPTS = {
    "width": 200,
    "height": 100,
    "webhook_urls": [{"name": "Test", "url": _WEBHOOK_URL}],
}


class TestWebhookPush:
    async def test_push_skipped_on_initial_render(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(_WEBHOOK_OPTS)

        with (
            patch(
                "custom_components.eink_dashboard.image"
                ".async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
        ):
            await entity._async_refresh(None)
            mock_push.assert_not_called()

    async def test_push_fires_on_image_change(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(_WEBHOOK_OPTS)

        # Initial render (push skipped).
        await entity._async_refresh(None)

        mock_session = MagicMock()
        with (
            patch(
                "custom_components.eink_dashboard.image"
                ".async_get_clientsession",
                return_value=mock_session,
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                return_value=b"changed-image",
            ),
        ):
            await entity._async_refresh(None)
            mock_push.assert_called_once_with(
                mock_session,
                _WEBHOOK_URL,
                b"changed-image",
            )

    async def test_push_fires_for_each_webhook(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(
            {
                "width": 200,
                "height": 100,
                "webhook_urls": [
                    {"name": "Device 1", "url": "https://trmnl.com/api/1"},
                    {"name": "Device 2", "url": "https://trmnl.com/api/2"},
                ],
            }
        )

        # Initial render (push skipped).
        await entity._async_refresh(None)

        mock_session = MagicMock()
        with (
            patch(
                "custom_components.eink_dashboard.image"
                ".async_get_clientsession",
                return_value=mock_session,
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                return_value=b"changed-image",
            ),
        ):
            await entity._async_refresh(None)
            assert mock_push.call_count == 2
            pushed_urls = {call.args[1] for call in mock_push.call_args_list}
            assert pushed_urls == {
                "https://trmnl.com/api/1",
                "https://trmnl.com/api/2",
            }

    async def test_push_does_not_fire_when_unchanged(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(_WEBHOOK_OPTS)

        with (
            patch(
                "custom_components.eink_dashboard.image"
                ".async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
        ):
            await entity._async_refresh(None)
            mock_push.reset_mock()
            await entity._async_refresh(None)
            mock_push.assert_not_called()

    async def test_push_does_not_fire_without_webhook_urls(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity({"width": 200, "height": 100})

        # Initial render (push skipped).
        await entity._async_refresh(None)

        with (
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                return_value=b"changed-image",
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
        ):
            await entity._async_refresh(None)
            mock_push.assert_not_called()

    async def test_push_does_not_fire_with_empty_webhook_urls(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(
            {"width": 200, "height": 100, "webhook_urls": []}
        )

        # Initial render (push skipped).
        await entity._async_refresh(None)

        with (
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                return_value=b"changed-image",
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
        ):
            await entity._async_refresh(None)
            mock_push.assert_not_called()

    async def test_push_skipped_when_image_too_large(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(_WEBHOOK_OPTS)

        # Initial render (push skipped).
        await entity._async_refresh(None)

        oversized = b"x" * (PUSH_MAX_IMAGE_BYTES + 1)
        with (
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                return_value=oversized,
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
            patch(
                "custom_components.eink_dashboard.image._LOGGER"
            ) as mock_log,
        ):
            await entity._async_refresh(None)
            mock_push.assert_not_called()
            mock_log.warning.assert_called_once()

    async def test_push_rate_limited(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(_WEBHOOK_OPTS)

        # Initial render (push skipped).
        await entity._async_refresh(None)
        entity._last_push = 1.0

        with (
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                return_value=b"changed-image",
            ),
            patch(
                "custom_components.eink_dashboard.image"
                ".async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
            patch("custom_components.eink_dashboard.image.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 30.0
            await entity._async_refresh(None)
            mock_push.assert_not_called()
            assert entity._last_push == 1.0

    async def test_push_skipped_when_image_blank(
        self, make_entity: Callable[..., Any]
    ) -> None:
        entity, _entry = make_entity(_WEBHOOK_OPTS)

        # Initial render (push skipped).
        await entity._async_refresh(None)

        blank_png = io.BytesIO()
        Image.new("L", (200, 100), 255).save(blank_png, "PNG")
        blank_bytes = blank_png.getvalue()

        with (
            patch(
                "custom_components.eink_dashboard.image.render_dashboard",
                return_value=blank_bytes,
            ),
            patch(
                "custom_components.eink_dashboard.image.async_push_image",
                new_callable=AsyncMock,
            ) as mock_push,
        ):
            await entity._async_refresh(None)
            mock_push.assert_not_called()
            assert entity._rendered == blank_bytes

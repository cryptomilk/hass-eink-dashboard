from __future__ import annotations

import io
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers.template import TemplateError
from PIL import Image

from custom_components.eink_dashboard.const import (
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.eink_dashboard.image import (
    PUSH_MAX_IMAGE_BYTES,
    EinkDashboardImage,
    async_setup_entry,
)


def _make_entry(
    options: dict[str, Any] | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.title = "Test Dashboard"
    entry.options = options or {
        "width": 200,
        "height": 100,
    }
    return entry


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.states.async_all.return_value = []
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    return hass


def _png_from_bytes(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


class TestEinkDashboardImage:
    def test_attributes_set_from_entry(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)

        assert entity._attr_name == "Test Dashboard"
        assert entity._attr_unique_id == "test_entry_id"
        assert entity._attr_content_type == "image/png"

    def test_device_info_set_from_entry(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)

        assert entity._attr_device_info == {
            "identifiers": {(DOMAIN, "test_entry_id")}
        }

    async def test_async_image_returns_none_before_refresh(
        self,
    ) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)

        result = await entity.async_image()
        assert result is None

    async def test_refresh_renders_png(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        await entity._async_refresh(None)

        result = await entity.async_image()
        assert result is not None
        img = _png_from_bytes(result)
        assert img.size == (200, 100)
        assert img.mode == "L"

    async def test_refresh_updates_timestamp(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        assert entity._attr_image_last_updated is None
        await entity._async_refresh(None)
        assert entity._attr_image_last_updated is not None

    async def test_refresh_skips_write_when_unchanged(
        self,
    ) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        await entity._async_refresh(None)
        entity.async_write_ha_state.reset_mock()

        await entity._async_refresh(None)
        entity.async_write_ha_state.assert_not_called()

    async def test_added_to_hass_sets_up_interval(
        self,
    ) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

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
        self,
    ) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        unsub = MagicMock()
        with patch(
            "custom_components.eink_dashboard.image.async_track_time_interval",
            return_value=unsub,
        ):
            await entity.async_added_to_hass()

        await entity.async_will_remove_from_hass()
        unsub.assert_called_once()

    async def test_set_widgets_affects_render(
        self,
    ) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        entity.set_widgets(
            [
                {
                    "type": "text",
                    "x": 10,
                    "y": 10,
                    "text": "Hello",
                    "font_size": 20,
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

    async def test_build_states_from_hass(self) -> None:
        hass = _make_hass()
        state_obj = MagicMock()
        state_obj.entity_id = "sensor.temp"
        state_obj.state = "22"
        state_obj.attributes = {"unit_of_measurement": "°C"}
        hass.states.async_all.return_value = [state_obj]

        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)

        states = entity._build_states()
        assert "sensor.temp" in states
        assert states["sensor.temp"]["state"] == "22"
        assert (
            states["sensor.temp"]["attributes"]["unit_of_measurement"] == "°C"
        )

    async def test_fetch_forecasts_merges_into_states(self) -> None:
        hass = _make_hass()
        forecast_data = [
            {"datetime": "2025-05-04", "temperature": 18, "templow": 8},
        ]
        hass.services.async_call = AsyncMock(
            return_value={
                "weather.home": {"forecast": forecast_data},
            }
        )
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.set_widgets([{"type": "weather", "entity": "weather.home"}])

        states = {
            "weather.home": {
                "state": "sunny",
                "attributes": {"temperature": 20},
            }
        }
        await entity._async_fetch_forecasts(states)

        assert (
            states["weather.home"]["attributes"]["forecast"] == forecast_data
        )
        hass.services.async_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )

    async def test_fetch_forecasts_skips_missing_entity(self) -> None:
        hass = _make_hass()
        hass.services.async_call = AsyncMock()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.set_widgets([{"type": "weather", "entity": "weather.missing"}])

        states: dict[str, Any] = {}
        await entity._async_fetch_forecasts(states)

        hass.services.async_call.assert_not_called()

    async def test_fetch_forecasts_handles_service_error(self) -> None:
        hass = _make_hass()
        hass.services.async_call = AsyncMock(
            side_effect=Exception("service unavailable")
        )
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.set_widgets([{"type": "weather", "entity": "weather.home"}])

        states = {
            "weather.home": {
                "state": "sunny",
                "attributes": {"temperature": 20},
            }
        }
        await entity._async_fetch_forecasts(states)

        assert "forecast" not in states["weather.home"]["attributes"]

    async def test_custom_update_interval(self) -> None:
        hass = _make_hass()
        entry = _make_entry(
            {"width": 200, "height": 100, "update_interval": 30}
        )
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        with patch(
            "custom_components.eink_dashboard.image.async_track_time_interval",
            return_value=MagicMock(),
        ) as mock_track:
            await entity.async_added_to_hass()
            args = mock_track.call_args
            assert args[0][2] == timedelta(seconds=30)

    async def test_rotation_applied(self) -> None:
        hass = _make_hass()
        entry = _make_entry({"width": 200, "height": 100, "rotation": 90})
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        await entity._async_refresh(None)

        result = await entity.async_image()
        assert result is not None
        img = _png_from_bytes(result)
        assert img.size == (100, 200)

    async def test_template_in_text_widget_is_resolved(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()
        entity.set_widgets(
            [
                {
                    "type": "text",
                    "x": 10,
                    "y": 10,
                    "text": "{{ states('sensor.temp') }}",
                    "font_size": 20,
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

    async def test_static_text_skips_template_render(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()
        entity.set_widgets(
            [
                {
                    "type": "text",
                    "x": 10,
                    "y": 10,
                    "text": "Hello",
                    "font_size": 20,
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

    async def test_template_error_falls_back_to_raw(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()
        entity.set_widgets(
            [
                {
                    "type": "text",
                    "x": 10,
                    "y": 10,
                    "text": "{{ bad }}",
                    "font_size": 20,
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

    async def test_non_text_widget_unaffected_by_templates(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()
        entity.set_widgets([{"type": "separator", "y": 50}])

        with patch(
            "custom_components.eink_dashboard.image.Template"
        ) as MockTemplate:
            await entity._async_refresh(None)
            MockTemplate.assert_not_called()

    async def test_optimize_options_forwarded_to_render(self) -> None:
        from custom_components.eink_dashboard.render import render_dashboard

        hass = _make_hass()
        entry = _make_entry(
            {
                "width": 200,
                "height": 100,
                "optimize": True,
                "grayscale_levels": 4,
                "sharpness": 2.0,
                "contrast": 1.5,
            }
        )
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        with patch(
            "custom_components.eink_dashboard.image.render_dashboard",
            wraps=render_dashboard,
        ) as mock_render:
            await entity._async_refresh(None)
            config = mock_render.call_args[0][1]
            assert config["optimize"] is True
            assert config["grayscale_levels"] == 4
            assert config["sharpness"] == 2.0
            assert config["contrast"] == 1.5


class TestImagePlatformSetup:
    async def test_async_setup_entry(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        widgets = [{"type": "separator", "y": 50}]
        hass.data = {DOMAIN: {entry.entry_id: {"widgets": widgets}}}

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
    async def test_push_fires_on_image_change(self) -> None:
        hass = _make_hass()
        entry = _make_entry(_WEBHOOK_OPTS)
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

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
        ):
            await entity._async_refresh(None)
            mock_push.assert_called_once_with(
                mock_session,
                _WEBHOOK_URL,
                entity._rendered,
            )

    async def test_push_fires_for_each_webhook(self) -> None:
        hass = _make_hass()
        entry = _make_entry(
            {
                "width": 200,
                "height": 100,
                "webhook_urls": [
                    {"name": "Device 1", "url": "https://trmnl.com/api/1"},
                    {"name": "Device 2", "url": "https://trmnl.com/api/2"},
                ],
            }
        )
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

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
        ):
            await entity._async_refresh(None)
            assert mock_push.call_count == 2
            pushed_urls = {call.args[1] for call in mock_push.call_args_list}
            assert pushed_urls == {
                "https://trmnl.com/api/1",
                "https://trmnl.com/api/2",
            }

    async def test_push_does_not_fire_when_unchanged(self) -> None:
        hass = _make_hass()
        entry = _make_entry(_WEBHOOK_OPTS)
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

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
        self,
    ) -> None:
        hass = _make_hass()
        entry = _make_entry({"width": 200, "height": 100})
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        with patch(
            "custom_components.eink_dashboard.image.async_push_image",
            new_callable=AsyncMock,
        ) as mock_push:
            await entity._async_refresh(None)
            mock_push.assert_not_called()

    async def test_push_does_not_fire_with_empty_webhook_urls(
        self,
    ) -> None:
        hass = _make_hass()
        entry = _make_entry({"width": 200, "height": 100, "webhook_urls": []})
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

        with patch(
            "custom_components.eink_dashboard.image.async_push_image",
            new_callable=AsyncMock,
        ) as mock_push:
            await entity._async_refresh(None)
            mock_push.assert_not_called()

    async def test_push_skipped_when_image_too_large(self) -> None:
        hass = _make_hass()
        entry = _make_entry(_WEBHOOK_OPTS)
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()

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

    async def test_push_rate_limited(self) -> None:
        hass = _make_hass()
        entry = _make_entry(_WEBHOOK_OPTS)
        entity = EinkDashboardImage(hass, entry)
        entity.async_write_ha_state = MagicMock()
        entity._last_push = 1.0

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
            patch("custom_components.eink_dashboard.image.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 30.0
            await entity._async_refresh(None)
            mock_push.assert_not_called()
            assert entity._last_push == 1.0

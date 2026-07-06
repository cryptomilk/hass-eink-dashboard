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

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import websocket_api
from homeassistant.components.frontend import (
    DATA_EXTRA_MODULE_URL,
    UrlManager,
)
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eink_dashboard.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import (
        MockHAClientWebSocket,
        WebSocketGenerator,
    )

_DEFAULT_OPTIONS = {
    "device_model": "custom",
    "width": 758,
    "height": 1024,
}

_RENDER_SVG_TARGET = "custom_components.eink_dashboard.render_widget_svg"


async def _setup_entry(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    widgets: list[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[MockHAClientWebSocket, MockConfigEntry]:
    """Set up the integration and connect a WebSocket test client.

    Brings up the ``http`` component (required by both the
    integration's own ``async_setup`` and by ``hass_ws_client``),
    registers a config entry, and forwards platform setup so the
    real image and battery sensor entities exist. When ``widgets``
    is given it is written directly into ``hass.data`` after setup,
    bypassing the persisted store.

    Args:
        hass: Home Assistant instance.
        hass_ws_client: phacc fixture that connects a WS test client.
        widgets: Widget list to expose to the WS handlers, or None to
            leave the store-loaded (empty) list untouched.
        options: Config entry options, or None for a default preset.

    Returns:
        Tuple of (connected WebSocket test client, the config entry).
    """
    assert await async_setup_component(hass, "http", {})
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(
        lambda _event, _url: None, []
    )
    entry = MockConfigEntry(domain=DOMAIN, options=options or _DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if widgets is not None:
        hass.data[DOMAIN][entry.entry_id]["widgets"] = widgets
    client = await hass_ws_client(hass)
    return client, entry


async def _send_render_widget(
    client: MockHAClientWebSocket,
    entry_id: str,
    widget_index: int,
    *,
    widget: dict[str, Any] | None = None,
    msg_id: int = 1,
) -> dict[str, Any]:
    """Send an eink_dashboard/render_widget command.

    Builds the WebSocket message, sends it, and returns the parsed
    JSON response.

    Args:
        client: Connected WebSocket test client.
        entry_id: Config entry ID to target.
        widget_index: Index of the widget to render.
        widget: Optional widget override dict, sent as
            msg["widget"] when provided.
        msg_id: WebSocket message ID.

    Returns:
        The parsed JSON response dict.
    """
    msg: dict[str, Any] = {
        "id": msg_id,
        "type": "eink_dashboard/render_widget",
        "entry_id": entry_id,
        "widget_index": widget_index,
    }
    if widget is not None:
        msg["widget"] = widget
    await client.send_json(msg)
    return await client.receive_json()


async def _send_render_widgets(
    client: MockHAClientWebSocket,
    entry_id: str,
    *,
    widgets: list[dict[str, Any]] | None = None,
    msg_id: int = 1,
) -> dict[str, Any]:
    """Send an eink_dashboard/render_widgets command.

    Builds the WebSocket message, sends it, and returns the parsed
    JSON response.

    Args:
        client: Connected WebSocket test client.
        entry_id: Config entry ID to target.
        widgets: Optional widget list override, sent as
            msg["widgets"] when provided.
        msg_id: WebSocket message ID.

    Returns:
        The parsed JSON response dict.
    """
    msg: dict[str, Any] = {
        "id": msg_id,
        "type": "eink_dashboard/render_widgets",
        "entry_id": entry_id,
    }
    if widgets is not None:
        msg["widgets"] = widgets
    await client.send_json(msg)
    return await client.receive_json()


class TestWsRenderWidget:
    async def test_returns_svg_for_valid_widget(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Happy path: handler renders the requested widget and returns SVG.
        widget = {"type": "separator", "y": 50}
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[widget]
        )

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>"):
            result = await _send_render_widget(client, entry.entry_id, 0)

        assert result["success"]
        assert result["result"]["svg"] == "<svg/>"

    async def test_unknown_entry_id_sends_error(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Unknown entry_id: handler sends ERR_NOT_FOUND without rendering.
        client, _entry = await _setup_entry(hass, hass_ws_client)

        result = await _send_render_widget(client, "missing", 0)

        assert not result["success"]
        assert result["error"]["code"] == websocket_api.ERR_NOT_FOUND

    @pytest.mark.parametrize(
        ("widget_index", "expected_error"),
        [
            # Beyond list length: handler's own bounds check
            # returns ERR_NOT_FOUND.
            (5, websocket_api.ERR_NOT_FOUND),
            # Negative: rejected by vol.Range(min=0) before the
            # handler ever runs, so ERR_INVALID_FORMAT instead.
            (-1, websocket_api.ERR_INVALID_FORMAT),
        ],
    )
    async def test_bad_widget_index_sends_error(
        self,
        hass: HomeAssistant,
        hass_ws_client: WebSocketGenerator,
        widget_index: int,
        expected_error: str,
    ) -> None:
        # Invalid widget_index is rejected, either by the schema
        # or by the handler's own bounds check.
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[{"type": "separator"}]
        )

        result = await _send_render_widget(
            client, entry.entry_id, widget_index
        )

        assert not result["success"]
        assert result["error"]["code"] == expected_error

    async def test_config_uses_entry_dimensions(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Config dict passed to the renderer has width/height from options.
        widget = {"type": "separator"}
        client, entry = await _setup_entry(
            hass,
            hass_ws_client,
            widgets=[widget],
            options={"width": 400, "height": 300},
        )

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>") as mock_render:
            await _send_render_widget(client, entry.entry_id, 0)

        _, config = mock_render.call_args.args
        assert config["width"] == 400
        assert config["height"] == 300

    async def test_config_includes_entity_states(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # States from hass.states are passed through to the renderer.
        widget = {"type": "separator"}
        hass.states.async_set(
            "sensor.temp", "21.5", {"unit_of_measurement": "°C"}
        )
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[widget]
        )

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>") as mock_render:
            await _send_render_widget(client, entry.entry_id, 0)

        _, config = mock_render.call_args.args
        assert "sensor.temp" in config["states"]
        assert config["states"]["sensor.temp"]["state"] == "21.5"

    async def test_config_includes_grayscale_levels(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # grayscale_levels comes from entry.options, not the device preset.
        widget = {"type": "separator"}
        client, entry = await _setup_entry(
            hass,
            hass_ws_client,
            widgets=[widget],
            options={
                "device_model": "kindle_pw",
                "width": 758,
                "height": 1024,
                "grayscale_levels": 4,
            },
        )

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>") as mock_render:
            await _send_render_widget(client, entry.entry_id, 0)

        _, config = mock_render.call_args.args
        assert config["grayscale_levels"] == 4

    async def test_config_includes_battery_level(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Battery level and charging state appear in config once the
        # real battery sensor entity (created by the sensor platform)
        # has a value.
        widget = {"type": "device_battery"}
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[widget]
        )
        sensor = hass.data[DOMAIN][entry.entry_id]["battery_sensor"]
        sensor.update_battery(72, True)

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>") as mock_render:
            await _send_render_widget(client, entry.entry_id, 0)

        _, config = mock_render.call_args.args
        assert config["device_battery_level"] == 72
        assert config["device_battery_charging"] is True

    async def test_config_omits_battery_when_no_sensor(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Battery keys are absent when the sensor has never been updated.
        widget = {"type": "separator"}
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[widget]
        )

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>") as mock_render:
            await _send_render_widget(client, entry.entry_id, 0)

        _, config = mock_render.call_args.args
        assert "device_battery_level" not in config
        assert "device_battery_charging" not in config

    async def test_render_called_with_correct_widget(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # The renderer receives the widget at the requested index.
        widgets = [
            {"type": "separator"},
            {"type": "heading", "heading": "hello"},
        ]
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=widgets
        )

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>") as mock_render:
            await _send_render_widget(client, entry.entry_id, 1)

        widget_arg, _ = mock_render.call_args.args
        assert widget_arg == widgets[1]

    async def test_unknown_widget_type_sends_not_found(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # KeyError from renderer (unknown widget type): ERR_NOT_FOUND.
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[{"type": "separator"}]
        )

        with patch(_RENDER_SVG_TARGET, side_effect=KeyError("separator")):
            result = await _send_render_widget(client, entry.entry_id, 0)

        assert not result["success"]
        assert result["error"]["code"] == websocket_api.ERR_NOT_FOUND

    async def test_render_error_sends_unknown_error(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Non-KeyError renderer exception: handler sends ERR_UNKNOWN_ERROR.
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[{"type": "separator"}]
        )

        with patch(_RENDER_SVG_TARGET, side_effect=RuntimeError("boom")):
            result = await _send_render_widget(client, entry.entry_id, 0)

        assert not result["success"]
        assert result["error"]["code"] == websocket_api.ERR_UNKNOWN_ERROR

    async def test_widget_override_used_instead_of_stored(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # When msg["widget"] is provided the renderer receives it
        # instead of the stored widget at widget_index.
        stored = {"type": "separator"}
        override = {"type": "heading", "heading": "override"}
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[stored]
        )

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>") as mock_render:
            await _send_render_widget(
                client, entry.entry_id, 0, widget=override
            )

        widget_arg, _ = mock_render.call_args.args
        assert widget_arg == override

    async def test_widget_override_skips_index_bounds_check(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # A provided widget override does not require a valid
        # widget_index because the stored list is never consulted.
        client, entry = await _setup_entry(hass, hass_ws_client, widgets=[])
        override = {"type": "heading", "heading": "hi"}

        with patch(_RENDER_SVG_TARGET, return_value="<svg/>"):
            result = await _send_render_widget(
                client, entry.entry_id, 99, widget=override
            )

        assert result["success"]
        assert result["result"]["svg"] == "<svg/>"

    async def test_fetches_forecast_for_weather_widget(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Forecast data is fetched via weather.get_forecasts and
        # injected into config["states"] before rendering.
        hass.states.async_set("weather.home", "rainy", {"temperature": 9.8})
        widget = {"type": "weather", "entity": "weather.home"}
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[widget]
        )
        forecast_payload = [
            {"datetime": "2026-05-15T00:00:00", "temperature": 10}
        ]

        captured_config: dict[str, Any] = {}

        def _capture(w: Any, cfg: dict[str, Any]) -> str:
            captured_config.update(copy.deepcopy(cfg))
            return "<svg/>"

        with (
            patch(
                "homeassistant.core.ServiceRegistry.async_call",
                AsyncMock(
                    return_value={
                        "weather.home": {"forecast": forecast_payload}
                    }
                ),
            ) as mock_call,
            patch(_RENDER_SVG_TARGET, side_effect=_capture),
        ):
            result = await _send_render_widget(client, entry.entry_id, 0)

        attrs = captured_config["states"]["weather.home"]["attributes"]
        assert attrs["forecast"] == forecast_payload
        mock_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )
        assert result["success"]
        assert result["result"]["svg"] == "<svg/>"

    async def test_fetches_forecast_for_weather_widget_override(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Forecast data is fetched when a weather widget is provided
        # via msg["widget"] override (no stored widget consulted).
        hass.states.async_set("weather.home", "rainy", {"temperature": 9.8})
        client, entry = await _setup_entry(hass, hass_ws_client, widgets=[])
        forecast_payload = [
            {"datetime": "2026-05-15T00:00:00", "temperature": 10}
        ]

        captured_config: dict[str, Any] = {}

        def _capture(w: Any, cfg: dict[str, Any]) -> str:
            captured_config.update(copy.deepcopy(cfg))
            return "<svg/>"

        with (
            patch(
                "homeassistant.core.ServiceRegistry.async_call",
                AsyncMock(
                    return_value={
                        "weather.home": {"forecast": forecast_payload}
                    }
                ),
            ) as mock_call,
            patch(_RENDER_SVG_TARGET, side_effect=_capture),
        ):
            result = await _send_render_widget(
                client,
                entry.entry_id,
                0,
                widget={"type": "weather", "entity": "weather.home"},
            )

        attrs = captured_config["states"]["weather.home"]["attributes"]
        assert attrs["forecast"] == forecast_payload
        mock_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )
        assert result["success"]
        assert result["result"]["svg"] == "<svg/>"


class TestWsRenderWidgets:
    async def test_returns_all_svgs(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Happy path: all widgets are rendered and returned in order.
        widgets = [
            {"type": "separator"},
            {"type": "heading", "heading": "hello"},
        ]
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=widgets
        )

        with patch(_RENDER_SVG_TARGET, side_effect=["<svg1/>", "<svg2/>"]):
            result = await _send_render_widgets(client, entry.entry_id)

        assert result["success"]
        assert result["result"]["svgs"] == ["<svg1/>", "<svg2/>"]

    async def test_empty_widget_list(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Zero widgets returns an empty svgs list without error.
        client, entry = await _setup_entry(hass, hass_ws_client, widgets=[])

        result = await _send_render_widgets(client, entry.entry_id)

        assert result["success"]
        assert result["result"]["svgs"] == []

    async def test_unknown_entry_id_sends_error(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Unknown entry_id: handler sends ERR_NOT_FOUND without rendering.
        client, _entry = await _setup_entry(hass, hass_ws_client)

        result = await _send_render_widgets(client, "missing")

        assert not result["success"]
        assert result["error"]["code"] == websocket_api.ERR_NOT_FOUND

    async def test_config_built_once(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # _build_display_config is called once regardless of widget count.
        widgets = [{"type": "separator"}, {"type": "separator"}]
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=widgets
        )

        with (
            patch(
                "custom_components.eink_dashboard._build_display_config",
                return_value={
                    "width": 758,
                    "height": 1024,
                    "grayscale_levels": 2,
                    "states": {},
                },
            ) as mock_cfg,
            patch(_RENDER_SVG_TARGET, return_value="<svg/>"),
        ):
            await _send_render_widgets(client, entry.entry_id)

        mock_cfg.assert_called_once()

    async def test_unknown_widget_type_sends_not_found(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # KeyError from renderer (unknown widget type): ERR_NOT_FOUND.
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[{"type": "separator"}]
        )

        with patch(_RENDER_SVG_TARGET, side_effect=KeyError("separator")):
            result = await _send_render_widgets(client, entry.entry_id)

        assert not result["success"]
        assert result["error"]["code"] == websocket_api.ERR_NOT_FOUND

    async def test_render_error_sends_unknown_error(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Non-KeyError renderer exception: handler sends ERR_UNKNOWN_ERROR.
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[{"type": "separator"}]
        )

        with patch(_RENDER_SVG_TARGET, side_effect=RuntimeError("boom")):
            result = await _send_render_widgets(client, entry.entry_id)

        assert not result["success"]
        assert result["error"]["code"] == websocket_api.ERR_UNKNOWN_ERROR

    async def test_widgets_override_used_instead_of_stored(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # When msg["widgets"] is provided the renderer uses those
        # widgets instead of the stored list.
        stored = [{"type": "separator"}]
        override = [
            {"type": "heading", "heading": "a"},
            {"type": "heading", "heading": "b"},
        ]
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=stored
        )

        rendered_widgets: list[dict[str, Any]] = []

        def _capture(w: dict[str, Any], _cfg: dict[str, Any]) -> str:
            rendered_widgets.append(w)
            return "<svg/>"

        with patch(_RENDER_SVG_TARGET, side_effect=_capture):
            result = await _send_render_widgets(
                client, entry.entry_id, widgets=override
            )

        assert rendered_widgets == override
        assert result["success"]
        assert result["result"]["svgs"] == ["<svg/>", "<svg/>"]

    async def test_fetches_forecast_for_weather_widget(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        # Forecast data is fetched via weather.get_forecasts and
        # injected into config["states"] before rendering all widgets.
        hass.states.async_set("weather.home", "rainy", {"temperature": 9.8})
        widget = {"type": "weather", "entity": "weather.home"}
        client, entry = await _setup_entry(
            hass, hass_ws_client, widgets=[widget]
        )
        forecast_payload = [
            {"datetime": "2026-05-15T00:00:00", "temperature": 10}
        ]

        captured_configs: list[dict[str, Any]] = []

        def _capture(w: Any, cfg: dict[str, Any]) -> str:
            captured_configs.append(copy.deepcopy(cfg))
            return "<svg/>"

        with (
            patch(
                "homeassistant.core.ServiceRegistry.async_call",
                AsyncMock(
                    return_value={
                        "weather.home": {"forecast": forecast_payload}
                    }
                ),
            ) as mock_call,
            patch(_RENDER_SVG_TARGET, side_effect=_capture),
        ):
            result = await _send_render_widgets(client, entry.entry_id)

        assert captured_configs, "renderer was not called"
        attrs = captured_configs[0]["states"]["weather.home"]["attributes"]
        assert attrs["forecast"] == forecast_payload
        mock_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )
        assert result["success"]
        assert result["result"]["svgs"] == ["<svg/>"]

    @pytest.mark.parametrize(
        "bad_widgets",
        [["not-a-dict"], [None]],
        ids=["string-element", "none-element"],
    )
    async def test_widgets_override_rejects_non_dict(
        self,
        hass: HomeAssistant,
        hass_ws_client: WebSocketGenerator,
        bad_widgets: list[Any],
    ) -> None:
        # The [dict] schema rejects non-dict elements in the
        # widgets override before the handler ever runs.
        client, entry = await _setup_entry(hass, hass_ws_client)

        result = await _send_render_widgets(
            client, entry.entry_id, widgets=bad_widgets
        )

        assert not result["success"]
        assert result["error"]["code"] == websocket_api.ERR_INVALID_FORMAT

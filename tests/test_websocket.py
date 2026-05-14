from __future__ import annotations

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.components import websocket_api

from custom_components.eink_dashboard import (
    async_setup,
    ws_render_widget,
    ws_render_widgets,
)
from custom_components.eink_dashboard.const import DOMAIN


def _make_state(entity_id: str, state: str, attributes: dict) -> MagicMock:
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    s.attributes = attributes
    return s


def _make_hass(
    entry_id: str = "entry1",
    widgets: list | None = None,
    options: dict | None = None,
    states: list | None = None,
    battery_sensor: MagicMock | None = None,
    *,
    entry_missing: bool = False,
) -> MagicMock:
    hass = MagicMock()
    hass.http = MagicMock()
    hass.http.register_view = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()

    ha_entry = MagicMock()
    ha_entry.options = options or {
        "device_model": "custom",
        "width": 758,
        "height": 1024,
    }

    if entry_missing:
        hass.data = {}
    else:
        entry_data: dict = {
            "widgets": widgets or [],
            "entry": ha_entry,
        }
        if battery_sensor is not None:
            entry_data["battery_sensor"] = battery_sensor
        hass.data = {DOMAIN: {entry_id: entry_data}}

    mock_states = states or []
    hass.states.async_all = MagicMock(return_value=mock_states)

    # Execute the function synchronously so tests don't need asyncio.
    async def _executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor_job
    return hass


def _make_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


class TestWsRenderWidget:
    async def test_returns_svg_for_valid_widget(self) -> None:
        # Happy path: handler renders the requested widget and returns SVG.
        widget = {"type": "separator", "y": 50}
        hass = _make_hass(widgets=[widget])
        conn = _make_connection()
        msg = {"id": 1, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ):
            await ws_render_widget(hass, conn, msg)

        conn.send_result.assert_called_once_with(1, {"svg": "<svg/>"})
        conn.send_error.assert_not_called()

    async def test_unknown_entry_id_sends_error(self) -> None:
        # Unknown entry_id: handler sends ERR_NOT_FOUND without rendering.
        hass = _make_hass(entry_missing=True)
        conn = _make_connection()
        msg = {"id": 2, "entry_id": "missing", "widget_index": 0}

        await ws_render_widget(hass, conn, msg)

        conn.send_error.assert_called_once()
        args = conn.send_error.call_args.args
        assert args[0] == 2
        assert args[1] == websocket_api.ERR_NOT_FOUND
        conn.send_result.assert_not_called()

    async def test_widget_index_out_of_range_sends_error(self) -> None:
        # Index beyond widget list: handler sends ERR_NOT_FOUND.
        hass = _make_hass(widgets=[{"type": "separator"}])
        conn = _make_connection()
        msg = {"id": 3, "entry_id": "entry1", "widget_index": 5}

        await ws_render_widget(hass, conn, msg)

        conn.send_error.assert_called_once()
        assert conn.send_error.call_args.args[1] == websocket_api.ERR_NOT_FOUND
        conn.send_result.assert_not_called()

    async def test_negative_widget_index_sends_error(self) -> None:
        # Negative index: handler sends ERR_NOT_FOUND.
        hass = _make_hass(widgets=[{"type": "separator"}])
        conn = _make_connection()
        msg = {"id": 4, "entry_id": "entry1", "widget_index": -1}

        await ws_render_widget(hass, conn, msg)

        conn.send_error.assert_called_once()
        assert conn.send_error.call_args.args[1] == websocket_api.ERR_NOT_FOUND
        conn.send_result.assert_not_called()

    async def test_config_uses_entry_dimensions(self) -> None:
        # Config dict passed to the renderer has width/height from options.
        widget = {"type": "separator"}
        hass = _make_hass(
            widgets=[widget],
            options={"width": 400, "height": 300},
        )
        conn = _make_connection()
        msg = {"id": 5, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ) as mock_render:
            await ws_render_widget(hass, conn, msg)

        _, config = mock_render.call_args.args
        assert config["width"] == 400
        assert config["height"] == 300

    async def test_config_includes_entity_states(self) -> None:
        # States from hass.states are passed through to the renderer.
        widget = {"type": "separator"}
        mock_state = _make_state(
            "sensor.temp", "21.5", {"unit_of_measurement": "°C"}
        )
        hass = _make_hass(widgets=[widget], states=[mock_state])
        conn = _make_connection()
        msg = {"id": 6, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ) as mock_render:
            await ws_render_widget(hass, conn, msg)

        _, config = mock_render.call_args.args
        assert "sensor.temp" in config["states"]
        assert config["states"]["sensor.temp"]["state"] == "21.5"

    async def test_config_includes_grayscale_levels(self) -> None:
        # grayscale_levels comes from entry.options, not the device preset.
        widget = {"type": "separator"}
        hass = _make_hass(
            widgets=[widget],
            options={
                "device_model": "kindle_pw",
                "width": 758,
                "height": 1024,
                "grayscale_levels": 4,
            },
        )
        conn = _make_connection()
        msg = {"id": 8, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ) as mock_render:
            await ws_render_widget(hass, conn, msg)

        _, config = mock_render.call_args.args
        assert config["grayscale_levels"] == 4

    async def test_config_includes_battery_level(self) -> None:
        # Battery level and charging state appear in config when a sensor
        # is registered.
        widget = {"type": "device_battery"}
        sensor = MagicMock()
        sensor.native_value = 72
        sensor.extra_state_attributes = {"is_charging": True}
        hass = _make_hass(widgets=[widget], battery_sensor=sensor)
        conn = _make_connection()
        msg = {"id": 10, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ) as mock_render:
            await ws_render_widget(hass, conn, msg)

        _, config = mock_render.call_args.args
        assert config["device_battery_level"] == 72
        assert config["device_battery_charging"] is True

    async def test_config_omits_battery_when_no_sensor(self) -> None:
        # Battery keys are absent when no battery sensor is registered.
        widget = {"type": "separator"}
        hass = _make_hass(widgets=[widget])
        conn = _make_connection()
        msg = {"id": 11, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ) as mock_render:
            await ws_render_widget(hass, conn, msg)

        _, config = mock_render.call_args.args
        assert "device_battery_level" not in config
        assert "device_battery_charging" not in config

    async def test_render_called_with_correct_widget(self) -> None:
        # The renderer receives the widget at the requested index.
        widgets = [
            {"type": "separator"},
            {"type": "text", "text": "hello"},
        ]
        hass = _make_hass(widgets=widgets)
        conn = _make_connection()
        msg = {"id": 7, "entry_id": "entry1", "widget_index": 1}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ) as mock_render:
            await ws_render_widget(hass, conn, msg)

        widget_arg, _ = mock_render.call_args.args
        assert widget_arg == widgets[1]

    async def test_unknown_widget_type_sends_not_found(self) -> None:
        # KeyError from renderer (unknown widget type): ERR_NOT_FOUND.
        widget = {"type": "separator"}
        hass = _make_hass(widgets=[widget])
        conn = _make_connection()
        msg = {"id": 9, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=KeyError("separator"),
        ):
            await ws_render_widget(hass, conn, msg)

        conn.send_error.assert_called_once()
        args = conn.send_error.call_args.args
        assert args[0] == 9
        assert args[1] == websocket_api.ERR_NOT_FOUND
        conn.send_result.assert_not_called()

    async def test_render_error_sends_unknown_error(self) -> None:
        # Non-KeyError renderer exception: handler sends ERR_UNKNOWN_ERROR.
        widget = {"type": "separator"}
        hass = _make_hass(widgets=[widget])
        conn = _make_connection()
        msg = {"id": 12, "entry_id": "entry1", "widget_index": 0}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=RuntimeError("boom"),
        ):
            await ws_render_widget(hass, conn, msg)

        conn.send_error.assert_called_once()
        args = conn.send_error.call_args.args
        assert args[0] == 12
        assert args[1] == websocket_api.ERR_UNKNOWN_ERROR
        conn.send_result.assert_not_called()

    async def test_widget_override_used_instead_of_stored(
        self,
    ) -> None:
        # When msg["widget"] is provided the renderer receives it
        # instead of the stored widget at widget_index.
        stored = {"type": "separator"}
        override = {"type": "text", "text": "override"}
        hass = _make_hass(widgets=[stored])
        conn = _make_connection()
        msg = {
            "id": 13,
            "entry_id": "entry1",
            "widget_index": 0,
            "widget": override,
        }

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ) as mock_render:
            await ws_render_widget(hass, conn, msg)

        widget_arg, _ = mock_render.call_args.args
        assert widget_arg == override

    async def test_widget_override_skips_index_bounds_check(
        self,
    ) -> None:
        # A provided widget override does not require a valid
        # widget_index because the stored list is never consulted.
        hass = _make_hass(widgets=[])
        conn = _make_connection()
        override = {"type": "text", "text": "hi"}
        msg = {
            "id": 14,
            "entry_id": "entry1",
            "widget_index": 99,
            "widget": override,
        }

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            return_value="<svg/>",
        ):
            await ws_render_widget(hass, conn, msg)

        conn.send_result.assert_called_once_with(14, {"svg": "<svg/>"})
        conn.send_error.assert_not_called()

    async def test_fetches_forecast_for_weather_widget(
        self,
    ) -> None:
        # Forecast data is fetched via weather.get_forecasts and
        # injected into config["states"] before rendering.
        weather_state = _make_state(
            "weather.home", "rainy", {"temperature": 9.8}
        )
        widget = {
            "type": "weather",
            "entity": "weather.home",
        }
        hass = _make_hass(widgets=[widget], states=[weather_state])
        conn = _make_connection()
        msg = {
            "id": 15,
            "entry_id": "entry1",
            "widget_index": 0,
        }
        forecast_payload = [
            {"datetime": "2026-05-15T00:00:00", "temperature": 10}
        ]
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(
            return_value={"weather.home": {"forecast": forecast_payload}}
        )

        captured_config: dict = {}

        def _capture(w, cfg):
            captured_config.update(copy.deepcopy(cfg))
            return "<svg/>"

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=_capture,
        ):
            await ws_render_widget(hass, conn, msg)

        attrs = captured_config["states"]["weather.home"]["attributes"]
        assert attrs["forecast"] == forecast_payload
        hass.services.async_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )
        conn.send_result.assert_called_once_with(15, {"svg": "<svg/>"})
        conn.send_error.assert_not_called()

    async def test_fetches_forecast_for_weather_widget_override(
        self,
    ) -> None:
        # Forecast data is fetched when a weather widget is provided
        # via msg["widget"] override (no stored widget consulted).
        weather_state = _make_state(
            "weather.home", "rainy", {"temperature": 9.8}
        )
        hass = _make_hass(widgets=[], states=[weather_state])
        conn = _make_connection()
        msg = {
            "id": 16,
            "entry_id": "entry1",
            "widget_index": 0,
            "widget": {"type": "weather", "entity": "weather.home"},
        }
        forecast_payload = [
            {"datetime": "2026-05-15T00:00:00", "temperature": 10}
        ]
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(
            return_value={"weather.home": {"forecast": forecast_payload}}
        )

        captured_config: dict = {}

        def _capture(w, cfg):
            captured_config.update(copy.deepcopy(cfg))
            return "<svg/>"

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=_capture,
        ):
            await ws_render_widget(hass, conn, msg)

        attrs = captured_config["states"]["weather.home"]["attributes"]
        assert attrs["forecast"] == forecast_payload
        hass.services.async_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )
        conn.send_result.assert_called_once_with(16, {"svg": "<svg/>"})
        conn.send_error.assert_not_called()


class TestCommandRegistration:
    async def test_command_registered_on_setup(self) -> None:
        # async_setup() registers both WS commands via async_register_command.
        hass = _make_hass()
        hass.data = {}

        with patch(
            "custom_components.eink_dashboard.websocket_api"
            ".async_register_command"
        ) as mock_reg:
            await async_setup(hass, {})

        calls = [c.args for c in mock_reg.call_args_list]
        assert (hass, ws_render_widget) in calls
        assert (hass, ws_render_widgets) in calls


class TestWsRenderWidgets:
    async def test_returns_all_svgs(self) -> None:
        # Happy path: all widgets are rendered and returned in order.
        widgets = [
            {"type": "separator"},
            {"type": "text", "text": "hello"},
        ]
        hass = _make_hass(widgets=widgets)
        conn = _make_connection()
        msg = {"id": 1, "entry_id": "entry1"}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=["<svg1/>", "<svg2/>"],
        ):
            await ws_render_widgets(hass, conn, msg)

        conn.send_result.assert_called_once_with(
            1, {"svgs": ["<svg1/>", "<svg2/>"]}
        )
        conn.send_error.assert_not_called()

    async def test_empty_widget_list(self) -> None:
        # Zero widgets returns an empty svgs list without error.
        hass = _make_hass(widgets=[])
        conn = _make_connection()
        msg = {"id": 2, "entry_id": "entry1"}

        await ws_render_widgets(hass, conn, msg)

        conn.send_result.assert_called_once_with(2, {"svgs": []})
        conn.send_error.assert_not_called()

    async def test_unknown_entry_id_sends_error(self) -> None:
        # Unknown entry_id: handler sends ERR_NOT_FOUND without rendering.
        hass = _make_hass(entry_missing=True)
        conn = _make_connection()
        msg = {"id": 3, "entry_id": "missing"}

        await ws_render_widgets(hass, conn, msg)

        conn.send_error.assert_called_once()
        args = conn.send_error.call_args.args
        assert args[0] == 3
        assert args[1] == websocket_api.ERR_NOT_FOUND
        conn.send_result.assert_not_called()

    async def test_config_built_once(self) -> None:
        # _build_display_config is called once regardless of widget count.
        widgets = [{"type": "separator"}, {"type": "separator"}]
        hass = _make_hass(widgets=widgets)
        conn = _make_connection()
        msg = {"id": 4, "entry_id": "entry1"}

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
            patch(
                "custom_components.eink_dashboard.render_widget_svg",
                return_value="<svg/>",
            ),
        ):
            await ws_render_widgets(hass, conn, msg)

        mock_cfg.assert_called_once()

    async def test_unknown_widget_type_sends_not_found(self) -> None:
        # KeyError from renderer (unknown widget type): ERR_NOT_FOUND.
        hass = _make_hass(widgets=[{"type": "separator"}])
        conn = _make_connection()
        msg = {"id": 5, "entry_id": "entry1"}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=KeyError("separator"),
        ):
            await ws_render_widgets(hass, conn, msg)

        conn.send_error.assert_called_once()
        args = conn.send_error.call_args.args
        assert args[0] == 5
        assert args[1] == websocket_api.ERR_NOT_FOUND
        conn.send_result.assert_not_called()

    async def test_render_error_sends_unknown_error(self) -> None:
        # Non-KeyError renderer exception: handler sends ERR_UNKNOWN_ERROR.
        hass = _make_hass(widgets=[{"type": "separator"}])
        conn = _make_connection()
        msg = {"id": 6, "entry_id": "entry1"}

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=RuntimeError("boom"),
        ):
            await ws_render_widgets(hass, conn, msg)

        conn.send_error.assert_called_once()
        args = conn.send_error.call_args.args
        assert args[0] == 6
        assert args[1] == websocket_api.ERR_UNKNOWN_ERROR
        conn.send_result.assert_not_called()

    async def test_widgets_override_used_instead_of_stored(
        self,
    ) -> None:
        # When msg["widgets"] is provided the renderer uses those
        # widgets instead of the stored list.
        stored = [{"type": "separator"}]
        override = [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]
        hass = _make_hass(widgets=stored)
        conn = _make_connection()
        msg = {"id": 7, "entry_id": "entry1", "widgets": override}

        rendered_widgets: list = []

        def _capture(w, _cfg):
            rendered_widgets.append(w)
            return "<svg/>"

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=_capture,
        ):
            await ws_render_widgets(hass, conn, msg)

        assert rendered_widgets == override
        conn.send_result.assert_called_once_with(
            7, {"svgs": ["<svg/>", "<svg/>"]}
        )
        conn.send_error.assert_not_called()

    async def test_fetches_forecast_for_weather_widget(
        self,
    ) -> None:
        # Forecast data is fetched via weather.get_forecasts and
        # injected into config["states"] before rendering all widgets.
        weather_state = _make_state(
            "weather.home", "rainy", {"temperature": 9.8}
        )
        widget = {
            "type": "weather",
            "entity": "weather.home",
        }
        hass = _make_hass(widgets=[widget], states=[weather_state])
        conn = _make_connection()
        msg = {"id": 8, "entry_id": "entry1"}
        forecast_payload = [
            {"datetime": "2026-05-15T00:00:00", "temperature": 10}
        ]
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(
            return_value={"weather.home": {"forecast": forecast_payload}}
        )

        captured_configs: list[dict] = []

        def _capture(w, cfg):
            captured_configs.append(copy.deepcopy(cfg))
            return "<svg/>"

        with patch(
            "custom_components.eink_dashboard.render_widget_svg",
            side_effect=_capture,
        ):
            await ws_render_widgets(hass, conn, msg)

        assert captured_configs, "renderer was not called"
        attrs = captured_configs[0]["states"]["weather.home"]["attributes"]
        assert attrs["forecast"] == forecast_payload
        hass.services.async_call.assert_called_once_with(
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            blocking=True,
            return_response=True,
        )
        conn.send_result.assert_called_once_with(8, {"svgs": ["<svg/>"]})
        conn.send_error.assert_not_called()


class TestWidgetsOverrideSchema:
    """Verify the voluptuous [dict] schema rejects non-dict elements."""

    _SCHEMA = vol.Schema(
        {
            vol.Required("type"): str,
            vol.Required("entry_id"): str,
            vol.Optional("widgets"): [dict],
        }
    )

    def test_rejects_string_element(self) -> None:
        # Schema must reject a list containing a plain string.
        with pytest.raises(vol.Invalid):
            self._SCHEMA(
                {
                    "type": "eink_dashboard/render_widgets",
                    "entry_id": "entry1",
                    "widgets": ["not-a-dict"],
                }
            )

    def test_rejects_none_element(self) -> None:
        # Schema must reject a list containing None.
        with pytest.raises(vol.Invalid):
            self._SCHEMA(
                {
                    "type": "eink_dashboard/render_widgets",
                    "entry_id": "entry1",
                    "widgets": [None],
                }
            )

    def test_accepts_dict_elements(self) -> None:
        # Schema must accept a list of dicts.
        result = self._SCHEMA(
            {
                "type": "eink_dashboard/render_widgets",
                "entry_id": "entry1",
                "widgets": [{"type": "separator"}],
            }
        )
        assert result["widgets"] == [{"type": "separator"}]

    def test_accepts_empty_list(self) -> None:
        # Schema must accept an empty widget list.
        result = self._SCHEMA(
            {
                "type": "eink_dashboard/render_widgets",
                "entry_id": "entry1",
                "widgets": [],
            }
        )
        assert result["widgets"] == []

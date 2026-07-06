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

from typing import ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    PADDING,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.widgets.weather import (
    _build_weather_context,
)
from tests.helpers import (
    assert_all_white,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    content_bbox,
    make_config,
    render_to_image,
)

MOCK_WEATHER_STATE = {
    "weather.home": {
        "state": "sunny",
        "attributes": {
            "temperature": 22,
            "humidity": 58,
            "wind_speed": 12,
            "temperature_unit": "°C",
            "wind_speed_unit": "km/h",
            "pressure": 1013,
            "pressure_unit": "hPa",
            "cloud_coverage": 45,
            "precipitation_unit": "mm",
            "forecast": [
                {
                    "datetime": "2026-05-02T12:00:00",
                    "temperature": 24,
                    "templow": 16,
                    "condition": "sunny",
                    "precipitation": 0,
                },
                {
                    "datetime": "2026-05-03T12:00:00",
                    "temperature": 19,
                    "templow": 14,
                    "condition": "cloudy",
                    "precipitation": 5,
                },
                {
                    "datetime": "2026-05-04T12:00:00",
                    "temperature": 21,
                    "templow": 15,
                    "condition": "partlycloudy",
                    "precipitation": 0,
                },
            ],
        },
    },
}


class TestRenderWeather:
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 600,
        "height": 400,
        "states": MOCK_WEATHER_STATE,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def test_weather_draws_temperature(self) -> None:
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, PADDING + 106, 10, 300, 70)

    def test_weather_draws_forecast(self) -> None:
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "forecast_days": 3,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, 50, 110, 550, 200)

    def test_weather_missing_entity_is_noop(self) -> None:
        widgets = [
            {
                "type": "weather",
                "entity": "weather.nonexistent",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 600, 400)

    def test_weather_no_forecast(self) -> None:
        states = {
            "weather.home": {
                "state": "cloudy",
                "attributes": {
                    "temperature": 15,
                    "humidity": 70,
                    "wind_speed": 20,
                    "forecast": [],
                },
            }
        }
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(
            widgets,
            {"width": 600, "height": 300, "states": states},
        )
        assert img.size == (600, 300)
        assert_has_dark_pixels(
            img, PADDING, 10, PADDING + 90, 100, threshold=200
        )
        assert_has_dark_pixels(img, PADDING + 106, 10, 300, 70)

    def test_weather_icon_sunny(self) -> None:
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img, PADDING, 10, PADDING + 90, 100, threshold=200
        )

    def test_weather_landscape_layout(self) -> None:
        """Weather widget on a wide, short canvas (e.g. TRMNL OG 800x480)."""
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "forecast_days": 3,
            }
        ]
        config = self._config(width=800, height=480)
        img = render_to_image(widgets, config)
        # Temperature drawn in the left area
        assert_has_dark_pixels(img, PADDING + 106, 10, 350, 70)
        # Detail chips row (humidity, pressure, wind, cloud)
        assert_has_dark_pixels(img, PADDING, 80, 400, 100)
        # Forecast section visible
        assert_has_dark_pixels(img, 50, 110, 750, 220)

    def test_weather_narrow_layout(self) -> None:
        """Weather widget on a narrow display still renders temp and
        details."""
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        config = self._config(width=350, height=250)
        img = render_to_image(widgets, config)
        assert_has_dark_pixels(img, PADDING + 106, 10, 300, 70)
        assert_has_dark_pixels(img, PADDING, 80, 326, 100)

    def test_weather_draws_detail_chips(self) -> None:
        """Detail row shows humidity, pressure, wind, cloud coverage."""
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, PADDING, 80, 500, 100)

    def test_weather_forecast_precipitation(self) -> None:
        """Precipitation amounts appear under forecast days when > 0."""
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "forecast_days": 3,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Forecast area with hi/lo temps and precipitation
        assert_has_dark_pixels(img, 50, 150, 550, 210)

    def test_weather_forecast_separate_hilo(self) -> None:
        """High and low temps are on separate lines in forecast."""
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "forecast_days": 3,
            }
        ]
        img = render_to_image(widgets, self._config())
        # High temp row (y ~ 162 at s=1: forecast_y+52)
        assert_has_dark_pixels(img, 50, 155, 550, 175)
        # Low temp row (y ~ 180 at s=1: forecast_y+70)
        assert_has_dark_pixels(img, 50, 175, 550, 195, threshold=200)

    def test_weather_rainy_condition(self) -> None:
        states = {
            "weather.home": {
                "state": "rainy",
                "attributes": {
                    "temperature": 10,
                    "humidity": 90,
                    "wind_speed": 25,
                    "forecast": [],
                },
            }
        }
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(
            widgets,
            {"width": 600, "height": 200, "states": states},
        )
        assert_has_dark_pixels(
            img, PADDING, 10, PADDING + 90, 100, threshold=200
        )

    def test_weather_icon_anchors_text(self) -> None:
        # Temperature text is drawn right of the icon and
        # within the icon's vertical band.
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Icon area: starts at x + icon_pad, y + icon_pad.
        # At s=1, icon_pad=10, icon_size=80.
        assert_has_dark_pixels(
            img,
            PADDING,
            10,
            PADDING + 100,
            110,
            threshold=200,
        )
        # Temperature text: starts after icon + right pad.
        # At s=1, temp_x = 24 + 10 + 80 + 16 = 130.
        assert_has_dark_pixels(
            img,
            PADDING + 100,
            20,
            350,
            100,
        )

    def test_weather_compact_forecast_3_days(self) -> None:
        # 3 days in a 5-column grid: columns 1 and 3 empty.
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "forecast_days": 3,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Natural width at s=1: right_edge = 24 + 380 = 404.
        # available_w = 404 - 24 - 24 = 356.
        # n_cols=5, col_width = 356 // 5 = 71.
        # Col 1 spans [95, 166], col 3 spans [237, 308].
        # Forecast starts at ~y=154.
        assert_all_white(img, 105, 160, 155, 260)
        assert_all_white(img, 250, 160, 295, 260)
        # Filled column 0 should have content.
        assert_has_dark_pixels(
            img,
            30,
            160,
            90,
            260,
        )

    def test_weather_hilo_right_aligned(self) -> None:
        # Hi/lo/precip text is right-aligned at right_edge.
        # At s=1, right_edge = 24 + 380 = 404.
        # The hi "24°" text (~30px) should end near x=404,
        # so dark pixels appear in the range [360, 404].
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Hi/lo text near right edge (x=360..404, y=20..80).
        assert_has_dark_pixels(img, 360, 20, 404, 80)
        # Area between temperature end (~280) and hi/lo
        # start (~360) should be mostly white.
        assert_all_white(img, 290, 20, 350, 40)

    def test_weather_separator_matches_content(self) -> None:
        # Separator width equals n_cols * col_width, not
        # the full display width.
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "forecast_days": 3,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Natural width: right_edge = 404.
        # pad=10, content_left=34, content_w=360.
        # n_cols=5, col_width=72, content_width=360.
        # Separator ends at 34 + 360 = 394.
        # Pixels beyond 400 on separator line (~y=145)
        # should be white.
        assert_all_white(img, 400, 140, 600, 155)

    def test_weather_separator_color_is_light_gray(self) -> None:
        # Separator line uses COLOR_LIGHT_GRAY, not COLOR_GRAY, so
        # it recedes behind the text on 16-level displays.
        m = _compute_metrics(48)  # row_h_ref = round(48 * s) at s=1.0
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": 0,
                "y": 0,
                "w": 400,
                "forecast_days": 3,
            }
        ]
        img = render_to_image(widgets, self._config())
        # sep_y mirrors the renderer formula at s=1.0:
        # content_top (m.padding) + icon_size (80) + detail_gap (2)
        # + detail_icon_h (20) + sep_gap (8).
        s = 1.0
        sep_y = (
            m.padding
            + round(80 * s)
            + round(2 * s)
            + round(20 * s)
            + round(8 * s)
        )
        assert_has_gray_pixels(
            img,
            m.padding + 20,
            sep_y - m.divider,
            380,
            sep_y + m.divider + 1,
            low=COLOR_LIGHT_GRAY - 20,
            high=COLOR_LIGHT_GRAY + 20,
        )

    def test_weather_card_border(self) -> None:
        # Border style wraps the entire weather layout in a
        # rounded-rectangle outline drawn on all four edges.
        # assert_card_border is not used here because the bottom
        # edge needs a dynamically computed total_h derived from
        # the weather layout formula (icon, detail, separator,
        # forecast zones).
        m = _compute_metrics(48)  # row_h_ref = round(48 * s) at s=1.0
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Top edge (inset by m.radius to avoid rounded corners)
        assert_has_dark_pixels(img, m.radius, 0, 400 - m.radius, m.border)
        # Left edge
        assert_has_dark_pixels(img, 0, m.radius, m.border, 100)
        # Right edge
        assert_has_dark_pixels(img, 400 - m.border, m.radius, 400, 100)
        # Bottom edge: total_h mirrors the renderer formula at s=1.0
        # with forecast.  icon_size=80 dominates temp_h (~44px for
        # Roboto at 64px) at s=1.0, so max(icon_size, temp_h)=80.
        s = 1.0
        pad = round(10 * s)
        total_h = (
            m.padding
            + round(80 * s)  # row1_h
            + round(2 * s)
            + round(20 * s)  # detail_h
            + round(8 * s)  # sep_gap
            + max(2, round(3 * s))  # sep_thickness
            + round(8 * s)  # sep_gap after separator
            + round(88 * s)  # forecast_zone_h
            + round(16 * s)  # precip_text_h
            + pad  # bottom pad
        )
        assert_has_dark_pixels(
            img,
            m.radius,
            total_h - m.border,
            400 - m.radius,
            total_h,
        )
        # Temperature text still renders inside the card.
        assert_has_dark_pixels(img, 106, 10, 300, 70)

    def test_weather_card_left_bar(self) -> None:
        # Left-bar style draws a gray vertical bar on the left
        # edge only; the right edge remains undecorated.
        m = _compute_metrics(48)  # row_h_ref = round(48 * s) at s=1.0
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "left_bar",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Gray bar spans the full height; 2px vertical inset
        # avoids sub-pixel edge effects at widget boundaries.
        # +1 because PIL rectangle uses inclusive coordinates so the
        # bar occupies pixels 0..left_bar (left_bar+1 pixels wide).
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar + 1,
            100,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Far right edge is undecorated
        assert_all_white(img, 395, 0, 400, 5)

    def test_weather_card_none(self) -> None:
        # Explicit card_style="none" leaves border positions white
        # and preserves existing content rendering.
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        # No border decoration at corners
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)
        # Temperature text still renders in the content area
        assert_has_dark_pixels(img, 106, 5, 300, 70)

    def test_weather_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none" (no card decoration drawn).
        base = {"type": "weather", "entity": "weather.home", "x": 0, "y": 0}
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    def test_weather_card_style_none_has_soft_padding(self) -> None:
        # card_style="none" applies soft lpad so content is inset by
        # m.padding, consistent with tile/heading/entities.
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        m = _compute_metrics(48)  # _WX_ROW_H at scale=1.0
        bbox = content_bbox(img, 0, 0, 400, 200)
        assert bbox is not None, "expected non-white content"
        # Content must start at m.padding (soft pad), not flush at
        # x=0.  1px tolerance for sub-pixel rasterisation.
        assert bbox[0] >= m.padding - 1, (
            f"content left edge {bbox[0]} starts before soft padding "
            f"({m.padding}); card_style='none' should apply lpad"
        )

    def test_weather_card_border_nonzero_origin(self) -> None:
        # Border is correctly positioned when widget has non-zero x/y.
        ox, oy = 50, 30
        m = _compute_metrics(48)  # row_h_ref = round(48 * s) at s=1.0
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": ox,
                "y": oy,
                "w": 300,
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Top edge at y=oy
        assert_has_dark_pixels(
            img,
            ox + m.radius,
            oy,
            ox + 300 - m.radius,
            oy + m.border,
        )
        # Left edge at x=ox
        assert_has_dark_pixels(
            img,
            ox,
            oy + m.radius,
            ox + m.border,
            oy + 100,
        )
        # Area to the left of the widget is undecorated
        assert_all_white(img, 0, oy, ox - 1, oy + 5)
        # Temperature text inside the card:
        # content_left = ox + m.padding, temp_x = content_left + 80 + 16
        temp_x_min = ox + m.padding + 80 + 16
        assert_has_dark_pixels(img, temp_x_min, oy + 10, ox + 280, oy + 70)


# ── Custom sensor overrides ─────────────────────────────────────────

_SENSOR_STATES = {
    **MOCK_WEATHER_STATE,
    "sensor.outdoor_temp": {
        "state": "18.7",
        "attributes": {"unit_of_measurement": "°C"},
    },
    "sensor.outdoor_temp_whole": {
        "state": "22",
        "attributes": {"unit_of_measurement": "°C"},
    },
    "sensor.outdoor_temp_unavailable": {
        "state": "unavailable",
        "attributes": {},
    },
    "sensor.outdoor_humidity": {
        "state": "73",
        "attributes": {"unit_of_measurement": "%"},
    },
}

_BASE_WIDGET: dict[str, object] = {
    "type": "weather",
    "entity": "weather.home",
    "x": PADDING,
    "y": 0,
    "w": 400,
    "forecast_days": 0,
}

_BASE_CONFIG: dict[str, object] = {
    "width": 600,
    "height": 300,
    "states": _SENSOR_STATES,
}


class TestWeatherSensorOverrides:
    def test_custom_temp_sensor_uses_sensor_value(self) -> None:
        # temperature_entity overrides the weather entity's temperature
        # attribute; the context temp_text should reflect the sensor state.
        ctx = _build_weather_context(
            {**_BASE_WIDGET, "temperature_entity": "sensor.outdoor_temp"},
            _BASE_CONFIG,
        )
        assert ctx["temp_text"] == "18.7°C"

    def test_custom_temp_sensor_formats_one_decimal_for_whole_number(
        self,
    ) -> None:
        # A whole-number sensor value must still show one decimal place,
        # e.g. "22.0°C" rather than "22°C".
        ctx = _build_weather_context(
            {
                **_BASE_WIDGET,
                "temperature_entity": "sensor.outdoor_temp_whole",
            },
            _BASE_CONFIG,
        )
        assert ctx["temp_text"] == "22.0°C"

    def test_custom_temp_sensor_uses_sensor_unit(self) -> None:
        # The temperature unit comes from the sensor's
        # unit_of_measurement attribute, not the weather entity.
        states = {
            **_SENSOR_STATES,
            "sensor.temp_f": {
                "state": "65.3",
                "attributes": {"unit_of_measurement": "°F"},
            },
        }
        ctx = _build_weather_context(
            {**_BASE_WIDGET, "temperature_entity": "sensor.temp_f"},
            {**_BASE_CONFIG, "states": states},
        )
        assert ctx["temp_text"] == "65.3°F"

    def test_custom_temp_sensor_missing_falls_back_to_weather(self) -> None:
        # When the named temperature_entity is not in states, the widget
        # falls back to the weather entity's temperature attribute.
        ctx = _build_weather_context(
            {**_BASE_WIDGET, "temperature_entity": "sensor.nonexistent"},
            _BASE_CONFIG,
        )
        # Weather entity has temperature=22 (integer), formatted
        # without decimal.
        assert ctx["temp_text"] == "22°C"

    def test_custom_temp_sensor_unavailable_falls_back_to_weather(
        self,
    ) -> None:
        # When the sensor is present but in "unavailable" state (non-numeric),
        # _resolve_sensor_override falls back to the weather entity's value.
        ctx = _build_weather_context(
            {
                **_BASE_WIDGET,
                "temperature_entity": "sensor.outdoor_temp_unavailable",
            },
            _BASE_CONFIG,
        )
        assert ctx["temp_text"] == "22°C"

    def test_custom_humidity_sensor_overrides_weather_humidity(self) -> None:
        # humidity_entity overrides the weather entity's humidity attribute
        # in the detail chip row; value must be an integer percentage.
        ctx = _build_weather_context(
            {**_BASE_WIDGET, "humidity_entity": "sensor.outdoor_humidity"},
            _BASE_CONFIG,
        )
        humidity_item = next(
            (d for d in ctx["detail_items"] if d["text"] == "73%"),
            None,
        )
        assert humidity_item is not None, (
            "expected humidity chip with sensor value '73%', "
            f"got detail_items: {ctx['detail_items']}"
        )

    def test_custom_humidity_sensor_missing_falls_back_to_weather(
        self,
    ) -> None:
        # When humidity_entity is absent from states, humidity falls back
        # to the weather entity's humidity attribute (58 in
        # MOCK_WEATHER_STATE).
        ctx = _build_weather_context(
            {**_BASE_WIDGET, "humidity_entity": "sensor.nonexistent"},
            _BASE_CONFIG,
        )
        humidity_item = next(
            (d for d in ctx["detail_items"] if d["text"] == "58%"),
            None,
        )
        assert humidity_item is not None, (
            "expected fallback humidity chip with weather entity value "
            f"'58%', got detail_items: {ctx['detail_items']}"
        )

from __future__ import annotations

import dataclasses
import datetime as dt
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw, ImageFont

from custom_components.eink_dashboard.const import (
    COLOR_BLACK,
    COLOR_GRAY,
    PADDING,
)
from custom_components.eink_dashboard.render import (
    WidgetMetrics,
    _compute_metrics,
    _draw_card_container,
    _draw_card_row,
    _draw_chip,
    _draw_chip_flow,
    _format_relative_date,
    _load_font,
    _parse_days_until,
    render_dashboard,
)
from tests.helpers import (
    assert_all_white,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    assert_vertically_centered,
    content_bbox,
    make_config,
    pixel,
    png_to_image,
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


class TestRenderDashboard:
    def test_empty_widget_list_returns_white_image(self) -> None:
        config = {"width": 100, "height": 100}
        result = render_dashboard([], config)

        img = png_to_image(result)
        assert img.mode == "L"
        assert img.size == (100, 100)
        assert pixel(img, 50, 50) == 255

    def test_returns_valid_png(self) -> None:
        config = {"width": 200, "height": 300}
        result = render_dashboard([], config)

        img = png_to_image(result)
        assert img.format == "PNG"
        assert img.size == (200, 300)

    def test_rotation_90(self) -> None:
        config = {"width": 200, "height": 100, "rotation": 90}
        result = render_dashboard([], config)

        img = png_to_image(result)
        assert img.size == (100, 200)

    def test_rotation_270(self) -> None:
        config = {"width": 200, "height": 100, "rotation": 270}
        result = render_dashboard([], config)

        img = png_to_image(result)
        assert img.size == (100, 200)

    def test_unknown_widget_type_is_skipped(self) -> None:
        config = {"width": 100, "height": 100}
        widgets = [{"type": "nonexistent", "x": 10, "y": 10}]
        result = render_dashboard(widgets, config)

        img = png_to_image(result)
        assert img.size == (100, 100)


class TestRenderText:
    def test_text_draws_pixels(self) -> None:
        config = {"width": 200, "height": 100}
        widgets = [
            {
                "type": "text",
                "x": 10,
                "y": 10,
                "text": "Hello",
                "font_size": 20,
            }
        ]
        result = render_dashboard(widgets, config)

        img = png_to_image(result)
        assert_has_dark_pixels(img, 10, 10, 100, 40)

    def test_text_right_align(self) -> None:
        config = {"width": 200, "height": 100}
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 10,
                "text": "Hi",
                "font_size": 20,
                "align": "right",
            }
        ]
        result = render_dashboard(widgets, config)

        img = png_to_image(result)
        assert_has_dark_pixels(img, 140, 10, 200, 40)

    def test_text_center_align(self) -> None:
        config = {"width": 200, "height": 100}
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 10,
                "text": "Hi",
                "font_size": 20,
                "align": "center",
            }
        ]
        result = render_dashboard(widgets, config)

        img = png_to_image(result)
        assert_has_dark_pixels(img, 80, 10, 120, 40)

    def test_text_custom_color(self) -> None:
        config = {"width": 200, "height": 100}
        widgets = [
            {
                "type": "text",
                "x": 10,
                "y": 10,
                "text": "Gray",
                "font_size": 20,
                "color": 160,
            }
        ]
        result = render_dashboard(widgets, config)

        img = png_to_image(result)
        assert_has_gray_pixels(img, 10, 10, 80, 40, low=100, high=200)


class TestRenderSeparator:
    _CONFIG = {"width": 300, "height": 200}

    def test_separator_default_horizontal_line(self) -> None:
        # Default: horizontal line, 2px black, spans PADDING to width-PADDING.
        widgets = [{"type": "separator", "x": PADDING, "y": 50}]
        img = png_to_image(render_dashboard(widgets, self._CONFIG))
        assert pixel(img, PADDING, 50) == COLOR_BLACK
        assert pixel(img, 275, 50) == COLOR_BLACK
        # Below PADDING should be white
        assert pixel(img, 10, 50) == 255
        # 2px thick: y+1 is dark, y+2 is white
        assert pixel(img, 100, 51) == COLOR_BLACK
        assert pixel(img, 100, 52) == 255

    def test_separator_horizontal_bar(self) -> None:
        # style="bar" draws a ~6px gray horizontal bar.
        widgets = [
            {"type": "separator", "x": PADDING, "y": 50, "style": "bar"}
        ]
        img = png_to_image(render_dashboard(widgets, self._CONFIG))
        assert_has_gray_pixels(img, PADDING, 50, 275, 56)
        assert_all_white(img, PADDING, 58, 275, 70)

    def test_separator_vertical_line(self) -> None:
        # direction="vertical" draws a 2px black vertical line.
        widgets = [
            {
                "type": "separator",
                "x": 50,
                "y": PADDING,
                "direction": "vertical",
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._CONFIG))
        assert pixel(img, 50, PADDING) == COLOR_BLACK
        assert pixel(img, 50, 175) == COLOR_BLACK
        # Above PADDING should be white
        assert pixel(img, 50, 5) == 255
        # 2px wide: x+1 is dark, x+2 is white
        assert pixel(img, 51, 100) == COLOR_BLACK
        assert pixel(img, 52, 100) == 255

    def test_separator_vertical_bar(self) -> None:
        # direction="vertical", style="bar" draws a ~6px gray vertical bar.
        widgets = [
            {
                "type": "separator",
                "x": 50,
                "y": PADDING,
                "direction": "vertical",
                "style": "bar",
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._CONFIG))
        assert_has_gray_pixels(img, 50, PADDING, 56, 175)
        assert_all_white(img, 58, PADDING, 70, 175)

    def test_separator_explicit_length(self) -> None:
        # length=100 limits the separator to 100px from x.
        widgets = [{"type": "separator", "x": PADDING, "y": 50, "length": 100}]
        img = png_to_image(render_dashboard(widgets, self._CONFIG))
        assert_has_dark_pixels(img, PADDING, 50, PADDING + 100, 52)
        assert pixel(img, PADDING + 102, 50) == 255

    def test_separator_vertical_explicit_length(self) -> None:
        # Vertical separator with length=80 stops at y+80.
        widgets = [
            {
                "type": "separator",
                "x": 50,
                "y": PADDING,
                "direction": "vertical",
                "length": 80,
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._CONFIG))
        assert_has_dark_pixels(img, 50, PADDING, 52, PADDING + 80)
        assert pixel(img, 50, PADDING + 82) == 255

    def test_separator_bar_2level_widens(self) -> None:
        # grayscale_levels=2 widens a bar to ~10-12px.
        config = {**self._CONFIG, "grayscale_levels": 2}
        widgets = [
            {"type": "separator", "x": PADDING, "y": 50, "style": "bar"}
        ]
        img = png_to_image(render_dashboard(widgets, config))
        bb = content_bbox(img, PADDING, 50, 275, 70)
        assert bb is not None
        bar_h = bb[3] - bb[1]
        assert bar_h >= 10

    def test_separator_line_ignores_2level(self) -> None:
        # style="line" stays 2px even on 2-level displays.
        config = {**self._CONFIG, "grayscale_levels": 2}
        widgets = [{"type": "separator", "x": PADDING, "y": 50}]
        img = png_to_image(render_dashboard(widgets, config))
        assert pixel(img, 100, 52) == 255


class TestRenderWeather:
    _DEFAULTS: dict[str, object] = {
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
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
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
        result = render_dashboard(
            widgets,
            {"width": 600, "height": 300, "states": states},
        )
        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
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
        result = render_dashboard(widgets, config)

        img = png_to_image(result)
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
        result = render_dashboard(widgets, config)

        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
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
        result = render_dashboard(
            widgets,
            {"width": 600, "height": 200, "states": states},
        )
        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())
        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())
        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())
        img = png_to_image(result)
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
        result = render_dashboard(widgets, self._config())
        img = png_to_image(result)
        # Natural width: right_edge = 404.
        # pad=10, content_left=34, content_w=360.
        # n_cols=5, col_width=72, content_width=360.
        # Separator ends at 34 + 360 = 394.
        # Pixels beyond 400 on separator line (~y=145)
        # should be white.
        assert_all_white(img, 400, 140, 600, 155)


MOCK_SENSOR_STATES = {
    "sensor.living_room_temperature": {
        "state": "22.1",
        "attributes": {
            "unit_of_measurement": "°C",
            "friendly_name": "Living Room",
            "device_class": "temperature",
        },
    },
    "sensor.bedroom_temperature": {
        "state": "19.8",
        "attributes": {
            "unit_of_measurement": "°C",
            "friendly_name": "Bedroom",
            "device_class": "temperature",
        },
    },
    "sensor.humidity": {
        "state": "45",
        "attributes": {
            "unit_of_measurement": "%",
            "friendly_name": "Humidity",
            "device_class": "humidity",
        },
    },
    "sensor.no_device_class": {
        "state": "42",
        "attributes": {
            "friendly_name": "Plain Sensor",
        },
    },
    "binary_sensor.front_door": {
        "state": "off",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "binary_sensor.kitchen_window": {
        "state": "on",
        "attributes": {
            "friendly_name": "Kitchen Window",
            "device_class": "window",
        },
    },
}


class TestRenderSensorRows:
    # Verify rendering of redesigned sensor_rows widgets
    # using card container + icon circles + two-line text.
    _DEFAULTS: dict[str, object] = {
        "width": 400,
        "height": 300,
        "states": MOCK_SENSOR_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_sensor_rows_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "card_style": "border",
                "entities": [
                    "sensor.living_room_temperature",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Top edge
        assert_has_dark_pixels(
            img,
            m.radius,
            0,
            400 - m.radius,
            m.border,
        )
        # Bottom edge — +1 margin accommodates PIL's inset
        # stroke rounding at larger border widths.
        assert_has_dark_pixels(
            img,
            m.radius,
            56 - m.border - 1,
            400 - m.radius,
            57,
        )
        # Left edge
        assert_has_dark_pixels(
            img,
            0,
            m.radius,
            m.border,
            56 - m.radius,
        )
        # Right edge
        assert_has_dark_pixels(
            img,
            400 - m.border,
            m.radius,
            400,
            56 - m.radius,
        )

    def test_sensor_rows_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge;
        # the right edge should be white.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [
                    "sensor.living_room_temperature",
                ],
                "card_style": "left_bar",
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # The bar fills the full height [0, 56]; 2px inset
        # avoids sub-pixel edge effects.
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            54,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Right edge: no decoration
        assert_all_white(img, 395, 0, 400, 1)

    def test_sensor_rows_card_none(self) -> None:
        # No-decoration style has white edges — only content
        # (icon + text) draws pixels inside the card area.
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [
                    "sensor.living_room_temperature",
                ],
                "card_style": "none",
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Top-left corner should be white (no border, no bar)
        assert_all_white(img, 0, 0, 3, 3)
        # Far right edge should be white
        assert_all_white(img, 397, 0, 400, 3)

    def test_sensor_rows_row_divider(self) -> None:
        # A gray divider exists at the boundary between two
        # rows (at y = h/2).
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entities": [
                    "sensor.living_room_temperature",
                    "sensor.humidity",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Divider sits at row boundary y=56, gray colored
        assert_has_gray_pixels(
            img,
            m.padding + 20,
            56 - m.divider,
            380,
            56 + m.divider,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_sensor_rows_no_divider_single_entity(
        self,
    ) -> None:
        # A single entity should not produce a divider; the
        # area below the card should be white.
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [
                    "sensor.living_room_temperature",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # With only one entity there is no row boundary, so the
        # area just below the card (y=56..60) must be white —
        # no divider line bleeds out.
        assert_all_white(img, 0, 57, 400, 60)

    # ── Alignment tests ───────────────────────────────

    def test_sensor_rows_icon_centered_with_text(
        self,
    ) -> None:
        # Icon circle is vertically centered with the text
        # block in a single-entity row.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "card_style": "border",
                "entities": [
                    "sensor.living_room_temperature",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Icon region: inside the card padding, spanning the
        # icon diameter area.
        icon_left = m.padding
        icon_right = icon_left + m.icon_dia
        text_left = icon_right + m.inner_gap
        assert_vertically_centered(
            img,
            icon_region=(icon_left, 0, icon_right, 56),
            text_region=(text_left, 0, 380, 56),
        )

    # ── Scaling tests ─────────────────────────────────

    def test_sensor_rows_scales_with_h(self) -> None:
        # Doubling h roughly doubles the content height in
        # the icon area (scaling is proportional).
        m_small = _compute_metrics(56)
        m_large = _compute_metrics(112)
        widget_small = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": [
                "sensor.living_room_temperature",
            ],
        }
        widget_large = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entities": [
                "sensor.living_room_temperature",
            ],
        }
        img_s = png_to_image(render_dashboard([widget_small], self._config()))
        img_l = png_to_image(render_dashboard([widget_large], self._config()))
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(
                m_small.padding,
                0,
                m_small.padding + m_small.icon_dia,
                56,
            ),
            region_large=(
                m_large.padding,
                0,
                m_large.padding + m_large.icon_dia,
                112,
            ),
            expected_ratio=2.0,
        )

    # ── Content tests ─────────────────────────────────

    def test_sensor_rows_draws_content(self) -> None:
        # Both icon area and text area contain dark pixels.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [
                    "sensor.living_room_temperature",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Icon circle area
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )
        # Text area right of icon
        text_left = m.padding + m.icon_dia + m.inner_gap
        assert_has_dark_pixels(
            img,
            text_left,
            0,
            380,
            56,
        )

    def test_sensor_rows_with_title(self) -> None:
        # Title is drawn above the card area as gray text.
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "title": "Sensors",
                "entities": [
                    "sensor.living_room_temperature",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Title text should appear near the top of the widget
        assert_has_dark_pixels(img, 0, 0, 200, 20)

    def test_sensor_rows_secondary_text(self) -> None:
        # Secondary text (state + unit) is drawn in gray below
        # the primary text.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": [
                    "sensor.living_room_temperature",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # The lower half of the text area (below midpoint)
        # should contain gray pixels from secondary text.
        text_left = m.padding + m.icon_dia + m.inner_gap
        assert_has_gray_pixels(
            img,
            text_left,
            40,
            300,
            75,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_sensor_rows_missing_entity_skipped(
        self,
    ) -> None:
        # A nonexistent entity is skipped; remaining entities
        # still render.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entities": [
                    "sensor.nonexistent",
                    "sensor.humidity",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Row 0 (y=0..56) holds missing entity — should be
        # empty because the renderer skips it, leaving a gap.
        assert_all_white(img, m.padding, 2, 380, 54)
        # Row 1 (y=56..112) holds the valid entity —
        # should have dark content (icon + text).
        assert_has_dark_pixels(
            img,
            m.padding,
            58,
            380,
            110,
            threshold=200,
        )

    def test_sensor_rows_empty_entities(self) -> None:
        # Empty entity list produces a white canvas.
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entities": [],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        assert_all_white(img, 0, 0, 400, 300)

    def test_sensor_rows_binary_sensor(self) -> None:
        # Binary sensor entities render with icon content in
        # the icon circle area.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [
                    "binary_sensor.front_door",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Icon area should have content (gray circle + icon)
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )
        # Text area should have content (friendly name + state)
        text_left = m.padding + m.icon_dia + m.inner_gap
        assert_has_dark_pixels(img, text_left, 0, 380, 56)

    # ── Icon tests ────────────────────────────────────

    def test_sensor_rows_icon_circle_gray_fill(
        self,
    ) -> None:
        # The icon circle background should contain gray
        # pixels (fill = COLOR_GRAY).
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": [
                    "sensor.living_room_temperature",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        assert_has_gray_pixels(
            img,
            m.padding,
            (80 - m.icon_dia) // 2,
            m.padding + m.icon_dia,
            (80 + m.icon_dia) // 2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_sensor_rows_no_device_class_letter_fallback(
        self,
    ) -> None:
        # An entity without device_class still renders content
        # in the icon circle area (letter fallback).
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": ["sensor.no_device_class"],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Icon circle area should have content (gray circle
        # with white letter)
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )


class TestRenderDeviceBattery:
    _DEFAULTS: dict[str, object] = {
        "width": 400,
        "height": 100,
        "device_battery_level": 75,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def test_device_battery_draws_fill(self) -> None:
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        result = render_dashboard(widgets, self._config())
        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING + 1, 33, PADDING + 16, 42)

    def test_device_battery_none_is_noop(self) -> None:
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        result = render_dashboard(
            widgets, self._config(device_battery_level=None)
        )
        img = png_to_image(result)
        assert_all_white(img, 0, 0, 400, 100)

    def test_device_battery_missing_key_is_noop(self) -> None:
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        result = render_dashboard(widgets, {"width": 400, "height": 100})
        img = png_to_image(result)
        assert_all_white(img, 0, 0, 400, 100)

    def test_device_battery_draws_percentage_text(self) -> None:
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        result = render_dashboard(widgets, self._config())
        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING + 28, 29, PADDING + 70, 47)

    def test_device_battery_draws_nub(self) -> None:
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        result = render_dashboard(widgets, self._config())
        img = png_to_image(result)
        assert_has_dark_pixels(
            img, PADDING + 23, 35, PADDING + 25, 40, threshold=200
        )

    def test_device_battery_zero_percent(self) -> None:
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        result = render_dashboard(
            widgets, self._config(device_battery_level=0)
        )
        img = png_to_image(result)
        assert_has_dark_pixels(
            img, PADDING, 32, PADDING + 25, 43, threshold=200
        )

    def test_device_battery_100_percent(self) -> None:
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        result = render_dashboard(
            widgets, self._config(device_battery_level=100)
        )
        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING + 1, 33, PADDING + 21, 42)

    def test_device_battery_icon_scales_with_font_size(self) -> None:
        # font_size=48 → s=2 → icon is 44×20 instead of default 22×10
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 40,
                "font_size": 48,
            }
        ]
        result = render_dashboard(
            widgets, self._config(device_battery_level=75)
        )
        img = png_to_image(result)
        # Scaled icon body: PADDING to PADDING+44, icon_y=64 to 84
        assert_has_dark_pixels(
            img, PADDING, 64, PADDING + 44, 85, threshold=200
        )

        # At default font_size, the gap between nub-end (PADDING+24) and
        # label-start (PADDING+30) is clear — proving the scaled icon actually
        # extends its body into a region the default size never reaches.
        result_default = render_dashboard(
            [{"type": "device_battery", "x": PADDING, "y": 40}],
            self._config(device_battery_level=75),
        )
        img_default = png_to_image(result_default)
        assert all(
            pixel(img_default, x, y) >= 200
            for x in range(PADDING + 25, PADDING + 30)
            for y in range(40, 50)
        )


MOCK_STATUS_ICON_STATES = {
    "binary_sensor.front_door": {
        "state": "on",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "binary_sensor.kitchen_window": {
        "state": "off",
        "attributes": {
            "friendly_name": "Kitchen Window",
            "device_class": "window",
        },
    },
    "binary_sensor.water_alarm": {
        "state": "on",
        "attributes": {
            "friendly_name": "Water Alarm",
            "device_class": "moisture",
        },
    },
    "binary_sensor.motion": {
        "state": "off",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
}


def _make_dummy_icon(
    size: int = 64,
) -> tuple[Image.Image, Image.Image]:
    """Create a synthetic icon for tests that need _load_icon."""
    gray = Image.new("L", (size, size), 0)
    mask = Image.new("L", (size, size), 255)
    return gray, mask


class TestRenderStatusIcons:
    # Verify rendering of redesigned status_icons widgets
    # using pill-shaped chips with MDI icons.
    _DEFAULTS: dict[str, object] = {
        "width": 500,
        "height": 200,
        "states": MOCK_STATUS_ICON_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_chip_pill_shape(self) -> None:
        # Corner pixel is white (clipped by pill radius);
        # border pixels inward along the top edge are dark.
        h = 40
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": [
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Extreme top-left corner: outside the pill radius
        radius = h // 2
        assert pixel(img, 0, 0) == 255
        # A few pixels inward from the radius along the
        # top edge: inside the border stroke
        assert_has_dark_pixels(img, radius, 0, radius + 5, 3)

    def test_problem_chip_inverted(self) -> None:
        # front_door: state=on, device_class=door (problem)
        # → chip interior is filled black.
        h = 40
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": [
                    "binary_sensor.front_door",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Interior center of the chip should be very dark
        # (black fill from inverted=True).
        cx = h // 2
        cy = h // 2
        assert pixel(img, cx, cy) < 64

    def test_normal_chip_outline(self) -> None:
        # kitchen_window: state=off → not a problem →
        # outlined chip with white interior.
        h = 40
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": [
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Center of the chip should be white (outlined only)
        cx = h // 2
        cy = h // 2
        assert pixel(img, cx, cy) >= 200
        # The border itself should have dark pixels
        # (along top edge past the radius)
        radius = h // 2
        assert_has_dark_pixels(img, radius, 0, radius + 5, 3)

    def test_wrapping(self) -> None:
        # Narrow w forces chips to wrap to the next row.
        h = 40
        gap = round(h * 0.29)
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": h,
                "entities": [
                    "binary_sensor.front_door",
                    "binary_sensor.kitchen_window",
                    "binary_sensor.water_alarm",
                    "binary_sensor.motion",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Dark pixels should exist below the first chip row
        # (second row starts at y = h + gap).
        second_row_y = h + gap
        assert_has_dark_pixels(
            img,
            0,
            second_row_y,
            200,
            second_row_y + h,
        )

    # ── Content tests ─────────────────────────────────

    def test_icon_presence(self) -> None:
        # Entity with mapped device_class (door) → MDI icon
        # drawn inside the chip's icon region.  Patches
        # _load_icon so PNGs need not be built.
        h = 40
        pad = round(h * 0.18)
        icon_sz = round(h * 0.29)
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": [
                    "binary_sensor.front_door",
                ],
            }
        ]
        dummy = _make_dummy_icon()
        with patch(
            "custom_components.eink_dashboard.render._load_icon",
            return_value=dummy,
        ):
            img = png_to_image(render_dashboard(widgets, self._config()))
        # Icon region inside the chip (after horizontal
        # padding).  The dummy icon is a solid black square
        # with full opacity, so non-white pixels confirm
        # the icon was drawn.
        assert content_bbox(img, pad, 0, pad + icon_sz, h) is not None

    def test_title(self) -> None:
        # Title text is rendered above chip area in gray.
        h = 40
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "title": "Doors",
                "entities": [
                    "binary_sensor.front_door",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        # Title area: top pixels should have content
        title_font_sz = max(10, round(h * 0.14))
        title_advance = round(title_font_sz * 1.4)
        assert_has_dark_pixels(img, 0, 0, 200, title_advance, threshold=200)
        # Chip content starts below the title
        assert_has_dark_pixels(img, 0, title_advance, 400, title_advance + h)

    # ── Edge case tests ───────────────────────────────

    def test_empty_entities_noop(self) -> None:
        # Empty entity list → canvas is entirely white.
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 40,
                "entities": [],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        assert_all_white(img, 0, 0, 500, 200)

    def test_missing_entity_skipped(self) -> None:
        # Nonexistent entity is skipped; valid entity
        # still renders.
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 40,
                "entities": [
                    "binary_sensor.nonexistent",
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        img = png_to_image(render_dashboard(widgets, self._config()))
        assert_has_dark_pixels(img, 0, 0, 400, 40)

    def test_motion_on_is_not_inverted(self) -> None:
        # Motion sensor with state "on" is informational,
        # not a problem — chip must NOT be inverted (no
        # black fill).
        h = 40
        pad = round(h * 0.18)
        states = dict(MOCK_STATUS_ICON_STATES)
        states["binary_sensor.motion"] = {
            "state": "on",
            "attributes": {
                "friendly_name": "Motion",
                "device_class": "motion",
            },
        }
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": [
                    "binary_sensor.motion",
                ],
            }
        ]
        cfg = self._config(states=states)
        img = png_to_image(render_dashboard(widgets, cfg))
        # Interior of the chip (between border and text)
        # should contain white pixels — a filled black
        # chip would have none.
        mid_y = h // 2
        interior_x = pad + 5
        assert pixel(img, interior_x, mid_y) == 255

    # ── Scaling tests ─────────────────────────────────

    def test_scales_with_h(self) -> None:
        # Doubling h roughly doubles chip content height.
        h_small = 40
        h_large = 80
        entity = ["binary_sensor.kitchen_window"]
        img_s = png_to_image(
            render_dashboard(
                [
                    {
                        "type": "status_icons",
                        "x": 0,
                        "y": 0,
                        "w": 400,
                        "h": h_small,
                        "entities": entity,
                    }
                ],
                self._config(),
            )
        )
        img_l = png_to_image(
            render_dashboard(
                [
                    {
                        "type": "status_icons",
                        "x": 0,
                        "y": 0,
                        "w": 400,
                        "h": h_large,
                        "entities": entity,
                    }
                ],
                self._config(),
            )
        )
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(0, 0, 400, h_small),
            region_large=(0, 0, 400, h_large),
            expected_ratio=2.0,
        )

    # ── Alignment tests ───────────────────────────────

    def test_icon_vertically_centered(self) -> None:
        # Icon content and text content share the same
        # vertical center within the chip.  Patches
        # _load_icon so PNGs need not be built.
        h = 40
        pad = round(h * 0.18)
        icon_sz = round(h * 0.29)
        icon_gap = round(h * 0.14)
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": [
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        dummy = _make_dummy_icon()
        with patch(
            "custom_components.eink_dashboard.render._load_icon",
            return_value=dummy,
        ):
            img = png_to_image(render_dashboard(widgets, self._config()))
        text_start = pad + icon_sz + icon_gap
        assert_vertically_centered(
            img,
            icon_region=(pad, 0, pad + icon_sz, h),
            text_region=(text_start, 0, 300, h),
        )


MOCK_WASTE_SCHEDULE_STATES = {
    "sensor.restmull": {
        "state": "2026-05-03",
        "attributes": {"friendly_name": "Restmull"},
    },
    "sensor.gelbe_tonne": {
        "state": "2026-05-04",
        "attributes": {"friendly_name": "Gelbe Tonne"},
    },
    "sensor.papier": {
        "state": "2026-05-05",
        "attributes": {"friendly_name": "Papier"},
    },
}

_TODAY = dt.date(2026, 5, 2)
_PATCH_NOW = "custom_components.eink_dashboard.render.date"


class TestWasteDateHelpers:
    def test_parse_iso_date(self) -> None:
        today = dt.date(2026, 5, 2)
        assert _parse_days_until("2026-05-02", today) == 0
        assert _parse_days_until("2026-05-03", today) == 1
        assert _parse_days_until("2026-05-09", today) == 7

    def test_parse_integer_string(self) -> None:
        today = dt.date(2026, 5, 2)
        assert _parse_days_until("0", today) == 0
        assert _parse_days_until("3", today) == 3

    def test_parse_invalid_returns_none(self) -> None:
        today = dt.date(2026, 5, 2)
        assert _parse_days_until("unavailable", today) is None
        assert _parse_days_until("unknown", today) is None
        assert _parse_days_until("", today) is None

    def test_format_today(self) -> None:
        assert _format_relative_date(0, "2026-05-02") == "today"

    def test_format_tomorrow(self) -> None:
        assert _format_relative_date(1, "2026-05-03") == "tomorrow"

    def test_format_in_n_days(self) -> None:
        assert _format_relative_date(3, "2026-05-05") == "in 3 days"

    def test_format_none_returns_raw(self) -> None:
        assert _format_relative_date(None, "unavailable") == "unavailable"

    def test_format_negative_returns_raw(self) -> None:
        assert _format_relative_date(-1, "2026-05-01") == "2026-05-01"


class TestRenderWasteSchedule:
    _DEFAULTS: dict[str, object] = {
        "width": 500,
        "height": 300,
        "states": MOCK_WASTE_SCHEDULE_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def test_waste_schedule_draws_entities(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": [
                    "sensor.restmull",
                    "sensor.gelbe_tonne",
                ],
            }
        ]
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING, 10, 300, 38, threshold=200)
        assert_has_dark_pixels(img, PADDING, 38, 300, 66, threshold=200)

    def test_waste_schedule_with_title(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "title": "Waste Collection",
                "entities": ["sensor.restmull"],
            }
        ]
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING, 10, 250, 40)
        assert_has_dark_pixels(img, PADDING, 42, 300, 70, threshold=200)

    def test_waste_schedule_missing_entity_skipped(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": [
                    "sensor.nonexistent",
                    "sensor.restmull",
                ],
            }
        ]
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING, 10, 300, 38, threshold=200)

    def test_waste_schedule_empty_entities_is_noop(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": [],
            }
        ]
        result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        assert_all_white(img, 0, 0, 500, 300)

    def test_waste_schedule_today_fills_circle(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": ["sensor.restmull"],
            }
        ]
        # restmull state is 2026-05-03; today = 2026-05-03 → days=0
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = dt.date(2026, 5, 3)
            result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        assert_has_dark_pixels(
            img, PADDING, 16, PADDING + 11, 27, threshold=64
        )

    def test_waste_schedule_tomorrow_fills_circle(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": ["sensor.restmull"],
            }
        ]
        # restmull state is 2026-05-03; today = 2026-05-02 → days=1
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        assert_has_dark_pixels(
            img, PADDING, 16, PADDING + 11, 27, threshold=64
        )

    def test_waste_schedule_future_draws_outline(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": ["sensor.gelbe_tonne"],
            }
        ]
        # gelbe_tonne state is 2026-05-04; today = 2026-05-02 → days=2
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        # Interior of circle should NOT be solid black
        interior_black = all(
            pixel(img, x, y) < 64
            for x in range(PADDING + 2, PADDING + 9)
            for y in range(18, 25)
        )
        assert not interior_black
        # But the circle boundary should have some non-white pixels
        assert_has_dark_pixels(
            img, PADDING, 16, PADDING + 11, 27, threshold=240
        )

    def test_waste_schedule_date_right_aligned(self) -> None:
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": ["sensor.restmull"],
            }
        ]
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config())

        img = png_to_image(result)
        assert_has_dark_pixels(img, 380, 10, 476, 38, threshold=200)

    def test_waste_schedule_integer_state(self) -> None:
        states = {
            "sensor.restmull": {
                "state": "3",
                "attributes": {"friendly_name": "Restmull"},
            }
        }
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": ["sensor.restmull"],
            }
        ]
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config(states=states))

        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING, 10, 300, 38, threshold=200)

    def test_waste_schedule_past_date_skipped(self) -> None:
        states = {
            "sensor.restmull": {
                "state": "2026-05-01",
                "attributes": {"friendly_name": "Restmull"},
            }
        }
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": ["sensor.restmull"],
            }
        ]
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config(states=states))

        img = png_to_image(result)
        assert_all_white(img, 0, 0, 500, 300)

    def test_waste_schedule_beyond_3_days_skipped(self) -> None:
        states = {
            "sensor.restmull": {
                "state": "2026-05-06",
                "attributes": {"friendly_name": "Restmull"},
            }
        }
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "entities": ["sensor.restmull"],
            }
        ]
        # 2026-05-06 is 4 days from today (2026-05-02) → filtered out
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(widgets, self._config(states=states))

        img = png_to_image(result)
        assert_all_white(img, 0, 0, 500, 300)


class TestFontSizeControls:
    """Verify that font_size config is respected per widget type."""

    def test_weather_custom_font_size(self) -> None:
        # font_size=11 → s=11/32≈0.34; icon_size=22, temp at x+26
        # detail_y = y+icon_size+round(8*s) = 10+22+3 = 35
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "font_size": 11,
            }
        ]
        result = render_dashboard(
            widgets,
            {"width": 400, "height": 200, "states": MOCK_WEATHER_STATE},
        )
        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING + 22, 10, PADDING + 100, 40)
        # Detail chips at detail_y=35 (wrong /22 divisor shifts them to y=46)
        assert_has_dark_pixels(img, PADDING, 35, PADDING + 200, 46)

    def test_device_battery_custom_font_size(self) -> None:
        # font_size=20 — larger percentage label
        widgets = [
            {"type": "device_battery", "x": PADDING, "y": 20, "font_size": 20}
        ]
        result = render_dashboard(
            widgets,
            {"width": 400, "height": 100, "device_battery_level": 75},
        )
        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING + 28, 10, PADDING + 90, 40)

    def test_waste_schedule_custom_font_size(self) -> None:
        # font_size=42 → s=42/28=1.5; row_height=round(28*1.5)=42
        # Row 1 at y=10; row 2 at y=52.
        widgets = [
            {
                "type": "waste_schedule",
                "x": PADDING,
                "y": 10,
                "font_size": 42,
                "entities": ["sensor.restmull", "sensor.gelbe_tonne"],
            }
        ]
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            result = render_dashboard(
                widgets,
                {
                    "width": 400,
                    "height": 150,
                    "states": MOCK_WASTE_SCHEDULE_STATES,
                },
            )
        img = png_to_image(result)
        assert_has_dark_pixels(img, PADDING, 10, 350, 50, threshold=200)
        assert_has_dark_pixels(img, PADDING, 52, 350, 100, threshold=200)


class TestLoadFont:
    def test_medium_returns_different_object(self) -> None:
        # medium=True must produce a distinct cached object
        regular = _load_font(18)
        medium = _load_font(18, medium=True)
        assert regular is not medium
        # When the TTF is available, verify the actual font style
        if hasattr(medium, "getname"):
            family, style = medium.getname()
            if style != "Regular":
                assert style == "Medium"

    def test_regular_is_cached(self) -> None:
        assert _load_font(18) is _load_font(18)

    def test_medium_is_cached(self) -> None:
        assert _load_font(18, medium=True) is _load_font(18, medium=True)

    def test_size_clamped_to_minimum(self) -> None:
        assert _load_font(0) is not None
        assert _load_font(-5) is not None
        assert _load_font(0, medium=True) is not None
        assert _load_font(-5, medium=True) is not None


class TestComputeMetrics:
    def test_returns_frozen_dataclass(self) -> None:
        m = _compute_metrics(56)
        assert isinstance(m, WidgetMetrics)
        with pytest.raises(AttributeError):
            m.border = 99  # type: ignore[misc]

    def test_reference_baseline_h56(self) -> None:
        m = _compute_metrics(56)
        assert m.border == 2
        assert m.padding == 12
        assert m.radius == 12
        assert m.icon_dia == 36
        assert m.font_primary == 18
        assert m.font_secondary == 14
        assert m.divider == 4
        assert m.inner_gap == 12
        assert m.left_bar == 4

    def test_minimum_clamps_small_row_h(self) -> None:
        m = _compute_metrics(10)
        assert m.border == 2
        assert m.font_primary == 10
        assert m.font_secondary == 10
        assert m.divider == 2
        assert m.left_bar == 2

    def test_unclamped_fields_small_row_h(self) -> None:
        m = _compute_metrics(10)
        assert m.padding == 2
        assert m.radius == 2
        assert m.icon_dia == 6
        assert m.inner_gap == 2

    def test_scales_at_large_row_h(self) -> None:
        m = _compute_metrics(200)
        assert m.border == 8
        assert m.padding == 42
        assert m.radius == 42
        assert m.icon_dia == 128
        assert m.font_primary == 64
        assert m.font_secondary == 50
        assert m.divider == 14
        assert m.inner_gap == 42
        assert m.left_bar == 14

    def test_clamp_boundary_border(self) -> None:
        assert _compute_metrics(37).border == 2  # clamped: round(1.48) = 1 < 2
        assert _compute_metrics(100).border == 4  # natural: round(4) = 4 > 2

    def test_all_fields_present(self) -> None:
        m = _compute_metrics(56)
        for f in dataclasses.fields(WidgetMetrics):
            assert isinstance(getattr(m, f.name), int), f"{f.name} is not int"


class TestDrawCardContainer:
    # Canvas 400x200, card at (10, 10)-(310, 110), metrics from row_h=56.
    _X, _Y, _W, _H = 10, 10, 300, 100

    def _blank(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("L", (400, 200), 255)
        return img, ImageDraw.Draw(img)

    def _m(self) -> WidgetMetrics:
        return _compute_metrics(
            56
        )  # border=2, padding=12, radius=12, left_bar=4

    def test_border_draws_dark_pixels_on_all_edges(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_container(draw, self._X, self._Y, self._W, self._H, m)
        assert_has_dark_pixels(
            img,
            self._X + m.radius,
            self._Y,
            self._X + self._W - m.radius,
            self._Y + m.border,
        )
        assert_has_dark_pixels(
            img,
            self._X + m.radius,
            self._Y + self._H - m.border,
            self._X + self._W - m.radius,
            self._Y + self._H,
        )
        assert_has_dark_pixels(
            img,
            self._X,
            self._Y + m.radius,
            self._X + m.border,
            self._Y + self._H - m.radius,
        )
        assert_has_dark_pixels(
            img,
            self._X + self._W - m.border,
            self._Y + m.radius,
            self._X + self._W,
            self._Y + self._H - m.radius,
        )

    def test_border_interior_is_white(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_container(draw, self._X, self._Y, self._W, self._H, m)
        inset = m.border + 1  # +1 for Pillow anti-aliasing at the border edge
        assert_all_white(
            img,
            self._X + inset,
            self._Y + m.radius,  # skip rounded corners
            self._X + self._W - inset,
            self._Y + self._H - m.radius,
        )

    def test_border_returns_padding_offset(self) -> None:
        # border style should offset content by m.padding, consistent
        # with left_bar semantics (content clears the frame decoration).
        _, draw = self._blank()
        m = self._m()
        offset = _draw_card_container(
            draw, self._X, self._Y, self._W, self._H, m
        )
        assert offset == m.padding

    def test_left_bar_draws_gray_on_left(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_container(
            draw, self._X, self._Y, self._W, self._H, m, card_style="left_bar"
        )
        assert_has_gray_pixels(
            img,
            self._X,
            self._Y + 10,
            self._X + m.left_bar,
            self._Y + self._H - 10,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_left_bar_right_edge_is_white(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_container(
            draw, self._X, self._Y, self._W, self._H, m, card_style="left_bar"
        )
        # Area to the right of bar + padding should have no decoration
        right_start = self._X + m.left_bar + m.padding + 1
        assert_all_white(
            img, right_start, self._Y, self._X + self._W, self._Y + 1
        )
        assert_all_white(
            img,
            right_start,
            self._Y + 10,
            self._X + self._W,
            self._Y + self._H - 10,
        )

    def test_left_bar_returns_offset(self) -> None:
        _, draw = self._blank()
        m = self._m()
        offset = _draw_card_container(
            draw, self._X, self._Y, self._W, self._H, m, card_style="left_bar"
        )
        assert offset == m.left_bar + m.padding

    def test_none_leaves_canvas_white(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_container(
            draw, self._X, self._Y, self._W, self._H, m, card_style="none"
        )
        assert_all_white(
            img, self._X, self._Y, self._X + self._W, self._Y + self._H
        )

    def test_none_returns_zero_offset(self) -> None:
        _, draw = self._blank()
        m = self._m()
        offset = _draw_card_container(
            draw, self._X, self._Y, self._W, self._H, m, card_style="none"
        )
        assert offset == 0

    def test_left_bar_widens_for_2_level_display(self) -> None:
        img, draw = self._blank()
        m = self._m()  # left_bar=4
        offset = _draw_card_container(
            draw,
            self._X,
            self._Y,
            self._W,
            self._H,
            m,
            card_style="left_bar",
            grayscale_levels=2,
        )
        # At h=56: widened bar = max(10, 4*3) = 12px.
        # Gray should extend to pixel 12.
        widened = max(10, m.left_bar * 3)
        assert_has_gray_pixels(
            img,
            self._X + m.left_bar,
            self._Y + 10,
            self._X + widened,
            self._Y + self._H - 10,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        assert offset == widened + m.padding

    def test_left_bar_standard_width_without_2_level(self) -> None:
        img, draw = self._blank()
        m = self._m()  # left_bar=4
        _draw_card_container(
            draw,
            self._X,
            self._Y,
            self._W,
            self._H,
            m,
            card_style="left_bar",
            grayscale_levels=16,
        )
        # Pixel just past the normal bar width (4px) should be white.
        assert_all_white(
            img,
            self._X + m.left_bar + 1,
            self._Y + 1,
            self._X + 10,
            self._Y + self._H - 1,
        )

    def test_left_bar_no_config_uses_standard_width(self) -> None:
        img, draw = self._blank()
        m = self._m()  # left_bar=4
        _draw_card_container(
            draw, self._X, self._Y, self._W, self._H, m, card_style="left_bar"
        )
        # Pixel just past the normal bar width (4px) should be white.
        assert_all_white(
            img,
            self._X + m.left_bar + 1,
            self._Y + 1,
            self._X + 10,
            self._Y + self._H - 1,
        )

    def test_default_card_style_is_border(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_container(draw, self._X, self._Y, self._W, self._H, m)
        # Default should behave identically to card_style="border".
        assert_has_dark_pixels(
            img,
            self._X + m.radius,
            self._Y,
            self._X + self._W - m.radius,
            self._Y + m.border,
        )


class TestDrawCardRow:
    # Canvas 400x200, row at (10, 10), width 300, row_h 56 (reference size).
    _X, _Y, _W, _H = 10, 10, 300, 56

    def _blank(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("L", (400, 200), 255)
        return img, ImageDraw.Draw(img)

    def _m(self) -> WidgetMetrics:
        # padding=12, icon_dia=36, inner_gap=12,
        # font_primary=18, font_secondary=14
        return _compute_metrics(56)

    def test_icon_circle_drawn(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw, img, self._X, self._Y, self._W, self._H, m, primary="Hello"
        )
        # Icon circle: cx=10+12=22, circle_y=10+(56-36)//2=20, dia=36
        assert_has_gray_pixels(img, 22, 20, 58, 56, low=100, high=140)

    def test_letter_fallback(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            m,
            primary="Temperature",
        )
        # Gray circle is drawn
        assert_has_gray_pixels(img, 24, 22, 56, 54, low=100, high=140)
        # White letter pixels exist inside the circle
        # (letter on gray background)
        center_x = 22 + m.icon_dia // 2
        center_y = 20 + m.icon_dia // 2
        has_white = any(
            pixel(img, x, y) == 255
            for x in range(center_x - 6, center_x + 6)
            for y in range(center_y - 6, center_y + 6)
        )
        assert has_white, "no white letter pixels found inside icon circle"

    def test_primary_text_drawn(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw, img, self._X, self._Y, self._W, self._H, m, primary="Hello"
        )
        # Text starts at x=22+36+12=70
        assert_has_dark_pixels(img, 70, self._Y, 250, self._Y + self._H)

    def test_secondary_text_drawn(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            m,
            primary="Hello",
            secondary="world",
        )
        # Primary (black) in the upper half, secondary (gray) below it.
        assert_has_dark_pixels(img, 70, 22, 250, 40)
        assert_has_gray_pixels(img, 70, 40, 250, 56, low=100, high=140)

    def test_primary_only_centered(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw, img, self._X, self._Y, self._W, self._H, m, primary="Hello"
        )
        # Single-line primary should be vertically centered in the row.
        # Tolerance of 5px allows for PIL ascender/descender space that
        # may not contain rendered pixels, shifting the glyph center.
        text_bb = content_bbox(
            img, 70, self._Y, self._X + self._W, self._Y + self._H
        )
        assert text_bb is not None, "no text content found"
        text_cy = (text_bb[1] + text_bb[3]) / 2
        row_cy = self._Y + self._H / 2  # 10 + 28 = 38
        assert abs(text_cy - row_cy) <= 5, (
            f"primary text not centered: "
            f"text_cy={text_cy:.1f}, row_cy={row_cy:.1f}"
        )

    def test_value_right_aligned(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            m,
            primary="Hello",
            value="today",
        )
        # Value text near right edge (x+w-padding = 298)
        assert_has_gray_pixels(
            img,
            240,
            self._Y,
            self._X + self._W,
            self._Y + self._H,
            low=100,
            high=140,
        )

    def test_icon_vertically_centered_with_text(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            m,
            primary="Hello",
            secondary="world",
        )
        # Tolerance of 4px accounts for font metric vs rendered-pixel
        # center offset.
        assert_vertically_centered(
            img,
            icon_region=(22, self._Y, 58, self._Y + self._H),
            text_region=(70, self._Y, 250, self._Y + self._H),
            tolerance=4.0,
        )

    def test_no_value_area_is_white(self) -> None:
        img, draw = self._blank()
        m = self._m()
        _draw_card_row(
            draw, img, self._X, self._Y, self._W, self._H, m, primary="Hi"
        )
        # Area near right padding edge should be white when no value provided
        right_area_start = self._X + self._W - m.padding - 20
        assert_all_white(
            img,
            right_area_start,
            self._Y,
            self._X + self._W,
            self._Y + self._H,
        )

    def test_icon_scales_with_row_h(self) -> None:
        # Render at row_h=56 (small) and row_h=112 (large, 2×).
        row_h_s = 56
        img_s, draw_s = self._blank()
        m_s = _compute_metrics(row_h_s)
        _draw_card_row(
            draw_s,
            img_s,
            self._X,
            self._Y,
            self._W,
            row_h_s,
            m_s,
            primary="Hello",
        )
        icon_x_s = self._X + m_s.padding
        cy_s = self._Y + (row_h_s - m_s.icon_dia) // 2
        region_s = (
            icon_x_s,
            cy_s,
            icon_x_s + m_s.icon_dia,
            cy_s + m_s.icon_dia,
        )

        row_h_l = 112
        img_l = Image.new("L", (800, 400), 255)
        draw_l = ImageDraw.Draw(img_l)
        m_l = _compute_metrics(row_h_l)
        _draw_card_row(
            draw_l,
            img_l,
            self._X,
            self._Y,
            self._W * 2,
            row_h_l,
            m_l,
            primary="Hello",
        )
        icon_x_l = self._X + m_l.padding
        cy_l = self._Y + (row_h_l - m_l.icon_dia) // 2
        region_l = (
            icon_x_l,
            cy_l,
            icon_x_l + m_l.icon_dia,
            cy_l + m_l.icon_dia,
        )

        assert_scales_proportionally(
            img_s,
            img_l,
            region_s,
            region_l,
            expected_ratio=2.0,
        )


class TestDrawChip:
    # Canvas 400x200; chip at (20, 20) with h=40.
    _X, _Y, _H = 20, 20, 40

    def _blank(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("L", (400, 200), 255)
        return img, ImageDraw.Draw(img)

    def _font(self) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return _load_font(14)

    def _border(self) -> int:
        # border = max(2, round(40 * 0.04)) = 2
        return max(2, round(self._H * 0.04))

    def test_pill_shape_corners_white(self) -> None:
        img, draw = self._blank()
        font = self._font()
        _draw_chip(
            draw, img, self._X, self._Y, self._H, "OK", font, self._border()
        )
        # The extreme corner pixels of the chip bounding box should be white
        # because the pill shape clips them away (radius = h // 2 = 20).
        assert pixel(img, self._X, self._Y) == 255, (
            "top-left corner should be white (pill clips it)"
        )
        assert pixel(img, self._X, self._Y + self._H - 1) == 255, (
            "bottom-left corner should be white (pill clips it)"
        )

    def test_pill_border_drawn(self) -> None:
        img, draw = self._blank()
        font = self._font()
        _draw_chip(
            draw, img, self._X, self._Y, self._H, "OK", font, self._border()
        )
        # The top-center of the pill must have border pixels (past the radius
        # zone on each side); radius=20 so center is well past the arc zone.
        radius = self._H // 2
        mid_x = self._X + radius + 5
        assert_has_dark_pixels(img, mid_x, self._Y, mid_x + 10, self._Y + 3)

    def test_text_drawn_inside_chip(self) -> None:
        img, draw = self._blank()
        font = self._font()
        _draw_chip(
            draw, img, self._X, self._Y, self._H, "OK", font, self._border()
        )
        # Text "OK" should produce dark pixels somewhere inside the chip
        # interior (well inward from the pill border).
        pad_h = round(self._H * 0.18)
        text_x = self._X + pad_h
        assert_has_dark_pixels(
            img,
            text_x,
            self._Y + 4,
            text_x + 30,
            self._Y + self._H - 4,
        )

    def test_normal_mode_white_interior(self) -> None:
        img, draw = self._blank()
        font = self._font()
        # Pre-measure text width to locate the white zone past
        # the text column.
        bbox = draw.textbbox((0, 0), "X", font=font)
        text_w = bbox[2] - bbox[0]
        _draw_chip(
            draw, img, self._X, self._Y, self._H, "X", font, self._border()
        )
        # A horizontal strip at the vertical center (between border pixels)
        # that avoids the text column should be white in normal mode.
        # Text "X" is narrow; check the right half of the chip interior.
        mid_y = self._Y + self._H // 2
        pad_h = round(self._H * 0.18)
        text_right = self._X + pad_h + text_w
        chip_right = text_right + pad_h
        # There must be a white region between text end and chip right edge.
        assert_all_white(
            img,
            text_right + 2,
            mid_y - 2,
            chip_right - 2,
            mid_y + 2,
        )

    def test_inverted_mode_dark_fill(self) -> None:
        img, draw = self._blank()
        font = self._font()
        _draw_chip(
            draw,
            img,
            self._X,
            self._Y,
            self._H,
            "OK",
            font,
            self._border(),
            inverted=True,
        )
        # Check a pixel in the fill area that is left of the text column
        # so it is not overdrawn by white text.
        # Text starts at cx = x + pad_h = 20 + round(40*0.18) = 20+7 = 27.
        # A pixel at x=24 (inside pill, before text) must be black fill.
        mid_y = self._Y + self._H // 2
        assert pixel(img, self._X + 4, mid_y) == COLOR_BLACK, (
            "inverted chip interior (left of text) should be black"
        )

    def test_returns_correct_x(self) -> None:
        img, draw = self._blank()
        font = self._font()
        result = _draw_chip(
            draw, img, self._X, self._Y, self._H, "OK", font, self._border()
        )
        bbox = draw.textbbox((0, 0), "OK", font=font)
        text_w = bbox[2] - bbox[0]
        pad_h = round(self._H * 0.18)
        expected_chip_w = pad_h * 2 + text_w
        assert result == self._X + expected_chip_w, (
            f"expected {self._X + expected_chip_w}, got {result}"
        )

    def test_chip_with_icon_draws_icon_area(self) -> None:
        # Verify the icon paste branch is reached and draws dark
        # pixels in the icon area (left of the text column).
        img, draw = self._blank()
        font = self._font()
        icon_sz = 64
        # A solid black grayscale image and a fully opaque mask
        # guarantee dark pixels are pasted onto the canvas.
        gray = Image.new("L", (icon_sz, icon_sz), 0)
        mask = Image.new("L", (icon_sz, icon_sz), 255)
        _draw_chip(
            draw,
            img,
            self._X,
            self._Y,
            self._H,
            "X",
            font,
            self._border(),
            icon=(gray, mask),
        )
        # The icon is placed at pad_h + icon_x inside the chip,
        # vertically centered.  Any pixel in the icon cell must
        # be darker than the white background (255).
        pad_h = round(self._H * 0.18)
        icon_render_sz = round(self._H * 0.29)
        icon_left = self._X + pad_h
        icon_top = self._Y + (self._H - icon_render_sz) // 2
        assert_has_dark_pixels(
            img,
            icon_left,
            icon_top,
            icon_left + icon_render_sz,
            icon_top + icon_render_sz,
        )


class TestDrawChipFlow:
    # Canvas 500x400; flow at (20, 20), width 350, chip h=40.
    _X, _Y, _W, _H = 20, 20, 350, 40

    def _blank(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("L", (500, 400), 255)
        return img, ImageDraw.Draw(img)

    def _font(self) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return _load_font(14)

    def _border(self) -> int:
        return max(2, round(self._H * 0.04))

    def test_single_chip(self) -> None:
        img, draw = self._blank()
        font = self._font()
        _draw_chip_flow(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            [{"text": "OK"}],
            font,
            self._border(),
        )
        # A chip must be drawn at the starting position.
        assert_has_dark_pixels(
            img, self._X, self._Y, self._X + 80, self._Y + self._H
        )
        # No chips should appear on the second row.
        gap = round(self._H * 0.29)
        row2_y = self._Y + self._H + gap
        assert_all_white(
            img, self._X, row2_y, self._X + self._W, row2_y + self._H
        )

    def test_multiple_chips_with_gaps(self) -> None:
        img, draw = self._blank()
        font = self._font()
        _draw_chip_flow(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            [{"text": "A"}, {"text": "B"}],
            font,
            self._border(),
        )
        # Both chips must be drawn on the first row.
        assert_has_dark_pixels(
            img, self._X, self._Y, self._X + 40, self._Y + self._H
        )
        # Measure where first chip ends to find the gap region.
        bbox_a = draw.textbbox((0, 0), "A", font=font)
        text_w_a = bbox_a[2] - bbox_a[0]
        pad_h = round(self._H * 0.18)
        chip_w_a = pad_h * 2 + text_w_a
        gap = round(self._H * 0.29)
        gap_start = self._X + chip_w_a
        gap_end = gap_start + gap
        # Vertical center strip of the gap region should be white.
        mid_y = self._Y + self._H // 2
        if gap > 2:
            assert_all_white(
                img,
                gap_start + 1,
                mid_y - 2,
                gap_end - 1,
                mid_y + 2,
            )

    def test_wrapping(self) -> None:
        img, draw = self._blank()
        font = self._font()
        # Use long labels so chips fill the row quickly and wrap.
        chips = [
            {"text": "Temperature"},
            {"text": "Humidity"},
            {"text": "Pressure"},
            {"text": "Luminance"},
        ]
        _draw_chip_flow(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            chips,
            font,
            self._border(),
        )
        # At least one chip must appear on the second row.
        gap = round(self._H * 0.29)
        row2_y = self._Y + self._H + gap
        assert_has_dark_pixels(
            img,
            self._X,
            row2_y,
            self._X + self._W,
            row2_y + self._H,
        )

    def test_returns_final_y(self) -> None:
        img, draw = self._blank()
        font = self._font()
        # Single row of chips: result should be y + h.
        result = _draw_chip_flow(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            [{"text": "OK"}],
            font,
            self._border(),
        )
        assert result == self._Y + self._H, (
            f"single-row flow should return {self._Y + self._H}, got {result}"
        )

    def test_empty_chips_returns_y(self) -> None:
        img, draw = self._blank()
        font = self._font()
        result = _draw_chip_flow(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            [],
            font,
            self._border(),
        )
        assert result == self._Y, (
            f"empty chips should return y={self._Y}, got {result}"
        )

    def test_inverted_chip_in_flow(self) -> None:
        img, draw = self._blank()
        font = self._font()
        _draw_chip_flow(
            draw,
            img,
            self._X,
            self._Y,
            self._W,
            self._H,
            [{"text": "ALERT", "inverted": True}],
            font,
            self._border(),
        )
        mid_y = self._Y + self._H // 2
        assert pixel(img, self._X + 4, mid_y) == COLOR_BLACK, (
            "inverted chip in flow should have black fill"
        )

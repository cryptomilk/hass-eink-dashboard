from __future__ import annotations

import dataclasses
import datetime as dt
from unittest.mock import patch

import pytest

from custom_components.eink_dashboard.const import (
    COLOR_BLACK,
    COLOR_GRAY,
    PADDING,
)
from custom_components.eink_dashboard.render import (
    WidgetMetrics,
    _compute_metrics,
    _format_relative_date,
    _load_font,
    _parse_days_until,
    render_dashboard,
)
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    assert_vertically_centered,
    content_bbox,
    make_config,
    pixel,
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


class TestRenderDashboard:
    def test_empty_widget_list_returns_white_image(self) -> None:
        config = {"width": 100, "height": 100}
        img = render_to_image([], config)
        assert img.mode == "L"
        assert img.size == (100, 100)
        assert pixel(img, 50, 50) == 255

    def test_returns_valid_png(self) -> None:
        config = {"width": 200, "height": 300}
        img = render_to_image([], config)
        assert img.format == "PNG"
        assert img.size == (200, 300)

    def test_rotation_90(self) -> None:
        config = {"width": 200, "height": 100, "rotation": 90}
        img = render_to_image([], config)
        assert img.size == (100, 200)

    def test_rotation_270(self) -> None:
        config = {"width": 200, "height": 100, "rotation": 270}
        img = render_to_image([], config)
        assert img.size == (100, 200)

    def test_unknown_widget_type_is_skipped(self) -> None:
        config = {"width": 100, "height": 100}
        widgets = [{"type": "nonexistent", "x": 10, "y": 10}]
        img = render_to_image(widgets, config)
        assert img.size == (100, 100)


class TestRenderText:
    # Verify rendering of the text widget (SVG pipeline).
    _DEFAULTS: dict[str, object] = {
        "width": 200,
        "height": 100,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def test_text_draws_pixels(self) -> None:
        # Left-aligned text renders dark pixels in the expected region.
        widgets = [
            {
                "type": "text",
                "x": 10,
                "y": 10,
                "text": "Hello",
                "font_size": 20,
            }
        ]
        img = render_to_image(widgets, self._config())
        # x=10 start; right bound 100 = left half of 200px canvas
        assert_has_dark_pixels(img, 10, 10, 100, 40)

    def test_text_right_align(self) -> None:
        # Right-aligned text appears near the right edge of the canvas.
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
        img = render_to_image(widgets, self._config())
        # Right 60px of 200px canvas — where short right-aligned text
        # lands when anchored to the right edge.
        assert_has_dark_pixels(img, 140, 10, 200, 40)

    def test_text_right_align_left_is_white(self) -> None:
        # Right-aligned text leaves the far-left region blank.
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
        img = render_to_image(widgets, self._config())
        # Left 40% of 200px canvas — comfortably clear of
        # right-aligned "Hi" which lands near the right edge.
        assert_all_white(img, 0, 10, 80, 40)

    def test_text_center_align(self) -> None:
        # Center-aligned text appears in the middle of the available width.
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
        img = render_to_image(widgets, self._config())
        # Middle 40px band (80–120) of 200px canvas — centered
        # "Hi" at font_size 20 should fall in this range.
        assert_has_dark_pixels(img, 80, 10, 120, 40)

    def test_text_custom_color(self) -> None:
        # A non-black color value renders as gray rather than black.
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
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(img, 10, 10, 80, 40, low=100, high=200)

    def test_text_empty_string_is_white(self) -> None:
        # An empty text string produces no visible content.
        widgets = [{"type": "text", "x": 0, "y": 0, "text": ""}]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 200, 100)

    def test_text_explicit_w_constrains_right_align(self) -> None:
        # With explicit w, right-aligned text stays within the widget
        # boundary, not spread across the full canvas width.
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "Hi",
                "font_size": 20,
                "align": "right",
                "w": 100,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Right half of w=100 — right-aligned "Hi" anchors to x=100.
        assert_has_dark_pixels(img, 50, 0, 100, 30)
        # Left 40px of w=100 — clear of right-aligned "Hi".
        assert_all_white(img, 0, 0, 40, 30)

    def test_text_scales_with_font_size(self) -> None:
        # Doubling font_size approximately doubles rendered glyph height.
        config = self._config(width=400, height=200)
        small = render_to_image(
            [
                {
                    "type": "text",
                    "x": 0,
                    "y": 0,
                    "text": "X",
                    "font_size": 20,
                }
            ],
            config,
        )
        large = render_to_image(
            [
                {
                    "type": "text",
                    "x": 0,
                    "y": 0,
                    "text": "X",
                    "font_size": 40,
                }
            ],
            config,
        )
        assert_scales_proportionally(
            small,
            large,
            # 40×35 covers a 20px glyph; 70×60 covers a 40px glyph.
            region_small=(0, 0, 40, 35),
            region_large=(0, 0, 70, 60),
            expected_ratio=2.0,
            tolerance=0.35,
        )

    def test_text_card_border(self) -> None:
        # card_style="border" draws dark pixels along all four edges.
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 60,
                "text": "Hello",
                "font_size": 20,
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config(width=400, height=60))
        m = _compute_metrics(60)
        assert_card_border(img, 400, 60, m, bottom_margin=0)

    def test_text_card_left_bar(self) -> None:
        # card_style="left_bar" draws a solid gray bar on the left
        # edge; the center of that bar must be exactly COLOR_GRAY.
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 60,
                "text": "Hello",
                "font_size": 20,
                "card_style": "left_bar",
            }
        ]
        img = render_to_image(widgets, self._config(width=400, height=60))
        m = _compute_metrics(60)
        # The midpoint of the bar must be solid gray (not text
        # anti-aliasing): the bar fill color is #787878 = 120.
        bar_mid_x = m.left_bar // 2
        assert pixel(img, bar_mid_x, 30) == COLOR_GRAY
        # Right edge — white (no right-side decoration)
        assert_all_white(img, 395, 0, 400, 60)

    def test_text_card_none_explicit(self) -> None:
        # Explicit card_style="none" renders no card decoration
        # but the text content is still visible.
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 60,
                "text": "Hello",
                "font_size": 20,
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config(width=400, height=60))
        # No border — corners must be white
        assert pixel(img, 0, 0) == 255
        assert pixel(img, 399, 0) == 255
        assert pixel(img, 0, 59) == 255
        assert pixel(img, 399, 59) == 255
        # Text is still visible somewhere in the widget area
        assert_has_dark_pixels(img, 0, 0, 400, 60)

    def test_text_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none".
        config = self._config(width=400, height=60)
        base = {
            "type": "text",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 60,
            "text": "Hello",
            "font_size": 20,
        }
        with_none = render_dashboard([{**base, "card_style": "none"}], config)
        without = render_dashboard([base], config)
        assert with_none == without

    def test_text_card_border_text_offset(self) -> None:
        # With card_style="border" the text is inset by the card padding
        # and must not appear between the border and the padding gap.
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 60,
                "text": "Hello",
                "font_size": 20,
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config(width=400, height=60))
        m = _compute_metrics(60)
        # Gap between border and content padding — should be white
        # in the straight section of the border (past the corner radius).
        if m.padding > m.border + 1 and m.radius < 30:
            assert_all_white(
                img,
                m.border + 1,
                m.radius + 1,
                m.padding,
                60 - m.radius - 1,
            )
        # Text content exists to the right of the padding inset
        assert_has_dark_pixels(img, m.padding, 0, 400 - m.padding, 60)

    def test_text_with_title(self) -> None:
        # An optional title renders as gray text above the card area;
        # the main text must be pushed below the title band, so the
        # area immediately below the title band must be white when no
        # card_style decoration fills it.
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "text": "Hello",
                "font_size": 20,
                "title": "Section",
            }
        ]
        img_with = render_to_image(widgets, self._config(width=400, height=80))
        # Without a title the canvas top should be darker (main text).
        img_without = render_to_image(
            [
                {
                    "type": "text",
                    "x": 0,
                    "y": 0,
                    "w": 400,
                    "h": 80,
                    "text": "Hello",
                    "font_size": 20,
                }
            ],
            self._config(width=400, height=80),
        )
        # The two renders must differ (title moves the main text down)
        assert img_with.tobytes() != img_without.tobytes()
        # Title band must contain gray pixels (title text color).
        title_font_sz = max(10, round(80 * 0.14))
        title_advance = round(title_font_sz * 1.4)
        assert_has_gray_pixels(
            img_with, 0, 0, 400, title_advance, low=100, high=200
        )

    def test_text_card_border_vertically_centered(self) -> None:
        # With card_style="border" the text is vertically centered
        # inside the card, not pinned to the top.
        h = 80
        widgets = [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "text": "Hello",
                "font_size": 20,
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config(width=400, height=h))
        m = _compute_metrics(h)
        # Text must appear in the middle vertical band — at least some
        # dark pixels between 25 % and 75 % of the card height.
        quarter = h // 4
        assert_has_dark_pixels(
            img, m.padding, quarter, 400 - m.padding, h - quarter
        )
        # The top strip (just inside the border, before centre band)
        # must be white — text should not be pinned to the top.
        top_strip_end = h // 4 - 2
        if top_strip_end > m.border + 2:
            assert_all_white(
                img, m.padding + 2, m.border + 2, 300, top_strip_end
            )


class TestRenderSeparator:
    _CONFIG = {"width": 300, "height": 200}

    def test_separator_default_horizontal_line(self) -> None:
        # Default: horizontal line, 2px black, spans PADDING to width-PADDING.
        widgets = [{"type": "separator", "x": PADDING, "y": 50}]
        img = render_to_image(widgets, self._CONFIG)
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
        img = render_to_image(widgets, self._CONFIG)
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
        img = render_to_image(widgets, self._CONFIG)
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
        img = render_to_image(widgets, self._CONFIG)
        assert_has_gray_pixels(img, 50, PADDING, 56, 175)
        assert_all_white(img, 58, PADDING, 70, 175)

    def test_separator_explicit_length(self) -> None:
        # length=100 limits the separator to 100px from x.
        widgets = [{"type": "separator", "x": PADDING, "y": 50, "length": 100}]
        img = render_to_image(widgets, self._CONFIG)
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
        img = render_to_image(widgets, self._CONFIG)
        assert_has_dark_pixels(img, 50, PADDING, 52, PADDING + 80)
        assert pixel(img, 50, PADDING + 82) == 255

    def test_separator_bar_2level_widens(self) -> None:
        # grayscale_levels=2 widens a bar to ~10-12px.
        config = {**self._CONFIG, "grayscale_levels": 2}
        widgets = [
            {"type": "separator", "x": PADDING, "y": 50, "style": "bar"}
        ]
        img = render_to_image(widgets, config)
        bb = content_bbox(img, PADDING, 50, 275, 70)
        assert bb is not None
        bar_h = bb[3] - bb[1]
        assert bar_h >= 10

    def test_separator_line_ignores_2level(self) -> None:
        # style="line" stays 2px even on 2-level displays.
        config = {**self._CONFIG, "grayscale_levels": 2}
        widgets = [{"type": "separator", "x": PADDING, "y": 50}]
        img = render_to_image(widgets, config)
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
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 400, 56, m)

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
        img = render_to_image(widgets, self._config())
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
        img = render_to_image(widgets, self._config())
        # Top-left corner should be white (no border, no bar)
        assert_all_white(img, 0, 0, 3, 3)
        # Far right edge should be white
        assert_all_white(img, 397, 0, 400, 3)

    def test_sensor_rows_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none" (no card decoration drawn).
        base = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["sensor.living_room_temperature"],
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

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
        img = render_to_image(widgets, self._config())
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
        img = render_to_image(widgets, self._config())
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
        img = render_to_image(widgets, self._config())
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
        img_s = render_to_image([widget_small], self._config())
        img_l = render_to_image([widget_large], self._config())
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
        img = render_to_image(widgets, self._config())
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
        img = render_to_image(widgets, self._config())
        # Title is rendered in COLOR_GRAY, so assert gray pixels
        # (not just any dark pixels) in the title region.
        assert_has_gray_pixels(img, 0, 0, 200, 20)

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
        img = render_to_image(widgets, self._config())
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
        # A nonexistent entity is filtered out before row_h is
        # computed, so the present entity fills the full height
        # with no blank gap above it.
        m = _compute_metrics(112)
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
        img = render_to_image(widgets, self._config())
        # sensor.humidity is the only resolved entity and
        # occupies the full 112 px height.
        assert_has_dark_pixels(
            img,
            m.padding,
            2,
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
        img = render_to_image(widgets, self._config())
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
        img = render_to_image(widgets, self._config())
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
        img = render_to_image(widgets, self._config())
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
        img = render_to_image(widgets, self._config())
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
    # Verify rendering of device battery widgets in both icon and chip
    # layouts.  Icon layout renders a compact battery outline with fill
    # bar sized proportionally from h (default h=40 → 30×14 body).
    # Chip layout uses w/h-based sizing with a pill-shaped container.
    _DEFAULTS: dict[str, object] = {
        "width": 400,
        "height": 100,
        "device_battery_level": 75,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # -- Icon layout (default): bigger battery icon (30x14) ----------

    def test_icon_draws_fill(self) -> None:
        # Verify the fill bar renders inside the battery body.
        # At 75%: fill_w = int((30-2)*75/100) = 21 px.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Fill region: (PADDING+1, icon_y+1) to (PADDING+22, icon_y+bh-1)
        # icon_y=30, bh=14 → fill at (25, 31) to (46, 43)
        assert_has_dark_pixels(img, PADDING + 1, 31, PADDING + 22, 43)

    def test_icon_draws_percentage_text(self) -> None:
        # Verify percentage label appears to the right of the icon.
        # Text starts at x + 30 + 1 + 3 + 4 = x + 38
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, PADDING + 38, 29, PADDING + 80, 47)

    def test_icon_draws_nub(self) -> None:
        # Verify the nub (battery terminal) renders in gray.
        # Nub at (PADDING+31, nub_y) to (PADDING+33, nub_y+8)
        # nub_y = icon_y + (14-8)//2 = 30 + 3 = 33
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            PADDING + 31,
            33,
            PADDING + 34,
            41,
            threshold=200,
        )

    def test_icon_draws_outline(self) -> None:
        # Verify the battery body outline (gray rectangle).
        # Body from (PADDING, 30) to (PADDING+30, 44)
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Top edge of body
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 30, 31, threshold=200
        )
        # Left edge of body
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 1, 44, threshold=200
        )

    def test_icon_vertically_centers_with_text(self) -> None:
        # Verify the battery icon is vertically centred against
        # the text label.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Icon region: battery body area
        # Text region: right of nub+gap
        assert_vertically_centered(
            img,
            icon_region=(PADDING, 28, PADDING + 34, 46),
            text_region=(PADDING + 38, 20, PADDING + 90, 50),
            tolerance=3.0,
        )

    def test_icon_zero_percent(self) -> None:
        # Verify 0% shows outline only, no fill.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config(device_battery_level=0))
        # Outline is present (gray, threshold=200)
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 34, 44, threshold=200
        )
        # Interior should be white (no fill bar)
        assert_all_white(img, PADDING + 2, 32, PADDING + 28, 42)

    def test_icon_100_percent(self) -> None:
        # Verify 100% fills the entire battery body interior.
        # fill_w = int((30-2)*100/100) = 28
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config(device_battery_level=100))
        assert_has_dark_pixels(img, PADDING + 1, 31, PADDING + 29, 43)

    def test_icon_scales_with_h(self) -> None:
        # Doubling h doubles the battery icon body dimensions.
        # At h=40: body is 30×14. At h=80: body is ~60×28.
        cfg_small = make_config(
            {"width": 400, "height": 60, "device_battery_level": 75}
        )
        cfg_large = make_config(
            {
                "width": 400,
                "height": 100,
                "device_battery_level": 75,
            }
        )
        img_small = render_to_image(
            [
                {
                    "type": "device_battery",
                    "x": 0,
                    "y": 0,
                    "h": 40,
                }
            ],
            cfg_small,
        )
        img_large = render_to_image(
            [
                {
                    "type": "device_battery",
                    "x": 0,
                    "y": 0,
                    "h": 80,
                }
            ],
            cfg_large,
        )
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(0, 0, 400, 60),
            region_large=(0, 0, 400, 100),
            expected_ratio=2.0,
            tolerance=0.35,
        )

    def test_icon_default_layout(self) -> None:
        # Verify that omitting layout defaults to "icon" and renders
        # the battery body (not a chip).
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Battery body outline at (PADDING, 30)
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 30, 44, threshold=200
        )

    # -- Data edge cases (shared by both layouts) --------------------

    def test_none_level_is_noop(self) -> None:
        # Verify null battery level produces a blank canvas.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config(device_battery_level=None))
        assert_all_white(img, 0, 0, 400, 100)

    def test_missing_key_is_noop(self) -> None:
        # Verify absent device_battery_level key produces blank canvas.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, {"width": 400, "height": 100})
        assert_all_white(img, 0, 0, 400, 100)

    def test_icon_low_battery_forces_black(self) -> None:
        # Below 20% overrides color to black for emphasis; both colors
        # produce identical output and the widget actually draws pixels.
        base = {
            "type": "device_battery",
            "x": PADDING,
            "y": 20,
        }
        cfg = self._config(device_battery_level=15)
        gray_img = render_to_image([{**base, "color": COLOR_GRAY}], cfg)
        black_img = render_to_image([{**base, "color": COLOR_BLACK}], cfg)
        assert gray_img.tobytes() == black_img.tobytes()
        # Verify something was actually drawn (guards against both
        # renders producing blank images, which would also be equal).
        assert_has_dark_pixels(
            gray_img, PADDING, 30, PADDING + 35, 44, threshold=200
        )

    def test_chip_low_battery_forces_black(self) -> None:
        # Below 20% chip overrides color to black for emphasis; both
        # colors produce identical output and the widget draws pixels.
        base = {
            "type": "device_battery",
            "x": PADDING,
            "y": 10,
            "h": 40,
            "layout": "chip",
        }
        cfg = self._config(device_battery_level=10)
        gray_img = render_to_image([{**base, "color": COLOR_GRAY}], cfg)
        black_img = render_to_image([{**base, "color": COLOR_BLACK}], cfg)
        assert gray_img.tobytes() == black_img.tobytes()
        # Verify the chip was actually rendered with dark pixels.
        assert_has_dark_pixels(
            gray_img, PADDING, 10, PADDING + 80, 50, threshold=200
        )

    # -- Chip layout -------------------------------------------------

    def test_chip_draws_pill_shape(self) -> None:
        # Verify the chip has a pill-shaped border (rounded corners).
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Extreme corner should be white (outside pill radius)
        assert pixel(img, PADDING, 10) == 255
        # A few pixels inward along the top edge should have border
        assert_has_dark_pixels(img, PADDING + 10, 10, PADDING + 30, 12)

    def test_chip_draws_fill_bar(self) -> None:
        # Verify the fill bar appears inside the chip at 75%.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Fill bar should exist in the left portion of the bar
        assert_has_dark_pixels(img, PADDING + 8, 18, PADDING + 42, 36)
        # Right 25% of bar interior should be unfilled
        assert_all_white(img, PADDING + 43, 24, PADDING + 54, 36)

    def test_chip_draws_percentage_text(self) -> None:
        # Verify percentage label appears inside the chip.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Text should appear in the right portion of the chip
        assert_has_dark_pixels(img, PADDING + 60, 14, PADDING + 150, 46)

    def test_chip_zero_percent_shows_outline_only(self) -> None:
        # Verify 0% chip has the bar outline but no fill inside.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config(device_battery_level=0))
        # The chip outline should still be present
        assert_has_dark_pixels(img, PADDING + 10, 10, PADDING + 150, 50)
        # Interior of the bar should be white (no fill)
        assert_all_white(img, PADDING + 8, 24, PADDING + 54, 36)

    def test_chip_100_percent_fills_bar(self) -> None:
        # Verify 100% chip fills the entire bar interior.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config(device_battery_level=100))
        # Right portion that is white at 75% should be filled
        assert_has_dark_pixels(img, PADDING + 43, 24, PADDING + 54, 36)

    def test_chip_scales_with_h(self) -> None:
        # Verify doubling h roughly doubles the chip content height.
        small_widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 30,
                "layout": "chip",
            }
        ]
        large_widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 300,
                "h": 60,
                "layout": "chip",
            }
        ]
        cfg = self._config()
        img_small = render_to_image(small_widgets, cfg)
        img_large = render_to_image(large_widgets, cfg)
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(0, 0, 200, 30),
            region_large=(0, 0, 300, 60),
            expected_ratio=2.0,
            tolerance=0.35,
        )

    # -- Card style (shared by both layouts) -------------------------

    def test_card_style_border_icon(self) -> None:
        # Border style draws a rounded rectangle frame around
        # the icon layout; content still renders inside.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "border",
                "layout": "icon",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 200, 56, m)
        # Content (battery icon) renders inside the card
        assert_has_dark_pixels(
            img, m.padding, 5, m.padding + 40, 56, threshold=200
        )

    def test_card_style_border_chip(self) -> None:
        # Border style draws a rounded rectangle frame around
        # the chip layout; content still renders inside.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "border",
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 200, 56, m)
        # Content (fill bar) renders inside the card
        assert_has_dark_pixels(img, m.padding + 5, 15, m.padding + 60, 45)

    def test_card_style_left_bar_icon(self) -> None:
        # Left_bar style draws a gray vertical bar spanning the
        # full card height.  Checking below y≈25 avoids the
        # battery body outline (y≈6–20) which is also gray.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "left_bar",
                "layout": "icon",
            }
        ]
        img = render_to_image(widgets, self._config())
        # The bar must extend into the lower portion of the card
        # (below the battery icon at ~y=6–20).
        assert_has_gray_pixels(
            img,
            0,
            35,
            m.left_bar,
            54,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Right edge should be white
        assert_all_white(img, 197, 0, 200, 3)

    def test_card_style_left_bar_chip(self) -> None:
        # Left_bar style draws a gray vertical bar on the left
        # edge for the chip layout.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "left_bar",
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            54,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Right edge should be white
        assert_all_white(img, 197, 0, 200, 3)

    def test_card_style_none_is_default(self) -> None:
        # Omitting card_style produces identical output to
        # explicit card_style="none".
        base: dict[str, object] = {
            "type": "device_battery",
            "x": PADDING,
            "y": 10,
            "w": 200,
            "h": 56,
            "layout": "chip",
        }
        cfg = self._config()
        with_none = render_dashboard([{**base, "card_style": "none"}], cfg)
        without = render_dashboard([base], cfg)
        assert with_none == without

    def test_card_style_none_no_border(self) -> None:
        # Explicit card_style="none" has no border decoration
        # on any edge.
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "none",
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Top-left corner: white (no border)
        assert_all_white(img, 0, 0, 3, 3)
        # Right edge: white (no border)
        assert_all_white(img, 197, 0, 200, 3)


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


class TestRenderStatusIcons:
    # Verify rendering of status_icons widgets as icon-and-text
    # labels with MDI icons and card containers.
    _DEFAULTS: dict[str, object] = {
        "width": 500,
        "height": 200,
        "states": MOCK_STATUS_ICON_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_no_label_rect(self) -> None:
        # Labels have no enclosing rectangle — the top-left
        # corner is white (no border stroke).
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
        img = render_to_image(widgets, self._config())
        assert pixel(img, 0, 0) == 255
        assert pixel(img, 0, h - 1) == 255

    def test_auto_width(self) -> None:
        # When no explicit w is set, the card border shrinks
        # to fit the content instead of spanning the display.
        h = 40
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "h": h,
                "card_style": "border",
                "entities": [
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        img = render_to_image(widgets, self._config())
        # Right quarter of the 500px canvas is white — the
        # card border does not extend to the display edge.
        assert_all_white(img, 375, 0, 500, h)

    def test_wrapping(self) -> None:
        # Narrow w forces labels to wrap to the next row.
        h = 40
        gap = int(h * 0.18)
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
        img = render_to_image(widgets, self._config())
        # Dark pixels must exist below the first label row
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
        # Entity with a mapped device_class renders an MDI icon
        # inside a state circle.
        h = 40
        pad = int(h * 0.18)
        icon_dia = int(h * 0.64)
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
        img = render_to_image(widgets, self._config())
        # Circle area has dark pixels (outlined circle stroke
        # or icon content).
        assert_has_dark_pixels(
            img,
            pad,
            0,
            pad + icon_dia,
            h,
        )

    def test_title(self) -> None:
        # Title text is rendered above the chip area in gray.
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
        img = render_to_image(widgets, self._config())
        title_font_sz = max(10, round(h * 0.14))
        title_advance = round(title_font_sz * 1.4)
        # Title area has content (threshold=200 catches gray text).
        assert_has_dark_pixels(img, 0, 0, 200, title_advance, threshold=200)
        # Label content starts below the title.
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
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 500, 200)

    def test_all_entities_missing_noop(self) -> None:
        # All listed entities absent from states → canvas is
        # entirely white (same outcome as empty entity list).
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 40,
                "entities": [
                    "binary_sensor.nonexistent_a",
                    "binary_sensor.nonexistent_b",
                ],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 500, 200)

    def test_missing_entity_skipped(self) -> None:
        # Nonexistent entity is silently skipped; the valid
        # entity still renders.
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
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, 0, 0, 400, 40)

    def test_icon_fallback_from_entity_attr(self) -> None:
        # Entity without a device_class mapping but with an
        # icon attribute renders the icon via the mdi: fallback.
        h = 40
        pad = int(h * 0.18)
        icon_dia = int(h * 0.64)
        states = {
            "sensor.custom": {
                "state": "on",
                "attributes": {
                    "friendly_name": "Custom",
                    "icon": "mdi:washing-machine",
                },
            },
        }
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": ["sensor.custom"],
            }
        ]
        cfg = self._config(states=states)
        img = render_to_image(widgets, cfg)
        # Circle area has dark pixels confirming the fallback
        # icon was rendered inside the state circle.
        assert_has_dark_pixels(
            img,
            pad,
            0,
            pad + icon_dia,
            h,
        )

    # ── State indicator tests ────────────────────────

    def test_circle_filled_when_on(self) -> None:
        # Entity with state "on" has a filled gray circle —
        # the circle centre is dark.
        h = 40
        pad = int(h * 0.18)
        icon_dia = int(h * 0.64)
        cx = pad + icon_dia // 2
        cy = h // 2
        states = {
            "binary_sensor.front_door": {
                "state": "on",
                "attributes": {
                    "friendly_name": "Front Door",
                    "device_class": "door",
                },
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
                    "binary_sensor.front_door",
                ],
            }
        ]
        cfg = self._config(states=states)
        img = render_to_image(widgets, cfg)
        # Circle interior near the edge (away from icon
        # content) should be gray-filled.
        assert pixel(img, cx - icon_dia // 2 + 2, cy) < 160

    def test_circle_outlined_when_off(self) -> None:
        # Entity with state "off" has an outlined circle —
        # the circle interior is white with a dark stroke.
        h = 80
        pad = int(h * 0.18)
        icon_dia = int(h * 0.64)
        icon_r = icon_dia // 2
        cx = pad + icon_r
        cy = h // 2
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
        img = render_to_image(widgets, self._config())
        # Outlined circle has dark stroke at the top.
        circle_top = cy - icon_r
        assert_has_dark_pixels(
            img,
            cx - 2,
            circle_top,
            cx + 2,
            circle_top + 4,
        )
        # Gap between stroke and icon is white.  Probe 3 px
        # inside the left edge of the circle, where the icon
        # SVG (60 % of circle dia) hasn't started yet.
        probe_x = pad + 3
        assert pixel(img, probe_x, cy) >= 200

    def test_show_state_text(self) -> None:
        # show_state appends the entity state to the label text,
        # making the rendered content wider.
        h = 40
        entity = ["binary_sensor.kitchen_window"]
        base_widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": entity,
            }
        ]
        state_widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "show_state": True,
                "entities": entity,
            }
        ]
        img_base = render_to_image(base_widgets, self._config())
        img_state = render_to_image(
            state_widgets,
            self._config(),
        )
        # The state-text variant has wider content.
        bbox_base = content_bbox(img_base, 0, 0, 400, h)
        bbox_state = content_bbox(img_state, 0, 0, 400, h)
        assert bbox_state[2] > bbox_base[2]

    def test_show_icon_false_no_circle(self) -> None:
        # show_icon=False suppresses the icon circle — the
        # label starts near the left edge without a circle gap.
        h = 40
        entity = ["binary_sensor.kitchen_window"]
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "show_icon": False,
                "entities": entity,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Circle area (pad..pad+icon_dia) is white — no circle
        # drawn.  Text starts at pad, so check only the circle
        # area past where text ink could appear by verifying
        # content is narrower than the icon variant.
        icon_widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": entity,
            }
        ]
        img_icon = render_to_image(icon_widgets, self._config())
        bbox_no = content_bbox(img, 0, 0, 400, h)
        bbox_yes = content_bbox(img_icon, 0, 0, 400, h)
        # Without icon circle, content is narrower.
        assert bbox_no[2] < bbox_yes[2]

    # ── Scaling tests ─────────────────────────────────

    def test_scales_with_h(self) -> None:
        # Doubling h roughly doubles label content height.
        h_small = 40
        h_large = 80
        entity = ["binary_sensor.kitchen_window"]
        img_s = render_to_image(
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
        img_l = render_to_image(
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
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(0, 0, 400, h_small),
            region_large=(0, 0, 400, h_large),
            expected_ratio=2.0,
        )

    # ── Alignment tests ───────────────────────────────

    def test_icon_vertically_centered(self) -> None:
        # Icon circle and text share the same vertical centre
        # within the label.
        h = 40
        pad = int(h * 0.18)
        icon_dia = int(h * 0.64)
        icon_gap = int(h * 0.14)
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
        img = render_to_image(widgets, self._config())
        text_start = pad + icon_dia + icon_gap
        # tolerance=3.0: resvg dominant-baseline="central"
        # differs slightly from PIL's ascender-based centering.
        assert_vertically_centered(
            img,
            icon_region=(pad, 0, pad + icon_dia, h),
            text_region=(text_start, 0, 300, h),
            tolerance=3.0,
        )

    # ── Card container tests ──────────────────────────

    def test_card_border(self) -> None:
        # Border style draws dark pixels on all four edges
        # of the label container.
        h = 40
        W = 400
        m = _compute_metrics(h)
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": W,
                "h": h,
                "card_style": "border",
                "entities": [
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, W, h, m)

    def test_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge;
        # the right edge is white.
        h = 40
        m = _compute_metrics(h)
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "card_style": "left_bar",
                "entities": [
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        img = render_to_image(widgets, self._config())
        # The bar fills the full height; 2px inset avoids
        # sub-pixel edge effects at top/bottom.
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            h - 2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Right edge: no decoration.
        assert_all_white(img, 395, 0, 400, 1)

    def test_card_none(self) -> None:
        # No-decoration style has white corners — only label
        # content draws pixels.
        h = 40
        widgets = [
            {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "card_style": "none",
                "entities": [
                    "binary_sensor.kitchen_window",
                ],
            }
        ]
        img = render_to_image(widgets, self._config())
        # Top-left corner: no border, no bar.
        assert_all_white(img, 0, 0, 3, 3)
        # Far right edge: no decoration.
        assert_all_white(img, 397, 0, 400, 3)

    def test_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output
        # to card_style="none" (no card decoration drawn).
        base = {
            "type": "status_icons",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 40,
            "entities": ["binary_sensor.kitchen_window"],
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without


MOCK_WASTE_SCHEDULE_STATES = {
    "sensor.waste_collection": {
        "state": "Restmuell in 1 day",
        "attributes": {
            "friendly_name": "Waste Collection",
            "Restmuell": "2026-05-03",
            "Biotonne": "2026-05-04",
            "Papier": "2026-05-05",
        },
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

    def test_parse_iso_datetime(self) -> None:
        # ISO datetime strings (with time component) should parse
        # by extracting just the date portion, like TypeScript does.
        today = dt.date(2026, 5, 2)
        assert _parse_days_until("2026-05-03T10:00:00", today) == 1
        assert _parse_days_until("2026-05-02T00:00:00", today) == 0

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
    # Verify rendering of redesigned waste_schedule widgets
    # using card container + trash-can icon + urgency styling.
    # Data model: single entity with attribute-based dates.

    _ENTRIES: list[dict[str, str]] = [
        {"attribute": "Restmuell", "label": "Restmuell"},
        {"attribute": "Biotonne", "label": "Bio"},
        {"attribute": "Papier", "label": "Papier"},
    ]

    _DEFAULTS: dict[str, object] = {
        "width": 400,
        "height": 300,
        "states": MOCK_WASTE_SCHEDULE_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def _widget(self, **overrides: object) -> dict[str, object]:
        """Build a waste_schedule widget config with defaults."""
        base: dict[str, object] = {
            "type": "waste_schedule",
            "entity": "sensor.waste_collection",
            "entries": list(self._ENTRIES),
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 168,
        }
        base.update(overrides)
        return base

    # ── Structural tests ──────────────────────────────

    def test_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        row_h = 168 // 3
        m = _compute_metrics(row_h)
        w = self._widget(card_style="border")
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_card_border(img, 400, 168, m)

    def test_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge;
        # right edge should be white.
        row_h = 168 // 3
        m = _compute_metrics(row_h)
        w = self._widget(card_style="left_bar")
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            166,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Right edge: no decoration
        assert_all_white(img, 395, 0, 400, 1)

    def test_card_none(self) -> None:
        # No-decoration style has white corners.
        w = self._widget(card_style="none")
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Top-left corner should be white
        assert_all_white(img, 0, 0, 3, 3)
        # Far right edge should be white
        assert_all_white(img, 397, 0, 400, 3)

    def test_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none" (no card decoration drawn).
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            with_none = render_dashboard(
                [self._widget(card_style="none")], self._config()
            )
            without = render_dashboard([self._widget()], self._config())
        assert with_none == without

    def test_row_divider(self) -> None:
        # Gray dividers exist at row boundaries between rows.
        row_h = 168 // 3
        m = _compute_metrics(row_h)
        w = self._widget()
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Divider at first row boundary (y = row_h)
        assert_has_gray_pixels(
            img,
            m.padding + 20,
            row_h - m.divider,
            380,
            row_h + m.divider,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_no_divider_single_entry(self) -> None:
        # Single entry should not produce a divider below.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Area just below the row must be white
        assert_all_white(img, 0, 57, 400, 60)

    # ── Alignment tests ───────────────────────────────

    def test_icon_centered_with_text(self) -> None:
        # Icon circle is vertically centered with the text
        # in a single-entry row.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        h = 56
        m = _compute_metrics(h)
        w = self._widget(
            entries=entries,
            h=h,
            card_style="border",
        )
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        icon_left = m.padding
        icon_right = icon_left + m.icon_dia
        text_left = icon_right + m.inner_gap
        assert_vertically_centered(
            img,
            icon_region=(icon_left, 0, icon_right, h),
            text_region=(text_left, 0, 380, h),
            tolerance=3.0,
        )

    # ── Scaling tests ─────────────────────────────────

    def test_scales_with_h(self) -> None:
        # Doubling h roughly doubles icon area content height.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        m_small = _compute_metrics(56)
        m_large = _compute_metrics(112)
        w_small = self._widget(entries=entries, h=56)
        w_large = self._widget(entries=entries, h=112)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img_s = render_to_image([w_small], self._config())
            img_l = render_to_image([w_large], self._config())
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

    def test_draws_entries(self) -> None:
        # All 3 entries within range render content in their
        # respective row regions.
        row_h = 168 // 3
        w = self._widget()
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Row 0 (Restmuell, days=1)
        assert_has_dark_pixels(
            img,
            0,
            0,
            400,
            row_h,
            threshold=200,
        )
        # Row 1 (Biotonne, days=2)
        assert_has_dark_pixels(
            img,
            0,
            row_h,
            400,
            2 * row_h,
            threshold=200,
        )
        # Row 2 (Papier, days=3)
        assert_has_dark_pixels(
            img,
            0,
            2 * row_h,
            400,
            3 * row_h,
            threshold=200,
        )

    def test_with_title(self) -> None:
        # Title text is rendered above the card area.
        h = 100
        w = self._widget(
            title="Waste",
            entries=[
                {"attribute": "Restmuell", "label": "Restmuell"},
            ],
            h=h,
        )
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Title area near the top
        assert_has_dark_pixels(img, 0, 0, 200, 20)

    def test_missing_attribute_skipped(self) -> None:
        # An entry whose attribute is absent from the entity
        # is silently skipped.
        entries = [
            {"attribute": "Nonexistent", "label": "Gone"},
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Only one visible entry; content should exist
        assert_has_dark_pixels(
            img,
            0,
            0,
            400,
            56,
            threshold=200,
        )

    def test_empty_entries_noop(self) -> None:
        # Empty entries list produces a white canvas.
        w = self._widget(entries=[])
        img = render_to_image([w], self._config())
        assert_all_white(img, 0, 0, 400, 300)

    def test_entity_missing_noop(self) -> None:
        # Entity not in states produces a white canvas.
        w = self._widget(entity="sensor.nonexistent")
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_all_white(img, 0, 0, 400, 300)

    def test_urgency_today_black_icon(self) -> None:
        # days=0: icon circle should be filled black (not gray).
        # The icon image sits at 60% of icon_dia in the center,
        # so we check the ring between icon and circle edge.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        h = 80
        m = _compute_metrics(h)
        w = self._widget(entries=entries, h=h)
        # Restmuell = 2026-05-03; today = 2026-05-03 → days=0
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = dt.date(2026, 5, 3)
            img = render_to_image([w], self._config())
        # Check the ring along the horizontal centerline
        # where we're guaranteed to be inside the circle
        # but outside the 60%-scaled icon.
        ring_x = m.padding + 4
        ring_y = h // 2
        assert pixel(img, ring_x, ring_y) < 64

    def test_urgency_tomorrow_black_icon(self) -> None:
        # days=1: icon circle should be filled black (not gray).
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        h = 80
        m = _compute_metrics(h)
        w = self._widget(entries=entries, h=h)
        # Restmuell = 2026-05-03; today = 2026-05-02 → days=1
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        ring_x = m.padding + 4
        ring_y = h // 2
        assert pixel(img, ring_x, ring_y) < 64

    def test_urgency_future_outline_icon(self) -> None:
        # days=2: icon circle should be drawn as a black outline
        # on white background, not as a filled gray circle.
        entries = [
            {"attribute": "Biotonne", "label": "Bio"},
        ]
        h = 80
        m = _compute_metrics(h)
        w = self._widget(entries=entries, h=h)
        # Biotonne = 2026-05-04; today = 2026-05-02 → days=2
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # The stroke pixel at the leftmost point of the circle path
        # should be black (outline stroke).  PIL strokes inside the
        # bounding box so padding+2 was safe; resvg centers the stroke
        # on the path (inner edge at padding+1.5), making padding+2 fall
        # in the white fill area.  Use padding (the path x-coordinate
        # itself) which is firmly in the stroke for both engines.
        stroke_x = m.padding
        ring_y = h // 2
        assert pixel(img, stroke_x, ring_y) < 64
        # The interior pixel (well inside the stroke, before
        # the icon image begins) should be white (fill).
        # icon_dia=51, border=3: resvg stroke inner edge at ~x=18.5,
        # fill starts at x=19.  Check at padding+border+3=23 to stay
        # safely in the white fill for both engines.
        interior_x = m.padding + m.border + 3
        assert pixel(img, interior_x, ring_y) > 200

    def test_date_right_aligned(self) -> None:
        # Relative date text appears near the right edge.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Dark pixels near right edge (value text area)
        assert_has_dark_pixels(
            img,
            300,
            0,
            400,
            56,
            threshold=200,
        )

    def test_urgency_today_date_black(self) -> None:
        # days=0: date text should be rendered in black (high
        # urgency).  Verify the value region has black pixels
        # (< 64), not just any dark pixels.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        # Restmuell = 2026-05-03; today = 2026-05-03 → days=0
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = dt.date(2026, 5, 3)
            img = render_to_image([w], self._config())
        assert any(
            pixel(img, x, y) < 64
            for y in range(0, 56)
            for x in range(300, 400)
        ), "days=0 date text should be black (< 64)"

    def test_urgency_tomorrow_date_gray(self) -> None:
        # days=1: date text should be gray, not black.  Verify
        # the value region has gray pixels but no black pixels.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        # Restmuell = 2026-05-03; today = 2026-05-02 → days=1
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Should have gray pixels (date label "tomorrow")
        assert_has_gray_pixels(img, 300, 0, 400, 56)
        # Should NOT have black pixels — date is gray for days=1
        assert not any(
            pixel(img, x, y) < 64
            for y in range(0, 56)
            for x in range(300, 400)
        ), "days=1 date text should be gray, not black"

    def test_past_date_skipped(self) -> None:
        # Entry with date in the past is not rendered.
        states = {
            "sensor.waste_collection": {
                "state": "past",
                "attributes": {
                    "friendly_name": "Waste",
                    "Restmuell": "2026-05-01",
                },
            },
        }
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config(states=states))
        assert_all_white(img, 0, 0, 400, 300)

    def test_beyond_3_days_skipped(self) -> None:
        # Entry with days > 3 is not rendered.
        states = {
            "sensor.waste_collection": {
                "state": "far",
                "attributes": {
                    "friendly_name": "Waste",
                    "Restmuell": "2026-05-06",
                },
            },
        }
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        # 2026-05-06 is 4 days from 2026-05-02 → filtered
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config(states=states))
        assert_all_white(img, 0, 0, 400, 300)

    def test_integer_attribute_value(self) -> None:
        # Integer strings in attributes parse correctly.
        states = {
            "sensor.waste_collection": {
                "state": "ok",
                "attributes": {
                    "friendly_name": "Waste",
                    "Restmuell": "3",
                },
            },
        }
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config(states=states))
        assert_has_dark_pixels(
            img,
            0,
            0,
            400,
            56,
            threshold=200,
        )

    # ── Layout tests ──────────────────────────────────

    def test_card_layout_shows_most_urgent(self) -> None:
        # Card layout renders only the most urgent entry
        # (lowest days) and uses the full height.
        h = 168
        w = self._widget(layout="card", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Content should exist (most urgent = Restmuell,
        # days=1)
        assert_has_dark_pixels(
            img,
            0,
            0,
            400,
            h,
            threshold=200,
        )

    def test_card_layout_uses_full_height(self) -> None:
        # Card layout uses full h as row height, so the icon
        # circle is much larger than in list layout with 3
        # entries.
        h = 168
        m_card = _compute_metrics(h)
        m_list = _compute_metrics(h // 3)
        # Card mode icon diameter should be larger
        assert m_card.icon_dia > m_list.icon_dia
        w = self._widget(layout="card", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        # Icon circle area should have content spanning a
        # large vertical range
        icon_bb = content_bbox(
            img,
            m_card.padding,
            0,
            m_card.padding + m_card.icon_dia,
            h,
        )
        assert icon_bb is not None
        icon_h = icon_bb[3] - icon_bb[1]
        # Icon should span at least 40% of widget height
        assert icon_h > h * 0.4


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
        img = render_to_image(
            widgets,
            {"width": 400, "height": 200, "states": MOCK_WEATHER_STATE},
        )
        assert_has_dark_pixels(img, PADDING + 22, 10, PADDING + 100, 40)
        # Detail chips at detail_y=35 (wrong /22 divisor shifts them to y=46)
        assert_has_dark_pixels(img, PADDING, 35, PADDING + 200, 46)

    def test_device_battery_custom_font_size(self) -> None:
        # font_size=20 → s=20/24≈0.83; body 25×12
        # Text starts further right than at default font_size.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 20,
                "font_size": 20,
            }
        ]
        img = render_to_image(
            widgets,
            {"width": 400, "height": 100, "device_battery_level": 75},
        )
        assert_has_dark_pixels(img, PADDING + 32, 10, PADDING + 90, 40)


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

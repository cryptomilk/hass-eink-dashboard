from __future__ import annotations

import dataclasses
import datetime as dt
import re
from typing import ClassVar
from unittest.mock import patch

import pytest

from custom_components.eink_dashboard.const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    COLOR_WHITE,
    DEFAULT_ROW_H,
    PADDING,
    NumberFormat,
)
from custom_components.eink_dashboard.render import (
    DEFAULT_METRICS,
    WidgetMetrics,
    _compute_metrics,
    _format_relative_date,
    _load_font,
    _parse_days_until,
    color_to_hex,
    format_number,
    render_dashboard,
    resolve_number_format,
)
from custom_components.eink_dashboard.svg_render import (
    _auto_row_height,
    _card_insets,
    _metrics_context,
    _title_layout,
    render_widget_svg,
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


def _icon_ring_region(
    row_h: int,
    m: WidgetMetrics,
    *,
    stroke_inset: int = 0,
) -> tuple[int, int, int, int]:
    """Return the top-arc bounding box of the icon circle.

    The returned region sits above the icon glyph area, between the
    top of the circle and the top of the inner icon bounding box.
    Used in icon-style tests to check for gray fill (filled) or white
    fill (outlined / none).

    Args:
        row_h: Height of the row that contains the icon.
        m: WidgetMetrics computed for that row height.
        stroke_inset: Additional inward offset on the top edge to
            account for thickened strokes (e.g. ``m.border * 3 // 2``
            on 2-level displays).  Defaults to 0.

    Returns:
        ``(x1, y1, x2, y2)`` bounding box of the ring region.
    """
    cy = row_h // 2
    r = m.icon_dia // 2
    cx = m.padding + r
    ring_y1 = cy - r + stroke_inset + 3
    ring_y2 = cy - m.icon_inner // 2 - 1
    ring_x1 = cx - r // 2 + 3
    ring_x2 = cx + r // 2 - 3
    return ring_x1, ring_y1, ring_x2, ring_y2


def _right_icon_ring_region(
    w: int,
    h: int,
    card_style: str = "none",
    grayscale_levels: int = 16,
) -> tuple[int, int, int, int, int, int]:
    """Return the icon ring region for right-aligned icon style tests.

    Used by widgets where the icon sits on the right side of a header
    row — Entity and Sensor.  The header height is computed as 40% of
    the total widget height ``h``.

    Returns ``(icon_cx, icon_cy, ring_x1, ring_y1, ring_x2, ring_y2)``
    — the centre of the icon circle and the bounding box of the top arc
    above the icon glyph area.

    Args:
        w: Canvas width in pixels.
        h: Total widget height in pixels; header_h (40%) is computed
            internally.
        card_style: Card decoration style string.
        grayscale_levels: Display grayscale depth.

    Returns:
        Six-tuple (icon_cx, icon_cy, ring_x1, ring_y1, ring_x2,
        ring_y2).
    """
    header_h = round(h * 0.40)
    m = _compute_metrics(header_h)
    _, r_inset, _ = _card_insets(m, card_style, grayscale_levels)
    rpad = m.padding if r_inset == 0 else 0
    icon_r = m.icon_dia // 2
    icon_cx = w - r_inset - rpad - icon_r
    icon_cy = header_h // 2
    # Mirror the context builder's icon_stroke_w so the ring region
    # starts past the inner edge of a widened stroke on 2-level.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    ring_y1 = icon_cy - icon_r + icon_stroke_w // 2 + 3
    ring_y2 = icon_cy - m.icon_inner // 2 - 1
    ring_x1 = icon_cx - icon_r // 2 + 3
    ring_x2 = icon_cx + icon_r // 2 - 3
    return icon_cx, icon_cy, ring_x1, ring_y1, ring_x2, ring_y2


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


class TestColorToHex:
    def test_black(self) -> None:
        # 0 is COLOR_BLACK — must convert to #000000.
        assert color_to_hex(0) == "#000000"

    def test_white(self) -> None:
        # 255 is COLOR_WHITE — must convert to #ffffff.
        assert color_to_hex(255) == "#ffffff"

    def test_gray(self) -> None:
        # 120 is COLOR_GRAY — must convert to #787878.
        assert color_to_hex(120) == "#787878"

    def test_light_gray(self) -> None:
        # 180 is COLOR_LIGHT_GRAY — must convert to #b4b4b4.
        assert color_to_hex(180) == "#b4b4b4"


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


class TestVisibilityConditions:
    # Verify that widget visibility conditions are evaluated during
    # render_dashboard() and that hidden widgets leave the canvas
    # untouched.

    _TEXT: ClassVar[dict[str, object]] = {
        "type": "text",
        "x": 10,
        "y": 10,
        "w": 180,
        "h": 30,
        "text": "hello",
        "font_size": 20,
    }

    def _config(self, states: dict | None = None) -> dict:
        """Build a minimal render config with optional entity states."""
        return {
            "width": 200,
            "height": 100,
            "states": states or {},
        }

    def test_widget_without_visibility_always_renders(self) -> None:
        # No visibility field — widget must appear regardless.
        img = render_to_image([self._TEXT], self._config())
        assert_has_dark_pixels(img, 10, 10, 190, 45)

    def test_widget_with_empty_visibility_always_renders(self) -> None:
        # An empty conditions list is equivalent to no visibility field.
        widget = {**self._TEXT, "visibility": []}
        img = render_to_image([widget], self._config())
        assert_has_dark_pixels(img, 10, 10, 190, 45)

    def test_widget_with_met_state_condition_renders(self) -> None:
        # When the state condition is satisfied the widget is rendered.
        widget = {
            **self._TEXT,
            "visibility": [
                {
                    "condition": "state",
                    "entity": "input_boolean.show",
                    "state": "on",
                }
            ],
        }
        states = {"input_boolean.show": {"state": "on", "attributes": {}}}
        img = render_to_image([widget], self._config(states))
        assert_has_dark_pixels(img, 10, 10, 190, 45)

    def test_widget_with_unmet_state_condition_is_skipped(self) -> None:
        # When the state condition is not satisfied the widget region
        # remains white (canvas is untouched).
        widget = {
            **self._TEXT,
            "visibility": [
                {
                    "condition": "state",
                    "entity": "input_boolean.show",
                    "state": "on",
                }
            ],
        }
        states = {"input_boolean.show": {"state": "off", "attributes": {}}}
        img = render_to_image([widget], self._config(states))
        assert_all_white(img, 10, 10, 190, 45)

    def test_two_widgets_one_hidden_renders_correctly(self) -> None:
        # First widget has an unmet condition (hidden); second widget
        # has no condition and must render normally.
        hidden = {
            **self._TEXT,
            "y": 10,
            "visibility": [
                {
                    "condition": "state",
                    "entity": "s.x",
                    "state": "on",
                }
            ],
        }
        visible = {**self._TEXT, "y": 60}
        states = {"s.x": {"state": "off", "attributes": {}}}
        img = render_to_image([hidden, visible], self._config(states))
        assert_all_white(img, 10, 10, 190, 44)
        assert_has_dark_pixels(img, 10, 60, 190, 95)


class TestRenderText:
    # Verify rendering of the text widget (SVG pipeline).
    _DEFAULTS: ClassVar[dict[str, object]] = {
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
    _CONFIG: ClassVar[dict[str, object]] = {"width": 300, "height": 200}

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
    _DEFAULTS: ClassVar[dict[str, object]] = {
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

    def test_sensor_rows_icon_from_entity_attr(self) -> None:
        # Entity without device_class but with an icon attribute
        # renders that icon instead of the letter fallback.  The
        # icon area should produce different output than the plain
        # letter fallback and contain dark pixels from an MDI glyph.
        m = _compute_metrics(56)
        states_with_icon = {
            **self._config()["states"],
            "sensor.no_device_class": {
                "state": "42",
                "attributes": {
                    "friendly_name": "Plain Sensor",
                    "icon": "mdi:thermometer",
                },
            },
        }
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
        img_with_icon = render_to_image(
            widgets,
            self._config(states=states_with_icon),
        )
        img_no_icon = render_to_image(widgets, self._config())
        # Adding an icon attribute must change the rendered output.
        assert img_with_icon.tobytes() != img_no_icon.tobytes(), (
            "icon attribute should change rendered icon from letter"
        )
        assert_has_dark_pixels(
            img_with_icon,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )

    # ── Auto-sizing tests ─────────────────────────────

    def test_sensor_rows_auto_height_single_entity(self) -> None:
        # Without explicit h, widget height equals DEFAULT_ROW_H.
        w = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": ["sensor.living_room_temperature"],
        }
        svg = render_widget_svg(w, self._config())
        # Parse height from the SVG viewport attribute.
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == DEFAULT_ROW_H

    def test_sensor_rows_auto_height_two_entities(self) -> None:
        # Without explicit h, widget height equals 2 * DEFAULT_ROW_H.
        w = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": [
                "sensor.living_room_temperature",
                "sensor.living_room_temperature",
            ],
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 2 * DEFAULT_ROW_H

    def test_sensor_rows_explicit_h_preserved(self) -> None:
        # An explicit h overrides auto-sizing.
        explicit_h = 200
        w = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": explicit_h,
            "entities": ["sensor.living_room_temperature"],
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == explicit_h

    def test_sensor_rows_border_single_padding(self) -> None:
        # With card_style="border", card_container yields x_off=padding
        # so card_row must not add its own padding again.  The icon
        # circle left arc should appear in the strip m.padding..2*m.padding;
        # double-padding would push the circle entirely past 2*m.padding.
        metrics = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "border",
                "entities": ["sensor.living_room_temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            metrics.padding,
            0,
            2 * metrics.padding,
            DEFAULT_ROW_H,
            threshold=200,
        )

    def test_sensor_rows_left_bar_single_padding(self) -> None:
        # With card_style="left_bar", card_container yields
        # x_off = bar_w + m.padding.  The icon circle left arc should
        # appear in the strip (bar_w+m.padding)..(bar_w+2*m.padding);
        # double-padding would push it entirely past bar_w+2*m.padding.
        metrics = _compute_metrics(DEFAULT_ROW_H)
        # For grayscale_levels=16 (default), bar_w == m.left_bar.
        bar_w = metrics.left_bar
        widgets = [
            {
                "type": "sensor_rows",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "left_bar",
                "entities": ["sensor.living_room_temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            bar_w + metrics.padding,
            0,
            bar_w + 2 * metrics.padding,
            DEFAULT_ROW_H,
            threshold=200,
        )


class TestRenderDeviceBattery:
    # Verify rendering of device battery widgets in both icon and chip
    # layouts.  Icon layout renders a compact battery outline with fill
    # bar sized proportionally from h (default h=40 → 30×14 body).
    # Chip layout uses w/h-based sizing with a pill-shaped container.
    _DEFAULTS: ClassVar[dict[str, object]] = {
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
    _DEFAULTS: ClassVar[dict[str, object]] = {
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
        pad = h * 18 // 100
        icon_dia = h * 64 // 100
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
        pad = h * 18 // 100
        icon_dia = h * 64 // 100
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

    _ENTRIES: ClassVar[list[dict[str, str]]] = [
        {"attribute": "Restmuell", "label": "Restmuell"},
        {"attribute": "Biotonne", "label": "Bio"},
        {"attribute": "Papier", "label": "Papier"},
    ]

    _DEFAULTS: ClassVar[dict[str, object]] = {
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

    def test_waste_schedule_border_single_padding(self) -> None:
        # With card_style="border", card_container yields x_off=padding
        # so card_row must not add its own padding again.  The icon
        # circle left arc should appear in the strip m.padding..2*m.padding;
        # double-padding would push it entirely past 2*m.padding.
        entries = [{"attribute": "Restmuell", "label": "Restmuell"}]
        w = self._widget(entries=entries, h=DEFAULT_ROW_H, card_style="border")
        metrics = _compute_metrics(DEFAULT_ROW_H)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_has_dark_pixels(
            img,
            metrics.padding,
            0,
            2 * metrics.padding,
            DEFAULT_ROW_H,
            threshold=200,
        )

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

    def test_show_all_renders_far_entry(self) -> None:
        # With show_all=True, entries beyond 3 days are rendered.
        states = {
            "sensor.waste_collection": {
                "state": "far",
                "attributes": {
                    "friendly_name": "Waste",
                    "Restmuell": "2026-05-09",
                },
            },
        }
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        # 2026-05-09 is 7 days from 2026-05-02 → normally filtered
        w = self._widget(entries=entries, h=56, show_all=True)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config(states=states))
        assert_has_dark_pixels(img, 0, 0, 400, 56, threshold=200)

    def test_show_all_false_keeps_default_cutoff(self) -> None:
        # With show_all=False (or omitted), entries beyond 3 days
        # are still filtered and the widget renders blank.
        states = {
            "sensor.waste_collection": {
                "state": "far",
                "attributes": {
                    "friendly_name": "Waste",
                    "Restmuell": "2026-05-09",
                },
            },
        }
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        # 2026-05-09 is 7 days from 2026-05-02 → filtered
        w = self._widget(entries=entries, h=56, show_all=False)
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

    # ── Auto-sizing tests ─────────────────────────────

    def test_waste_schedule_auto_height_single_entry(self) -> None:
        # Without explicit h, widget height equals DEFAULT_ROW_H.
        w = {
            "type": "waste_schedule",
            "entity": "sensor.waste_collection",
            "entries": [{"attribute": "Restmuell", "label": "Restmuell"}],
            "x": 0,
            "y": 0,
            "w": 400,
        }
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == DEFAULT_ROW_H

    def test_waste_schedule_auto_height_three_entries(self) -> None:
        # Without explicit h, widget height equals 3 * DEFAULT_ROW_H.
        # Relies on all three _ENTRIES attributes being present and
        # within 0–3 days in MOCK_WASTE_SCHEDULE_STATES on _TODAY.
        w = {
            "type": "waste_schedule",
            "entity": "sensor.waste_collection",
            "entries": list(self._ENTRIES),
            "x": 0,
            "y": 0,
            "w": 400,
        }
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 3 * DEFAULT_ROW_H

    def test_waste_schedule_explicit_h_preserved(self) -> None:
        # An explicit h overrides auto-sizing.
        explicit_h = 300
        w = self._widget(h=explicit_h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == explicit_h


MOCK_TILE_STATES = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
            "custom_attr": "special",
        },
    },
    "binary_sensor.front_door": {
        "state": "off",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "binary_sensor.motion": {
        "state": "on",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
    "sensor.no_class": {
        "state": "99",
        "attributes": {
            "friendly_name": "Plain",
        },
    },
}


class TestRenderTile:
    # Verify rendering of the single-entity Tile widget: icon circle
    # on the left, primary name and secondary state text on the right.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 300,
        "states": MOCK_TILE_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_tile_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.temperature",
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 400, 56, m)

    def test_tile_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge;
        # the right edge should be white.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.temperature",
                "card_style": "left_bar",
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
        assert_all_white(img, 395, 0, 400, 1)

    def test_tile_card_none(self) -> None:
        # No-decoration style has white edges — only content
        # (icon + text) draws pixels inside the card area.
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.temperature",
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)

    def test_tile_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none" (no card decoration drawn).
        base = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entity": "sensor.temperature",
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── Icon style tests ──────────────────────────────

    def test_tile_icon_circle_gray_fill_active(self) -> None:
        # An active entity (state "on") without explicit icon_style
        # draws a filled gray circle.  Check the top ring area above
        # the icon glyph for gray background pixels.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        # Top ring: inside circle boundary, above icon glyph.
        ring_y1 = cy - r + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        assert_has_gray_pixels(
            img,
            ring_x1,
            ring_y1,
            ring_x2,
            ring_y2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_tile_icon_circle_outlined_inactive(self) -> None:
        # An inactive entity (state "off") without explicit icon_style
        # draws an outlined circle: background inside is white (not
        # gray).  Check the top ring area above the icon glyph where
        # only the circle background color is visible.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "binary_sensor.front_door",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        # Top ring region: inside the circle boundary, above the
        # icon glyph (which starts at cy - icon_inner//2).  The
        # circle fill is white here for outlined, gray for filled.
        ring_y1 = cy - r + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        # Outlined circle has white fill — no gray in top ring.
        found_gray = False
        for y in range(ring_y1, ring_y2):
            for x in range(ring_x1, ring_x2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "outlined circle should have white fill (no gray) "
            "in the top ring above the icon glyph"
        )

    def test_tile_icon_style_filled_explicit(self) -> None:
        # icon_style="filled" forces a gray circle even for an inactive
        # entity (state "off").  The top ring above the icon glyph
        # contains gray (circle background).
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "binary_sensor.front_door",
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        ring_y1 = cy - r + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        assert_has_gray_pixels(
            img,
            ring_x1,
            ring_y1,
            ring_x2,
            ring_y2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_tile_icon_style_outlined_explicit(self) -> None:
        # icon_style="outlined" forces an outlined circle even for an
        # active entity (state "on").  The top ring above the icon
        # glyph has white fill (no gray) for outlined.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "binary_sensor.motion",
                "icon_style": "outlined",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        ring_y1 = cy - r + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        found_gray = False
        for y in range(ring_y1, ring_y2):
            for x in range(ring_x1, ring_x2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "explicitly outlined circle should have white fill"
        )

    def test_tile_icon_style_none_no_circle(self) -> None:
        # icon_style="none" suppresses the circle background entirely.
        # The top ring area above the icon glyph should be white (no
        # gray circle fill).
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "binary_sensor.motion",
                "icon_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        # Top ring: inside circle boundary, above icon glyph.
        ring_y1 = cy - r + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        found_gray = False
        for y in range(ring_y1, ring_y2):
            for x in range(ring_x1, ring_x2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "icon_style='none' should not draw a gray circle"
        )

    def test_tile_2level_always_outlined(self) -> None:
        # On a 2-level display (grayscale_levels=2) the auto-switch
        # forces "outlined" even for an active entity (state "on"),
        # so the top ring above the icon glyph has no gray fill.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config(grayscale_levels=2))
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        # Mirror the context builder's icon_stroke_w so the ring
        # region starts past the stroke inner edge on 2-level.
        icon_stroke_w = m.border * 3
        ring_y1 = cy - r + icon_stroke_w // 2 + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        found_gray = False
        for y in range(ring_y1, ring_y2):
            for x in range(ring_x1, ring_x2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "2-level display must force outlined (no gray fill)"
            " even for active entity"
        )

    # ── Content tests ─────────────────────────────────

    def test_tile_draws_content(self) -> None:
        # Both icon area and text area contain dark pixels.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )
        text_left = m.padding + m.icon_dia + m.inner_gap
        assert_has_dark_pixels(img, text_left, 0, 380, 56)

    def test_tile_shows_state_text(self) -> None:
        # Secondary text (state + unit) renders below the primary name
        # when hide_state is not set.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        text_left = m.padding + m.icon_dia + m.inner_gap
        # Lower half of text area should have gray (secondary) text.
        assert_has_gray_pixels(
            img,
            text_left,
            40,
            300,
            75,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_tile_hide_state(self) -> None:
        # hide_state=True suppresses secondary text; only primary name
        # is rendered in the text area.
        widgets_with = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "sensor.temperature",
            }
        ]
        widgets_hidden = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entity": "sensor.temperature",
                "hide_state": True,
            }
        ]
        # Both should draw primary text but hidden should differ
        # from the default (secondary text affects layout).
        with_state = render_dashboard(widgets_with, self._config())
        hidden = render_dashboard(widgets_hidden, self._config())
        assert with_state != hidden, (
            "hide_state=True should change rendered output"
        )

    def test_tile_name_override(self) -> None:
        # name= overrides the entity friendly_name in the widget output.
        # Two renders with different names should differ.
        base = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        named_render = render_dashboard(
            [{**base, "name": "Custom Name"}], self._config()
        )
        assert default_render != named_render, (
            "name= override should change rendered output"
        )

    def test_tile_state_content_attribute(self) -> None:
        # state_content="custom_attr" shows the attribute value instead
        # of the default state string.  Rendering should differ from
        # the default (state + unit).
        base = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 80,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        attr_render = render_dashboard(
            [{**base, "state_content": "custom_attr"}], self._config()
        )
        assert default_render != attr_render, (
            "state_content= should change rendered output"
        )

    def test_tile_icon_override(self) -> None:
        # icon= overrides the MDI icon resolved from device_class.
        # A custom icon may differ from the device_class default.
        base = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entity": "sensor.temperature",
        }
        # mdi:star differs from the temperature device_class icon.
        override_render = render_dashboard(
            [{**base, "icon": "mdi:star"}], self._config()
        )
        default_render = render_dashboard([base], self._config())
        assert override_render != default_render, (
            "icon= override should change rendered output"
        )

    def test_tile_no_device_class_letter_fallback(self) -> None:
        # An entity without device_class renders the letter fallback
        # inside the icon circle area.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.no_class",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Icon circle area should contain content (circle + letter).
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )

    def test_tile_icon_from_entity_attr(self) -> None:
        # Entity with an icon attribute but no device_class shows
        # that icon instead of the letter fallback.  Compare output
        # with and without the icon attribute, and confirm the icon
        # area contains dark pixels consistent with an MDI glyph.
        m = _compute_metrics(56)
        base_states = {
            **MOCK_TILE_STATES,
            "sensor.no_class": {
                "state": "99",
                "attributes": {
                    "friendly_name": "Plain",
                    "icon": "mdi:thermometer",
                },
            },
        }
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.no_class",
            }
        ]
        img_with_icon = render_to_image(
            widgets, self._config(states=base_states)
        )
        img_no_icon = render_to_image(widgets, self._config())
        assert img_with_icon.tobytes() != img_no_icon.tobytes(), (
            "icon attribute should change rendered icon from letter"
        )
        assert_has_dark_pixels(
            img_with_icon,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )

    def test_tile_hanger_icon_via_hass_frontend(self) -> None:
        # mdi:hanger is not in the device_class tables; it must be
        # resolved via hass_frontend JSON chunks.  When the entity
        # carries icon="mdi:hanger", the icon area should differ from
        # the plain letter fallback and contain an MDI glyph.
        m = _compute_metrics(56)
        states_with_hanger = {
            **MOCK_TILE_STATES,
            "sensor.no_class": {
                "state": "99",
                "attributes": {
                    "friendly_name": "Laundry",
                    "icon": "mdi:hanger",
                },
            },
        }
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.no_class",
            }
        ]
        img_with_hanger = render_to_image(
            widgets, self._config(states=states_with_hanger)
        )
        img_no_icon = render_to_image(widgets, self._config())
        assert img_with_hanger.tobytes() != img_no_icon.tobytes(), (
            "hanger icon should resolve via hass_frontend, "
            "not fall back to letter"
        )
        assert_has_dark_pixels(
            img_with_hanger,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )

    # ── Data edge cases ───────────────────────────────

    def test_tile_missing_entity_white_canvas(self) -> None:
        # A missing entity produces a white canvas with no crash.
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.nonexistent",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, 300)

    def test_tile_no_entity_field_white_canvas(self) -> None:
        # Omitting entity entirely produces a white canvas.
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, 300)

    # ── Alignment tests ───────────────────────────────

    def test_tile_icon_centered_with_text(self) -> None:
        # Icon circle is vertically centered with the text block.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entity": "sensor.temperature",
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        icon_left = m.padding
        icon_right = icon_left + m.icon_dia
        text_left = icon_right + m.inner_gap
        assert_vertically_centered(
            img,
            icon_region=(icon_left, 0, icon_right, 56),
            text_region=(text_left, 0, 380, 56),
            tolerance=3.0,
        )

    # ── Scaling tests ─────────────────────────────────

    def test_tile_scales_with_h(self) -> None:
        # Doubling h roughly doubles the icon circle height
        # (proportional scaling).
        m_small = _compute_metrics(56)
        m_large = _compute_metrics(112)
        widget_small = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entity": "sensor.temperature",
        }
        widget_large = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
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

    # ── Auto-sizing tests ─────────────────────────────

    def test_tile_auto_height(self) -> None:
        # Without explicit h, the widget height equals DEFAULT_ROW_H.
        w = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == DEFAULT_ROW_H

    def test_tile_explicit_h_preserved(self) -> None:
        # An explicit h overrides auto-sizing.
        w = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 200,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200

    # ── Padding tests ─────────────────────────────────

    def test_tile_border_single_padding(self) -> None:
        # With card_style="border", card_container provides x_off so
        # card_row must not add its own padding.  The icon circle left
        # arc appears in the strip m.padding..2*m.padding.
        metrics = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entity": "sensor.temperature",
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            metrics.padding,
            0,
            2 * metrics.padding,
            DEFAULT_ROW_H,
            threshold=200,
        )

    def test_tile_left_bar_single_padding(self) -> None:
        # With card_style="left_bar", card_container yields
        # x_off = bar_w + m.padding.  The icon circle left arc appears
        # in the strip (bar_w+m.padding)..(bar_w+2*m.padding).
        metrics = _compute_metrics(DEFAULT_ROW_H)
        bar_w = metrics.left_bar
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entity": "sensor.temperature",
                "card_style": "left_bar",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            bar_w + metrics.padding,
            0,
            bar_w + 2 * metrics.padding,
            DEFAULT_ROW_H,
            threshold=200,
        )


MOCK_HEADING_STATES = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Temperature",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    },
    "sensor.humidity": {
        "state": "58",
        "attributes": {
            "friendly_name": "Humidity",
            "device_class": "humidity",
            "unit_of_measurement": "%",
        },
    },
    "binary_sensor.motion": {
        "state": "on",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
}


class TestRenderHeading:
    # Verify rendering of the Heading widget: optional icon, heading
    # text with title/subtitle styling, and optional entity badges.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 300,
        "states": MOCK_HEADING_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_heading_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Living Room",
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 400, 56, m)

    def test_heading_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge;
        # the right edge should be white.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Living Room",
                "card_style": "left_bar",
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
        assert_all_white(img, 395, 0, 400, 1)

    def test_heading_card_none(self) -> None:
        # No-decoration style has white corners — no border drawn.
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Living Room",
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)

    def test_heading_card_style_none_is_default(self) -> None:
        # Omitting card_style produces byte-identical output to
        # card_style="none".
        base = {
            "type": "heading",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "heading": "Living Room",
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── Content tests ─────────────────────────────────

    def test_heading_draws_text(self) -> None:
        # Heading text renders dark pixels in the text region.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Living Room",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Text starts at m.padding (no icon) and spans the widget.
        assert_has_dark_pixels(img, m.padding, 0, 380, 56)

    def test_heading_with_icon_draws_icon(self) -> None:
        # When an icon is provided, the icon area has dark pixels.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Living Room",
                "icon": "mdi:home",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Icon occupies a small area at m.padding on the left.
        assert_has_dark_pixels(
            img, m.padding, 4, m.padding + 30, 52, threshold=200
        )

    def test_heading_no_icon_text_starts_at_padding(self) -> None:
        # Without an icon the heading text starts at the padding offset;
        # the strip left of m.padding should be white.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "XXXX",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Strip left of padding is white (no decoration, no icon).
        assert_all_white(img, 0, 0, m.padding - 1, 56)
        # Text is present starting at m.padding.
        assert_has_dark_pixels(img, m.padding, 0, m.padding + 60, 56)

    # ── Heading style tests ───────────────────────────

    def test_heading_title_style_draws_dark_text(self) -> None:
        # Title style renders the heading in black (dark pixels).
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Section",
                "heading_style": "title",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, m.padding, 0, m.padding + 120, 56)

    def test_heading_subtitle_style_draws_gray_text(self) -> None:
        # Subtitle style renders the heading in gray (secondary color).
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Section",
                "heading_style": "subtitle",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Subtitle text should be gray, not solid black.
        assert_has_gray_pixels(
            img,
            m.padding,
            0,
            m.padding + 120,
            56,
            low=COLOR_GRAY - 30,
            high=COLOR_GRAY + 30,
        )

    def test_heading_subtitle_smaller_than_title(self) -> None:
        # Subtitle content bounding box is shorter than title
        # (smaller font yields smaller glyph height).
        m = _compute_metrics(56)
        text_x = m.padding
        widgets_title = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Section",
                "heading_style": "title",
            }
        ]
        widgets_subtitle = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Section",
                "heading_style": "subtitle",
            }
        ]
        img_title = render_to_image(widgets_title, self._config())
        img_subtitle = render_to_image(widgets_subtitle, self._config())
        bb_title = content_bbox(img_title, text_x, 0, 400, 56)
        bb_subtitle = content_bbox(img_subtitle, text_x, 0, 400, 56)
        assert bb_title is not None, "title should draw content"
        assert bb_subtitle is not None, "subtitle should draw content"
        title_h = bb_title[3] - bb_title[1]
        subtitle_h = bb_subtitle[3] - bb_subtitle[1]
        assert subtitle_h < title_h, (
            f"subtitle ({subtitle_h}px) should be shorter than "
            f"title ({title_h}px)"
        )

    def test_heading_title_is_default_style(self) -> None:
        # Omitting heading_style produces byte-identical output to
        # heading_style="title".
        base = {
            "type": "heading",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "heading": "Section",
        }
        with_title = render_dashboard(
            [{**base, "heading_style": "title"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_title == without

    # ── Icon style tests ──────────────────────────────

    def test_heading_icon_style_none_no_gray_circle(self) -> None:
        # icon_style="none" (default) renders no gray circle background;
        # the ring area above the icon glyph (where a filled circle
        # would appear) should be white.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "heading": "Section",
                "icon": "mdi:home",
                "icon_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        # Ring region where a filled circle would show gray fill.
        ring_y1 = cy - r + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        assert ring_y2 > ring_y1 and ring_x2 > ring_x1, (
            "ring region must be non-empty"
        )
        found_gray = any(
            COLOR_GRAY - 20 < pixel(img, rx, ry) < COLOR_GRAY + 20
            for ry in range(ring_y1, ring_y2)
            for rx in range(ring_x1, ring_x2)
        )
        assert not found_gray, (
            "icon_style=none should have no gray circle fill"
        )

    def test_heading_icon_style_filled(self) -> None:
        # icon_style="filled" renders a gray circle background.
        # The ring above the icon glyph has gray fill.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "heading": "Section",
                "icon": "mdi:home",
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        ring_y1 = cy - r + 3
        ring_y2 = cy - m.icon_inner // 2 - 1
        ring_x1 = cx - r // 2 + 3
        ring_x2 = cx + r // 2 - 3
        assert ring_y2 > ring_y1 and ring_x2 > ring_x1, (
            "ring region must be non-empty"
        )
        assert_has_gray_pixels(
            img,
            ring_x1,
            ring_y1,
            ring_x2,
            ring_y2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_heading_icon_style_outlined(self) -> None:
        # icon_style="outlined" renders a circle outline (dark border,
        # white fill); dark pixels appear at the circle boundary.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "heading": "Section",
                "icon": "mdi:home",
                "icon_style": "outlined",
            }
        ]
        img = render_to_image(widgets, self._config())
        cy = 80 // 2
        r = m.icon_dia // 2
        cx = m.padding + r
        assert_has_dark_pixels(
            img, cx - r, cy - r, cx + r, cy + r, threshold=128
        )

    def test_heading_icon_style_none_is_default(self) -> None:
        # Omitting icon_style produces byte-identical output to
        # icon_style="none".
        base = {
            "type": "heading",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "heading": "Section",
            "icon": "mdi:home",
        }
        with_none = render_dashboard(
            [{**base, "icon_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── Badge tests ───────────────────────────────────

    def test_heading_badges_change_output(self) -> None:
        # Adding an entity badge changes the rendered output.
        base = {
            "type": "heading",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "heading": "Section",
        }
        without_badges = render_dashboard([base], self._config())
        with_badges = render_dashboard(
            [{**base, "badges": ["sensor.temperature"]}],
            self._config(),
        )
        assert without_badges != with_badges, (
            "adding a badge should change rendered output"
        )

    def test_heading_no_badges_no_crash(self) -> None:
        # Empty badges list renders without error; heading text present.
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Section",
                "badges": [],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, PADDING, 0, 380, 56)

    def test_heading_badge_missing_entity_skipped(self) -> None:
        # A badge referencing a nonexistent entity is skipped silently.
        # Output must be byte-identical to rendering with no badges —
        # the missing entity leaves no trace in the image.
        base = {
            "type": "heading",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "heading": "Section",
        }
        no_badges = render_dashboard([base], self._config())
        missing = render_dashboard(
            [{**base, "badges": ["sensor.nonexistent"]}],
            self._config(),
        )
        assert no_badges == missing, (
            "missing entity should produce same output as no badges"
        )

    def test_heading_badges_on_right_side(self) -> None:
        # Badges appear in the right portion of the heading row.
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "A",
                "badges": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        # Badge text (e.g. "22.5°C") should appear in the right half.
        assert_has_dark_pixels(img, 200, 0, 400, 56)

    # ── Edge case tests ───────────────────────────────

    def test_heading_empty_heading_is_white(self) -> None:
        # Empty heading text with no icon and no badges → blank canvas.
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, 56)

    def test_heading_invalid_icon_no_crash(self) -> None:
        # An unrecognized MDI icon name does not crash; heading renders.
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Section",
                "icon": "mdi:this-icon-does-not-exist-xyz",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, PADDING, 0, 380, 56)

    # ── Scaling tests ─────────────────────────────────

    def test_heading_scales_proportionally(self) -> None:
        # Doubling the widget height approximately doubles the content
        # (heading text) height.
        widgets_small = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "heading": "Section",
            }
        ]
        widgets_large = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "heading": "Section",
            }
        ]
        img_small = render_to_image(widgets_small, self._config())
        img_large = render_to_image(
            widgets_large, make_config(self._DEFAULTS, height=300)
        )
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(PADDING, 0, 380, 56),
            region_large=(PADDING, 0, 380, 112),
            expected_ratio=2.0,
            tolerance=0.4,
        )

    # ── Auto-sizing tests ─────────────────────────────

    def test_heading_auto_height(self) -> None:
        # Without explicit h, the widget height equals DEFAULT_ROW_H.
        w = {
            "type": "heading",
            "x": 0,
            "y": 0,
            "w": 400,
            "heading": "Section",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == DEFAULT_ROW_H

    def test_heading_explicit_h_preserved(self) -> None:
        # An explicit h overrides auto-sizing.
        w = {
            "type": "heading",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 200,
            "heading": "Section",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200


MOCK_ENTITY_STATES = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
            # Extra attribute for attribute= display test.
            "humidity": 58,
        },
    },
    "binary_sensor.motion": {
        "state": "on",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
    "binary_sensor.front_door": {
        "state": "off",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "sensor.no_class": {
        "state": "99",
        "attributes": {
            "friendly_name": "Plain",
        },
    },
}


class TestRenderEntity:
    # Verify rendering of the Entity widget: name and icon in a header
    # row (name left, icon right), with the entity state value displayed
    # in a large font in the lower info section.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 300,
        "states": MOCK_ENTITY_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_entity_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        h = 112
        # Metrics are derived from the header section height (40% of h).
        m = _compute_metrics(round(h * 0.40))
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 400, h, m)

    def test_entity_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge;
        # the right edge should be white.
        h = 112
        m = _compute_metrics(round(h * 0.40))
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "card_style": "left_bar",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            h - 2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        assert_all_white(img, 395, 0, 400, 1)

    def test_entity_card_none(self) -> None:
        # No-decoration style has white edges — only content
        # (name, icon, value) draws pixels inside the card.
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entity": "sensor.temperature",
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)

    def test_entity_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none" (no card decoration drawn).
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── Icon style tests ──────────────────────────────
    # Use h=224 so the header section (40% = 90px) gives a large
    # enough icon circle to measure the ring region reliably.

    def _icon_ring(
        self, h: int, card_style: str = "none", grayscale_levels: int = 16
    ) -> tuple[int, int, int, int, int, int]:
        """Delegate to module-level _right_icon_ring_region."""
        return _right_icon_ring_region(400, h, card_style, grayscale_levels)

    def test_entity_icon_circle_gray_fill_active(self) -> None:
        # An active entity (state "on") without explicit icon_style
        # draws a filled gray circle in the right portion of the header.
        # Check the ring area above the icon glyph for gray fill pixels.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_entity_icon_circle_outlined_inactive(self) -> None:
        # An inactive entity (state "off") without explicit icon_style
        # draws an outlined circle: interior is white, not gray.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.front_door",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "outlined circle should have white fill (no gray) "
            "in the top ring above the icon glyph"
        )

    def test_entity_icon_style_filled_explicit(self) -> None:
        # icon_style="filled" forces a gray circle even for an inactive
        # entity (state "off").
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.front_door",
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_entity_icon_style_outlined_explicit(self) -> None:
        # icon_style="outlined" forces an outlined circle even for an
        # active entity (state "on").  No gray in the ring.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
                "icon_style": "outlined",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "explicitly outlined circle should have white fill"
        )

    def test_entity_icon_style_none_no_circle(self) -> None:
        # icon_style="none" suppresses the circle entirely; no gray
        # fill in the ring area above the icon glyph.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
                "icon_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "icon_style='none' should not draw a gray circle"
        )

    def test_entity_2level_always_outlined(self) -> None:
        # On a 2-level display (grayscale_levels=2), the auto-switch
        # forces "outlined" even for an active entity (state "on").
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h, grayscale_levels=2)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config(grayscale_levels=2))
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "2-level display must force outlined (no gray fill) "
            "even for active entity"
        )

    # ── Content tests ─────────────────────────────────

    def test_entity_draws_name_and_value(self) -> None:
        # The header row (top ~40%) has name text on the left, and the
        # info section (bottom ~60%) has the large state value.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Name area: left portion of the header row.
        assert_has_dark_pixels(img, m.padding, 0, 200, header_h)
        # Value area: info section below the header row.
        assert_has_dark_pixels(img, m.padding, header_h, 350, h)

    def test_entity_name_override(self) -> None:
        # name= overrides the entity friendly_name; renders differ.
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        named_render = render_dashboard(
            [{**base, "name": "Custom Name"}], self._config()
        )
        assert default_render != named_render, (
            "name= override should change rendered output"
        )

    def test_entity_icon_override(self) -> None:
        # icon= overrides the MDI icon resolved from device_class.
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        override_render = render_dashboard(
            [{**base, "icon": "mdi:star"}], self._config()
        )
        default_render = render_dashboard([base], self._config())
        assert override_render != default_render, (
            "icon= override should change rendered output"
        )

    def test_entity_shows_unit(self) -> None:
        # Entities with unit_of_measurement show the unit alongside the
        # value; renders with and without unit differ.
        base: dict[str, object] = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        states_no_unit = {
            **MOCK_ENTITY_STATES,
            "sensor.temperature": {
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    # No unit_of_measurement.
                },
            },
        }
        with_unit = render_dashboard([base], self._config())
        without_unit = render_dashboard(
            [base], self._config(states=states_no_unit)
        )
        assert with_unit != without_unit, (
            "unit_of_measurement should change rendered output"
        )

    def test_entity_unit_override(self) -> None:
        # unit= overrides the automatically detected unit.
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        unit_render = render_dashboard([{**base, "unit": "F"}], self._config())
        assert default_render != unit_render, (
            "unit= override should change rendered output"
        )

    def test_entity_attribute_display(self) -> None:
        # attribute= shows the specified attribute value instead of the
        # entity state; renders differ from the default.
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        attr_render = render_dashboard(
            [{**base, "attribute": "humidity"}], self._config()
        )
        assert default_render != attr_render, (
            "attribute= should change rendered output"
        )

    def test_entity_attribute_suppresses_unit(self) -> None:
        # When attribute= is set, the automatic unit_of_measurement
        # from the entity state is suppressed.  Only an explicit
        # unit= override would cause a unit to appear.
        base: dict[str, object] = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        # sensor.temperature has unit_of_measurement="°C".
        # With attribute="humidity" the unit must be suppressed.
        with_attr = render_dashboard(
            [{**base, "attribute": "humidity"}], self._config()
        )
        # Same attribute query against a state dict with no unit.
        states_no_unit = {
            **MOCK_ENTITY_STATES,
            "sensor.temperature": {
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "humidity": 58,
                },
            },
        }
        without_unit = render_dashboard(
            [{**base, "attribute": "humidity"}],
            self._config(states=states_no_unit),
        )
        assert with_attr == without_unit, (
            "attribute= should suppress automatic unit_of_measurement"
        )

    def test_entity_attribute_unknown_no_crash(self) -> None:
        # attribute= with a nonexistent attribute key renders without
        # crashing; name text still appears in the header row.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "attribute": "nonexistent_attr",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Name text still renders in the header area even when attribute
        # is unknown (value shows "unknown" text).
        assert_has_dark_pixels(img, m.padding, 0, 200, header_h)

    def test_entity_no_device_class_letter_fallback(self) -> None:
        # An entity without device_class renders a letter fallback in
        # the icon area on the right side of the header row.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        _, r_inset, _ = _card_insets(m, "none", 16)
        rpad = m.padding if r_inset == 0 else 0
        icon_r = m.icon_dia // 2
        icon_x1 = 400 - r_inset - rpad - icon_r * 2
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.no_class",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Icon area (right portion of header row) contains content.
        assert_has_dark_pixels(img, icon_x1, 0, 400, header_h, threshold=200)

    # ── Data edge cases ───────────────────────────────

    def test_entity_missing_entity_white_canvas(self) -> None:
        # A missing entity produces a white canvas without crashing.
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entity": "sensor.nonexistent",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, 300)

    def test_entity_no_entity_field_white_canvas(self) -> None:
        # Omitting entity entirely produces a white canvas.
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, 300)

    # ── Alignment tests ───────────────────────────────

    def test_entity_icon_in_header_right(self) -> None:
        # The icon appears in the right portion of the header row and
        # contains dark pixels (circle + glyph).
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        _, r_inset, _ = _card_insets(m, "none", 16)
        rpad = m.padding if r_inset == 0 else 0
        icon_r = m.icon_dia // 2
        icon_cx = 400 - r_inset - rpad - icon_r
        icon_x1 = icon_cx - icon_r
        icon_x2 = min(icon_cx + icon_r + 1, 400)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Icon area on the right side of the header row has content.
        assert_has_dark_pixels(
            img, icon_x1, 0, icon_x2, header_h, threshold=200
        )

    def test_entity_name_in_header_left(self) -> None:
        # The entity name appears in the left portion of the header row.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, m.padding, 0, 200, header_h)

    # ── Scaling tests ─────────────────────────────────

    def test_entity_scales_with_h(self) -> None:
        # Doubling h roughly doubles the bounding box of rendered content.
        h_small = 112
        h_large = 224
        widget_small = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h_small,
            "entity": "sensor.temperature",
        }
        widget_large = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h_large,
            "entity": "sensor.temperature",
        }
        img_s = render_to_image([widget_small], self._config())
        img_l = render_to_image([widget_large], self._config())
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(0, 0, 400, h_small),
            region_large=(0, 0, 400, h_large),
            expected_ratio=2.0,
        )

    # ── Auto-sizing tests ─────────────────────────────

    def test_entity_auto_height(self) -> None:
        # Without explicit h, the widget height equals 2 * DEFAULT_ROW_H
        # (entity card is inherently a 2-row-tall widget).
        w = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 2 * DEFAULT_ROW_H

    def test_entity_explicit_h_preserved(self) -> None:
        # An explicit h overrides the auto-sized default.
        w = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 200,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200


MOCK_ENTITIES_STATES = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    },
    "sensor.humidity": {
        "state": "45",
        "attributes": {
            "friendly_name": "Humidity",
            "device_class": "humidity",
            "unit_of_measurement": "%",
        },
    },
    "sensor.pressure": {
        "state": "1013",
        "attributes": {
            "friendly_name": "Pressure",
            "device_class": "pressure",
            "unit_of_measurement": "hPa",
        },
    },
    "binary_sensor.front_door": {
        "state": "off",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "binary_sensor.motion": {
        "state": "on",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
}


class TestRenderEntities:
    # Verify rendering of the Entities widget: multi-entity list card
    # with optional title, divider rows, and section rows.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 400,
        "states": MOCK_ENTITIES_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_entities_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "card_style": "border",
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 400, 56, m)

    def test_entities_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge;
        # the right edge should be white.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": ["sensor.temperature"],
                "card_style": "left_bar",
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
        assert_all_white(img, 395, 0, 400, 1)

    def test_entities_card_none(self) -> None:
        # No-decoration style has white edges — only content
        # (icon + text) draws pixels inside the card area.
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": ["sensor.temperature"],
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)

    def test_entities_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none" (no card decoration drawn).
        base = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["sensor.temperature"],
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    def test_entities_row_divider_between_entity_rows(
        self,
    ) -> None:
        # A gray divider exists at the boundary between two consecutive
        # entity rows (at y = row_h for a two-entity widget).
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entities": [
                    "sensor.temperature",
                    "sensor.humidity",
                ],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            m.padding + 20,
            56 - m.divider,
            380,
            56 + m.divider,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_entities_no_divider_single_entity(self) -> None:
        # A single entity produces no divider; the area below
        # the card should be white.
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 57, 400, 60)

    def test_entities_explicit_divider_row(self) -> None:
        # An explicit {type: "divider"} row renders a horizontal
        # line between entity rows.
        m = _compute_metrics(56)
        row_h = 56
        # Widget: entity, divider, entity — divider sits between rows.
        entities: list[object] = [
            "sensor.temperature",
            {"type": "divider"},
            "sensor.humidity",
        ]
        # Compute divider_h = round(row_h * 0.15) for y bounds.
        divider_h = round(row_h * 0.15)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "entities": entities,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Gray pixels should exist somewhere in the middle of the
        # widget where the explicit divider row sits.
        mid_y = row_h + divider_h // 2
        assert_has_gray_pixels(
            img,
            m.padding + 20,
            mid_y - m.divider,
            380,
            mid_y + m.divider + 1,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_entities_section_row_renders_text(self) -> None:
        # A {type: "section", label: "..."} row renders gray text
        # above the following entity rows.
        row_h = 56
        entities: list[object] = [
            {"type": "section", "label": "Climate"},
            "sensor.temperature",
        ]
        section_h = round(row_h * 0.6)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "entities": entities,
            }
        ]
        img = render_to_image(widgets, self._config())
        # Gray pixels (section label text) should exist in the
        # section row area (y 0 .. section_h).
        assert_has_gray_pixels(
            img,
            0,
            0,
            300,
            section_h,
            low=COLOR_GRAY - 40,
            high=COLOR_GRAY + 40,
        )

    def test_entities_empty_entities_white(self) -> None:
        # Empty entity list produces a white canvas.
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, 300)

    def test_entities_missing_entity_skipped(self) -> None:
        # Nonexistent entity is skipped; remaining entities still
        # render normally without a blank gap.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [
                    "sensor.nonexistent",
                    "sensor.temperature",
                ],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            m.padding,
            2,
            380,
            54,
            threshold=200,
        )

    # ── Alignment tests ───────────────────────────────

    def test_entities_icon_centered_with_text(self) -> None:
        # Icon circle is vertically centered with the text block.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_vertically_centered(
            img,
            icon_region=(m.padding, 0, m.padding + m.icon_dia, 56),
            text_region=(
                m.padding + m.icon_dia + m.inner_gap,
                0,
                380,
                56,
            ),
            tolerance=3.0,
        )

    # ── Scaling tests ─────────────────────────────────

    def test_entities_scales_with_h(self) -> None:
        # Doubling h for a single entity row doubles icon content
        # height proportionally.
        m_small = _compute_metrics(56)
        m_large = _compute_metrics(112)
        widget_small = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["sensor.temperature"],
        }
        widget_large = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entities": ["sensor.temperature"],
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

    def test_entities_draws_content(self) -> None:
        # Icon area and text area both contain dark pixels.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )
        text_left = m.padding + m.icon_dia + m.inner_gap
        assert_has_dark_pixels(img, text_left, 0, 380, 56)

    def test_entities_with_title(self) -> None:
        # Title is drawn above the card area as gray text.
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "title": "Sensors",
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(img, 0, 0, 200, 20)

    def test_entities_name_override(self) -> None:
        # An entity row with a name override renders the override,
        # producing different output than the friendly_name default.
        base_widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["sensor.temperature"],
        }
        override_widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": [
                {
                    "entity": "sensor.temperature",
                    "name": "Kitchen Sensor",
                }
            ],
        }
        img_base = render_to_image([base_widget], self._config())
        img_override = render_to_image([override_widget], self._config())
        assert img_base.tobytes() != img_override.tobytes(), (
            "name override should change rendered text"
        )

    def test_entities_value_right_aligned(self) -> None:
        # The state value is rendered near the right edge of the row.
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        # Right quarter of the widget (x > 300) should contain
        # dark pixels from the state value text.
        assert_has_dark_pixels(img, 300, 0, 390, 56)

    def test_entities_object_row_entity_key(self) -> None:
        # Entity row given as an object {entity, name?, icon?}
        # renders content like a string entity ID shorthand.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 56,
                "entities": [{"entity": "sensor.temperature"}],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            m.padding + m.icon_dia,
            56,
            threshold=200,
        )

    def test_entities_value_text_gray(self) -> None:
        # The right-aligned state value is rendered in gray.
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        # Right portion of the row at mid-height should have gray
        # pixels from the right-aligned state value text.
        assert_has_gray_pixels(
            img,
            300,
            20,
            395,
            60,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    # ── Icon style tests ──────────────────────────────

    def test_entities_icon_circle_gray_fill_active(self) -> None:
        # Active entity (state "on") without explicit icon_style draws
        # a filled gray circle.  The top ring above the icon glyph
        # contains gray background pixels.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": ["binary_sensor.motion"],
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(80, m)
        assert_has_gray_pixels(
            img, rx1, ry1, rx2, ry2, low=COLOR_GRAY - 20, high=COLOR_GRAY + 20
        )

    def test_entities_icon_circle_outlined_inactive(
        self,
    ) -> None:
        # Inactive entity (state "off") without explicit icon_style
        # draws an outlined circle with white fill.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": ["binary_sensor.front_door"],
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(80, m)
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "outlined circle should have white fill (no gray) "
            "in the top ring above the icon glyph"
        )

    def test_entities_icon_style_filled_explicit(self) -> None:
        # icon_style="filled" forces a gray circle even for an
        # inactive entity (state "off").
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": ["binary_sensor.front_door"],
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(80, m)
        assert_has_gray_pixels(
            img, rx1, ry1, rx2, ry2, low=COLOR_GRAY - 20, high=COLOR_GRAY + 20
        )

    def test_entities_icon_style_outlined_explicit(self) -> None:
        # icon_style="outlined" forces an outlined circle even for an
        # active entity (state "on"); top ring has white fill.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": ["binary_sensor.motion"],
                "icon_style": "outlined",
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(80, m)
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "explicitly outlined circle should have white fill"
        )

    def test_entities_icon_style_none_no_circle(self) -> None:
        # icon_style="none" suppresses the circle background;
        # top ring above icon glyph is white (no gray fill).
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": ["binary_sensor.motion"],
                "icon_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(80, m)
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "icon_style='none' should not draw a gray circle"
        )

    def test_entities_2level_always_outlined(self) -> None:
        # On a 2-level display (grayscale_levels=2) the auto-switch
        # forces outlined even for an active entity (state "on");
        # top ring has no gray fill.
        m = _compute_metrics(80)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 80,
                "entities": ["binary_sensor.motion"],
            }
        ]
        img = render_to_image(widgets, self._config(grayscale_levels=2))
        rx1, ry1, rx2, ry2 = _icon_ring_region(
            80, m, stroke_inset=m.border * 3 // 2
        )
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                v = pixel(img, x, y)
                if COLOR_GRAY - 20 < v < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "2-level display must force outlined (no gray fill)"
        )

    def test_entities_2level_divider_stroke_widened(self) -> None:
        # On a 2-level display the auto-divider stroke-width must be
        # 3× m.divider to prevent dithering into dot patterns.
        m = _compute_metrics(DEFAULT_ROW_H)
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": [
                "sensor.temperature",
                "sensor.humidity",
            ],
        }
        svg = render_widget_svg(w, self._config(grayscale_levels=2))
        expected_sw = m.divider * 3
        assert f'stroke-width="{expected_sw}"' in svg, (
            f"2-level divider stroke-width should be {expected_sw}"
            f" (3 × m.divider={m.divider})"
        )

    # ── Auto-sizing tests ─────────────────────────────

    def test_entities_auto_height_single_entity(self) -> None:
        # Without explicit h, one entity row height == DEFAULT_ROW_H.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": ["sensor.temperature"],
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == DEFAULT_ROW_H

    def test_entities_auto_height_two_entities(self) -> None:
        # Without explicit h, two entity rows height == 2 * DEFAULT_ROW_H.
        # Auto-divider lines render within row bounds and do not add to svg_h.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": [
                "sensor.temperature",
                "sensor.humidity",
            ],
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 2 * DEFAULT_ROW_H

    def test_entities_explicit_h_preserved(self) -> None:
        # An explicit h overrides auto-sizing.
        explicit_h = 200
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": explicit_h,
            "entities": ["sensor.temperature"],
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == explicit_h

    def test_entities_border_single_padding(self) -> None:
        # With card_style="border", card_container yields x_off=padding
        # so card_row must not add its own padding again.  Icon circle
        # left arc appears in the strip m.padding..2*m.padding.
        metrics = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "border",
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            metrics.padding,
            0,
            2 * metrics.padding,
            DEFAULT_ROW_H,
            threshold=200,
        )

    def test_entities_left_bar_single_padding(self) -> None:
        # With card_style="left_bar", icon circle left arc appears in
        # the strip (bar_w+m.padding)..(bar_w+2*m.padding).
        metrics = _compute_metrics(DEFAULT_ROW_H)
        bar_w = metrics.left_bar
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "card_style": "left_bar",
                "entities": ["sensor.temperature"],
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            bar_w + metrics.padding,
            0,
            bar_w + 2 * metrics.padding,
            DEFAULT_ROW_H,
            threshold=200,
        )


MOCK_SENSOR_CARD_STATES: dict[str, dict[str, object]] = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    },
    "binary_sensor.motion": {
        "state": "on",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
    "binary_sensor.front_door": {
        "state": "off",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "sensor.no_class": {
        "state": "42",
        "attributes": {
            "friendly_name": "Plain",
        },
    },
}

# History points for graph tests.  Injected directly into the states
# dict using the compressed format {"s": value, "lu": unix_timestamp}
# that _fetch_history() produces, so tests run without the recorder.
# 9 data points spanning ~22 hours (last timestamp 1747699200) so that
# no point sits exactly on the 24-hour hours_to_show boundary.
_SENSOR_CARD_HISTORY = [
    {"s": "20.0", "lu": 1747620000.0},
    {"s": "21.0", "lu": 1747623600.0},
    {"s": "22.5", "lu": 1747634400.0},
    {"s": "23.0", "lu": 1747645200.0},
    {"s": "22.5", "lu": 1747656000.0},
    {"s": "21.5", "lu": 1747666800.0},
    {"s": "20.0", "lu": 1747677600.0},
    {"s": "21.0", "lu": 1747688400.0},
    {"s": "22.5", "lu": 1747699200.0},
]

MOCK_SENSOR_WITH_HISTORY: dict[str, dict[str, object]] = {
    **MOCK_SENSOR_CARD_STATES,
    "sensor.temperature": {
        **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
        "history": _SENSOR_CARD_HISTORY,
    },
}


class TestRenderSensor:
    # Verify rendering of the Sensor widget: header row (name left,
    # icon right), large value in the info section, and an optional
    # history sparkline graph below.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 300,
        "states": MOCK_SENSOR_CARD_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def _icon_ring(
        self,
        h: int,
        card_style: str = "none",
        grayscale_levels: int = 16,
    ) -> tuple[int, int, int, int, int, int]:
        """Delegate to module-level _right_icon_ring_region."""
        return _right_icon_ring_region(400, h, card_style, grayscale_levels)

    # ── Structural tests ──────────────────────────────

    def test_sensor_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        h = 112
        # Border metrics use header_h (40% of h) — same convention as
        # the Entity widget; border/radius/left_bar scale from the
        # header row, not the full card height.
        m = _compute_metrics(round(h * 0.40))
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 400, h, m)

    def test_sensor_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge; right
        # edge should be white.
        h = 112
        m = _compute_metrics(round(h * 0.40))
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "card_style": "left_bar",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            h - 2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        assert_all_white(img, 395, 0, 400, 1)

    def test_sensor_card_none(self) -> None:
        # No-decoration style has white edges — only content draws
        # pixels inside the card.
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entity": "sensor.temperature",
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)

    def test_sensor_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none".
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── Icon style tests ──────────────────────────────
    # Use h=224 so the header section (40% = ~90px) gives an icon
    # circle large enough to reliably sample the ring region.

    def test_sensor_icon_circle_gray_fill_active(self) -> None:
        # Active entity (state "on") without explicit icon_style draws
        # a filled gray circle in the right portion of the header.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_sensor_icon_circle_outlined_inactive(self) -> None:
        # Inactive entity (state "off") without explicit icon_style
        # draws an outlined circle: interior is white, not gray.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.front_door",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "outlined circle should have white fill (no gray) "
            "in the top ring above the icon glyph"
        )

    def test_sensor_icon_style_filled_explicit(self) -> None:
        # icon_style="filled" forces gray circle even for inactive
        # entity (state "off").
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.front_door",
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_sensor_icon_style_outlined_explicit(self) -> None:
        # icon_style="outlined" forces outlined circle even for active
        # entity (state "on").  No gray in the ring.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
                "icon_style": "outlined",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "explicitly outlined circle should have white fill"
        )

    def test_sensor_icon_style_none_no_circle(self) -> None:
        # icon_style="none" suppresses the circle entirely; no gray
        # fill in the ring area above the icon glyph.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
                "icon_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "icon_style='none' should not draw a gray circle"
        )

    def test_sensor_2level_always_outlined(self) -> None:
        # On 2-level displays (grayscale_levels=2), active entity is
        # forced to outlined style regardless of state.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h, grayscale_levels=2)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config(grayscale_levels=2))
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "2-level display must force outlined (no gray fill) "
            "even for active entity"
        )

    # ── Content tests ─────────────────────────────────

    def test_sensor_draws_name_and_value(self) -> None:
        # Header row (top ~40%) has name on the left; info section
        # (bottom ~60%) has the large state value.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, m.padding, 0, 200, header_h)
        assert_has_dark_pixels(img, m.padding, header_h, 350, h)

    def test_sensor_name_override(self) -> None:
        # name= overrides the entity friendly_name; renders differ.
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        named_render = render_dashboard(
            [{**base, "name": "Override"}], self._config()
        )
        assert default_render != named_render, (
            "name= override should change rendered output"
        )

    def test_sensor_icon_override(self) -> None:
        # icon= overrides the MDI icon resolved from device_class.
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        override_render = render_dashboard(
            [{**base, "icon": "mdi:star"}], self._config()
        )
        assert default_render != override_render, (
            "icon= override should change rendered output"
        )

    def test_sensor_shows_unit(self) -> None:
        # unit_of_measurement appears alongside the value; renders
        # with and without unit differ.
        base: dict[str, object] = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        states_no_unit = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    # No unit_of_measurement.
                },
            },
        }
        with_unit = render_dashboard([base], self._config())
        without_unit = render_dashboard(
            [base], self._config(states=states_no_unit)
        )
        assert with_unit != without_unit, (
            "unit_of_measurement should change rendered output"
        )

    def test_sensor_unit_override(self) -> None:
        # unit= overrides the automatically detected unit.
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        unit_render = render_dashboard([{**base, "unit": "F"}], self._config())
        assert default_render != unit_render, (
            "unit= override should change rendered output"
        )

    def test_sensor_no_device_class_letter_fallback(self) -> None:
        # Entity without device_class renders a letter in the icon
        # area on the right side of the header row.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        _, r_inset, _ = _card_insets(m, "none", 16)
        rpad = m.padding if r_inset == 0 else 0
        icon_r = m.icon_dia // 2
        icon_x1 = 400 - r_inset - rpad - icon_r * 2
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.no_class",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, icon_x1, 0, 400, header_h, threshold=200)

    # ── Graph tests ───────────────────────────────────

    def test_sensor_graph_has_polyline(self) -> None:
        # With graph="line" and history data, the SVG contains a
        # <polyline> element.
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget, self._config(states=MOCK_SENSOR_WITH_HISTORY)
        )
        assert "<polyline" in svg

    def test_sensor_no_graph_no_polyline(self) -> None:
        # Without graph="line", no <polyline> appears in the SVG.
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 2 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(
            widget, self._config(states=MOCK_SENSOR_WITH_HISTORY)
        )
        assert "<polyline" not in svg

    def test_sensor_graph_draws_dark_pixels(self) -> None:
        # With graph="line" and history data, dark pixels appear in
        # the graph region (bottom DEFAULT_ROW_H of the widget).
        # Layout split: entity section = 2 * DEFAULT_ROW_H, graph
        # section = 1 * DEFAULT_ROW_H.  Matches auto-height tests:
        # no-graph → 2×, with-graph → 3× DEFAULT_ROW_H.
        entity_h = 2 * DEFAULT_ROW_H
        graph_h = DEFAULT_ROW_H
        h = entity_h + graph_h
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "graph": "line",
            }
        ]
        img = render_to_image(
            widgets, self._config(states=MOCK_SENSOR_WITH_HISTORY)
        )
        # Polyline falls within the bottom graph_h rows.
        assert_has_dark_pixels(img, 0, entity_h, 400, h)

    def test_sensor_graph_no_history_no_polyline(self) -> None:
        # graph="line" with no history in the state dict produces no
        # <polyline> (graceful degradation).
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        # _DEFAULTS states have no "history" key.
        svg = render_widget_svg(widget, self._config())
        assert "<polyline" not in svg

    def test_sensor_graph_non_numeric_filtered(self) -> None:
        # History entries with non-numeric states are filtered out;
        # the widget renders without crashing.
        history_with_bad = [
            {"s": "unavailable", "lu": 1747612800.0},
            {"s": "unknown", "lu": 1747623600.0},
            {"s": "22.5", "lu": 1747634400.0},
            {"s": "on", "lu": 1747645200.0},
            {"s": "23.0", "lu": 1747656000.0},
        ]
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": history_with_bad,
            },
        }
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(widget, self._config(states=states))
        assert "<svg" in svg
        # Two numeric entries survive filtering → polyline is rendered.
        assert "<polyline" in svg

    def test_sensor_graph_all_non_numeric_no_crash(self) -> None:
        # When every history entry is non-numeric the renderer must not
        # crash and must not produce a polyline (zero valid data points).
        all_bad = [
            {"s": "unavailable", "lu": 1747620000.0},
            {"s": "unknown", "lu": 1747630800.0},
            {"s": "unavailable", "lu": 1747641600.0},
        ]
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": all_bad,
            },
        }
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(widget, self._config(states=states))
        assert "<svg" in svg, (
            "renderer must not crash on all-non-numeric history"
        )
        assert "<polyline" not in svg, (
            "no polyline expected when all history entries are non-numeric"
        )

    def test_sensor_graph_single_point_no_crash(self) -> None:
        # A single valid history data point must not crash the renderer.
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": [{"s": "22.5", "lu": 1747634400.0}],
            },
        }
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(widget, self._config(states=states))
        assert "<svg" in svg

    def test_sensor_graph_8bit_fill(self) -> None:
        # At grayscale_levels=16 (8-bit), a light-gray filled area
        # appears below the polyline.  Checked via fill color rather
        # than a specific SVG element name (<polygon> or <path>).
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget,
            self._config(
                states=MOCK_SENSOR_WITH_HISTORY,
                grayscale_levels=16,
            ),
        )
        fill_hex = color_to_hex(COLOR_LIGHT_GRAY)
        assert fill_hex in svg

    def test_sensor_graph_2level_fill_present(self) -> None:
        # At grayscale_levels=2 the fill polygon is rendered; Floyd-Steinberg
        # dithering in the optimize pipeline converts it to a dot pattern.
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget,
            self._config(
                states=MOCK_SENSOR_WITH_HISTORY,
                grayscale_levels=2,
            ),
        )
        fill_hex = color_to_hex(COLOR_LIGHT_GRAY)
        assert fill_hex in svg

    def test_sensor_graph_2level_stroke_widened(self) -> None:
        # On a 2-level display the graph polyline stroke-width must be
        # 2× m.border to keep the line readable without being too thick.
        # With graph="line" the graph occupies the bottom DEFAULT_ROW_H,
        # so entity_h = h - DEFAULT_ROW_H, and header_h = 40% of that.
        h = 3 * DEFAULT_ROW_H
        entity_h = h - DEFAULT_ROW_H
        header_h = round(entity_h * 0.40)
        m = _compute_metrics(header_h)
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget,
            self._config(
                states=MOCK_SENSOR_WITH_HISTORY,
                grayscale_levels=2,
            ),
        )
        expected_sw = m.border * 2
        assert f'stroke-width="{expected_sw}"' in svg, (
            f"2-level graph stroke-width should be {expected_sw}"
            f" (2 × m.border={m.border})"
        )

    def test_sensor_graph_limits(self) -> None:
        # limits= alters the Y-axis range, changing the polyline
        # coordinate positions and therefore the rendered output.
        widget_base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        config = self._config(states=MOCK_SENSOR_WITH_HISTORY)
        auto_render = render_dashboard([widget_base], config)
        limited_render = render_dashboard(
            [{**widget_base, "limits": {"min": 0, "max": 100}}],
            config,
        )
        assert auto_render != limited_render

    def test_sensor_graph_detail_changes_output(self) -> None:
        # detail affects polyline point count in the SVG string, so
        # render_widget_svg is the right level here (not rasterisation).
        # detail=1 (downsampled) must produce different output than
        # detail=2 (full resolution) when history has many data points.
        many_points = [
            {
                "s": str(round(20.0 + i * 0.1, 1)),
                "lu": 1747612800.0 + i * 1800,
            }
            for i in range(48)
        ]
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": many_points,
            },
        }
        widget_base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        config = self._config(states=states)
        detail1 = render_widget_svg({**widget_base, "detail": 1}, config)
        detail2 = render_widget_svg({**widget_base, "detail": 2}, config)
        assert detail1 != detail2

    def test_sensor_graph_hours_to_show(self) -> None:
        # hours_to_show limits the time window rendered in the graph.
        # A 12-hour window omits older points, producing different
        # polyline coordinates than a 24-hour window.
        widget_base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        config = self._config(states=MOCK_SENSOR_WITH_HISTORY)
        svg_24h = render_widget_svg(
            {**widget_base, "hours_to_show": 24}, config
        )
        svg_12h = render_widget_svg(
            {**widget_base, "hours_to_show": 12}, config
        )
        assert svg_24h != svg_12h, (
            "hours_to_show=12 should produce different output than 24"
        )

    # ── Data edge cases ───────────────────────────────

    def test_sensor_missing_entity_white_canvas(self) -> None:
        # A missing entity produces a white canvas without crashing.
        h = 112
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.nonexistent",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, h)

    def test_sensor_no_entity_field_white_canvas(self) -> None:
        # Omitting entity entirely produces a white canvas.
        h = 112
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, h)

    # ── Alignment tests ───────────────────────────────

    def test_sensor_icon_in_header_right(self) -> None:
        # Icon appears in the right portion of the header row and
        # contains dark pixels (circle + glyph).
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        _, r_inset, _ = _card_insets(m, "none", 16)
        rpad = m.padding if r_inset == 0 else 0
        icon_r = m.icon_dia // 2
        icon_cx = 400 - r_inset - rpad - icon_r
        icon_x1 = icon_cx - icon_r
        icon_x2 = min(icon_cx + icon_r + 1, 400)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img, icon_x1, 0, icon_x2, header_h, threshold=200
        )

    def test_sensor_name_in_header_left(self) -> None:
        # Entity name appears in the left portion of the header row.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, m.padding, 0, 200, header_h)

    # ── Scaling tests ─────────────────────────────────

    def test_sensor_scales_with_h(self) -> None:
        # Doubling h roughly doubles the bounding box height of
        # rendered content.
        h_small = 112
        h_large = 224
        widget_small = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h_small,
            "entity": "sensor.temperature",
        }
        widget_large = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h_large,
            "entity": "sensor.temperature",
        }
        img_s = render_to_image([widget_small], self._config())
        img_l = render_to_image([widget_large], self._config())
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(0, 0, 400, h_small),
            region_large=(0, 0, 400, h_large),
            expected_ratio=2.0,
        )

    # ── Auto-sizing tests ─────────────────────────────

    def test_sensor_auto_height_no_graph(self) -> None:
        # Without graph, default height is 2 * DEFAULT_ROW_H.
        w = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 2 * DEFAULT_ROW_H

    def test_sensor_auto_height_with_graph(self) -> None:
        # With graph="line", default height is 3 * DEFAULT_ROW_H.
        w = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 3 * DEFAULT_ROW_H

    def test_sensor_explicit_h_preserved(self) -> None:
        # An explicit h overrides the auto-sized default.
        w = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 200,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200


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

    def test_device_battery_default_render(self) -> None:
        # device_battery derives font size from h (not font_size);
        # verify that a default h=40 render produces dark pixels in
        # the icon and label region at 75% charge.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 20,
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
            _family, style = medium.getname()
            if style != "Regular":
                assert style == "Medium"

    def test_bold_returns_different_object(self) -> None:
        # bold=True must produce a distinct cached object
        regular = _load_font(18)
        bold = _load_font(18, bold=True)
        assert regular is not bold
        # When the TTF is available, verify the actual font style
        if hasattr(bold, "getname"):
            _family, style = bold.getname()
            if style != "Regular":
                assert style == "Bold"

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
        """Reference values at the default row height."""
        m = _compute_metrics(56)
        assert m.border == 2
        assert m.padding == 12
        assert m.radius == 12
        assert m.icon_dia == 36
        assert m.icon_inner == 21
        assert m.font_letter == 18
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
        """Unclamped fields scale proportionally at small heights."""
        m = _compute_metrics(10)
        assert m.padding == 2
        assert m.radius == 2
        assert m.icon_dia == 6
        assert m.icon_inner == 3
        assert m.font_letter == 3
        assert m.inner_gap == 2

    def test_scales_at_large_row_h(self) -> None:
        """All fields scale proportionally at large heights."""
        m = _compute_metrics(200)
        assert m.border == 8
        assert m.padding == 42
        assert m.radius == 42
        assert m.icon_dia == 128
        assert m.icon_inner == 76
        assert m.font_letter == 64
        assert m.font_primary == 64
        assert m.font_secondary == 50
        assert m.divider == 14
        assert m.inner_gap == 42
        assert m.left_bar == 14

    def test_reference_h40(self) -> None:
        """All fields at a compact row height."""
        m = _compute_metrics(40)
        assert m.border == 2
        assert m.padding == 8
        assert m.radius == 8
        assert m.icon_dia == 26
        assert m.icon_inner == 15
        assert m.font_letter == 13
        assert m.font_primary == 13
        assert m.font_secondary == 10
        assert m.divider == 3
        assert m.inner_gap == 8
        assert m.left_bar == 3

    def test_reference_h72(self) -> None:
        """All fields at a spacious row height."""
        m = _compute_metrics(72)
        assert m.border == 3
        assert m.padding == 15
        assert m.radius == 15
        assert m.icon_dia == 46
        assert m.icon_inner == 27
        assert m.font_letter == 23
        assert m.font_primary == 23
        assert m.font_secondary == 18
        assert m.divider == 5
        assert m.inner_gap == 15
        assert m.left_bar == 5

    def test_clamp_boundary_border(self) -> None:
        assert _compute_metrics(37).border == 2  # clamped: round(1.48) = 1 < 2
        assert _compute_metrics(100).border == 4  # natural: round(4) = 4 > 2

    def test_all_fields_present(self) -> None:
        m = _compute_metrics(56)
        for f in dataclasses.fields(WidgetMetrics):
            assert isinstance(getattr(m, f.name), int), f"{f.name} is not int"

    def test_default_metrics_matches_default_row_h(
        self,
    ) -> None:
        """Module-level DEFAULT_METRICS matches DEFAULT_ROW_H."""
        # Verify the module-level constant equals
        # _compute_metrics(DEFAULT_ROW_H).
        assert _compute_metrics(DEFAULT_ROW_H) == DEFAULT_METRICS

    def test_default_metrics_is_frozen(self) -> None:
        """DEFAULT_METRICS is immutable."""
        # Assignment to a frozen dataclass field must raise AttributeError.
        with pytest.raises(AttributeError):
            DEFAULT_METRICS.border = 99  # type: ignore[misc]


class TestHelperFunctions:
    """Unit tests for shared helpers in svg_render.py."""

    def test_metrics_context_keys(self) -> None:
        """All keys are m_-prefixed and include baseline values."""
        ctx = _metrics_context(_compute_metrics(56))
        assert all(k.startswith("m_") for k in ctx)
        assert ctx["m_padding"] == 12

    def test_card_insets_border(self) -> None:
        """Border style insets padding on both sides."""
        m = _compute_metrics(56)
        assert _card_insets(m, "border", 16) == (
            m.padding,
            m.padding,
            0,
        )

    def test_card_insets_left_bar(self) -> None:
        """Left-bar style insets bar_w + padding on the left."""
        m = _compute_metrics(56)
        assert _card_insets(m, "left_bar", 16) == (
            m.left_bar + m.padding,
            0,
            m.left_bar,
        )

    def test_card_insets_left_bar_2level(self) -> None:
        """2-level display widens the bar via max(10, left_bar*3)."""
        m = _compute_metrics(56)
        bar_w = max(10, m.left_bar * 3)
        assert _card_insets(m, "left_bar", 2) == (
            bar_w + m.padding,
            0,
            bar_w,
        )

    def test_card_insets_none(self) -> None:
        """No card style produces zero insets."""
        m = _compute_metrics(56)
        assert _card_insets(m, "none", 16) == (0, 0, 0)

    def test_auto_row_height_no_title(self) -> None:
        """Without title, height is num_rows * DEFAULT_ROW_H."""
        assert _auto_row_height("", 2) == 2 * DEFAULT_ROW_H

    def test_auto_row_height_with_title(self) -> None:
        """With title, content_h matches target within 1 px."""
        h = _auto_row_height("Title", 2)
        _, _, content_h = _title_layout("Title", h)
        assert abs(content_h - 2 * DEFAULT_ROW_H) <= 1

    def test_auto_row_height_rejects_zero_rows(self) -> None:
        """num_rows < 1 raises ValueError."""
        with pytest.raises(ValueError, match="num_rows"):
            _auto_row_height("", 0)


class TestConsistencyContract:
    """Regression guards for cross-widget layout consistency.

    These tests assert that shared layout primitives (icon position,
    icon diameter, text position, color palette) remain consistent
    across widget types as the codebase evolves.
    """

    _ROW_H = 56
    _W = 400

    @classmethod
    def setup_class(cls) -> None:
        """Render reference images once for all tests in this class."""
        sr_widget: dict[str, object] = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": cls._W,
            "h": cls._ROW_H,
            "entities": ["sensor.living_room_temperature"],
        }
        sr_cfg = make_config(
            {
                "width": cls._W,
                "height": cls._ROW_H,
                "states": MOCK_SENSOR_STATES,
            }
        )
        cls._sr_img = render_to_image([sr_widget], sr_cfg)

        ws_widget: dict[str, object] = {
            "type": "waste_schedule",
            "x": 0,
            "y": 0,
            "w": cls._W,
            "h": cls._ROW_H,
            "entity": "sensor.waste_collection",
            "entries": [{"attribute": "Restmuell", "label": "Restmuell"}],
        }
        ws_cfg = make_config(
            {
                "width": cls._W,
                "height": cls._ROW_H,
                "states": MOCK_WASTE_SCHEDULE_STATES,
            }
        )
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            cls._ws_img = render_to_image([ws_widget], ws_cfg)

    def test_card_row_widgets_share_icon_position(self) -> None:
        # Two card_row widgets at the same row_h place the icon circle
        # at the same x offset from the widget left edge.
        m = _compute_metrics(self._ROW_H)
        # Strip exactly wide enough to contain the icon circle, no wider,
        # to avoid glyph ink from the text region affecting the bbox.
        icon_x2 = m.padding + m.icon_dia
        sr_bbox = content_bbox(self._sr_img, 0, 0, icon_x2, self._ROW_H)
        ws_bbox = content_bbox(self._ws_img, 0, 0, icon_x2, self._ROW_H)

        assert sr_bbox is not None, "sensor_rows: no icon pixels found"
        assert ws_bbox is not None, "waste_schedule: no icon pixels found"
        assert sr_bbox[0] == ws_bbox[0], (
            f"icon left edge differs: sensor_rows={sr_bbox[0]}, "
            f"waste_schedule={ws_bbox[0]}"
        )

    def test_card_row_widgets_share_icon_diameter(self) -> None:
        # Two card_row widgets at the same row_h produce the same icon
        # circle width (icon_dia from _compute_metrics).
        m = _compute_metrics(self._ROW_H)
        icon_x2 = m.padding + m.icon_dia
        sr_bbox = content_bbox(self._sr_img, 0, 0, icon_x2, self._ROW_H)
        ws_bbox = content_bbox(self._ws_img, 0, 0, icon_x2, self._ROW_H)

        assert sr_bbox is not None
        assert ws_bbox is not None
        sr_dia = sr_bbox[2] - sr_bbox[0]
        ws_dia = ws_bbox[2] - ws_bbox[0]
        assert sr_dia == ws_dia, (
            f"icon diameter differs: sensor_rows={sr_dia}, "
            f"waste_schedule={ws_dia}"
        )

    def test_card_row_widgets_share_text_position(self) -> None:
        # Two card_row widgets at the same row_h place primary text at
        # the same x offset.  Tolerance of 1px accounts for glyph-edge
        # variation between different first characters (e.g. 'L' vs 'R'
        # have slightly different leftmost ink pixels in Roboto).
        m = _compute_metrics(self._ROW_H)
        # Expected text x: lpad + icon_dia + inner_gap with no card frame.
        tx = m.padding + m.icon_dia + m.inner_gap

        # Crop just the text area (right of icon).
        sr_bbox = content_bbox(self._sr_img, tx - 2, 0, tx + 200, self._ROW_H)
        ws_bbox = content_bbox(self._ws_img, tx - 2, 0, tx + 200, self._ROW_H)

        assert sr_bbox is not None, "sensor_rows: no text pixels found"
        assert ws_bbox is not None, "waste_schedule: no text pixels found"
        assert abs(sr_bbox[0] - ws_bbox[0]) <= 1, (
            f"text left edge differs by more than 1px: "
            f"sensor_rows={sr_bbox[0]}, waste_schedule={ws_bbox[0]}"
        )

    def test_chip_and_card_row_same_icon_dia(self) -> None:
        # The status_icons context builder must pass the same icon_dia
        # that card_row uses at the same height — both must come from
        # _compute_metrics().  Font size is intentionally different:
        # chip uses 46% of h while card_row uses font_primary (32%),
        # so only icon diameter is verified here.
        for h in (40, 56, 72, 100):
            m = _compute_metrics(h)
            widget: dict[str, object] = {
                "type": "status_icons",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entities": ["binary_sensor.front_door"],
            }
            cfg = make_config(
                {"width": 400, "height": h, "states": MOCK_STATUS_ICON_STATES}
            )
            # render_widget_svg returns the rendered SVG; the context is
            # not directly accessible, so we verify indirectly by
            # checking that the rendered icon circle diameter matches
            # what _compute_metrics() prescribes.
            svg = render_widget_svg(widget, cfg)
            # Anchor the search to <circle to avoid collisions with
            # other SVG elements that may carry numeric r-like attributes.
            expected_r = m.icon_dia // 2
            assert re.search(
                r"<circle[^>]*\br=\"" + str(expected_r) + r"\"", svg
            ), (
                f"h={h}: chip circle radius {expected_r} not found in SVG; "
                f"icon_dia should be {m.icon_dia}"
            )

    def test_svg_colors_match_palette_sensor_rows(self) -> None:
        # All hex colors in a rendered sensor_rows SVG come from
        # color_to_hex() applied to known const.py color constants.
        widget: dict[str, object] = {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": self._W,
            "h": self._ROW_H,
            "entities": ["sensor.living_room_temperature"],
        }
        cfg = make_config(
            {
                "width": self._W,
                "height": self._ROW_H,
                "states": MOCK_SENSOR_STATES,
            }
        )
        svg = render_widget_svg(widget, cfg)
        palette = {
            color_to_hex(COLOR_BLACK),
            color_to_hex(COLOR_WHITE),
            color_to_hex(COLOR_GRAY),
            color_to_hex(COLOR_LIGHT_GRAY),
        }
        colors = set(re.findall(r"#[0-9a-f]{6}", svg.lower()))
        assert colors <= palette, (
            f"Unexpected hex colors in sensor_rows SVG: {colors - palette}"
        )

    def test_svg_colors_match_palette_waste_schedule(self) -> None:
        # All hex colors in a rendered waste_schedule SVG come from
        # color_to_hex() — including per-row dynamic fills for urgency
        # styling (date_fill, icon_fill).
        widget: dict[str, object] = {
            "type": "waste_schedule",
            "x": 0,
            "y": 0,
            "w": self._W,
            "h": self._ROW_H,
            "entity": "sensor.waste_collection",
            "entries": [{"attribute": "Restmuell", "label": "Restmuell"}],
        }
        cfg = make_config(
            {
                "width": self._W,
                "height": self._ROW_H,
                "states": MOCK_WASTE_SCHEDULE_STATES,
            }
        )
        palette = {
            color_to_hex(COLOR_BLACK),
            color_to_hex(COLOR_WHITE),
            color_to_hex(COLOR_GRAY),
            color_to_hex(COLOR_LIGHT_GRAY),
        }
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(widget, cfg)
        colors = set(re.findall(r"#[0-9a-f]{6}", svg.lower()))
        assert colors <= palette, (
            f"Unexpected hex colors in waste_schedule SVG: {colors - palette}"
        )


class TestResolveNumberFormat:
    def test_language_en_returns_comma_decimal(self) -> None:
        # English defaults to dot decimal (comma thousands).
        result = resolve_number_format("language", "en")
        assert result == NumberFormat.COMMA_DECIMAL

    def test_language_de_returns_decimal_comma(self) -> None:
        # German defaults to comma decimal (dot thousands).
        result = resolve_number_format("language", "de")
        assert result == NumberFormat.DECIMAL_COMMA

    def test_language_fr_returns_space_comma(self) -> None:
        # French defaults to space thousands + comma decimal.
        result = resolve_number_format("language", "fr")
        assert result == NumberFormat.SPACE_COMMA

    def test_language_de_ch_uses_primary_subtag(self) -> None:
        # "de-CH" primary subtag is "de" → decimal_comma.
        result = resolve_number_format("language", "de-CH")
        assert result == NumberFormat.DECIMAL_COMMA

    def test_language_ja_returns_comma_decimal(self) -> None:
        # Japanese: not in comma/space sets → defaults to comma_decimal.
        result = resolve_number_format("language", "ja")
        assert result == NumberFormat.COMMA_DECIMAL

    def test_explicit_decimal_comma_returned_as_is(self) -> None:
        # Explicit formats bypass language lookup.
        assert (
            resolve_number_format("decimal_comma", "en")
            == NumberFormat.DECIMAL_COMMA
        )

    def test_system_treated_as_comma_decimal(self) -> None:
        # Server-side has no browser locale; "system" falls back to
        # dot decimal.
        result = resolve_number_format("system", "en")
        assert result == NumberFormat.COMMA_DECIMAL

    def test_none_returned_as_is(self) -> None:
        assert resolve_number_format("none", "en") == NumberFormat.NONE


class TestFormatNumber:
    def test_non_numeric_string_passes_through(self) -> None:
        # "on", "off", and HA sentinels must not be modified.
        assert format_number("on", "decimal_comma", "de") == "on"

    def test_unavailable_passes_through(self) -> None:
        result = format_number("unavailable", "decimal_comma", "de")
        assert result == "unavailable"

    def test_double_dash_passes_through(self) -> None:
        assert format_number("--", "decimal_comma", "de") == "--"

    def test_integer_no_decimal_unchanged(self) -> None:
        # Integers have no decimal separator to swap.
        assert format_number("22", "decimal_comma", "de") == "22"

    def test_comma_decimal_preserves_dot(self) -> None:
        # US/UK style: decimal separator stays as ".".
        assert format_number("8.41", "comma_decimal", "en") == "8.4"

    def test_decimal_comma_swaps_to_comma(self) -> None:
        # German style: "8.41" → "8,4".
        assert format_number("8.41", "decimal_comma", "de") == "8,4"

    def test_space_comma_swaps_to_comma(self) -> None:
        # French style: decimal separator is ",".
        assert format_number("8.41", "space_comma", "fr") == "8,4"

    def test_quote_decimal_preserves_dot(self) -> None:
        # Swiss German style: decimal separator is ".".
        assert format_number("8.41", "quote_decimal", "de-CH") == "8.4"

    def test_none_format_no_grouping(self) -> None:
        # No formatting: keep dot decimal, no grouping.
        assert format_number("1234.56", "none", "en") == "1234.6"

    def test_thousands_grouping_comma_decimal(self) -> None:
        # 1,234.56 for US style.
        assert format_number("1234.56", "comma_decimal", "en") == "1,234.6"

    def test_thousands_grouping_decimal_comma(self) -> None:
        # 1.234,56 for German style.
        assert format_number("1234.56", "decimal_comma", "de") == "1.234,6"

    def test_thousands_grouping_space_comma(self) -> None:
        # French: narrow non-breaking space + comma decimal.
        result = format_number("1234.56", "space_comma", "fr")
        assert result == "1 234,6"

    def test_thousands_grouping_quote_decimal(self) -> None:
        # Swiss: apostrophe thousands + dot decimal.
        assert format_number("1234.56", "quote_decimal", "de-CH") == "1'234.6"

    def test_decimal_places_capped_at_one(self) -> None:
        # Values with more than 1 decimal place are capped at 1 —
        # e-ink displays are small and extra precision is noise.
        assert format_number("8.410", "decimal_comma", "de") == "8,4"
        assert format_number("15.600000", "decimal_comma", "de") == "15,6"

    def test_language_de_inferred(self) -> None:
        # "language" + "de" → decimal_comma.
        assert format_number("8.41", "language", "de") == "8,4"

    def test_language_en_inferred(self) -> None:
        # "language" + "en" → comma_decimal (dot decimal, no change for small
        # values without thousands).
        assert format_number("8.41", "language", "en") == "8.4"

    def test_negative_value(self) -> None:
        # Negative numbers should preserve the minus sign.
        assert format_number("-8.41", "decimal_comma", "de") == "-8,4"


class TestLocaleFormattingInWidgets:
    """Verify that locale number format is applied in SVG output."""

    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 100,
        "number_format": "comma_decimal",
        "language": "en",
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def test_entity_widget_decimal_comma(self) -> None:
        # Entity widget with German locale must render comma decimal.
        widget = {
            "type": "entity",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

    def test_entity_widget_comma_decimal(self) -> None:
        # Entity widget with US locale must keep dot decimal.
        widget = {
            "type": "entity",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="comma_decimal",
            language="en",
        )
        svg = render_widget_svg(widget, config)
        assert "8.4" in svg

    def test_sensor_row_decimal_comma(self) -> None:
        # Sensor row secondary text must be formatted for German locale.
        widget = {
            "type": "sensor_rows",
            "entities": ["sensor.humidity"],
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {
                        "unit_of_measurement": "g/m³",
                        "friendly_name": "Humidity",
                    },
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg

    def test_non_numeric_state_unchanged(self) -> None:
        # "unavailable" should not be mangled by format_number.
        widget = {
            "type": "entity",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "unavailable",
                    "attributes": {},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "unavailable" in svg

    def test_tile_widget_decimal_comma(self) -> None:
        # Tile secondary text must use comma decimal for German locale.
        widget = {
            "type": "tile",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

    def test_heading_badge_decimal_comma(self) -> None:
        # Heading badge state must use comma decimal for German locale.
        widget = {
            "type": "heading",
            "heading": "Room",
            "badges": ["sensor.humidity"],
            "w": 400,
            "h": 56,
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg


    def test_entities_decimal_comma(self) -> None:
        # Entities state value must use comma decimal for German locale.
        widget = {
            "type": "entities",
            "entities": ["sensor.humidity"],
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {
                        "unit_of_measurement": "g/m³",
                        "friendly_name": "Humidity",
                    },
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

    def test_weather_decimal_comma(self) -> None:
        # Weather detail values must use dot-thousands for German locale.
        # Pressure 1013 → "1.013" with decimal_comma thousands separator.
        widget = {
            "type": "weather",
            "entity": "weather.home",
        }
        config = self._config(
            width=600,
            height=400,
            states=MOCK_WEATHER_STATE,
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "1.013" in svg

    def test_sensor_widget_decimal_comma(self) -> None:
        # Sensor widget value must use comma decimal for German locale.
        widget = {
            "type": "sensor",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

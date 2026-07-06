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

import re
from typing import ClassVar

from custom_components.eink_dashboard.const import DEFAULT_ROW_H
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    make_config,
    render_to_image,
)

# Sensor with a mid-range value (22.5%) so fill and background arcs
# are both visible in the standard 270° gauge.
MOCK_GAUGE_STATES: dict[str, dict[str, object]] = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    },
    "sensor.pressure": {
        "state": "1013",
        "attributes": {
            "friendly_name": "Barometer",
            "device_class": "pressure",
            "unit_of_measurement": "hPa",
        },
    },
    # value=0 → fill_pct=0, entire arc is background gray.
    "sensor.zero": {
        "state": "0",
        "attributes": {
            "friendly_name": "Empty",
            "unit_of_measurement": "%",
        },
    },
    # Entity with a numeric attribute for testing attribute= key.
    "sensor.with_attr": {
        "state": "50",
        "attributes": {
            "friendly_name": "Attributed",
            "unit_of_measurement": "%",
            "my_attr": 75.3,
        },
    },
    # Non-numeric state to exercise the decimals fallback path.
    "sensor.unavailable": {
        "state": "unavailable",
        "attributes": {
            "friendly_name": "Unavailable Sensor",
        },
    },
}


class TestRenderGauge:
    """Verify rendering of gauge widgets.

    Covers circular arc shapes, fill/needle modes, segment labels,
    name position, and card styles.
    """

    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 400,
        "states": MOCK_GAUGE_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        """Return display config merged with overrides."""
        return make_config(self._DEFAULTS, **overrides)

    def _base_widget(self, **overrides: object) -> dict[str, object]:
        """Return a 200×200 gauge widget dict merged with overrides."""
        w: dict[str, object] = {
            "type": "gauge",
            "x": 0,
            "y": 0,
            "w": 200,
            "h": 200,
            "entity": "sensor.temperature",
        }
        w.update(overrides)
        return w

    # ── Arc rendering ──────────────────────────────────────────────────

    def test_gauge_draws_dark_pixels(self) -> None:
        # Gauge renders dark pixels somewhere in the widget area.
        img = render_to_image([self._base_widget()], self._config())
        assert_has_dark_pixels(img, 0, 0, 200, 200)

    def test_gauge_top_arc_region(self) -> None:
        # Standard 270° gauge traces through the 12 o'clock position;
        # the top strip of the widget must contain non-white pixels.
        img = render_to_image([self._base_widget()], self._config())
        assert_has_dark_pixels(img, 40, 0, 160, 65, threshold=200)

    def test_gauge_left_arc_region(self) -> None:
        # Standard 270° gauge arc passes through the 9 o'clock (left)
        # position; the left edge of the middle band must be non-white.
        img = render_to_image([self._base_widget()], self._config())
        assert_has_dark_pixels(img, 0, 50, 55, 130, threshold=200)

    def test_gauge_right_arc_region(self) -> None:
        # Standard 270° gauge arc passes through the 3 o'clock (right)
        # position; the right edge of the middle band must be non-white.
        img = render_to_image([self._base_widget()], self._config())
        assert_has_dark_pixels(img, 145, 50, 200, 130, threshold=200)

    def test_gauge_background_arc_is_light_gray(self) -> None:
        # The background arc (unfilled portion) is COLOR_LIGHT_GRAY
        # (~180).  With value=0 (fill_pct=0) the entire arc is the
        # background arc.  The top region (always unfilled for low
        # values) must contain light-gray pixels, not black.
        widget = self._base_widget(entity="sensor.zero")
        img = render_to_image([widget], self._config())
        assert_has_gray_pixels(img, 65, 2, 135, 60, low=150, high=215)

    def test_gauge_fill_arc_is_dark(self) -> None:
        # For value=22.5 (non-zero fill), the filled portion of the arc
        # must produce pixels darker than the background gray.
        img = render_to_image([self._base_widget()], self._config())
        assert_has_dark_pixels(img, 0, 0, 200, 200, threshold=100)

    def test_gauge_value_text_in_center(self) -> None:
        # Value text is rendered in the center interior of the arc.
        img = render_to_image([self._base_widget()], self._config())
        assert_has_dark_pixels(img, 45, 45, 155, 145)

    def test_gauge_bold_value_renders_bold_weight(self) -> None:
        # bold_value=True renders the center value text with a
        # bold font-weight instead of the default medium (500).
        svg = render_widget_svg(
            self._base_widget(bold_value=True), self._config()
        )
        assert 'font-weight="bold"' in svg

    def test_gauge_default_value_is_medium_weight(self) -> None:
        # Without bold_value, the center value text uses the
        # medium (500) font-weight, not bold.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert 'font-weight="500"' in svg
        assert 'font-weight="bold"' not in svg

    def test_gauge_name_label_at_bottom(self) -> None:
        # Default header_position="bottom": name label rendered near
        # the bottom of the widget.
        img = render_to_image([self._base_widget()], self._config())
        assert_has_dark_pixels(img, 10, 155, 190, 200)

    # ── Gauge types ────────────────────────────────────────────────────

    def test_gauge_standard_and_full_differ(self) -> None:
        # Standard (270°) and full (360°) gauge types produce different
        # renders — the full gauge has no gap at the bottom.
        std = render_dashboard(
            [self._base_widget(gauge_type="standard")], self._config()
        )
        full = render_dashboard(
            [self._base_widget(gauge_type="full")], self._config()
        )
        assert std != full

    def test_gauge_standard_and_half_differ(self) -> None:
        # Standard (270°) and half (180°) gauge types produce different
        # renders.
        std = render_dashboard(
            [self._base_widget(gauge_type="standard")], self._config()
        )
        half = render_dashboard(
            [self._base_widget(gauge_type="half")], self._config()
        )
        assert std != half

    def test_gauge_full_type_has_pixels_everywhere(self) -> None:
        # Full (360°) gauge arc covers all four cardinal positions.
        img = render_to_image(
            [self._base_widget(gauge_type="full")], self._config()
        )
        # Top
        assert_has_dark_pixels(img, 40, 0, 160, 65, threshold=200)
        # Left
        assert_has_dark_pixels(img, 0, 50, 55, 130, threshold=200)
        # Right
        assert_has_dark_pixels(img, 145, 50, 200, 130, threshold=200)

    def test_gauge_half_type_has_top_arc(self) -> None:
        # Half (180°) gauge arc traces the top semicircle from 9 to 3
        # o'clock via 12 o'clock.
        img = render_to_image(
            [self._base_widget(gauge_type="half")], self._config()
        )
        assert_has_dark_pixels(img, 40, 0, 160, 100, threshold=200)

    # ── Needle vs fill ─────────────────────────────────────────────────

    def test_gauge_needle_mode_differs_from_fill(self) -> None:
        # needle=True produces different output than needle=False.
        fill_png = render_dashboard(
            [self._base_widget(needle=False)], self._config()
        )
        needle_png = render_dashboard(
            [self._base_widget(needle=True)], self._config()
        )
        assert fill_png != needle_png

    def test_gauge_needle_mode_has_arc_pixels(self) -> None:
        # Needle mode still draws arc pixels (segment bands or plain
        # background arc).
        img = render_to_image([self._base_widget(needle=True)], self._config())
        assert_has_dark_pixels(img, 0, 0, 200, 200, threshold=200)

    # ── Header position ────────────────────────────────────────────────

    def test_gauge_header_position_top(self) -> None:
        # header_position="top" moves name label to the top strip.
        img = render_to_image(
            [self._base_widget(header_position="top")], self._config()
        )
        assert_has_dark_pixels(img, 10, 0, 190, 40)

    def test_gauge_header_top_and_bottom_differ(self) -> None:
        # top and bottom header positions produce different renders.
        top_png = render_dashboard(
            [self._base_widget(header_position="top")], self._config()
        )
        bot_png = render_dashboard(
            [self._base_widget(header_position="bottom")],
            self._config(),
        )
        assert top_png != bot_png

    # ── Card styles ────────────────────────────────────────────────────

    def test_gauge_card_border(self) -> None:
        # card_style="border" draws dark pixels on all four card edges.
        # Uses DEFAULT_ROW_H metrics to match the context builder.
        w, h = 200, 200
        m = _compute_metrics(DEFAULT_ROW_H)
        img = render_to_image(
            [self._base_widget(card_style="border")], self._config()
        )
        assert_card_border(img, w, h, m)

    def test_gauge_card_left_bar(self) -> None:
        # card_style="left_bar" draws a gray bar on the left edge.
        img = render_to_image(
            [self._base_widget(card_style="left_bar")], self._config()
        )
        assert_has_gray_pixels(img, 0, 10, 20, 190)

    def test_gauge_card_none_is_default(self) -> None:
        # Omitting card_style is byte-identical to card_style="none".
        with_none = render_dashboard(
            [{**self._base_widget(), "card_style": "none"}],
            self._config(),
        )
        without = render_dashboard([self._base_widget()], self._config())
        assert with_none == without

    # ── Edge cases ─────────────────────────────────────────────────────

    def test_gauge_attribute_display(self) -> None:
        # attribute= reads the specified entity attribute instead of
        # the state value; the render must differ from the default.
        base = self._base_widget(entity="sensor.with_attr")
        default_png = render_dashboard([base], self._config())
        attr_png = render_dashboard(
            [{**base, "attribute": "my_attr"}], self._config()
        )
        assert default_png != attr_png

    def test_gauge_non_numeric_state_with_decimals(self) -> None:
        # Non-numeric state with decimals set falls back to the raw
        # state string without crashing.
        widget = self._base_widget(entity="sensor.unavailable", decimals=2)
        svg = render_widget_svg(widget, self._config())
        assert "unavailable" in svg

    def test_gauge_min_equals_max(self) -> None:
        # When min == max val_range is 0; fill_pct guard returns 0.0
        # and the widget renders without a ZeroDivisionError.
        widget = self._base_widget(min=50, max=50)
        svg = render_widget_svg(widget, self._config())
        assert svg

    # ── Segment handling ───────────────────────────────────────────────

    def test_gauge_segment_label_in_svg(self) -> None:
        # Segment label for the matching value appears in SVG output.
        # value=22.5 lies in [0, 30) → label "Cool".
        segments: list[object] = [
            {"from": 0, "color": 180, "label": "Cool"},
            {"from": 30, "color": 80, "label": "Warm"},
        ]
        widget = self._base_widget(segments=segments)
        svg = render_widget_svg(widget, self._config())
        assert "Cool" in svg

    def test_gauge_segment_no_label_when_above_threshold(self) -> None:
        # value=22.5 ≥ 30 threshold is NOT met, so "Warm" label is
        # absent; "Cool" label is present.
        segments: list[object] = [
            {"from": 0, "color": 180, "label": "Cool"},
            {"from": 30, "color": 80, "label": "Warm"},
        ]
        widget = self._base_widget(segments=segments)
        svg = render_widget_svg(widget, self._config())
        assert "Warm" not in svg

    def test_gauge_segment_color_int(self) -> None:
        # Integer segment color (grayscale 0–255) accepted without error.
        segments: list[object] = [{"from": 0, "color": 180, "label": "Low"}]
        widget = self._base_widget(segments=segments)
        svg = render_widget_svg(widget, self._config())
        assert svg  # non-empty SVG, no exception

    def test_gauge_segment_color_hex(self) -> None:
        # Hex segment color is auto-converted to grayscale.
        segments: list[object] = [{"from": 0, "color": "#4b75ec"}]
        widget = self._base_widget(segments=segments)
        svg = render_widget_svg(widget, self._config())
        assert svg

    def test_gauge_segment_color_rgb(self) -> None:
        # RGB array segment color is auto-converted to grayscale.
        segments: list[object] = [{"from": 0, "color": [15, 138, 215]}]
        widget = self._base_widget(segments=segments)
        svg = render_widget_svg(widget, self._config())
        assert svg

    def test_gauge_no_segments_renders(self) -> None:
        # Gauge without segments renders successfully.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert svg

    def test_gauge_segments_with_needle_change_output(self) -> None:
        # Adding segments to needle mode changes the output (segment
        # bands are drawn in the background).
        no_segs = render_dashboard(
            [self._base_widget(needle=True)], self._config()
        )
        with_segs = render_dashboard(
            [
                self._base_widget(
                    needle=True,
                    segments=[
                        {"from": 0, "color": 200},
                        {"from": 50, "color": 100},
                    ],
                )
            ],
            self._config(),
        )
        assert no_segs != with_segs

    # ── SVG content ────────────────────────────────────────────────────

    def test_gauge_value_in_svg(self) -> None:
        # The entity state value appears in the SVG output.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "22" in svg  # "22.5" or rounded

    def test_gauge_unit_in_svg(self) -> None:
        # The unit_of_measurement attribute appears in the SVG output.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "°C" in svg

    def test_gauge_show_unit_false_hides_unit(self) -> None:
        # show_unit=False removes the unit from the SVG.
        widget = self._base_widget(show_unit=False)
        svg = render_widget_svg(widget, self._config())
        assert "°C" not in svg

    def test_gauge_custom_name_in_svg(self) -> None:
        # Explicit name override appears in the SVG output.
        widget = self._base_widget(name="My Gauge")
        svg = render_widget_svg(widget, self._config())
        assert "My Gauge" in svg

    def test_gauge_decimals_rounds_value(self) -> None:
        # decimals=0 rounds the displayed value to zero decimal places.
        widget = self._base_widget(decimals=0)
        svg = render_widget_svg(widget, self._config())
        # 22.5 with 0 decimals is "22" or "23" depending on rounding.
        assert re.search(r"\b2[23]\b", svg) is not None

    def test_gauge_custom_min_max(self) -> None:
        # Custom min/max change the fill_pct calculation.
        # With min=20, max=25, value=22.5 → 50% fill.
        # This should produce a different render than the default
        # min=0, max=100 (22.5% fill).
        default_png = render_dashboard([self._base_widget()], self._config())
        custom_png = render_dashboard(
            [self._base_widget(min=20, max=25)], self._config()
        )
        assert default_png != custom_png

    # ── Missing entity ─────────────────────────────────────────────────

    def test_gauge_missing_entity_white(self) -> None:
        # Missing entity renders a blank white widget without crashing.
        widget = self._base_widget(entity="sensor.nonexistent")
        img = render_to_image([widget], self._config())
        assert_all_white(img, 0, 0, 200, 200)

    # ── Auto-sizing ────────────────────────────────────────────────────

    def test_gauge_explicit_h_preserved(self) -> None:
        # Explicit h appears as the SVG height attribute.
        widget = {
            "type": "gauge",
            "x": 0,
            "y": 0,
            "w": 200,
            "h": 180,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(widget, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 180

    def test_gauge_auto_height_equals_width(self) -> None:
        # Without explicit h, the gauge defaults to h == w (square).
        widget = {
            "type": "gauge",
            "x": 0,
            "y": 0,
            "w": 200,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(widget, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200

    # ── Scaling ────────────────────────────────────────────────────────

    def test_gauge_scales_proportionally(self) -> None:
        # Doubling h roughly doubles the content height.
        w_small = self._base_widget(h=150)
        w_large = self._base_widget(h=300)
        img_small = render_to_image([w_small], self._config())
        img_large = render_to_image(
            [w_large],
            make_config(self._DEFAULTS, height=600),
        )
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(0, 0, 200, 150),
            region_large=(0, 0, 200, 300),
            expected_ratio=2.0,
            tolerance=0.4,
        )

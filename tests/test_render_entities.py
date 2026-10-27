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

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    DEFAULT_ROW_H,
)
from custom_components.eink_dashboard.fonts import (
    pixel_font_size,
    pixel_fonts_context,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets.entities import (
    _build_entities_context,
)
from tests.helpers import (
    _icon_ring_region,
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
            low=COLOR_LIGHT_GRAY - 20,
            high=COLOR_LIGHT_GRAY + 20,
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
            low=COLOR_LIGHT_GRAY - 20,
            high=COLOR_LIGHT_GRAY + 20,
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

    def test_entities_shrinks_when_too_small(self) -> None:
        # A widget shorter than DEFAULT_ROW_H per row still shrinks
        # its rows to fit (halving h halves the icon height).
        half = DEFAULT_ROW_H // 2
        m_small = _compute_metrics(half)
        m_large = _compute_metrics(DEFAULT_ROW_H)
        base = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": ["sensor.temperature"],
        }
        img_s = render_to_image([{**base, "h": half}], self._config())
        img_l = render_to_image([{**base, "h": DEFAULT_ROW_H}], self._config())
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(
                m_small.padding,
                0,
                m_small.padding + m_small.icon_dia,
                half,
            ),
            region_large=(
                m_large.padding,
                0,
                m_large.padding + m_large.icon_dia,
                DEFAULT_ROW_H,
            ),
            expected_ratio=2.0,
        )

    def test_entities_rows_do_not_grow_beyond_default(self) -> None:
        # A tall widget with one entity keeps the standard row
        # height and stacks it at the top instead of blowing it up.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 240,
            "entities": ["sensor.temperature"],
        }
        svg = render_widget_svg(w, self._config())
        img = render_to_image([w], self._config())
        assert 'height="240"' in svg
        assert_has_dark_pixels(img, 0, 0, 400, DEFAULT_ROW_H)
        assert_all_white(img, 0, DEFAULT_ROW_H + 2, 400, 240)

    def test_entities_row_height_caps_rows(self) -> None:
        # row_height sets the maximum row height: a tall widget with
        # one entity renders one row_height-tall row at the top.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 240,
            "row_height": 100,
            "entities": ["sensor.temperature"],
        }
        svg = render_widget_svg(w, self._config())
        img = render_to_image([w], self._config())
        m = _compute_metrics(100)
        assert f'r="{m.icon_dia // 2}"' in svg
        assert_has_dark_pixels(img, 0, 0, 400, 100)
        assert_all_white(img, 0, 102, 400, 240)

    def test_entities_row_height_drives_auto_height(self) -> None:
        # Without explicit h the widget is num_rows * row_height tall.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "row_height": 40,
            "entities": ["sensor.temperature", "sensor.humidity"],
        }
        svg = render_widget_svg(w, self._config())
        assert 'height="80"' in svg

    def test_entities_hide_icon(self) -> None:
        # hide_icon removes icon circles and letter fallbacks and
        # starts the text at the row's left padding.
        m = _compute_metrics(DEFAULT_ROW_H)
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "hide_icon": True,
            "entities": ["sensor.temperature", "binary_sensor.motion"],
        }
        svg = render_widget_svg(w, self._config())
        assert "<circle" not in svg
        assert "<path" not in svg
        assert f'<text\n  x="{m.padding}"' in svg

    def test_entities_divider_width_configurable(self) -> None:
        # divider_width sets a fixed stroke for auto and explicit
        # dividers on any display.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "divider_width": 1,
            "entities": [
                "sensor.temperature",
                "sensor.humidity",
                {"type": "divider"},
                "sensor.temperature",
            ],
        }
        for levels in (2, 16):
            svg = render_widget_svg(w, self._config(display_levels=levels))
            widths = re.findall(r'<line[^>]*stroke-width="(\d+)"', svg)
            assert widths == ["1", "1"]

    def test_entities_divider_width_zero_hides_divider(self) -> None:
        # divider_width=0 removes all divider lines.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "divider_width": 0,
            "entities": [
                "sensor.temperature",
                "sensor.humidity",
                {"type": "divider"},
                "sensor.temperature",
            ],
        }
        svg = render_widget_svg(w, self._config())
        assert "<line" not in svg

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

    def test_entities_ignores_widget_level_name_and_icon(self) -> None:
        # Stray widget-level ``name``/``icon`` keys in stored JSON must
        # not override the per-row entity defaults.
        base_widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["sensor.temperature"],
        }
        stray_widget = {
            **base_widget,
            "name": "Kitchen Sensor",
            "icon": "mdi:lightbulb",
        }
        img_base = render_to_image([base_widget], self._config())
        img_stray = render_to_image([stray_widget], self._config())
        assert img_base.tobytes() == img_stray.tobytes()

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

    def test_entities_decimals_overrides_default_precision(self) -> None:
        # decimals=0 rounds every row's value to a whole number,
        # overriding the default capped-at-1 formatting.
        widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["sensor.temperature"],
            "decimals": 0,
        }
        ctx = _build_entities_context(widget, self._config())
        assert ctx["rows"][0]["value"] == "22°C"

    def test_entities_humidity_uses_device_class_default_precision(
        self,
    ) -> None:
        # With no widget decimals= and no HA display_precision, a
        # humidity entity falls back to the device-class default of
        # 0 decimals, matching HA's own whole-percent display.
        states = {
            **MOCK_ENTITIES_STATES,
            "sensor.humidity": {
                "state": "48.2",
                "attributes": {
                    "friendly_name": "Humidity",
                    "device_class": "humidity",
                    "unit_of_measurement": "%",
                },
            },
        }
        widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["sensor.humidity"],
        }
        ctx = _build_entities_context(widget, self._config(states=states))
        assert ctx["rows"][0]["value"] == "48%"

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

    def test_entities_value_text_black(self) -> None:
        # The right-aligned state value is rendered in black (the
        # value is the most important element, so it gets the
        # highest contrast).
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
        # Right portion of the row at mid-height should have black
        # pixels from the right-aligned state value text.
        assert any(
            pixel(img, x, y) < 64
            for y in range(20, 60)
            for x in range(300, 395)
        ), "state value text should be black (< 64)"

    def test_entities_value_font_larger_than_name(self) -> None:
        # The state value is the element users scan for at a
        # glance, so it must render in a larger font than the
        # entity name.  Compare SVG font sizes, which are snapped
        # to the TRMNL pixel grid: at the capped 56 px row the
        # name's descenders make rendered glyph boxes equally tall.
        m = _compute_metrics(DEFAULT_ROW_H)
        widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": DEFAULT_ROW_H,
            "entities": ["sensor.temperature"],
        }
        svg = render_widget_svg(widget, self._config())
        sizes = {
            int(sz) for sz in re.findall(r'<text[^>]*font-size="(\d+)"', svg)
        }
        # Sizes are snapped to the TRMNL pixel grid (default on).
        with pixel_fonts_context(True):
            primary = pixel_font_size(m.font_primary)
            secondary = pixel_font_size(m.font_secondary)
        assert primary in sizes
        assert secondary in sizes
        assert primary > secondary

    def test_entities_default_value_not_bold(self) -> None:
        # By default, the row value has no bold
        # font-weight attribute.
        widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": DEFAULT_ROW_H,
            "entities": ["sensor.temperature"],
        }
        svg = render_widget_svg(widget, self._config())
        assert 'font-weight="bold"' not in svg

    # ── Icon style tests ──────────────────────────────

    def test_entities_icon_circle_gray_fill_active(self) -> None:
        # Active entity (state "on") without explicit icon_style draws
        # a filled gray circle.  The top ring above the icon glyph
        # contains gray background pixels.
        m = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entities": ["binary_sensor.motion"],
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(DEFAULT_ROW_H, m)
        assert_has_gray_pixels(
            img, rx1, ry1, rx2, ry2, low=COLOR_GRAY - 20, high=COLOR_GRAY + 20
        )

    def test_entities_icon_circle_outlined_inactive(
        self,
    ) -> None:
        # Inactive entity (state "off") without explicit icon_style
        # draws an outlined circle with white fill.
        m = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entities": ["binary_sensor.front_door"],
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(DEFAULT_ROW_H, m)
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
        m = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entities": ["binary_sensor.front_door"],
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(DEFAULT_ROW_H, m)
        assert_has_gray_pixels(
            img, rx1, ry1, rx2, ry2, low=COLOR_GRAY - 20, high=COLOR_GRAY + 20
        )

    def test_entities_icon_style_outlined_explicit(self) -> None:
        # icon_style="outlined" forces an outlined circle even for an
        # active entity (state "on"); top ring has white fill.
        m = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entities": ["binary_sensor.motion"],
                "icon_style": "outlined",
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(DEFAULT_ROW_H, m)
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
        m = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entities": ["binary_sensor.motion"],
                "icon_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        rx1, ry1, rx2, ry2 = _icon_ring_region(DEFAULT_ROW_H, m)
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
        # On a 2-level display (display_levels=2) the auto-switch
        # forces outlined even for an active entity (state "on");
        # top ring has no gray fill.
        m = _compute_metrics(DEFAULT_ROW_H)
        widgets = [
            {
                "type": "entities",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": DEFAULT_ROW_H,
                "entities": ["binary_sensor.motion"],
            }
        ]
        img = render_to_image(widgets, self._config(display_levels=2))
        rx1, ry1, rx2, ry2 = _icon_ring_region(
            DEFAULT_ROW_H, m, stroke_inset=m.border * 3 // 2
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

    def test_entities_divider_defaults_to_one_pixel(self) -> None:
        # Without divider_width auto and explicit dividers are 1 px
        # on every display.
        w = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": [
                "sensor.temperature",
                "sensor.humidity",
                {"type": "divider"},
                "sensor.temperature",
            ],
        }
        for levels in (2, 16):
            svg = render_widget_svg(w, self._config(display_levels=levels))
            widths = re.findall(r'<line[^>]*stroke-width="(\d+)"', svg)
            assert widths == ["1", "1"]

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

    # ── Font customization tests ──────────────────────

    def test_entities_value_font_size_override(self) -> None:
        # fonts.value.size enlarges the right-aligned state value
        # glyphs relative to the widget's derived default size.
        widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 56,
            "entities": ["binary_sensor.front_door"],
        }
        default = render_to_image([widget], self._config())
        bigger = render_to_image(
            [{**widget, "fonts": {"value": {"size": 40}}}],
            self._config(),
        )
        # Only the right-aligned value lives in the right strip; the
        # name and icon sit far to the left of it.
        bbox_default = content_bbox(default, 300, 0, 398, 56)
        bbox_bigger = content_bbox(bigger, 300, 0, 398, 56)
        assert bbox_default is not None
        assert bbox_bigger is not None
        assert (bbox_bigger[3] - bbox_bigger[1]) > (
            bbox_default[3] - bbox_default[1]
        )

    def test_entities_fonts_value_weight_bold(self) -> None:
        # fonts.value.weight="bold" renders the row value in bold.
        widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 80,
            "entities": ["sensor.temperature"],
            "fonts": {"value": {"weight": "bold"}},
        }
        svg = render_widget_svg(widget, self._config())
        assert 'font-weight="bold"' in svg

    def test_entities_section_font_size_override(self) -> None:
        # fonts.section.size enlarges the standalone section-row label
        # glyphs relative to the derived default size.
        widget = {
            "type": "entities",
            "x": 0,
            "y": 0,
            "w": 400,
            "entities": [
                {"type": "section", "label": "Climate"},
                "sensor.temperature",
            ],
        }
        default = render_to_image([widget], self._config())
        bigger = render_to_image(
            [{**widget, "fonts": {"section": {"size": 40}}}],
            self._config(),
        )
        # The section row occupies the top band (section_h ≈ 34 px);
        # only its gray label renders there.
        bbox_default = content_bbox(default, 0, 0, 300, 34)
        bbox_bigger = content_bbox(bigger, 0, 0, 300, 34)
        assert bbox_default is not None
        assert bbox_bigger is not None
        assert (bbox_bigger[3] - bbox_bigger[1]) > (
            bbox_default[3] - bbox_default[1]
        )

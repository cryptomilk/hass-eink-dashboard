from __future__ import annotations

import re
from typing import ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    DEFAULT_ROW_H,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from tests.helpers import (
    _icon_ring_region,
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    assert_vertically_centered,
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

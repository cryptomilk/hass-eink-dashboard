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
from custom_components.eink_dashboard.svg_render import (
    _card_insets,
    render_widget_svg,
)
from tests.helpers import (
    _right_icon_ring_region,
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    make_config,
    pixel,
    render_to_image,
)

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

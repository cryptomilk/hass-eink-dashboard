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

    def test_tile_hide_icon_suppresses_icon(self) -> None:
        # hide_icon=True must leave the icon ring area white (no gray
        # circle fill) and text must start near the left padding —
        # shifted left relative to the normal icon+gap column.
        # hide_state=True forces single-line text (primary centered at
        # cy=40) so ascenders stay below the ring region and do not
        # produce false positives.
        row_h = 80
        m = _compute_metrics(row_h)
        ring_x1, ring_y1, ring_x2, ring_y2 = _icon_ring_region(row_h, m)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": row_h,
                "entity": "binary_sensor.motion",
                "hide_icon": True,
                "hide_state": True,
            }
        ]
        img = render_to_image(widgets, self._config())
        # No gray fill in the icon ring (circle is suppressed).
        assert_all_white(img, ring_x1, ring_y1, ring_x2, ring_y2)
        # With hide_icon the icon column collapses, so text appears
        # starting near the left padding rather than after icon+gap.
        normal_text_x = m.padding + m.icon_dia + m.inner_gap
        assert_has_dark_pixels(img, m.padding, 0, normal_text_x, row_h)

    def test_tile_hide_icon_with_icon_style(self) -> None:
        # hide_icon=True must suppress the icon even when icon_style is
        # set explicitly (e.g. "filled") — the style flag must not
        # override the hide decision.
        row_h = 80
        m = _compute_metrics(row_h)
        ring_x1, ring_y1, ring_x2, ring_y2 = _icon_ring_region(row_h, m)
        widgets = [
            {
                "type": "tile",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": row_h,
                "entity": "binary_sensor.motion",
                "hide_icon": True,
                "hide_state": True,
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, ring_x1, ring_y1, ring_x2, ring_y2)

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
        # when hide_state is not set, in black (the value is the most
        # important element, so it gets the highest contrast).
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
        # Lower half of text area should have black (secondary) text.
        assert any(
            pixel(img, x, y) < 64
            for y in range(40, 75)
            for x in range(text_left, 300)
        ), "state value text should be black (< 64)"

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

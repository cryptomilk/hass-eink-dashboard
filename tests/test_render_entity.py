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
from typing import TYPE_CHECKING, ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    DEFAULT_ROW_H,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets._helpers import _card_insets
from custom_components.eink_dashboard.widgets.entity import (
    _build_entity_context,
)
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_no_gray_pixels,
    assert_scales_proportionally,
    content_bbox,
    make_config,
    render_to_image,
)

if TYPE_CHECKING:
    from PIL import Image

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
    # For invert_condition numeric_state tests.
    "sensor.count": {
        "state": "2",
        "attributes": {"friendly_name": "Count"},
    },
    # For invert_condition state_not tests.
    "sensor.status": {
        "state": "washing",
        "attributes": {"friendly_name": "Status"},
    },
}


def _band_bbox(
    img: Image.Image,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    low: int,
    high: int,
    *,
    min_pixels: int = 20,
) -> tuple[int, int, int, int] | None:
    """Return the bbox of pixels within [low, high] in a region.

    Unlike ``content_bbox`` (any non-white pixel), this isolates a
    specific tone band so gray name text can be distinguished from
    black value/unit text even when both appear in the same region.
    A minimum pixel count is required before trusting a match —
    anti-aliased edges of black text blend through every gray tone
    for a pixel or two, so a handful of stray hits within the band
    are noise, not genuine gray content.

    Args:
        img: A grayscale ("L" mode) PIL image.
        x1: Left edge of the region.
        y1: Top edge of the region.
        x2: Right edge of the region.
        y2: Bottom edge of the region.
        low: Lower bound (exclusive) of the tone band.
        high: Upper bound (exclusive) of the tone band.
        min_pixels: Minimum number of matching pixels required for
            the match to count as real content rather than
            anti-aliasing noise.

    Returns:
        (left, top, right, bottom) of matching content in absolute
        image coordinates, or None if fewer than ``min_pixels`` pixels
        in the region fall within the band.
    """
    crop = img.crop((x1, y1, x2, y2))
    mask = crop.point(lambda p: 255 if low < p < high else 0)
    if sum(1 for v in mask.get_flattened_data() if v == 255) < min_pixels:
        return None
    bbox = mask.getbbox()
    if bbox is None:
        return None
    return (x1 + bbox[0], y1 + bbox[1], x1 + bbox[2], y1 + bbox[3])


def _content_x_range(w: int, h: int) -> tuple[int, int]:
    """Left/right x-bounds of the text column right of the icon.

    Mirrors the geometry the new left-aligned Entity layout is
    expected to use: icon column at the left content edge, text
    column starting after the icon + inner gap.

    Args:
        w: Widget width in pixels.
        h: Widget height in pixels. Card framing (padding) derives
            from the full widget height, but the icon itself derives
            from a single-row-equivalent height (h // 2) so it stays
            proportionate to the value/unit/name text next to it.

    Returns:
        (text_x0, text_x1): left edge of the text column and right
        content edge of the widget.
    """
    m = _compute_metrics(h)
    m_icon = _compute_metrics(h // 2)
    x_off, r_inset, _ = _card_insets(m, "none", 16)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0
    text_x0 = x_off + lpad + m_icon.icon_dia + m_icon.inner_gap
    text_x1 = w - r_inset - rpad
    return text_x0, text_x1


class TestRenderEntity:
    # Verify rendering of the redesigned Entity widget: icon on the
    # left (vertically centered against the full widget height),
    # value+unit (both black) to the right of the icon, and the
    # entity name (gray, smaller) positioned above or below the
    # value+unit line per name_position/name_align.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 300,
        "states": MOCK_ENTITY_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # ── Structural tests ──────────────────────────────

    def test_entity_card_border(self) -> None:
        # Border style draws dark pixels on all four edges. Metrics
        # are now derived from the full widget height (no separate
        # header band).
        h = 112
        m = _compute_metrics(h)
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
        m = _compute_metrics(h)
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
    # Use h=224 for a large enough icon circle to measure the ring
    # region reliably. The icon is now left-aligned and vertically
    # centered against the full widget height.

    def _icon_ring(
        self, h: int, display_levels: int = 16
    ) -> tuple[int, int, int, int, int, int]:
        """Left-aligned icon ring region (icon moved to the left).

        The icon's diameter/border derive from a single-row-
        equivalent height (h // 2), matching the production
        geometry in ``_build_entity_context`` — the icon stays
        proportionate to the value/unit/name text next to it rather
        than scaling with the full (2-row-tall) widget height. Card
        padding (used for the icon's x position) still derives from
        the full height, since that's a property of the card frame,
        not the icon.
        """
        m = _compute_metrics(h)
        m_icon = _compute_metrics(h // 2)
        icon_r = m_icon.icon_dia // 2
        icon_stroke_w = (
            m_icon.border * 3 if display_levels <= 2 else m_icon.border
        )
        # Checks a window extending +-icon_r//2 from the circle's
        # horizontal center. The circle's own curve dips measurably
        # below the top by the edge of that window -- a geometric
        # property of the circle, independent of stroke width.
        # Compensate by extending the vertical inset by that dip
        # amount, plus half the actual stroke width, so the checked
        # band clears both the curve and the ring stroke.
        dx_max = icon_r // 2
        dip = icon_r - round((icon_r**2 - dx_max**2) ** 0.5)
        stroke_inset = dip + icon_stroke_w // 2 + 2
        # icon_cx uses the card's own padding (m), not m_icon --
        # the icon's *position* is a property of the card frame,
        # only its diameter/border derive from the row-equivalent
        # height. Inlined rather than delegating to the shared
        # _icon_ring_region() helper, which assumes a single metrics
        # object drives both position and size.
        icon_cx = m.padding + icon_r
        icon_cy = h // 2
        ring_y1 = icon_cy - icon_r + stroke_inset
        ring_y2 = icon_cy - m_icon.icon_inner // 2 - 1
        ring_x1 = icon_cx - icon_r // 2 + 3
        ring_x2 = icon_cx + icon_r // 2 - 3
        return icon_cx, icon_cy, ring_x1, ring_y1, ring_x2, ring_y2

    def test_entity_icon_circle_gray_fill_active(self) -> None:
        # An active entity (state "on") without explicit icon_style
        # draws a filled gray circle on the left. Check the ring area
        # above the icon glyph for gray fill pixels.
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
                # hide_name isolates the icon ring from the name
                # text, which would otherwise render in the same
                # left column and confound the gray-fill check.
                "hide_name": True,
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
                "hide_name": True,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_no_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
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
                "hide_name": True,
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
                "hide_name": True,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_no_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
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
                "hide_name": True,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_no_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_entity_2level_always_outlined(self) -> None:
        # On a 2-level display (display_levels=2), the auto-switch
        # forces "outlined" even for an active entity (state "on").
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h, display_levels=2)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
                "hide_name": True,
            }
        ]
        img = render_to_image(widgets, self._config(display_levels=2))
        assert_no_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_entity_hide_icon_suppresses_icon(self) -> None:
        # hide_icon=True must leave the icon ring area white —
        # no circle, no glyph, no letter fallback.
        h = 224
        _, _, ring_x1, ring_y1, ring_x2, ring_y2 = self._icon_ring(h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.no_class",
                "hide_icon": True,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, ring_x1, ring_y1, ring_x2, ring_y2)

    def test_entity_hide_icon_with_icon_style(self) -> None:
        # hide_icon=True must suppress the icon even when icon_style is
        # set explicitly (e.g. "filled") — the style flag must not
        # override the hide decision.
        h = 224
        _, _, ring_x1, ring_y1, ring_x2, ring_y2 = self._icon_ring(h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.no_class",
                "hide_icon": True,
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, ring_x1, ring_y1, ring_x2, ring_y2)

    def test_entity_hide_icon_collapses_column(self) -> None:
        # hide_icon=True must shift value/unit text left to the
        # content edge, closing the gap normally reserved for the
        # icon column.
        h = 224
        m = _compute_metrics(h)
        widgets_normal = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        widgets_hidden = [{**widgets_normal[0], "hide_icon": True}]
        img_n = render_to_image(widgets_normal, self._config())
        img_h = render_to_image(widgets_hidden, self._config())
        bbox_n = _band_bbox(img_n, 0, 0, 400, h, 0, 60)
        bbox_h = _band_bbox(img_h, 0, 0, 400, h, 0, 60)
        assert bbox_n is not None
        assert bbox_h is not None
        assert bbox_h[0] < bbox_n[0], (
            "value must start further left when the icon is hidden"
        )
        # +3 tolerates anti-aliased glyph edge slop at the left
        # boundary of the value text.
        assert bbox_h[0] <= m.padding + 3, (
            "value must start near the left content edge when the "
            "icon column is collapsed"
        )

    def test_entity_hide_name_omits_name_entirely(self) -> None:
        # hide_name=True must omit the name text everywhere in the
        # text column, while the value keeps rendering.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "hide_name": True,
            }
        ]
        img = render_to_image(widgets, self._config())
        # min_pixels is raised well above the default: black value
        # text anti-aliases through the entire 0-255 range at its
        # edges, so a handful of those edge pixels can land inside
        # the gray band by chance. A high threshold ensures only
        # genuine gray (name) content trips this assertion.
        assert (
            _band_bbox(img, text_x0, 0, text_x1, h, 100, 140, min_pixels=200)
            is None
        ), "no gray (name) content should render when hide_name=True"
        assert _band_bbox(img, text_x0, 0, text_x1, h, 0, 60) is not None, (
            "value must still render when hide_name=True"
        )

    def test_entity_hide_name_icon_still_visible(self) -> None:
        # hide_name=True must not affect icon rendering — the icon
        # circle keeps drawing on the left.
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
                "hide_name": True,
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

    # ── Content tests ─────────────────────────────────

    def test_entity_draws_name_and_value(self) -> None:
        # Value (black) and name (gray) both render in the text
        # column right of the icon.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
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
        assert _band_bbox(img, text_x0, 0, text_x1, h, 0, 60) is not None, (
            "value should render in black"
        )
        assert _band_bbox(img, text_x0, 0, text_x1, h, 100, 140) is not None, (
            "name should render in gray"
        )

    def test_entity_value_font_larger_than_name(self) -> None:
        # The state value is the element users scan for at a
        # glance, so it must render in a larger font than the
        # entity name -- compare rendered glyph heights.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
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
        value_bbox = _band_bbox(img, text_x0, 0, text_x1, h, 0, 60)
        assert value_bbox is not None
        # Search for the name band strictly below the value's own
        # bounding box, skipping one extra row. Black text
        # anti-aliases through every gray tone along its own outline
        # (not just its edges), so searching starting exactly at the
        # value's bottom edge picks up stray gray-band hits from the
        # value glyph itself; the +1 margin clears that row and
        # isolates genuine name content instead.
        name_bbox = _band_bbox(
            img, text_x0, value_bbox[3] + 1, text_x1, h, 100, 140
        )
        assert name_bbox is not None
        value_h = value_bbox[3] - value_bbox[1]
        name_h = name_bbox[3] - name_bbox[1]
        assert value_h > name_h

    def test_entity_bold_value_renders_bold_weight(self) -> None:
        # bold_value=True renders the state value with a bold
        # font-weight attribute in the SVG.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
            "bold_value": True,
        }
        svg = render_widget_svg(widget, self._config())
        assert 'font-weight="bold"' in svg

    def test_entity_default_value_not_bold(self) -> None:
        # Without bold_value, the state value has no bold
        # font-weight attribute.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(widget, self._config())
        assert 'font-weight="bold"' not in svg

    def test_entity_name_font_floor_at_compact_h(self) -> None:
        # At compact widget heights the name font size must not
        # drop below the 10px legibility floor.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 60,
            "entity": "sensor.temperature",
        }
        ctx = _build_entity_context(widget, self._config())
        assert ctx["name_font_sz"] >= 10

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

    def test_entity_unit_positioned_right_of_value(self) -> None:
        # The unit extends the black value+unit block further right
        # than the value renders alone — proving the unit is placed
        # immediately after the value, not elsewhere.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h,
            "entity": "sensor.temperature",
        }
        states_no_unit = {
            **MOCK_ENTITY_STATES,
            "sensor.temperature": {
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                },
            },
        }
        img_with = render_to_image([base], self._config())
        img_without = render_to_image(
            [base], self._config(states=states_no_unit)
        )
        bbox_with = _band_bbox(img_with, text_x0, 0, text_x1, h, 0, 60)
        bbox_without = _band_bbox(img_without, text_x0, 0, text_x1, h, 0, 60)
        assert bbox_with is not None
        assert bbox_without is not None
        assert bbox_with[2] > bbox_without[2], (
            "unit text should extend the value+unit block to the right"
        )
        # ±2 tolerates sub-pixel rounding differences between the
        # two independently rendered images.
        assert abs(bbox_with[0] - bbox_without[0]) <= 2, (
            "value should start at the same x with or without a unit"
        )

    def test_entity_unit_renders_black_not_gray(self) -> None:
        # Unit must render black (like the value), not gray. Push the
        # name to the top so the lower half of the text column
        # contains only value+unit, then confirm no gray pixels
        # appear there.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "name_position": "top",
            }
        ]
        img = render_to_image(widgets, self._config())
        lower = (text_x0, h // 2, text_x1, h)
        # min_pixels is raised well above the default: black
        # value+unit text anti-aliases through the entire 0-255
        # range at its edges, so a handful of those edge pixels can
        # land inside the gray band by chance. A high threshold
        # ensures only genuine gray content trips this assertion.
        assert _band_bbox(img, *lower, 100, 140, min_pixels=200) is None, (
            "value+unit row must contain no gray pixels"
        )
        assert _band_bbox(img, *lower, 0, 60) is not None, (
            "value+unit row must contain black pixels"
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
        # crashing; value text still appears in the text column.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
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
        assert_has_dark_pixels(img, text_x0, 0, text_x1, h, threshold=140)

    def test_entity_no_device_class_letter_fallback(self) -> None:
        # An entity without device_class renders a letter fallback in
        # the icon area on the left side of the widget.
        h = 224
        m = _compute_metrics(h)
        x1 = m.padding
        x2 = m.padding + m.icon_dia
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.no_class",
                "hide_name": True,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, x1, 0, x2, h, threshold=200)

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

    def test_entity_icon_vertically_centered_in_widget(self) -> None:
        # The icon is vertically centered against the full widget
        # height, not a header sub-band.
        h = 224
        m = _compute_metrics(h)
        x1 = m.padding
        x2 = m.padding + m.icon_dia
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
        bbox = content_bbox(img, x1, 0, x2, h)
        assert bbox is not None
        center = (bbox[1] + bbox[3]) / 2
        # ±4 tolerates font-hinting vertical offset in the glyph
        # bounding box relative to the true geometric center.
        assert abs(center - h / 2) <= 4, (
            f"icon vertical center {center:.1f} not centered on h/2={h / 2}"
        )

    def test_entity_value_right_of_icon(self) -> None:
        # The value renders in the text column to the right of the
        # icon column.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
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
        assert _band_bbox(img, text_x0, 0, text_x1, h, 0, 60) is not None, (
            "value must render right of the icon column"
        )

    def test_entity_name_align_left_default(self) -> None:
        # Without name_align, the name is left-aligned near the
        # start of the text column.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
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
        name_bbox = _band_bbox(img, text_x0, 0, text_x1, h, 100, 140)
        assert name_bbox is not None
        # +5 tolerates anti-aliased glyph edge slop at the start of
        # the name text.
        assert name_bbox[0] <= text_x0 + 5, (
            "name should be left-aligned by default"
        )

    def test_entity_name_align_right(self) -> None:
        # name_align="right" right-aligns the name near the widget's
        # right content edge.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
        widgets = [
            {
                "type": "entity",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "name_align": "right",
            }
        ]
        img = render_to_image(widgets, self._config())
        name_bbox = _band_bbox(img, text_x0, 0, text_x1, h, 100, 140)
        assert name_bbox is not None
        # -5 tolerates anti-aliased glyph edge slop at the end of
        # the name text.
        assert name_bbox[2] >= text_x1 - 5, (
            "name_align='right' should right-align the name"
        )

    def test_entity_name_position_bottom_is_default(self) -> None:
        # Omitting name_position must produce byte-identical output
        # to name_position="bottom".
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        explicit_render = render_dashboard(
            [{**base, "name_position": "bottom"}], self._config()
        )
        assert default_render == explicit_render

    def test_entity_name_position_top_moves_name_above_value(self) -> None:
        # name_position="top" renders the name higher up (smaller y)
        # than the default "bottom" placement.
        h = 224
        text_x0, text_x1 = _content_x_range(400, h)
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h,
            "entity": "sensor.temperature",
        }
        img_bottom = render_to_image([base], self._config())
        img_top = render_to_image(
            [{**base, "name_position": "top"}], self._config()
        )
        name_bottom = _band_bbox(img_bottom, text_x0, 0, text_x1, h, 100, 140)
        name_top = _band_bbox(img_top, text_x0, 0, text_x1, h, 100, 140)
        assert name_bottom is not None
        assert name_top is not None
        assert name_top[1] < name_bottom[1], (
            "name_position='top' should render the name higher than "
            "the default bottom placement"
        )

    # ── Invert condition tests ────────────────────────

    def test_entity_invert_condition_met(self) -> None:
        # A state condition that matches the entity's current state
        # inverts the widget: context has invert=True and the SVG
        # gains a full-size black background rect plus white text.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "binary_sensor.motion",
            "invert_condition": [
                {
                    "condition": "state",
                    "entity": "binary_sensor.motion",
                    "state": "on",
                }
            ],
        }
        ctx = _build_entity_context(widget, self._config())
        assert ctx["invert"] is True
        svg = render_widget_svg(widget, self._config())
        assert re.search(
            r'<rect x="0" y="0" width="400" height="224"\s*'
            r'rx="\d+" ry="\d+"\s*fill="#000000"/>',
            svg,
        ), "inverted entity must draw a full-size black background rect"
        assert 'fill="#ffffff"' in svg, (
            "inverted entity must render text/icon in white"
        )

    def test_entity_invert_condition_not_met(self) -> None:
        # A state condition that does not match leaves the widget
        # un-inverted: no black background, white canvas outside
        # content.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "binary_sensor.front_door",
            "invert_condition": [
                {
                    "condition": "state",
                    "entity": "binary_sensor.front_door",
                    "state": "on",
                }
            ],
        }
        ctx = _build_entity_context(widget, self._config())
        assert ctx["invert"] is False
        img = render_to_image([widget], self._config())
        assert_all_white(img, 0, 0, 3, 3)

    def test_entity_invert_condition_absent(self) -> None:
        # Omitting invert_condition entirely never inverts the widget.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "binary_sensor.motion",
        }
        ctx = _build_entity_context(widget, self._config())
        assert ctx["invert"] is False

    def test_entity_invert_condition_empty_list(self) -> None:
        # invert_condition=[] must never invert, even though
        # check_conditions([]) alone would return True — the widget
        # must special-case emptiness.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "binary_sensor.motion",
            "invert_condition": [],
        }
        ctx = _build_entity_context(widget, self._config())
        assert ctx["invert"] is False

    def test_entity_invert_forces_no_circle_icon(self) -> None:
        # An active entity normally draws a filled icon circle
        # (<circle> element).  When inverted, the icon style is
        # forced to no-circle so the glyph draws directly on the
        # black background.
        base = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "binary_sensor.motion",
        }
        normal_svg = render_widget_svg(base, self._config())
        assert "<circle" in normal_svg, (
            "sanity check: active entity normally draws an icon circle"
        )
        inverted = {
            **base,
            "invert_condition": [
                {
                    "condition": "state",
                    "entity": "binary_sensor.motion",
                    "state": "on",
                }
            ],
        }
        ctx = _build_entity_context(inverted, self._config())
        assert ctx["icon_no_circle"] is True
        assert ctx["icon_outline"] is False
        inverted_svg = render_widget_svg(inverted, self._config())
        assert "<circle" not in inverted_svg, (
            "inverted entity must suppress the icon circle entirely"
        )

    def test_entity_invert_with_border_uses_white_stroke(self) -> None:
        # When inverted, the card border stroke must switch to white
        # so it stays visible against the solid black card
        # background — a black stroke would vanish against the
        # black fill.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "binary_sensor.motion",
            "card_style": "border",
            "invert_condition": [
                {
                    "condition": "state",
                    "entity": "binary_sensor.motion",
                    "state": "on",
                }
            ],
        }
        svg = render_widget_svg(widget, self._config())
        assert 'stroke="#ffffff"' in svg, (
            "inverted entity with card_style=border must render a "
            "white border stroke, not a black one that vanishes "
            "against the black card background"
        )

    def test_entity_invert_numeric_state_condition(self) -> None:
        # A numeric_state condition (above: 0) inverts when the
        # entity's state is a positive number.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "sensor.count",
            "invert_condition": [
                {
                    "condition": "numeric_state",
                    "entity": "sensor.count",
                    "above": 0,
                }
            ],
        }
        ctx = _build_entity_context(widget, self._config())
        assert ctx["invert"] is True

    def test_entity_invert_numeric_state_condition_zero(self) -> None:
        # numeric_state above=0 does not invert when the state is 0
        # (the exclusive lower bound is not satisfied).
        states = {
            **MOCK_ENTITY_STATES,
            "sensor.count": {
                "state": "0",
                "attributes": {"friendly_name": "Count"},
            },
        }
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "sensor.count",
            "invert_condition": [
                {
                    "condition": "numeric_state",
                    "entity": "sensor.count",
                    "above": 0,
                }
            ],
        }
        ctx = _build_entity_context(widget, self._config(states=states))
        assert ctx["invert"] is False

    def test_entity_invert_numeric_state_condition_non_numeric(
        self,
    ) -> None:
        # numeric_state above=0 does not invert on a non-numeric
        # state such as "unknown".
        states = {
            **MOCK_ENTITY_STATES,
            "sensor.count": {
                "state": "unknown",
                "attributes": {"friendly_name": "Count"},
            },
        }
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "sensor.count",
            "invert_condition": [
                {
                    "condition": "numeric_state",
                    "entity": "sensor.count",
                    "above": 0,
                }
            ],
        }
        ctx = _build_entity_context(widget, self._config(states=states))
        assert ctx["invert"] is False

    def test_entity_invert_state_not_condition(self) -> None:
        # state_not inverts when the entity holds a real value, not
        # one of the excluded placeholder states.
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "sensor.status",
            "invert_condition": [
                {
                    "condition": "state",
                    "entity": "sensor.status",
                    "state_not": ["", "unknown", "unavailable"],
                }
            ],
        }
        ctx = _build_entity_context(widget, self._config())
        assert ctx["invert"] is True

    def test_entity_invert_state_not_condition_excluded(self) -> None:
        # state_not does not invert for excluded placeholder states:
        # empty string, "unknown", and "unavailable".
        widget = {
            "type": "entity",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 224,
            "entity": "sensor.status",
            "invert_condition": [
                {
                    "condition": "state",
                    "entity": "sensor.status",
                    "state_not": ["", "unknown", "unavailable"],
                }
            ],
        }
        for excluded_state in ("", "unknown", "unavailable"):
            states = {
                **MOCK_ENTITY_STATES,
                "sensor.status": {
                    "state": excluded_state,
                    "attributes": {"friendly_name": "Status"},
                },
            }
            ctx = _build_entity_context(widget, self._config(states=states))
            assert ctx["invert"] is False, (
                f"state {excluded_state!r} must not invert"
            )

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

from __future__ import annotations

import re
from typing import ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    DEFAULT_ROW_H,
    PADDING,
)
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
    content_bbox,
    make_config,
    pixel,
    render_to_image,
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

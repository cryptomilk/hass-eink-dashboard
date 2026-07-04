from __future__ import annotations

import datetime as dt
import re
from typing import ClassVar
from unittest.mock import patch

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    DEFAULT_ROW_H,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    _format_relative_date,
    _parse_days_until,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from tests.helpers import (
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
            low=COLOR_LIGHT_GRAY - 20,
            high=COLOR_LIGHT_GRAY + 20,
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

    def test_waste_schedule_2level_icon_stroke_widened(self) -> None:
        # On a 2-level display icon circle stroke-width must be
        # 3× m.border to avoid dithering into dot patterns.
        # Use an entry with days >= 2 (Biotonne, 2 days) so the
        # icon renders as an outlined circle with a stroke-width.
        entries = [{"attribute": "Biotonne", "label": "Bio"}]
        m = _compute_metrics(DEFAULT_ROW_H)
        w = self._widget(entries=entries, h=DEFAULT_ROW_H)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config(grayscale_levels=2))
        expected_sw = m.border * 3
        assert f'stroke-width="{expected_sw}"' in svg, (
            f"2-level icon stroke-width should be {expected_sw}"
            f" (3 × m.border={m.border})"
        )

    def test_waste_schedule_2level_divider_stroke_widened(self) -> None:
        # On a 2-level display divider stroke-width must be
        # 3× m.divider to avoid dithering into dot patterns.
        m = _compute_metrics(DEFAULT_ROW_H)
        w = self._widget(h=3 * DEFAULT_ROW_H)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config(grayscale_levels=2))
        expected_sw = m.divider * 3
        assert f'stroke-width="{expected_sw}"' in svg, (
            f"2-level divider stroke-width should be {expected_sw}"
            f" (3 × m.divider={m.divider})"
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

    def test_urgency_tomorrow_date_black(self) -> None:
        # days=1: date text is black regardless of urgency — the
        # date is the value users scan for, so it always gets the
        # highest contrast. Urgency is conveyed by the icon instead.
        entries = [
            {"attribute": "Restmuell", "label": "Restmuell"},
        ]
        w = self._widget(entries=entries, h=56)
        # Restmuell = 2026-05-03; today = 2026-05-02 → days=1
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert any(
            pixel(img, x, y) < 64
            for y in range(0, 56)
            for x in range(300, 400)
        ), "days=1 date text should be black (< 64)"

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
        from tests.helpers import content_bbox

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

    # ── Bold value tests ───────────────────────────────

    def test_bold_value_list_layout(self) -> None:
        # bold_value=True renders the right-aligned date value
        # (list layout) with a bold font-weight attribute.
        w = self._widget(bold_value=True)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert 'font-weight="bold"' in svg

    def test_bold_value_card_layout(self) -> None:
        # bold_value=True renders the secondary date line (card
        # layout) with a bold font-weight attribute.
        w = self._widget(layout="card", bold_value=True)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert 'font-weight="bold"' in svg

    def test_default_value_not_bold(self) -> None:
        # Without bold_value, neither layout renders a bold value.
        w = self._widget()
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert 'font-weight="bold"' not in svg

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

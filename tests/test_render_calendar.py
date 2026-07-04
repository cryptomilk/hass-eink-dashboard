"""Tests for the calendar widget renderer."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, ClassVar
from unittest.mock import patch

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    DEFAULT_ROW_H,
    color_to_hex,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    _format_calendar_label,
    _is_event_now,
    _parse_calendar_dt,
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

_TODAY = dt.date(2026, 6, 11)
_TOMORROW = dt.date(2026, 6, 12)
_FUTURE = dt.date(2026, 6, 15)  # Monday, 4 days from _TODAY
_PATCH_NOW = "custom_components.eink_dashboard.render.date"

# End times are chosen so _is_event_now() always returns False
# during any real test run (events ended before the day began),
# giving deterministic "today but not now" = gray-filled icon.
MOCK_CALENDAR_STATES: dict[str, Any] = {
    "calendar.family": {
        "state": "off",
        "attributes": {
            "friendly_name": "Family Calendar",
            "events": [
                {
                    "start": "2026-06-12T10:00:00",
                    "end": "2026-06-12T11:00:00",
                    "summary": "Doctor Appointment",
                    "all_day": False,
                },
                {
                    "start": "2026-06-15T14:00:00",
                    "end": "2026-06-15T15:00:00",
                    "summary": "Team Meeting",
                    "all_day": False,
                },
            ],
        },
    },
    # today_cal: event today from 00:00–00:01 so is_now is always
    # False but start_date == today → gray-filled icon.
    "calendar.today_cal": {
        "state": "off",
        "attributes": {
            "friendly_name": "Today Calendar",
            "events": [
                {
                    "start": "2026-06-11T00:00:00",
                    "end": "2026-06-11T00:01:00",
                    "summary": "Morning Standup",
                    "all_day": False,
                },
            ],
        },
    },
    "calendar.allday_cal": {
        "state": "off",
        "attributes": {
            "friendly_name": "All-Day Calendar",
            "events": [
                {
                    "start": "2026-06-11",
                    "end": "2026-06-12",
                    "summary": "All Day Event",
                    "all_day": True,
                },
            ],
        },
    },
    "calendar.future_only": {
        "state": "off",
        "attributes": {
            "friendly_name": "Future Calendar",
            "events": [
                {
                    "start": "2026-06-15T14:00:00",
                    "end": "2026-06-15T15:00:00",
                    "summary": "Future Event",
                    "all_day": False,
                },
            ],
        },
    },
}


class TestCalendarHelpers:
    """Unit tests for calendar helper functions in render.py."""

    def test_parse_date_only(self) -> None:
        # All-day events use date-only strings; time part is None.
        d, hm = _parse_calendar_dt("2026-06-11")
        assert d == dt.date(2026, 6, 11)
        assert hm is None

    def test_parse_datetime_local(self) -> None:
        # Local datetime (no timezone) returns (date, (hour, minute)).
        d, hm = _parse_calendar_dt("2026-06-11T10:30:00")
        assert d == dt.date(2026, 6, 11)
        assert hm == (10, 30)

    def test_parse_datetime_with_tz_offset(self) -> None:
        # Timezone offset is stripped; local wall-clock values kept.
        d, hm = _parse_calendar_dt("2026-06-11T14:00:00+02:00")
        assert d == dt.date(2026, 6, 11)
        assert hm == (14, 0)

    def test_parse_datetime_space_separator(self) -> None:
        # HA sometimes uses a space instead of "T" as separator.
        d, hm = _parse_calendar_dt("2026-06-11 09:15:00")
        assert d == dt.date(2026, 6, 11)
        assert hm == (9, 15)

    def test_parse_invalid_falls_back_to_today(self) -> None:
        # An unparseable string falls back to date.today().
        d, hm = _parse_calendar_dt("unavailable")
        assert d == dt.date.today()
        assert hm is None

    def test_format_label_today_allday(self) -> None:
        # All-day event today formats as bare "Today".
        label = _format_calendar_label(
            "2026-06-11",
            all_day=True,
            today=dt.date(2026, 6, 11),
        )
        assert label == "Today"

    def test_format_label_today_timed(self) -> None:
        # Timed event today appends "HH:MM" in 24-hour format.
        label = _format_calendar_label(
            "2026-06-11T14:30:00",
            all_day=False,
            today=dt.date(2026, 6, 11),
        )
        assert label == "Today 14:30"

    def test_format_label_tomorrow_timed(self) -> None:
        # Tomorrow's timed event uses "Tomorrow HH:MM".
        label = _format_calendar_label(
            "2026-06-12T10:00:00",
            all_day=False,
            today=dt.date(2026, 6, 11),
        )
        assert label == "Tomorrow 10:00"

    def test_format_label_within_week(self) -> None:
        # 3 days from now uses a weekday abbreviation.
        # 2026-06-14 is a Sunday.
        label = _format_calendar_label(
            "2026-06-14T09:00:00",
            all_day=False,
            today=dt.date(2026, 6, 11),
        )
        assert label == "Sun 9:00"

    def test_format_label_beyond_week_timed(self) -> None:
        # Timed events 8+ days out use "Mon DD HH:MM".
        label = _format_calendar_label(
            "2026-06-22T09:00:00",
            all_day=False,
            today=dt.date(2026, 6, 11),
        )
        assert label == "Jun 22 9:00"

    def test_format_label_beyond_week_allday(self) -> None:
        # All-day events 8+ days out use bare "Mon DD" (no time).
        label = _format_calendar_label(
            "2026-06-22",
            all_day=True,
            today=dt.date(2026, 6, 11),
        )
        assert label == "Jun 22"

    def test_format_label_12hour(self) -> None:
        # 12-hour mode appends AM/PM.
        label = _format_calendar_label(
            "2026-06-12T14:30:00",
            all_day=False,
            today=dt.date(2026, 6, 11),
            time_format="12",
        )
        assert label == "Tomorrow 2:30 PM"

    def test_format_label_midnight(self) -> None:
        # Midnight formats as 0:00 in 24-hour mode.
        label = _format_calendar_label(
            "2026-06-12T00:00:00",
            all_day=False,
            today=dt.date(2026, 6, 11),
        )
        assert label == "Tomorrow 0:00"

    def test_is_event_now_timed_during(self) -> None:
        # A timed event is "now" when current time is within its window.
        now = dt.datetime(2026, 6, 11, 10, 30)
        assert _is_event_now("2026-06-11T10:00:00", "2026-06-11T11:00:00", now)

    def test_is_event_not_now_after(self) -> None:
        # An event that already ended is not "now".
        now = dt.datetime(2026, 6, 11, 12, 0)
        assert not _is_event_now(
            "2026-06-11T10:00:00", "2026-06-11T11:00:00", now
        )

    def test_is_event_not_now_before(self) -> None:
        # An event that hasn't started is not "now".
        now = dt.datetime(2026, 6, 11, 9, 0)
        assert not _is_event_now(
            "2026-06-11T10:00:00", "2026-06-11T11:00:00", now
        )

    def test_is_allday_event_now(self) -> None:
        # All-day event is "now" when today falls within [start, end).
        now = dt.datetime(2026, 6, 11, 15, 0)
        assert _is_event_now("2026-06-11", "2026-06-12", now)

    def test_is_allday_event_not_now_next_day(self) -> None:
        # All-day event is not "now" the day after it ends.
        now = dt.datetime(2026, 6, 12, 8, 0)
        assert not _is_event_now("2026-06-11", "2026-06-12", now)


class TestRenderCalendar:
    """Verify rendering of calendar widgets."""

    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 300,
        "grayscale_levels": 16,
        "time_format": "24",
        "states": MOCK_CALENDAR_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        """Build a display config with optional overrides."""
        return make_config(self._DEFAULTS, **overrides)

    def _widget(self, **overrides: object) -> dict[str, object]:
        """Build a calendar widget config with sensible defaults."""
        base: dict[str, object] = {
            "type": "calendar",
            "entity": "calendar.family",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
        }
        base.update(overrides)
        return base

    # ── Structural tests ──────────────────────────────

    def test_calendar_draws_event_content(self) -> None:
        # Dark pixels appear in the widget area when events are present.
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([self._widget()], self._config())
        assert_has_dark_pixels(img, 0, 0, 400, 112)

    def test_calendar_12h_time_format(self) -> None:
        # time_format="12" in the display config is forwarded to event
        # labels; the widget renders successfully and produces content.
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image(
                [self._widget()], self._config(time_format="12")
            )
        assert_has_dark_pixels(img, 0, 0, 400, 112)

    def test_calendar_no_entity_white(self) -> None:
        # Missing entity produces blank output without crashing.
        w = self._widget(entity="calendar.nonexistent")
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_all_white(img, 0, 0, 400, 300)

    def test_calendar_no_events_white(self) -> None:
        # Empty events list produces blank output.
        states: dict[str, Any] = {
            "calendar.empty": {
                "state": "off",
                "attributes": {
                    "friendly_name": "Empty",
                    "events": [],
                },
            }
        }
        w = self._widget(entity="calendar.empty", h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config(states=states))
        assert_all_white(img, 0, 0, 400, 300)

    def test_calendar_card_border(self) -> None:
        # card_style="border" draws dark pixels on all four edges.
        h = 112
        row_h = h // 2
        m = _compute_metrics(row_h)
        w = self._widget(h=h, card_style="border")
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_card_border(img, 400, h, m)

    def test_calendar_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to "none".
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            with_none = render_dashboard(
                [self._widget(card_style="none")], self._config()
            )
            without = render_dashboard([self._widget()], self._config())
        assert with_none == without

    def test_calendar_card_left_bar(self) -> None:
        # card_style="left_bar" draws a gray bar along the left edge.
        h = 56
        m = _compute_metrics(h)
        w = self._widget(
            entity="calendar.future_only",
            h=h,
            card_style="left_bar",
        )
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar + 2,
            h - 2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_calendar_divider_between_rows(self) -> None:
        # Multiple events produce a light-gray divider at the row boundary.
        h = 112
        row_h = h // 2
        m = _compute_metrics(row_h)
        w = self._widget(h=h, max_events=2)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_has_gray_pixels(
            img,
            m.padding + 10,
            row_h - m.divider,
            380,
            row_h + m.divider + 1,
            low=COLOR_LIGHT_GRAY - 20,
            high=COLOR_LIGHT_GRAY + 20,
        )

    def test_calendar_no_divider_single_event(self) -> None:
        # Single event widget has no divider below the row.
        h = 56
        w = self._widget(entity="calendar.future_only", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_all_white(img, 0, h + 1, 400, h + 4)

    def test_calendar_icon_present(self) -> None:
        # Calendar icon (dark pixels) appears in the icon area.
        h = 56
        m = _compute_metrics(h)
        w = self._widget(entity="calendar.future_only", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_has_dark_pixels(img, m.padding, 0, m.padding + m.icon_dia, h)

    # ── Alignment tests ───────────────────────────────

    def test_calendar_icon_vertically_centered(self) -> None:
        # Icon circle is vertically centered with the primary text.
        h = 56
        m = _compute_metrics(h)
        w = self._widget(entity="calendar.future_only", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        icon_region = (m.padding, 0, m.padding + m.icon_dia, h)
        text_x = m.padding + m.icon_dia + m.inner_gap
        text_region = (text_x, 0, 380, h)
        assert_vertically_centered(
            img, icon_region, text_region, tolerance=3.0
        )

    # ── Scaling tests ─────────────────────────────────

    def test_calendar_scales_proportionally(self) -> None:
        # Doubling h doubles the icon bounding box height.
        m_small = _compute_metrics(56)
        m_large = _compute_metrics(112)
        w_small = self._widget(entity="calendar.future_only", h=56)
        w_large = self._widget(entity="calendar.future_only", h=112)
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

    # ── Auto-sizing tests ─────────────────────────────

    def test_calendar_auto_height_single_event(self) -> None:
        # Without explicit h and one event, height == DEFAULT_ROW_H.
        w = {
            "type": "calendar",
            "entity": "calendar.future_only",
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

    def test_calendar_auto_height_two_events(self) -> None:
        # Without explicit h and two events, height == 2 * DEFAULT_ROW_H.
        w = {
            "type": "calendar",
            "entity": "calendar.family",
            "x": 0,
            "y": 0,
            "w": 400,
            "max_events": 2,
        }
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 2 * DEFAULT_ROW_H

    def test_calendar_explicit_h_preserved(self) -> None:
        # An explicit h overrides auto-sizing regardless of event count.
        w = self._widget(h=200)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200

    # ── Content / data tests ──────────────────────────

    def test_calendar_max_events_limits_rows(self) -> None:
        # max_events=1 forces only one row despite two events available.
        w = {
            "type": "calendar",
            "entity": "calendar.family",
            "x": 0,
            "y": 0,
            "w": 400,
            "max_events": 1,
        }
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == DEFAULT_ROW_H

    def test_calendar_event_summary_in_svg(self) -> None:
        # Event summary text appears in the rendered SVG.
        w = self._widget(max_events=1)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert "Doctor Appointment" in svg

    def test_calendar_all_day_event_no_time(self) -> None:
        # All-day event label is "Today" with no colon-separated time.
        w = self._widget(entity="calendar.allday_cal", h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert "Today" in svg
        # Extract the 10 characters after "Today" and verify no ":"
        today_idx = svg.index("Today")
        after = svg[today_idx + len("Today") : today_idx + len("Today") + 10]
        assert ":" not in after

    def test_calendar_timed_event_shows_time(self) -> None:
        # Timed event label includes the start time in HH:MM format.
        w = self._widget(entity="calendar.future_only", h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        # Future event starts at 14:00.
        assert "14:00" in svg

    def test_calendar_title_shown(self) -> None:
        # When title is set, title text appears in the SVG output.
        w = self._widget(h=80, title="My Events")
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert "My Events" in svg

    def test_calendar_date_right_aligned(self) -> None:
        # Date/time label appears near the right edge of the widget.
        h = 56
        w = self._widget(entity="calendar.future_only", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_has_dark_pixels(img, 300, 0, 400, h, threshold=200)

    def test_calendar_value_text_black(self) -> None:
        # The right-aligned date/time value is rendered in black
        # (the value is the most important element, so it gets the
        # highest contrast).
        h = 56
        w = self._widget(entity="calendar.future_only", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert any(
            pixel(img, x, y) < 64 for y in range(0, h) for x in range(300, 400)
        ), "date value text should be black (< 64)"

    def test_calendar_name_text_gray(self) -> None:
        # The event summary (name) is rendered in gray, secondary
        # to the black date/time value.
        h = 56
        m = _compute_metrics(h)
        w = self._widget(entity="calendar.future_only", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        text_left = m.padding + m.icon_dia + m.inner_gap
        assert_has_gray_pixels(img, text_left, 0, 300, h)

    def test_calendar_bold_value_renders_bold_weight(self) -> None:
        # bold_value=True renders the date/time value with a bold
        # font-weight attribute in the SVG.
        w = self._widget(bold_value=True)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert 'font-weight="bold"' in svg

    def test_calendar_default_value_not_bold(self) -> None:
        # Without bold_value, the date/time value has no bold
        # font-weight attribute.
        w = self._widget()
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        assert 'font-weight="bold"' not in svg

    # ── Urgency / icon fill tests ─────────────────────

    def test_calendar_today_event_gray_filled_icon(self) -> None:
        # Today's event (not in progress) renders with a gray-filled
        # icon circle.  The SVG should contain the gray hex color on a
        # circle element.
        w = self._widget(entity="calendar.today_cal", h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        # Gray fill hex (#787878) must appear — used as icon_fill
        # on the filled-circle path in _macros.svg.j2.
        assert color_to_hex(COLOR_GRAY) in svg

    def test_calendar_future_event_outlined_icon(self) -> None:
        # Future event renders with an outlined circle (black stroke,
        # white fill).  The circle element has a stroke-width attribute.
        w = self._widget(entity="calendar.future_only", h=56)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config())
        # Outlined mode emits stroke and stroke-width on the circle.
        assert "stroke-width=" in svg

    def test_calendar_future_event_white_interior(self) -> None:
        # Outlined icon has a white interior (not filled with gray).
        h = 80
        m = _compute_metrics(h)
        w = self._widget(entity="calendar.future_only", h=h)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        ring_y = h // 2
        # The leftmost arc pixel should be the black stroke.
        assert pixel(img, m.padding, ring_y) < 64
        # Just inside the stroke, before the glyph: white fill.
        assert pixel(img, m.padding + m.border + 3, ring_y) > 200

    # ── 2-level display tests ─────────────────────────

    def test_calendar_2level_icon_stroke_widened(self) -> None:
        # On 2-level displays the icon circle stroke is 3× m.border.
        m = _compute_metrics(DEFAULT_ROW_H)
        w = self._widget(
            entity="calendar.future_only",
            h=DEFAULT_ROW_H,
        )
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config(grayscale_levels=2))
        expected = m.border * 3
        assert f'stroke-width="{expected}"' in svg, (
            f"2-level stroke-width should be {expected}"
            f" (3 × m.border={m.border})"
        )

    def test_calendar_2level_divider_stroke_widened(self) -> None:
        # On 2-level displays the row divider stroke is 3× m.divider.
        m = _compute_metrics(DEFAULT_ROW_H)
        w = self._widget(h=2 * DEFAULT_ROW_H, max_events=2)
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(w, self._config(grayscale_levels=2))
        expected = m.divider * 3
        assert f'stroke-width="{expected}"' in svg, (
            f"2-level divider stroke-width should be {expected}"
            f" (3 × m.divider={m.divider})"
        )

    def test_calendar_border_single_padding(self) -> None:
        # With card_style="border", card_container provides x_off=padding;
        # card_row must not add its own padding again.  The icon circle's
        # left arc should appear in the strip [m.padding, 2*m.padding].
        h = DEFAULT_ROW_H
        m = _compute_metrics(h)
        w = self._widget(
            entity="calendar.future_only",
            h=h,
            card_style="border",
        )
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            img = render_to_image([w], self._config())
        assert_has_dark_pixels(
            img,
            m.padding,
            0,
            2 * m.padding,
            h,
            threshold=200,
        )

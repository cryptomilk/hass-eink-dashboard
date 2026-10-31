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

"""Tests for the week calendar widget renderer."""

from __future__ import annotations

import datetime as dt
from typing import Any
from unittest.mock import patch

from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets.week_calendar import (
    _build_week_calendar_context,
    _first_weekday_index,
    _snap_gray,
)
from tests.helpers import (
    assert_all_white,
    assert_has_dark_pixels,
    render_to_image,
)

_NOW = "custom_components.eink_dashboard.widgets.week_calendar._now"
# Monday 2026-10-19, 10:15.
_MONDAY = dt.datetime(2026, 10, 19, 10, 15)


def _ev(start: str, end: str, summary: str) -> dict[str, str]:
    """Build a calendar event dict as returned by calendar.get_events."""
    return {"start": start, "end": end, "summary": summary}


def _config(events: list[dict[str, str]], **overrides: Any) -> dict[str, Any]:
    """Build a display config holding ``events`` for calendar.test."""
    cfg: dict[str, Any] = {
        "width": 758,
        "height": 480,
        "display_levels": 16,
        "time_format": "24",
        "language": "en",
        "first_weekday": "monday",
        "states": {
            "calendar.test": {
                "state": "off",
                "attributes": {"week_events": events},
            }
        },
    }
    cfg.update(overrides)
    return cfg


def _widget(**overrides: Any) -> dict[str, Any]:
    """Build a week calendar widget config."""
    base: dict[str, Any] = {
        "type": "week_calendar",
        "entity": "calendar.test",
        "x": 0,
        "y": 0,
        "w": 700,
        "h": 440,
    }
    base.update(overrides)
    return base


def _ctx(
    events: list[dict[str, str]],
    now: dt.datetime = _MONDAY,
    widget: dict[str, Any] | None = None,
    **cfg: Any,
) -> dict[str, Any]:
    """Build the template context with a patched clock."""
    with patch(_NOW, return_value=now):
        return _build_week_calendar_context(
            widget or _widget(), _config(events, **cfg)
        )


class TestFirstWeekday:
    """Resolving the first_weekday setting."""

    def test_explicit_name(self) -> None:
        # An explicit weekday name maps to its index.
        assert _first_weekday_index("sunday", "de") == 6

    def test_language_default(self) -> None:
        # "language" uses the locale's first day: Monday for German,
        # Sunday for US English.
        assert _first_weekday_index("language", "de") == 0
        assert _first_weekday_index("language", "en-US") == 6

    def test_unknown_language_falls_back_to_monday(self) -> None:
        # A malformed language tag must not raise.
        assert _first_weekday_index("language", "123") == 0


class TestGridlineGray:
    """Gridline grays snap to levels the display can show."""

    def test_four_level_display_snaps_to_real_levels(self) -> None:
        # On a 4-level display the levels are 0, 85, 170, 255, so
        # the grays move to 85 and 170 and stay solid after
        # dithering instead of turning into dots.
        assert _snap_gray(120, 4) == "#555555"
        assert _snap_gray(180, 4) == "#aaaaaa"

    def test_two_level_display_has_no_gray(self) -> None:
        # A black-and-white display can only draw black or white.
        assert _snap_gray(120, 2) == "#000000"

    def test_many_levels_keep_the_gray(self) -> None:
        # With 256 levels any gray is exact, so nothing changes.
        assert _snap_gray(120, 256) == "#787878"

    def test_hour_and_day_lines_share_one_color(self) -> None:
        # The hour lines and the vertical day separators use the same
        # snapped gray (the light gray level on a 4-level display).
        ctx = _ctx([], display_levels=4)
        assert ctx["grid_line_color"] == "#aaaaaa"
        assert "day_line_color" not in ctx


class TestWeekColumns:
    """Seven columns starting on the configured first weekday."""

    def test_seven_headers_start_monday(self) -> None:
        # Monday-first week: headers run Mon 19 … Sun 25.
        ctx = _ctx([])
        labels = [h["label"] for h in ctx["headers"]]
        assert len(labels) == 7
        assert labels[0].endswith("19")
        assert labels[-1].endswith("25")

    def test_sunday_first_week(self) -> None:
        # With Sunday first, Monday 19 Oct belongs to the week that
        # started on Sunday 18 Oct.
        ctx = _ctx([], first_weekday="sunday")
        labels = [h["label"] for h in ctx["headers"]]
        assert labels[0].endswith("18")
        assert labels[-1].endswith("24")

    def test_sunday_belongs_to_current_week(self) -> None:
        # On Sunday the week still shows Monday-to-Sunday containing
        # that day rather than jumping ahead.
        ctx = _ctx([], now=dt.datetime(2026, 10, 25, 20, 0))
        assert ctx["headers"][0]["label"].endswith("19")
        assert ctx["headers"][6]["is_today"] is True

    def test_german_weekday_names(self) -> None:
        # Day labels follow the display language.
        ctx = _ctx([], language="de")
        assert ctx["headers"][0]["label"].startswith("Mo")

    def test_today_header_flagged(self) -> None:
        # Only today's column is highlighted.
        ctx = _ctx([])
        flags = [h["is_today"] for h in ctx["headers"]]
        assert flags == [True, False, False, False, False, False, False]


class TestWeekEvents:
    """Event positioning inside the grid."""

    def test_event_position_scales_with_time(self) -> None:
        # A later event sits lower; a longer one is taller.
        ctx = _ctx(
            [
                _ev("2026-10-19T08:00:00", "2026-10-19T09:00:00", "Early"),
                _ev("2026-10-19T14:00:00", "2026-10-19T16:00:00", "Late"),
            ]
        )
        early, late = sorted(ctx["events"], key=lambda e: e["y"])
        assert late["y"] > early["y"]
        assert late["h"] > early["h"]

    def test_event_inside_grid_bounds(self) -> None:
        # In-grid events never extend past the grid.
        ctx = _ctx(
            [_ev("2026-10-19T19:00:00", "2026-10-19T21:30:00", "Evening")]
        )
        ev = ctx["events"][0]
        assert ev["y"] >= ctx["grid_top"]
        assert ev["y"] + ev["h"] <= ctx["grid_bottom"]

    def test_event_text_starts_with_time(self) -> None:
        # Every in-grid event, even a short one, carries its start
        # time on its first text line.
        ctx = _ctx(
            [
                _ev("2026-10-19T09:30:00", "2026-10-19T11:00:00", "Long"),
                _ev("2026-10-19T14:00:00", "2026-10-19T14:15:00", "Short"),
            ]
        )
        firsts = sorted((e["y"], e["lines"][0]["time"]) for e in ctx["events"])
        assert firsts[0][1] == "9:30"
        assert firsts[1][1] == "14:00"

    def test_event_text_uses_roboto_without_bold(self) -> None:
        # The start time is drawn at its fixed size and the title at
        # the event size, both in regular-weight Roboto with the
        # renderer's default text rendering, like the other widgets.
        events = [_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Solo")]
        with patch(_NOW, return_value=_MONDAY):
            svg = render_widget_svg(_widget(), _config(events))
        assert 'font-size="9">9:00</tspan> Solo</text>' in svg
        assert (
            'font-weight="400"\n  font-size="12"\n  dominant-baseline'
        ) in svg
        assert 'font-family="Roboto' in svg
        assert "text-rendering" not in svg
        assert 'font-weight="700"' not in svg

    def test_default_font_sizes(self) -> None:
        # Without overrides or scaling the text keeps its fixed sizes.
        ctx = _ctx([_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Gym")])
        assert ctx["time_font_sz"] == 9
        assert ctx["events"][0]["font_sz"] == 12
        assert ctx["day_weight"] == "500"
        assert ctx["event_weight"] == "400"

    def test_font_scale_scales_default_sizes(self) -> None:
        # The display-level font_scale multiplies every default size.
        ctx = _ctx(
            [_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Gym")],
            font_scale=1.5,
        )
        base = _ctx([_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Gym")])
        assert ctx["time_font_sz"] == 14
        assert ctx["events"][0]["font_sz"] == 18
        assert ctx["day_font"] > base["day_font"]
        assert ctx["hour_font"] > base["hour_font"]

    def test_font_roles_set_size_and_weight(self) -> None:
        # An explicit role size is absolute: font_scale does not apply.
        ctx = _ctx(
            [_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Gym")],
            widget=_widget(
                title="Week",
                fonts={
                    "title": {"size": 20},
                    "day": {"size": 12, "weight": "bold"},
                    "hour": {"size": 9},
                    "time": {"size": 8},
                    "event": {"size": 11, "weight": "medium"},
                },
            ),
            font_scale=2.0,
        )
        assert ctx["title_font_sz"] == 20
        assert ctx["day_font"] == 12
        assert ctx["day_weight"] == "bold"
        assert ctx["hour_font"] == 9
        assert ctx["time_font_sz"] == 8
        assert ctx["event_weight"] == "500"
        assert ctx["events"][0]["font_sz"] == 11

    def test_invalid_event_size_uses_default(self) -> None:
        # A non-numeric size is ignored, so the default size applies.
        ctx = _ctx(
            [_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Gym")],
            widget=_widget(fonts={"event": {"size": "abc"}}),
        )
        assert ctx["events"][0]["font_sz"] == 12

    def test_header_grows_with_day_font(self) -> None:
        # A day font larger than the header leaves room for itself.
        ctx = _ctx([], widget=_widget(fonts={"day": {"size": 30}}))
        assert ctx["header_h"] >= 36

    def test_cut_text_ends_in_ellipsis(self) -> None:
        # A title that does not fit the box is cut with an ellipsis.
        long_title = "Quarterly planning workshop with the whole team"
        events = [
            _ev("2026-10-19T09:00:00", "2026-10-19T09:30:00", long_title)
        ]
        ctx = _ctx(events)
        texts = [ln["text"] for ln in ctx["events"][0]["lines"]]
        assert any(t.endswith("…") for t in texts)

    def test_close_short_events_do_not_collide(self) -> None:
        # Two 10 minute events 5 minutes apart do not overlap in time
        # but their minimum-height boxes would; they must not be
        # drawn on top of each other.
        ctx = _ctx(
            [
                _ev("2026-10-19T10:00:00", "2026-10-19T10:10:00", "A"),
                _ev("2026-10-19T10:15:00", "2026-10-19T10:25:00", "B"),
            ]
        )
        a, b = ctx["events"]
        apart_x = (
            a["x"] + a["w"] <= b["x"] + 1 or b["x"] + b["w"] <= a["x"] + 1
        )
        apart_y = a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
        assert apart_x or apart_y

    def test_overlapping_short_events_fit_two_lines(self) -> None:
        # Overlapping 30 minute events are drawn tall enough for two
        # text lines, so even in a narrow column the time sits on
        # one line and the title on the next instead of being lost.
        titles = ["One", "Two", "Six"]
        ctx = _ctx(
            [
                _ev("2026-10-19T15:00:00", "2026-10-19T15:30:00", t)
                for t in titles
            ]
        )
        assert len(ctx["events"]) == 3
        for ev in ctx["events"]:
            assert ev["h"] >= 2 * 12 + 2
            text = " ".join(ln["text"] for ln in ev["lines"])
            assert any(t in text for t in titles)

    def test_boxes_sit_on_gridlines(self) -> None:
        # A lone event starts on a vertical gridline and ends one
        # pixel before the next one.
        ctx = _ctx([_ev("2026-10-21T10:00:00", "2026-10-21T11:00:00", "Wed")])
        ev = ctx["events"][0]
        assert ev["x"] == ctx["col_xs"][2]
        assert ev["x"] + ev["w"] == ctx["col_xs"][3] - 1

    def test_event_lands_in_its_column(self) -> None:
        # A Wednesday event is placed inside Wednesday's column.
        ctx = _ctx([_ev("2026-10-21T10:00:00", "2026-10-21T11:00:00", "Wed")])
        ev = ctx["events"][0]
        assert ctx["col_xs"][2] <= ev["x"] < ctx["col_xs"][3]

    def test_overlapping_events_share_column(self) -> None:
        # Two overlapping events sit side by side at half width.
        ctx = _ctx(
            [
                _ev("2026-10-19T09:00:00", "2026-10-19T10:30:00", "A"),
                _ev("2026-10-19T10:00:00", "2026-10-19T11:00:00", "B"),
            ]
        )
        a, b = sorted(ctx["events"], key=lambda e: e["x"])
        # Neighbours are separated by a one pixel gap.
        assert a["x"] + a["w"] == b["x"] - 1
        col_w = ctx["col_xs"][1] - ctx["col_xs"][0]
        assert a["w"] < col_w * 0.6

    def test_events_before_and_after_become_chips(self) -> None:
        # Events fully outside 8:00–20:00 are stacked as chips and
        # are not drawn in the grid.
        ctx = _ctx(
            [
                _ev("2026-10-19T05:00:00", "2026-10-19T05:30:00", "Run"),
                _ev("2026-10-19T22:30:00", "2026-10-19T23:30:00", "Call"),
            ]
        )
        assert ctx["events"] == []
        assert len(ctx["chips"]) == 2
        top, bottom = sorted(ctx["chips"], key=lambda c: c["y"])
        assert top["y"] < ctx["grid_top"]
        assert bottom["y"] >= ctx["grid_bottom"]

    def test_event_crossing_grid_start_is_clipped(self) -> None:
        # An event running 7:00–9:00 is drawn from the grid start.
        ctx = _ctx([_ev("2026-10-19T07:00:00", "2026-10-19T09:00:00", "Fly")])
        assert ctx["chips"] == []
        assert ctx["events"][0]["y"] == ctx["grid_top"]

    def test_overnight_event_splits_across_days(self) -> None:
        # A 23:00–07:00 event shows as a chip on day one and an
        # in-grid segment on day two.
        ctx = _ctx([_ev("2026-10-19T23:00:00", "2026-10-20T09:00:00", "Nite")])
        assert len(ctx["chips"]) == 1
        assert len(ctx["events"]) == 1
        assert ctx["events"][0]["x"] >= ctx["col_xs"][1]

    def test_overnight_continuation_shows_real_start(self) -> None:
        # The next-day part of a 23:00 event is labelled 23:00, not
        # the 0:00 midnight cut.
        ctx = _ctx([_ev("2026-10-19T23:00:00", "2026-10-20T09:00:00", "Nite")])
        assert ctx["events"][0]["lines"][0]["time"] == "23:00"

    def test_all_day_event_spans_days(self) -> None:
        # A three-day all-day event becomes one bar across the days
        # (end date is exclusive).
        ctx = _ctx([_ev("2026-10-21", "2026-10-24", "Trip")])
        assert len(ctx["all_day"]) == 1
        bar = ctx["all_day"][0]
        assert bar["x"] == ctx["col_xs"][2]
        assert bar["x"] + bar["w"] == ctx["col_xs"][5] - 1

    def test_events_outside_week_ignored(self) -> None:
        # Events from other weeks do not appear.
        ctx = _ctx(
            [
                _ev("2026-10-12T10:00:00", "2026-10-12T11:00:00", "Last"),
                _ev("2026-10-26T10:00:00", "2026-10-26T11:00:00", "Next"),
            ]
        )
        assert ctx["events"] == []
        assert ctx["chips"] == []

    def test_custom_hour_range(self) -> None:
        # start_hour/end_hour change which events fall in the grid.
        ctx = _ctx(
            [_ev("2026-10-19T08:00:00", "2026-10-19T09:00:00", "X")],
            widget=_widget(start_hour=9, end_hour=18),
        )
        assert ctx["events"] == []
        assert len(ctx["chips"]) == 1

    def test_cleared_hours_use_defaults(self) -> None:
        # A cleared editor field arrives as "" or None and must not
        # abort the render; the default 8-20 axis applies instead.
        ctx = _ctx(
            [_ev("2026-10-19T10:00:00", "2026-10-19T11:00:00", "X")],
            widget=_widget(start_hour="", end_hour=None),
        )
        assert len(ctx["events"]) == 1
        assert ctx["chips"] == []

    def test_no_current_time_marker(self) -> None:
        # The display refreshes too rarely for a "now" line to be
        # accurate, so none is drawn.
        with patch(_NOW, return_value=_MONDAY):
            svg = render_widget_svg(_widget(), _config([]))
        assert "now_line" not in _ctx([])
        assert 'stroke-width="2"' not in svg

    def test_missing_entity_renders_empty_grid(self) -> None:
        # An unknown entity still yields a grid with no events.
        with patch(_NOW, return_value=_MONDAY):
            ctx = _build_week_calendar_context(
                _widget(entity="calendar.nope"), _config([])
            )
        assert ctx["events"] == []
        assert len(ctx["headers"]) == 7

    def test_multiple_calendars_are_merged(self) -> None:
        # Events from every listed calendar appear in one grid.
        cfg = _config([_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "A")])
        cfg["states"]["calendar.other"] = {
            "state": "off",
            "attributes": {
                "week_events": [
                    _ev("2026-10-20T09:00:00", "2026-10-20T10:00:00", "B")
                ]
            },
        }
        widget = _widget(entity=["calendar.test", "calendar.other"])
        with patch(_NOW, return_value=_MONDAY):
            ctx = _build_week_calendar_context(widget, cfg)
        assert len(ctx["events"]) == 2

    def test_size_scales_with_widget(self) -> None:
        # A bigger widget gives a taller grid and wider columns.
        small = _ctx([], widget=_widget(w=400, h=300))
        big = _ctx([], widget=_widget(w=700, h=440))
        assert big["grid_bottom"] - big["grid_top"] > (
            small["grid_bottom"] - small["grid_top"]
        )
        assert big["col_xs"][1] - big["col_xs"][0] > (
            small["col_xs"][1] - small["col_xs"][0]
        )


class TestRenderWeekCalendar:
    """End-to-end rendering."""

    def test_svg_renders(self) -> None:
        # The widget renders to a well-formed SVG of the given size.
        with patch(_NOW, return_value=_MONDAY):
            svg = render_widget_svg(
                _widget(),
                _config(
                    [_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Hi")]
                ),
            )
        assert svg.startswith("<svg")
        assert "Hi" in svg

    def test_draws_dark_pixels(self) -> None:
        # Today's inverted header produces dark pixels at the top.
        with patch(_NOW, return_value=_MONDAY):
            img = render_to_image([_widget()], _config([]))
        assert_has_dark_pixels(img, 40, 0, 110, 20)

    def test_outer_frame_is_black_on_every_side(self) -> None:
        # The widget's outermost pixel rows and columns are solid
        # black, including the left edge of the hour column.
        with patch(_NOW, return_value=_MONDAY):
            img = render_to_image([_widget(h=300)], _config([]))
        for x in range(0, 700):
            assert img.getpixel((x, 0)) == 0
            assert img.getpixel((x, 299)) == 0
        for y in range(0, 300):
            assert img.getpixel((0, y)) == 0
            assert img.getpixel((699, y)) == 0

    def test_events_are_black_with_white_text(self) -> None:
        # Event boxes are filled black and their text is white.
        with patch(_NOW, return_value=_MONDAY):
            svg = render_widget_svg(
                _widget(),
                _config(
                    [_ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "Hi")]
                ),
            )
        assert 'rx="' in svg
        assert 'stroke="#ffffff"' not in svg

    def test_first_hour_line_skipped_right_under_header(self) -> None:
        # Without all-day events or chips the first hour line would sit
        # right under the header border, so it is not drawn; with an
        # all-day strip above the grid it is.
        def dashed_lines(events: list[dict[str, str]]) -> int:
            with patch(_NOW, return_value=_MONDAY):
                svg = render_widget_svg(_widget(), _config(events))
            return svg.count("stroke-dasharray")

        hour_lines = 20 - 8 + 1
        assert dashed_lines([]) == hour_lines - 1
        assert dashed_lines([_ev("2026-10-19", "2026-10-20", "Day")]) == (
            hour_lines
        )

    def test_leaves_area_below_widget_white(self) -> None:
        # Nothing is drawn outside the widget's height.
        with patch(_NOW, return_value=_MONDAY):
            img = render_to_image([_widget(h=300)], _config([]))
        assert_all_white(img, 0, 320, 758, 480)


class TestMalformedEvents:
    """Bad calendar data is skipped instead of distorting the widget."""

    def test_unparseable_or_missing_bounds_are_skipped(self) -> None:
        # Empty, missing, null and garbled start/end values would
        # otherwise land on today; none of them draws anything.
        good = _ev("2026-10-20T09:00:00", "2026-10-20T10:00:00", "Good")
        ctx = _ctx(
            [
                _ev("", "2026-10-19T10:00:00", "Empty start"),
                {"start": "2026-10-19T09:00:00", "summary": "No end"},
                {"start": None, "end": None, "summary": "Null"},
                _ev("2026-10-19T09:00:00", "garbage", "Bad end"),
                _ev("2026-13-45", "2026-13-46", "Bad date"),
                good,
            ]
        )
        assert [len(e["lines"]) for e in ctx["events"]] == [1]
        assert ctx["all_day"] == []
        assert ctx["chips"] == []

    def test_non_dict_event_is_skipped(self) -> None:
        # A stray non-dict entry does not raise.
        ctx = _ctx(
            [
                "oops",
                None,
                _ev("2026-10-19T09:00:00", "2026-10-19T10:00:00", "A"),
            ]  # type: ignore[list-item]
        )
        assert len(ctx["events"]) == 1

    def test_non_list_week_events_is_empty(self) -> None:
        # None or a non-list value (a string, a dict) is treated as no
        # events instead of raising.
        for bad in (None, "x", {"a": 1}):
            ctx = _ctx(bad)  # type: ignore[arg-type]
            assert ctx["events"] == []

    def test_missing_attributes_is_empty(self) -> None:
        # A state without attributes renders an empty week.
        cfg = _config([])
        cfg["states"]["calendar.test"] = {"state": "off", "attributes": None}
        with patch(_NOW, return_value=_MONDAY):
            ctx = _build_week_calendar_context(_widget(), cfg)
        assert ctx["events"] == []


class TestAllDayOverflow:
    """All-day events that do not fit the strip are counted, not lost."""

    @staticmethod
    def _texts(ctx: dict[str, Any]) -> list[str]:
        return [ln["text"] for box in ctx["all_day"] for ln in box["lines"]]

    def test_three_lanes_show_everything(self) -> None:
        # Up to three overlapping all-day events fit, so no marker.
        ctx = _ctx(
            [_ev("2026-10-19", "2026-10-20", f"Day {i}") for i in range(3)]
        )
        assert len(ctx["all_day"]) == 3
        assert not any(t.startswith("+") for t in self._texts(ctx))

    def test_extra_all_day_events_become_a_count(self) -> None:
        # Five on one day: two bars stay and the last lane shows "+3"
        # for the three that no longer fit.
        ctx = _ctx(
            [_ev("2026-10-19", "2026-10-20", f"Day {i}") for i in range(5)]
        )
        assert len(ctx["all_day"]) == 3
        assert sorted(self._texts(ctx))[0] == "+3"
        assert ctx["grid_top"] == (
            ctx["content_y"]
            + ctx["header_h"]
            + 3 * ctx["all_day"][0]["h"]
            + 3 * 2
        )

    def test_hidden_multi_day_event_counts_on_every_day(self) -> None:
        # A hidden three-day event adds one to each day it covers.
        ctx = _ctx(
            [
                *(
                    _ev("2026-10-19", "2026-10-22", f"Long {i}")
                    for i in range(3)
                ),
                _ev("2026-10-19", "2026-10-22", "Hidden"),
            ]
        )
        markers = [t for t in self._texts(ctx) if t.startswith("+")]
        assert markers == ["+2", "+2", "+2"]


class TestAgendaLayout:
    """A short widget lists each day's events instead of a time grid."""

    _SHORT = 130

    @staticmethod
    def _day(ctx: dict[str, Any], i: int) -> list[str]:
        """Return the row texts of day column ``i``, top to bottom."""
        left, right = ctx["col_xs"][i], ctx["col_xs"][i + 1]
        rows = sorted(
            (b for b in ctx["events"] if left <= b["x"] < right),
            key=lambda b: b["y"],
        )
        return [
            f"{b['lines'][0]['time']} {b['lines'][0]['text']}".strip()
            for b in rows
        ]

    def test_layout_depends_on_size_only(self) -> None:
        # The same widget size gives the same layout whatever the
        # events are, so adding an event never flips the layout.
        busy = [_ev("2026-10-19", "2026-10-20", f"Day {i}") for i in range(6)]
        for h, agenda in ((440, False), (self._SHORT, True)):
            widget = _widget(h=h)
            assert _ctx([], widget=widget)["agenda"] is agenda
            assert _ctx(busy, widget=widget)["agenda"] is agenda

    def test_lists_all_day_then_timed_by_start(self) -> None:
        # All-day events come first, then timed ones in time order,
        # whatever order the calendar returned them in.
        ctx = _ctx(
            [
                _ev("2026-10-19T14:00:00", "2026-10-19T15:00:00", "Late"),
                _ev("2026-10-19", "2026-10-20", "Birthday"),
                _ev("2026-10-19T09:30:00", "2026-10-19T10:00:00", "Early"),
            ],
            widget=_widget(h=self._SHORT),
        )
        assert self._day(ctx, 0) == ["Birthday", "9:30 Early", "14:00 Late"]

    def test_events_outside_the_hours_are_listed(self) -> None:
        # There is no time axis, so start_hour/end_hour do not hide
        # anything.
        ctx = _ctx(
            [
                _ev("2026-10-19T05:00:00", "2026-10-19T05:30:00", "Dawn"),
                _ev("2026-10-19T22:00:00", "2026-10-19T23:00:00", "Night"),
            ],
            widget=_widget(h=self._SHORT),
        )
        assert self._day(ctx, 0) == ["5:00 Dawn", "22:00 Night"]

    def test_multi_day_all_day_event_repeats_each_day(self) -> None:
        # A three-day all-day event is listed under each of its days.
        ctx = _ctx(
            [_ev("2026-10-19", "2026-10-22", "Trip")],
            widget=_widget(h=self._SHORT),
        )
        assert [self._day(ctx, i) for i in range(4)] == [
            ["Trip"],
            ["Trip"],
            ["Trip"],
            [],
        ]

    def test_overnight_event_continues_on_next_day(self) -> None:
        # A continuation keeps the event's real start time.
        ctx = _ctx(
            [_ev("2026-10-19T22:00:00", "2026-10-20T01:00:00", "Party")],
            widget=_widget(h=self._SHORT),
        )
        assert self._day(ctx, 0) == ["22:00 Party"]
        assert self._day(ctx, 1) == ["22:00 Party"]

    def test_overflow_is_counted(self) -> None:
        # More events than rows: the last row counts what is left, so
        # shown events plus the count add up to all of them.
        total = 20
        ctx = _ctx(
            [
                _ev(
                    f"2026-10-19T{9 + i // 4:02d}:{15 * (i % 4):02d}:00",
                    f"2026-10-19T{9 + i // 4:02d}:{15 * (i % 4) + 10:02d}:00",
                    f"Ev {i}",
                )
                for i in range(total)
            ],
            widget=_widget(h=self._SHORT),
        )
        rows = self._day(ctx, 0)
        assert rows[-1].startswith("+")
        assert len(rows) - 1 + int(rows[-1][1:]) == total

    def test_stays_inside_the_widget(self) -> None:
        # No row is drawn below the widget, however many events.
        h = self._SHORT
        ctx = _ctx(
            [_ev("2026-10-19", "2026-10-20", f"Day {i}") for i in range(30)],
            widget=_widget(h=h),
        )
        assert ctx["events"]
        for box in ctx["events"]:
            assert box["y"] >= ctx["content_y"] + ctx["header_h"]
            assert box["y"] + box["h"] <= h

    def test_tiny_widget_shows_only_the_header(self) -> None:
        # With no room for a row, nothing is listed and nothing breaks.
        ctx = _ctx(
            [_ev("2026-10-19", "2026-10-20", "Day")],
            widget=_widget(h=24),
        )
        assert ctx["agenda"] is True
        assert ctx["events"] == []
        assert len(ctx["headers"]) == 7

    def test_renders_to_svg(self) -> None:
        # The template draws the agenda like the grid layout.
        with patch(_NOW, return_value=_MONDAY):
            img = render_to_image(
                [_widget(h=self._SHORT)],
                _config([_ev("2026-10-19", "2026-10-20", "Day")]),
            )
        assert_has_dark_pixels(img, 0, 0, 758, self._SHORT)
        assert_all_white(img, 0, self._SHORT + 20, 758, 480)


class TestAllDayText:
    """All-day bars show their text at every grid-mode height."""

    def test_bars_and_markers_have_text(self) -> None:
        # The lane is tall enough for one line of event text even when
        # the day font, and so the header, is small.
        events = [
            _ev("2026-10-19", "2026-10-20", f"Day {i}") for i in range(5)
        ]
        for h in range(210, 481, 10):
            ctx = _ctx(events, widget=_widget(h=h))
            if ctx["agenda"]:
                continue
            texts = [b["lines"][0]["text"] for b in ctx["all_day"]]
            assert len(texts) == 3
            assert all(texts), f"empty all-day text at h={h}: {texts}"
            assert any(t.startswith("+") for t in texts)

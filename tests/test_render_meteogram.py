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

import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    DEFAULT_ROW_H,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    _month_abbrev,
    _weekday_abbrev,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets._helpers import _card_insets
from custom_components.eink_dashboard.widgets.meteogram import (
    _prune_overlapping_day_markers,
)
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    content_bbox,
    make_config,
    render_to_image,
)

# Six full days of hourly data (2026-05-02T00:00 onward), a Saturday
# into a Sunday, so tests can exercise a single day-boundary crossing
# at 2026-05-03T00:00. The range extends past the 120h clamp ceiling
# so a render at hours=500 (clamped to 120) actually differs from an
# unclamped/data-extent-based render, rather than the two coinciding
# because the mock data ran out first. Temperature follows a smooth
# daily sine wave so a "hours"-limited window and the full window
# produce visibly different curves. Explicit UTC tzinfo (matching
# real HA forecast timestamps and _FORECAST_TIMESERIES in
# test_render_graph.py) keeps day-boundary math independent of the
# host's local timezone -- a naive datetime's .isoformat() has no
# offset, and _parse_attribute_timestamp() would then interpret it
# as local time via datetime.fromisoformat(...).timestamp().
_HOURLY_START = datetime(2026, 5, 2, 0, 0, 0, tzinfo=UTC)
_METEOGRAM_HOURLY_FORECAST = [
    {
        "datetime": (_HOURLY_START + timedelta(hours=i)).isoformat(),
        "temperature": round(
            20 + 6 * math.sin((i % 24) / 24 * 2 * math.pi), 1
        ),
        "condition": "sunny" if 6 <= (i % 24) < 20 else "clear-night",
        "cloud_coverage": 20 if 6 <= (i % 24) < 20 else 60,
        # Nonzero for a few hours each day (10:00-12:00), zero the
        # rest of the time -- gives the precipitation-bar tests both
        # bars and gaps to check for.
        "precipitation": 1.5 if 10 <= (i % 24) < 13 else 0.0,
    }
    for i in range(144)
]

# Same hourly cadence as _METEOGRAM_HOURLY_FORECAST but without a
# "precipitation" key at all, matching weather integrations that
# don't report it (see WEATHER.md's graceful-degradation note).
_METEOGRAM_HOURLY_FORECAST_NO_PRECIP = [
    {
        "datetime": (_HOURLY_START + timedelta(hours=i)).isoformat(),
        "temperature": round(
            20 + 6 * math.sin((i % 24) / 24 * 2 * math.pi), 1
        ),
        "condition": "sunny" if 6 <= (i % 24) < 20 else "clear-night",
        "cloud_coverage": 20 if 6 <= (i % 24) < 20 else 60,
    }
    for i in range(144)
]

# Precipitation on the very first and last plotted hour of a
# default 24h window, so the resulting bars sit right at the
# content area's left/right edges -- exercises the bar-clamping
# logic that keeps bars from overhanging into the card border. The
# value (999.9) is deliberately oversized so its label is far wider
# than a single content-edge bar slot regardless of font-size or
# padding tuning, rather than relying on a value that only just
# barely overhangs.
_METEOGRAM_HOURLY_FORECAST_EDGE_PRECIP = [
    {
        "datetime": (_HOURLY_START + timedelta(hours=i)).isoformat(),
        "temperature": round(
            20 + 6 * math.sin((i % 24) / 24 * 2 * math.pi), 1
        ),
        "condition": "sunny" if 6 <= (i % 24) < 20 else "clear-night",
        "cloud_coverage": 20 if 6 <= (i % 24) < 20 else 60,
        "precipitation": 999.9 if i in (0, 24) else 0.0,
    }
    for i in range(144)
]

# Two forecast entries spaced 20h apart -- wider than the 8h
# minimum window (_MIN_HOURS) -- so a widget requesting the
# minimum window filters this down to a single remaining point.
# Used to exercise the precipitation-bar computation's handling of
# a too-short point list.
_METEOGRAM_HOURLY_FORECAST_SPARSE = [
    {
        "datetime": _HOURLY_START.isoformat(),
        "temperature": 20.0,
        "condition": "sunny",
        "cloud_coverage": 20,
        "precipitation": 1.5,
    },
    {
        "datetime": (_HOURLY_START + timedelta(hours=20)).isoformat(),
        "temperature": 21.0,
        "condition": "sunny",
        "cloud_coverage": 20,
        "precipitation": 0.0,
    },
]

# Precipitation amounts small enough (0.01mm) that format_number()
# rounds them to "0.0" at its 1-decimal-place display precision --
# exercises the near-zero label suppression that keeps a visible
# bar from being paired with a misleading "0.0" label.
_METEOGRAM_HOURLY_FORECAST_TINY_PRECIP = [
    {
        "datetime": (_HOURLY_START + timedelta(hours=i)).isoformat(),
        "temperature": round(
            20 + 6 * math.sin((i % 24) / 24 * 2 * math.pi), 1
        ),
        "condition": "sunny" if 6 <= (i % 24) < 20 else "clear-night",
        "cloud_coverage": 20 if 6 <= (i % 24) < 20 else 60,
        "precipitation": 0.01 if 10 <= (i % 24) < 13 else 0.0,
    }
    for i in range(144)
]

# Two adjacent hours with sharply different precipitation amounts,
# close enough together in a narrow widget that their labels
# collide -- exercises the priority-based placement that keeps the
# higher amount's label over the lower one's.
_METEOGRAM_HOURLY_FORECAST_PRIORITY_PRECIP = [
    {
        "datetime": (_HOURLY_START + timedelta(hours=i)).isoformat(),
        "temperature": round(
            20 + 6 * math.sin((i % 24) / 24 * 2 * math.pi), 1
        ),
        "condition": "sunny" if 6 <= (i % 24) < 20 else "clear-night",
        "cloud_coverage": 20 if 6 <= (i % 24) < 20 else 60,
        "precipitation": {10: 0.5, 11: 9.0}.get(i, 0.0),
    }
    for i in range(24)
]

# Hourly forecast starting late in the day (22:00 UTC) so the
# "today" label sits only ~2h before the next midnight boundary on
# the x-axis -- exercises _prune_overlapping_day_markers()'s
# first-marker collision case.
_HOURLY_START_LATE = datetime(2026, 5, 2, 22, 0, 0, tzinfo=UTC)
_METEOGRAM_HOURLY_FORECAST_LATE_START = [
    {
        "datetime": (_HOURLY_START_LATE + timedelta(hours=i)).isoformat(),
        "temperature": round(
            20 + 6 * math.sin((i % 24) / 24 * 2 * math.pi), 1
        ),
        "condition": "sunny" if 6 <= (i % 24) < 20 else "clear-night",
        "cloud_coverage": 20 if 6 <= (i % 24) < 20 else 60,
    }
    for i in range(30)
]

MOCK_METEOGRAM_STATES: dict[str, dict[str, object]] = {
    "weather.home": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
            "forecast_hourly": _METEOGRAM_HOURLY_FORECAST,
        },
    },
    "weather.no_hourly": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
        },
    },
    "weather.no_precip": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
            "forecast_hourly": _METEOGRAM_HOURLY_FORECAST_NO_PRECIP,
        },
    },
    "weather.edge_precip": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
            "forecast_hourly": _METEOGRAM_HOURLY_FORECAST_EDGE_PRECIP,
        },
    },
    "weather.sparse_precip": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
            "forecast_hourly": _METEOGRAM_HOURLY_FORECAST_SPARSE,
        },
    },
    "weather.tiny_precip": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
            "forecast_hourly": _METEOGRAM_HOURLY_FORECAST_TINY_PRECIP,
        },
    },
    "weather.priority_precip": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
            "forecast_hourly": (_METEOGRAM_HOURLY_FORECAST_PRIORITY_PRECIP),
        },
    },
    "weather.late_start": {
        "state": "sunny",
        "attributes": {
            "temperature": 20.0,
            "forecast_hourly": _METEOGRAM_HOURLY_FORECAST_LATE_START,
        },
    },
}


class TestRenderMeteogram:
    """Verify rendering of meteogram widgets.

    The renderer (``widgets/meteogram.py`` + ``templates/
    meteogram.svg.j2``) does not exist yet — every test here must
    FAIL until it is implemented. Meteogram is a chart widget built
    on the same submodules as ``GRAPH`` (see
    ``widgets/graph/``), so its structural/scaling tests mirror
    ``TestRenderGraph`` rather than the row-based widget pattern.
    """

    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 700,
        "height": 300,
        "states": MOCK_METEOGRAM_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        """Return display config merged with overrides."""
        return make_config(self._DEFAULTS, **overrides)

    def _widget(self, **overrides: object) -> dict[str, object]:
        """Return a 700x260 meteogram widget dict merged with overrides."""
        w: dict[str, object] = {
            "type": "meteogram",
            "x": 0,
            "y": 0,
            "w": 700,
            "h": 260,
            "entity": "weather.home",
        }
        w.update(overrides)
        return w

    # ── Structural tests (card style, mirrors TestRenderGraph) ──────────

    def test_meteogram_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        h = 260
        m = _compute_metrics(DEFAULT_ROW_H)
        widget = self._widget(h=h, card_style="border")
        img = render_to_image([widget], self._config())
        assert_card_border(img, 700, h, m)

    def test_meteogram_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge; right
        # edge is white.
        h = 260
        m = _compute_metrics(DEFAULT_ROW_H)
        widget = self._widget(h=h, card_style="left_bar")
        img = render_to_image([widget], self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            h - 2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        assert_all_white(img, 695, 0, 700, 1)

    def test_meteogram_card_none(self) -> None:
        # No-decoration style has white corners — only inner content
        # draws pixels.
        widget = self._widget(card_style="none")
        img = render_to_image([widget], self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 697, 0, 700, 3)

    def test_meteogram_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none".
        base = self._widget()
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── Scaling ───────────────────────────────────────────────────────

    def test_meteogram_scales_proportionally(self) -> None:
        # Doubling widget height doubles the rendered plot content
        # height. Canvas height is fixed (large enough for the
        # taller widget) and only the widget's own h varies, mirroring
        # TestRenderGraph.test_graph_scales_proportionally.
        small = self._widget(h=160)
        large = self._widget(h=320)
        img_small = render_to_image([small], self._config(height=340))
        img_large = render_to_image([large], self._config(height=340))
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(0, 0, 700, 340),
            region_large=(0, 0, 700, 340),
            expected_ratio=2.0,
        )

    # ── Auto-sizing (mirrors TestRenderGraph, not row-count based) ──────

    def test_meteogram_auto_height(self) -> None:
        # Without an explicit h, the widget falls back to a sensible
        # default height (at least DEFAULT_ROW_H).
        widget: dict[str, object] = {
            "type": "meteogram",
            "x": 0,
            "y": 0,
            "w": 700,
            "entity": "weather.home",
        }
        svg = render_widget_svg(widget, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) >= DEFAULT_ROW_H

    def test_meteogram_explicit_h_preserved(self) -> None:
        # An explicit h is reflected in the SVG height attribute.
        widget = self._widget(h=200)
        svg = render_widget_svg(widget, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200

    # ── Data / missing-state handling ────────────────────────────────

    def test_meteogram_missing_entity_renders_blank(self) -> None:
        # An entity absent from states renders a blank (all-white)
        # canvas without crashing.
        widget = self._widget(entity="weather.nonexistent")
        img = render_to_image([widget], self._config())
        assert_all_white(img, 0, 0, 700, 300)

    def test_meteogram_missing_hourly_forecast_renders_blank(self) -> None:
        # An entity present in states but without a forecast_hourly
        # attribute renders blank rather than crashing — meteogram
        # requires hourly data and has no fallback to daily/
        # twice_daily forecasts.
        widget = self._widget(entity="weather.no_hourly")
        img = render_to_image([widget], self._config())
        assert_all_white(img, 0, 0, 700, 300)

    # ── Meteogram-specific content (SVG-string assertions, mirrors
    #    TestRenderGraph's use of render_widget_svg for content
    #    checks that don't depend on grayscale pixel luminance —
    #    the temperature curve is colored by a gradient, so warm
    #    segments render too light for reliable dark-pixel checks) ──

    def test_meteogram_draws_temperature_curve(self) -> None:
        # A stroked, unfilled path renders the temperature curve —
        # the same fill="none"/stroke shape _line_series() already
        # produces for the GRAPH widget's line mode.
        svg = render_widget_svg(self._widget(), self._config())
        # Bind fill="none" to the same <path> tag, so a coincidental
        # match elsewhere in the SVG can't produce a false pass.
        assert re.search(r'<path[^>]*fill="none"', svg) is not None

    def test_meteogram_grid_labels_clear_their_gridline(self) -> None:
        # Each Y-axis gridline label's baseline must sit above its
        # own gridline (smaller y, since SVG y grows downward), not
        # directly on it -- otherwise the label straddles the line
        # instead of sitting clear of it.
        svg = render_widget_svg(self._widget(), self._config())
        pairs = re.findall(
            r'<line x1="\d+" y1="(\d+)"\s+x2="\d+" y2="\d+"\s+'
            r'stroke="[^"]*"\s+stroke-width="[^"]*"/>\s*'
            r'<text x="\d+" y="(\d+)"',
            svg,
        )
        assert pairs, "expected at least one Y-axis gridline/label pair"
        for line_y, label_y in pairs:
            assert int(label_y) < int(line_y)

    def test_meteogram_icons_every_two_to_three_hours(self) -> None:
        # Condition icons appear every 2-3h, not once per hour, for
        # a 24h window. Weather icons are inlined with a fixed
        # viewBox="0 0 30 30" (see _weather_svg_filter), distinct
        # from any other icon system, so counting that substring
        # counts placed condition icons.
        widget = self._widget(hours=24)
        svg = render_widget_svg(widget, self._config())
        icon_count = svg.count('viewBox="0 0 30 30"')
        assert icon_count > 0
        assert icon_count < 24, "icons must not be placed every hour"
        # 24h at a 2-3h step is 8-12 icons.
        assert 6 <= icon_count <= 12

    def test_meteogram_edge_hour_ticks_anchor_inward(self) -> None:
        # The first/last hour tick always maps exactly to
        # content_left/content_right, regardless of widget height --
        # they anchor "start"/"end" instead of "middle" so their
        # label grows inward rather than straddling the plot edge.
        # Distinguishes them from every other label in the SVG (only
        # hour ticks pair an explicit text-anchor with
        # dominant-baseline="hanging"; day labels use "hanging" with
        # no text-anchor attribute at all).
        widget = self._widget(h=550, hours=72)
        svg = render_widget_svg(widget, self._config())
        assert re.search(
            r'<text[^>]*text-anchor="start"[^>]*'
            r'dominant-baseline="hanging"[^>]*>00</text>',
            svg,
        )
        assert re.search(
            r'<text[^>]*text-anchor="end"[^>]*'
            r'dominant-baseline="hanging"[^>]*>00</text>',
            svg,
        )
        assert re.search(
            r'<text[^>]*text-anchor="middle"[^>]*'
            r'dominant-baseline="hanging"[^>]*>03</text>',
            svg,
        )

    def test_meteogram_extreme_height_hour_ticks_do_not_clip(self) -> None:
        # hour_font_sz scales with the widget's height, but the
        # card's left/right insets don't -- at h=2000, hour_font_sz
        # (100px) dwarfs the fixed 12px padding, so a center-anchored
        # first/last tick would push roughly half its glyph width
        # past the canvas edge, where resvg clips it out of the
        # raster entirely. A wide w (5000) spaces interior ticks far
        # enough apart that only the edge ticks are at risk of
        # clipping -- isolating the fix from the unrelated, much
        # denser interior-tick-overlap case. With "start"/"end"
        # anchoring the edge labels grow inward instead, so no ink
        # should touch column 0 or column w-1. Reverting to
        # text-anchor="middle" for every tick reproduces the original
        # bug: content_bbox's left/right edges collapse to exactly 0
        # and w. The hour row occupies the bottom
        # (_ROW_GAP_RATIO + _HOUR_ROW_H_RATIO) * h = 0.1 * h = 200px
        # of the widget; nothing else in the template draws there.
        w = 5000
        h = 2000
        widget = self._widget(w=w, h=h, hours=72)
        img = render_to_image([widget], self._config(width=w, height=h))
        bbox = content_bbox(img, 0, h - 200, w, h)
        assert bbox is not None
        left, _, right, _ = bbox
        assert left > 0, "first hour tick clipped past the left edge"
        assert right < w - 1, "last hour tick clipped past the right edge"

    def test_meteogram_day_boundary_line_and_label(self) -> None:
        # A window spanning a midnight crossing draws a dashed
        # vertical line and a weekday+date label for the new day.
        widget = self._widget(hours=48)
        svg = render_widget_svg(widget, self._config())
        assert "stroke-dasharray" in svg
        # No comma, no zero-padded day, matching the existing
        # weekday/month label style in _format_relative_date().
        expected_label = (
            f"{_weekday_abbrev(date(2026, 5, 3), 'en')} "
            f"{_month_abbrev(date(2026, 5, 3), 'en')} 3"
        )
        assert expected_label in svg

    def test_meteogram_late_start_drops_first_day_label(self) -> None:
        # A forecast window starting at 22:00 puts the "today"
        # label only ~2h from the next midnight boundary on the
        # x-axis -- close enough that the two labels would overlap,
        # so the "today" label must be dropped in favor of the
        # boundary label (regression test for
        # _prune_overlapping_day_markers()).
        widget = self._widget(entity="weather.late_start")
        svg = render_widget_svg(widget, self._config())
        today_label = (
            f"{_weekday_abbrev(date(2026, 5, 2), 'en')} "
            f"{_month_abbrev(date(2026, 5, 2), 'en')} 2"
        )
        next_day_label = (
            f"{_weekday_abbrev(date(2026, 5, 3), 'en')} "
            f"{_month_abbrev(date(2026, 5, 3), 'en')} 3"
        )
        assert today_label not in svg
        assert next_day_label in svg

    def test_meteogram_multi_day_window_keeps_all_labels(self) -> None:
        # A window with generous spacing between day boundaries
        # keeps every label -- pruning must not remove markers that
        # don't actually collide or overflow.
        widget = self._widget(hours=96)
        svg = render_widget_svg(widget, self._config())
        for day in (2, 3, 4, 5):
            label = (
                f"{_weekday_abbrev(date(2026, 5, day), 'en')} "
                f"{_month_abbrev(date(2026, 5, day), 'en')} {day}"
            )
            assert label in svg

    def test_meteogram_show_cloud_cover_default_true(self) -> None:
        # show_cloud_cover defaults to True — omitting it must
        # produce the same output as explicitly enabling it.
        default_svg = render_widget_svg(self._widget(), self._config())
        explicit_svg = render_widget_svg(
            self._widget(show_cloud_cover=True), self._config()
        )
        assert default_svg == explicit_svg

    def test_meteogram_show_cloud_cover_toggle_changes_output(self) -> None:
        # Disabling show_cloud_cover removes the cloud-coverage band,
        # changing the rendered output.
        band_svg = render_widget_svg(
            self._widget(show_cloud_cover=True), self._config()
        )
        no_band_svg = render_widget_svg(
            self._widget(show_cloud_cover=False), self._config()
        )
        assert band_svg != no_band_svg

    def test_meteogram_hours_changes_output(self) -> None:
        # Different hours windows produce different rendered content.
        svg_24 = render_widget_svg(self._widget(hours=24), self._config())
        svg_48 = render_widget_svg(self._widget(hours=48), self._config())
        assert svg_24 != svg_48

    def test_meteogram_hours_clamped_below_minimum(self) -> None:
        # hours below the valid 8-120 range clamps to the minimum
        # (8), rather than being used as-is or crashing.
        svg_low = render_widget_svg(self._widget(hours=1), self._config())
        svg_min = render_widget_svg(self._widget(hours=8), self._config())
        assert svg_low == svg_min

    def test_meteogram_hours_clamped_above_maximum(self) -> None:
        # hours above the valid 8-120 range clamps to the maximum
        # (120), rather than being used as-is or crashing. Mock data
        # extends to 144h, well past the clamp ceiling, so this
        # actually exercises the clamp instead of both renders
        # coinciding merely because the data ran out.
        svg_high = render_widget_svg(self._widget(hours=500), self._config())
        svg_max = render_widget_svg(self._widget(hours=120), self._config())
        assert svg_high == svg_max

    # ── Precipitation bars ───────────────────────────────────────────

    def test_meteogram_show_precipitation_default_true(self) -> None:
        # show_precipitation defaults to True -- omitting it must
        # produce the same output as explicitly enabling it.
        default_svg = render_widget_svg(self._widget(), self._config())
        explicit_svg = render_widget_svg(
            self._widget(show_precipitation=True), self._config()
        )
        assert default_svg == explicit_svg

    def test_meteogram_show_precipitation_toggle_changes_output(self) -> None:
        # Disabling show_precipitation removes the precipitation
        # bars, changing the rendered output.
        bars_svg = render_widget_svg(
            self._widget(show_precipitation=True), self._config()
        )
        no_bars_svg = render_widget_svg(
            self._widget(show_precipitation=False), self._config()
        )
        assert bars_svg != no_bars_svg

    def test_meteogram_precipitation_bars_present(self) -> None:
        # Nonzero precipitation entries draw <rect> bars, distinct
        # from every other SVG element the widget emits (lines,
        # paths, text, inlined icon <g>/<path> elements).
        svg = render_widget_svg(self._widget(hours=24), self._config())
        assert re.search(r'<rect[^>]*fill-opacity="0.5"', svg) is not None

    def test_meteogram_no_precipitation_data_no_bars(self) -> None:
        # An entity whose forecast entries omit "precipitation"
        # entirely renders without crashing and without bars.
        widget = self._widget(entity="weather.no_precip")
        svg = render_widget_svg(widget, self._config())
        assert re.search(r'<rect[^>]*fill-opacity="0.5"', svg) is None

    def test_meteogram_precip_bars_stay_within_content_bounds(self) -> None:
        # Precipitation at the very first/last plotted hour maps to
        # content_left/content_right exactly; the bar must be
        # clamped so it doesn't overhang past those edges into the
        # card border.
        widget = self._widget(entity="weather.edge_precip")
        svg = render_widget_svg(widget, self._config())

        m = _compute_metrics(DEFAULT_ROW_H)
        x_off, r_inset, _bar_width = _card_insets(m, "none", 16)
        lpad = m.padding if x_off == 0 else 0
        rpad = m.padding if r_inset == 0 else 0
        content_left = x_off + lpad
        content_right = 700 - r_inset - rpad

        bars = re.findall(
            r'<rect x="(-?\d+)"[^>]*width="(\d+)"[^>]*'
            r'fill-opacity="0.5"',
            svg,
        )
        assert bars
        for x_str, w_str in bars:
            x, bar_w = int(x_str), int(w_str)
            assert x >= content_left
            assert x + bar_w <= content_right

    def test_meteogram_precip_bars_single_point_no_crash(self) -> None:
        # Sparse/irregular hourly data can leave only one point
        # after the hours-window filter (the raw forecast has two
        # entries 20h apart, wider than the 8h minimum window).
        # Precipitation-bar computation must not crash indexing
        # into a second point that doesn't exist.
        widget = self._widget(entity="weather.sparse_precip", hours=8)
        svg = render_widget_svg(widget, self._config())
        assert re.search(r'<rect[^>]*fill-opacity="0.5"', svg) is None

    def test_meteogram_precipitation_labels_present(self) -> None:
        # Precipitation bars draw a formatted amount ("1.5") above
        # them, distinguished from every other label by the
        # text-anchor="middle" + dominant-baseline="auto" combo the
        # template only uses for precip labels (day labels use
        # dominant-baseline="hanging"; grid labels have no
        # text-anchor).
        svg = render_widget_svg(self._widget(hours=24), self._config())
        labels = re.findall(
            r'<text[^>]*text-anchor="middle"[^>]*'
            r'dominant-baseline="auto"[^>]*>([^<]*)</text>',
            svg,
        )
        assert "1.5" in labels

    def test_meteogram_no_precipitation_no_labels(self) -> None:
        # An entity without precipitation data draws no bars and
        # therefore no precip amount labels.
        widget = self._widget(entity="weather.no_precip")
        svg = render_widget_svg(widget, self._config())
        assert (
            re.search(
                r'<text[^>]*text-anchor="middle"[^>]*'
                r'dominant-baseline="auto"[^>]*>',
                svg,
            )
            is None
        )

    def test_meteogram_narrow_widget_prunes_some_precip_labels(
        self,
    ) -> None:
        # A narrow, multi-day window packs several precipitation
        # bars close enough together that their labels would
        # overlap -- some labels must be dropped (empty label),
        # while every bar itself still renders.
        widget = self._widget(w=300, hours=120)
        config = self._config()
        svg = render_widget_svg(widget, config)
        bar_count = len(re.findall(r'<rect[^>]*fill-opacity="0.5"', svg))
        label_count = len(
            re.findall(
                r'<text[^>]*text-anchor="middle"[^>]*'
                r'dominant-baseline="auto"[^>]*>',
                svg,
            )
        )
        assert bar_count > 0
        assert 0 < label_count < bar_count

    def test_meteogram_precip_priority_keeps_highest(self) -> None:
        # Two adjacent hours (0.5mm, 9.0mm) sit close enough in a
        # narrow widget that only one label fits -- the higher
        # amount must win, not whichever bar comes first.
        widget = self._widget(
            w=300, entity="weather.priority_precip", hours=24
        )
        svg = render_widget_svg(widget, self._config())
        labels = re.findall(
            r'<text[^>]*text-anchor="middle"[^>]*'
            r'dominant-baseline="auto"[^>]*>([^<]*)</text>',
            svg,
        )
        assert "9.0" in labels
        assert "0.5" not in labels

    def test_meteogram_tiny_precip_bars_but_no_labels(self) -> None:
        # A 0.01mm reading rounds to "0.0" at the formatter's
        # 1-decimal-place precision -- the bar still draws, but no
        # misleading "0.0" label should appear next to it.
        widget = self._widget(entity="weather.tiny_precip", hours=24)
        svg = render_widget_svg(widget, self._config())
        assert re.search(r'<rect[^>]*fill-opacity="0.5"', svg) is not None
        assert (
            re.search(
                r'<text[^>]*text-anchor="middle"[^>]*'
                r'dominant-baseline="auto"[^>]*>',
                svg,
            )
            is None
        )

    def test_meteogram_precip_labels_within_content_bounds(self) -> None:
        # Precipitation at hours 0 and 24 places bars right at
        # content_left/content_right, centered exactly on the
        # boundary. A center-anchored label there is wider than the
        # bar itself, so it would overhang past the card border --
        # both edge labels must be suppressed while their bars still
        # draw (previously they would render past the boundary).
        widget = self._widget(entity="weather.edge_precip")
        svg = render_widget_svg(widget, self._config())

        bar_count = len(re.findall(r'<rect[^>]*fill-opacity="0.5"', svg))
        label_count = len(
            re.findall(
                r'<text[^>]*text-anchor="middle"[^>]*'
                r'dominant-baseline="auto"[^>]*>',
                svg,
            )
        )
        assert bar_count == 2
        assert label_count == 0


class TestPruneOverlappingDayMarkers:
    """Verify _prune_overlapping_day_markers() in isolation.

    Marker x-spacing is chosen far smaller (or larger) than any
    realistic label width at the given font size, so the expected
    outcome doesn't depend on exact glyph metrics. The exception is
    the overflow test below, which necessarily uses a tight margin
    since it must actually overflow ``content_right``.
    """

    _FONT_SZ = 17

    def test_markers_with_generous_spacing_are_all_kept(self) -> None:
        # No label collides or overflows -- the list passes through
        # unchanged.
        markers: list[dict[str, object]] = [
            {"x": 0, "label": "Sat May 2"},
            {"x": 400, "label": "Sun May 3"},
            {"x": 800, "label": "Mon May 4"},
        ]
        result = _prune_overlapping_day_markers(
            markers, self._FONT_SZ, content_right=1000
        )
        assert result == markers

    def test_first_marker_dropped_when_colliding_with_second(self) -> None:
        # The "today" marker sits right next to the first midnight
        # boundary -- it is dropped in favor of the boundary label.
        markers: list[dict[str, object]] = [
            {"x": 0, "label": "Sat May 2"},
            {"x": 20, "label": "Sun May 3"},
            {"x": 400, "label": "Mon May 4"},
        ]
        result = _prune_overlapping_day_markers(
            markers, self._FONT_SZ, content_right=1000
        )
        assert result == markers[1:]

    def test_interior_collisions_are_pruned(self) -> None:
        # Regression test: the original implementation only checked
        # the first-vs-second and last markers, so colliding markers
        # in the middle of the axis survived unpruned. A run of
        # markers crammed 20px apart (far closer than any 9-
        # character label at font size 17) must collapse to the
        # markers that actually clear each other.
        markers: list[dict[str, object]] = [
            {"x": 0, "label": "Sat May 2"},
            {"x": 20, "label": "Sun May 3"},
            {"x": 40, "label": "Mon May 4"},
            {"x": 60, "label": "Tue May 5"},
            {"x": 500, "label": "Wed May 6"},
        ]
        result = _prune_overlapping_day_markers(
            markers, self._FONT_SZ, content_right=1000
        )
        assert result == [markers[1], markers[4]]

    def test_last_marker_dropped_when_overflowing_content_right(
        self,
    ) -> None:
        # The last label's estimated extent runs past the plot's
        # right edge, so it's dropped even though it doesn't
        # collide with its neighbour.
        markers: list[dict[str, object]] = [
            {"x": 0, "label": "Sat May 2"},
            {"x": 900, "label": "Sun May 3"},
        ]
        result = _prune_overlapping_day_markers(
            markers, self._FONT_SZ, content_right=950
        )
        assert result == markers[:1]

    def test_empty_and_single_marker_lists_pass_through(self) -> None:
        # Degenerate inputs (no markers, or only the "today"
        # marker) must not raise.
        assert _prune_overlapping_day_markers([], self._FONT_SZ, 1000) == []
        single: list[dict[str, object]] = [{"x": 0, "label": "Sat May 2"}]
        assert (
            _prune_overlapping_day_markers(single, self._FONT_SZ, 1000)
            == single
        )

    def test_sole_remaining_marker_kept_despite_overflow(self) -> None:
        # Regression test: an overflowing last marker is normally
        # dropped, but not when it is the only marker left -- an
        # overflowing label is preferable to no day label at all.
        single: list[dict[str, object]] = [{"x": 900, "label": "Sun May 3"}]
        result = _prune_overlapping_day_markers(
            single, self._FONT_SZ, content_right=950
        )
        assert result == single

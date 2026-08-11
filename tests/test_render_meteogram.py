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
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_gray_pixels,
    assert_scales_proportionally,
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
# logic that keeps bars from overhanging into the card border.
_METEOGRAM_HOURLY_FORECAST_EDGE_PRECIP = [
    {
        "datetime": (_HOURLY_START + timedelta(hours=i)).isoformat(),
        "temperature": round(
            20 + 6 * math.sin((i % 24) / 24 * 2 * math.pi), 1
        ),
        "condition": "sunny" if 6 <= (i % 24) < 20 else "clear-night",
        "cloud_coverage": 20 if 6 <= (i % 24) < 20 else 60,
        "precipitation": 5.0 if i in (0, 24) else 0.0,
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

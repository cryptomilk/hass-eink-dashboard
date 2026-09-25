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

"""Meteogram widget context builder.

Renders a temperature curve over an hourly weather forecast, with
condition icons, day-boundary markers, and an optional cloud-coverage
band.  Built on the same low-level helpers as the ``GRAPH`` widget
(see ``widgets/graph/``) rather than duplicating time-axis/path
logic, per the architecture decided in the meteogram design doc.
"""

from __future__ import annotations

import datetime
import math
from itertools import pairwise
from typing import TYPE_CHECKING, Any, cast

from ..const import (
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
)
from ..svg_render import _weather_svg_filter
from ._helpers import (
    _card_insets,
    _color_context,
    _fmt,
    _temp_gradient_stops,
    _widget_dim,
)
from .graph import (
    _extract_attribute_points,
    _maybe_grayscale_stops,
    _parse_attribute_timestamp,
    _smooth_fill,
    _smooth_path,
    _y_bounds,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Hourly forecast window, in hours, clamped to this range regardless
# of what the widget config requests.
_MIN_HOURS = 8
_MAX_HOURS = 120
_DEFAULT_HOURS = 24

# Condition icons are placed every this many hours -- dense enough to
# read the weather trend, sparse enough not to clutter a ~300-400px
# wide e-ink card (WEATHER.md decision: "every 2-3h, not hourly").
_ICON_STEP_HOURS = 3
# Hour-axis ticks use the same cadence as icons.
_HOUR_TICK_STEP_HOURS = 3

# Layout ratios, all relative to the widget's total height "h" so
# the widget scales proportionally (mirrors _compute_metrics()'s
# row_h-relative ratios elsewhere in the codebase).
_DAY_LABEL_H_RATIO = 0.09
_ROW_GAP_RATIO = 0.025
_HOUR_ROW_H_RATIO = 0.075
_ICON_SIZE_RATIO = 0.10
_ICON_GAP_RATIO = 0.025
_ICON_LANE_H_RATIO = 0.14
_DAY_LABEL_FONT_RATIO = 0.065
_HOUR_FONT_RATIO = 0.05
_GRID_FONT_RATIO = 0.05
# Precipitation amount labels use the same visual tier as the
# Y-axis gridline labels.
_PRECIP_LABEL_FONT_RATIO = 0.05
_CLOUD_BAND_FRAC = 0.4
# Precipitation bars use at most this fraction of the plot height,
# so they stay subordinate to the temperature curve.
_PRECIP_BAR_MAX_FRAC = 0.5


def _build_meteogram_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the meteogram widget.

    Renders an hourly temperature curve colored by a continuous
    temperature gradient (matching the weather widget's min/max
    bar), with condition icons floating above the curve, dashed
    day-boundary markers, an optional cloud-coverage band, optional
    precipitation bars, and hour-axis ticks below the plot.

    Args:
        widget: Widget config dict.  Recognised keys: ``entity``
            (HA weather entity ID), ``hours`` (forecast window in
            hours, clamped to 8-120; default 24), ``show_cloud_cover``
            (bool, default ``True``), ``show_precipitation`` (bool,
            default ``True``), ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``display_levels``.

    Returns:
        Template context dict consumed by ``meteogram.svg.j2``.
        Returns ``{"w": ..., "h": ..., "has_entity": False,
        **_color_context()}`` when the entity is missing from
        states or has no usable hourly forecast.
    """
    from ..render import _compute_metrics

    x = widget.get("x", PADDING)
    w = _widget_dim(widget, "w", config["width"] - x)
    h = _widget_dim(widget, "h", 5 * DEFAULT_ROW_H)
    card_style = str(widget.get("card_style", DEFAULT_CARD_STYLE))
    display_levels = config.get("display_levels", 16)
    show_cloud_cover = bool(widget.get("show_cloud_cover", True))
    show_precipitation = bool(widget.get("show_precipitation", True))

    entity: str = widget.get("entity", "")
    states_dict: dict[str, Any] = config.get("states", {})

    blank: dict[str, object] = {
        "w": w,
        "h": h,
        "has_entity": False,
        **_color_context(),
    }

    if not entity or entity not in states_dict:
        return blank

    desc: dict[str, object] = {
        "entity": entity,
        "attribute": "forecast_hourly",
        "attribute_timestamp_key": "datetime",
        "attribute_value_key": "temperature",
    }
    points = _extract_attribute_points(desc, states_dict)
    if not points:
        return blank

    # Recover per-entry condition/cloud_coverage, which
    # _extract_attribute_points() doesn't carry (it only returns
    # the (timestamp, value) pairs used for the numeric series).
    state = states_dict.get(entity, {})
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    raw_forecast = attrs.get("forecast_hourly", [])
    entry_by_ts: dict[float, dict[str, object]] = {}
    if isinstance(raw_forecast, list):
        for entry in raw_forecast:
            if not isinstance(entry, dict):
                continue
            ts = _parse_attribute_timestamp(entry.get("datetime"))
            if ts is not None:
                entry_by_ts[ts] = entry

    # Clamp the requested window and slice to it from the first
    # available point -- forecast-relative, not wall-clock-relative.
    hours = widget.get("hours", _DEFAULT_HOURS)
    try:
        hours = int(float(hours))
    except (ValueError, TypeError):
        hours = _DEFAULT_HOURS
    hours = max(_MIN_HOURS, min(_MAX_HOURS, hours))
    t0 = points[0][0]
    cutoff = t0 + hours * 3600
    points = [p for p in points if p[0] <= cutoff]

    # x_off/r_inset reserve space for a card frame; the plot area
    # itself uses the full remaining width, with no header row.
    # Meteogram has no header row to derive a natural row height
    # from, so card frame metrics (border/radius/left_bar) use the
    # fixed DEFAULT_ROW_H reference, independent of the chart's own
    # height -- the same fixed-reference pattern the GRAPH widget
    # uses for its header row.
    m = _compute_metrics(DEFAULT_ROW_H)
    x_off, r_inset, bar_width = _card_insets(m, card_style, display_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    content_left = x_off + lpad
    content_w = w - x_off - lpad - r_inset - rpad
    content_right = content_left + content_w

    # Day boundaries are computed against UTC calendar dates, not
    # HA's configured local timezone -- matching the existing
    # pattern in widgets/weather.py for forecast day labels.
    times = [
        datetime.datetime.fromtimestamp(t, tz=datetime.UTC) for t, _ in points
    ]
    temps = [v for _, v in points]
    t_span = max((points[-1][0] - points[0][0]), 1.0)

    def map_x(ts: float) -> int:
        """Map a Unix timestamp to an X pixel coordinate."""
        frac = (ts - points[0][0]) / t_span
        return round(content_left + frac * content_w)

    day_label_h = round(h * _DAY_LABEL_H_RATIO)
    row_gap = max(1, round(h * _ROW_GAP_RATIO))
    hour_row_h = round(h * _HOUR_ROW_H_RATIO)
    icon_size = round(h * _ICON_SIZE_RATIO)
    icon_gap = round(h * _ICON_GAP_RATIO)
    icon_lane_h = round(h * _ICON_LANE_H_RATIO)
    day_label_font_sz = max(10, round(h * _DAY_LABEL_FONT_RATIO))
    hour_font_sz = max(9, round(h * _HOUR_FONT_RATIO))
    grid_font_sz = max(9, round(h * _GRID_FONT_RATIO))
    precip_font_sz = max(9, round(h * _PRECIP_LABEL_FONT_RATIO))
    curve_stroke_w = max(2, round(h * 0.012))
    grid_stroke_w = max(1, curve_stroke_w // 2)

    plot_top = day_label_h + row_gap
    hour_row_y = h - row_gap - hour_row_h
    plot_bottom = hour_row_y - row_gap

    y_min_raw, y_max_raw = _y_bounds(temps, None, None, None)
    y_min = math.floor(y_min_raw / 5) * 5 - 5
    y_max = math.ceil(y_max_raw / 5) * 5 + 5

    scale_top = plot_top + icon_lane_h
    scale_h = max(1, plot_bottom - scale_top)

    def map_y(temp: float) -> int:
        """Map a temperature value to a Y pixel coordinate."""
        frac = (temp - y_min) / (y_max - y_min)
        return round(plot_bottom - frac * scale_h)

    # --- Y-axis gridlines/labels ---
    step = 5 if (y_max - y_min) <= 30 else 10
    grid_lines: list[dict[str, object]] = []
    grid_val = math.ceil(y_min / step) * step
    while grid_val <= y_max:
        grid_lines.append(
            {
                "y": map_y(grid_val),
                "label": f"{grid_val:g}°",
            }
        )
        grid_val += step

    # --- Cloud-coverage band ---
    show_band = False
    cloud_band_path = ""
    if show_cloud_cover:
        band_max_h = (plot_bottom - plot_top) * _CLOUD_BAND_FRAC
        band_pts: list[tuple[int, int]] = []
        for ts, _v in points:
            entry = entry_by_ts.get(ts)
            cc = entry.get("cloud_coverage") if entry else None
            if cc is None:
                # Points missing cloud_coverage are skipped;
                # _smooth_path/_smooth_fill bridge across the gap
                # by interpolating between the nearest available
                # points.
                continue
            try:
                cc_val = float(str(cc))
            except (ValueError, TypeError):
                continue
            band_pts.append(
                (
                    map_x(ts),
                    round(plot_top + cc_val / 100 * band_max_h),
                )
            )
        if len(band_pts) >= 2:
            band_path = _smooth_path(band_pts)
            if band_path:
                # Close to plot_top (not a baseline) -- the band
                # grows down from the plot's top edge.
                cloud_band_path = _smooth_fill(band_path, band_pts, plot_top)
                show_band = True

    # --- Precipitation bars ---
    precip_bars = (
        _compute_precip_bars(
            points,
            entry_by_ts,
            map_x,
            plot_top,
            plot_bottom,
            content_left,
            content_right,
        )
        if show_precipitation
        else []
    )
    if precip_bars:
        precip_bars = _label_precip_bars(
            precip_bars,
            config,
            precip_font_sz,
            plot_top,
            row_gap,
            content_left,
            content_right,
        )

    # --- Day boundary markers ---
    language = str(config.get("language", "en"))
    day_markers: list[dict[str, object]] = []
    first_date = times[0].date()
    day_markers.append(
        {
            "x": content_left,
            "show_line": False,
            "label": _day_label(first_date, language),
        }
    )
    cursor = datetime.datetime.combine(
        first_date + datetime.timedelta(days=1),
        datetime.time.min,
        tzinfo=datetime.UTC,
    )
    t_last = times[-1]
    while cursor < t_last:
        cx = map_x(cursor.timestamp())
        day_markers.append(
            {
                "x": cx,
                "show_line": True,
                "line_y1": plot_top,
                "line_y2": plot_bottom,
                "label": _day_label(cursor.date(), language),
            }
        )
        cursor += datetime.timedelta(days=1)
    day_markers = _prune_overlapping_day_markers(
        day_markers, day_label_font_sz, content_right
    )

    # --- Temperature curve, colored by a continuous gradient ---
    curve_pts = [(map_x(t), map_y(v)) for t, v in points]
    curve_path = _smooth_path(curve_pts)
    sample_temps = [_sample_by_time(points, i / 16) for i in range(17)]
    curve_stops = _maybe_grayscale_stops(
        _temp_gradient_stops(sample_temps), config
    )

    # --- Condition icons, floating above the curve ---
    icons: list[dict[str, object]] = []
    for i in range(0, len(points), _ICON_STEP_HOURS):
        ts, temp = points[i]
        entry = entry_by_ts.get(ts)
        condition = entry.get("condition") if entry else None
        if not isinstance(condition, str) or not condition:
            continue
        try:
            icon_svg = _weather_svg_filter(condition, icon_size)
        except (KeyError, FileNotFoundError):
            continue
        # Clamp so the icon stays inside the content area at both
        # edges (the first point maps to content_left, the last
        # to content_right).
        cx = map_x(ts)
        cx = max(
            content_left + icon_size // 2,
            min(cx, content_right - icon_size // 2),
        )
        cy = map_y(temp) - icon_gap - icon_size // 2
        cy = max(cy, plot_top + icon_size // 2)
        icons.append(
            {
                "x": cx - icon_size // 2,
                "y": cy - icon_size // 2,
                "svg": icon_svg,
            }
        )

    # --- Hour-axis ticks ---
    hour_ticks: list[dict[str, object]] = [
        {
            "x": map_x(points[i][0]),
            "label": times[i].strftime("%H"),
        }
        for i in range(0, len(points), _HOUR_TICK_STEP_HOURS)
    ]

    return {
        "w": w,
        "h": h,
        "has_entity": True,
        "card_style": card_style,
        "bar_width": bar_width,
        "m_border": m.border,
        "m_radius": m.radius,
        **_color_context(),
        "curve_path": curve_path,
        "curve_stops": curve_stops,
        "curve_stroke_w": curve_stroke_w,
        "grid_lines": grid_lines,
        "grid_font_sz": grid_font_sz,
        "grid_stroke_w": grid_stroke_w,
        "content_left": content_left,
        "content_right": content_right,
        "show_cloud_band": show_band,
        "cloud_band_path": cloud_band_path,
        "show_precip": bool(precip_bars),
        "precip_bars": precip_bars,
        "precip_font_sz": precip_font_sz,
        "day_markers": day_markers,
        "day_label_font_sz": day_label_font_sz,
        "day_label_y": m.border,
        "icons": icons,
        "hour_ticks": hour_ticks,
        "hour_row_y": hour_row_y,
        "hour_font_sz": hour_font_sz,
    }


def _prune_overlapping_day_markers(
    day_markers: list[dict[str, object]],
    font_sz: int,
    content_right: int,
) -> list[dict[str, object]]:
    """Drop day-boundary labels that would overlap or overflow.

    Labels are left-anchored (``text-anchor="start"``), so a label
    collides with its neighbour whenever its rendered right edge
    reaches the neighbour's x position. This does a greedy left-to-
    right scan, keeping a marker only if it clears the last kept
    marker's label, so interior collisions are caught as well as the
    first-vs-second case (common when the forecast starts late in
    the day, putting midnight -- and the next label -- only a few
    hours away). The first marker is the "today" label and is
    preferred to drop over the midnight boundary it collides with,
    since the boundary line/label is more informative. The last kept
    label is dropped if it would overflow the plot's right edge,
    unless it is the only marker left, in which case it is kept
    (an overflowing label beats no label at all).

    Args:
        day_markers: Day-boundary marker dicts, in x order, each
            with ``x`` and ``label`` keys. The first entry is
            assumed to be the non-boundary "today" label, per how
            ``_build_meteogram_context()`` constructs this list.
        font_sz: Day-label font size in pixels, used to measure
            label width.
        content_right: X coordinate of the plot's right edge.

    Returns:
        The marker list with overlapping/overflowing labels removed.
    """
    from ..render import _load_font

    font = _load_font(font_sz)

    def label_extent(marker: dict[str, object]) -> int:
        """Return a marker label's estimated rendered right edge."""
        x = cast("int", marker["x"])
        label = str(marker["label"])
        return x + round(font.getlength(label))

    if len(day_markers) >= 2:
        first_edge = label_extent(day_markers[0]) + font_sz
        second_x = cast("int", day_markers[1]["x"])
        # A full font_sz of gap keeps labels from looking cramped
        # when they just barely miss.
        if first_edge >= second_x:
            day_markers = day_markers[1:]

    kept: list[dict[str, object]] = []
    prev_edge: int | None = None
    for marker in day_markers:
        marker_x = cast("int", marker["x"])
        if prev_edge is not None and prev_edge >= marker_x:
            continue
        kept.append(marker)
        prev_edge = label_extent(marker) + font_sz

    # No gap here: unlike the collision checks above, touching the
    # plot's right edge exactly is not treated as overflow. Never
    # drop the last remaining marker, since a single overflowing
    # label is preferable to no day label at all.
    if len(kept) > 1 and label_extent(kept[-1]) > content_right:
        kept.pop()
    return kept


def _compute_precip_bars(
    points: list[tuple[float, float]],
    entry_by_ts: dict[float, dict[str, object]],
    map_x: Callable[[float], int],
    plot_top: int,
    plot_bottom: int,
    content_left: int,
    content_right: int,
) -> list[dict[str, object]]:
    """Compute precipitation bar rects for the meteogram plot.

    Points with no ``precipitation`` entry or a zero/negative value
    draw no bar -- unlike the cloud-coverage band (a filled area
    that needs interpolated gap bridging), a missing precipitation
    reading just means "no bar here".

    Args:
        points: ``(timestamp, temperature)`` pairs, sorted by
            timestamp, defining the plotted time range.
        entry_by_ts: Full forecast entries keyed by timestamp, used
            to look up each point's ``precipitation`` value.
        map_x: Maps a Unix timestamp to an X pixel coordinate.
        plot_top: Y pixel coordinate of the plot's top edge.
        plot_bottom: Y pixel coordinate of the plot's bottom edge
            (baseline bars grow up from).
        content_left: X pixel coordinate of the plot's left edge,
            used to clamp bars so they don't overhang the content
            area.
        content_right: X pixel coordinate of the plot's right edge,
            used to clamp bars so they don't overhang the content
            area.

    Returns:
        Bar rects as ``{"x", "y", "w", "h", "value", "value_str"}``
        dicts, one per point with positive precipitation, where
        ``value`` is the raw precipitation amount and ``value_str``
        is its original string representation (preserved so label
        formatting doesn't inherit spurious decimal places from a
        ``float`` round-trip). Empty if none have data.
    """
    if len(points) < 2:
        return []

    precip_vals: list[tuple[float, float, str]] = []
    for ts, _v in points:
        entry = entry_by_ts.get(ts)
        precip = entry.get("precipitation") if entry else None
        if precip is None:
            continue
        precip_str = str(precip)
        try:
            precip_val = float(precip_str)
        except (ValueError, TypeError):
            continue
        if precip_val > 0:
            precip_vals.append((ts, precip_val, precip_str))

    if not precip_vals:
        return []

    # Floor at 2mm and add 1mm headroom so drizzle amounts still
    # draw a visible bar, mirroring the reference
    # lovelace-meteogram-card's precipitation Y-scale.
    precip_max = max(2.0, max(v for _, v, _s in precip_vals) + 1)
    max_bar_h = (plot_bottom - plot_top) * _PRECIP_BAR_MAX_FRAC
    slot_w = map_x(points[1][0]) - map_x(points[0][0])
    bar_w = max(2, round(slot_w * 0.8))

    bars: list[dict[str, object]] = []
    for ts, precip_val, precip_str in precip_vals:
        bar_h = max(1, round(precip_val / precip_max * max_bar_h))
        # Clamp so the bar stays inside the content area at both
        # edges (the first point maps to content_left, the last
        # to content_right).
        bar_x = max(
            content_left,
            min(map_x(ts) - bar_w // 2, content_right - bar_w),
        )
        bars.append(
            {
                "x": bar_x,
                "y": plot_bottom - bar_h,
                "w": bar_w,
                "h": bar_h,
                "value": precip_val,
                "value_str": precip_str,
            }
        )
    return bars


def _is_zero_label(label: str) -> bool:
    """Return whether a formatted numeric label displays as zero.

    Checks the label's own digits rather than re-deriving a display
    precision independently, so this can never disagree with what
    ``_fmt()`` (and, underneath it, ``format_number()``) actually
    renders -- e.g. a 0.01mm reading formatted to "0.0" or "0,0"
    (decimal-comma locales) both correctly count as zero.

    Args:
        label: A number formatted via ``_fmt()``.

    Returns:
        ``True`` if ``label`` contains at least one digit and every
        digit is "0".
    """
    digits = [c for c in label if c.isdigit()]
    return bool(digits) and all(d == "0" for d in digits)


def _label_precip_bars(
    precip_bars: list[dict[str, object]],
    config: DisplayConfig,
    font_sz: int,
    plot_top: int,
    row_gap: int,
    content_left: int,
    content_right: int,
) -> list[dict[str, object]]:
    """Attach formatted, priority-pruned labels to precipitation bars.

    Labels are centered above their bar (``text-anchor="middle"``),
    so two labels collide when one's right half-width reaches into
    the next's left half-width. When labels collide, the bar with
    the higher precipitation value keeps its label -- a bar whose
    label loses out, or would overflow the content area, still
    draws its bar, but gets an empty ``"label"`` so no colliding or
    overhanging text is rendered. Values that format to all-zero
    digits at the display precision (e.g. a 0.01mm drizzle reading
    formatting to "0.0") are also left unlabeled, since a visible
    bar next to a "0.0" label would be misleading.

    Args:
        precip_bars: Bar dicts from ``_compute_precip_bars()``, in
            x order, each with ``x``, ``y``, ``w``, ``value``, and
            ``value_str`` keys.
        config: Display config, used for locale-aware number
            formatting via ``_fmt()``.
        font_sz: Precipitation label font size in pixels.
        plot_top: Y pixel coordinate of the plot's top edge, used
            to keep labels from being clipped above the plot.
        row_gap: Vertical gap between a bar's top and its label.
        content_left: X pixel coordinate of the plot's left edge,
            used to drop labels that would overhang it.
        content_right: X pixel coordinate of the plot's right edge,
            used to drop labels that would overhang it.

    Returns:
        New bar dicts, each with an added ``label`` key (possibly
        empty). ``label_x`` and ``label_y`` are only present when
        ``label`` is non-empty.
    """
    from ..render import _load_font

    # Bold to match the template's font-weight="bold", so measured
    # widths reflect what actually renders.
    font = _load_font(font_sz, bold=True)

    # Candidate labels that could be placed: (index, value, left,
    # right, label, label_x, label_y). Bars that format to zero or
    # would overhang the content area are excluded up front, since
    # they can never win a placement regardless of priority.
    candidates: list[tuple[int, float, float, float, str, int, int]] = []
    for i, bar in enumerate(precip_bars):
        value = cast("float", bar["value"])
        value_str = cast("str", bar["value_str"])
        label = _fmt(value_str, config)
        if _is_zero_label(label):
            continue

        half_w = font.getlength(label) / 2
        bar_x = cast("int", bar["x"])
        bar_w = cast("int", bar["w"])
        center = bar_x + bar_w / 2
        left_edge = center - half_w
        right_edge = center + half_w

        # No gap here: matches _prune_overlapping_day_markers()'s
        # strict edge check -- touching exactly is not overflow.
        if left_edge < content_left or right_edge > content_right:
            continue

        # Safeguard: with _PRECIP_BAR_MAX_FRAC = 0.5 a bar's top
        # can't rise above the plot's midpoint, so this clamp
        # doesn't trigger today, but it guards against future
        # changes to that fraction or very short plot heights.
        label_y = max(cast("int", bar["y"]) - row_gap, plot_top + font_sz)
        candidates.append(
            (i, value, left_edge, right_edge, label, round(center), label_y)
        )

    # Place labels in descending precipitation order, so the most
    # informative readings win when two labels would collide. Ties
    # fall back to the original (left-to-right) order.
    #
    # A half-font-size margin is added to both sides of the overlap
    # test, giving a full font_sz of separation between two placed
    # labels -- the same "full font_sz of gap" margin
    # _prune_overlapping_day_markers() uses so adjacent labels don't
    # render touching.
    gap = font_sz / 2
    placed: dict[int, tuple[str, int, int]] = {}
    occupied: list[tuple[float, float]] = []
    for i, _value, left_edge, right_edge, label, label_x, label_y in sorted(
        candidates, key=lambda c: (-c[1], c[0])
    ):
        overlaps = any(
            left_edge < right + gap and right_edge > left - gap
            for left, right in occupied
        )
        if not overlaps:
            placed[i] = (label, label_x, label_y)
            occupied.append((left_edge, right_edge))

    labeled: list[dict[str, object]] = []
    for i, bar in enumerate(precip_bars):
        new_bar = dict(bar)
        if i in placed:
            label, label_x, label_y = placed[i]
            new_bar["label"] = label
            new_bar["label_x"] = label_x
            new_bar["label_y"] = label_y
        else:
            new_bar["label"] = ""
        labeled.append(new_bar)
    return labeled


def _sample_by_time(points: list[tuple[float, float]], frac: float) -> float:
    """Linearly interpolate a temperature at a time fraction.

    Interpolates by timestamp rather than list index, so the
    result matches the time-linear ``map_x()`` placement of the
    curve even when forecast points are irregularly spaced.

    Args:
        points: ``(timestamp, temperature)`` pairs, sorted by
            timestamp.
        frac: Position to sample, in ``[0, 1]``, as a fraction of
            the time span from the first to the last point.

    Returns:
        Interpolated temperature at ``frac``.
    """
    target = points[0][0] + frac * (points[-1][0] - points[0][0])
    for (t0, v0), (t1, v1) in pairwise(points):
        if t1 >= target:
            span = t1 - t0
            t = (target - t0) / span if span > 0 else 0.0
            return v0 + (v1 - v0) * t
    return points[-1][1]


def _day_label(d: datetime.date, language: str) -> str:
    """Return a day-boundary label: "Weekday Mon D".

    Args:
        d: Date to format.
        language: BCP 47 language code.

    Returns:
        Formatted label string.
    """
    from ..render import _month_abbrev, _weekday_abbrev

    weekday = _weekday_abbrev(d, language)
    month = _month_abbrev(d, language)
    return f"{weekday} {month} {d.day}"

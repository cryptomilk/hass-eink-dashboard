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

"""Graph widget path smoothing and axis/legend layout geometry."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from ...const import FontWeight
from .._helpers import _fmt, _resolve_tz

if TYPE_CHECKING:
    from ...const import DisplayConfig, Widget


def _smooth_path(pts: list[tuple[int, int]]) -> str:
    """Generate a smoothed SVG path d attribute via midpoint Q-curves.

    Uses midpoint quadratic Bezier interpolation as in mini-graph-card:
    for each consecutive pair A→B the midpoint Z(A,B) is the endpoint
    and B is the control point (SVG ``Q cx,cy ex,ey`` — control first,
    endpoint second).  The curve therefore passes through the midpoints,
    not the data points, producing C1-continuous transitions without a
    full Catmull-Rom spline.

    Args:
        pts: Ordered list of (x, y) integer pixel coordinates,
            oldest-to-newest.

    Returns:
        SVG path ``d`` attribute string starting with ``M``, or
        an empty string when ``pts`` has fewer than two entries.
    """
    if len(pts) < 2:
        return ""
    parts: list[str] = [f"M{pts[0][0]},{pts[0][1]}"]
    last = pts[0]
    for pt in pts[1:]:
        zx = round((last[0] + pt[0]) / 2)
        zy = round((last[1] + pt[1]) / 2)
        # Each fragment is "midpoint Q datapoint".  The midpoint
        # ends the Q command started by the *previous* iteration;
        # the new Q's endpoint comes from the *next* iteration's
        # midpoint (or the final-closure line below).  The very
        # first midpoint acts as an implicit LineTo after the M.
        parts.append(f" {zx},{zy} Q {pt[0]},{pt[1]}")
        last = pt
    # Close the final Q command: the last data point is the endpoint.
    parts.append(f" {pts[-1][0]},{pts[-1][1]}")
    return "".join(parts)


def _smooth_fill(
    path: str,
    pts: list[tuple[int, int]],
    gy2: int,
) -> str:
    """Append fill closure to a smoothed graph path.

    Extends the smoothed line path with L commands that drop to the
    baseline (``gy2``) and close the polygon back to the leftmost
    point, creating a filled area under the curve.

    Args:
        path: SVG path d attribute from ``_smooth_path``.
        pts: The same ordered list of (x, y) pixel coordinates used
            to generate ``path``.
        gy2: Bottom of the graph area in SVG coordinates.

    Returns:
        Closed SVG path d attribute string for the fill area,
        or an empty string when ``path`` is empty.
    """
    if not path:
        return ""
    return f"{path} L {pts[-1][0]},{gy2} L {pts[0][0]},{gy2} Z"


def _format_timestamp(
    ts: float,
    time_fmt: str,
    tz: datetime.tzinfo = datetime.UTC,
) -> str:
    """Format a Unix timestamp as a short time string.

    Args:
        ts: Unix timestamp (seconds since epoch).
        time_fmt: ``"12"`` for 12-hour with AM/PM, any other value
            for 24-hour ``HH:MM`` format.
        tz: Time zone the time is shown in (default UTC).

    Returns:
        Formatted time string.
    """
    dt = datetime.datetime.fromtimestamp(ts, tz=tz)
    if time_fmt == "12":
        # %-I is GNU libc-only; lstrip("0") is portable.
        return dt.strftime("%I:%M %p").lstrip("0")
    return dt.strftime("%H:%M")


def _axis_font(
    widget: Widget | None,
    graph_h: int,
    scale: float,
) -> tuple[int, FontWeight]:
    """Resolve the shared ``axis`` label role for a graph area height.

    Axis, extrema, and legend annotations all render with the same
    face, so one role covers them.  The default size is proportional
    to the graph area's pixel height; an explicit ``fonts.axis.size``
    overrides it, and ``fonts.axis.weight`` overrides the regular
    default.

    Args:
        widget: Widget config dict carrying the optional ``fonts``
            mapping.  ``None`` (direct geometry unit tests) means no
            override applies.
        graph_h: Graph area height in pixels the default size is
            derived from.
        scale: Display-level ``font_scale`` multiplier applied to the
            derived default size.

    Returns:
        ``(size, weight)`` for the axis label role.
    """
    from ...render import resolve_font

    return resolve_font(
        widget if widget is not None else {},
        "axis",
        max(10, round(graph_h * 0.06)),
        FontWeight.REGULAR,
        scale=scale,
    )


def _label_geometry(
    points: list[tuple[float, float]],
    y_min: float,
    y_max: float,
    gx1: int,
    gy1: int,
    gy2: int,
    config: DisplayConfig,
    label_font_sz: int,
    weight: FontWeight,
) -> tuple[int, int, int, int, int, str, str, str, str]:
    """Compute Y-axis and X-axis label geometry.

    Measures formatted label text widths to determine how much
    horizontal space to reserve on the left (Y-axis labels) and
    how much vertical space to reserve at the bottom (X-axis labels).
    If the X-axis label band would leave no usable graph area
    (``new_gy2 <= gy1``), X-axis labels are suppressed and ``gy2``
    is left unchanged.

    Args:
        points: Sorted (timestamp, value) data pairs.
        y_min: Y-axis lower bound.
        y_max: Y-axis upper bound.
        gx1: Current left edge of the graph area (will be shifted).
        gy1: Top edge of the graph area (used to detect clipping).
        gy2: Current bottom edge of the graph area (will be shifted).
        config: Display config for locale formatting and time_format.
        label_font_sz: Resolved axis label font size in pixels, from
            ``_axis_font()``.  Shared with the extrema and legend
            labels.
        weight: Resolved axis label weight, used to load the same
            face the template renders.

    Returns:
        Tuple of
        ``(new_gx1, new_gy2, y_label_x, x_label_y, label_font_sz,
           y_min_str, y_max_str, x_oldest_str, x_newest_str)``
        where ``new_gx1``/``new_gy2`` are the adjusted graph
        boundaries and the string fields are the formatted label texts.
        When X-axis labels are suppressed, ``x_label_y`` is 0 and the
        time strings are empty.
    """
    from ...render import _load_role_font

    label_font = _load_role_font(label_font_sz, weight)
    y_min_str = _fmt(f"{y_min:.1f}", config)
    y_max_str = _fmt(f"{y_max:.1f}", config)
    label_w = max(
        round(label_font.getlength(y_min_str)),
        round(label_font.getlength(y_max_str)),
    )
    label_gap = label_font_sz // 2
    y_label_x = gx1
    new_gx1 = gx1 + label_w + label_gap

    x_label_h = label_font_sz + label_font_sz // 2
    new_gy2 = gy2 - x_label_h

    # Suppress X-axis labels when the widget is too short to
    # accommodate them without inverting the graph area.
    if new_gy2 <= gy1:
        x_label_y = 0
        new_gy2 = gy2
        x_oldest_str = ""
        x_newest_str = ""
    else:
        # Place the hanging baseline just below new_gy2 so the text
        # body (label_font_sz tall) fits within the original gy2.
        x_label_y = new_gy2 + label_gap
        time_fmt = str(config.get("time_format", "24"))
        tz = _resolve_tz(config)
        t_oldest = min(t for t, _ in points)
        t_newest = max(t for t, _ in points)
        x_oldest_str = _format_timestamp(t_oldest, time_fmt, tz)
        x_newest_str = _format_timestamp(t_newest, time_fmt, tz)

    return (
        new_gx1,
        new_gy2,
        y_label_x,
        x_label_y,
        label_font_sz,
        y_min_str,
        y_max_str,
        x_oldest_str,
        x_newest_str,
    )


def _secondary_label_geometry(
    y_min: float,
    y_max: float,
    gx2: int,
    label_font_sz: int,
    config: DisplayConfig,
    *,
    weight: FontWeight = FontWeight.REGULAR,
) -> tuple[int, int, str, str]:
    """Compute secondary Y-axis label geometry on the right side.

    Mirrors ``_label_geometry`` for the right-hand axis.  Measures
    formatted label text widths and shifts ``gx2`` inward to reserve
    space for right-aligned secondary Y-axis labels.

    Args:
        y_min: Secondary Y-axis lower bound.
        y_max: Secondary Y-axis upper bound.
        gx2: Current right edge of the graph area.
        label_font_sz: Font size shared with primary labels.
        config: Display config for locale formatting.
        weight: Resolved axis label weight, used to load the same
            face the template renders.

    Returns:
        Tuple of ``(new_gx2, y2_label_right_x, y2_min_str,
        y2_max_str)`` where ``new_gx2`` is the adjusted right
        edge and the strings are the formatted Y-axis labels.
    """
    from ...render import _load_role_font

    y2_min_str = _fmt(f"{y_min:.1f}", config)
    y2_max_str = _fmt(f"{y_max:.1f}", config)
    font = _load_role_font(label_font_sz, weight)
    label_w = max(
        round(font.getlength(y2_min_str)),
        round(font.getlength(y2_max_str)),
    )
    label_gap = label_font_sz // 2
    y2_label_right_x = gx2
    new_gx2 = gx2 - label_w - label_gap
    return new_gx2, y2_label_right_x, y2_min_str, y2_max_str


def _extrema_geometry(
    points: list[tuple[float, float]],
    label_font_sz: int,
    gy2: int,
    config: DisplayConfig,
    graph_h: int,
    *,
    widget: Widget | None = None,
) -> tuple[int, int, int, str, str, bool]:
    """Compute extrema text geometry and formatted strings.

    Finds the data minimum and maximum, formats them with timestamps,
    and reserves a band directly above ``gy2`` for the text.

    Args:
        points: Sorted (timestamp, value) data pairs.
        label_font_sz: Font size already chosen for axis labels; reuse
            it for extrema so both are the same size.  Pass 0 when
            axis labels are disabled — the function then resolves the
            ``axis`` role itself from ``graph_h``, the same formula
            ``_axis_font()`` applies to the axis labels.
        gy2: Bottom edge of the free area; the band is taken from
            here upward and the returned ``new_gy2`` is its top.
        config: Display config for locale formatting and time_format.
        graph_h: Pixel height of the graph area (gy2 - gy1), used to
            derive a proportional font size when ``label_font_sz`` is 0.
        widget: Widget config dict, consulted for the ``fonts.axis``
            override when ``label_font_sz`` is 0.

    Returns:
        Tuple of
        ``(new_gy2, extrema_y, extrema_font_sz,
           extrema_min_str, extrema_max_str, show_extrema)``
        where ``new_gy2`` is the adjusted graph bottom and the string
        fields are the formatted extrema labels.
    """
    if label_font_sz:
        efont_sz = label_font_sz
    else:
        efont_sz, _ = _axis_font(
            widget, graph_h, config.get("font_scale", 1.0)
        )
    extrema_h = efont_sz + efont_sz // 2
    # The text hangs from the band top, so it stays inside the band
    # instead of running into whatever lies below gy2.
    extrema_y = gy2 - extrema_h
    new_gy2 = extrema_y

    time_fmt = str(config.get("time_format", "24"))
    tz = _resolve_tz(config)
    min_pt = min(points, key=lambda p: p[1])
    max_pt = max(points, key=lambda p: p[1])
    extrema_min_str = (
        f"Min: {_fmt(f'{min_pt[1]:.1f}', config)}"
        f" at {_format_timestamp(min_pt[0], time_fmt, tz)}"
    )
    extrema_max_str = (
        f"Max: {_fmt(f'{max_pt[1]:.1f}', config)}"
        f" at {_format_timestamp(max_pt[0], time_fmt, tz)}"
    )
    return new_gy2, extrema_y, efont_sz, extrema_min_str, extrema_max_str, True


def _truncate_to_width(text: str, font: Any, max_w: float) -> str:
    """Truncate ``text`` with a trailing ellipsis to fit ``max_w``.

    Widths are rounded before comparison so the fit check matches
    the rounding ``_legend_geometry`` applies when it measures the
    returned string for layout.

    Args:
        text: Candidate string.
        font: A loaded PIL font used to measure text width.
        max_w: Maximum allowed pixel width.

    Returns:
        ``text`` unchanged if it already fits; otherwise the longest
        prefix of ``text`` plus ``"…"`` that fits within ``max_w``.
        Returns an empty string if even a bare ``"…"`` does not fit.
    """
    if round(font.getlength(text)) <= max_w:
        return text
    ellipsis = "…"
    if round(font.getlength(ellipsis)) > max_w:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if round(font.getlength(text[:mid] + ellipsis)) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ellipsis


def _legend_geometry(
    entity_descs: list[dict[str, object]],
    states: dict[str, Any],
    gx1: int,
    gx2: int,
    gy2: int,
    label_font_sz: int,
    graph_h: int,
    bar_fills: tuple[str, ...] | None = None,
    *,
    widget: Widget | None = None,
    scale: float = 1.0,
) -> tuple[int, int, list[dict[str, object]]]:
    """Compute legend layout below the graph area.

    Builds a horizontal legend row with one entry per entity.  For
    line graphs, each entry shows a short dash-pattern line sample;
    for bar charts, a small filled rectangle swatch in the entity's
    fill color is shown instead.  The legend occupies a band
    directly above ``gy2``, whose top is returned as the new
    ``gy2``.  When entity names are long enough that entries would
    overflow the graph width (and overlap each other), names are
    truncated with an ellipsis to fit.  Each entry's fair share is
    an equal split of the available width; entries whose name
    already fits that share keep it in full, and the width they
    don't use is handed to the remaining (over-budget) entries
    before those are truncated, so one long name doesn't needlessly
    shrink short ones.

    Args:
        entity_descs: Normalized entity descriptor list from
            ``_normalize_entities()``.
        states: States dict for resolving entity friendly names.
        gx1: Left edge of the graph area.
        gx2: Right edge of the graph area, used to cap total legend
            width and truncate names that would otherwise overflow.
        gy2: Bottom edge of the free area; the band is taken from
            here upward.
        label_font_sz: Font size from axis labels; 0 triggers the
            same ``axis`` role resolution as ``_axis_font()``, based
            on ``graph_h``.
        graph_h: Graph area pixel height used when
            ``label_font_sz`` is 0.
        bar_fills: Tuple of hex fill colors for bar chart entities
            (from ``_BAR_FILL_COLORS``), or ``None`` for line mode.
            When provided, each legend entry includes swatch rect
            geometry keyed as ``swatch_x``, ``swatch_y``,
            ``swatch_w``, ``swatch_h``, ``bar_fill``.
        widget: Widget config dict, consulted for the ``fonts.axis``
            override.  The resolved weight applies to the legend text
            even when ``label_font_sz`` is given, so the measured
            face matches the rendered one.
        scale: Display-level ``font_scale`` multiplier applied to the
            derived size when ``label_font_sz`` is 0.

    Returns:
        Tuple of ``(new_gy2, legend_y, legend_entries)`` where
        ``legend_entries`` is a list of dicts each containing
        ``name``, ``line_x1``, ``line_x2``, ``line_y``,
        ``swatch_x``, ``swatch_y``, ``swatch_w``, ``swatch_h``,
        ``bar_fill``, ``text_x``, ``text_y``,
        ``stroke_dasharray``, and ``font_sz``.
    """
    from ...render import _load_role_font

    font_sz, font_weight = _axis_font(widget, graph_h, scale)
    if label_font_sz:
        # Axis labels are shown, so the caller already resolved the
        # role from the pre-adjustment graph height; reuse that size
        # rather than this call's smaller, post-adjustment basis.
        font_sz = label_font_sz
    legend_font = _load_role_font(font_sz, font_weight)
    line_sample_w = font_sz * 2
    gap = font_sz // 2
    legend_h = font_sz + gap
    # The band is taken from the bottom of the free area, so it never
    # overlaps bands reserved below it earlier.
    legend_y = gy2 - legend_h
    new_gy2 = legend_y

    names: list[str] = []
    for desc in entity_descs:
        eid = str(desc["entity"])
        name_override = str(desc.get("name", ""))
        if name_override:
            name = name_override
        else:
            st = states.get(eid, {})
            attrs = st.get("attributes", {}) if isinstance(st, dict) else {}
            name = (
                str(attrs.get("friendly_name", eid))
                if isinstance(attrs, dict)
                else eid
            )
        names.append(name)

    text_widths = [round(legend_font.getlength(n)) for n in names]
    entry_w = [line_sample_w + gap + tw + gap * 2 for tw in text_widths]
    avail_w = max(0, gx2 - gx1)
    if entity_descs and sum(entry_w) > avail_w:
        even_share = avail_w / len(entity_descs)
        fits = [w <= even_share for w in entry_w]
        spare_w = avail_w - sum(
            w for w, f in zip(entry_w, fits, strict=True) if f
        )
        overflow_n = len(fits) - sum(fits)
        over_share = spare_w / overflow_n if overflow_n else 0.0
        max_text_w = max(0.0, over_share - line_sample_w - gap * 3)
        names = [
            n if fits[i] else _truncate_to_width(n, legend_font, max_text_w)
            for i, n in enumerate(names)
        ]
        text_widths = [round(legend_font.getlength(n)) for n in names]

    entries: list[dict[str, object]] = []
    x = gx1
    # Centre each swatch/line sample and text label vertically
    # within the legend band.
    entry_mid_y = legend_y + legend_h // 2
    swatch_h = max(4, font_sz // 2)
    for i, (desc, name, text_w) in enumerate(
        zip(entity_descs, names, text_widths, strict=True)
    ):
        fill = bar_fills[i % len(bar_fills)] if bar_fills else ""
        entries.append(
            {
                "name": name,
                "line_x1": x,
                "line_x2": x + line_sample_w,
                "line_y": entry_mid_y,
                "swatch_x": x,
                "swatch_y": entry_mid_y - swatch_h // 2,
                "swatch_w": line_sample_w,
                "swatch_h": swatch_h,
                "bar_fill": fill,
                "text_x": x + line_sample_w + gap,
                "text_y": entry_mid_y,
                "stroke_dasharray": str(desc.get("dash", "")),
                "font_sz": font_sz,
            }
        )
        x += line_sample_w + gap + text_w + gap * 2
    return new_gy2, legend_y, entries

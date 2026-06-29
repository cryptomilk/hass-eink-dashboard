"""Graph widget context builder."""

from __future__ import annotations

import datetime
from typing import cast

from ..const import DEFAULT_ROW_H, PADDING, DisplayConfig, Widget
from ._helpers import (
    _color_context,
    _entity_info_context,
    _fmt,
    _widget_dim,
)


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
    if not path or len(pts) < 2:
        return ""
    return f"{path} L {pts[-1][0]},{gy2} L {pts[0][0]},{gy2} Z"


def _format_timestamp(ts: float, time_fmt: str) -> str:
    """Format a Unix timestamp as a short time string.

    Args:
        ts: Unix timestamp (seconds since epoch, UTC).
        time_fmt: ``"12"`` for 12-hour with AM/PM, any other value
            for 24-hour ``HH:MM`` format.

    Returns:
        Formatted time string.
    """
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.UTC)
    if time_fmt == "12":
        return dt.strftime("%-I:%M %p")
    return dt.strftime("%H:%M")


def _label_geometry(
    points: list[tuple[float, float]],
    y_min: float,
    y_max: float,
    gx1: int,
    gy2: int,
    config: DisplayConfig,
    graph_h: int,
) -> tuple[int, int, int, int, int, str, str, str, str]:
    """Compute Y-axis and X-axis label geometry.

    Measures formatted label text widths to determine how much
    horizontal space to reserve on the left (Y-axis labels) and
    how much vertical space to reserve at the bottom (X-axis labels).

    Args:
        points: Sorted (timestamp, value) data pairs.
        y_min: Y-axis lower bound.
        y_max: Y-axis upper bound.
        gx1: Current left edge of the graph area (will be shifted).
        gy2: Current bottom edge of the graph area (will be shifted).
        config: Display config for locale formatting and time_format.
        graph_h: Pixel height of the graph area (gy2 - gy1), used to
            derive proportional font size.

    Returns:
        Tuple of
        ``(new_gx1, new_gy2, y_label_x, x_label_y, label_font_sz,
           y_min_str, y_max_str, x_oldest_str, x_newest_str)``
        where ``new_gx1``/``new_gy2`` are the adjusted graph
        boundaries and the string fields are the formatted label texts.
    """
    from ..render import _load_font

    label_font_sz = max(10, round(graph_h * 0.06))
    label_font = _load_font(label_font_sz)
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
    x_label_y = gy2
    new_gy2 = gy2 - x_label_h

    time_fmt = str(config.get("time_format", "24"))
    t_oldest = min(t for t, _ in points)
    t_newest = max(t for t, _ in points)
    x_oldest_str = _format_timestamp(t_oldest, time_fmt)
    x_newest_str = _format_timestamp(t_newest, time_fmt)

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


def _extrema_geometry(
    points: list[tuple[float, float]],
    label_font_sz: int,
    gy2: int,
    config: DisplayConfig,
    graph_h: int,
) -> tuple[int, int, int, str, str, bool]:
    """Compute extrema text geometry and formatted strings.

    Finds the data minimum and maximum, formats them with timestamps,
    and reserves vertical space below the current graph bottom.

    Args:
        points: Sorted (timestamp, value) data pairs.
        label_font_sz: Font size already chosen for axis labels; reuse
            it for extrema so both are the same size.  Pass 0 when
            axis labels are disabled — the function then falls back to
            ``max(10, round(graph_h * 0.06))``, the same formula used
            by ``_label_geometry``.
        gy2: Current bottom edge of the graph area (will be shifted).
        config: Display config for locale formatting and time_format.
        graph_h: Pixel height of the graph area (gy2 - gy1), used to
            derive a proportional font size when ``label_font_sz`` is 0.

    Returns:
        Tuple of
        ``(new_gy2, extrema_y, extrema_font_sz,
           extrema_min_str, extrema_max_str, show_extrema)``
        where ``new_gy2`` is the adjusted graph bottom and the string
        fields are the formatted extrema labels.
    """
    efont_sz = label_font_sz or max(10, round(graph_h * 0.06))
    extrema_h = efont_sz + efont_sz // 2
    extrema_y = gy2
    new_gy2 = gy2 - extrema_h

    time_fmt = str(config.get("time_format", "24"))
    min_pt = min(points, key=lambda p: p[1])
    max_pt = max(points, key=lambda p: p[1])
    extrema_min_str = (
        f"Min: {_fmt(f'{min_pt[1]:.1f}', config)}"
        f" at {_format_timestamp(min_pt[0], time_fmt)}"
    )
    extrema_max_str = (
        f"Max: {_fmt(f'{max_pt[1]:.1f}', config)}"
        f" at {_format_timestamp(max_pt[0], time_fmt)}"
    )
    return new_gy2, extrema_y, efont_sz, extrema_min_str, extrema_max_str, True


def _build_graph_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the graph widget.

    Renders a compact header row (entity name, optional icon, and
    current value) at the top of the widget, with a dedicated line
    graph filling the remaining height.  Designed for e-ink displays
    where the chart is the primary content rather than a supplementary
    sparkline.

    History data is read from ``states[entity_id]["history"]``,
    injected by ``_fetch_history()`` in ``__init__.py``.  Raw entries
    are filtered to the ``hours_to_show`` time window, grouped into
    fixed-width time buckets using ``points_per_hour``, then reduced
    to a single representative value per bucket via ``aggregate_func``.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, required),
            ``name`` (display name override),
            ``icon`` (MDI icon name, e.g. ``"mdi:thermometer"``),
            ``unit`` (unit string override),
            ``hours_to_show`` (history window in hours; default 24),
            ``points_per_hour`` (data points per hour; default 0.5,
            giving one point per 2-hour bucket),
            ``aggregate_func`` (``"avg"``, ``"min"``, ``"max"``,
            ``"first"``, ``"last"``, or ``"sum"``; default
            ``"avg"``),
            ``group_by`` (``"interval"`` keeps ``points_per_hour``;
            ``"hour"`` forces 1 pt/hr; ``"date"`` forces 1 pt/day;
            default ``"interval"``),
            ``line_width`` (graph line stroke width in pixels;
            default 2; doubled on 2-level displays),
            ``upper_bound`` (optional fixed Y-axis upper bound;
            auto-computed from data when omitted),
            ``lower_bound`` (optional fixed Y-axis lower bound;
            auto-computed when omitted),
            ``min_bound_range`` (minimum Y-axis range; if the
            auto-computed range is smaller, it is expanded
            symmetrically around the midpoint),
            ``smoothing`` (midpoint Q-curve path smoothing;
            default ``True``),
            ``show_fill`` (draw light-gray fill below the line;
            default ``True``),
            ``show_labels`` (show Y-axis min/max labels and X-axis
            time labels; default ``True``),
            ``show_extrema`` (show min/max values with timestamps
            below the graph; default ``False``),
            ``show_state`` (show current entity value in the
            header; default ``True``),
            ``show_name`` (show entity name in the header; default
            ``True``),
            ``show_icon`` (show icon in the header; default
            ``True``),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``,
            ``grayscale_levels``, and optionally ``time_format``
            (``"24"`` or ``"12"``; default ``"24"``).

    Returns:
        Template context dict consumed by ``graph.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing from
        states.  Full context includes widget dimensions, card
        style, metrics, colors, icon geometry, header text, and
        graph path/fill coordinates.
    """
    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    hours_to_show: int = int(float(widget.get("hours_to_show", 24)))
    points_per_hour: float = float(widget.get("points_per_hour", 0.5))
    aggregate_func: str = str(widget.get("aggregate_func", "avg"))
    group_by: str = str(widget.get("group_by", "interval"))
    line_width: int = int(float(widget.get("line_width", 2)))
    upper_bound = widget.get("upper_bound")
    lower_bound = widget.get("lower_bound")
    min_bound_range = widget.get("min_bound_range")
    smoothing: bool = bool(widget.get("smoothing", True))
    show_fill: bool = bool(widget.get("show_fill", True))
    show_labels: bool = bool(widget.get("show_labels", True))
    show_extrema: bool = bool(widget.get("show_extrema", False))
    show_state: bool = bool(widget.get("show_state", True))
    show_name: bool = bool(widget.get("show_name", True))
    show_icon: bool = bool(widget.get("show_icon", True))
    grayscale_levels = config.get("grayscale_levels", 16)

    # group_by overrides points_per_hour before bucketing.
    if group_by == "hour":
        points_per_hour = 1.0
    elif group_by == "date":
        # One point per day = 1/24 points per hour.
        points_per_hour = 1.0 / 24.0

    # Default height: 5 rows to provide adequate graph space.
    svg_h = _widget_dim(widget, "h", 5 * DEFAULT_ROW_H)

    # Header occupies exactly one row; graph fills the rest.
    header_h = DEFAULT_ROW_H

    # Translate show_icon to hide_icon for _entity_info_context.
    ctx = _entity_info_context(
        {**widget, "hide_icon": not show_icon}, config, header_h, svg_w, svg_h
    )
    if ctx is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            **_color_context(),
        }

    # name_x = x_off + lpad (left content edge); icon_cx +
    # icon_r = svg_w - r_inset - rpad (right content edge).
    gx1: int = cast("int", ctx["name_x"])
    gx2: int = cast("int", ctx["icon_cx"]) + cast("int", ctx["icon_r"])

    # Stroke width: user-configured, widened on 2-level displays.
    graph_stroke_w = line_width * 2 if grayscale_levels <= 2 else line_width
    # Inset graph area by 2× stroke so line stays within bounds.
    margin = graph_stroke_w * 2
    gy1 = header_h + margin
    gy2 = svg_h - margin

    # --- History to graph coordinates ---
    graph_path = ""
    fill_path = ""
    polyline_points = ""
    fill_points = ""

    # Label / grid / extrema context — set inside the data guard.
    label_font_sz = 0
    y_label_x = gx1
    y_min_str = ""
    y_max_str = ""
    x_oldest_str = ""
    x_newest_str = ""
    x_label_y = gy2
    grid_y_top = gy1
    grid_y_bot = gy2
    show_labels_ctx = False
    show_grid = False
    extrema_font_sz = 0
    extrema_min_str = ""
    extrema_max_str = ""
    extrema_y = gy2
    show_extrema_ctx = False

    entity_id: str = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id, {})
    history: list[dict[str, object]] = state.get("history", [])

    # Filter to the hours_to_show time window.  Anchor to the newest
    # history entry rather than wall clock so a temporarily unavailable
    # entity does not shift the window — matches the sensor widget
    # convention.  The strict > intentionally excludes any entry at
    # exactly the cutoff boundary (inconsequential in practice).
    if history:
        t_latest = max(float(str(e.get("lu", 0))) for e in history)
        cutoff = t_latest - hours_to_show * 3600
        history = [e for e in history if float(str(e.get("lu", 0))) > cutoff]

    # Extract numeric (timestamp, value) pairs; skip non-numeric.
    numeric: list[tuple[float, float]] = []
    for entry in history:
        s = entry.get("s", "")
        lu = entry.get("lu", 0.0)
        try:
            val = float(str(s))
            numeric.append((float(str(lu)), val))
        except (ValueError, TypeError):
            continue

    if len(numeric) >= 2:
        points = _aggregate_history(numeric, points_per_hour, aggregate_func)

        values = [v for _, v in points]
        y_min, y_max = _y_bounds(
            values, lower_bound, upper_bound, min_bound_range
        )

        # Label geometry: adjusts gx1 and gy2 to reserve space for
        # axis text; must happen before pixel coordinate mapping.
        if show_labels:
            # Use pre-adjustment height for font sizing so it is
            # proportional to the widget's total graph allocation,
            # not the reduced area after labels are carved out.
            graph_h = gy2 - gy1
            (
                gx1,
                gy2,
                y_label_x,
                x_label_y,
                label_font_sz,
                y_min_str,
                y_max_str,
                x_oldest_str,
                x_newest_str,
            ) = _label_geometry(
                points, y_min, y_max, gx1, gy2, config, graph_h
            )
            show_labels_ctx = True

        # Extrema: adjusts gy2 to reserve space for min/max text.
        if show_extrema:
            graph_h_ex = gy2 - gy1
            (
                gy2,
                extrema_y,
                extrema_font_sz,
                extrema_min_str,
                extrema_max_str,
                show_extrema_ctx,
            ) = _extrema_geometry(
                points, label_font_sz, gy2, config, graph_h_ex
            )

        # Grid lines at the final graph-area top and bottom edges.
        grid_y_top = gy1
        grid_y_bot = gy2
        # Suppress fine gray lines on 2-level (B&W) displays.
        show_grid = show_labels_ctx and grayscale_levels > 2

        timestamps = [t for t, _ in points]
        t_min = min(timestamps)
        t_range = max(max(timestamps) - t_min, 1.0)
        y_range = y_max - y_min

        # Map (timestamp, value) → (x, y) pixel; Y is inverted.
        pts = [
            (
                round(gx1 + (t - t_min) / t_range * (gx2 - gx1)),
                round(gy2 - (v - y_min) / y_range * (gy2 - gy1)),
            )
            for t, v in points
        ]

        if smoothing:
            graph_path = _smooth_path(pts)
            if show_fill:
                fill_path = _smooth_fill(graph_path, pts, gy2)
        else:
            polyline_points = " ".join(f"{px},{py}" for px, py in pts)
            if show_fill:
                fill_pts = [
                    *pts,
                    (pts[-1][0], gy2),
                    (pts[0][0], gy2),
                ]
                fill_points = " ".join(f"{px},{py}" for px, py in fill_pts)

    return {
        **ctx,
        "has_graph": bool(polyline_points or graph_path),
        "polyline_points": polyline_points,
        "graph_path": graph_path,
        "fill_points": fill_points,
        "fill_path": fill_path,
        "graph_stroke_w": graph_stroke_w,
        "grid_stroke_w": max(1, graph_stroke_w // 2),
        "hide_state": not show_state,
        "show_name": show_name,
        # Axis labels.
        "show_labels": show_labels_ctx,
        "label_font_sz": label_font_sz,
        "y_label_x": y_label_x,
        "y_min_str": y_min_str,
        "y_max_str": y_max_str,
        "y_min_label_y": gy2,
        "y_max_label_y": gy1,
        "x_oldest_str": x_oldest_str,
        "x_newest_str": x_newest_str,
        "x_label_y": x_label_y,
        # gx1 is the data area left (shifted right past y-axis labels);
        # gx2 is the right content edge.  Grid lines and x-axis labels
        # intentionally span the data area only, not the label zone.
        "x_label_left": gx1,
        "x_label_right": gx2,
        # Grid lines.
        "show_grid": show_grid,
        "grid_y_top": grid_y_top,
        "grid_y_bot": grid_y_bot,
        # Extrema text.
        "show_extrema": show_extrema_ctx,
        "extrema_font_sz": extrema_font_sz,
        "extrema_min_str": extrema_min_str,
        "extrema_max_str": extrema_max_str,
        "extrema_y": extrema_y,
        "extrema_left": gx1,
        "extrema_right": gx2,
    }


def _aggregate_history(
    numeric: list[tuple[float, float]],
    points_per_hour: float,
    aggregate_func: str,
) -> list[tuple[float, float]]:
    """Bucket and aggregate numeric history into representative points.

    Groups (timestamp, value) pairs into fixed-width time buckets based
    on ``points_per_hour``, then reduces each bucket to a single value
    using ``aggregate_func``.  Falls back to the raw data when bucketing
    yields fewer than two points.

    Args:
        numeric: Numeric (timestamp, value) pairs to aggregate, in any
            order.
        points_per_hour: Target data density; bucket width in seconds
            is ``3600 / points_per_hour``.
        aggregate_func: Reduction function per bucket — one of
            ``"avg"``, ``"min"``, ``"max"``, ``"first"``, ``"last"``,
            ``"sum"``.

    Returns:
        Sorted oldest-to-newest list of (timestamp, value) pairs, one
        per non-empty bucket (or the raw data if < 2 buckets).
    """
    bucket_size = 3600.0 / max(points_per_hour, 0.001)
    t_max = max(t for t, _ in numeric)

    buckets: dict[int, list[tuple[float, float]]] = {}
    for t, v in numeric:
        idx = int((t_max - t) / bucket_size)
        if idx not in buckets:
            buckets[idx] = []
        buckets[idx].append((t, v))

    bucketed: list[tuple[float, float]] = []
    for idx, entries in buckets.items():
        # Right edge of the bucket so the newest bucket aligns with
        # t_max (the graph's right edge) without leaving dead space.
        t_repr = t_max - idx * bucket_size
        vals = [v for _, v in entries]
        if aggregate_func == "min":
            agg_val: float = min(vals)
        elif aggregate_func == "max":
            agg_val = max(vals)
        elif aggregate_func == "first":
            agg_val = min(entries, key=lambda e: e[0])[1]
        elif aggregate_func == "last":
            agg_val = max(entries, key=lambda e: e[0])[1]
        elif aggregate_func == "sum":
            agg_val = sum(vals)
        else:
            agg_val = sum(vals) / len(vals)
        bucketed.append((t_repr, agg_val))

    bucketed.sort(key=lambda p: p[0])
    return bucketed if len(bucketed) >= 2 else numeric


def _y_bounds(
    values: list[float],
    lower_bound: object,
    upper_bound: object,
    min_bound_range: object,
) -> tuple[float, float]:
    """Compute Y-axis lower and upper bounds from data and config.

    Applies explicit bounds, a flat-line guard, and an optional minimum
    range expansion so the graph is never distorted by tiny fluctuations.

    Args:
        values: All numeric data values in the visible window.
        lower_bound: Optional explicit lower bound (widget config).
        upper_bound: Optional explicit upper bound (widget config).
        min_bound_range: Optional minimum Y-axis range; when the
            auto-computed range is smaller, both bounds are expanded
            symmetrically around the midpoint.

    Returns:
        ``(y_min, y_max)`` — guaranteed ``y_max > y_min``.
    """
    try:
        y_min = (
            float(str(lower_bound)) if lower_bound is not None else min(values)
        )
    except (ValueError, TypeError):
        y_min = min(values)
    try:
        y_max = (
            float(str(upper_bound)) if upper_bound is not None else max(values)
        )
    except (ValueError, TypeError):
        y_max = max(values)

    # Flat-line or inverted-bounds guard: ensure a positive range.
    if y_max <= y_min:
        y_max = y_min + 1.0

    # Enforce minimum Y-axis range to prevent over-amplifying small
    # fluctuations (e.g. temperature stable at ±0.1°C).
    if min_bound_range is not None:
        try:
            mbr = float(str(min_bound_range))
        except (ValueError, TypeError):
            mbr = 0.0
        if mbr > 0 and (y_max - y_min) < mbr:
            center = (y_max + y_min) / 2.0
            y_min = center - mbr / 2.0
            y_max = center + mbr / 2.0

    return y_min, y_max

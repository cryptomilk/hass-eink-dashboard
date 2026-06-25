"""Graph widget context builder."""

from __future__ import annotations

from typing import cast

from ..const import DEFAULT_ROW_H, PADDING, DisplayConfig, Widget
from ._helpers import (
    _color_context,
    _entity_info_context,
    _widget_dim,
)


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
            ``line_width`` (graph line stroke width in pixels;
            default 2; doubled on 2-level displays),
            ``upper_bound`` (optional fixed Y-axis upper bound;
            auto-computed from data when omitted),
            ``lower_bound`` (optional fixed Y-axis lower bound;
            auto-computed when omitted),
            ``min_bound_range`` (not yet implemented; planned for
            Phase 2 — minimum Y-axis range to prevent
            over-amplifying small changes),
            ``show_fill`` (draw light-gray fill below the line;
            default ``True``),
            ``show_state`` (show current entity value in the
            header; default ``True``),
            ``show_name`` (show entity name in the header; default
            ``True``),
            ``show_icon`` (show icon in the header; default
            ``True``),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``graph.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing from
        states.  Full context includes widget dimensions, card
        style, metrics, colors, icon geometry, header text, and
        graph polyline/fill coordinates.
    """
    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    hours_to_show: int = int(float(widget.get("hours_to_show", 24)))
    points_per_hour: float = float(widget.get("points_per_hour", 0.5))
    aggregate_func: str = str(widget.get("aggregate_func", "avg"))
    line_width: int = int(float(widget.get("line_width", 2)))
    upper_bound = widget.get("upper_bound")
    lower_bound = widget.get("lower_bound")
    show_fill: bool = bool(widget.get("show_fill", True))
    show_state: bool = bool(widget.get("show_state", True))
    show_name: bool = bool(widget.get("show_name", True))
    show_icon: bool = bool(widget.get("show_icon", True))
    grayscale_levels = config.get("grayscale_levels", 16)

    # Default height: 5 rows to provide adequate graph space.
    svg_h = _widget_dim(widget, "h", 5 * DEFAULT_ROW_H)

    # Header occupies exactly one row; graph fills the rest.
    # _entity_info_context splits header_h 40/60 (name row vs
    # value row); the graph's gy1 origin depends on this ratio.
    header_h = DEFAULT_ROW_H

    # Translate show_icon to hide_icon for _entity_info_context.
    widget_ctx: Widget = dict(widget)
    widget_ctx["hide_icon"] = not show_icon

    ctx = _entity_info_context(widget_ctx, config, header_h, svg_w, svg_h)
    if ctx is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            **_color_context(),
        }

    # name_x = x_off + lpad (left content edge); icon_cx +
    # icon_r = svg_w - r_inset - rpad (right content edge
    # without icon overlap).
    gx1: int = cast("int", ctx["name_x"])
    gx2: int = cast("int", ctx["icon_cx"]) + cast("int", ctx["icon_r"])

    # Stroke width: user-configured, widened on 2-level displays.
    graph_stroke_w = line_width * 2 if grayscale_levels <= 2 else line_width
    # Inset graph area by 2× stroke so line stays within bounds.
    margin = graph_stroke_w * 2
    gy1 = header_h + margin
    gy2 = svg_h - margin

    # --- History to polyline coordinates ---
    polyline_points = ""
    fill_points = ""

    entity_id: str = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id, {})
    history: list[dict[str, object]] = state.get("history", [])

    # Filter to the hours_to_show time window.
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
        # Bucket entries by time offset from the most recent point.
        bucket_size = 3600.0 / max(points_per_hour, 0.001)
        t_max = max(t for t, _ in numeric)

        buckets: dict[int, list[tuple[float, float]]] = {}
        for t, v in numeric:
            idx = int((t_max - t) / bucket_size)
            if idx not in buckets:
                buckets[idx] = []
            buckets[idx].append((t, v))

        # Aggregate each bucket to one representative point.
        bucketed: list[tuple[float, float]] = []
        for idx, entries in buckets.items():
            # Representative time anchored to the bucket boundary.
            t_repr = t_max - idx * bucket_size
            vals = [v for _, v in entries]
            if aggregate_func == "min":
                agg_val: float = min(vals)
            elif aggregate_func == "max":
                agg_val = max(vals)
            elif aggregate_func == "first":
                # Earliest timestamp in the bucket.
                agg_val = min(entries, key=lambda e: e[0])[1]
            elif aggregate_func == "last":
                # Latest timestamp in the bucket.
                agg_val = max(entries, key=lambda e: e[0])[1]
            elif aggregate_func == "sum":
                agg_val = sum(vals)
            else:
                # Default: average.
                agg_val = sum(vals) / len(vals)
            bucketed.append((t_repr, agg_val))

        # Sort oldest → newest for coordinate mapping.
        bucketed.sort(key=lambda p: p[0])

        # Fall back to raw data if bucketing yields < 2 points.
        points = bucketed if len(bucketed) >= 2 else numeric

        values = [v for _, v in points]
        try:
            y_min = (
                float(str(lower_bound))
                if lower_bound is not None
                else min(values)
            )
        except (ValueError, TypeError):
            y_min = min(values)
        try:
            y_max = (
                float(str(upper_bound))
                if upper_bound is not None
                else max(values)
            )
        except (ValueError, TypeError):
            y_max = max(values)
        # Flat-line or inverted-bounds guard: ensure a positive range.
        if y_max <= y_min:
            y_max = y_min + 1.0

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
        polyline_points = " ".join(f"{px},{py}" for px, py in pts)
        if show_fill:
            bottom = gy2
            fill_pts = [
                *pts,
                (pts[-1][0], bottom),
                (pts[0][0], bottom),
            ]
            fill_points = " ".join(f"{px},{py}" for px, py in fill_pts)

    return {
        **ctx,
        "has_graph": bool(polyline_points),
        "polyline_points": polyline_points,
        "fill_points": fill_points,
        "graph_stroke_w": graph_stroke_w,
        "hide_state": not show_state,
        "show_name": show_name,
    }

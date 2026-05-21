"""Sensor widget context builder."""

from __future__ import annotations

from typing import Any, cast

from ..const import DEFAULT_ROW_H, PADDING
from ..svg_render import (
    _color_context,
    _entity_info_context,
    _widget_dim,
)

type Widget = dict[str, Any]
type DisplayConfig = dict[str, Any]


def _build_sensor_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the sensor widget.

    Renders a header row (entity name on the left, optional icon on
    the right), an info section (large state value with unit), and
    an optional history sparkline graph below.  Mirrors HA's Sensor
    card.

    Icon style follows the same auto-resolution logic as the Entity
    widget: active states → filled circle; inactive or 2-level
    displays → outlined circle; ``icon_style="none"`` hides the
    circle entirely.

    Without ``graph="line"``, the default height is
    ``2 * DEFAULT_ROW_H``.  With ``graph="line"``, the default is
    ``3 * DEFAULT_ROW_H`` (entity section + graph row).  History
    data is read from ``states[entity_id]["history"]``, injected by
    ``_fetch_history()`` in ``__init__.py``.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, required),
            ``name`` (display name override),
            ``icon`` (MDI icon name, e.g. ``"mdi:thermometer"``),
            ``unit`` (unit string override),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``),
            ``graph`` (``"line"`` to enable history sparkline),
            ``hours_to_show`` (history window in hours; default
            24),
            ``detail`` (``1`` for downsampled ~24 pts, ``2`` for
            full resolution; default 1),
            ``limits`` (dict with optional ``"min"``/``"max"``
            keys to fix the Y-axis range; editor uses flat
            ``limits_min``/``limits_max`` keys instead),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``sensor.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing.
        Full context includes widget dimensions, card style,
        metrics, colors, icon geometry, header text, info section
        value/unit, and graph polyline/fill data.
    """
    from ..render import DEFAULT_METRICS

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    graph: str | None = widget.get("graph")
    detail: int = int(float(widget.get("detail", 1)))
    hours_to_show: int = int(float(widget.get("hours_to_show", 24)))
    limits: dict[str, float] | None = widget.get("limits")
    if limits is None:
        # The frontend stores Y-axis bounds as flat keys rather
        # than a nested dict (ha-form does not support nested
        # objects).
        lmin = widget.get("limits_min")
        lmax = widget.get("limits_max")
        if lmin is not None or lmax is not None:
            limits = {}
            if lmin is not None:
                limits["min"] = lmin
            if lmax is not None:
                limits["max"] = lmax
    grayscale_levels = config.get("grayscale_levels", 16)

    has_graph = graph == "line"
    # Default height: 3 rows with graph section, 2 rows without.
    default_h = 3 * DEFAULT_ROW_H if has_graph else 2 * DEFAULT_ROW_H
    svg_h = _widget_dim(widget, "h", default_h)
    # Graph occupies the bottom DEFAULT_ROW_H pixels; entity
    # section fills the rest.
    graph_h = DEFAULT_ROW_H if has_graph else 0
    entity_h = max(1, svg_h - graph_h)

    ctx = _entity_info_context(widget, config, entity_h, svg_w, svg_h)
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

    # --- Graph section ---
    polyline_points = ""
    fill_points = ""
    # Graph stroke uses DEFAULT_METRICS (fixed at DEFAULT_ROW_H)
    # because the graph zone is always DEFAULT_ROW_H pixels tall
    # regardless of entity section height.  Widened 2× on 2-level
    # displays.
    graph_stroke_w = (
        DEFAULT_METRICS.border * 2
        if grayscale_levels <= 2
        else DEFAULT_METRICS.border
    )

    if has_graph:
        entity_id: str = widget.get("entity", "")
        state = config.get("states", {}).get(entity_id, {})
        history: list[dict[str, object]] = state.get("history", [])
        # Apply hours_to_show window: keep only entries whose
        # timestamp falls within the most recent hours_to_show
        # hours.
        if history:
            t_latest = max(float(str(e.get("lu", 0))) for e in history)
            cutoff = t_latest - hours_to_show * 3600
            history = [
                e for e in history if float(str(e.get("lu", 0))) > cutoff
            ]
        # Filter entries to numeric values only; skip
        # unavailable / unknown / on/off states so only
        # plottable data remains.
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
            # Downsample to ~24 points for detail=1 to avoid
            # pixel-level noise on small sparklines.
            if detail <= 1 and len(numeric) > 24:
                step = len(numeric) / 24
                indices = {round(i * step) for i in range(24)}
                indices.add(len(numeric) - 1)
                numeric = [
                    numeric[i] for i in sorted(indices) if i < len(numeric)
                ]

            # Y range: explicit limits override auto min/max.
            # isinstance guard rejects null or string values
            # gracefully.
            values = [v for _, v in numeric]
            y_min = (
                float(limits["min"])
                if limits
                and "min" in limits
                and isinstance(limits["min"], (int, float))
                else min(values)
            )
            y_max = (
                float(limits["max"])
                if limits
                and "max" in limits
                and isinstance(limits["max"], (int, float))
                else max(values)
            )
            if y_max == y_min:
                # Flat line: add a unit pad so the polyline
                # is centred rather than collapsed to the
                # bottom edge.
                y_max += 1.0

            # Inset by 2× stroke width so the polyline stays
            # inside the widget bounds (wider on 2-level
            # displays).
            margin = graph_stroke_w * 2
            gy1 = entity_h + margin
            gy2 = svg_h - margin

            timestamps = [t for t, _ in numeric]
            t_min = min(timestamps)
            t_range = max(max(timestamps) - t_min, 1.0)
            y_range = y_max - y_min

            # Map (timestamp, value) → (x, y) pixel; Y is
            # inverted.
            pts = [
                (
                    round(gx1 + (t - t_min) / t_range * (gx2 - gx1)),
                    round(gy2 - (v - y_min) / y_range * (gy2 - gy1)),
                )
                for t, v in numeric
            ]
            polyline_points = " ".join(f"{px},{py}" for px, py in pts)
            # Fill polygon rendered on all display types; on
            # 2-level displays Floyd-Steinberg dithering in
            # optimize.py converts the light-gray fill to a
            # dot pattern.
            bottom = gy2
            fill_pts = [
                *pts,
                (pts[-1][0], bottom),
                (pts[0][0], bottom),
            ]
            fill_points = " ".join(f"{px},{py}" for px, py in fill_pts)

    return {
        **ctx,
        # Graph.
        "has_graph": has_graph,
        "polyline_points": polyline_points,
        "fill_points": fill_points,
        "graph_stroke_w": graph_stroke_w,
    }

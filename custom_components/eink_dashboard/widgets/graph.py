"""Graph widget context builder."""

from __future__ import annotations

import datetime
import logging
from typing import Any, cast

from ..const import (
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
)
from ._helpers import (
    _card_insets,
    _color_context,
    _entity_info_context,
    _fmt,
    _widget_dim,
)

_LOGGER = logging.getLogger(__name__)

# SVG stroke-dasharray patterns for multi-entity line styles.
# Index 0 (solid) has no dasharray; index 1 is dashed; index 2
# is dotted.  Empty string means attribute is omitted in template.
_DASH_PATTERNS: tuple[str, ...] = ("", "8,4", "2,4")


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
        # %-I is GNU libc-only; lstrip("0") is portable.
        return dt.strftime("%I:%M %p").lstrip("0")
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


def _secondary_label_geometry(
    y_min: float,
    y_max: float,
    gx2: int,
    label_font_sz: int,
    config: DisplayConfig,
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

    Returns:
        Tuple of ``(new_gx2, y2_label_right_x, y2_min_str,
        y2_max_str)`` where ``new_gx2`` is the adjusted right
        edge and the strings are the formatted Y-axis labels.
    """
    from ..render import _load_font

    y2_min_str = _fmt(f"{y_min:.1f}", config)
    y2_max_str = _fmt(f"{y_max:.1f}", config)
    font = _load_font(label_font_sz)
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


def _fix_header_layout(
    ctx: dict[str, object],
    widget: Widget,
    config: DisplayConfig,
    header_h: int,
    svg_w: int,
    grayscale_levels: int,
) -> tuple[int, int]:
    """Override header layout fields in the context from _entity_info_context.

    ``_entity_info_context`` is designed for a tall two-zone section
    (40% header + 60% value).  For the graph widget's compact single
    row the font sizes and icon geometry must be re-derived from
    ``_compute_metrics(header_h)`` so they match the standard row
    height proportions used by the tile and heading widgets.

    Returns ``(gx1, gx2)`` — the left and right graph area edges
    computed from card insets, decoupled from icon geometry.

    Args:
        ctx: Context dict returned by ``_entity_info_context``; mutated
            in place.
        widget: Widget config dict.
        config: Display config.
        header_h: Pixel height of the header row.
        svg_w: Full widget width.
        grayscale_levels: Display grayscale depth.

    Returns:
        ``(gx1, gx2)`` — left and right graph area pixel edges.
    """
    from ..render import _compute_metrics, _load_font

    m_hdr = _compute_metrics(header_h)
    card_style = str(widget.get("card_style", DEFAULT_CARD_STYLE))
    x_off, r_inset, _bar_w = _card_insets(m_hdr, card_style, grayscale_levels)
    lpad = m_hdr.padding if x_off == 0 else 0
    rpad = m_hdr.padding if r_inset == 0 else 0

    ctx["name_font_sz"] = m_hdr.font_primary
    ctx["name_y"] = header_h // 2
    ctx["value_font_sz"] = m_hdr.font_secondary
    ctx["value_y"] = header_h // 2
    ctx["unit_font_sz"] = m_hdr.font_secondary
    ctx["unit_y"] = header_h // 2

    # When the name is shown, value_x must be shifted right past the
    # name text; otherwise name and value land on the same x coordinate.
    show_name = bool(widget.get("show_name", True))
    name_text_str = str(ctx.get("name_text", ""))
    if show_name and name_text_str:
        nf = _load_font(m_hdr.font_primary, medium=True)
        name_w = round(nf.getlength(name_text_str))
        ctx["value_x"] = cast("int", ctx["name_x"]) + name_w + m_hdr.inner_gap

    value_text_str = str(ctx.get("value_text", ""))
    unit_text_str = str(ctx.get("unit_text", ""))
    value_x = cast("int", ctx["value_x"])
    ctx["unit_x"] = value_x
    if unit_text_str and value_text_str:
        vf = _load_font(m_hdr.font_secondary, medium=True)
        ctx["unit_x"] = (
            value_x
            + round(vf.getlength(value_text_str))
            + m_hdr.inner_gap // 2
        )

    icon_r = m_hdr.icon_dia // 2
    icon_cx = svg_w - r_inset - rpad - icon_r
    icon_cy = r_inset + icon_r if r_inset else header_h // 2
    ctx["icon_r"] = icon_r
    ctx["icon_cx"] = icon_cx
    ctx["icon_cy"] = icon_cy
    ctx["icon_glyph_x"] = icon_cx - m_hdr.icon_inner // 2
    ctx["icon_glyph_y"] = icon_cy - m_hdr.icon_inner // 2
    ctx["letter_font_sz"] = m_hdr.font_letter

    return x_off + lpad, svg_w - r_inset - rpad


def _legend_geometry(
    entity_descs: list[dict[str, object]],
    states: dict[str, Any],
    gx1: int,
    gy2: int,
    label_font_sz: int,
    graph_h: int,
) -> tuple[int, int, list[dict[str, object]]]:
    """Compute legend layout below the graph area.

    Builds a horizontal legend row with one entry per entity: a short
    line sample (with the entity's dash pattern) followed by the
    entity name.  The legend is placed at ``gy2`` and that boundary
    is shifted upward to reserve space.

    Args:
        entity_descs: Normalized entity descriptor list from
            ``_normalize_entities()``.
        states: States dict for resolving entity friendly names.
        gx1: Left edge of the graph area.
        gy2: Current bottom edge of the graph area (shifted up).
        label_font_sz: Font size from axis labels; 0 triggers the
            same fallback formula as ``_label_geometry``.
        graph_h: Graph area pixel height used when
            ``label_font_sz`` is 0.

    Returns:
        Tuple of ``(new_gy2, legend_y, legend_entries)`` where
        ``legend_entries`` is a list of dicts each containing
        ``name``, ``line_x1``, ``line_x2``, ``line_y``,
        ``text_x``, ``text_y``, ``stroke_dasharray``, and
        ``font_sz``.
    """
    from ..render import _load_font

    font_sz = label_font_sz or max(10, round(graph_h * 0.06))
    legend_font = _load_font(font_sz)
    line_sample_w = font_sz * 2
    gap = font_sz // 2
    legend_h = font_sz + gap
    legend_y = gy2
    new_gy2 = gy2 - legend_h

    entries: list[dict[str, object]] = []
    x = gx1
    # Centre each line sample and text label vertically within the
    # legend band.
    entry_mid_y = legend_y + legend_h // 2
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
        entries.append(
            {
                "name": name,
                "line_x1": x,
                "line_x2": x + line_sample_w,
                "line_y": entry_mid_y,
                "text_x": x + line_sample_w + gap,
                "text_y": entry_mid_y,
                "stroke_dasharray": str(desc.get("dash", "")),
                "font_sz": font_sz,
            }
        )
        text_w = round(legend_font.getlength(name))
        x += line_sample_w + gap + text_w + gap * 2
    return new_gy2, legend_y, entries


def _extract_entity_points(
    desc: dict[str, object],
    states_dict: dict[str, Any],
    hours_to_show: int,
    points_per_hour: float,
    aggregate_func: str,
) -> list[tuple[float, float]]:
    """Extract and aggregate history data for one entity descriptor.

    Reads the entity's raw history from ``states_dict``, filters to
    the ``hours_to_show`` time window, strips non-numeric entries, and
    buckets the result via ``_aggregate_history``.

    Args:
        desc: Entity descriptor dict from ``_normalize_entities()``.
        states_dict: States dict from the display config.
        hours_to_show: History window in hours.
        points_per_hour: Target data density for bucketing.
        aggregate_func: Bucket reduction function name.

    Returns:
        Sorted oldest-to-newest list of ``(timestamp, value)`` pairs,
        or an empty list when fewer than two numeric entries remain
        after filtering.
    """
    eid = str(desc["entity"])
    state = states_dict.get(eid, {})
    raw_hist: list[dict[str, object]] = (
        list(state.get("history", [])) if isinstance(state, dict) else []
    )
    if raw_hist:
        t_latest = max(float(str(e.get("lu", 0))) for e in raw_hist)
        cutoff = t_latest - hours_to_show * 3600
        raw_hist = [e for e in raw_hist if float(str(e.get("lu", 0))) > cutoff]
    numeric: list[tuple[float, float]] = []
    for entry in raw_hist:
        s = entry.get("s", "")
        lu = entry.get("lu", 0.0)
        try:
            val = float(str(s))
            numeric.append((float(str(lu)), val))
        except (ValueError, TypeError):
            continue
    if len(numeric) >= 2:
        return _aggregate_history(numeric, points_per_hour, aggregate_func)
    return []


def _normalize_entities(
    widget: Widget,
) -> list[dict[str, object]]:
    """Normalize widget config into a canonical entity descriptor list.

    Accepts either the single-entity format (``entity`` string key)
    or the multi-entity format (``entities`` list of dicts).  When
    both are present ``entities`` takes precedence.  Flat editor keys
    ``entity_2`` / ``entity_3`` are also handled for widgets saved by
    the editor UI.

    Args:
        widget: Widget config dict.

    Returns:
        List of entity descriptor dicts, each with keys ``entity``
        (str), ``name`` (str, empty when not overridden), ``y_axis``
        (``"primary"`` or ``"secondary"``), ``line_style``
        (``"solid"``, ``"dashed"``, or ``"dotted"``), and ``dash``
        (the SVG ``stroke-dasharray`` value, empty for solid).
        Maximum 3 entries.  Returns an empty list when no entity
        source is found.
    """
    _STYLE_MAP: dict[str, int] = {"solid": 0, "dashed": 1, "dotted": 2}
    raw: list[dict[str, object]] = []

    entities_cfg = widget.get("entities")
    if isinstance(entities_cfg, list) and entities_cfg:
        raw.extend(
            item
            for item in entities_cfg
            if isinstance(item, dict) and item.get("entity")
        )
        if not raw:
            _LOGGER.warning(
                "Graph widget 'entities' list has no valid items "
                "(each item must be a dict with an 'entity' key); "
                "falling back to single-entity mode"
            )
    else:
        eid = str(widget.get("entity", ""))
        if eid:
            raw.append({"entity": eid})
        for suffix in ("_2", "_3"):
            eid2 = str(widget.get(f"entity{suffix}", ""))
            if eid2:
                raw.append(
                    {
                        "entity": eid2,
                        "name": str(widget.get(f"name{suffix}", "")),
                        "y_axis": str(
                            widget.get(f"y_axis{suffix}", "primary")
                        ),
                    }
                )

    result: list[dict[str, object]] = []
    for i, item in enumerate(raw[:3]):
        style = str(item.get("line_style", ""))
        idx = _STYLE_MAP.get(style, i)
        idx = min(idx, 2)
        style_name = ("solid", "dashed", "dotted")[idx]
        result.append(
            {
                "entity": str(item.get("entity", "")),
                "name": str(item.get("name", "")),
                "y_axis": str(item.get("y_axis", "primary")),
                "line_style": style_name,
                "dash": _DASH_PATTERNS[idx],
            }
        )
    return result


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

    Supports both single-entity mode (``entity`` string key) and
    multi-entity mode (``entities`` list of dicts).  Multiple entities
    are overlaid on the same graph with distinct dash patterns (solid,
    dashed, dotted).  Only the first entity receives a fill area.
    A legend is shown automatically when more than one entity is
    configured.  Entities with ``y_axis: "secondary"`` use a separate
    Y scale with labels on the right side of the graph.

    History data is read from ``states[entity_id]["history"]``,
    injected by ``_fetch_history()`` in ``__init__.py``.  Raw entries
    are filtered to the ``hours_to_show`` time window, grouped into
    fixed-width time buckets using ``points_per_hour``, then reduced
    to a single representative value per bucket via ``aggregate_func``.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, single-entity mode),
            ``entities`` (list of dicts, multi-entity mode;
            takes precedence over ``entity``),
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
            ``show_fill`` (draw light-gray fill below the first
            entity's line; default ``True``),
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
        **_color_context()}`` when no entity is present in states.
        Full context includes widget dimensions, card style, metrics,
        colors, icon geometry, header text, series list, and optional
        axis labels, grid lines, extrema, secondary Y-axis labels,
        and legend.
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

    # --- Normalize entity list ---
    entity_descs = _normalize_entities(widget)
    if not entity_descs:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            **_color_context(),
        }

    # Header uses the first entity.  If it is missing from states,
    # try subsequent entities so the header is never blank.
    ctx = None
    for desc in entity_descs:
        eid = str(desc["entity"])
        name_override = str(desc.get("name", ""))
        hw: dict[str, object] = {
            **widget,
            "entity": eid,
            "hide_icon": not show_icon,
        }
        if name_override:
            hw["name"] = name_override
        ctx = _entity_info_context(hw, config, header_h, svg_w, svg_h)
        if ctx is not None:
            break

    if ctx is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            **_color_context(),
        }

    gx1, gx2 = _fix_header_layout(
        ctx, widget, config, header_h, svg_w, grayscale_levels
    )

    # Stroke width: user-configured, widened on 2-level displays.
    graph_stroke_w = line_width * 2 if grayscale_levels <= 2 else line_width
    # Inset graph area by 2× stroke so line stays within bounds.
    margin = graph_stroke_w * 2
    gy1 = header_h + margin
    gy2 = svg_h - margin

    # --- Per-entity history extraction ---
    states_dict: dict[str, object] = config.get("states", {})
    per_entity_points: list[list[tuple[float, float]]] = [
        _extract_entity_points(
            desc,
            states_dict,
            hours_to_show,
            points_per_hour,
            aggregate_func,
        )
        for desc in entity_descs
    ]

    # --- Y bounds per axis ---
    primary_values: list[float] = []
    secondary_values: list[float] = []
    for i, desc in enumerate(entity_descs):
        ep = per_entity_points[i]
        if not ep:
            continue
        vals = [v for _, v in ep]
        if str(desc.get("y_axis", "primary")) == "secondary":
            secondary_values.extend(vals)
        else:
            primary_values.extend(vals)

    has_primary = bool(primary_values)
    has_secondary = bool(secondary_values)

    prim_y_min, prim_y_max = (
        _y_bounds(primary_values, lower_bound, upper_bound, min_bound_range)
        if has_primary
        else (0.0, 1.0)
    )
    sec_y_min, sec_y_max = (
        _y_bounds(secondary_values, None, None, None)
        if has_secondary
        else (0.0, 1.0)
    )

    # Label / grid / extrema context — populated inside data guard.
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

    # Collect all points from all entities for shared axis geometry.
    all_points: list[tuple[float, float]] = [
        p for ep in per_entity_points for p in ep
    ]
    # Use primary-axis points for label/extrema (first primary entity
    # that has data).
    primary_points: list[tuple[float, float]] = []
    for i, desc in enumerate(entity_descs):
        ep = per_entity_points[i]
        if ep and str(desc.get("y_axis", "primary")) != "secondary":
            primary_points = ep
            break
    if not primary_points and all_points:
        primary_points = per_entity_points[0]

    if primary_points:
        if show_labels:
            # Use pre-adjustment height for font sizing so it is
            # proportional to the widget's total graph allocation.
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
                primary_points,
                prim_y_min,
                prim_y_max,
                gx1,
                gy2,
                config,
                graph_h,
            )
            show_labels_ctx = True

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
                primary_points, label_font_sz, gy2, config, graph_h_ex
            )

        # Grid lines at the final graph-area top and bottom edges.
        grid_y_top = gy1
        grid_y_bot = gy2
        # Suppress fine gray lines on 2-level (B&W) displays.
        show_grid = show_labels_ctx and grayscale_levels > 2

    # --- Secondary Y-axis labels (shifts gx2 inward) ---
    show_secondary_labels = False
    y2_label_right_x = gx2
    y2_min_str = ""
    y2_max_str = ""
    y2_min_label_y = gy2
    y2_max_label_y = gy1
    # label_font_sz stays 0 when show_labels is True but primary
    # data is empty — _secondary_label_geometry needs a positive font
    # size, so the > 0 guard is not redundant with show_labels.
    if has_secondary and show_labels and label_font_sz > 0:
        (
            gx2,
            y2_label_right_x,
            y2_min_str,
            y2_max_str,
        ) = _secondary_label_geometry(
            sec_y_min, sec_y_max, gx2, label_font_sz, config
        )
        show_secondary_labels = True
        y2_min_label_y = gy2
        y2_max_label_y = gy1

    # --- Legend (shown when >1 entity configured) ---
    show_legend = len(entity_descs) > 1
    legend_y = gy2
    legend_entries: list[dict[str, object]] = []
    if show_legend and all_points:
        graph_h_leg = gy2 - gy1
        gy2, legend_y, legend_entries = _legend_geometry(
            entity_descs,
            states_dict,
            gx1,
            gy2,
            label_font_sz,
            graph_h_leg,
        )

    # --- Shared X range (union of all entities' timestamps) ---
    all_timestamps = [t for ep in per_entity_points for t, _ in ep]
    if all_timestamps:
        t_min = min(all_timestamps)
        t_max_all = max(all_timestamps)
        t_range = max(t_max_all - t_min, 1.0)
    else:
        t_min, t_range = 0.0, 1.0

    # --- Build series list ---
    series: list[dict[str, object]] = []
    has_any_data = False
    first_with_data_seen = False
    for desc, ep in zip(entity_descs, per_entity_points, strict=False):
        if not ep:
            series.append(
                {
                    "polyline_points": "",
                    "graph_path": "",
                    "fill_path": "",
                    "fill_points": "",
                    "stroke_dasharray": str(desc.get("dash", "")),
                    "has_data": False,
                }
            )
            continue

        has_any_data = True
        is_secondary = str(desc.get("y_axis", "primary")) == "secondary"
        y_min_s = sec_y_min if is_secondary else prim_y_min
        y_max_s = sec_y_max if is_secondary else prim_y_max
        y_range_s = y_max_s - y_min_s

        pxpts = [
            (
                round(gx1 + (t - t_min) / t_range * (gx2 - gx1)),
                round(gy2 - (v - y_min_s) / y_range_s * (gy2 - gy1)),
            )
            for t, v in ep
        ]

        # Only the first entity with data receives a fill area.
        do_fill = show_fill and not first_with_data_seen
        first_with_data_seen = True

        gp = fp = pp = fpts = ""
        if smoothing:
            gp = _smooth_path(pxpts)
            if do_fill and gp:
                fp = _smooth_fill(gp, pxpts, gy2)
        else:
            pp = " ".join(f"{px},{py}" for px, py in pxpts)
            if do_fill:
                fill_poly = [
                    *pxpts,
                    (pxpts[-1][0], gy2),
                    (pxpts[0][0], gy2),
                ]
                fpts = " ".join(f"{px},{py}" for px, py in fill_poly)

        series.append(
            {
                "polyline_points": pp,
                "graph_path": gp,
                "fill_path": fp,
                "fill_points": fpts,
                "stroke_dasharray": str(desc.get("dash", "")),
                "has_data": True,
            }
        )

    return {
        **ctx,
        "has_graph": has_any_data,
        "series": series,
        "graph_stroke_w": graph_stroke_w,
        "grid_stroke_w": max(1, graph_stroke_w // 2),
        "hide_state": not show_state,
        "show_name": show_name,
        # Primary axis labels.
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
        # Secondary Y-axis labels.
        "show_secondary_labels": show_secondary_labels,
        "y2_label_right_x": y2_label_right_x,
        "y2_min_str": y2_min_str,
        "y2_max_str": y2_max_str,
        "y2_min_label_y": y2_min_label_y,
        "y2_max_label_y": y2_max_label_y,
        # Legend.
        "show_legend": show_legend and has_any_data,
        "legend_y": legend_y,
        "legend_entries": legend_entries,
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

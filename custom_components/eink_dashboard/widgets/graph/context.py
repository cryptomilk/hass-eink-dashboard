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

"""Graph widget context builder."""

from __future__ import annotations

import datetime
from typing import Any, cast

from ...const import (
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
)
from .._helpers import (
    _card_insets,
    _color_context,
    _entity_info_context,
    _fmt,
    _widget_dim,
)
from .colors import _BAR_FILL_COLORS, _normalize_thresholds
from .data import (
    _extract_attribute_points,
    _extract_entity_points,
    _normalize_entities,
    _resolve_start_cutoff,
    _y_bounds,
)
from .geometry import (
    _extrema_geometry,
    _label_geometry,
    _legend_geometry,
    _secondary_label_geometry,
    _truncate_to_width,
)
from .series import _bar_series, _line_series


def _fix_header_layout(
    ctx: dict[str, object],
    widget: Widget,
    header_h: int,
    svg_w: int,
    display_levels: int,
    *,
    state_font_sz: int | None = None,
) -> tuple[int, int]:
    """Override header layout fields in the context from _entity_info_context.

    ``_entity_info_context`` is designed for a tall two-zone section
    (40% header + 60% value).  For the graph widget's compact single
    row the font sizes and icon geometry must be re-derived from
    ``_compute_metrics(header_h)`` so they match the standard row
    height proportions used by the tile and heading widgets.

    ``ctx["value_text"]`` is truncated in place to fit between
    ``value_x`` and the icon (or the right card inset, when the icon
    is hidden), so callers that set an unusually long value string
    — e.g. the multi-entity combined state text — must do so before
    calling this function.

    Returns ``(gx1, gx2)`` — the left and right graph area edges
    computed from card insets, decoupled from icon geometry.

    Args:
        ctx: Context dict returned by ``_entity_info_context``; mutated
            in place.
        widget: Widget config dict.
        header_h: Pixel height of the header row.
        svg_w: Full widget width.
        display_levels: Display grayscale depth.
        state_font_sz: Optional override for the value/unit font
            size in pixels, from the widget's ``state_font_size``
            config key. Falls back to ``m_hdr.font_secondary`` when
            omitted.

    Returns:
        ``(gx1, gx2)`` — left and right graph area pixel edges.
    """
    from ...render import _compute_metrics, _load_font

    m_hdr = _compute_metrics(header_h)
    card_style = str(widget.get("card_style", DEFAULT_CARD_STYLE))
    x_off, r_inset, _bar_w = _card_insets(m_hdr, card_style, display_levels)
    lpad = m_hdr.padding if x_off == 0 else 0
    rpad = m_hdr.padding if r_inset == 0 else 0
    value_unit_font_sz = (
        state_font_sz if state_font_sz is not None else m_hdr.font_secondary
    )

    ctx["name_font_sz"] = m_hdr.font_primary
    ctx["name_y"] = header_h // 2
    ctx["value_font_sz"] = value_unit_font_sz
    ctx["value_y"] = header_h // 2
    ctx["unit_font_sz"] = value_unit_font_sz
    ctx["unit_y"] = header_h // 2

    # When the name is shown, value_x must be shifted right past the
    # name text; otherwise name and value land on the same x coordinate.
    show_name = bool(widget.get("show_name", True))
    name_text_str = str(ctx.get("name_text", ""))
    if show_name and name_text_str:
        nf = _load_font(m_hdr.font_primary, medium=True)
        name_w = round(nf.getlength(name_text_str))
        ctx["value_x"] = cast("int", ctx["name_x"]) + name_w + m_hdr.inner_gap

    icon_r = m_hdr.icon_dia // 2
    icon_cx = svg_w - r_inset - rpad - icon_r
    icon_cy = r_inset + icon_r if r_inset else header_h // 2
    ctx["icon_r"] = icon_r
    ctx["icon_cx"] = icon_cx
    ctx["icon_cy"] = icon_cy
    ctx["icon_glyph_x"] = icon_cx - m_hdr.icon_inner // 2
    ctx["icon_glyph_y"] = icon_cy - m_hdr.icon_inner // 2
    ctx["letter_font_sz"] = m_hdr.font_letter

    # Value text must not run into the icon (or the right card inset
    # when the icon is hidden) — the multi-entity header's combined
    # state string can be much longer than a single entity's value.
    icon_shown = bool(ctx.get("icon_svg")) or bool(ctx.get("letter"))
    right_bound = (
        icon_cx - icon_r - m_hdr.inner_gap
        if icon_shown
        else svg_w - r_inset - rpad
    )
    value_text_str = str(ctx.get("value_text", ""))
    unit_text_str = str(ctx.get("unit_text", ""))
    value_x = cast("int", ctx["value_x"])
    value_bold = bool(ctx["value_bold"])
    vf = _load_font(value_unit_font_sz, medium=not value_bold, bold=value_bold)
    if value_text_str:
        value_text_str = _truncate_to_width(
            value_text_str, vf, max(0, right_bound - value_x)
        )
        ctx["value_text"] = value_text_str

    ctx["unit_x"] = value_x
    if unit_text_str and value_text_str:
        ctx["unit_x"] = (
            value_x
            + round(vf.getlength(value_text_str))
            + m_hdr.inner_gap // 2
        )

    return x_off + lpad, svg_w - r_inset - rpad


def _combined_state_text(
    entity_descs: list[dict[str, object]],
    states: dict[str, Any],
    config: DisplayConfig,
    show_state: bool,
    widget: Widget,
) -> str | None:
    """Build a " / "-joined state string for multi-entity headers.

    Args:
        entity_descs: Normalized entity descriptor list from
            ``_normalize_entities()``.
        states: States dict for resolving entity state and unit.
        config: Display config used for locale-aware number
            formatting via ``_fmt``.
        show_state: Widget's ``show_state`` setting; ``False``
            short-circuits to ``None`` without touching ``states``.
        widget: Widget config dict, consulted for the ``unit``
            override key. When set, it replaces every entity's
            auto-detected ``unit_of_measurement``, matching the
            single-entity behaviour in ``_entity_info_context``.

    Returns:
        The joined string of every entity with a usable (non-empty,
        known) state, or ``None`` when ``show_state`` is ``False``,
        only one entity is configured, or no entity has a usable
        state.
    """
    if not show_state or len(entity_descs) <= 1:
        return None
    unit_override = widget.get("unit")
    parts: list[str] = []
    for desc in entity_descs:
        eid = str(desc["entity"])
        st = states.get(eid, {})
        if not isinstance(st, dict):
            continue
        state_val = str(st.get("state", ""))
        if not state_val or state_val in ("unknown", "unavailable"):
            continue
        attrs = st.get("attributes", {})
        unit = (
            str(attrs.get("unit_of_measurement", ""))
            if isinstance(attrs, dict)
            else ""
        )
        if unit_override is not None:
            unit = str(unit_override)
        formatted = _fmt(state_val, config)
        parts.append(f"{formatted}{unit}" if unit else formatted)
    return " / ".join(parts) if parts else None


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
    injected by ``_fetch_history()`` in the integration's root
    ``__init__.py``.  Raw entries
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
            ``hours_to_show`` (history window in hours; default 24;
            ignored when ``start_time`` is set),
            ``start_time`` (time-of-day string, e.g. ``"00:00"``,
            parseable by ``datetime.time.fromisoformat``; when set,
            the graph shows data from this time today onward instead
            of a rolling ``hours_to_show`` window; empty/unparsable
            values are ignored; if the time has not occurred yet
            today, the graph shows no data until it does),
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
            ``secondary_upper_bound`` (optional fixed upper bound
            for the secondary Y-axis; auto-computed when omitted),
            ``secondary_lower_bound`` (optional fixed lower bound
            for the secondary Y-axis; auto-computed when omitted),
            ``smoothing`` (midpoint Q-curve path smoothing;
            default ``True``),
            ``show_fill`` (draw light-gray fill below the first
            entity's line; default ``True``),
            ``show_labels`` (show Y-axis min/max labels and X-axis
            time labels; default ``True``),
            ``show_extrema`` (show min/max values with timestamps
            below the graph; default ``False``),
            ``show_state`` (show current entity value in the
            header; default ``True``; when multiple entities are
            configured, every entity with a currently known state
            is shown concatenated with ``" / "``),
            ``show_name`` (show entity name in the header; default
            ``True``),
            ``show_icon`` (show icon in the header; default
            ``True``),
            ``show_legend`` (show the legend below the graph for
            multi-entity widgets; default ``True``; has no effect
            for single-entity widgets, which never show a legend),
            ``state_font_size`` (override the header value/unit font
            size in pixels; defaults to
            ``_compute_metrics(header_h).font_secondary`` when
            omitted),
            ``graph`` (chart type: ``"line"`` (default) for a line
            graph with polyline/path elements, or ``"bar"`` for a
            bar chart with ``<rect>`` elements; in bar mode
            ``smoothing`` and ``show_fill`` are ignored),
            ``bold_value`` (render the header value in bold;
            default ``False``),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``,
            ``display_levels``, and optionally ``time_format``
            (``"24"`` or ``"12"``; default ``"24"``).

    Returns:
        Template context dict consumed by ``graph.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when no entity is present in states.
        Full context includes widget dimensions, card style, metrics,
        colors, icon geometry, header text, series list, ``is_bar``
        (bool, ``True`` when ``graph="bar"``), ``legend_is_bar``
        (bool, controls rect vs line legend swatches), and optional
        axis labels, grid lines, extrema, secondary Y-axis labels,
        and legend.
    """
    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    hours_to_show: int = int(float(widget.get("hours_to_show", 24)))
    start_cutoff = _resolve_start_cutoff(
        str(widget.get("start_time", "")), datetime.datetime.now()
    )
    points_per_hour: float = float(widget.get("points_per_hour", 0.5))
    aggregate_func: str = str(widget.get("aggregate_func", "avg"))
    group_by: str = str(widget.get("group_by", "interval"))
    line_width: int = int(float(widget.get("line_width", 2)))
    upper_bound = widget.get("upper_bound")
    lower_bound = widget.get("lower_bound")
    min_bound_range = widget.get("min_bound_range")
    secondary_upper_bound = widget.get("secondary_upper_bound")
    secondary_lower_bound = widget.get("secondary_lower_bound")
    smoothing: bool = bool(widget.get("smoothing", True))
    show_fill: bool = bool(widget.get("show_fill", True))
    show_labels: bool = bool(widget.get("show_labels", True))
    show_extrema: bool = bool(widget.get("show_extrema", False))
    show_state: bool = bool(widget.get("show_state", True))
    show_name: bool = bool(widget.get("show_name", True))
    show_icon: bool = bool(widget.get("show_icon", True))
    show_legend: bool = bool(widget.get("show_legend", True))
    display_levels = config.get("display_levels", 16)
    # "line" (default) renders polyline/path; "bar" renders <rect>
    # elements.  smoothing and show_fill are ignored in bar mode.
    graph_type: str = str(widget.get("graph", "line"))
    is_bar: bool = graph_type == "bar"

    # --- Color thresholds ---
    # Normalise threshold list (canonical list or flat editor keys).
    # Suppressed on 2-level (B&W) displays where gradients produce
    # dithering artifacts; mirrors the grid-line suppression pattern.
    raw_thresholds = _normalize_thresholds(widget)
    threshold_transition: str = str(
        widget.get("color_thresholds_transition", "smooth")
    )
    has_thresholds: bool = len(raw_thresholds) >= 2 and display_levels > 2
    active_thresholds: list[dict[str, object]] = (
        raw_thresholds if has_thresholds else []
    )

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

    # --- Multi-entity state display ---
    # Header normally shows only the first entity's state; when
    # multiple entities are configured, concatenate every entity
    # with a usable state with " / " so all of them are visible.
    # This must run before _fix_header_layout() so the (possibly
    # much longer) combined text goes through its icon-overlap
    # truncation, not the original single-entity value.
    combined_state = _combined_state_text(
        entity_descs, config.get("states", {}), config, show_state, widget
    )
    if combined_state is not None:
        ctx["value_text"] = combined_state
        ctx["unit_text"] = ""

    state_font_size = widget.get("state_font_size")
    state_font_sz = (
        int(float(state_font_size)) if state_font_size is not None else None
    )
    gx1, gx2 = _fix_header_layout(
        ctx,
        widget,
        header_h,
        svg_w,
        display_levels,
        state_font_sz=state_font_sz,
    )

    # Stroke width: user-configured, widened on 2-level displays.
    graph_stroke_w = line_width * 2 if display_levels <= 2 else line_width
    # Inset graph area by 2× stroke so line stays within bounds.
    margin = graph_stroke_w * 2
    gy1 = header_h + margin
    gy2 = svg_h - margin

    # --- Per-entity data extraction ---
    # Entities with data_source="attribute" read a forecast-style
    # time-series list from a named entity attribute instead of the
    # recorder's state history.
    states_dict: dict[str, object] = config.get("states", {})
    per_entity_points: list[list[tuple[float, float]]] = []
    for desc in entity_descs:
        if str(desc.get("data_source", "history")) == "attribute":
            per_entity_points.append(
                _extract_attribute_points(desc, states_dict)
            )
        else:
            per_entity_points.append(
                _extract_entity_points(
                    desc,
                    states_dict,
                    hours_to_show,
                    points_per_hour,
                    aggregate_func,
                    start_cutoff,
                )
            )

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
        # min_bound_range has no secondary_min_bound_range
        # counterpart — only explicit min/max overrides are
        # exposed for the secondary axis, so this is always None.
        _y_bounds(
            secondary_values,
            secondary_lower_bound,
            secondary_upper_bound,
            None,
        )
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
    # Single source of truth for "is there any data to draw" — reused
    # for the legend-geometry gate, the final show_legend flag, and
    # has_graph, so the three can never desync from one another.
    has_any_data = bool(all_points)
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
                gy1,
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
        show_grid = show_labels_ctx and display_levels > 2

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
    multi_entity = len(entity_descs) > 1
    legend_y = gy2
    legend_entries: list[dict[str, object]] = []
    if multi_entity and has_any_data and show_legend:
        graph_h_leg = gy2 - gy1
        bar_fills_legend = _BAR_FILL_COLORS if is_bar else None
        gy2, legend_y, legend_entries = _legend_geometry(
            entity_descs,
            states_dict,
            gx1,
            gx2,
            gy2,
            label_font_sz,
            graph_h_leg,
            bar_fills=bar_fills_legend,
        )

    # --- Build series list ---
    if is_bar:
        # Bar mode: each entity's data points become <rect> elements.
        series: list[dict[str, object]] = _bar_series(
            per_entity_points,
            entity_descs,
            prim_y_min,
            prim_y_max,
            sec_y_min,
            sec_y_max,
            gx1,
            gx2,
            gy1,
            gy2,
            thresholds=active_thresholds,
            display_levels=display_levels,
        )
        # has_data per entity mirrors bool(ep), so this is always
        # equal to the has_any_data computed above from all_points;
        # reuse that single value rather than recomputing it here.
    else:
        # Line mode: delegate to helper to keep complexity in bounds.
        # has_any_data is set exactly when any entity has points,
        # so the returned value is always equal to the has_any_data
        # computed above from all_points; discard it and reuse the
        # single earlier value instead.
        series, _ = _line_series(
            per_entity_points,
            entity_descs,
            prim_y_min,
            prim_y_max,
            sec_y_min,
            sec_y_max,
            gx1,
            gx2,
            gy1,
            gy2,
            smoothing,
            show_fill,
            thresholds=active_thresholds,
            threshold_transition=threshold_transition,
            display_levels=display_levels,
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
        "show_legend": multi_entity and has_any_data and show_legend,
        "legend_y": legend_y,
        "legend_entries": legend_entries,
        # Bar chart mode flag consumed by the template.
        "is_bar": is_bar,
        # True when bar mode AND legend is visible: template uses
        # <rect> swatches instead of <line> dash-pattern samples.
        "legend_is_bar": is_bar,
        # Color thresholds: gradients for line graphs.
        # has_thresholds is False on 2-level displays or when fewer
        # than 2 thresholds are configured.
        "has_thresholds": has_thresholds and not is_bar,
        # Per-bar threshold fills active for bar chart mode.
        "threshold_bar_mode": has_thresholds and is_bar,
        # Graph area boundaries for gradient coordinate system.
        "gy1": gy1,
        "gy2": gy2,
    }

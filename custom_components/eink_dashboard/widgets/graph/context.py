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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from ...const import (
    COLOR_BLACK,
    COLOR_LIGHT_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    FontWeight,
    color_to_hex,
)
from .._helpers import (
    _card_insets,
    _entity_info_context,
    _fmt,
    _missing_entity_context,
    _resolve_precision,
    _widget_dim,
)
from .axes import (
    _bar_axis_ticks,
    _edge_ticks,
    _time_axis_ticks,
    _value_axis_ticks,
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
    _axis_font,
    _extrema_geometry,
    _legend_band_height,
    _legend_geometry,
    _truncate_to_width,
)
from .series import _bar_series, _line_series

if TYPE_CHECKING:
    from ...widget_config import GraphWidget

# Allowed range for x_axis_ticks / y_axis_ticks; matches the editor's
# number selector.  The minimum is also the default (min/max labels).
_MIN_AXIS_TICKS = 2
_MAX_AXIS_TICKS = 12


def _fix_header_layout(
    ctx: dict[str, object],
    widget: GraphWidget,
    header_h: int,
    svg_w: int,
    display_levels: int,
    *,
    state_font_sz: int | None = None,
    font_scale: float = 1.0,
) -> tuple[int, int]:
    """Override header layout fields in the context from _entity_info_context.

    ``_entity_info_context`` is designed for a tall two-zone section
    (40% header + 60% value).  For the graph widget's compact single
    row the font sizes and icon geometry must be re-derived from
    ``_compute_metrics(header_h)`` so they match the standard row
    height proportions used by the tile and heading widgets.

    Header text roles resolve through the shared ``resolve_font``
    API, so the widget's ``fonts`` overrides apply.  The legacy
    ``state_font_size`` key supplies the value/unit size fallback.

    ``ctx["value_text"]`` is truncated in place to fit between
    ``value_x`` and the icon (or the right card inset, when the icon
    is hidden), so callers that set an unusually long value string
    — e.g. the multi-entity combined state text — must do so before
    calling this function.

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
            omitted, and loses to an explicit ``fonts.value.size`` /
            ``fonts.unit.size``.
        font_scale: Display-level ``font_scale`` multiplier applied
            to derived sizes that have no explicit override.

    Returns:
        ``(gx1, gx2)`` — left and right graph area pixel edges.
    """
    from ...render import (
        _compute_metrics,
        _font_weight_svg,
        _load_role_font,
        resolve_font,
    )

    m_hdr = _compute_metrics(header_h)
    card_style = str(widget.get("card_style", DEFAULT_CARD_STYLE))
    x_off, r_inset, _bar_w = _card_insets(m_hdr, card_style, display_levels)
    lpad = m_hdr.padding if x_off == 0 else 0
    rpad = m_hdr.padding if r_inset == 0 else 0

    # Header text roles resolve through the shared API so the widget's
    # ``fonts`` overrides and the display-level ``font_scale`` apply.
    # ``state_font_size`` is the legacy fallback for the value/unit
    # size.
    value_unit_sz = (
        state_font_sz if state_font_sz is not None else m_hdr.font_secondary
    )

    name_font_sz, name_weight = resolve_font(
        widget,
        "name",
        m_hdr.font_primary,
        FontWeight.MEDIUM,
        scale=font_scale,
    )
    value_font_sz, value_weight = resolve_font(
        widget,
        "value",
        value_unit_sz,
        FontWeight.REGULAR,
        scale=font_scale,
    )
    unit_font_sz, unit_weight = resolve_font(
        widget,
        "unit",
        value_unit_sz,
        FontWeight.REGULAR,
        scale=font_scale,
    )

    ctx["name_font_sz"] = name_font_sz
    ctx["name_weight"] = _font_weight_svg(name_weight)
    ctx["name_y"] = header_h // 2
    ctx["value_font_sz"] = value_font_sz
    ctx["value_weight"] = _font_weight_svg(value_weight)
    ctx["value_y"] = header_h // 2
    ctx["unit_font_sz"] = unit_font_sz
    ctx["unit_weight"] = _font_weight_svg(unit_weight)
    ctx["unit_y"] = header_h // 2

    # When the name is shown, value_x must be shifted right past the
    # name text; otherwise name and value land on the same x coordinate.
    show_name = bool(widget.get("show_name", True))
    name_text_str = str(ctx.get("name_text", ""))
    if show_name and name_text_str:
        nf = _load_role_font(name_font_sz, name_weight)
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
    vf = _load_role_font(value_font_sz, value_weight)
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
    widget: GraphWidget,
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
            Also consulted for ``decimals``, which overrides each
            entity's HA ``display_precision`` and device-class
            default.

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
        precision = _resolve_precision(widget, st)
        formatted = _fmt(state_val, config, precision)
        parts.append(f"{formatted}{unit}" if unit else formatted)
    return " / ".join(parts) if parts else None


def _build_header_context(
    entity_descs: list[dict[str, object]],
    widget: GraphWidget,
    config: DisplayConfig,
    states_dict: dict[str, object],
    header_h: int,
    svg_w: int,
    svg_h: int,
    display_levels: int,
    *,
    show_icon: bool,
    show_state: bool,
) -> tuple[dict[str, object], int, int] | None:
    """Build the header context and graph area edges for the widget.

    Tries each entity in ``entity_descs`` in order until one has a
    usable state, so the header is never blank when the first
    configured entity is missing from ``states``.  An explicit
    widget-level ``title`` replaces the header name; when it is
    empty or missing, the first series' name is used.  When more
    than one entity is configured, the entities' states are
    concatenated into ``ctx["value_text"]`` before laying out the
    header, so the (possibly much longer) combined text goes through
    ``_fix_header_layout``'s icon-overlap truncation rather than the
    original single-entity value.

    Args:
        entity_descs: Normalized entity descriptor list from
            ``_normalize_entities()``.
        widget: Widget config dict.
        config: Display config.
        states_dict: ``config["states"]`` states dict.
        header_h: Pixel height of the header row.
        svg_w: Full widget width.
        svg_h: Full widget height.
        display_levels: Display grayscale depth.
        show_icon: Widget's ``show_icon`` setting.
        show_state: Widget's ``show_state`` setting.

    Returns:
        ``(ctx, gx1, gx2)`` — the header context dict from
        ``_entity_info_context`` (adjusted in place by
        ``_fix_header_layout``) and the left/right graph area pixel
        edges, or ``None`` when no entity has a usable state.
    """
    ctx = None
    # An explicit widget-level title replaces the header name for
    # every entity, so a graph title can differ from the first
    # series' legend label.  An empty title keeps the historical
    # behaviour of showing the first series' name.
    title = str(widget.get("title") or "")
    for desc in entity_descs:
        eid = str(desc["entity"])
        name_override = str(desc.get("name", ""))
        hw = widget.copy()
        hw["entity"] = eid
        hw["hide_icon"] = not show_icon
        if title:
            hw["name"] = title
        elif name_override:
            hw["name"] = name_override
        ctx = _entity_info_context(hw, config, header_h, svg_w, svg_h)
        if ctx is not None:
            break

    if ctx is None:
        return None

    combined_state = _combined_state_text(
        entity_descs, states_dict, config, show_state, widget
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
        font_scale=config.get("font_scale", 1.0),
    )
    return ctx, gx1, gx2


@dataclass(frozen=True, slots=True)
class _SeriesData:
    """Per-entity chart data and computed Y-axis bounds.

    Attributes:
        per_entity_points: One ``(timestamp, value)`` point list per
            entry in ``entity_descs``, in the same order.
        prim_y_min: Primary Y-axis lower bound.
        prim_y_max: Primary Y-axis upper bound.
        sec_y_min: Secondary Y-axis lower bound.
        sec_y_max: Secondary Y-axis upper bound.
        has_secondary: Whether any entity plots on the secondary axis.
        all_points: Every point from every entity, concatenated;
            used for shared axis geometry.
        has_any_data: Whether any entity has at least one point.
        primary_points: Points from the first primary-axis entity
            that has data, used for label/extrema geometry; falls
            back to the first entity with any data at all when every
            entity with data is on the secondary axis.
    """

    per_entity_points: list[list[tuple[float, float]]]
    prim_y_min: float
    prim_y_max: float
    sec_y_min: float
    sec_y_max: float
    has_secondary: bool
    all_points: list[tuple[float, float]]
    has_any_data: bool
    primary_points: list[tuple[float, float]]


def _collect_series_data(
    entity_descs: list[dict[str, object]],
    states_dict: dict[str, object],
    hours_to_show: int,
    points_per_hour: float,
    aggregate_func: str,
    start_cutoff: float | None,
    *,
    lower_bound: object,
    upper_bound: object,
    min_bound_range: object,
    secondary_lower_bound: object,
    secondary_upper_bound: object,
) -> _SeriesData:
    """Extract per-entity chart points and compute Y-axis bounds.

    Entities with ``data_source="attribute"`` read a forecast-style
    time-series list from a named entity attribute instead of the
    recorder's state history.

    Args:
        entity_descs: Normalized entity descriptor list from
            ``_normalize_entities()``.
        states_dict: ``config["states"]`` states dict.
        hours_to_show: History window in hours for entities using
            state history (ignored for ``data_source="attribute"``).
        points_per_hour: Data points per hour for bucketing.
        aggregate_func: Aggregation function for bucketing
            (``"avg"``, ``"min"``, ``"max"``, ``"first"``, ``"last"``,
            or ``"sum"``).
        start_cutoff: Optional fixed start time overriding
            ``hours_to_show``, from ``_resolve_start_cutoff()``.
        lower_bound: Optional fixed primary Y-axis lower bound.
        upper_bound: Optional fixed primary Y-axis upper bound.
        min_bound_range: Optional minimum primary Y-axis range.
        secondary_lower_bound: Optional fixed secondary Y-axis lower
            bound.
        secondary_upper_bound: Optional fixed secondary Y-axis upper
            bound.

    Returns:
        A ``_SeriesData`` instance with per-entity points, computed
        Y-axis bounds, and the flattened/primary point lists used for
        shared axis geometry.
    """
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

    all_points: list[tuple[float, float]] = [
        p for ep in per_entity_points for p in ep
    ]
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
        primary_points = next((ep for ep in per_entity_points if ep), [])

    return _SeriesData(
        per_entity_points=per_entity_points,
        prim_y_min=prim_y_min,
        prim_y_max=prim_y_max,
        sec_y_min=sec_y_min,
        sec_y_max=sec_y_max,
        has_secondary=has_secondary,
        all_points=all_points,
        has_any_data=has_any_data,
        primary_points=primary_points,
    )


def _axis_unit(
    entity_descs: list[dict[str, object]],
    states: dict[str, object],
    widget: GraphWidget,
    *,
    secondary: bool,
) -> str:
    """Return the unit shown on a value axis.

    The primary axis uses the widget's ``unit`` override when set,
    otherwise the ``unit_of_measurement`` of the first primary-axis
    entity.  The secondary axis uses its first entity's unit.

    Args:
        entity_descs: Normalized entity descriptors.
        states: States dict for reading entity attributes.
        widget: Widget config, consulted for the ``unit`` override.
        secondary: ``True`` for the right-hand axis.

    Returns:
        Unit string, or ``""`` when none is known.
    """
    if not secondary and widget.get("unit") is not None:
        return str(widget.get("unit"))
    for desc in entity_descs:
        is_sec = str(desc.get("y_axis", "primary")) == "secondary"
        if is_sec != secondary:
            continue
        st = states.get(str(desc["entity"]))
        attrs = (
            cast("dict[str, Any]", st).get("attributes")
            if isinstance(st, dict)
            else None
        )
        if isinstance(attrs, dict):
            return str(attrs.get("unit_of_measurement", ""))
        return ""
    return ""


def _tick_count(
    widget: GraphWidget, key: Literal["x_axis_ticks", "y_axis_ticks"]
) -> int:
    """Return a validated axis tick count from the widget config.

    The editor limits tick counts to 2-12, but stored configs may
    hold anything; malformed values fall back to the default of 2
    and out-of-range values are clamped.

    Args:
        widget: Widget configuration dict.
        key: ``"x_axis_ticks"`` or ``"y_axis_ticks"``.

    Returns:
        Tick count between ``_MIN_AXIS_TICKS`` and
        ``_MAX_AXIS_TICKS``.
    """
    try:
        count = int(float(widget.get(key, _MIN_AXIS_TICKS)))
    except (TypeError, ValueError, OverflowError):
        return _MIN_AXIS_TICKS
    return min(max(count, _MIN_AXIS_TICKS), _MAX_AXIS_TICKS)


def _x_axis_ticks(
    series: list[dict[str, object]],
    per_entity_points: list[list[tuple[float, float]]],
    primary_points: list[tuple[float, float]],
    is_bar: bool,
    count: int,
    gx1: int,
    gx2: int,
    font_sz: int,
    config: DisplayConfig,
) -> list[dict[str, object]]:
    """Return the x-axis ticks for the final plot geometry.

    Two ticks (the default) keep the oldest/newest time of the
    primary series at the plot edges.  Line graphs place round-time
    ticks using the same time mapping as the series (all entities'
    timestamps); bar charts label evenly spaced bars of the first
    series with data at their centres.

    Args:
        series: Built series dicts (bar mode reads ``bars``).
        per_entity_points: Data points per entity, same order.
        primary_points: Points of the series labelled by default.
        is_bar: ``True`` for bar charts.
        count: Requested maximum number of ticks.
        gx1: Plot left edge.
        gx2: Plot right edge.
        font_sz: Label font size.
        config: Display config.

    Returns:
        List of x tick dicts (see ``axes._time_axis_ticks``).
    """
    from ...render import _load_font

    t_first = min(t for t, _ in primary_points)
    t_last = max(t for t, _ in primary_points)
    edge = _edge_ticks(t_first, t_last, gx1, gx2, config)
    if count <= 2:
        return edge
    font = _load_font(font_sz)
    if is_bar:
        for s, ep in zip(series, per_entity_points, strict=True):
            bars = s.get("bars")
            if ep and isinstance(bars, list) and bars:
                ticks = _bar_axis_ticks(
                    cast("list[dict[str, object]]", bars),
                    [t for t, _ in ep],
                    count,
                    gx1,
                    gx2,
                    font,
                    config,
                )
                return ticks or edge
        return edge
    all_ts = [t for ep in per_entity_points for t, _ in ep]
    return _time_axis_ticks(
        min(all_ts), max(all_ts), count, gx1, gx2, font, config
    )


def _build_graph_context(
    widget: GraphWidget,
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
            ``title`` (header title override; when empty or missing,
            the first series' name is used),
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
            ``state_font_size`` (legacy override for the header
            value/unit font size in pixels; defaults to
            ``_compute_metrics(header_h).font_secondary`` when
            omitted, and loses to an explicit ``fonts.value.size`` /
            ``fonts.unit.size``),
            ``graph`` (chart type: ``"line"`` (default) for a line
            graph with polyline/path elements, or ``"bar"`` for a
            bar chart with ``<rect>`` elements; in bar mode
            ``smoothing`` and ``show_fill`` are ignored),
            ``fonts`` (per-role font overrides — a mapping of role
            name to ``{"size": int, "weight": str}``; roles are
            ``"name"`` (the header name), ``"value"`` (the header
            state text), ``"unit"`` (the header unit), and
            ``"axis"`` (axis, extrema, and legend labels).  An
            omitted ``size`` keeps the widget's derived size scaled
            by the display-level ``font_scale``; an explicit
            ``size`` is absolute.  An omitted ``weight`` keeps the
            role's default: name ``"medium"``, value, unit, and
            axis ``"regular"``),
            ``decimals`` (exact number of decimal places to show
            for the header value(s); overrides HA's
            ``display_precision`` and device-class defaults),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``,
            ``display_levels``, ``font_scale``, and optionally
            ``time_format`` (``"24"`` or ``"12"``; default ``"24"``).

    Returns:
        Template context dict consumed by ``graph.svg.j2``.
        Returns ``_missing_entity_context(w, h)`` when no entity
        is present in states.
        Full context includes widget dimensions, card style, metrics,
        colors, icon geometry, header text (with resolved role font
        sizes and SVG weight strings), series list, ``is_bar``
        (bool, ``True`` when ``graph="bar"``), ``legend_is_bar``
        (bool, controls rect vs line legend swatches),
        ``axis_font_weight`` (SVG weight for axis/extrema/legend
        labels), and optional axis labels, grid lines, extrema,
        secondary Y-axis labels, and legend.
    """
    from ...render import _font_weight_svg

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
    font_scale: float = config.get("font_scale", 1.0)
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
        return _missing_entity_context(svg_w, svg_h)

    states_dict: dict[str, object] = config.get("states", {})

    # Header uses the first entity with a usable state; multi-entity
    # states are concatenated for display.
    header_result = _build_header_context(
        entity_descs,
        widget,
        config,
        states_dict,
        header_h,
        svg_w,
        svg_h,
        display_levels,
        show_icon=show_icon,
        show_state=show_state,
    )
    if header_result is None:
        return _missing_entity_context(svg_w, svg_h)
    ctx, gx1, gx2 = header_result

    # Stroke width: user-configured, widened on 2-level displays.
    graph_stroke_w = line_width * 2 if display_levels <= 2 else line_width
    # Inset graph area by 2× stroke so line stays within bounds.
    margin = graph_stroke_w * 2
    gy1 = header_h + margin
    gy2 = svg_h - margin

    # --- Per-entity data extraction and Y-axis bounds ---
    series_data = _collect_series_data(
        entity_descs,
        states_dict,
        hours_to_show,
        points_per_hour,
        aggregate_func,
        start_cutoff,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        min_bound_range=min_bound_range,
        secondary_lower_bound=secondary_lower_bound,
        secondary_upper_bound=secondary_upper_bound,
    )
    per_entity_points = series_data.per_entity_points
    prim_y_min = series_data.prim_y_min
    prim_y_max = series_data.prim_y_max
    sec_y_min = series_data.sec_y_min
    sec_y_max = series_data.sec_y_max
    has_secondary = series_data.has_secondary
    # Single source of truth for "is there any data to draw" — reused
    # for the legend-geometry gate, the final show_legend flag, and
    # has_graph, so the three can never desync from one another.
    has_any_data = series_data.has_any_data
    primary_points = series_data.primary_points

    # --- Axis options ---
    x_axis_ticks = _tick_count(widget, "x_axis_ticks")
    y_axis_ticks = _tick_count(widget, "y_axis_ticks")
    x_tick_marks = bool(widget.get("x_axis_tick_marks", False))
    y_tick_marks = bool(widget.get("y_axis_tick_marks", False))
    x_axis_grid = bool(widget.get("x_axis_grid", False))
    y_axis_grid = bool(widget.get("y_axis_grid", False))
    y_axis_unit = bool(widget.get("y_axis_unit", False))

    # Axis labels, extrema, and the legend all render with the shared
    # ``axis`` role, resolved once from the widget so a
    # ``fonts.axis`` override and the display-level ``font_scale``
    # reach every one of them.  The default size is proportional to
    # the full graph allocation before any band is reserved.
    font_sz, axis_weight = _axis_font(widget, gy2 - gy1, font_scale)
    label_gap = font_sz // 2
    tick_len = max(3, font_sz // 3)
    show_labels_ctx = bool(primary_points and show_labels)
    label_font_sz = font_sz if show_labels_ctx else 0

    # --- Bottom bands, reserved bottom-up ---
    # Each band is cut from the bottom of the remaining area, giving
    # the top-to-bottom order: plot, x-axis labels, extrema, legend.
    # Band heights depend only on the font size, so the plot height
    # is final before the Y-axis gutters (which need it to fit their
    # labels) narrow the plot horizontally.
    multi_entity = len(entity_descs) > 1
    show_legend_ctx = multi_entity and has_any_data and show_legend
    legend_bottom = gy2
    if show_legend_ctx:
        gy2 -= _legend_band_height(font_sz)

    extrema_font_sz = 0
    extrema_min_str = ""
    extrema_max_str = ""
    extrema_y = gy2
    show_extrema_ctx = False
    if primary_points and show_extrema:
        new_gy2, ex_y, ex_min, ex_max = _extrema_geometry(
            primary_points, font_sz, gy2, config
        )
        # Skip the band when it would leave no room for the plot.
        if new_gy2 > gy1:
            gy2, extrema_y = new_gy2, ex_y
            extrema_min_str, extrema_max_str = ex_min, ex_max
            extrema_font_sz = font_sz
            show_extrema_ctx = True

    show_x_labels = False
    x_label_y = gy2
    if show_labels_ctx and gy2 - font_sz - label_gap > gy1:
        gy2 -= font_sz + label_gap
        # Hanging baseline half a line below the plot; tick marks
        # (tick_len <= label_gap) fit in the gap above the text.
        x_label_y = gy2 + label_gap
        show_x_labels = True

    # --- Y-axis ticks and label gutters (shift gx1 / gx2 inward) ---
    show_secondary_labels = False
    y_label_x = gx1
    y2_label_right_x = gx2
    y_ticks: list[dict[str, object]] = []
    y2_ticks: list[dict[str, object]] = []
    if show_labels_ctx:
        from ...render import _load_role_font

        label_font = _load_role_font(font_sz, axis_weight)
        mark_w = tick_len if y_tick_marks else 0
        y_ticks = _value_axis_ticks(
            prim_y_min,
            prim_y_max,
            y_axis_ticks,
            _axis_unit(entity_descs, states_dict, widget, secondary=False)
            if y_axis_unit
            else "",
            gy1,
            gy2,
            font_sz,
            config,
        )
        gx1 += (
            max(round(label_font.getlength(str(t["label"]))) for t in y_ticks)
            + label_gap
            + mark_w
        )
        if has_secondary:
            y2_ticks = _value_axis_ticks(
                sec_y_min,
                sec_y_max,
                y_axis_ticks,
                _axis_unit(entity_descs, states_dict, widget, secondary=True)
                if y_axis_unit
                else "",
                gy1,
                gy2,
                font_sz,
                config,
            )
            gx2 -= (
                max(
                    round(label_font.getlength(str(t["label"])))
                    for t in y2_ticks
                )
                + label_gap
                + mark_w
            )
            show_secondary_labels = True

    # --- Legend entries (need the final plot width) ---
    legend_y = legend_bottom
    legend_entries: list[dict[str, object]] = []
    if show_legend_ctx:
        bar_fills_legend = _BAR_FILL_COLORS if is_bar else None
        _, legend_y, legend_entries = _legend_geometry(
            entity_descs,
            states_dict,
            gx1,
            gx2,
            legend_bottom,
            font_sz,
            legend_bottom - gy1,
            bar_fills=bar_fills_legend,
            weight=axis_weight,
        )

    # Classic grid lines at the plot's top and bottom edges.
    # Suppressed on 2-level (B&W) displays.
    grid_y_top = gy1
    grid_y_bot = gy2
    show_grid = show_labels_ctx and display_levels > 2

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

    # --- X-axis ticks (need the final series geometry) ---
    x_ticks: list[dict[str, object]] = []
    if show_x_labels:
        x_ticks = _x_axis_ticks(
            series,
            per_entity_points,
            primary_points,
            is_bar,
            x_axis_ticks,
            gx1,
            gx2,
            font_sz,
            config,
        )

    # --- Tick marks and grid lines ---
    tick_marks: list[dict[str, object]] = []
    grid_lines: list[dict[str, object]] = []
    for t in y_ticks:
        ty = t["y"]
        if y_tick_marks:
            tick_marks.append(
                {"x1": gx1 - tick_len, "y1": ty, "x2": gx1, "y2": ty}
            )
        # The edge borders already draw a line at the plot's top and
        # bottom, so skip tick grid lines that would coincide.
        if y_axis_grid and not (show_grid and ty in (gy1, gy2)):
            grid_lines.append({"x1": gx1, "y1": ty, "x2": gx2, "y2": ty})
    if y_tick_marks:
        for t in y2_ticks:
            ty = t["y"]
            tick_marks.append(
                {"x1": gx2, "y1": ty, "x2": gx2 + tick_len, "y2": ty}
            )
    for t in x_ticks:
        tx = t["x"]
        if x_tick_marks:
            tick_marks.append(
                {"x1": tx, "y1": gy2, "x2": tx, "y2": gy2 + tick_len}
            )
        if x_axis_grid:
            grid_lines.append({"x1": tx, "y1": gy1, "x2": tx, "y2": gy2})
    grid_stroke_w = max(1, graph_stroke_w // 2)
    # Light gray dithers into noise on 2-level displays, so grid lines
    # are drawn dotted in black there instead.
    two_level = display_levels <= 2
    grid_line_color = color_to_hex(
        COLOR_BLACK if two_level else COLOR_LIGHT_GRAY
    )
    grid_line_dash = (
        f"{grid_stroke_w} {grid_stroke_w * 3}" if two_level else ""
    )

    return {
        **ctx,
        "has_graph": has_any_data,
        "series": series,
        "graph_stroke_w": graph_stroke_w,
        "grid_stroke_w": grid_stroke_w,
        "hide_state": not show_state,
        "show_name": show_name,
        # Primary axis labels.
        "show_labels": show_labels_ctx,
        "label_font_sz": label_font_sz,
        # Axis, extrema, and legend labels share one resolved weight.
        "axis_font_weight": _font_weight_svg(axis_weight),
        "y_label_x": y_label_x,
        # Legacy min/max and oldest/newest strings (first and last
        # tick) kept for callers that read them directly.
        "y_min_str": y_ticks[0]["label"] if y_ticks else "",
        "y_max_str": y_ticks[-1]["label"] if y_ticks else "",
        "y_min_label_y": gy2,
        "y_max_label_y": gy1,
        "x_oldest_str": x_ticks[0]["label"] if x_ticks else "",
        "x_newest_str": x_ticks[-1]["label"] if x_ticks else "",
        "x_label_y": x_label_y,
        # Tick lists: dicts with position, label and text placement.
        "y_ticks": y_ticks,
        "y2_ticks": y2_ticks,
        "x_ticks": x_ticks,
        "tick_marks": tick_marks,
        "grid_lines": grid_lines,
        "grid_line_color": grid_line_color,
        "grid_line_dash": grid_line_dash,
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
        "y2_min_str": y2_ticks[0]["label"] if y2_ticks else "",
        "y2_max_str": y2_ticks[-1]["label"] if y2_ticks else "",
        "y2_min_label_y": gy2,
        "y2_max_label_y": gy1,
        # Legend.
        "show_legend": show_legend_ctx,
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

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

"""Graph widget bar and line series builders."""

from __future__ import annotations

from .colors import (
    _BAR_FILL_COLORS,
    _bar_threshold_fill,
    _lighter_hex,
    _threshold_gradient_stops,
)
from .geometry import _smooth_fill, _smooth_path


def _bar_series(
    per_entity_points: list[list[tuple[float, float]]],
    entity_descs: list[dict[str, object]],
    prim_y_min: float,
    prim_y_max: float,
    sec_y_min: float,
    sec_y_max: float,
    gx1: int,
    gx2: int,
    gy1: int,
    gy2: int,
    thresholds: list[dict[str, object]] | None = None,
    display_levels: int = 16,
) -> list[dict[str, object]]:
    """Compute bar rectangles for a bar chart from per-entity points.

    Each entity's data points are placed at evenly-spaced horizontal
    positions across the graph area.  The bar height is proportional
    to the data value relative to the entity's Y-axis bounds.
    Entities with a secondary Y-axis use the secondary scale.

    Each entity receives a distinct fill color from
    ``_BAR_FILL_COLORS`` (black, gray, light gray) so that different
    series are visually distinguishable on e-ink displays that
    cannot rely on hue.  When ``thresholds`` is non-empty each
    individual bar's fill is determined by the threshold band
    containing its value instead.

    Args:
        per_entity_points: One list of (timestamp, value) pairs
            per entity, oldest-to-newest, post-aggregation.
        entity_descs: Normalized entity descriptor dicts from
            ``_normalize_entities()``.
        prim_y_min: Primary Y-axis lower bound.
        prim_y_max: Primary Y-axis upper bound.
        sec_y_min: Secondary Y-axis lower bound.
        sec_y_max: Secondary Y-axis upper bound.
        gx1: Left pixel edge of the graph area.
        gx2: Right pixel edge of the graph area.
        gy1: Top pixel edge of the graph area.
        gy2: Bottom pixel edge of the graph area (bar baseline).
        thresholds: Optional sorted ascending threshold list; when
            non-empty, per-bar threshold fills override entity-level
            colors.
        display_levels: Display grayscale depth for threshold color
            mapping.

    Returns:
        List of series dicts, one per entity.  Each dict contains:
        ``bars`` (list of ``{x, y, w, h, bar_fill}`` dicts),
        ``bar_fill`` (entity-level hex fill color), ``has_data``
        (bool), and empty string fields for the line-graph keys
        (``polyline_points``, ``graph_path``, ``fill_path``,
        ``fill_points``, ``stroke_dasharray``) so the SVG template
        does not require separate guards for bar vs line mode on
        those keys.
    """
    graph_w = gx2 - gx1
    result: list[dict[str, object]] = []
    for j, (desc, ep) in enumerate(
        zip(entity_descs, per_entity_points, strict=True)
    ):
        fill = _BAR_FILL_COLORS[j % len(_BAR_FILL_COLORS)]
        if not ep:
            result.append(
                {
                    "bars": [],
                    "bar_fill": fill,
                    "has_data": False,
                    "polyline_points": "",
                    "graph_path": "",
                    "fill_path": "",
                    "fill_points": "",
                    "stroke_dasharray": "",
                }
            )
            continue

        is_secondary = str(desc.get("y_axis", "primary")) == "secondary"
        y_min = sec_y_min if is_secondary else prim_y_min
        y_max = sec_y_max if is_secondary else prim_y_max
        y_range = y_max - y_min

        n = len(ep)
        # Divide graph width evenly across all data points.
        group_w = graph_w / n
        # 10% inter-bar gap; at least 1 px so bars never touch.
        spacing = max(1, round(group_w * 0.1))
        bar_w = max(1, round(group_w - spacing))
        # Centre the bar within its slot.
        bar_start = (round(group_w) - bar_w) // 2

        bars: list[dict[str, object]] = []
        for i, (_t, v) in enumerate(ep):
            bx = gx1 + round(i * group_w) + bar_start
            # Clamp value to prevent bar from leaving graph area.
            v_clamped = max(y_min, min(y_max, v))
            py = round(gy2 - (v_clamped - y_min) / y_range * (gy2 - gy1))
            py = max(gy1, min(gy2, py))
            bar_h = gy2 - py
            # Ensure a minimum visible bar height of 1 px.
            if bar_h < 1:
                bar_h = 1
                py = gy2 - 1
            bar: dict[str, object] = {
                "x": bx,
                "y": py,
                "w": bar_w,
                "h": bar_h,
                "bar_fill": fill,
            }
            # Per-bar threshold fill overrides entity-level color.
            if thresholds:
                bar["bar_fill"] = _bar_threshold_fill(
                    v, thresholds, display_levels
                )
            bars.append(bar)

        result.append(
            {
                "bars": bars,
                "bar_fill": fill,
                "has_data": True,
                "polyline_points": "",
                "graph_path": "",
                "fill_path": "",
                "fill_points": "",
                "stroke_dasharray": "",
            }
        )
    return result


def _line_series(
    per_entity_points: list[list[tuple[float, float]]],
    entity_descs: list[dict[str, object]],
    prim_y_min: float,
    prim_y_max: float,
    sec_y_min: float,
    sec_y_max: float,
    gx1: int,
    gx2: int,
    gy1: int,
    gy2: int,
    smoothing: bool,
    show_fill: bool,
    thresholds: list[dict[str, object]] | None = None,
    threshold_transition: str = "smooth",
    display_levels: int = 16,
) -> tuple[list[dict[str, object]], bool]:
    """Compute SVG line/polyline series dicts from per-entity points.

    Maps each entity's (timestamp, value) pairs to pixel coordinates
    and generates SVG path strings for the graph line and optional fill
    area.  Uses a shared X range spanning all entities' timestamps so
    multiple overlaid lines share the same time axis.

    When ``thresholds`` is non-empty, each series dict includes
    gradient stop lists (``threshold_stroke_stops`` and
    ``threshold_fill_stops``) and ``has_threshold_gradient`` is
    ``True``.  The SVG template uses these to emit ``<linearGradient>``
    definitions and reference them via ``url(#thresh-stroke-N)``.

    Args:
        per_entity_points: One list of (timestamp, value) pairs
            per entity, oldest-to-newest, post-aggregation.
        entity_descs: Normalized entity descriptor dicts from
            ``_normalize_entities()``.
        prim_y_min: Primary Y-axis lower bound.
        prim_y_max: Primary Y-axis upper bound.
        sec_y_min: Secondary Y-axis lower bound.
        sec_y_max: Secondary Y-axis upper bound.
        gx1: Left pixel edge of the graph area.
        gx2: Right pixel edge of the graph area.
        gy1: Top pixel edge of the graph area.
        gy2: Bottom pixel edge of the graph area (line baseline).
        smoothing: When ``True`` use midpoint Q-curve paths; when
            ``False`` use polylines.
        show_fill: When ``True`` draw a fill under the first
            entity's line.
        thresholds: Optional sorted ascending threshold list.  When
            non-empty, gradient stops are computed per entity.
        threshold_transition: ``"smooth"`` or ``"hard"``.
        display_levels: Display grayscale depth for color mapping.

    Returns:
        Tuple of ``(series, has_any_data)`` where ``series`` is a
        list of dicts (one per entity) containing ``polyline_points``,
        ``graph_path``, ``fill_path``, ``fill_points``,
        ``stroke_dasharray``, ``has_data``, ``has_threshold_gradient``
        (bool), ``threshold_stroke_stops``, and
        ``threshold_fill_stops``.
    """
    active_thresholds = thresholds or []
    all_timestamps = [t for ep in per_entity_points for t, _ in ep]
    if all_timestamps:
        t_min = min(all_timestamps)
        t_max_all = max(all_timestamps)
        t_range = max(t_max_all - t_min, 1.0)
    else:
        t_min, t_range = 0.0, 1.0

    series: list[dict[str, object]] = []
    has_any_data = False
    first_with_data_seen = False
    for desc, ep in zip(entity_descs, per_entity_points, strict=True):
        if not ep:
            series.append(
                {
                    "polyline_points": "",
                    "graph_path": "",
                    "fill_path": "",
                    "fill_points": "",
                    "stroke_dasharray": str(desc.get("dash", "")),
                    "has_data": False,
                    "has_threshold_gradient": False,
                    "threshold_stroke_stops": [],
                    "threshold_fill_stops": [],
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

        # Only the first primary-axis entity with data gets fill.
        do_fill = show_fill and not first_with_data_seen and not is_secondary
        if not is_secondary:
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

        # --- Threshold gradient stops for this series ---
        stroke_stops: list[dict[str, str]] = []
        fill_stops: list[dict[str, str]] = []
        has_grad = bool(active_thresholds)
        if has_grad:
            stroke_stops = _threshold_gradient_stops(
                active_thresholds,
                threshold_transition,
                y_min_s,
                y_max_s,
                display_levels,
            )
            fill_stops = [
                {
                    "offset": s["offset"],
                    "color": _lighter_hex(s["color"]),
                }
                for s in stroke_stops
            ]

        series.append(
            {
                "polyline_points": pp,
                "graph_path": gp,
                "fill_path": fp,
                "fill_points": fpts,
                "stroke_dasharray": str(desc.get("dash", "")),
                "has_data": True,
                "has_threshold_gradient": has_grad,
                "threshold_stroke_stops": stroke_stops,
                "threshold_fill_stops": fill_stops,
            }
        )
    return series, has_any_data

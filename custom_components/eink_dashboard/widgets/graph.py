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
import logging
import math
from typing import Any, cast

from ..const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    COLOR_MEDIUM_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
    color_to_hex,
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

# Fill colors for bar chart entity series: first entity is black,
# second is gray, third is light gray.  E-ink displays distinguish
# shades rather than hues; these three values give maximum contrast.
_BAR_FILL_COLORS: tuple[str, ...] = (
    color_to_hex(COLOR_BLACK),
    color_to_hex(COLOR_GRAY),
    color_to_hex(COLOR_LIGHT_GRAY),
)

# Named shade → grayscale constant mapping for explicit threshold
# overrides.  The four named levels map to the standard e-ink palette:
# black, dark gray, light gray, and a near-white value that is still
# visually distinct from the white background.
_SHADE_VALUES: dict[str, int] = {
    "black": COLOR_BLACK,
    "dark": COLOR_GRAY,
    "medium": COLOR_MEDIUM_GRAY,
    "light": COLOR_LIGHT_GRAY,
}

# Maximum data points kept from attribute sources.  Exceeding this
# triggers stride-based downsampling to cap render cost.  Typical
# forecasts (48-96 entries) are never affected.
_MAX_ATTRIBUTE_POINTS: int = 500


def _rgb_hex_to_grayscale(
    hex_color: str,
    grayscale_levels: int,
) -> str:
    """Convert an RGB hex color string to a grayscale hex string.

    Parses a ``#RRGGBB`` string, computes the ITU-R BT.601 luminance,
    and quantizes the result to the number of levels available on the
    display.  On 2-level (B&W) displays the result is clamped to pure
    black or white.

    Args:
        hex_color: CSS hex color string, e.g. ``"#ff0000"``.  Must
            start with ``#`` followed by exactly six hex digits.
            Values that do not match this form are treated as black.
        grayscale_levels: Number of distinct gray levels on the
            display.  ``2`` produces only black or white; higher
            values quantize to the nearest available step.

    Returns:
        Grayscale ``#rrggbb`` hex string suitable for SVG attributes.
        Falls back to ``color_to_hex(COLOR_BLACK)`` on parse error.
    """
    try:
        hex_clean = hex_color[1:]
        if len(hex_clean) != 6:
            raise ValueError("bad length")
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
    except (ValueError, AttributeError):
        return color_to_hex(COLOR_BLACK)
    # ITU-R BT.601 luminance coefficients.
    gray = round(0.299 * r + 0.587 * g + 0.114 * b)
    if grayscale_levels <= 2:
        # Hard threshold at mid-gray.
        return color_to_hex(0 if gray < 128 else 255)
    # Quantize to the nearest available step.
    steps = grayscale_levels - 1
    quantized = round(gray / 255 * steps) * 255 // steps
    return color_to_hex(quantized)


def _shade_to_hex(shade: str) -> str:
    """Convert a named shade string to a grayscale hex color.

    Args:
        shade: One of ``"black"``, ``"dark"``, ``"medium"``,
            or ``"light"``.  Unknown values fall back to black.

    Returns:
        Grayscale ``#rrggbb`` hex string.
    """
    return color_to_hex(_SHADE_VALUES.get(shade, COLOR_BLACK))


def _resolve_threshold_color(
    entry: dict[str, object],
    grayscale_levels: int,
) -> str:
    """Resolve the final hex color for one threshold entry.

    ``shade`` takes precedence over ``color`` on all displays.  When
    neither key is present the fallback is black.

    Args:
        entry: Threshold dict with optional ``"shade"`` and
            ``"color"`` keys.
        grayscale_levels: Display grayscale depth, used when mapping
            RGB colors to grayscale.

    Returns:
        Resolved ``#rrggbb`` hex string.
    """
    shade = str(entry.get("shade", ""))
    if shade:
        return _shade_to_hex(shade)
    color = str(entry.get("color", ""))
    if color:
        return _rgb_hex_to_grayscale(color, grayscale_levels)
    return color_to_hex(COLOR_BLACK)


def _lighter_hex(hex_color: str) -> str:
    """Shift a grayscale hex color 50% toward white.

    Used to produce a softer fill gradient from the same threshold
    colors as the stroke gradient.  Assumes the input is already a
    grayscale color (all three channels equal).

    Args:
        hex_color: Grayscale ``#rrggbb`` hex string.

    Returns:
        Lightened ``#rrggbb`` hex string.  Falls back to
        ``color_to_hex(COLOR_LIGHT_GRAY)`` on parse error.
    """
    try:
        gray = int(hex_color[1:3], 16)
    except (ValueError, AttributeError, IndexError):
        return color_to_hex(COLOR_LIGHT_GRAY)
    lighter = gray + (255 - gray) // 2
    return color_to_hex(lighter)


def _threshold_gradient_stops(
    thresholds: list[dict[str, object]],
    transition: str,
    y_min: float,
    y_max: float,
    grayscale_levels: int,
) -> list[dict[str, str]]:
    """Compute SVG linearGradient stop entries for color thresholds.

    The gradient runs top-to-bottom in SVG space.  Because the Y
    axis is inverted (high data values map to small Y coordinates),
    a high threshold value maps to a small offset percentage.

    For ``"smooth"`` transitions each threshold produces one stop.
    For ``"hard"`` transitions the boundary between consecutive
    threshold bands is duplicated — two stops at the same offset with
    different colors create a sharp edge with no blending.

    Args:
        thresholds: Sorted ascending by ``"value"``.  Must contain
            at least two entries (enforced by caller).
        transition: ``"smooth"`` or ``"hard"``.
        y_min: Y-axis lower bound (bottom of graph area).
        y_max: Y-axis upper bound (top of graph area).
        grayscale_levels: Display grayscale depth for color mapping.

    Returns:
        List of ``{"offset": "XX.XX%", "color": "#hex"}`` dicts,
        ordered top (0%) to bottom (100%) of the gradient.
    """
    y_range = y_max - y_min

    def _offset(val: float) -> str:
        """Convert a data value to an SVG gradient offset percentage."""
        # High value → small offset (near top of SVG gradient).
        pct = (y_max - val) / y_range * 100.0
        pct = max(0.0, min(100.0, pct))
        return f"{pct:.2f}%"

    colors = [
        _resolve_threshold_color(t, grayscale_levels) for t in thresholds
    ]

    if transition == "hard":
        # Descending by value so we build stops top → bottom.
        desc = list(reversed(thresholds))
        desc_colors = list(reversed(colors))
        stops: list[dict[str, str]] = [
            {"offset": "0.00%", "color": desc_colors[0]},
        ]
        for i in range(1, len(desc)):
            off = _offset(float(str(desc[i]["value"])))
            # Stop for the color of the band ABOVE the boundary.
            stops.append({"offset": off, "color": desc_colors[i - 1]})
            # Stop for the color of the band BELOW — same offset.
            stops.append({"offset": off, "color": desc_colors[i]})
        stops.append({"offset": "100.00%", "color": desc_colors[-1]})
        return stops

    # Smooth: one stop per threshold, descending (top → bottom).
    return [
        {
            "offset": _offset(float(str(t["value"]))),
            "color": c,
        }
        for t, c in zip(reversed(thresholds), reversed(colors), strict=True)
    ]


def _bar_threshold_fill(
    value: float,
    thresholds: list[dict[str, object]],
    grayscale_levels: int,
) -> str:
    """Resolve the threshold fill color for a single bar value.

    Walks the threshold list (sorted ascending) to find the highest
    threshold boundary that the data value meets or exceeds.

    Args:
        value: The bar's data value.
        thresholds: Sorted ascending by ``"value"``.
        grayscale_levels: Display grayscale depth for color mapping.

    Returns:
        Resolved ``#rrggbb`` hex string for the bar's fill.
    """
    chosen = thresholds[0]
    for t in thresholds:
        if value >= float(str(t["value"])):
            chosen = t
        else:
            break
    return _resolve_threshold_color(chosen, grayscale_levels)


def _normalize_thresholds(
    widget: Widget,
) -> list[dict[str, object]]:
    """Normalize widget config into a canonical threshold list.

    Accepts either the canonical ``color_thresholds`` list or flat
    editor keys ``threshold_{1..4}_{value,color,shade}``.  When both
    are present, the canonical list takes precedence.

    Args:
        widget: Widget config dict.

    Returns:
        List of threshold dicts each with keys ``value`` (float),
        ``color`` (str, empty when absent), and ``shade`` (str, empty
        when absent).  Sorted ascending by ``value``.  May be empty.
    """
    canonical = widget.get("color_thresholds")
    if isinstance(canonical, list) and canonical:
        result: list[dict[str, object]] = []
        for item in canonical:
            if not isinstance(item, dict):
                continue
            try:
                v = float(str(item.get("value", "")))
            except (ValueError, TypeError):
                continue
            result.append(
                {
                    "value": v,
                    "color": str(item.get("color", "")),
                    "shade": str(item.get("shade", "")),
                }
            )
        return sorted(result, key=lambda t: float(str(t["value"])))

    # Flat editor keys: threshold_1_value ... threshold_4_value.
    result = []
    for n in range(1, 5):
        raw_v = widget.get(f"threshold_{n}_value")
        if raw_v is None:
            continue
        try:
            v = float(str(raw_v))
        except (ValueError, TypeError):
            continue
        result.append(
            {
                "value": v,
                "color": str(widget.get(f"threshold_{n}_color", "")),
                "shade": str(widget.get(f"threshold_{n}_shade", "")),
            }
        )
    return sorted(result, key=lambda t: float(str(t["value"])))


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
    gy1: int,
    gy2: int,
    config: DisplayConfig,
    graph_h: int,
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
        graph_h: Pixel height of the graph area (gy2 - gy1), used to
            derive proportional font size.

    Returns:
        Tuple of
        ``(new_gx1, new_gy2, y_label_x, x_label_y, label_font_sz,
           y_min_str, y_max_str, x_oldest_str, x_newest_str)``
        where ``new_gx1``/``new_gy2`` are the adjusted graph
        boundaries and the string fields are the formatted label texts.
        When X-axis labels are suppressed, ``x_label_y`` is 0 and the
        time strings are empty.
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
        value_bold = bool(ctx["value_bold"])
        vf = _load_font(
            m_hdr.font_secondary,
            medium=not value_bold,
            bold=value_bold,
        )
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
    bar_fills: tuple[str, ...] | None = None,
) -> tuple[int, int, list[dict[str, object]]]:
    """Compute legend layout below the graph area.

    Builds a horizontal legend row with one entry per entity.  For
    line graphs, each entry shows a short dash-pattern line sample;
    for bar charts, a small filled rectangle swatch in the entity's
    fill color is shown instead.  The legend is placed at ``gy2``
    and that boundary is shifted upward to reserve space.

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
        bar_fills: Tuple of hex fill colors for bar chart entities
            (from ``_BAR_FILL_COLORS``), or ``None`` for line mode.
            When provided, each legend entry includes swatch rect
            geometry keyed as ``swatch_x``, ``swatch_y``,
            ``swatch_w``, ``swatch_h``, ``bar_fill``.

    Returns:
        Tuple of ``(new_gy2, legend_y, legend_entries)`` where
        ``legend_entries`` is a list of dicts each containing
        ``name``, ``line_x1``, ``line_x2``, ``line_y``,
        ``swatch_x``, ``swatch_y``, ``swatch_w``, ``swatch_h``,
        ``bar_fill``, ``text_x``, ``text_y``,
        ``stroke_dasharray``, and ``font_sz``.
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
    # Centre each swatch/line sample and text label vertically
    # within the legend band.
    entry_mid_y = legend_y + legend_h // 2
    swatch_h = max(4, font_sz // 2)
    for i, desc in enumerate(entity_descs):
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
        text_w = round(legend_font.getlength(name))
        x += line_sample_w + gap + text_w + gap * 2
    return new_gy2, legend_y, entries


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
    grayscale_levels: int = 16,
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
        grayscale_levels: Display grayscale depth for threshold color
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
                    v, thresholds, grayscale_levels
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
    grayscale_levels: int = 16,
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
        grayscale_levels: Display grayscale depth for color mapping.

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
                grayscale_levels,
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
        t_latest = max(
            (
                float(str(e.get("lu", 0)))
                for e in raw_hist
                if math.isfinite(float(str(e.get("lu", 0))))
            ),
            default=None,
        )
        if t_latest is None:
            raw_hist = []
        else:
            cutoff = t_latest - hours_to_show * 3600
            raw_hist = [
                e
                for e in raw_hist
                if math.isfinite(float(str(e.get("lu", 0))))
                and float(str(e.get("lu", 0))) > cutoff
            ]
    numeric: list[tuple[float, float]] = []
    for entry in raw_hist:
        s = entry.get("s", "")
        lu = entry.get("lu", 0.0)
        try:
            val = float(str(s))
            ts = float(str(lu))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(val) or not math.isfinite(ts):
            continue
        numeric.append((ts, val))
    if len(numeric) >= 2:
        return _aggregate_history(numeric, points_per_hour, aggregate_func)
    return []


def _parse_attribute_timestamp(value: object) -> float | None:
    """Parse a timestamp field from an attribute time-series entry.

    Accepts either a Unix timestamp (int/float, or a numeric string)
    or an ISO 8601 string (e.g. ``"2026-07-01T04:00:00+00:00"``).

    Args:
        value: Raw timestamp value from the attribute entry.

    Returns:
        Unix timestamp in seconds, or ``None`` if unparseable.
    """
    try:
        result = float(str(value))
        if not math.isfinite(result):
            return None
        return result
    except (ValueError, TypeError):
        pass
    try:
        return datetime.datetime.fromisoformat(str(value)).timestamp()
    except (ValueError, TypeError):
        return None


def _extract_attribute_points(
    desc: dict[str, object],
    states_dict: dict[str, Any],
) -> list[tuple[float, float]]:
    """Extract time-series data from an entity attribute.

    Reads a list of dicts from ``states_dict[entity]["attributes"]
    [attribute]``, pulling the timestamp and value out of each entry
    via the descriptor's configured key names. Used for forward-
    looking forecast data (solar production, energy prices, etc.)
    that is not available through the recorder.

    Args:
        desc: Entity descriptor dict from ``_normalize_entities()``,
            with ``attribute``, ``attribute_timestamp_key``, and
            ``attribute_value_key`` keys.
        states_dict: States dict from the display config.

    Returns:
        Sorted oldest-to-newest list of ``(timestamp, value)`` pairs,
        or an empty list when the attribute is missing or fewer than
        two numeric entries survive parsing.
    """
    eid = str(desc["entity"])
    attribute = str(desc.get("attribute", ""))
    ts_key = str(desc.get("attribute_timestamp_key", "timestamp"))
    value_key = str(desc.get("attribute_value_key", ""))
    state = states_dict.get(eid, {})
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    raw_list = attrs.get(attribute, []) if isinstance(attrs, dict) else []

    numeric: list[tuple[float, float]] = []
    if isinstance(raw_list, list):
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            ts = _parse_attribute_timestamp(entry.get(ts_key))
            if ts is None:
                continue
            try:
                val = float(str(entry.get(value_key)))
            except (ValueError, TypeError):
                continue
            if not math.isfinite(val):
                continue
            numeric.append((ts, val))

    if len(numeric) >= 2:
        numeric.sort(key=lambda p: p[0])
        if len(numeric) > _MAX_ATTRIBUTE_POINTS:
            stride = len(numeric) / _MAX_ATTRIBUTE_POINTS
            numeric = [
                numeric[round(i * stride)]
                for i in range(_MAX_ATTRIBUTE_POINTS)
            ]
        return numeric
    return []


def _normalize_entities(
    widget: Widget,
) -> list[dict[str, object]]:
    """Normalize widget config into a canonical entity descriptor list.

    Accepts either the single-entity format (``entity`` string key)
    or the multi-entity format (``entities`` list of dicts).  When
    both are present ``entities`` takes precedence.  Flat editor keys
    ``entity_2`` / ``entity_3`` are also handled for widgets saved by
    the editor UI.  These flat secondary-entity keys always default
    to ``data_source="history"`` because the editor does not expose
    attribute-source fields for them; use the ``entities`` list
    format to configure an attribute source on a secondary entity.

    Args:
        widget: Widget config dict.

    Returns:
        List of entity descriptor dicts, each with keys ``entity``
        (str), ``name`` (str, empty when not overridden), ``y_axis``
        (``"primary"`` or ``"secondary"``), ``line_style``
        (``"solid"``, ``"dashed"``, or ``"dotted"``), ``dash``
        (the SVG ``stroke-dasharray`` value, empty for solid),
        ``data_source`` (``"history"`` or ``"attribute"``),
        ``attribute`` (str, the attribute name holding a time-series
        list when ``data_source`` is ``"attribute"``),
        ``attribute_timestamp_key`` (str, default ``"timestamp"``),
        and ``attribute_value_key`` (str).  Maximum 3 entries.
        Returns an empty list when no entity source is found.
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
            raw.append(
                {
                    "entity": eid,
                    "data_source": str(widget.get("data_source", "history")),
                    "attribute": str(widget.get("attribute", "")),
                    "attribute_timestamp_key": str(
                        widget.get("attribute_timestamp_key", "timestamp")
                    ),
                    "attribute_value_key": str(
                        widget.get("attribute_value_key", "")
                    ),
                }
            )
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
                "data_source": str(item.get("data_source", "history")),
                "attribute": str(item.get("attribute", "")),
                "attribute_timestamp_key": str(
                    item.get("attribute_timestamp_key", "timestamp")
                ),
                "attribute_value_key": str(
                    item.get("attribute_value_key", "")
                ),
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
            ``graph`` (chart type: ``"line"`` (default) for a line
            graph with polyline/path elements, or ``"bar"`` for a
            bar chart with ``<rect>`` elements; in bar mode
            ``smoothing`` and ``show_fill`` are ignored),
            ``bold_value`` (render the header value in bold;
            default ``False``),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``,
            ``grayscale_levels``, and optionally ``time_format``
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
    has_thresholds: bool = len(raw_thresholds) >= 2 and grayscale_levels > 2
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

    gx1, gx2 = _fix_header_layout(
        ctx, widget, config, header_h, svg_w, grayscale_levels
    )

    # Stroke width: user-configured, widened on 2-level displays.
    graph_stroke_w = line_width * 2 if grayscale_levels <= 2 else line_width
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
    multi_entity = len(entity_descs) > 1
    legend_y = gy2
    legend_entries: list[dict[str, object]] = []
    if multi_entity and all_points:
        graph_h_leg = gy2 - gy1
        bar_fills_legend = _BAR_FILL_COLORS if is_bar else None
        gy2, legend_y, legend_entries = _legend_geometry(
            entity_descs,
            states_dict,
            gx1,
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
            grayscale_levels=grayscale_levels,
        )
        has_any_data = any(bool(s["has_data"]) for s in series)
    else:
        # Line mode: delegate to helper to keep complexity in bounds.
        series, has_any_data = _line_series(
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
            grayscale_levels=grayscale_levels,
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
        "show_legend": multi_entity and has_any_data,
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


def _aggregate_history(
    numeric: list[tuple[float, float]],
    points_per_hour: float,
    aggregate_func: str,
) -> list[tuple[float, float]]:
    """Bucket and aggregate numeric history into representative points.

    Groups (timestamp, value) pairs into fixed-width time buckets based
    on ``points_per_hour``, then reduces each bucket to a single value
    using ``aggregate_func``.  Falls back to ``numeric`` sorted
    oldest-to-newest only when no buckets are produced (degenerate
    input).

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
        per non-empty bucket, or ``numeric`` sorted when bucketing
        produces no entries.
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
    if bucketed:
        return bucketed
    return sorted(numeric, key=lambda p: p[0])


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

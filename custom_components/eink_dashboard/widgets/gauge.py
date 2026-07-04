"""Gauge widget context builder."""

from __future__ import annotations

import contextlib
import math
from typing import TYPE_CHECKING, cast

from ..const import (
    COLOR_BLACK,
    COLOR_LIGHT_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ..svg_render import _mdi_svg_filter
from ._helpers import (
    _card_insets,
    _color_context,
    _fmt,
    _metrics_context,
    _widget_dim,
)

if TYPE_CHECKING:
    import markupsafe

# Gauge type arc configuration: (start_deg, end_deg, arc_angle).
# Standard: 270° arc with gap at the bottom (lower-left to
# lower-right via the top).
# Half: 180° upper semicircle, flat bottom edge.
# Full: 360° complete circle.  SVG arc commands degenerate to a
# zero-length path when start == end; using 359.99° avoids this.
# The resulting 0.01° gap is ~0.017 px at typical e-ink radii —
# invisible at display resolution.
_GAUGE_ANGLES: dict[str, tuple[float, float, float]] = {
    "standard": (135.0, 405.0, 270.0),
    "half": (180.0, 360.0, 180.0),
    "full": (135.0, 494.99, 359.99),
}


def _svg_arc(
    cx: float,
    cy: float,
    r: float,
    start_deg: float,
    end_deg: float,
) -> str:
    """Return an SVG arc path string.

    Computes a clockwise circular arc from ``start_deg`` to
    ``end_deg`` around ``(cx, cy)`` with radius ``r``.  Angles use
    the SVG coordinate system (0° = right, 90° = down).

    Args:
        cx: Arc centre x coordinate.
        cy: Arc centre y coordinate.
        r: Arc radius in pixels.
        start_deg: Start angle in degrees.
        end_deg: End angle in degrees.

    Returns:
        SVG ``M … A …`` path string with coordinates at 3 decimal
        places.
    """
    t1 = math.radians(start_deg)
    t2 = math.radians(end_deg)
    sx = cx + r * math.cos(t1)
    sy = cy + r * math.sin(t1)
    ex = cx + r * math.cos(t2)
    ey = cy + r * math.sin(t2)
    # Sweep > 180° requires the large-arc flag so the longer arc is
    # drawn rather than the short chord.  At exactly 180° both arcs
    # are the same semicircle, so large=0 (from strict >) is correct.
    large = 1 if (end_deg - start_deg) > 180 else 0
    return (
        f"M {sx:.3f} {sy:.3f} A {r:.3f} {r:.3f} 0 {large} 1 {ex:.3f} {ey:.3f}"
    )


def _parse_segment_color(color: object) -> str:
    """Convert a segment color value to an SVG hex grayscale string.

    Accepts three formats:

    - Integer 0–255: used directly as a grayscale level.
    - List ``[r, g, b]``: luminance-converted to grayscale.
    - Hex string ``"#rrggbb"``: luminance-converted to grayscale.

    Non-grayscale colors are converted via the luminance formula
    ``0.299R + 0.587G + 0.114B``.  Unrecognised values fall back to
    ``COLOR_LIGHT_GRAY``.

    Args:
        color: Segment color in one of the accepted formats.

    Returns:
        SVG hex color string, e.g. ``"#787878"``.
    """
    if isinstance(color, int):
        return color_to_hex(max(0, min(255, color)))
    if isinstance(color, list) and len(color) == 3:
        try:
            # str() handles non-string elements (e.g. None→"None"
            # raises ValueError, which is caught below).
            r_v = int(float(str(color[0])))
            g_v = int(float(str(color[1])))
            b_v = int(float(str(color[2])))
        except (TypeError, ValueError):
            return color_to_hex(COLOR_LIGHT_GRAY)
        gray = int(0.299 * r_v + 0.587 * g_v + 0.114 * b_v)
        return color_to_hex(gray)
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        r_v = int(color[1:3], 16)
        g_v = int(color[3:5], 16)
        b_v = int(color[5:7], 16)
        gray = int(0.299 * r_v + 0.587 * g_v + 0.114 * b_v)
        return color_to_hex(gray)
    return color_to_hex(COLOR_LIGHT_GRAY)


def _match_segment(
    segments: list[dict[str, object]],
    value: float,
) -> dict[str, object] | None:
    """Return the segment whose ``from`` threshold the value meets.

    Segments must be pre-sorted by ``from`` ascending (done by
    ``_build_gauge_context``).  The highest segment whose ``from`` is
    ≤ ``value`` is returned.  When the value falls below all
    thresholds the first segment is returned as a fallback.  Returns
    ``None`` when the list is empty.

    Args:
        segments: Parsed segment dicts with ``from`` (float),
            ``color`` (hex string), ``label`` (str), and optional
            ``icon`` fields.  Must be sorted by ``"from"`` ascending.
        value: Current entity value as a float.

    Returns:
        Matching segment dict, or ``None`` for an empty list.
    """
    if not segments:
        return None
    matched: dict[str, object] | None = None
    for seg in segments:
        if cast("float", seg["from"]) <= value:
            matched = seg
    return matched if matched is not None else segments[0]


def _build_gauge_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the gauge widget.

    Renders a circular arc gauge showing a sensor value either as a
    fill arc (needle=False, default) or a needle dot (needle=True).
    Three arc shapes are supported: standard (270°, gap at bottom),
    half (180°, upper semicircle), and full (360°, complete circle).
    Optional coloured segments define the gauge ranges; the matching
    segment's colour, label, and icon are applied for the current
    value.  All colours are converted to grayscale for e-ink
    displays.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, required),
            ``name`` (display name override),
            ``icon`` (MDI icon, e.g. ``"mdi:thermometer"``),
            ``min`` (minimum value; default 0),
            ``max`` (maximum value; default 100),
            ``unit`` (unit string override),
            ``show_unit`` (display unit; default ``True``),
            ``decimals`` (decimal places to display),
            ``attribute`` (HA attribute key to display instead of
            state),
            ``needle`` (needle-dot mode; default ``False``),
            ``gauge_type`` (``"standard"`` / ``"half"`` /
            ``"full"``; default ``"standard"``),
            ``header_position`` (``"bottom"`` / ``"top"``;
            default ``"bottom"``),
            ``bold_value`` (render the value text in bold instead
            of medium weight; default ``False``),
            ``card_style``, ``segments``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``gauge.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing from the
        state dict.
    """
    from ..render import _compute_metrics

    x = widget.get("x", PADDING)
    w = _widget_dim(widget, "w", config["width"] - x)
    # Default: square gauge (height equals width).
    h = _widget_dim(widget, "h", w)

    entity_id: str = widget.get("entity", "")
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)
    card_style: str = widget.get("card_style", DEFAULT_CARD_STYLE)
    gauge_type: str = widget.get("gauge_type", "standard")
    header_position: str = widget.get("header_position", "bottom")
    needle: bool = bool(widget.get("needle", False))
    min_val: float = float(widget.get("min", 0))
    max_val: float = float(widget.get("max", 100))
    segments_raw: list[object] = list(widget.get("segments", []))
    name_override = widget.get("name")
    icon_override = widget.get("icon")
    unit_override = widget.get("unit")
    show_unit: bool = bool(widget.get("show_unit", True))
    decimals = widget.get("decimals")
    attribute: str | None = widget.get("attribute")
    value_bold: bool = widget.get("bold_value", False)

    # Missing entity → blank white canvas.
    state = states.get(entity_id) if entity_id else None
    if state is None:
        return {
            "w": w,
            "h": h,
            "has_entity": False,
            **_color_context(),
        }

    attrs: dict[str, object] = state.get("attributes", {})

    # --- Value ---
    if attribute is not None:
        raw_attr = attrs.get(attribute)
        state_val = str(raw_attr) if raw_attr is not None else "0"
    else:
        state_val = str(state.get("state", "0"))

    # Apply optional decimal rounding before locale formatting.
    if decimals is not None:
        try:
            rounded = f"{float(state_val):.{int(decimals)}f}"
        except (ValueError, TypeError):
            rounded = state_val
    else:
        rounded = state_val
    formatted_val = _fmt(rounded, config)

    # --- Unit ---
    if show_unit:
        auto_unit = str(attrs.get("unit_of_measurement", ""))
        unit_text: str = (
            str(unit_override) if unit_override is not None else auto_unit
        )
    else:
        unit_text = ""

    # --- Name ---
    name_text: str = (
        str(name_override)
        if name_override is not None
        else str(attrs.get("friendly_name", entity_id))
    )

    # --- Card insets ---
    # Use DEFAULT_ROW_H for consistent border proportions across
    # widget sizes (gauge has no natural row_h concept).
    m = _compute_metrics(DEFAULT_ROW_H)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)

    # --- Gauge geometry ---
    # Name label: height proportional to the total widget height.
    name_font_sz = max(10, round(h * 0.07))
    name_h = round(name_font_sz * 1.8)

    # Content area width after horizontal card insets.
    content_w = w - x_off - r_inset

    # Vertical padding inside a border card to keep the arc off the
    # edge.
    vert_inset = m.padding if card_style == "border" else 0

    # Gauge arc area: content region minus the name label strip.
    # The gauge always has exactly one name label (top or bottom).
    gauge_area_h = h - name_h - 2 * vert_inset

    # Name label vertical position.
    if header_position == "top":
        gauge_area_y = vert_inset + name_h
        name_y = vert_inset + name_h // 2
    else:
        gauge_area_y = vert_inset
        name_y = h - vert_inset - name_h // 2

    # Gauge circle: largest square fitting in the arc area.
    gauge_sq = min(gauge_area_h, content_w)

    # Arc centre: centre of the gauge area (horizontal centre of
    # the content strip, vertical centre of the arc region).
    cx = float(x_off + content_w // 2)
    cy = float(gauge_area_y + gauge_area_h // 2)

    # Thick arc stroke, proportional to the gauge square.
    stroke_w = max(6, round(gauge_sq * 0.10))
    # Radius so the arc outer edge sits just inside the gauge square.
    radius = max(1, gauge_sq // 2 - stroke_w)

    # --- Arc path ---
    start_deg, end_deg, arc_angle = _GAUGE_ANGLES.get(
        gauge_type, _GAUGE_ANGLES["standard"]
    )
    arc_path = _svg_arc(cx, cy, radius, start_deg, end_deg)

    # --- Fill percentage ---
    try:
        value_f = float(state_val)
    except (ValueError, TypeError):
        value_f = min_val
    value_f = max(min_val, min(max_val, value_f))
    val_range = max_val - min_val
    fill_pct = (value_f - min_val) / val_range if val_range > 0 else 0.0
    fill_pct = max(0.0, min(1.0, fill_pct))

    # Stroke-dasharray lengths for fill mode.
    # Round linecaps extend stroke_w/2 past each dash endpoint, so
    # the two caps together overshoot by stroke_w.  Subtract that from
    # fill_length so the visible arc tip aligns with the true position.
    arc_length = 2.0 * math.pi * radius * (arc_angle / 360.0)
    fill_length = max(0.0, arc_length * fill_pct - stroke_w)
    gap_length = max(0.0, arc_length - fill_length)

    # --- Segments ---
    parsed_segs: list[dict[str, object]] = []
    for seg in segments_raw:
        if not isinstance(seg, dict):
            continue
        # isinstance narrows only to dict[Unknown, Unknown].
        seg_d = cast("dict[str, object]", seg)
        parsed_segs.append(
            {
                "from": float(str(seg_d.get("from", 0))),
                "color": _parse_segment_color(
                    seg_d.get("color", COLOR_LIGHT_GRAY)
                ),
                "label": str(seg_d.get("label", "")),
                "icon": seg_d.get("icon"),
            }
        )

    parsed_segs.sort(key=lambda s: s["from"])  # type: ignore[arg-type]
    matched_seg = _match_segment(parsed_segs, value_f)

    # Fill arc colour: matching segment or black.
    fill_color: str = (
        str(matched_seg["color"]) if matched_seg else color_to_hex(COLOR_BLACK)
    )
    segment_label: str = (
        str(matched_seg.get("label", "")) if matched_seg else ""
    )

    # Per-segment icon overrides widget-level icon.
    seg_icon: object = matched_seg.get("icon") if matched_seg else None
    effective_icon = seg_icon if seg_icon else icon_override

    # --- Icon (not shown for half gauge) ---
    # Proportional to the gauge radius; used both for icon rendering
    # and icon positioning, so computed once here.
    icon_size = max(10, round(radius * 0.30))
    icon_svg: markupsafe.Markup | str = ""
    has_icon = gauge_type != "half"
    if has_icon and effective_icon:
        icon_name = str(effective_icon)
        if icon_name.startswith("mdi:"):
            icon_name = icon_name[4:]
        with contextlib.suppress(FileNotFoundError, ValueError):
            icon_svg = _mdi_svg_filter(icon_name, icon_size)

    # --- Segment band arcs for needle mode ---
    # parsed_segs is pre-sorted by "from" ascending.
    seg_arcs: list[dict[str, object]] = []
    if needle and parsed_segs:
        for i, seg in enumerate(parsed_segs):
            seg_from = cast("float", seg["from"])
            seg_to = (
                cast("float", parsed_segs[i + 1]["from"])
                if i + 1 < len(parsed_segs)
                else max_val
            )
            seg_s_pct = (
                (seg_from - min_val) / val_range if val_range > 0 else 0.0
            )
            seg_e_pct = (
                (seg_to - min_val) / val_range if val_range > 0 else 1.0
            )
            seg_s_pct = max(0.0, min(1.0, seg_s_pct))
            seg_e_pct = max(0.0, min(1.0, seg_e_pct))
            seg_s_angle = start_deg + arc_angle * seg_s_pct
            seg_e_angle = start_deg + arc_angle * seg_e_pct
            if seg_e_angle > seg_s_angle:
                seg_arcs.append(
                    {
                        "path": _svg_arc(
                            cx, cy, radius, seg_s_angle, seg_e_angle
                        ),
                        "color": seg["color"],
                    }
                )

    # --- Needle position ---
    # Needle is a filled circle at the current-value arc position.
    needle_angle = start_deg + arc_angle * fill_pct
    needle_rad = math.radians(needle_angle)
    needle_x = cx + radius * math.cos(needle_rad)
    needle_y = cy + radius * math.sin(needle_rad)
    needle_dot_r = stroke_w // 2
    # White halo is 2 px wider on each side than the dot.
    needle_border_r = needle_dot_r + 2

    # --- Text layout ---
    # Value: large text centred at the arc centre.
    value_font_sz = max(12, round(radius * 0.45))
    value_x = cx
    value_y = cy

    # Unit: smaller text, baseline below the value glyph.
    unit_font_sz = max(10, round(radius * 0.22))
    unit_y = cy + value_font_sz // 2 + 4

    # Segment label: below the unit.
    seg_label_font_sz = max(10, round(radius * 0.20))
    seg_label_y = unit_y + unit_font_sz + 2

    # Icon position: above the value text.
    icon_x = cx - icon_size // 2
    icon_y = cy - value_font_sz // 2 - icon_size - 4

    bg_arc_color = color_to_hex(COLOR_LIGHT_GRAY)

    return {
        "w": w,
        "h": h,
        "has_entity": True,
        "card_style": card_style,
        "grayscale_levels": grayscale_levels,
        "bar_width": bar_width,
        "x_off": x_off,
        "r_inset": r_inset,
        **_metrics_context(m),
        **_color_context(),
        # Arc geometry.
        "arc_path": arc_path,
        "stroke_w": stroke_w,
        "bg_arc_color": bg_arc_color,
        "fill_color": fill_color,
        # Fill mode.
        "needle": needle,
        "fill_length": fill_length,
        "gap_length": gap_length,
        # Needle mode.
        "needle_x": needle_x,
        "needle_y": needle_y,
        "needle_dot_r": needle_dot_r,
        "needle_border_r": needle_border_r,
        "needle_color": fill_color,
        "seg_arcs": seg_arcs,
        # Value text.
        "formatted_val": formatted_val,
        "value_x": value_x,
        "value_y": value_y,
        "value_font_sz": value_font_sz,
        "value_bold": value_bold,
        # Unit text.
        "unit_text": unit_text,
        "unit_x": cx,
        "unit_y": unit_y,
        "unit_font_sz": unit_font_sz,
        # Segment label.
        "segment_label": segment_label,
        "seg_label_x": cx,
        "seg_label_y": seg_label_y,
        "seg_label_font_sz": seg_label_font_sz,
        # Icon.
        "has_icon": has_icon,
        "icon_svg": icon_svg,
        "icon_x": icon_x,
        "icon_y": icon_y,
        # Name label.
        "name_text": name_text,
        "name_x": cx,
        "name_y": name_y,
        "name_font_sz": name_font_sz,
    }

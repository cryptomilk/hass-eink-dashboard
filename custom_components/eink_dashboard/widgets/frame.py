"""Frame widget context builder."""

from __future__ import annotations

from ..const import (
    COLOR_BLACK,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ._helpers import _color_context, _widget_dim


def _build_frame_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the frame widget.

    Computes the SVG viewport dimensions and the bounding rectangle
    for the rounded-corner border element.  The border stroke is
    pre-inset by ``border_width // 2`` so the stroke grows fully
    inward, keeping the outer edge flush with the declared widget
    bounds.  Interior fill is transparent by default so underlying
    canvas content (or the white background) shows through.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``color`` (int 0–255, default ``COLOR_BLACK``),
            ``fill_color`` (int 0–255; absent = transparent),
            ``border_width`` (int px; default 2),
            ``border_radius`` (int px; default 12),
            ``x`` (default 0), ``y`` (default 0),
            ``w`` (default ``config["width"] - x``),
            ``h`` (default ``config["height"] - y``).
        config: Display config with ``width`` and ``height``.

    Returns:
        Dict consumed by ``frame.svg.j2``: ``w``, ``h``,
        ``rect_x``, ``rect_y``, ``rect_w``, ``rect_h``, ``rx``,
        ``stroke``, ``fill``, ``border_width``, plus
        ``hex_black``, ``hex_white``, ``hex_gray``,
        ``hex_light_gray``.
    """
    x = widget.get("x", 0)
    y = widget.get("y", 0)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", config["height"] - y)

    border_width: int = widget.get("border_width", 2)
    border_radius: int = widget.get("border_radius", 12)
    color: int = widget.get("color", COLOR_BLACK)

    stroke = color_to_hex(color)

    # Absent fill_color → transparent interior ("none").
    raw_fill: int | None = widget.get("fill_color")
    fill: str = color_to_hex(raw_fill) if raw_fill is not None else "none"

    # Inset the rect by border_width // 2 so the SVG stroke —
    # which is center-aligned on the path — grows fully inward,
    # matching card_container's stroke behaviour.  For odd
    # border_width the outer half-pixel is clipped by the viewport,
    # so the visible stroke is (border_width - 1) px wide.
    inset = border_width // 2

    return {
        "w": svg_w,
        "h": svg_h,
        "rect_x": inset,
        "rect_y": inset,
        "rect_w": max(1, svg_w - border_width),
        "rect_h": max(1, svg_h - border_width),
        "rx": border_radius,
        "stroke": stroke,
        "fill": fill,
        "border_width": border_width,
        **_color_context(),
    }

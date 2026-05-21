"""Separator widget context builder."""

from __future__ import annotations

from typing import Any

from ..const import COLOR_BLACK, COLOR_GRAY, PADDING
from ._helpers import _color_context, _widget_dim

type Widget = dict[str, Any]
type DisplayConfig = dict[str, Any]


def _build_separator_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the separator widget.

    Computes the SVG viewport dimensions and the bounding rectangle
    for the separator element.  Both ``"line"`` and ``"bar"`` styles
    are represented as a single ``<rect>`` whose width and height are
    pre-computed here so the template needs no conditionals.

    The ``"bar"`` style widens to 10 px on 2-level displays
    (``grayscale_levels <= 2``) so the dithered dot pattern reads
    clearly as a separator.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``direction`` (``"horizontal"`` | ``"vertical"``,
            default ``"horizontal"``),
            ``style`` (``"line"`` | ``"bar"``,
            default ``"line"``),
            ``length`` (explicit pixel length; omit for full
            span), ``x`` (default ``PADDING``),
            ``y`` (default 0).
        config: Display config with ``width``, ``height``, and
            optional ``grayscale_levels`` (default 16).

    Returns:
        Dict consumed by ``separator.svg.j2``: ``w``, ``h``,
        ``bar_w``, ``bar_h``, ``fill``.
    """
    from ..render import color_to_hex

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    direction = widget.get("direction", "horizontal")
    style = widget.get("style", "line")
    grayscale_levels = config.get("grayscale_levels", 16)

    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", config["height"] - y)

    if style == "bar":
        color: int = COLOR_GRAY
        # Widen bar on 2-level displays so the dithered dot
        # pattern reads clearly as a separator.
        thickness = 10 if grayscale_levels <= 2 else 6
    else:
        color = COLOR_BLACK
        thickness = 2

    # Default span: viewport dimension minus one PADDING unit,
    # matching the PIL formula config[dim] - PADDING - pos.
    explicit_length: int | None = widget.get("length")
    if explicit_length is not None:
        length = explicit_length
    elif direction == "vertical":
        length = svg_h - PADDING
    else:
        length = svg_w - PADDING

    fill = color_to_hex(color)

    if direction == "vertical":
        bar_w: int = thickness
        bar_h: int = length
    else:
        bar_w = length
        bar_h = thickness

    return {
        "w": svg_w,
        "h": svg_h,
        "bar_w": bar_w,
        "bar_h": bar_h,
        "fill": fill,
        **_color_context(),
    }

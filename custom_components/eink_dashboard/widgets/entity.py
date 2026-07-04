"""Entity widget context builder."""

from __future__ import annotations

from ..const import DEFAULT_ROW_H, PADDING, DisplayConfig, Widget
from ._helpers import (
    _color_context,
    _entity_info_context,
    _widget_dim,
)


def _build_entity_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the entity widget.

    Renders a two-section card: a header row (entity name on the
    left, optional icon on the right) and an info section below
    (large state value with optional unit).  Mirrors HA's Entity
    card (``hui-entity-card.ts``).

    Icon style controls circle rendering, with automatic resolution
    based on entity state when ``icon_style`` is omitted:

    - ``"filled"`` — gray-filled circle (default for active states
      when ``grayscale_levels > 2``).
    - ``"outlined"`` — white circle with black stroke (default for
      inactive states and all 2-level displays).
    - ``"none"`` — no circle; icon glyph rendered without
      decoration.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, required),
            ``name`` (display name override),
            ``icon`` (MDI icon name, e.g. ``"mdi:thermometer"``),
            ``hide_icon`` (suppress the icon; default ``False``),
            ``hide_name`` (suppress the entity name text; default
            ``False``),
            ``attribute`` (attribute key to show as value instead
            of state),
            ``unit`` (unit string override),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``),
            ``bold_value`` (render the state value in bold;
            default ``False``),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``entity.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing.
        Full context includes widget dimensions, card style,
        metrics, colors, icon geometry, header text, and info
        section value/unit.
    """
    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", 2 * DEFAULT_ROW_H)
    attribute: str | None = widget.get("attribute")
    ctx = _entity_info_context(
        widget,
        config,
        svg_h,
        svg_w,
        svg_h,
        attribute=attribute,
    )
    if ctx is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            "hide_state": False,
            **_color_context(),
        }
    return {**ctx, "has_graph": False, "hide_state": False}

"""Tile widget context builder."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import markupsafe

from ..const import (
    COLOR_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
)
from ..svg_render import _mdi_svg_filter
from ._helpers import (
    _ACTIVE_STATES,
    _auto_row_height,
    _card_insets,
    _color_context,
    _fmt,
    _metrics_context,
    _widget_dim,
)


def _build_tile_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the tile widget.

    Single-entity card with icon circle on the left, entity name
    as primary text, and optional state text as secondary.  Mirrors
    HA's Tile card (``hui-tile-card.ts``).

    Icon circle style is controlled by the ``icon_style`` config
    field:

    - ``"filled"`` — gray circle background, white icon (default
      for active entities).
    - ``"outlined"`` — white fill, black stroke circle, black icon
      (default for inactive entities).
    - ``"none"`` — no circle; icon is rendered in black.

    When ``icon_style`` is absent the style is chosen automatically:
    2-level displays always use ``"outlined"``; multi-level displays
    use ``"filled"`` for active states (per ``_ACTIVE_STATES``) and
    ``"outlined"`` otherwise.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (required entity ID),
            ``name`` (display name override),
            ``icon`` (MDI icon override, e.g. ``"mdi:lightbulb"``),
            ``hide_state`` (suppress secondary text),
            ``state_content`` (attribute name or list; first element
            used when a list is provided),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``), ``card_style``,
            ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``height``,
            ``states``, and ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``tile.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False}`` when
        the entity is absent from ``states``.  Full context
        includes: widget dimensions (``w``, ``h``), layout
        geometry (``row_h``, ``x_off``, ``r_inset``, ``lpad``,
        ``rpad``), metrics fields (``m_*`` prefix), color hex
        strings (``hex_*`` prefix), text content (``primary``,
        ``secondary``), icon data (``icon_svg``, ``letter``),
        and icon style flags (``icon_fill``, ``icon_outline``,
        ``icon_no_circle``).  The ``card_row`` ``value`` key is
        intentionally omitted — tiles have no right-aligned
        value text; the macro defaults to ``""``.
    """
    from ..render import (
        _compute_metrics,
        _device_class_icon,
        color_to_hex,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    entity_id: str = widget.get("entity", "")
    name_override = widget.get("name")
    icon_override = widget.get("icon")
    hide_state: bool = widget.get("hide_state", False)
    state_content = widget.get("state_content")
    icon_style = widget.get("icon_style")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    state = states.get(entity_id) if entity_id else None
    if state is None:
        return {
            "w": svg_w,
            "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
            "has_entity": False,
            **_color_context(),
        }

    # Single row: row_h equals svg_h.  Kept as a separate
    # variable so card_row receives the same parameter name
    # as in multi-row widgets (e.g. waste_schedule).
    svg_h = _widget_dim(widget, "h", _auto_row_height("", 1))
    row_h = svg_h
    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    # Zero lpad/rpad when card_container already insets that
    # side.
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    attrs = state.get("attributes", {})
    domain = entity_id.split(".")[0] if entity_id else ""
    state_val = state.get("state", "")

    # Primary text: name override or entity friendly_name.
    primary: str = (
        str(name_override)
        if name_override is not None
        else attrs.get("friendly_name", entity_id)
    )

    # Secondary text: attribute, default state+unit, or hidden.
    if hide_state:
        secondary: str = ""
    elif state_content is not None:
        sc: str = (
            state_content[0]
            if isinstance(state_content, list) and state_content
            else (state_content if not isinstance(state_content, list) else "")
        )
        secondary = _fmt(str(attrs.get(sc, "")), config) if sc else ""
    else:
        unit = attrs.get("unit_of_measurement", "")
        fmtd = _fmt(state_val, config)
        secondary = f"{fmtd}{unit}" if unit else fmtd

    # Icon: explicit override → letter fallback when not found.
    # No override → device_class → letter fallback.
    # When an explicit icon is requested and its file is absent,
    # skip device_class lookup so the user's intent is respected.
    icon_svg: markupsafe.Markup | str = ""
    if icon_override is not None:
        icon_name = str(icon_override)
        if icon_name.startswith("mdi:"):
            icon_name = icon_name[4:]
        with contextlib.suppress(FileNotFoundError):
            icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)
    else:
        resolved_name = _device_class_icon(attrs, state_val, domain)
        if resolved_name is None:
            raw = attrs.get("icon", "")
            if raw.startswith("mdi:"):
                resolved_name = raw[4:]
        if resolved_name:
            with contextlib.suppress(FileNotFoundError):
                icon_svg = _mdi_svg_filter(resolved_name, m.icon_inner)

    letter = ""
    if not icon_svg:
        friendly = attrs.get("friendly_name", entity_id)
        letter = friendly[:1].upper() if friendly else ""

    # Icon style: explicit config overrides auto-switching.
    is_active = state_val in _ACTIVE_STATES
    if icon_style is None:
        # 2-level displays use outlined for maximum contrast.
        # Multi-level displays switch by entity state.
        if grayscale_levels <= 2:
            resolved_style = "outlined"
        elif is_active:
            resolved_style = "filled"
        else:
            resolved_style = "outlined"
    else:
        resolved_style = str(icon_style)

    icon_outline = resolved_style == "outlined"
    icon_no_circle = resolved_style == "none"
    # Filled style always uses gray; state is conveyed by
    # icon_style (filled vs outlined), not fill colour.
    icon_fill = color_to_hex(COLOR_GRAY)
    # Widen the outline stroke on 2-level displays to avoid
    # dithering.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border

    return {
        "w": svg_w,
        "h": svg_h,
        "has_entity": True,
        "card_style": card_style,
        "bar_width": bar_width,
        **_metrics_context(m),
        **_color_context(),
        "row_h": row_h,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
        "primary": primary,
        "secondary": secondary,
        "icon_svg": icon_svg,
        "icon_fill": icon_fill,
        "icon_outline": icon_outline,
        "icon_no_circle": icon_no_circle,
        "icon_stroke_w": icon_stroke_w,
        "letter": letter,
    }

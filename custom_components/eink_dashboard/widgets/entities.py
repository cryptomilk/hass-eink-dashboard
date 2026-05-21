"""Entities widget context builder."""

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
    _title_layout,
    _widget_dim,
)


def _build_entities_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the entities widget.

    Multi-entity list card with optional title and per-row types.
    Mirrors HA's Entities card (``hui-entities-card.ts``).

    Each item in the ``entities`` config list is classified as one
    of three row types:

    - **Entity row** — a plain string entity ID, or a dict with an
      ``entity`` key (and optional ``name`` / ``icon`` overrides).
      Rendered with icon circle, primary text, and right-aligned
      state value.
    - **Divider row** — ``{"type": "divider"}``.  Rendered as a
      thin gray horizontal line.
    - **Section row** — ``{"type": "section", "label": str}``.
      Rendered as a gray sub-heading above the next group.

    Entity rows whose entity ID is absent from ``states`` are
    silently skipped.  The widget returns ``has_rows=False`` when
    no entity rows remain after filtering.

    Icon style is widget-level and applies uniformly to all entity
    rows:

    - ``"filled"`` — gray-filled circle, white icon (default for
      active states on multi-level displays).
    - ``"outlined"`` — white fill, black stroke circle, black icon
      (default for inactive states and 2-level displays).
    - ``"none"`` — no circle; icon glyph rendered in black.

    Auto-dividers — thin gray lines drawn between consecutive entity
    rows — are suppressed when a divider or section row follows the
    entity row, since those rows provide their own visual break.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entities`` (list of row configs),
            ``title`` (optional label above the card),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``), ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``entities.svg.j2``.
        Returns ``{"w": …, "h": …, "has_rows": False,
        **_color_context()}`` when no entity rows survive
        state filtering.  Full context includes ``w``, ``h``,
        ``has_rows``, title layout fields, card geometry,
        metrics (``m_*``), colors (``hex_*``), row list and
        per-row layout dicts.
    """
    from ..render import (
        _compute_metrics,
        _device_class_icon,
        color_to_hex,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    title: str = widget.get("title", "")
    icon_style = widget.get("icon_style")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    entity_configs: list = widget.get("entities", [])
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)
    colors = _color_context()

    # --- Classify rows ---
    # Absent entity states are filtered out here so layout
    # counts reflect what will actually be rendered.
    classified: list[dict[str, object]] = []
    for entry in entity_configs:
        if isinstance(entry, str):
            if entry in states:
                classified.append(
                    {
                        "row_type": "entity",
                        "entity_id": entry,
                        "name_override": None,
                        "icon_override": None,
                    }
                )
        elif isinstance(entry, dict):
            row_type = entry.get("type")
            if row_type == "divider":
                classified.append({"row_type": "divider"})
            elif row_type == "section":
                classified.append(
                    {
                        "row_type": "section",
                        "label": str(entry.get("label", "")),
                    }
                )
            else:
                eid: str = str(entry.get("entity", ""))
                if eid and eid in states:
                    classified.append(
                        {
                            "row_type": "entity",
                            "entity_id": eid,
                            "name_override": entry.get("name"),
                            "icon_override": entry.get("icon"),
                        }
                    )

    n_entity = sum(1 for r in classified if r["row_type"] == "entity")
    if n_entity == 0:
        return {
            "w": svg_w,
            "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
            "has_rows": False,
            **colors,
        }

    n_divider = sum(1 for r in classified if r["row_type"] == "divider")
    n_section = sum(1 for r in classified if r["row_type"] == "section")

    # Divider takes 15% of an entity row height.
    divider_h_base = round(DEFAULT_ROW_H * 0.15)
    # Section sub-heading takes 60% of an entity row height.
    section_h_base = round(DEFAULT_ROW_H * 0.6)

    # --- Height ---
    if "h" not in widget:
        # Auto-height: delegate to the shared fixpoint helper,
        # passing a heterogeneous content_target that accounts
        # for the mix of entity, divider, and section row
        # heights.
        content_target = (
            n_entity * DEFAULT_ROW_H
            + n_divider * divider_h_base
            + n_section * section_h_base
        )
        svg_h = _auto_row_height(
            title,
            max(1, n_entity),
            content_target=content_target,
        )
        title_font_sz, content_y, content_h = _title_layout(title, svg_h)
        row_h = DEFAULT_ROW_H
    else:
        svg_h = _widget_dim(widget, "h", DEFAULT_ROW_H)
        title_font_sz, content_y, content_h = _title_layout(title, svg_h)
        # Proportional allocation: entity rows have weight 1,
        # divider rows 0.15, section rows 0.6.
        total_weight = n_entity + n_divider * 0.15 + n_section * 0.6
        row_h = max(1, round(content_h / total_weight))

    # Sub-row heights scale with row_h.
    # Divider takes 15% of an entity row height.
    divider_h = max(1, round(row_h * 0.15))
    # Section sub-heading takes 60% of an entity row height.
    section_h = max(1, round(row_h * 0.6))

    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Widen outline stroke on 2-level displays to avoid
    # dithering.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    # Widen divider lines on 2-level displays (same rationale).
    divider_stroke_w = m.divider * 3 if grayscale_levels <= 2 else m.divider
    icon_fill = color_to_hex(COLOR_GRAY)
    # Section label font ~46% of row height (matches chip label
    # ratio).
    section_font_sz = round(row_h * 0.46)

    # --- Build row dicts ---
    rows: list[dict[str, object]] = []
    y = content_y  # absolute SVG y pointer within the canvas

    for i, cls in enumerate(classified):
        if cls["row_type"] == "divider":
            rows.append(
                {
                    "row_type": "divider",
                    "line_y": y + divider_h // 2,
                }
            )
            y += divider_h

        elif cls["row_type"] == "section":
            rows.append(
                {
                    "row_type": "section",
                    "label": str(cls.get("label", "")),
                    "font_sz": section_font_sz,
                    "text_y": y + section_h // 2,
                }
            )
            y += section_h

        else:
            entity_id = str(cls["entity_id"])
            name_override = cls["name_override"]
            icon_override = cls["icon_override"]
            state = states[entity_id]
            attrs = state.get("attributes", {})
            domain = entity_id.split(".")[0]
            state_val: str = state.get("state", "")

            primary: str = (
                str(name_override)
                if name_override is not None
                else attrs.get("friendly_name", entity_id)
            )

            unit = attrs.get("unit_of_measurement", "")
            fmtd = _fmt(state_val, config)
            value = f"{fmtd}{unit}" if unit else fmtd

            # Icon: explicit override → device_class →
            # attrs["icon"] → letter fallback.
            icon_svg: markupsafe.Markup | str = ""
            if icon_override is not None:
                icon_name: str | None = str(icon_override)
                if icon_name.startswith("mdi:"):
                    icon_name = icon_name[4:]
                with contextlib.suppress(FileNotFoundError):
                    icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)
            else:
                icon_name = _device_class_icon(attrs, state_val, domain)
                if icon_name is None:
                    raw = attrs.get("icon", "")
                    if raw.startswith("mdi:"):
                        icon_name = raw[4:]
                if icon_name:
                    with contextlib.suppress(FileNotFoundError):
                        icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)

            letter = ""
            if not icon_svg:
                friendly = attrs.get("friendly_name", entity_id)
                letter = friendly[:1].upper() if friendly else ""

            # Icon style: widget-level or auto by entity
            # state.
            is_active = state_val in _ACTIVE_STATES
            if icon_style is None:
                resolved_style = (
                    "outlined"
                    if grayscale_levels <= 2
                    else ("filled" if is_active else "outlined")
                )
            else:
                resolved_style = str(icon_style)

            icon_outline = resolved_style == "outlined"
            icon_no_circle = resolved_style == "none"

            # Auto-divider: draw after this entity row only
            # when the immediately following row is also an
            # entity row.  Explicit divider/section rows
            # break the chain.
            draw_divider = (
                i + 1 < len(classified)
                and classified[i + 1]["row_type"] == "entity"
            )

            # Clamp so rounding in the proportional-height
            # branch cannot push the last row past the
            # content area bottom.
            row_y = min(y, content_y + content_h - row_h)
            rows.append(
                {
                    "row_type": "entity",
                    "y": row_y,
                    "primary": primary,
                    "value": value,
                    "icon_svg": icon_svg,
                    "icon_fill": icon_fill,
                    "icon_outline": icon_outline,
                    "icon_no_circle": icon_no_circle,
                    "letter": letter,
                    "draw_divider": draw_divider,
                }
            )
            y += row_h

    return {
        "w": svg_w,
        "h": svg_h,
        "has_rows": True,
        "title": title,
        "title_font_sz": title_font_sz,
        "content_y": content_y,
        "content_h": content_h,
        "card_style": card_style,
        "bar_width": bar_width,
        **_metrics_context(m),
        **colors,
        "row_h": row_h,
        "rows": rows,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
        "icon_stroke_w": icon_stroke_w,
        "divider_stroke_w": divider_stroke_w,
    }

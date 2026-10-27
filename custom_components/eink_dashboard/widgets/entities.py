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

"""Entities widget context builder."""

from __future__ import annotations

from ..const import (
    COLOR_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    FontWeight,
    Widget,
    color_to_hex,
)
from ._helpers import (
    CardRow,
    _auto_row_height,
    _card_insets,
    _color_context,
    _divider_stroke_width,
    _fmt,
    _icon_stroke_width,
    _max_row_height,
    _metrics_context,
    _resolve_entity,
    _resolve_entity_icon,
    _row_context,
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
            ``"none"``),
            ``fonts`` (per-role font overrides — a mapping of role
            name to ``{"size": int, "weight": str}``; roles are
            ``"title"``, ``"row_primary"`` (the entity name),
            ``"row_secondary"``, ``"value"``, and ``"section"``.
            An omitted ``size`` keeps the widget's derived size
            scaled by the display-level ``font_scale``; an explicit
            ``size`` is absolute.  An omitted ``weight`` keeps the
            role's default: title/row_secondary/value/section
            ``"regular"``, row_primary ``"medium"``),
            ``row_height`` (maximum entity row height in px;
            default ``config["row_height"]``, scaled to the
            display's pixel density; also the per-row size when
            ``h`` is omitted),
            ``hide_icon`` (omit the icon circles; text starts at
            the left padding; default ``False``),
            ``divider_width`` (fixed stroke in px for auto and
            explicit dividers; ``0`` hides the lines; default 1),
            ``decimals`` (exact number of decimal places to show
            for every row's value; overrides HA's
            ``display_precision`` and device-class defaults),
            ``card_style``, ``x``, ``w``, ``h``.
            Entity rows never grow beyond ``row_height``; extra
            height is left blank below the rows.
        config: Display config with ``width``, ``states``, and
            ``display_levels``.

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
        _font_weight_svg,
        resolve_font,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    title: str = widget.get("title", "")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    hide_icon: bool = bool(widget.get("hide_icon", False))
    max_row_h = _max_row_height(widget, config)
    entity_configs: list = widget.get("entities", [])
    states = config.get("states", {})
    display_levels = config.get("display_levels", 16)
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
    divider_h_base = round(max_row_h * 0.15)
    # Section sub-heading takes 60% of an entity row height.
    section_h_base = round(max_row_h * 0.6)

    # --- Height ---
    if "h" not in widget:
        # Auto-height: delegate to the shared fixpoint helper,
        # passing a heterogeneous content_target that accounts
        # for the mix of entity, divider, and section row
        # heights.
        content_target = (
            n_entity * max_row_h
            + n_divider * divider_h_base
            + n_section * section_h_base
        )
        svg_h = _auto_row_height(
            title,
            max(1, n_entity),
            content_target=content_target,
        )
        title_font_sz, content_y, content_h = _title_layout(title, svg_h)
        auto_rows = True
    else:
        svg_h = _widget_dim(widget, "h", DEFAULT_ROW_H)
        title_font_sz, content_y, content_h = _title_layout(title, svg_h)
        auto_rows = False

    font_scale = config.get("font_scale", 1.0)
    if title:
        title_font_sz, title_weight = resolve_font(
            widget,
            "title",
            title_font_sz,
            FontWeight.REGULAR,
            scale=font_scale,
        )
        # _title_layout reserves the band from the *default* title
        # size (advance = 1.4 × size); re-derive it from the resolved
        # size so an enlarged title keeps its clearance from the card
        # content instead of overlapping the first row.
        content_y = round(title_font_sz * 1.4)
        content_h = svg_h - content_y
    else:
        title_weight = FontWeight.REGULAR

    if auto_rows:
        row_h = max_row_h
    else:
        # Proportional allocation: entity rows have weight 1,
        # divider rows 0.15, section rows 0.6.
        # Rows never grow beyond max_row_h so a tall widget with
        # few rows stacks them at the top at the standard size.
        total_weight = n_entity + n_divider * 0.15 + n_section * 0.6
        row_h = max(1, min(max_row_h, round(content_h / total_weight)))

    # Sub-row heights scale with row_h.
    # Divider takes 15% of an entity row height.
    divider_h = max(1, round(row_h * 0.15))
    # Section sub-heading takes 60% of an entity row height.
    section_h = max(1, round(row_h * 0.6))
    # The card frame wraps the rows only, not any unused space below.
    content_h = min(
        content_h,
        n_entity * row_h + n_divider * divider_h + n_section * section_h,
    )

    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, display_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    icon_stroke_w = _icon_stroke_width(m.border, display_levels)
    divider_stroke_w = _divider_stroke_width(widget)
    # SVG strokes are centred on the path; shift odd widths by half a
    # pixel so the line covers whole pixel rows instead of blurring
    # across two.
    divider_y_off = (divider_stroke_w % 2) / 2
    icon_fill = color_to_hex(COLOR_GRAY)
    # Section label font ~46% of row height (matches chip label
    # ratio).
    section_font_sz = round(row_h * 0.46)

    # Per-role font overrides.  Each role resolves through the shared
    # API so the widget's ``fonts`` map and the display-level
    # ``font_scale`` apply uniformly.  The entity-row metrics are
    # cross-wired (see the template): the name uses the secondary
    # size and the value the primary size, so the role defaults
    # follow the same wiring.
    row_primary_font_sz, row_primary_weight = resolve_font(
        widget,
        "row_primary",
        m.font_secondary,
        FontWeight.MEDIUM,
        scale=font_scale,
    )
    row_secondary_font_sz, row_secondary_weight = resolve_font(
        widget,
        "row_secondary",
        m.font_secondary,
        FontWeight.REGULAR,
        scale=font_scale,
    )
    value_font_sz, value_weight = resolve_font(
        widget,
        "value",
        m.font_primary,
        FontWeight.REGULAR,
        scale=font_scale,
    )
    section_font_sz, section_weight = resolve_font(
        widget,
        "section",
        section_font_sz,
        FontWeight.REGULAR,
        scale=font_scale,
    )

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
                    "font_weight": _font_weight_svg(section_weight),
                    "text_y": y + section_h // 2,
                }
            )
            y += section_h

        else:
            _raw_icon = cls["icon_override"]
            # Per-row view of the widget: the row's entity, name and
            # icon replace the widget-level keys, while decimals,
            # icon_style and hide_icon still apply to every row.
            row_widget = {
                **widget,
                "entity": cls["entity_id"],
                "name": cls["name_override"],
                "icon": str(_raw_icon) if _raw_icon is not None else None,
            }
            entity = _resolve_entity(row_widget, config)
            if entity is None:
                # Unreachable: absent entities were filtered out
                # during classification.
                continue

            unit = entity.attrs.get("unit_of_measurement", "")
            fmtd = _fmt(entity.state_val, config, entity.precision)
            value = f"{fmtd}{unit}" if unit else fmtd

            icon = _resolve_entity_icon(
                row_widget, entity, m.icon_inner, display_levels
            )

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
                    **_row_context(
                        CardRow(
                            y=row_y,
                            primary=entity.name,
                            value=value,
                            icon_svg=icon.svg,
                            icon_fill=icon_fill,
                            icon_outline=icon.outline,
                            icon_no_circle=icon.no_circle,
                            letter=icon.letter,
                        )
                    ),
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
        "title_weight": _font_weight_svg(title_weight),
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
        "divider_y_off": divider_y_off,
        "hide_icon": hide_icon,
        "row_primary_font_sz": row_primary_font_sz,
        "row_primary_weight": _font_weight_svg(row_primary_weight),
        "row_secondary_font_sz": row_secondary_font_sz,
        "row_secondary_weight": _font_weight_svg(row_secondary_weight),
        "value_font_sz": value_font_sz,
        "value_weight": _font_weight_svg(value_weight),
    }

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

"""Waste schedule widget context builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..const import (
    COLOR_BLACK,
    COLOR_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    FontWeight,
    color_to_hex,
)
from ..svg_render import _mdi_svg_filter
from ._helpers import (
    CardRow,
    _auto_row_height,
    _card_insets,
    _color_context,
    _divider_stroke_width,
    _icon_stroke_width,
    _list_row_height,
    _max_row_height,
    _metrics_context,
    _row_context,
    _title_layout,
    _widget_dim,
)

if TYPE_CHECKING:
    from ..widget_config import WasteScheduleEntry, WasteScheduleWidget


def _build_waste_schedule_context(
    widget: WasteScheduleWidget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the waste_schedule widget.

    Renders waste collection entries as card rows with urgency
    styling.  Each entry maps an entity attribute (ISO date string
    or integer day offset) to a short label and colour scheme:

    - ``days <= 1``: black-filled icon circle.
    - ``days >= 2``: outlined icon circle (white fill, black
      stroke).

    Date text is always black regardless of urgency; urgency is
    conveyed by the icon fill/outline alone.

    Two layouts are supported via the ``layout`` parameter:

    - ``"list"`` (default): one row per visible entry, each with a
      gray horizontal divider between rows; date is shown as a
      right-aligned ``value`` string.  Rows never grow beyond
      ``row_height``; extra widget height is left blank.
    - ``"card"``: only the most urgent entry (lowest day count)
      using the full widget height; date is shown as a
      ``secondary`` line below the primary label.

    By default only entries within the 0–3 day range are rendered.
    When ``show_all`` is ``True``, entries with any future date are
    included regardless of distance.  Entries with missing,
    unparseable, or past dates are always silently skipped.

    Args:
        widget: Widget config dict.  Recognised keys: ``entity``
            (entity ID whose attributes hold the dates),
            ``entries`` (list of ``{"attribute": …, "label": …}``
            dicts), ``layout`` (``"list"`` or ``"card"``),
            ``show_all`` (``bool``, default ``False``),
            ``fonts`` (per-role font overrides — a mapping of
            role name to ``{"size": int, "weight": str}``; roles
            are ``"title"``, ``"primary"``, ``"secondary"``, and
            ``"value"``.  An omitted ``size`` keeps the widget's
            derived size scaled by the display-level
            ``font_scale``; an explicit ``size`` is absolute.  An
            omitted ``weight`` keeps the role's default: title
            ``"regular"``, primary ``"medium"``, secondary and
            value ``"regular"``),
            ``row_height`` (maximum row height in px; default
            ``config["row_height"]``, scaled to the display's pixel
            density; also the per-row size when ``h`` is omitted),
            ``hide_icon`` (omit the icon circles; text starts at
            the left padding; default ``False``),
            ``divider_width`` (fixed divider stroke in px; ``0``
            hides dividers; default 1),
            ``card_style``, ``title``, ``x``, ``w``, ``h``.
        config: Display config with ``states`` (entity ID →
            state dict), ``display_levels``, ``font_scale``, and
            ``language``.

    Returns:
        Template context dict consumed by
        ``waste_schedule.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_rows": False}`` when the entity
        is absent from states, ``entries`` is empty, or no entries
        fall within the visible day range.
    """
    from ..render import (
        _compute_metrics,
        _font_weight_svg,
        _format_relative_date,
        _get_today,
        _parse_days_until,
        resolve_font,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_id: str = widget.get("entity", "")
    entries: list[WasteScheduleEntry] = widget.get("entries", [])
    layout: str = widget.get("layout", "list")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title: str = widget.get("title", "")
    show_all: bool = bool(widget.get("show_all", False))
    hide_icon: bool = bool(widget.get("hide_icon", False))
    max_row_h = _max_row_height(widget, config)
    language: str = config.get("language", "en")
    states = config.get("states", {})
    display_levels = config.get("display_levels", 16)

    empty_ctx: dict[str, object] = {
        "w": svg_w,
        "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
        "has_rows": False,
        **_color_context(),
    }
    if not entity_id or not entries:
        return empty_ctx

    entity_state = states.get(entity_id)
    if entity_state is None:
        return empty_ctx

    attrs = entity_state.get("attributes", {})

    # Resolve visible entries before computing height so the
    # auto-sizing fallback knows how many rows to accommodate.
    # Config order is preserved — equal-day entries keep the
    # order the user configured them, matching the PIL renderer.
    # Use _get_today() from render.py so tests can patch
    # "custom_components.eink_dashboard.render.date" to control
    # the date returned here.
    today = _get_today()
    visible: list[tuple[str, str, int]] = []
    for entry in entries:
        attr_key = entry.get("attribute", "")
        label = entry.get("label") or attr_key
        raw = str(attrs.get(attr_key, ""))
        if not raw:
            continue
        days = _parse_days_until(raw, today)
        if days is None or days < 0:
            continue
        if not show_all and days > 3:
            continue
        visible.append((label, raw, days))

    if not visible:
        return empty_ctx

    if layout == "card":
        # Most urgent entry only (stable sort: equal days keep
        # config order), displayed at full widget height.
        visible.sort(key=lambda e: e[2])
        visible = [visible[0]]

    # Auto-size: default to content height so the widget is no
    # taller than its rendered rows.  Explicit "h" in the widget
    # config overrides this, preserving backward compatibility.
    num_display_rows = len(visible)
    svg_h = _widget_dim(
        widget,
        "h",
        _auto_row_height(title, num_display_rows, max_row_h),
    )
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
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
    if layout == "card":
        # Single most-urgent entry fills the whole widget.
        row_h = content_h
    else:
        row_h = _list_row_height(content_h, num_display_rows, max_row_h)
        # The card frame wraps the rows only, not any unused space
        # below them.
        content_h = row_h * num_display_rows

    m = _compute_metrics(row_h)

    # Per-role font resolution.  The defaults reproduce what the
    # template rendered before the overrides existed: the title and
    # the date text were Roboto Regular, the label Roboto Medium.
    primary_font_sz, primary_weight = resolve_font(
        widget,
        "primary",
        m.font_primary,
        FontWeight.MEDIUM,
        scale=font_scale,
    )
    secondary_font_sz, secondary_weight = resolve_font(
        widget,
        "secondary",
        m.font_secondary,
        FontWeight.REGULAR,
        scale=font_scale,
    )
    value_font_sz, value_weight = resolve_font(
        widget,
        "value",
        m.font_secondary,
        FontWeight.REGULAR,
        scale=font_scale,
    )

    icon_stroke_w = _icon_stroke_width(m.border, display_levels)
    divider_stroke_w = _divider_stroke_width(widget)
    # SVG strokes are centred on the path; shift odd widths by half a
    # pixel so the line covers whole pixel rows instead of blurring
    # across two.
    divider_y_off = (divider_stroke_w % 2) / 2
    x_off, r_inset, bar_width = _card_insets(m, card_style, display_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Build the trash-can icon SVG once; all entries share the
    # same icon, only the circle fill/outline differs.
    icon_sz = m.icon_inner
    icon_svg = _mdi_svg_filter("trash-can", icon_sz)

    rows: list[dict[str, object]] = []
    for i, (label, raw, days) in enumerate(visible):
        date_str = _format_relative_date(days, raw, language)
        # Date text is always black; urgency is conveyed by the
        # icon fill/outline instead.
        date_fill = color_to_hex(COLOR_BLACK)
        use_outline = days >= 2
        # Outlined circles ignore icon_fill (macro uses white
        # fill + black stroke), but we still pass it correctly.
        icon_fill = (
            color_to_hex(COLOR_BLACK)
            if days <= 1
            else color_to_hex(COLOR_GRAY)
        )
        rows.append(
            _row_context(
                CardRow(
                    y=content_y + i * row_h,
                    primary=label,
                    # Card layout: date as secondary (below primary).
                    # List layout: date as right-aligned value.
                    secondary=(date_str if layout == "card" else ""),
                    value=("" if layout == "card" else date_str),
                    icon_svg=icon_svg,
                    icon_outline=use_outline,
                    icon_fill=icon_fill,
                    secondary_fill=date_fill,
                    value_fill=date_fill,
                )
            )
        )

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
        **_color_context(),
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
        # Per-role text sizes and SVG weight strings; ``card_row``
        # renders the weights verbatim.
        "primary_font_sz": primary_font_sz,
        "primary_weight": _font_weight_svg(primary_weight),
        "secondary_font_sz": secondary_font_sz,
        "secondary_weight": _font_weight_svg(secondary_weight),
        "value_font_sz": value_font_sz,
        "value_weight": _font_weight_svg(value_weight),
    }

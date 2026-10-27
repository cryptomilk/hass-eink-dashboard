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

"""Calendar widget context builder."""

from __future__ import annotations

from datetime import datetime

from ..const import (
    COLOR_BLACK,
    COLOR_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    FontWeight,
    Widget,
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


def _build_calendar_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the calendar widget.

    Renders upcoming calendar events as a list of card rows.
    Rows never grow beyond ``row_height``; extra widget height
    is left blank below them.
    Events are sourced from
    ``states[entity_id]["attributes"]["events"]``, which is
    injected by ``_fetch_calendar_events()`` before rendering.

    Icon urgency rules:

    - Happening now: black-filled circle.
    - Today (not now): gray-filled circle.
    - Future: outlined circle (white fill, black stroke).

    The date/time value text is always black regardless of
    urgency; the event summary name is always gray. Urgency is
    conveyed by the icon fill/outline alone.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (calendar entity ID),
            ``max_events`` (int, default 5),
            ``title`` (optional header string),
            ``fonts`` (per-role font overrides — a mapping of role
            name to ``{"size": int, "weight": str}``; roles are
            ``"title"``, ``"primary"`` (event summary),
            ``"secondary"``, and ``"value"`` (date/time).  An
            omitted ``size`` keeps the widget's derived size scaled
            by the display-level ``font_scale``; an explicit
            ``size`` is absolute.  An omitted ``weight`` keeps the
            role's default: title ``"regular"``, primary
            ``"medium"``, secondary ``"regular"``, value
            ``"regular"``),
            ``row_height`` (maximum row height in px; default
            ``config["row_height"]``, scaled to the display's pixel
            density; also the per-row size when ``h`` is omitted),
            ``hide_icon`` (omit the icon circles; text starts at
            the left padding; default ``False``),
            ``divider_width`` (fixed divider stroke in px; ``0``
            hides dividers; default 1),
            ``card_style`` (``"border"``, ``"left_bar"``,
            or ``"none"``), ``x``, ``w``, ``h``.
        config: Display config with ``states``,
            ``display_levels``, ``time_format``, and ``language``.

    Returns:
        Template context dict consumed by
        ``calendar.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_rows": False}`` when the
        entity is absent, events list is empty, or no events
        remain after capping at ``max_events``.
    """
    from ..render import (
        _compute_metrics,
        _font_weight_svg,
        _format_calendar_label,
        _get_today,
        _is_event_now,
        _parse_calendar_dt,
        resolve_font,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_id: str = widget.get("entity", "")
    max_events: int = int(widget.get("max_events", 5))
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title: str = widget.get("title", "")
    hide_icon: bool = bool(widget.get("hide_icon", False))
    max_row_h = _max_row_height(widget, config)
    time_format: str = config.get("time_format", "24")
    language: str = config.get("language", "en")
    font_scale: float = config.get("font_scale", 1.0)
    states = config.get("states", {})
    display_levels = config.get("display_levels", 16)

    empty_ctx: dict[str, object] = {
        "w": svg_w,
        "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
        "has_rows": False,
        **_color_context(),
    }

    if not entity_id:
        return empty_ctx

    entity_state = states.get(entity_id)
    if entity_state is None:
        return empty_ctx

    attrs = entity_state.get("attributes", {})
    raw_events: list[dict[str, object]] = attrs.get("events", [])

    if not raw_events:
        return empty_ctx

    visible = list(raw_events[:max_events])
    if not visible:
        return empty_ctx

    today = _get_today()
    now = datetime.now()

    num_rows = len(visible)
    svg_h = _widget_dim(
        widget,
        "h",
        _auto_row_height(title, num_rows, max_row_h),
    )
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    if title:
        title_font_sz, title_weight = resolve_font(
            widget,
            "title",
            title_font_sz,
            FontWeight.REGULAR,
            scale=font_scale,
        )
        # _title_layout reserves a band sized for the *default*
        # title size (advance = 1.4 × font size).  Re-derive it from
        # the resolved size with the same ratio, so an enlarged
        # title keeps its clearance from the card content instead of
        # overlapping the first row.
        content_y = round(title_font_sz * 1.4)
        content_h = svg_h - content_y
    else:
        title_weight = FontWeight.REGULAR
    row_h = _list_row_height(content_h, num_rows, max_row_h)
    # The card frame wraps the rows only, not any unused space below.
    content_h = row_h * num_rows

    m = _compute_metrics(row_h)
    icon_stroke_w = _icon_stroke_width(m.border, display_levels)
    divider_stroke_w = _divider_stroke_width(widget)
    # SVG strokes are centred on the path; shift odd widths by half a
    # pixel so the line covers whole pixel rows instead of blurring
    # across two.
    divider_y_off = (divider_stroke_w % 2) / 2
    x_off, r_inset, bar_width = _card_insets(m, card_style, display_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Row text roles resolve through the shared API so the widget's
    # ``fonts`` overrides and the display-level ``font_scale`` apply.
    # The value falls back to the secondary size, matching card_row's
    # own default.
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

    # Build the calendar icon once; all rows share the same glyph.
    icon_svg = _mdi_svg_filter("calendar", m.icon_inner)

    rows: list[dict[str, object]] = []
    for i, event in enumerate(visible):
        start = str(event.get("start", ""))
        end = str(event.get("end", ""))
        summary = str(event.get("summary", ""))
        all_day = bool(event.get("all_day", False))

        label = _format_calendar_label(
            start, all_day, today, time_format, language
        )
        is_now = _is_event_now(start, end, now)
        start_date, _ = _parse_calendar_dt(start)
        is_today = start_date == today

        if is_now:
            icon_fill = color_to_hex(COLOR_BLACK)
            use_outline = False
        else:
            icon_fill = color_to_hex(COLOR_GRAY)
            use_outline = not is_today
        value_fill = color_to_hex(COLOR_BLACK)

        rows.append(
            _row_context(
                CardRow(
                    y=content_y + i * row_h,
                    primary=summary,
                    value=label,
                    icon_svg=icon_svg,
                    icon_outline=use_outline,
                    icon_fill=icon_fill,
                    secondary_fill=color_to_hex(COLOR_GRAY),
                    value_fill=value_fill,
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
        "primary_font_sz": primary_font_sz,
        "primary_weight": _font_weight_svg(primary_weight),
        "secondary_font_sz": secondary_font_sz,
        "secondary_weight": _font_weight_svg(secondary_weight),
        "value_font_sz": value_font_sz,
        "value_weight": _font_weight_svg(value_weight),
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
        "icon_stroke_w": icon_stroke_w,
        "divider_stroke_w": divider_stroke_w,
        "divider_y_off": divider_y_off,
        "hide_icon": hide_icon,
    }

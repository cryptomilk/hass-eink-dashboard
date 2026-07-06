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
    Widget,
    color_to_hex,
)
from ..svg_render import _mdi_svg_filter
from ._helpers import (
    _auto_row_height,
    _card_insets,
    _color_context,
    _metrics_context,
    _title_layout,
    _widget_dim,
)


def _build_calendar_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the calendar widget.

    Renders upcoming calendar events as a list of card rows.
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
            ``bold_value`` (render the right-aligned date/time
            value in bold; default ``False``),
            ``card_style`` (``"border"``, ``"left_bar"``,
            or ``"none"``), ``x``, ``w``, ``h``.
        config: Display config with ``states``,
            ``grayscale_levels``, and ``time_format``.

    Returns:
        Template context dict consumed by
        ``calendar.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_rows": False}`` when the
        entity is absent, events list is empty, or no events
        remain after capping at ``max_events``.
    """
    from ..render import (
        _compute_metrics,
        _format_calendar_label,
        _get_today,
        _is_event_now,
        _parse_calendar_dt,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_id: str = widget.get("entity", "")
    max_events: int = int(widget.get("max_events", 5))
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title: str = widget.get("title", "")
    value_bold: bool = widget.get("bold_value", False)
    time_format: str = config.get("time_format", "24")
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

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
        _auto_row_height(title, num_rows),
    )
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    row_h = content_h // num_rows

    m = _compute_metrics(row_h)
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    divider_stroke_w = m.divider * 3 if grayscale_levels <= 2 else m.divider
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Build the calendar icon once; all rows share the same glyph.
    icon_svg = _mdi_svg_filter("calendar", m.icon_inner)

    rows: list[dict[str, object]] = []
    for i, event in enumerate(visible):
        start = str(event.get("start", ""))
        end = str(event.get("end", ""))
        summary = str(event.get("summary", ""))
        all_day = bool(event.get("all_day", False))

        label = _format_calendar_label(start, all_day, today, time_format)
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
            {
                "y": content_y + i * row_h,
                "primary": summary,
                "secondary": "",
                "value": label,
                "icon_svg": icon_svg,
                "icon_outline": use_outline,
                "icon_fill": icon_fill,
                "secondary_fill": color_to_hex(COLOR_GRAY),
                "value_fill": value_fill,
                "letter": "",
            }
        )

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
        **_color_context(),
        "row_h": row_h,
        "rows": rows,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
        "icon_stroke_w": icon_stroke_w,
        "divider_stroke_w": divider_stroke_w,
        "value_bold": value_bold,
    }

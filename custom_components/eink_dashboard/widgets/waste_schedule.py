"""Waste schedule widget context builder."""

from __future__ import annotations

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


def _build_waste_schedule_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the waste_schedule widget.

    Renders waste collection entries as card rows with urgency
    styling.  Each entry maps an entity attribute (ISO date string
    or integer day offset) to a short label and colour scheme:

    - ``days <= 1``: black-filled icon circle; date text is black
      when ``days == 0`` (today) and gray otherwise.
    - ``days >= 2``: outlined icon circle (white fill, black
      stroke); date text is gray.

    Two layouts are supported via the ``layout`` parameter:

    - ``"list"`` (default): one row per visible entry, each with a
      gray horizontal divider between rows; date is shown as a
      right-aligned ``value`` string.
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
            ``card_style``, ``title``, ``x``, ``w``, ``h``.
        config: Display config with ``states`` (entity ID →
            state dict) and ``grayscale_levels``.

    Returns:
        Template context dict consumed by
        ``waste_schedule.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_rows": False}`` when the entity
        is absent from states, ``entries`` is empty, or no entries
        fall within the visible day range.
    """
    from ..render import (
        _compute_metrics,
        _format_relative_date,
        _get_today,
        _parse_days_until,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_id: str = widget.get("entity", "")
    entries: list[dict[str, str]] = widget.get("entries", [])
    layout: str = widget.get("layout", "list")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title: str = widget.get("title", "")
    show_all: bool = bool(widget.get("show_all", False))
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

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
        _auto_row_height(title, num_display_rows),
    )
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    # card layout always trims visible to one entry above, so
    # num_display_rows == 1 and the division is equivalent to
    # content_h.
    row_h = content_h // num_display_rows

    m = _compute_metrics(row_h)
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    divider_stroke_w = m.divider * 3 if grayscale_levels <= 2 else m.divider
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Build the trash-can icon SVG once; all entries share the
    # same icon, only the circle fill/outline differs.
    icon_sz = m.icon_inner
    icon_svg = _mdi_svg_filter("trash-can", icon_sz)

    rows: list[dict[str, object]] = []
    for i, (label, raw, days) in enumerate(visible):
        date_str = _format_relative_date(days, raw)
        # days == 0 (today): black date text for urgency.
        # days >= 1: gray date text.
        date_fill = (
            color_to_hex(COLOR_BLACK)
            if days == 0
            else color_to_hex(COLOR_GRAY)
        )
        use_outline = days >= 2
        # Outlined circles ignore icon_fill (macro uses white
        # fill + black stroke), but we still pass it correctly.
        icon_fill = (
            color_to_hex(COLOR_BLACK)
            if days <= 1
            else color_to_hex(COLOR_GRAY)
        )
        rows.append(
            {
                "y": content_y + i * row_h,
                "primary": label,
                # Card layout: date as secondary (below primary).
                # List layout: date as right-aligned value.
                "secondary": (date_str if layout == "card" else ""),
                "value": ("" if layout == "card" else date_str),
                "icon_svg": icon_svg,
                "icon_outline": use_outline,
                "icon_fill": icon_fill,
                "secondary_fill": date_fill,
                "value_fill": date_fill,
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
    }

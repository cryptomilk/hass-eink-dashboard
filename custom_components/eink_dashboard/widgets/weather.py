"""Weather widget context builder."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import markupsafe

from ..const import (
    DEFAULT_CARD_STYLE,
    FONT_SIZE_WEATHER,
    PADDING,
    DisplayConfig,
    Widget,
)
from ..svg_render import (
    _ICONS_DIR,
    _build_inline_svg,
    _load_svg_paths,
    _weather_svg_filter,
)
from ._helpers import (
    _card_insets,
    _color_context,
    _fmt,
    _metrics_context,
    _widget_dim,
)

# Weather base geometry at scale=1.0
# (font_size == FONT_SIZE_WEATHER == 32).  Each value is multiplied
# by `scale` in _build_weather_context() to adapt to the configured
# font_size.  These constants are weather-specific and have no
# equivalent in WidgetMetrics; padding and divider thickness are
# derived from _compute_metrics() directly inside the builder.
#
# _WX_ROW_H must be defined first; other derived constants reference
# it.
_WX_ROW_H = 48  # 48, not DEFAULT_ROW_H (56): matches original PIL proportions
_WX_NATURAL_W = 380  # natural card width
_WX_ICON = 80  # condition icon diameter
_WX_FONT_XL = 64  # temperature font size (bold)
_WX_FONT_SM = 16  # hi/lo, detail, and forecast font
_WX_FONT_XS = 14  # precipitation text font
_WX_ICON_R_PAD = 16  # gap: condition icon → temp text
_WX_DETAIL_GAP = 2  # vertical gap above detail row
_WX_DETAIL_ICON_H = 20  # detail icon height
_WX_ICON_GAP = 4  # gap: detail icon → its text
_WX_SEP_GAP = 8  # gap above/below separator line
_WX_FC_ZONE_H = 88  # forecast zone height
_WX_PRECIP_H = _WX_FONT_SM  # line height matches font
_WX_FC_ICON = 32  # forecast day icon diameter
_WX_FC_ICON_CY = 34  # forecast icon centre Y offset
_WX_FC_HI_Y = 52  # forecast hi-temp text Y offset
_WX_FC_LO_Y = 70  # forecast lo-temp text Y offset
_WX_FC_PRECIP_Y = _WX_FC_ZONE_H  # precip text at zone bottom
_WX_MIN_FC_COLS = 5  # minimum forecast column count
_WX_LO_Y_FRAC = 0.4  # lo temp Y as fraction of temp_h
_WX_PRECIP_Y_FRAC = 0.72  # precip text Y as fraction of temp_h

_DETAIL_ICON_MAP: dict[str, str] = {
    "humidity": "wi-humidity",
    "barometer": "wi-barometer",
    "wind": "wi-strong-wind",
    "cloud": "wi-cloud",
}


def _cap_weather_font_xl(
    font_xl_size: int,
    font_xl: Any,
    font_sm: Any,
    font_xs: Any,
    temp_text: str,
    avail: int,
    today_hi: str,
    today_lo: str,
    today_precip: str,
) -> int:
    """Return font_xl capped so the temperature text fits.

    Measures the widest hi/lo/precipitation string to determine
    how far that column protrudes leftward from its right anchor,
    then reduces font_xl proportionally if the temperature text
    would overlap it.

    Args:
        font_xl_size: Nominal xl font size in pixels.
        font_xl: PIL font loaded at font_xl_size (for text
            measurement).
        font_sm: PIL font for hi/lo text measurement.
        font_xs: PIL font for precipitation text measurement.
        temp_text: Formatted temperature string (e.g. "13.8°C").
        avail: Pixel budget between temp_x and the hi/lo column.
        today_hi: High-temperature string (may be empty).
        today_lo: Low-temperature string (may be empty).
        today_precip: Precipitation string (may be empty).

    Returns:
        Capped font size; equals font_xl_size when text already
        fits.
    """
    hilo_w = 0
    if today_hi:
        hilo_w = max(hilo_w, round(font_sm.getlength(today_hi)))
    if today_lo:
        hilo_w = max(hilo_w, round(font_sm.getlength(today_lo)))
    if today_precip:
        hilo_w = max(hilo_w, round(font_xs.getlength(today_precip)))
    budget = avail - hilo_w
    temp_w = round(font_xl.getlength(temp_text))
    if budget > 0 and temp_w > budget:
        return round(font_xl_size * budget / temp_w)
    return font_xl_size


def _build_weather_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the weather widget.

    Pre-computes every position and icon SVG string so the
    Jinja2 template contains no layout logic.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity``, ``x``, ``y``, ``w``, ``font_size``,
            ``forecast_days``, ``card_style``.
        config: Display config with ``width``, ``height``,
            ``states``, ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``weather.svg.j2``.
        Returns ``{"w": …, "h": …, "has_state": False}`` when
        the entity is absent from ``states``.
    """
    # Lazy imports avoid circular dependency: render.py imports
    # svg_render.py at module level; if svg_render.py imported
    # render.py at module level the initialisation would fail.
    from ..render import (
        _DAY_ABBREV,
        _compute_metrics,
        _fmt_temp,
        _load_font,
    )

    entity_id = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id)
    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    if state is None:
        svg_h = _widget_dim(
            widget,
            "h",
            config["height"] - widget.get("y", 0),
        )
        return {
            "w": svg_w,
            "h": svg_h,
            "has_state": False,
            **_color_context(),
        }

    font_size = widget.get("font_size", FONT_SIZE_WEATHER)
    forecast_days = widget.get("forecast_days", 5)
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    grayscale_levels = config.get("grayscale_levels", 16)

    scale = font_size / FONT_SIZE_WEATHER

    # Card width: use explicit w or natural width capped to
    # canvas.
    w_override = widget.get("w")
    if w_override is not None:
        card_w = w_override
    else:
        card_w = min(round(_WX_NATURAL_W * scale), svg_w)
        # Clip SVG to content width so the editor resize box
        # matches the rendered content, not the full canvas.
        svg_w = _widget_dim(widget, "w", card_w)

    # PIL fonts for text measurement only — never used for
    # drawing.  Affects: temp_h, temp_bbox (getbbox) and
    # text_w_i (getlength) below.
    # Bold is used for font_xl because the temperature text
    # renders with font-weight="bold" in the SVG template.
    font_xl = _load_font(round(_WX_FONT_XL * scale), bold=True)
    font_sm = _load_font(round(_WX_FONT_SM * scale))

    # Entity attributes.
    condition = state.get("state", "")
    attrs = state.get("attributes", {})
    temp = attrs.get("temperature", "--")
    temp_unit = attrs.get("temperature_unit", "°C")
    humidity = attrs.get("humidity")
    wind = attrs.get("wind_speed")
    wind_unit = attrs.get("wind_speed_unit", "km/h")
    pressure = attrs.get("pressure")
    pressure_unit = attrs.get("pressure_unit", "hPa")
    cloud_coverage = attrs.get("cloud_coverage")
    forecast = attrs.get("forecast", [])

    # Card metrics — 48 at scale=1 gives card-level metrics
    # (padding~10, radius~10) matching the original PIL layout.
    m = _compute_metrics(round(_WX_ROW_H * scale))

    # Sizing constants, all proportional to scale.
    icon_size = round(_WX_ICON * scale)
    pad = m.padding
    icon_right_pad = round(_WX_ICON_R_PAD * scale)
    detail_gap = round(_WX_DETAIL_GAP * scale)
    detail_icon_h = round(_WX_DETAIL_ICON_H * scale)
    icon_gap = round(_WX_ICON_GAP * scale)
    sep_gap = round(_WX_SEP_GAP * scale)
    sep_thickness = m.divider
    forecast_zone_h = round(_WX_FC_ZONE_H * scale)
    precip_text_h = round(_WX_PRECIP_H * scale)

    # Measure temperature text height (PIL) for height
    # estimation.
    nf = config.get("number_format", "language")
    lang = config.get("language", "en")
    temp_text = f"{_fmt_temp(temp, nf, lang)}{temp_unit}"
    temp_bbox = font_xl.getbbox(temp_text)
    temp_h = temp_bbox[3] - temp_bbox[1]

    top_pad = m.padding

    # Total card height, matching PIL's formula exactly.
    row1_h = top_pad + max(icon_size, temp_h)
    detail_h = detail_gap + detail_icon_h
    has_forecast = bool(forecast) and forecast_days > 0
    if has_forecast:
        forecast_section_h = (
            sep_gap + sep_thickness + sep_gap + forecast_zone_h + precip_text_h
        )
    else:
        forecast_section_h = pad
    total_h = row1_h + detail_h + forecast_section_h + pad
    # Default to content height so the SVG is no taller than
    # its rendered content.  Without this, the editor resize box
    # spans the full remaining canvas when no explicit h is
    # configured.
    svg_h = _widget_dim(widget, "h", total_h)

    # Content insets — "border" and "left_bar" use the shared
    # helper; "none" applies its own pad so that the weather card
    # content never touches the viewport edge.
    if card_style == "none":
        content_left = pad
        content_w = card_w - 2 * pad
        bar_width = 0
    else:
        x_off, r_inset, bar_width = _card_insets(
            m, card_style, grayscale_levels
        )
        content_left = x_off
        content_w = card_w - x_off - r_inset

    content_top = top_pad

    # Row 1: condition icon + temperature + today hi/lo/precip.
    icon_cy = content_top + icon_size // 2
    icon_x = content_left
    icon_y = content_top
    temp_x = content_left + icon_size + icon_right_pad
    # dominant-baseline="central" in template — centres em-square
    # on icon_cy, matching PIL's visible-ink centering within a
    # few pixels.
    temp_y = icon_cy

    # vis_top: top of the visible temperature glyph, used as
    # anchor for the stacked hi/lo/precip text block.
    vis_top = icon_cy - temp_h // 2
    hilo_right = content_left + content_w - pad

    today_hi = ""
    today_lo = ""
    today_precip = ""
    lo_y = vis_top + round(temp_h * _WX_LO_Y_FRAC)
    precip_y = vis_top + round(temp_h * _WX_PRECIP_Y_FRAC)
    precip_unit_fc = attrs.get("precipitation_unit", "mm")
    if forecast:
        today = forecast[0]
        hi_val = today.get("temperature")
        lo_val = today.get("templow")
        p_val = today.get("precipitation")
        if hi_val is not None:
            today_hi = f"{_fmt_temp(hi_val, nf, lang)}°"
        if lo_val is not None:
            today_lo = f"{_fmt_temp(lo_val, nf, lang)}°"
        if p_val is not None:
            today_precip = f"{_fmt(str(p_val), config)}{precip_unit_fc}"

    # Cap font_xl so temp text doesn't overlap the hi/lo column.
    font_xl_size = _cap_weather_font_xl(
        round(_WX_FONT_XL * scale),
        font_xl,
        font_sm,
        _load_font(round(_WX_FONT_XS * scale)),
        temp_text,
        hilo_right - temp_x - pad,
        today_hi,
        today_lo,
        today_precip,
    )

    # row1_bottom mirrors PIL's max() between icon bottom and
    # the bottom of the temperature glyph.
    temp_y_pil = icon_cy - temp_bbox[1] - temp_h // 2
    row1_bottom = max(
        content_top + icon_size,
        temp_y_pil + temp_bbox[3],
    )

    # Condition icon SVG.
    try:
        cond_icon_svg: markupsafe.Markup | str = _weather_svg_filter(
            condition, icon_size
        )
    except (KeyError, FileNotFoundError):
        cond_icon_svg = ""

    # Detail row: icon + text pairs for weather attributes.
    detail_y = row1_bottom + detail_gap
    raw_details: list[tuple[str, str]] = []
    if humidity is not None:
        raw_details.append(("humidity", f"{_fmt(str(humidity), config)}%"))
    if pressure is not None:
        raw_details.append(
            (
                "barometer",
                f"{_fmt(str(round(pressure)), config)}{pressure_unit}",
            )
        )
    if wind is not None:
        raw_details.append(
            (
                "wind",
                f"{_fmt(str(round(wind)), config)}{wind_unit}",
            )
        )
    if cloud_coverage is not None:
        raw_details.append(
            (
                "cloud",
                f"{_fmt(str(cloud_coverage), config)}%",
            )
        )

    detail_cols = max(len(raw_details), 1)
    col_w_detail = content_w // detail_cols
    detail_items: list[dict[str, object]] = []

    for i, (icon_name, text) in enumerate(raw_details):
        col_cx = content_left + col_w_detail * i + col_w_detail // 2
        text_w_i = round(font_sm.getlength(text))
        svg_filename = _DETAIL_ICON_MAP.get(icon_name, "")
        # Wrap in Markup so Jinja2 emits the SVG verbatim.  All
        # icon strings added to the context must be Markup
        # instances.
        detail_icon_svg: markupsafe.Markup | str = ""
        if svg_filename:
            detail_path = (_ICONS_DIR / f"{svg_filename}.svg").resolve()
            try:
                detail_paths = _load_svg_paths(detail_path)
                detail_icon_svg = markupsafe.Markup(
                    _build_inline_svg(
                        detail_paths,
                        detail_icon_h,
                        "0 0 30 30",
                    )
                )
            except FileNotFoundError:
                pass
        has_detail_icon = bool(detail_icon_svg)
        icon_w = detail_icon_h + icon_gap if has_detail_icon else 0
        item_w = icon_w + text_w_i
        item_x = col_cx - item_w // 2
        detail_items.append(
            {
                "icon_svg": detail_icon_svg,
                "icon_x": item_x,
                "icon_y": detail_y,
                "text_x": (
                    item_x + detail_icon_h + icon_gap
                    if has_detail_icon
                    else item_x
                ),
                "text_y": detail_y + detail_icon_h // 2,
                "text": text,
            }
        )

    detail_bottom = detail_y + detail_icon_h

    # Forecast grid.
    forecast_entries: list[dict[str, object]] = []
    sep_x1 = 0
    sep_x2 = 0
    sep_y = 0

    if has_forecast:
        forecast_cols = max(forecast_days, _WX_MIN_FC_COLS)
        col_width = content_w // forecast_cols
        content_width = forecast_cols * col_width
        separator_y = detail_bottom + sep_gap
        sep_x1 = content_left
        sep_x2 = content_left + content_width
        sep_y = separator_y
        # sep_thickness accounts for the separator line height
        # so forecast content starts below the stroke bottom,
        # matching the sep_thickness term in
        # forecast_section_h.
        forecast_y = separator_y + sep_thickness + sep_gap
        fc_icon_size = round(_WX_FC_ICON * scale)

        if forecast_days >= forecast_cols:
            col_positions = list(range(forecast_days))
        elif forecast_days <= 1:
            col_positions = [forecast_cols // 2]
        else:
            col_positions = [
                round(i * (forecast_cols - 1) / (forecast_days - 1))
                for i in range(forecast_days)
            ]

        for idx, day in enumerate(forecast[:forecast_days]):
            col_i = col_positions[idx]
            cx = content_left + col_width * col_i + col_width // 2
            dt_str = day.get("datetime")
            if dt_str:
                day_label = _DAY_ABBREV[
                    datetime.fromisoformat(dt_str).weekday()
                ]
            else:
                day_label = ""

            day_condition = day.get("condition", "")
            try:
                fc_icon_svg: markupsafe.Markup | str = _weather_svg_filter(
                    day_condition, fc_icon_size
                )
            except (KeyError, FileNotFoundError):
                fc_icon_svg = ""

            fc_hi_val = day.get("temperature", "")
            fc_lo_val = day.get("templow", "")
            fc_hi = (
                f"{_fmt_temp(fc_hi_val, nf, lang)}°" if fc_hi_val != "" else ""
            )
            fc_lo = (
                f"{_fmt_temp(fc_lo_val, nf, lang)}°" if fc_lo_val != "" else ""
            )
            fc_p = day.get("precipitation")
            fc_precip = (
                f"{_fmt(str(fc_p), config)}{precip_unit_fc}"
                if fc_p is not None and fc_p > 0
                else ""
            )
            icon_cy_fc = forecast_y + round(_WX_FC_ICON_CY * scale)
            forecast_entries.append(
                {
                    "cx": cx,
                    "label": day_label,
                    "label_y": forecast_y,
                    "icon_svg": fc_icon_svg,
                    "icon_x": cx - fc_icon_size // 2,
                    "icon_y": (icon_cy_fc - fc_icon_size // 2),
                    "hi": fc_hi,
                    "hi_y": forecast_y + round(_WX_FC_HI_Y * scale),
                    "lo": fc_lo,
                    "lo_y": forecast_y + round(_WX_FC_LO_Y * scale),
                    "precip": fc_precip,
                    "precip_y": forecast_y + round(_WX_FC_PRECIP_Y * scale),
                }
            )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_state": True,
        "card_w": card_w,
        "total_h": total_h,
        "card_style": card_style,
        **_metrics_context(m),
        "bar_width": bar_width,
        "icon_svg": cond_icon_svg,
        "icon_x": icon_x,
        "icon_y": icon_y,
        "icon_size": icon_size,
        "temp_text": temp_text,
        "temp_x": temp_x,
        "temp_y": temp_y,
        "font_xl": font_xl_size,
        "font_sm": round(_WX_FONT_SM * scale),
        # font_xs is template-only; no PIL measurement needed.
        "font_xs": round(_WX_FONT_XS * scale),
        "hilo_right": hilo_right,
        "hi_text": today_hi,
        "hi_y": vis_top,
        "lo_text": today_lo,
        "lo_y": lo_y,
        "precip_text": today_precip,
        "precip_y": precip_y,
        "detail_items": detail_items,
        "has_forecast": has_forecast,
        "sep_x1": sep_x1,
        "sep_x2": sep_x2,
        "sep_y": sep_y,
        "sep_thickness": sep_thickness,
        "forecast_entries": forecast_entries,
        **_color_context(),
    }

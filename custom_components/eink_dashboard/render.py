from __future__ import annotations

import functools
import io
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    COLOR_WHITE,
    PADDING,
    Align,
    WidgetType,
)
from .optimize import optimize_for_eink

type Widget = dict[str, Any]
type DisplayConfig = dict[str, Any]
type RendererFn = Callable[[ImageDraw.ImageDraw, Widget, DisplayConfig], None]

_FONTS_DIR = Path(__file__).parent / "fonts"
_ICONS_DIR = Path(__file__).parent / "icons"

_KNOWN_CONDITIONS: frozenset[str] = frozenset(
    {
        "sunny",
        "clear-night",
        "cloudy",
        "partlycloudy",
        "fog",
        "hail",
        "lightning",
        "lightning-rainy",
        "pouring",
        "rainy",
        "snowy",
        "snowy-rainy",
        "windy",
        "windy-variant",
        "exceptional",
    }
)


@functools.cache
def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(1, size)
    ttf_path = _FONTS_DIR / "Roboto-Regular.ttf"
    if ttf_path.exists():
        return ImageFont.truetype(str(ttf_path), size)
    return ImageFont.load_default(size)


@functools.cache
def _load_icon(
    condition: str,
    size: int,
) -> tuple[Image.Image, Image.Image] | None:
    if condition not in _KNOWN_CONDITIONS:
        return None
    path = _ICONS_DIR / f"{condition}.png"
    if not path.exists():
        return None
    icon = Image.open(path).convert("RGBA")
    if icon.size != (size, size):
        icon = icon.resize((size, size), Image.Resampling.LANCZOS)
    gray = icon.convert("L")
    mask = icon.split()[3]
    return (gray, mask)


def render_text(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    text = widget.get("text", "")
    font_size = widget.get("font_size", 22)
    color = widget.get("color", COLOR_BLACK)
    align = widget.get("align", Align.LEFT)

    font = _load_font(font_size)
    w_override = widget.get("w")
    right_edge = x + w_override if w_override is not None else config["width"]

    if align in (Align.RIGHT, Align.CENTER):
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        if align == Align.RIGHT:
            x = right_edge - PADDING - text_w
        else:
            x = x + (right_edge - x - text_w) // 2

    draw.text((x, y), text, fill=color, font=font)


def render_line(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    _config: DisplayConfig,
) -> None:
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    x2 = widget.get("x2", x)
    y2 = widget.get("y2", y)
    color = widget.get("color", COLOR_LIGHT_GRAY)
    width = widget.get("width", 1)
    draw.line([(x, y), (x2, y2)], fill=color, width=width)


def render_separator(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    y = widget.get("y", 0)
    color = widget.get("color", COLOR_LIGHT_GRAY)
    x0 = widget.get("x", PADDING)
    w_override = widget.get("w")
    x1 = (
        x0 + w_override
        if w_override is not None
        else config["width"] - PADDING
    )
    draw.line([(x0, y), (x1, y)], fill=color, width=1)


_DAY_ABBREV = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _draw_weather_icon(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    condition: str,
) -> None:
    result = _load_icon(condition, size)
    if result is not None:
        gray, mask = result
        img.paste(gray, (cx - size // 2, cy - size // 2), mask)
    else:
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), "?", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (cx - tw // 2, cy - th // 2),
            "?",
            fill=COLOR_BLACK,
            font=font,
        )


def render_weather(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    entity_id = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id)
    if state is None:
        return

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", 22)
    forecast_days = widget.get("forecast_days", 3)
    width = config["width"]
    w_override = widget.get("w")
    right_edge = (x + w_override) if w_override is not None else width

    s = font_size / 22
    font_xl = _load_font(round(48 * s))
    font_md = _load_font(font_size)
    font_sm = _load_font(round(16 * s))

    condition = state.get("state", "")
    attrs = state.get("attributes", {})
    temp = attrs.get("temperature", "--")
    humidity = attrs.get("humidity", "--")
    wind = attrs.get("wind_speed", "--")

    img = config.get("_image")
    icon_cx = x + round(45 * s)
    icon_cy = y + round(45 * s)
    if img is not None:
        _draw_weather_icon(
            img, draw, icon_cx, icon_cy, round(64 * s), condition
        )

    draw.text(
        (x + round(100 * s), y),
        f"{temp}°C",
        fill=COLOR_BLACK,
        font=font_xl,
    )
    draw.text(
        (x + round(100 * s), y + round(54 * s)),
        condition.replace("_", " ").title(),
        fill=COLOR_GRAY,
        font=font_md,
    )

    hum_text = f"{humidity}%"
    bbox = draw.textbbox((0, 0), hum_text, font=font_md)
    hum_w = bbox[2] - bbox[0]
    draw.text(
        (right_edge - PADDING - hum_w, y + round(8 * s)),
        hum_text,
        fill=COLOR_BLACK,
        font=font_md,
    )

    wind_text = f"{wind} km/h"
    bbox = draw.textbbox((0, 0), wind_text, font=font_md)
    wind_w = bbox[2] - bbox[0]
    draw.text(
        (right_edge - PADDING - wind_w, y + round(38 * s)),
        wind_text,
        fill=COLOR_BLACK,
        font=font_md,
    )

    forecast = attrs.get("forecast", [])
    if not forecast or forecast_days <= 0:
        return

    col_width = (right_edge - x - PADDING) // forecast_days
    forecast_y = y + round(100 * s)

    draw.line(
        [
            (x, forecast_y - round(4 * s)),
            (right_edge - PADDING, forecast_y - round(4 * s)),
        ],
        fill=COLOR_LIGHT_GRAY,
        width=1,
    )

    for i, day in enumerate(forecast[:forecast_days]):
        cx = x + col_width * i + col_width // 2
        dt_str = day.get("datetime")
        if dt_str:
            dt = datetime.fromisoformat(dt_str)
            day_label = _DAY_ABBREV[dt.weekday()]
        else:
            day_label = ""
        bbox = draw.textbbox((0, 0), day_label, font=font_sm)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (cx - text_w // 2, forecast_y),
            day_label,
            fill=COLOR_GRAY,
            font=font_sm,
        )
        if img is not None:
            _draw_weather_icon(
                img,
                draw,
                cx,
                forecast_y + round(38 * s),
                round(28 * s),
                day.get("condition", ""),
            )
        hi = day.get("temperature", "")
        lo = day.get("templow", "")
        hi_lo = f"{hi}° / {lo}°"
        bbox = draw.textbbox((0, 0), hi_lo, font=font_sm)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (cx - text_w // 2, forecast_y + round(60 * s)),
            hi_lo,
            fill=COLOR_BLACK,
            font=font_sm,
        )


_SENSOR_ROW_HEIGHT = 30
_SENSOR_TITLE_ADVANCE = 32


def render_sensor_rows(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", 22)
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]
    w_override = widget.get("w")
    right_edge = (x + w_override) if w_override is not None else width

    s = font_size / 22
    font_md = _load_font(font_size)
    row_height = round(_SENSOR_ROW_HEIGHT * s)

    if title:
        draw.text((x, y), title, fill=COLOR_BLACK, font=font_md)
        y += round(_SENSOR_TITLE_ADVANCE * s)

    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        label = attrs.get("friendly_name", entity_id)
        value = state.get("state", "")
        unit = attrs.get("unit_of_measurement", "")
        display_val = f"{value}{unit}" if unit else value

        draw.text(
            (x + round(16 * s), y), label, fill=COLOR_BLACK, font=font_md
        )
        bbox = draw.textbbox((0, 0), display_val, font=font_md)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (right_edge - PADDING - text_w, y),
            display_val,
            fill=COLOR_BLACK,
            font=font_md,
        )
        y += row_height


_BATTERY_BODY_W = 22
_BATTERY_BODY_H = 10
_BATTERY_NUB_W = 2
_BATTERY_NUB_H = 4


def render_battery_bar(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    entity_id = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id)
    if state is None:
        return

    raw = state.get("state", "")
    try:
        pct = int(float(raw))
    except (ValueError, TypeError):
        return
    pct = max(0, min(100, pct))

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", 14)
    color = widget.get("color", COLOR_BLACK)

    bw = _BATTERY_BODY_W
    bh = _BATTERY_BODY_H

    draw.rectangle(
        [x, y, x + bw, y + bh],
        outline=COLOR_GRAY,
        width=1,
    )

    nub_y = y + (bh - _BATTERY_NUB_H) // 2
    draw.rectangle(
        [x + bw + 1, nub_y, x + bw + _BATTERY_NUB_W, nub_y + _BATTERY_NUB_H],
        fill=COLOR_GRAY,
    )

    fill_w = int((bw - 2) * pct / 100)
    if fill_w > 0:
        draw.rectangle(
            [x + 1, y + 1, x + 1 + fill_w, y + bh - 1],
            fill=color,
        )

    font = _load_font(font_size)
    label = f"{pct}%"
    draw.text(
        (x + bw + _BATTERY_NUB_W + 4, y - 2),
        label,
        fill=color,
        font=font,
    )


_STATUS_ICON_SIZE = 12
_STATUS_ROW_HEIGHT = 26
_STATUS_TITLE_ADVANCE = 30
_PROBLEM_DEVICE_CLASSES = {
    "door",
    "window",
    "garage_door",
    "opening",
    "moisture",
    "smoke",
    "gas",
    "problem",
    "safety",
    "tamper",
    "vibration",
}


def render_status_icons(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", 18)
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]
    w_override = widget.get("w")
    right_edge = (x + w_override) if w_override is not None else width

    s = font_size / 18
    font = _load_font(font_size)
    font_title = _load_font(round(22 * s))
    sz = round(_STATUS_ICON_SIZE * s)
    row_height = round(_STATUS_ROW_HEIGHT * s)

    if title:
        draw.text((x, y), title, fill=COLOR_BLACK, font=font_title)
        y += round(_STATUS_TITLE_ADVANCE * s)

    cur_x = x
    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        label = attrs.get("friendly_name", entity_id)
        is_on = state.get("state") == "on"
        device_class = attrs.get("device_class", "")
        is_problem = is_on and device_class in _PROBLEM_DEVICE_CLASSES

        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        item_w = sz + round(6 * s) + text_w + round(20 * s)

        if cur_x + item_w > right_edge - PADDING and cur_x > x:
            cur_x = x
            y += row_height

        icon_top = y + round(4 * s)
        if is_problem:
            draw.rectangle(
                [cur_x, icon_top, cur_x + sz, icon_top + sz],
                fill=COLOR_BLACK,
            )
        else:
            draw.rectangle(
                [cur_x, icon_top, cur_x + sz, icon_top + sz],
                outline=COLOR_GRAY,
            )

        draw.text(
            (cur_x + sz + round(6 * s), y), label, fill=COLOR_BLACK, font=font
        )

        cur_x += item_w


_WASTE_ROW_HEIGHT = 28
_WASTE_TITLE_ADVANCE = 32
_WASTE_ICON_SIZE = 10


def _parse_days_until(raw: str, today: date) -> int | None:
    try:
        target = date.fromisoformat(raw)
        return (target - today).days
    except ValueError:
        pass
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _format_relative_date(days: int | None, raw: str) -> str:
    if days is None or days < 0:
        return raw
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def render_waste_schedule(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", 18)
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]
    w_override = widget.get("w")
    right_edge = (x + w_override) if w_override is not None else width

    s = font_size / 18
    font_md = _load_font(round(22 * s))
    font_sm = _load_font(font_size)
    sz = round(_WASTE_ICON_SIZE * s)
    row_height = round(_WASTE_ROW_HEIGHT * s)

    if title:
        draw.text((x, y), title, fill=COLOR_BLACK, font=font_md)
        y += round(_WASTE_TITLE_ADVANCE * s)

    today = date.today()
    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        label = attrs.get("friendly_name", entity_id)
        raw = state.get("state", "")

        days = _parse_days_until(raw, today)
        if days is not None and (days < 0 or days > 3):
            continue
        icon_top = y + round(6 * s)
        if days is not None and days <= 1:
            draw.ellipse(
                [x, icon_top, x + sz, icon_top + sz],
                fill=COLOR_BLACK,
            )
        else:
            draw.ellipse(
                [x, icon_top, x + sz, icon_top + sz],
                outline=COLOR_GRAY,
            )

        draw.text(
            (x + sz + round(8 * s), y),
            label,
            fill=COLOR_BLACK,
            font=font_sm,
        )

        date_str = _format_relative_date(days, raw)
        bbox = draw.textbbox((0, 0), date_str, font=font_sm)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (right_edge - PADDING - text_w, y),
            date_str,
            fill=COLOR_GRAY,
            font=font_sm,
        )
        y += row_height


_RENDERERS: dict[WidgetType, RendererFn] = {
    WidgetType.TEXT: render_text,
    WidgetType.LINE: render_line,
    WidgetType.SEPARATOR: render_separator,
    WidgetType.WEATHER: render_weather,
    WidgetType.SENSOR_ROWS: render_sensor_rows,
    WidgetType.BATTERY_BAR: render_battery_bar,
    WidgetType.STATUS_ICONS: render_status_icons,
    WidgetType.WASTE_SCHEDULE: render_waste_schedule,
}


def render_dashboard(
    widget_list: list[Widget],
    config: DisplayConfig,
) -> bytes:
    config = {"width": 600, "height": 800, **config}
    w = config["width"]
    h = config["height"]
    img = Image.new("L", (w, h), COLOR_WHITE)
    config["_image"] = img
    draw = ImageDraw.Draw(img)

    for widget in widget_list:
        widget_type = widget.get("type")
        if widget_type is None:
            continue
        renderer = _RENDERERS.get(widget_type)
        if renderer is not None:
            renderer(draw, widget, config)

    rotation = config.get("rotation", 0)
    if rotation:
        img = img.rotate(rotation, expand=True)

    img = optimize_for_eink(img, config)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

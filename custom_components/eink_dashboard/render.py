from __future__ import annotations

import functools
import io
import math
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


@functools.cache
def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    ttf_path = _FONTS_DIR / "DejaVuSans.ttf"
    if ttf_path.exists():
        return ImageFont.truetype(str(ttf_path), size)
    return ImageFont.load_default(size)


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
    width = config["width"]

    if align in (Align.RIGHT, Align.CENTER):
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        if align == Align.RIGHT:
            x = width - PADDING - text_w
        else:
            x = (width - text_w) // 2

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
    x1 = config["width"] - PADDING
    draw.line([(x0, y), (x1, y)], fill=color, width=1)


_DAY_ABBREV = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _draw_weather_icon(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    condition: str,
) -> None:
    if condition == "sunny":
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=COLOR_BLACK,
            width=2,
        )
        ray_len = radius + 8
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            x0 = cx + int((radius + 3) * math.cos(rad))
            y0 = cy + int((radius + 3) * math.sin(rad))
            x1 = cx + int(ray_len * math.cos(rad))
            y1 = cy + int(ray_len * math.sin(rad))
            draw.line(
                [(x0, y0), (x1, y1)],
                fill=COLOR_BLACK,
                width=2,
            )
    elif condition in ("cloudy", "partlycloudy"):
        draw.ellipse(
            [cx - 18, cy - 8, cx + 6, cy + 12],
            fill=COLOR_GRAY,
            outline=COLOR_BLACK,
        )
        draw.ellipse(
            [cx - 8, cy - 16, cx + 16, cy + 4],
            fill=COLOR_GRAY,
            outline=COLOR_BLACK,
        )
        draw.ellipse(
            [cx + 2, cy - 6, cx + 22, cy + 14],
            fill=COLOR_GRAY,
            outline=COLOR_BLACK,
        )
        draw.rectangle(
            [cx - 16, cy + 2, cx + 20, cy + 12],
            fill=COLOR_GRAY,
        )
        draw.line(
            [(cx - 16, cy + 12), (cx + 20, cy + 12)],
            fill=COLOR_BLACK,
            width=1,
        )
        if condition == "partlycloudy":
            draw.ellipse(
                [cx + 10, cy - 22, cx + 26, cy - 6],
                outline=COLOR_BLACK,
                width=2,
            )
    elif condition == "rainy":
        draw.ellipse(
            [cx - 16, cy - 12, cx + 4, cy + 4],
            fill=COLOR_GRAY,
            outline=COLOR_BLACK,
        )
        draw.ellipse(
            [cx - 6, cy - 18, cx + 14, cy - 2],
            fill=COLOR_GRAY,
            outline=COLOR_BLACK,
        )
        draw.rectangle(
            [cx - 14, cy - 2, cx + 12, cy + 4],
            fill=COLOR_GRAY,
        )
        draw.line(
            [(cx - 14, cy + 4), (cx + 12, cy + 4)],
            fill=COLOR_BLACK,
            width=1,
        )
        for dx in [-8, 0, 8]:
            draw.line(
                [(cx + dx, cy + 8), (cx + dx - 3, cy + 18)],
                fill=COLOR_BLACK,
                width=2,
            )
    else:
        font = _load_font(radius)
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
    forecast_days = widget.get("forecast_days", 3)

    condition = state.get("state", "")
    attrs = state.get("attributes", {})
    temp = attrs.get("temperature", "--")
    humidity = attrs.get("humidity", "--")
    wind = attrs.get("wind_speed", "--")

    font_xl = _load_font(48)
    font_md = _load_font(22)
    font_sm = _load_font(16)

    icon_cx = x + 45
    icon_cy = y + 45
    _draw_weather_icon(draw, icon_cx, icon_cy, 20, condition)

    draw.text(
        (x + 100, y),
        f"{temp}°C",
        fill=COLOR_BLACK,
        font=font_xl,
    )
    draw.text(
        (x + 100, y + 54),
        condition.replace("_", " ").title(),
        fill=COLOR_GRAY,
        font=font_md,
    )

    width = config["width"]

    hum_text = f"{humidity}%"
    bbox = draw.textbbox((0, 0), hum_text, font=font_md)
    hum_w = bbox[2] - bbox[0]
    draw.text(
        (width - PADDING - hum_w, y + 8),
        hum_text,
        fill=COLOR_BLACK,
        font=font_md,
    )

    wind_text = f"{wind} km/h"
    bbox = draw.textbbox((0, 0), wind_text, font=font_md)
    wind_w = bbox[2] - bbox[0]
    draw.text(
        (width - PADDING - wind_w, y + 38),
        wind_text,
        fill=COLOR_BLACK,
        font=font_md,
    )

    forecast = attrs.get("forecast", [])
    if not forecast or forecast_days <= 0:
        return

    col_width = (width - x - PADDING) // forecast_days
    forecast_y = y + 100

    draw.line(
        [(x, forecast_y - 4), (width - PADDING, forecast_y - 4)],
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
        _draw_weather_icon(
            draw, cx, forecast_y + 38, 14, day.get("condition", "")
        )
        hi = day.get("temperature", "")
        lo = day.get("templow", "")
        hi_lo = f"{hi}° / {lo}°"
        bbox = draw.textbbox((0, 0), hi_lo, font=font_sm)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (cx - text_w // 2, forecast_y + 60),
            hi_lo,
            fill=COLOR_BLACK,
            font=font_sm,
        )


_SENSOR_ROW_HEIGHT = 30


def render_sensor_rows(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]

    font_md = _load_font(22)

    if title:
        draw.text((x, y), title, fill=COLOR_BLACK, font=font_md)
        y += 32

    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        label = attrs.get("friendly_name", entity_id)
        value = state.get("state", "")
        unit = attrs.get("unit_of_measurement", "")
        display_val = f"{value}{unit}" if unit else value

        draw.text((x + 16, y), label, fill=COLOR_BLACK, font=font_md)
        bbox = draw.textbbox((0, 0), display_val, font=font_md)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (width - PADDING - text_w, y),
            display_val,
            fill=COLOR_BLACK,
            font=font_md,
        )
        y += _SENSOR_ROW_HEIGHT


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

    font = _load_font(14)
    label = f"{pct}%"
    draw.text(
        (x + bw + _BATTERY_NUB_W + 4, y - 2),
        label,
        fill=color,
        font=font,
    )


_STATUS_ICON_SIZE = 12
_STATUS_ROW_HEIGHT = 26
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
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]

    font = _load_font(18)
    font_title = _load_font(22)

    if title:
        draw.text((x, y), title, fill=COLOR_BLACK, font=font_title)
        y += 30

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

        s = _STATUS_ICON_SIZE
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        item_w = s + 6 + text_w + 20

        if cur_x + item_w > width - PADDING and cur_x > x:
            cur_x = x
            y += _STATUS_ROW_HEIGHT

        if is_problem:
            draw.rectangle(
                [cur_x, y + 4, cur_x + s, y + 4 + s],
                fill=COLOR_BLACK,
            )
        else:
            draw.rectangle(
                [cur_x, y + 4, cur_x + s, y + 4 + s],
                outline=COLOR_GRAY,
            )

        draw.text((cur_x + s + 6, y), label, fill=COLOR_BLACK, font=font)

        cur_x += item_w


_WASTE_ROW_HEIGHT = 28
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
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]

    font_md = _load_font(22)
    font_sm = _load_font(18)

    if title:
        draw.text((x, y), title, fill=COLOR_BLACK, font=font_md)
        y += 32

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
        s = _WASTE_ICON_SIZE
        if days is not None and days <= 1:
            draw.ellipse(
                [x, y + 6, x + s, y + 6 + s],
                fill=COLOR_BLACK,
            )
        else:
            draw.ellipse(
                [x, y + 6, x + s, y + 6 + s],
                outline=COLOR_GRAY,
            )

        draw.text(
            (x + s + 8, y),
            label,
            fill=COLOR_BLACK,
            font=font_sm,
        )

        date_str = _format_relative_date(days, raw)
        bbox = draw.textbbox((0, 0), date_str, font=font_sm)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (width - PADDING - text_w, y),
            date_str,
            fill=COLOR_GRAY,
            font=font_sm,
        )
        y += _WASTE_ROW_HEIGHT


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

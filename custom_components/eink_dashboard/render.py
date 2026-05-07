"""PIL-based rendering engine for e-ink dashboard widgets."""

from __future__ import annotations

import functools
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    COLOR_WHITE,
    FONT_SIZE_DEVICE_BATTERY,
    FONT_SIZE_SENSOR_ROWS,
    FONT_SIZE_STATUS_ICONS,
    FONT_SIZE_TEXT,
    FONT_SIZE_WASTE_SCHEDULE,
    FONT_SIZE_WEATHER,
    PADDING,
    Align,
    WidgetType,
)
from .optimize import optimize_for_eink

_LOGGER = logging.getLogger(__name__)

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


def _load_font(
    size: int, medium: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Roboto at the given pixel size, falling back to PIL default.

    Args:
        size: Font size in pixels (clamped to a minimum of 1).
        medium: When True, load Roboto Medium (weight 500) instead of
            Roboto Regular (weight 400).

    Returns:
        A FreeTypeFont loaded from the TTF file, or the PIL built-in
        default font if the TTF is not found.
    """
    return _load_font_cached(max(1, size), medium)


@functools.cache
def _load_font_cached(
    size: int, medium: bool
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font at the given size (unclamped, cached).

    Separated from _load_font so that size=0 and size=1 produce distinct
    cache entries instead of colliding after the clamp.
    """
    filename = "Roboto-Medium.ttf" if medium else "Roboto-Regular.ttf"
    ttf_path = _FONTS_DIR / filename
    if ttf_path.exists():
        return ImageFont.truetype(str(ttf_path), size)
    return ImageFont.load_default(size)


def _fmt_temp(value: str | float | int) -> str:
    """Format a temperature value, omitting the decimal when it is zero."""
    n = float(value)
    return str(int(n)) if n == int(n) else str(n)


_DETAIL_ICONS: frozenset[str] = frozenset(
    {"humidity", "barometer", "wind", "cloud", "raindrop"}
)


@functools.cache
def _load_icon(
    name: str,
    size: int,
) -> tuple[Image.Image, Image.Image] | None:
    """Load and resize a PNG icon, returning (gray, mask) or None."""
    if name not in _KNOWN_CONDITIONS and name not in _DETAIL_ICONS:
        _LOGGER.debug("_load_icon: %r not in allowlist, skipping", name)
        return None
    path = _ICONS_DIR / f"{name}.png"
    if not path.exists():
        return None
    icon = Image.open(path).convert("RGBA")
    if icon.size != (size, size):
        icon = icon.resize((size, size), Image.Resampling.LANCZOS)
    gray = icon.convert("L")
    mask = icon.split()[3]
    return (gray, mask)


@dataclass(frozen=True, slots=True)
class WidgetMetrics:
    """Proportional layout dimensions derived from a widget's row height.

    All fields are pixel values computed as fixed ratios of the row height,
    with minimum clamps on fields that would become illegible at small sizes.

    Attributes:
        border: Stroke width for card outlines.
        padding: Inner padding between card edge and content.
        radius: Corner radius for rounded card rectangles.
        icon_dia: Diameter of circular status/category icons.
        font_primary: Font size for main labels and values.
        font_secondary: Font size for secondary text (dates, units).
        divider: Thickness of horizontal divider lines between rows.
        inner_gap: Horizontal gap between icon and adjacent text.
        left_bar: Width of the vertical accent bar on card left edges.
    """

    border: int
    padding: int
    radius: int
    icon_dia: int
    font_primary: int
    font_secondary: int
    divider: int
    inner_gap: int
    left_bar: int


def _compute_metrics(row_h: int) -> WidgetMetrics:
    """Compute proportional widget dimensions from a row height.

    Args:
        row_h: Height of a single row in pixels. All layout dimensions
            are derived as fixed ratios of this value.

    Returns:
        A WidgetMetrics instance with all derived pixel sizes.  See
        WidgetMetrics for field descriptions.
    """
    return WidgetMetrics(
        border=max(2, round(row_h * 0.04)),
        padding=round(row_h * 0.21),
        radius=round(row_h * 0.21),
        icon_dia=round(row_h * 0.64),
        font_primary=max(10, round(row_h * 0.32)),
        font_secondary=max(10, round(row_h * 0.25)),
        divider=max(2, round(row_h * 0.07)),
        inner_gap=round(row_h * 0.21),
        left_bar=max(2, round(row_h * 0.07)),
    )


def _draw_card_container(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    m: WidgetMetrics,
    card_style: str = "border",
    grayscale_levels: int = 16,
) -> int:
    """Draw card container decoration and return the content x-offset.

    Renders the card's visual frame based on ``card_style``.  Callers use
    the returned offset to position content so it clears the left bar
    (``"left_bar"``) or starts at the card edge (``"border"`` / ``"none"``).

    Args:
        draw: PIL ImageDraw context.
        x: Left edge of the card area in pixels.
        y: Top edge of the card area in pixels.
        w: Total width of the card area in pixels.
        h: Total height of the card area in pixels.
        m: Pre-computed layout metrics from ``_compute_metrics()``.
        card_style: One of ``"border"``, ``"left_bar"``, or ``"none"``.
        grayscale_levels: Number of gray levels on the display.  When ``<= 2``
            the left bar is widened so the dithered dot pattern is clearly
            visible on 2-level displays.  Pass
            ``config.get("grayscale_levels", 16)`` from the caller.

    Returns:
        Horizontal pixel offset from ``x`` where content should start.
        Zero for ``"border"`` and ``"none"``; positive for ``"left_bar"``.
    """
    if card_style == "border":
        draw.rounded_rectangle(
            [x, y, x + w, y + h],
            radius=m.radius,
            outline=COLOR_BLACK,
            width=m.border,
        )
        return 0
    elif card_style == "left_bar":
        bar_w = m.left_bar
        # On 2-level displays (TRMNL), widen the bar so the dithered dot
        # pattern forms a clearly visible stripe.
        if grayscale_levels <= 2:
            bar_w = max(10, m.left_bar * 3)
        draw.rectangle(
            [x, y, x + bar_w, y + h],
            fill=COLOR_GRAY,
        )
        return bar_w + m.padding
    else:  # "none"
        return 0


def _draw_card_row(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    x: int,
    y: int,
    w: int,
    row_h: int,
    m: WidgetMetrics,
    *,
    primary: str,
    secondary: str = "",
    value: str = "",
    icon: tuple[Image.Image, Image.Image] | None = None,
    icon_fill: int = COLOR_GRAY,
) -> None:
    """Draw one row inside a card container.

    Renders a single entity row with a circular icon area on the left,
    primary and optional secondary text in the center, and an optional
    right-aligned value string.  Used by SENSOR_ROWS, WASTE_SCHEDULE,
    PERSON, and ALARM widget renderers.

    Args:
        draw: PIL ImageDraw context for shapes and text.
        img: PIL Image for pasting icon PNGs via ``img.paste()``.
        x: Left edge of the row area in pixels.
        y: Top edge of the row area in pixels.
        w: Width of the row area in pixels.
        row_h: Height of the row in pixels.
        m: Pre-computed layout metrics from ``_compute_metrics()``.
        primary: Main text label (entity friendly name).  Drawn with
            Roboto Medium at ``m.font_primary`` size.
        secondary: Sub-text (state + unit), drawn below primary in gray.
            When empty, primary text is vertically centered alone.
        value: Right-aligned text (e.g. relative date).  Drawn in gray
            at ``m.font_secondary`` size.
        icon: ``(gray, mask)`` tuple from ``_load_icon()``, or
            ``None`` for letter fallback (first letter of
            ``primary``).  Resized internally to 60 % of
            ``m.icon_dia``; pass the raw original-size icon.
        icon_fill: Fill color for the icon circle background.
    """
    font_p = _load_font(m.font_primary, medium=True)
    font_s = _load_font(m.font_secondary)
    icon_x = x + m.padding

    # Draw icon circle, then place the PNG icon or a letter fallback
    # centered inside it.
    circle_y = y + (row_h - m.icon_dia) // 2
    draw.ellipse(
        [icon_x, circle_y, icon_x + m.icon_dia, circle_y + m.icon_dia],
        fill=icon_fill,
    )
    if icon is not None:
        icon_sz = round(m.icon_dia * 0.6)
        gray, mask = icon
        resized_g = gray.resize((icon_sz, icon_sz), Image.Resampling.LANCZOS)
        resized_m = mask.resize((icon_sz, icon_sz), Image.Resampling.LANCZOS)
        offset = (m.icon_dia - icon_sz) // 2
        img.paste(
            resized_g,
            (icon_x + offset, circle_y + offset),
            resized_m,
        )
    else:
        letter = primary[0].upper() if primary else "?"
        font_letter = _load_font(round(m.icon_dia * 0.5))
        # Measure at origin so lw/lh are pure glyph dimensions; font
        # size includes ascender/descender space that would shift the
        # letter off-center inside the circle.
        bbox = draw.textbbox((0, 0), letter, font=font_letter)
        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (
                icon_x + (m.icon_dia - lw) // 2,
                circle_y + (m.icon_dia - lh) // 2,
            ),
            letter,
            fill=COLOR_WHITE,
            font=font_letter,
        )
    text_x = icon_x + m.icon_dia + m.inner_gap

    # Text block (vertically centered in row)
    if secondary:
        p_bb = draw.textbbox((0, 0), primary, font=font_p)
        s_bb = draw.textbbox((0, 0), secondary, font=font_s)
        p_h = p_bb[3] - p_bb[1]
        s_h = s_bb[3] - s_bb[1]
        text_block_h = p_h + s_h
        text_y = y + (row_h - text_block_h) // 2
        draw.text((text_x, text_y), primary, fill=COLOR_BLACK, font=font_p)
        draw.text(
            (text_x, text_y + p_h),
            secondary,
            fill=COLOR_GRAY,
            font=font_s,
        )
    else:
        bbox = draw.textbbox((0, 0), primary, font=font_p)
        text_h = bbox[3] - bbox[1]
        draw.text(
            (text_x, y + (row_h - text_h) // 2),
            primary,
            fill=COLOR_BLACK,
            font=font_p,
        )

    # Right-aligned value
    if value:
        bbox = draw.textbbox((0, 0), value, font=font_s)
        vw = bbox[2] - bbox[0]
        vh = bbox[3] - bbox[1]
        draw.text(
            (x + w - m.padding - vw, y + (row_h - vh) // 2),
            value,
            fill=COLOR_GRAY,
            font=font_s,
        )


def _draw_chip(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    x: int,
    y: int,
    h: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    border: int,
    *,
    icon: tuple[Image.Image, Image.Image] | None = None,
    inverted: bool = False,
) -> int:
    """Draw a pill-shaped chip and return the x coordinate after it.

    Renders a rounded-rectangle container whose end-caps are perfect
    semicircles (``radius = h // 2``).  The chip width is computed from
    the text measurement plus horizontal padding and, when present, an
    icon.  All internal dimensions are proportional to ``h``.

    Args:
        draw: PIL ImageDraw context for shapes and text.
        img: PIL Image for pasting icon PNGs via ``img.paste()``.
        x: Left edge of the chip in pixels.
        y: Top edge of the chip in pixels.
        h: Chip height in pixels (also controls all internal sizing).
        text: Label text drawn inside the chip.
        font: Font used for ``text`` measurement and rendering.
        border: Outline stroke width in pixels.
        icon: ``(gray, mask)`` tuple from ``_load_icon()``, or
            ``None`` for a text-only chip.  Resized internally
            to ``round(h * 0.29)`` pixels; callers should load
            icons at a size at least this large to avoid
            upscaling artifacts.
        inverted: When ``True``, fill the chip black and draw text and
            icon in white (used for problem / urgent states).

    Returns:
        The x coordinate immediately to the right of the chip
        (``x + chip_w``), suitable for placing the next chip.
    """
    bbox = draw.textbbox((0, 0), text, font=font)
    # int() narrows the PIL stub type (int | float) to int so that
    # chip_w stays int and the return type matches.
    text_w = int(bbox[2] - bbox[0])
    pad_h = round(h * 0.18)
    icon_sz = round(h * 0.29)
    icon_gap = round(h * 0.14)
    chip_w = pad_h * 2 + text_w
    if icon is not None:
        chip_w += icon_sz + icon_gap
    radius = h // 2

    bg = COLOR_BLACK if inverted else COLOR_WHITE
    fg = COLOR_WHITE if inverted else COLOR_BLACK

    draw.rounded_rectangle(
        [x, y, x + chip_w, y + h],
        radius=radius,
        fill=bg,
        outline=COLOR_BLACK,
        width=border,
    )
    cx = x + pad_h
    if icon is not None:
        icon_y = y + (h - icon_sz) // 2
        gray, mask = icon
        resized_gray = gray.resize(
            (icon_sz, icon_sz), Image.Resampling.LANCZOS
        )
        resized_mask = mask.resize(
            (icon_sz, icon_sz), Image.Resampling.LANCZOS
        )
        if inverted:
            resized_gray = ImageOps.invert(resized_gray)
        img.paste(resized_gray, (cx, icon_y), resized_mask)
        cx += icon_sz + icon_gap
    # Vertically center the text glyph within the chip using the
    # measured bounding box height (not the nominal font size, which
    # includes ascender/descender space that would shift the glyph
    # upward).
    text_h = bbox[3] - bbox[1]
    text_y = y + (h - text_h) // 2
    draw.text((cx, text_y), text, fill=fg, font=font)
    return x + chip_w


def _draw_chip_flow(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    chips: list[dict[str, Any]],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    border: int,
) -> int:
    """Lay out chips in a horizontal flow with wrapping.

    Draws each chip from ``chips`` left-to-right.  When a chip would
    extend past ``x + w``, it wraps to the next line.  The first chip
    on a new line is never skipped — a chip wider than ``w`` is drawn
    at the left edge and will overflow.

    Args:
        draw: PIL ImageDraw context for shapes and text.
        img: PIL Image for icon pasting (forwarded to ``_draw_chip``).
        x: Left edge of the flow container.
        y: Top edge of the flow container.
        w: Maximum width of the flow container in pixels.
        h: Height of each chip row in pixels.
        chips: Sequence of chip descriptors.  Each dict may contain:
            ``text`` (str, required), ``icon`` (``(gray, mask)`` tuple,
            optional), ``inverted`` (bool, optional, default False).
        font: Font used for text measurement and rendering.
        border: Outline stroke width forwarded to ``_draw_chip``.

    Returns:
        The y coordinate at the bottom of the last chip row
        (``last_row_y + h``).
    """
    if not chips:
        return y
    # Chip-to-chip gap — same ratio as icon_sz by coincidence.
    gap = round(h * 0.29)
    cur_x = x
    cur_y = y
    for chip in chips:
        # Measure chip width for wrapping — must stay in sync
        # with _draw_chip()'s chip_w calculation.
        bbox = draw.textbbox((0, 0), chip["text"], font=font)
        text_w = bbox[2] - bbox[0]
        pad_h = round(h * 0.18)
        has_icon = chip.get("icon") is not None
        icon_sz = round(h * 0.29) if has_icon else 0
        icon_gap = round(h * 0.14) if has_icon else 0
        chip_w = pad_h * 2 + text_w + icon_sz + icon_gap

        # Wrap when the chip would overflow AND this is not the
        # first chip on the current line.  Note: cur_x includes
        # the trailing gap from the previous chip, so wrapping
        # is slightly eager (by one gap width).
        if cur_x + chip_w > x + w and cur_x > x:
            cur_x = x
            cur_y += h + gap
        cur_x = _draw_chip(
            draw,
            img,
            cur_x,
            cur_y,
            h,
            chip["text"],
            font,
            border,
            icon=chip.get("icon"),
            inverted=chip.get("inverted", False),
        )
        cur_x += gap
    return cur_y + h


def _compute_right_edge(x: int, widget: Widget, config_width: int) -> int:
    """Return the right boundary for content layout.

    Uses the widget's explicit width override if set, otherwise
    falls back to the full display width.

    Args:
        x: Left x-coordinate of the widget.
        widget: Widget configuration dict.
        config_width: Display width from the config.

    Returns:
        Right-edge x-coordinate.
    """
    w = widget.get("w")
    return (x + w) if w is not None else config_width


def render_text(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    """Draw a text widget with optional alignment and custom font size."""
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    text = widget.get("text", "")
    font_size = widget.get("font_size", FONT_SIZE_TEXT)
    color = widget.get("color", COLOR_BLACK)
    align = widget.get("align", Align.LEFT)

    font = _load_font(font_size)
    right_edge = _compute_right_edge(x, widget, config["width"])

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
    """Draw a straight line between two points defined by the widget."""
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
    """Draw a full-width horizontal rule at the given y position."""
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
    """Paste a weather condition icon centred at (cx, cy), or draw '?'."""
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


def _draw_detail_chip(
    img: Image.Image | None,
    draw: ImageDraw.ImageDraw,
    x: int,
    text_y: int,
    icon_name: str,
    text: str,
    icon_size: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> int:
    """Draw an icon-plus-text chip and return the x coordinate after it."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    icon_y = int(text_y + (text_h - icon_size) // 2)
    if img is not None:
        result = _load_icon(icon_name, icon_size)
        if result is not None:
            gray, mask = result
            img.paste(gray, (x, icon_y), mask)
    text_x = x + icon_size + round(icon_size * 0.25)
    draw.text((text_x, text_y), text, fill=COLOR_BLACK, font=font)
    text_w = int(bbox[2] - bbox[0])
    return text_x + text_w


def render_weather(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    """Draw current conditions, detail chips, and a multi-day forecast."""
    entity_id = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id)
    if state is None:
        _LOGGER.warning(
            "render_weather: entity %r not in states, widget will be blank",
            entity_id,
        )
        return

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", FONT_SIZE_WEATHER)
    forecast_days = widget.get("forecast_days", 5)
    width = config["width"]
    right_edge = _compute_right_edge(x, widget, width)

    s = font_size / FONT_SIZE_WEATHER
    font_xl = _load_font(round(48 * s))
    font_sm = _load_font(round(16 * s))
    font_xs = _load_font(round(14 * s))

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

    img = config.get("_image")

    # Row 1: condition icon + temperature
    icon_size = round(64 * s)
    icon_cx = x + icon_size // 2
    icon_cy = y + icon_size // 2
    if img is not None:
        _draw_weather_icon(img, draw, icon_cx, icon_cy, icon_size, condition)

    temp_text = f"{_fmt_temp(temp)}{temp_unit}"
    temp_bbox = draw.textbbox((0, 0), temp_text, font=font_xl)
    temp_h = temp_bbox[3] - temp_bbox[1]
    temp_y = y + (icon_size - temp_h) // 2
    draw.text(
        (x + icon_size + round(12 * s), temp_y),
        temp_text,
        fill=COLOR_BLACK,
        font=font_xl,
    )

    # Row 2: detail chips with small icons
    detail_y = y + icon_size + round(8 * s)
    detail_icon_size = round(18 * s)
    chip_x = x
    chip_gap = round(20 * s)

    if humidity is not None:
        chip_x = _draw_detail_chip(
            img,
            draw,
            chip_x,
            detail_y,
            "humidity",
            f"{humidity}%",
            detail_icon_size,
            font_sm,
        )
        chip_x += chip_gap
    if pressure is not None:
        chip_x = _draw_detail_chip(
            img,
            draw,
            chip_x,
            detail_y,
            "barometer",
            f"{pressure}{pressure_unit}",
            detail_icon_size,
            font_sm,
        )
        chip_x += chip_gap
    if wind is not None:
        chip_x = _draw_detail_chip(
            img,
            draw,
            chip_x,
            detail_y,
            "wind",
            f"{wind}{wind_unit}",
            detail_icon_size,
            font_sm,
        )
        chip_x += chip_gap
    if cloud_coverage is not None:
        _draw_detail_chip(
            img,
            draw,
            chip_x,
            detail_y,
            "cloud",
            f"{cloud_coverage}%",
            detail_icon_size,
            font_sm,
        )

    # Forecast
    forecast = attrs.get("forecast", [])
    if not forecast or forecast_days <= 0:
        return

    separator_y = detail_y + round(22 * s)
    draw.line(
        [(x, separator_y), (right_edge - PADDING, separator_y)],
        fill=COLOR_LIGHT_GRAY,
        width=1,
    )

    forecast_y = separator_y + round(6 * s)
    col_width = (right_edge - x - PADDING) // forecast_days

    for i, day in enumerate(forecast[:forecast_days]):
        cx = x + col_width * i + col_width // 2

        # Day label
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

        # Condition icon
        if img is not None:
            _draw_weather_icon(
                img,
                draw,
                cx,
                forecast_y + round(34 * s),
                round(28 * s),
                day.get("condition", ""),
            )

        # High temp
        hi = day.get("temperature", "")
        hi_text = f"{_fmt_temp(hi)}°" if hi != "" else ""
        bbox = draw.textbbox((0, 0), hi_text, font=font_sm)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (cx - text_w // 2, forecast_y + round(52 * s)),
            hi_text,
            fill=COLOR_BLACK,
            font=font_sm,
        )

        # Low temp
        lo = day.get("templow", "")
        lo_text = f"{_fmt_temp(lo)}°" if lo != "" else ""
        bbox = draw.textbbox((0, 0), lo_text, font=font_sm)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (cx - text_w // 2, forecast_y + round(70 * s)),
            lo_text,
            fill=COLOR_GRAY,
            font=font_sm,
        )

        # Precipitation
        precip = day.get("precipitation")
        if precip is not None and precip > 0:
            precip_unit = attrs.get("precipitation_unit", "mm")
            precip_text = f"{precip}{precip_unit}"
            bbox = draw.textbbox((0, 0), precip_text, font=font_xs)
            text_w = bbox[2] - bbox[0]
            draw.text(
                (cx - text_w // 2, forecast_y + round(88 * s)),
                precip_text,
                fill=COLOR_GRAY,
                font=font_xs,
            )


_SENSOR_ROW_HEIGHT = 30
_SENSOR_TITLE_ADVANCE = 32


def render_sensor_rows(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    """Draw a labelled list of sensor values with right-aligned readings."""
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", FONT_SIZE_SENSOR_ROWS)
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]
    right_edge = _compute_right_edge(x, widget, width)

    s = font_size / FONT_SIZE_SENSOR_ROWS
    font_md = _load_font(font_size)
    row_height = round(_SENSOR_ROW_HEIGHT * s)

    if title:
        draw.text((x, y), title, fill=COLOR_BLACK, font=font_md)
        y += round(_SENSOR_TITLE_ADVANCE * s)

    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            _LOGGER.debug(
                "render_sensor_rows: entity %r not in states", entity_id
            )
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


def render_device_battery(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    """Draw battery icon and percentage for the device's own battery."""
    level = config.get("device_battery_level")
    if level is None:
        _LOGGER.debug(
            "render_device_battery: no battery level in config, skipping"
        )
        return

    pct = max(0, min(100, int(level)))

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", FONT_SIZE_DEVICE_BATTERY)
    color = widget.get("color", COLOR_BLACK)

    s = font_size / FONT_SIZE_DEVICE_BATTERY
    bw = round(_BATTERY_BODY_W * s)
    bh = round(_BATTERY_BODY_H * s)
    nub_w = round(_BATTERY_NUB_W * s)
    nub_h = round(_BATTERY_NUB_H * s)
    nub_gap = max(1, round(s))
    gap = round(4 * s)

    font = _load_font(font_size)
    label = f"{pct}%"
    bbox = draw.textbbox((0, 0), label, font=font)
    text_h = bbox[3] - bbox[1]
    icon_y = y + bbox[1] + (text_h - bh) // 2

    draw.rectangle(
        [x, icon_y, x + bw, icon_y + bh],
        outline=COLOR_GRAY,
        width=1,
    )

    nub_y = icon_y + (bh - nub_h) // 2
    draw.rectangle(
        [x + bw + nub_gap, nub_y, x + bw + nub_gap + nub_w - 1, nub_y + nub_h],
        fill=COLOR_GRAY,
    )

    fill_w = int((bw - 2) * pct / 100)
    if fill_w > 0:
        draw.rectangle(
            [x + 1, icon_y + 1, x + 1 + fill_w, icon_y + bh - 1],
            fill=color,
        )

    draw.text(
        (x + bw + nub_gap + nub_w + gap, y),
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
    """Draw binary-sensor status icons, highlighting problem states."""
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", FONT_SIZE_STATUS_ICONS)
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]
    right_edge = _compute_right_edge(x, widget, width)

    s = font_size / FONT_SIZE_STATUS_ICONS
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
            _LOGGER.debug(
                "render_status_icons: entity %r not in states", entity_id
            )
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
    """Parse an ISO date or integer offset into days from today."""
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
    """Return 'today', 'tomorrow', 'in N days', or the original string."""
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
    """Draw upcoming waste-collection entries due within the next 3 days."""
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    font_size = widget.get("font_size", FONT_SIZE_WASTE_SCHEDULE)
    title = widget.get("title", "")
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    width = config["width"]
    right_edge = _compute_right_edge(x, widget, width)

    s = font_size / FONT_SIZE_WASTE_SCHEDULE
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
            _LOGGER.debug(
                "render_waste_schedule: entity %r not in states", entity_id
            )
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
    WidgetType.DEVICE_BATTERY: render_device_battery,
    WidgetType.STATUS_ICONS: render_status_icons,
    WidgetType.WASTE_SCHEDULE: render_waste_schedule,
}


def render_dashboard(
    widget_list: list[Widget],
    config: DisplayConfig,
) -> bytes:
    """Render all widgets onto a grayscale canvas and return PNG bytes."""
    config = {"width": 600, "height": 800, **config}
    w = config["width"]
    h = config["height"]
    img = Image.new("L", (w, h), COLOR_WHITE)
    config["_image"] = img
    draw = ImageDraw.Draw(img)

    for widget in widget_list:
        widget_type = widget.get("type")
        if widget_type is None:
            _LOGGER.warning("render_dashboard: widget has no type: %r", widget)
            continue
        renderer = _RENDERERS.get(widget_type)
        if renderer is None:
            _LOGGER.warning(
                "render_dashboard: unknown widget type %r, skipping",
                widget_type,
            )
            continue
        _LOGGER.debug(
            "render_dashboard: rendering widget type=%s entity=%s",
            widget_type,
            widget.get("entity", "N/A"),
        )
        renderer(draw, widget, config)

    mn, mx = img.getextrema()
    _LOGGER.debug(
        "render_dashboard: pre-optimize pixel range min=%d max=%d",
        mn,
        mx,
    )

    rotation = config.get("rotation", 0)
    if rotation:
        img = img.rotate(rotation, expand=True)

    img = optimize_for_eink(img, config)

    _LOGGER.debug(
        "render_dashboard: post-optimize mode=%s size=%s",
        img.mode,
        img.size,
    )

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

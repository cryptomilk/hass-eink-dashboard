"""PIL-based rendering engine for e-ink dashboard widgets."""

from __future__ import annotations

import functools
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_WHITE,
    DEFAULT_CARD_STYLE,
    PADDING,
    WidgetType,
)
from .optimize import optimize_for_eink
from .svg_render import (
    _SVG_RENDERERS,
    _svg_to_png,
    render_widget_svg,
)

_LOGGER = logging.getLogger(__name__)

type Widget = dict[str, Any]
type DisplayConfig = dict[str, Any]
type RendererFn = Callable[[ImageDraw.ImageDraw, Widget, DisplayConfig], None]

_FONTS_DIR = Path(__file__).parent / "fonts"
_ICONS_DIR = Path(__file__).parent / "icons" / "png"


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
    """Format a temperature value, omitting the decimal when it is zero.

    Returns '--' for non-numeric values such as the HA unavailable
    sentinel '--'.
    """
    try:
        n = float(value)
    except (ValueError, TypeError):
        return "--"
    return str(int(n)) if n == int(n) else str(n)


@functools.lru_cache(maxsize=256)
def _load_icon(
    name: str,
    size: int,
) -> tuple[Image.Image, Image.Image] | None:
    """Load and resize a PNG icon, returning (gray, mask) or None.

    Names with a colon prefix (e.g. ``"mdi:thermometer"``) resolve
    directly to ``icons/{prefix}/{bare}.png`` with no fallback.  Bare
    names (no colon) try ``icons/weather/`` first (backward
    compatibility for weather-widget callers), then ``icons/mdi/``.

    Args:
        name: Icon name, optionally prefixed (e.g. ``"mdi:thermometer"``
            or bare ``"sunny"``).
        size: Desired square output size in pixels.

    Returns:
        ``(gray, mask)`` tuple of mode-"L" images, or ``None`` when the
        icon file cannot be found.  The images are cached — callers must
        not mutate them in place; call ``.copy()`` or ``.resize()``
        (which returns a new image) before any modification.
    """
    if ":" in name:
        # Prefixed name: route directly to the named subdirectory.
        prefix, bare = name.split(":", 1)
        if not bare:
            _LOGGER.debug("_load_icon: %r has empty name after prefix", name)
            return None
        path = _ICONS_DIR / prefix / f"{bare}.png"
    else:
        path = _ICONS_DIR / "weather" / f"{name}.png"
        if not path.exists():
            path = _ICONS_DIR / "mdi" / f"{name}.png"
    if not path.exists():
        _LOGGER.debug("_load_icon: %r not found, skipping", name)
        return None
    icon = Image.open(path).convert("RGBA")
    if icon.size != (size, size):
        icon = icon.resize((size, size), Image.Resampling.LANCZOS)
    gray = icon.convert("L")
    mask = icon.split()[3]
    return (gray, mask)


_SENSOR_DEVICE_CLASS_ICONS: dict[str, str] = {
    "temperature": "thermometer",
    "humidity": "water-percent",
    "pressure": "gauge",
    "battery": "battery",
    "power": "flash",
    "energy": "lightning-bolt",
    "gas": "fire",
    "illuminance": "brightness-5",
    "moisture": "water-alert",
    "apparent_power": "flash-auto",
    "aqi": "air-filter",
    "carbon_dioxide": "molecule-co2",
    "carbon_monoxide": "molecule-co",
    "current": "current-ac",
    "data_size": "database",
    "distance": "ruler",
    "duration": "timer-outline",
    "frequency": "sine-wave",
    "irradiance": "sun-wireless",
    "monetary": "currency-usd",
    "nitrogen_dioxide": "smog",
    "ozone": "weather-dust",
    "ph": "ph",
    "pm25": "blur",
    "signal_strength": "signal",
    "speed": "speedometer",
    "voltage": "flash",
    "volume": "cup-water",
    "water": "water",
    "weight": "weight",
    "wind_speed": "weather-windy",
}

# (off_icon, on_icon) — index 0 = normal/closed, index 1 = active/open
_BINARY_SENSOR_DEVICE_CLASS_ICONS: dict[str, tuple[str, str]] = {
    "door": ("door-closed", "door-open"),
    "window": (
        "window-closed-variant",
        "window-open-variant",
    ),
    "garage_door": ("garage", "garage-open"),
    "lock": ("lock", "lock-open"),
    "motion": ("motion-sensor-off", "motion-sensor"),
    "smoke": (
        "smoke-detector-variant",
        "smoke-detector-variant-alert",
    ),
    "battery": ("battery", "battery-alert"),
    "battery_charging": ("battery-charging", "battery-charging"),
    "cold": ("thermometer", "snowflake"),
    "connectivity": ("wifi-off", "wifi"),
    "heat": ("thermometer", "fire-alert"),
    "light": ("brightness-5", "brightness-7"),
    "occupancy": ("home-outline", "home-account"),
    "opening": ("square-outline", "square"),
    "plug": ("power-plug-off", "power-plug"),
    "presence": ("account-outline", "account"),
    "problem": ("check-circle", "alert-circle"),
    "running": ("stop-circle", "play-circle"),
    "safety": ("shield-check", "shield-alert"),
    "sound": ("volume-off", "volume-high"),
    "tamper": ("shield-check", "shield-alert"),
    "update": ("package", "package-up"),
    "vibration": ("crop-portrait", "vibrate"),
}


def _device_class_icon(
    attrs: dict[str, Any],
    state: str,
    domain: str = "",
) -> str | None:
    """Resolve an MDI icon name from device_class, state, and domain.

    For binary sensor entities (``domain == "binary_sensor"``), looks
    up the device_class in the binary sensor mapping and returns the
    state-appropriate icon from the (off_icon, on_icon) pair.  If the
    device_class is not in the binary map, returns ``None`` (callers
    fall back to the first-letter label).  For all other domains,
    returns the single icon mapped to the device_class in the sensor
    mapping.

    Args:
        attrs: Entity attributes dict, expected to contain
            "device_class".
        state: Entity state string (e.g. "on", "off", "22.1").
        domain: HA entity domain (e.g. "binary_sensor", "sensor").
            Only "binary_sensor" triggers the binary icon map;
            all other values use the sensor map.

    Returns:
        MDI icon name without the "mdi:" prefix (e.g. "door-open",
        "thermometer"), or None when no mapping exists.
    """
    dc = attrs.get("device_class", "")
    if domain == "binary_sensor":
        pair = _BINARY_SENSOR_DEVICE_CLASS_ICONS.get(dc)
        if pair is not None:
            return pair[1] if state == "on" else pair[0]
        return None
    return _SENSOR_DEVICE_CLASS_ICONS.get(dc)


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
    card_style: str = DEFAULT_CARD_STYLE,
    grayscale_levels: int = 16,
) -> tuple[int, int]:
    """Draw card container decoration and return content insets.

    Renders the card's visual frame based on ``card_style``.  Callers use
    the returned offsets to position content so it clears the left bar
    (``"left_bar"``) or stays inside the border stroke (``"border"``).

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
        ``(x_off, right_inset)`` tuple.

        ``x_off``: horizontal pixel offset from ``x`` where content
        should start.  Add to ``x`` for the absolute content
        x-coordinate.

        ``right_inset``: pixels to subtract from the right edge so
        content stays inside the card frame.

        Callers compute content width as ``w - x_off - right_inset``.
    """
    if card_style == "border":
        draw.rounded_rectangle(
            [x, y, x + w, y + h],
            radius=m.radius,
            outline=COLOR_BLACK,
            width=m.border,
        )
        return (m.padding, m.padding)
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
        return (bar_w + m.padding, 0)
    elif card_style == "none":
        return (0, 0)
    else:
        _LOGGER.warning(
            "_draw_card_container: unknown card_style %r, treating as 'none'",
            card_style,
        )
        return (0, 0)


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
    icon_outline: bool = False,
    value_fill: int = COLOR_GRAY,
    secondary_fill: int = COLOR_GRAY,
) -> None:
    """Draw one row inside a card container.

    Renders a single entity row with a circular icon area on the
    left, primary and optional secondary text in the center, and
    an optional right-aligned value string.  Used by SENSOR_ROWS
    and WASTE_SCHEDULE widget renderers.

    Args:
        draw: PIL ImageDraw context for shapes and text.
        img: PIL Image for pasting icon PNGs via ``img.paste()``.
        x: Left edge of the row area in pixels.
        y: Top edge of the row area in pixels.
        w: Width of the row area in pixels.
        row_h: Height of the row in pixels.
        m: Pre-computed layout metrics from
            ``_compute_metrics()``.
        primary: Main text label (entity friendly name).  Drawn
            with Roboto Medium at ``m.font_primary`` size.
        secondary: Sub-text (state + unit), drawn below primary.
            When empty, primary text is vertically centered
            alone.
        value: Right-aligned text (e.g. relative date).  Drawn at
            ``m.font_secondary`` size.
        icon: ``(gray, mask)`` tuple from ``_load_icon()``, or
            ``None`` for letter fallback (first letter of
            ``primary``).  Internally downscaled to
            ``round(m.icon_dia * 0.6)`` so the circle
            background shows a visible ring; load at
            ``m.icon_dia`` (the function then downscales).
        icon_fill: Fill color for the icon circle background.
            Ignored when ``icon_outline`` is ``True``.
        icon_outline: When ``True``, draw the icon circle as a
            black outline on a white background instead of a
            solid fill.  Used for waste entries with days >= 2
            (spec: outline black icon).
        value_fill: Fill color for the right-aligned value text.
        secondary_fill: Fill color for the secondary text.
    """
    font_p = _load_font(m.font_primary, medium=True)
    font_s = _load_font(m.font_secondary)
    icon_x = x + m.padding

    # Draw icon circle, then place the PNG icon or a letter fallback
    # centered inside it.
    circle_y = y + (row_h - m.icon_dia) // 2
    if icon_outline:
        # Outline circle: white fill with black stroke — used for
        # waste entries due in 2-3 days (spec: outline black icon).
        draw.ellipse(
            [
                icon_x,
                circle_y,
                icon_x + m.icon_dia,
                circle_y + m.icon_dia,
            ],
            fill=COLOR_WHITE,
            outline=COLOR_BLACK,
            width=m.border,
        )
    else:
        draw.ellipse(
            [
                icon_x,
                circle_y,
                icon_x + m.icon_dia,
                circle_y + m.icon_dia,
            ],
            fill=icon_fill,
        )
    if icon is not None:
        # Shrink to 60 % so the circle background shows
        # a visible ring around the icon.
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
        # Measure at origin to get absolute ink bounds.
        # Subtracting bb[0]/bb[1] converts anchor coordinates (which
        # PIL places at the left-ascender) to ink-top-left coordinates,
        # so the glyph is centred on visible pixels rather than on the
        # font's ascender line.
        letter_bb = draw.textbbox((0, 0), letter, font=font_letter)
        lw, lh = letter_bb[2] - letter_bb[0], letter_bb[3] - letter_bb[1]
        draw.text(
            (
                icon_x + (m.icon_dia - lw) // 2 - letter_bb[0],
                circle_y + (m.icon_dia - lh) // 2 - letter_bb[1],
            ),
            letter,
            # Outline circles have white background, so letter
            # must be black to remain legible.
            fill=COLOR_BLACK if icon_outline else COLOR_WHITE,
            font=font_letter,
        )
    text_x = icon_x + m.icon_dia + m.inner_gap

    # Text block (vertically centered in row).
    # textbbox returns ink bounds in anchor coordinates.  PIL's default
    # "la" anchor places draw.text() at the ascender line, so bb[1] is
    # the gap between that line and the actual ink top.  Subtracting
    # bb[1] from the draw y converts anchor-y to ink-top-y, centering
    # on visible pixels rather than on the ascender/descender envelope.
    if secondary:
        p_bb = draw.textbbox((0, 0), primary, font=font_p)
        s_bb = draw.textbbox((0, 0), secondary, font=font_s)
        p_h = p_bb[3] - p_bb[1]
        s_h = s_bb[3] - s_bb[1]
        line_gap = max(2, round(row_h * 0.04))
        text_block_h = p_h + line_gap + s_h
        text_y = y + (row_h - text_block_h) // 2
        draw.text(
            (text_x, text_y - p_bb[1]),
            primary,
            fill=COLOR_BLACK,
            font=font_p,
        )
        draw.text(
            (text_x, text_y + p_h + line_gap - s_bb[1]),
            secondary,
            fill=secondary_fill,
            font=font_s,
        )
    else:
        p_bb = draw.textbbox((0, 0), primary, font=font_p)
        text_h = p_bb[3] - p_bb[1]
        draw.text(
            (text_x, y + (row_h - text_h) // 2 - p_bb[1]),
            primary,
            fill=COLOR_BLACK,
            font=font_p,
        )

    # Right-aligned value
    if value:
        v_bb = draw.textbbox((0, 0), value, font=font_s)
        vw = v_bb[2] - v_bb[0]
        vh = v_bb[3] - v_bb[1]
        draw.text(
            (x + w - m.padding - vw, y + (row_h - vh) // 2 - v_bb[1]),
            value,
            fill=value_fill,
            font=font_s,
        )


# Proportional sizing constants for pill-shaped chips.  All three
# functions (_chip_width, _draw_chip, _draw_chip_flow) must use the
# same values so width measurement and drawing stay in sync.
_CHIP_PAD_RATIO: float = 0.18
_CHIP_ICON_RATIO: float = 0.29
_CHIP_GAP_RATIO: float = 0.14
_CHIP_FONT_RATIO: float = 0.46


def _chip_width(
    draw: ImageDraw.ImageDraw,
    h: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    has_icon: bool,
) -> int:
    """Compute the total pixel width of a pill-shaped chip.

    Single source of truth for the chip width formula, shared by
    ``_draw_chip`` (drawing) and ``_draw_chip_flow`` (wrapping).
    All dimensions are proportional to ``h``.

    Args:
        draw: PIL ImageDraw context used for text measurement.
        h: Chip height in pixels.
        text: Label text inside the chip.
        font: Font used for text measurement.
        has_icon: Whether the chip includes a leading icon.

    Returns:
        Total chip width in pixels.
    """
    bbox = draw.textbbox((0, 0), text, font=font)
    # int() truncates to match canvas Math.floor() behavior.
    text_w = int(bbox[2] - bbox[0])
    pad_h = round(h * _CHIP_PAD_RATIO)
    icon_sz = round(h * _CHIP_ICON_RATIO) if has_icon else 0
    icon_gap = round(h * _CHIP_GAP_RATIO) if has_icon else 0
    return pad_h * 2 + text_w + icon_sz + icon_gap


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
    chip_w = _chip_width(draw, h, text, font, has_icon=icon is not None)
    pad_h = round(h * _CHIP_PAD_RATIO)
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
        icon_sz = round(h * _CHIP_ICON_RATIO)
        icon_gap = round(h * _CHIP_GAP_RATIO)
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
    # Vertically center the text glyph within the chip.  Subtracting
    # bbox[1] converts the "la" anchor y to the actual ink top so the
    # glyph is centred on visible pixels, not on the ascender line.
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    text_y = y + (h - text_h) // 2 - bbox[1]
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
        h: Height of each chip row in pixels.  Also controls
            the inter-chip gap (``round(h * 0.29)``), which
            equals the icon size by design so the gaps feel
            proportional to the chip content.
        chips: Sequence of chip descriptors.  Each dict may contain:
            ``text`` (str, required), ``icon`` (``(gray, mask)`` tuple,
            optional — both an absent key and an explicit ``None`` value
            mean no icon), ``inverted`` (bool, optional, default False).
        font: Font used for text measurement and rendering.
        border: Outline stroke width forwarded to ``_draw_chip``.

    Returns:
        The y coordinate at the bottom of the last chip row
        (``last_row_y + h``).
    """
    if not chips:
        # Nothing drawn: don't advance y.
        return y
    # Chip-to-chip gap — same ratio as icon size, by design.
    gap = round(h * _CHIP_ICON_RATIO)
    cur_x = x
    cur_y = y
    for chip in chips:
        chip_w = _chip_width(
            draw,
            h,
            chip["text"],
            font,
            has_icon=chip.get("icon") is not None,
        )

        # Add inter-chip gap and wrap when the chip would
        # overflow.  The gap is skipped for the first chip on
        # each line (cur_x == x).
        if cur_x > x:
            if cur_x + gap + chip_w > x + w:
                cur_x = x
                cur_y += h + gap
            else:
                cur_x += gap
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
    return cur_y + h


_DAY_ABBREV = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


_PROBLEM_DEVICE_CLASSES = {
    "door",
    "window",
    "garage_door",
    "opening",
    "moisture",
    "smoke",
    "problem",
    "safety",
    "tamper",
    "vibration",
}


def _parse_days_until(raw: str, today: date) -> int | None:
    """Parse a date string into the number of days from *today*.

    Tries two formats in order: first as an ISO date or datetime
    string (only the first 10 characters — ``YYYY-MM-DD`` — are
    parsed, so full datetime strings like ``"2026-05-03T10:00:00"``
    are accepted), then as a plain integer string (e.g. ``"3"``).
    Returns ``None`` when neither format matches.

    Args:
        raw: Date string from the entity attribute value.
        today: Reference date used to compute the day delta.

    Returns:
        Number of days from *today* to the target date (positive =
        future, negative = past), or ``None`` if *raw* cannot be
        parsed as either an ISO date or an integer.
    """
    try:
        # Slice to 10 chars to handle full ISO datetime strings
        # like "2026-05-03T10:00:00" — mirrors TypeScript's
        # raw.slice(0, 10) in parseDaysUntil().
        target = date.fromisoformat(raw[:10])
        return (target - today).days
    except ValueError:
        pass
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _format_relative_date(days: int | None, raw: str) -> str:
    """Format a day offset as a human-readable relative label.

    Converts a numeric day offset into the friendly string shown as
    the right-aligned date value in waste schedule rows.  When
    *days* is ``None`` or negative (past dates), *raw* is returned
    verbatim so the original attribute string is visible rather than
    silently blank.

    Args:
        days: Day offset from today (0 = today, 1 = tomorrow,
            positive = future).  ``None`` or negative values pass
            through to *raw*.
        raw: Original attribute value string, returned unchanged
            when *days* cannot be formatted as a relative label.

    Returns:
        ``"today"``, ``"tomorrow"``, ``"in N days"`` for non-negative
        offsets, or *raw* unchanged for ``None`` / negative *days*.
    """
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
    """Draw waste collection entries as card rows with urgency styling.

    Supports two layouts: ``"list"`` (default) shows all entries
    due within 3 days as rows with dividers, ``"card"`` shows only
    the most urgent entry using the full widget height.

    Data comes from a single entity whose attributes contain
    waste types as keys with ISO date values.  The ``entries``
    config maps attribute keys to short display labels.

    Args:
        draw: PIL ImageDraw context.
        widget: Widget config with entity, entries, x, y, w, h,
            layout, card_style, and optional title.
        config: Display config with states and _image.
    """
    img: Image.Image = config["_image"]
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    w = widget.get("w", config["width"] - x)
    h = widget.get("h", 168)
    title = widget.get("title", "")
    entity_id: str = widget.get("entity", "")
    entries: list[dict[str, str]] = widget.get("entries", [])
    layout = widget.get("layout", "list")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    if not entity_id or not entries:
        return

    state = states.get(entity_id)
    if state is None:
        _LOGGER.debug(
            "render_waste_schedule: entity %r not in states",
            entity_id,
        )
        return
    attrs = state.get("attributes", {})

    # Title above the card (gray, scales with h)
    if title:
        title_font_sz = max(10, round(h * 0.14))
        title_font = _load_font(title_font_sz)
        draw.text(
            (x, y),
            title,
            fill=COLOR_GRAY,
            font=title_font,
        )
        title_advance = round(title_font_sz * 1.4)
        y += title_advance
        h -= title_advance

    # Resolve entries: look up each attribute, parse days,
    # filter to the 0–3 day range.  Entries are appended in
    # config order, which matters for the stable sort below —
    # equal-days entries stay in the order the user configured them.
    today = date.today()
    visible: list[tuple[str, str, int]] = []
    for entry in entries:
        attr_key = entry.get("attribute", "")
        label = entry.get("label") or attr_key
        raw = str(attrs.get(attr_key, ""))
        if not raw:
            continue
        days = _parse_days_until(raw, today)
        if days is None or days < 0 or days > 3:
            continue
        visible.append((label, raw, days))

    if not visible:
        return

    if layout == "card":
        # Show the most urgent entry (lowest days value).
        # Stable sort: equal-days entries keep config order.
        visible.sort(key=lambda e: e[2])
        label, raw, days = visible[0]
        row_h = h
        m = _compute_metrics(row_h)
        x_off, r_inset = _draw_card_container(
            draw,
            x,
            y,
            w,
            h,
            m,
            card_style,
            grayscale_levels,
        )
        cx, cw = x + x_off, w - x_off - r_inset
        # Black icon for today/tomorrow, outline for days 2-3
        icon_fill = COLOR_BLACK if days <= 1 else COLOR_GRAY
        use_outline = days >= 2
        icon = _load_icon("mdi:trash-can", m.icon_dia)
        date_str = _format_relative_date(days, raw)
        # Today entries get black date text for urgency
        sf = COLOR_BLACK if days == 0 else COLOR_GRAY
        _draw_card_row(
            draw,
            img,
            cx,
            y,
            cw,
            row_h,
            m,
            primary=label,
            secondary=date_str,
            icon=icon,
            icon_fill=icon_fill,
            icon_outline=use_outline,
            secondary_fill=sf,
        )
    else:
        # List layout: one row per visible entry
        n = len(visible)
        row_h = h // n
        m = _compute_metrics(row_h)
        x_off, r_inset = _draw_card_container(
            draw,
            x,
            y,
            w,
            h,
            m,
            card_style,
            grayscale_levels,
        )
        cx, cw = x + x_off, w - x_off - r_inset
        icon = _load_icon("mdi:trash-can", m.icon_dia)

        for i, (label, raw, days) in enumerate(visible):
            row_y = y + i * row_h
            icon_fill = COLOR_BLACK if days <= 1 else COLOR_GRAY
            use_outline = days >= 2
            date_str = _format_relative_date(days, raw)
            # Today entries get black date text for urgency
            vf = COLOR_BLACK if days == 0 else COLOR_GRAY
            _draw_card_row(
                draw,
                img,
                cx,
                row_y,
                cw,
                row_h,
                m,
                primary=label,
                value=date_str,
                icon=icon,
                icon_fill=icon_fill,
                icon_outline=use_outline,
                value_fill=vf,
            )
            # Gray divider between rows (not after last)
            if i < n - 1:
                div_y = row_y + row_h
                draw.line(
                    [
                        (cx + m.padding, div_y),
                        (cx + cw - m.padding, div_y),
                    ],
                    fill=COLOR_GRAY,
                    width=m.divider,
                )


_RENDERERS: dict[WidgetType, RendererFn] = {
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
            _LOGGER.warning(
                "render_dashboard: widget has no type: %r",
                widget,
            )
            continue

        # SVG-first dispatch: render to PNG and paste onto the
        # canvas.  Fall back to the PIL renderer otherwise.
        if widget_type in _SVG_RENDERERS:
            wx = widget.get("x", PADDING)
            wy = widget.get("y", 0)
            sw = widget.get("w", w - wx)
            sh = widget.get("h", h - wy)
            _LOGGER.debug(
                "render_dashboard: SVG rendering type=%s at (%d,%d) %dx%d",
                widget_type,
                wx,
                wy,
                sw,
                sh,
            )
            svg = render_widget_svg(widget, config)
            # Omit height so resvg uses the SVG's intrinsic
            # height.  Widgets whose content wraps beyond the
            # declared h (e.g. status_icons) set the SVG height
            # to the full content height in their context builder.
            png = _svg_to_png(svg, sw)
            widget_img = Image.open(io.BytesIO(png)).convert("L")
            img.paste(widget_img, (wx, wy))
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

"""Dashboard rendering orchestrator and shared utility helpers.

Thin wrapper around the SVG pipeline in ``svg_render.py``.
``render_dashboard()`` rasterises each widget SVG individually,
pastes onto a canvas, and applies rotation plus e-ink
optimisation.  Shared helpers (``_load_font``,
``_compute_metrics``, ``_fmt_temp``, etc.) live here to avoid
circular imports — ``svg_render.py`` imports them lazily at call
time.
"""

from __future__ import annotations

import functools
import io
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageFont

from .conditions import check_conditions
from .const import DEFAULT_ROW_H, PADDING
from .optimize import optimize_for_eink
from .svg_render import (
    _SVG_RENDERERS,
    _svg_to_png,
    render_widget_svg,
)

_LOGGER = logging.getLogger(__name__)

type Widget = dict[str, Any]
type DisplayConfig = dict[str, Any]

_FONTS_DIR = Path(__file__).parent / "fonts" / "Roboto"


def _load_font(
    size: int, medium: bool = False, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Roboto at the given pixel size, falling back to PIL default.

    Args:
        size: Font size in pixels (clamped to a minimum of 1).
        medium: When True, load Roboto Medium (weight 500) instead of
            Roboto Regular (weight 400).
        bold: When True, load Roboto Bold (weight 700). Takes
            precedence over ``medium``.

    Returns:
        A FreeTypeFont loaded from the TTF file, or the PIL built-in
        default font if the TTF is not found.
    """
    return _load_font_cached(max(1, size), medium, bold)


@functools.cache
def _load_font_cached(
    size: int, medium: bool, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font at the given size (unclamped, cached).

    Separated from _load_font so that size=0 and size=1 produce distinct
    cache entries instead of colliding after the clamp.
    """
    if bold:
        filename = "Roboto-Bold.ttf"
    elif medium:
        filename = "Roboto-Medium.ttf"
    else:
        filename = "Roboto-Regular.ttf"
    ttf_path = _FONTS_DIR / filename
    if ttf_path.exists():
        return ImageFont.truetype(str(ttf_path), size)
    return ImageFont.load_default(size)


def color_to_hex(c: int) -> str:
    """Convert a grayscale 0–255 value to an SVG hex color string.

    Args:
        c: Grayscale intensity (0 = black, 255 = white).

    Returns:
        Lowercase six-digit hex string, e.g. ``"#000000"`` for 0,
        ``"#787878"`` for 120, ``"#ffffff"`` for 255.
    """
    c = max(0, min(255, c))
    return f"#{c:02x}{c:02x}{c:02x}"


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
    "washing_machine": (
        "washing-machine",
        "washing-machine-alert",
    ),
    "dishwasher": ("dishwasher", "dishwasher-alert"),
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
        icon_inner: Side length of the icon glyph inside a circle.
        font_letter: Font size for single-letter fallback inside icon
            circles.
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
    icon_inner: int
    font_letter: int
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
    icon_dia = round(row_h * 0.64)
    return WidgetMetrics(
        border=max(2, round(row_h * 0.04)),
        padding=round(row_h * 0.21),
        radius=round(row_h * 0.21),
        icon_dia=icon_dia,
        # Floor division matches the Jinja template formula so that
        # both sides agree when `m_icon_inner` is passed to `card_row`.
        icon_inner=icon_dia * 60 // 100,
        font_letter=icon_dia * 5 // 10,
        font_primary=max(10, round(row_h * 0.32)),
        font_secondary=max(10, round(row_h * 0.25)),
        divider=max(2, round(row_h * 0.07)),
        inner_gap=round(row_h * 0.21),
        left_bar=max(2, round(row_h * 0.07)),
    )


DEFAULT_METRICS: WidgetMetrics = _compute_metrics(DEFAULT_ROW_H)


def _left_bar_width(m: WidgetMetrics, grayscale_levels: int) -> int:
    """Return the rendered width of a left_bar card decoration.

    On 2-level displays (TRMNL) the bar is tripled so the
    dithered dot pattern reads clearly as a solid stripe.

    Args:
        m: Proportional metrics from ``_compute_metrics``.
        grayscale_levels: Quantisation level count from the
            display config.

    Returns:
        Bar width in pixels.
    """
    if grayscale_levels <= 2:
        return max(10, m.left_bar * 3)
    return m.left_bar


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


def _get_today() -> date:
    """Return today's date.

    Thin wrapper around ``date.today()`` so the SVG context builder
    can call this function and tests can patch
    ``custom_components.eink_dashboard.render.date`` to control
    the return value via this scope.

    Returns:
        Today's date as a ``datetime.date`` instance.
    """
    return date.today()


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


def render_dashboard(
    widget_list: list[Widget],
    config: DisplayConfig,
) -> bytes:
    """Render widgets to PNG bytes for e-ink display.

    Rasterises each widget SVG individually at its intrinsic size,
    pastes the results onto a white canvas, then applies rotation
    and e-ink optimisation.  Per-widget rasterisation is ~3x faster
    than composing one large SVG because resvg's cost scales with
    document complexity and pixmap area.

    Args:
        widget_list: Widget configuration dicts.  Each must have a
            ``"type"`` key matching a registered SVG renderer.
        config: Display config with ``width``, ``height``, ``rotation``,
            and entity ``states``.  Defaults to 600×800 if dimensions
            are absent.

    Returns:
        PNG image bytes ready for delivery to the e-ink display.
    """
    config = {"width": 600, "height": 800, **config}
    w = config["width"]
    h = config["height"]

    img = Image.new("L", (w, h), 255)

    for widget in widget_list:
        widget_type = widget.get("type")
        if widget_type is None:
            _LOGGER.warning(
                "render_dashboard: widget has no type: %r",
                widget,
            )
            continue
        if widget_type not in _SVG_RENDERERS:
            _LOGGER.warning(
                "render_dashboard: unknown widget type %r, skipping",
                widget_type,
            )
            continue
        visibility = widget.get("visibility")
        # Both None (absent) and [] (empty) mean "always visible".
        if visibility:
            states = config.get("states", {})
            if not check_conditions(visibility, states):
                _LOGGER.debug(
                    "render_dashboard: visibility conditions not"
                    " met for widget type=%s, skipping",
                    widget_type,
                )
                continue
        wx = widget.get("x", PADDING)
        wy = widget.get("y", 0)
        _LOGGER.debug(
            "render_dashboard: SVG rendering type=%s at (%d,%d)",
            widget_type,
            wx,
            wy,
        )
        svg = render_widget_svg(widget, config)
        png = _svg_to_png(svg)
        wimg = Image.open(io.BytesIO(png)).convert("L")
        img.paste(wimg, (wx, wy))

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

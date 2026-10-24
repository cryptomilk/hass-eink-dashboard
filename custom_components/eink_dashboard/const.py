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

"""Constants, enums, and device presets for the e-ink dashboard."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

type Widget = dict[str, Any]
"""Widget configuration dict passed to context builders."""

type DisplayConfig = dict[str, Any]
"""Display configuration dict with dimensions, states, etc."""


class WebhookTarget(TypedDict):
    """A named webhook that receives the rendered image.

    Stored as a plain dict in the ``webhook_urls`` config entry option.
    """

    name: str
    """Label shown in the options flow when removing the target."""
    url: str
    """Endpoint that receives the PNG via HTTP POST."""


DOMAIN = "eink_dashboard"


class FontFamily(StrEnum):
    """Bundled font families used for dashboard text.

    TRMNL and ROBOTO are selectable in Display settings; the selected
    one is listed first in every SVG ``font-family`` stack, and the
    other stays available as a glyph fallback.  INTER is not
    selectable: it is only used as the TRMNL large-text fallback.
    """

    TRMNL = "TRMNL"
    """Pixel font with 12, 16 and 21 px optical sizes, for
    low-resolution panels."""
    ROBOTO = "Roboto"
    """Outline font with Regular, Medium and Bold weights, for
    high-resolution panels."""
    INTER = "Inter"
    """Outline font with Regular, Medium and Bold weights, used as
    the TRMNL large-text fallback (see ``large_text_fallback()`` in
    ``fonts.py``)."""


DEFAULT_WIDTH = 758
DEFAULT_HEIGHT = 1024
DEFAULT_UPDATE_INTERVAL = 60
DEFAULT_GRAYSCALE_DEPTH = 8
DEFAULT_OPTIMIZE = False
DEFAULT_DISPLAY_LEVELS = 16
DEFAULT_DITHER_ALGORITHM = "floyd_steinberg"
DEFAULT_MEASURED_PALETTE = "auto"
DEFAULT_EXPOSURE = 1.0
DEFAULT_SATURATION = 1.0
DEFAULT_USE_SYSTEM_FONTS = False
# Snap TRMNL text to its pixel grid and disable text anti-aliasing.
DEFAULT_PIXEL_FONTS = True
# Largest TRMNL scale multiple (of its 21 px face) drawn in TRMNL;
# larger text falls back to Inter because scaled-up pixel glyphs look
# blocky.  "auto" derives it from the pixel density, "never" disables
# the fallback, "1"-"4" are fixed multiples.
PIXEL_FONT_LIMIT_AUTO = "auto"
PIXEL_FONT_LIMIT_NEVER = "never"
PIXEL_FONT_LIMIT_OPTIONS = (
    PIXEL_FONT_LIMIT_AUTO,
    "1",
    "2",
    "3",
    "4",
    PIXEL_FONT_LIMIT_NEVER,
)
DEFAULT_PIXEL_FONT_LIMIT = PIXEL_FONT_LIMIT_AUTO
# The automatic limit keeps one font pixel at most 1/62 inch (about
# 0.4 mm) on the panel: 2x on 124 ppi panels, 3x at 212 ppi, 4x at
# 300 ppi.  Displays with an unknown density use the fallback scale.
PIXEL_FONT_PPI_PER_SCALE = 62
DEFAULT_PIXEL_FONT_MAX_SCALE = 2
# Render every non-white text colour (gray labels etc.) as black.
DEFAULT_BLACK_TEXT = False
# Render dividers, separators and left card bars in solid black.
DEFAULT_BLACK_DIVIDERS = False
# Font for high-resolution displays and the renderer's fallback.
DEFAULT_FONT_FAMILY = FontFamily.ROBOTO
# Pixel font for low-resolution displays, where small anti-aliased text
# breaks up into gray fringes.
LOW_RES_FONT_FAMILY = FontFamily.TRMNL
# Custom displays whose shorter side is at most this many pixels default
# to LOW_RES_FONT_FAMILY, matching the 800 x 480 presets.
LOW_RES_MAX_SHORT_SIDE = 480
DEFAULT_ROW_H = 56
# Pixel density the DEFAULT_ROW_H baseline was designed for (Kindle
# Paperwhite 1/2, 6" at 758x1024).  List rows default to the same
# physical height on other devices; see default_list_row_height().
REFERENCE_PPI = 212
# Default stroke width in px of the dividers between list rows.
DEFAULT_DIVIDER_W = 1
# DEFAULT_METRICS = _compute_metrics(DEFAULT_ROW_H) lives in render.py
# rather than here to avoid a circular import (render.py imports const.py).
MAX_WIDGETS = 200

PADDING = 24

COLOR_BLACK = 0
COLOR_WHITE = 255
COLOR_GRAY = 120
COLOR_MEDIUM_GRAY = 150
COLOR_LIGHT_GRAY = 180


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


DEFAULT_CARD_STYLE = "none"

# Scale denominator for weather widget geometry: all _WX_* base
# dimensions are natural values at font_size == FONT_SIZE_WEATHER
# and are multiplied by (font_size / FONT_SIZE_WEATHER) in
# _build_weather_context().  Other per-widget font-size constants
# were removed in Step 1.7 because their widgets now derive sizes
# from _compute_metrics(); this one remains because the weather
# widget's scale-factor system depends on it as a ratio reference.
FONT_SIZE_WEATHER = 32

DEFAULT_WEATHER_MODE = "full"


@dataclass(frozen=True)
class DevicePreset:
    """Static display properties for a known e-ink device model."""

    label: str
    width: int
    height: int
    display_levels: int
    optimize: bool
    manufacturer: str
    native_landscape: bool = False
    integration_dithers: bool = False
    dither_algorithm: str = DEFAULT_DITHER_ALGORITHM
    color_scheme: str | None = None
    """Color palette for color e-ink displays (e.g. ``"bwgbry"`` for
    Spectra 6-color).  ``None`` means grayscale.  String values match
    keys in ``optimize._COLOR_SCHEMES``."""
    measured_palette: str = DEFAULT_MEASURED_PALETTE
    """Measured palette key for photographically calibrated dithering.
    ``"auto"`` means use the idealized ``ColorScheme`` derived from
    ``color_scheme`` or ``display_levels``.  Non-auto values match
    keys in ``optimize._MEASURED_PALETTES``."""
    ppi: int | None = None
    """Physical pixel density in pixels per inch, derived from the
    panel diagonal.  Scales the default list row height so rows have
    the same physical size on every device.  ``None`` when the panel
    size is unknown; the default then stays at ``DEFAULT_ROW_H``."""
    font_family: FontFamily = DEFAULT_FONT_FAMILY
    """Default font family for this device.  Low-resolution panels use
    the TRMNL pixel font; the others use Roboto.  Users can override it
    in Display settings."""


DEVICE_PRESETS: dict[str, DevicePreset] = {
    "kindle_4": DevicePreset(
        "Kindle 4/5",
        600,
        800,
        16,
        True,
        "Amazon",
        ppi=167,
    ),
    "kindle_pw": DevicePreset(
        "Kindle Paperwhite 1/2/3",
        758,
        1024,
        16,
        True,
        "Amazon",
        ppi=212,
    ),
    "kindle_pw4": DevicePreset(
        "Kindle Paperwhite 4",
        1072,
        1448,
        16,
        True,
        "Amazon",
        ppi=300,
    ),
    "kindle_oasis": DevicePreset(
        "Kindle Oasis 2/3",
        1264,
        1680,
        16,
        True,
        "Amazon",
        ppi=300,
    ),
    "trmnl_og": DevicePreset(
        "TRMNL OG",
        800,
        480,
        2,
        True,
        "TRMNL",
        native_landscape=True,
        ppi=124,
        font_family=LOW_RES_FONT_FAMILY,
    ),
    "trmnl_x": DevicePreset(
        "TRMNL X",
        1872,
        1404,
        16,
        True,
        "TRMNL",
        native_landscape=True,
        ppi=227,
    ),
    "trmnl_rgb": DevicePreset(
        "TRMNL RGB",
        2560,
        1440,
        2,
        True,
        "TRMNL",
        native_landscape=True,
    ),
    "reterminal_e1001": DevicePreset(
        "reTerminal E1001",
        800,
        480,
        4,
        False,
        "Seeed",
        native_landscape=True,
        integration_dithers=True,
        ppi=124,
        font_family=LOW_RES_FONT_FAMILY,
    ),
    "reterminal_e1002": DevicePreset(
        "reTerminal E1002",
        800,
        480,
        256,
        False,
        "Seeed",
        native_landscape=True,
        integration_dithers=True,
        color_scheme="bwgbry",
        ppi=128,
        font_family=LOW_RES_FONT_FAMILY,
    ),
    "reterminal_e1003": DevicePreset(
        "reTerminal E1003",
        1872,
        1404,
        16,
        False,
        "Seeed",
        native_landscape=True,
        integration_dithers=True,
        ppi=227,
    ),
    "custom": DevicePreset(
        "Custom",
        758,
        1024,
        16,
        False,
        "",
    ),
}


def resolve_device_preset(options: Mapping[str, Any]) -> DevicePreset:
    """Return the device preset selected by ``device_model``.

    A missing or unrecognised ``device_model`` resolves to the
    ``"custom"`` preset, never ``None``, so callers never need a
    separate fallback branch.

    Args:
        options: Config entry options with an optional
            ``device_model`` key.

    Returns:
        The matching ``DevicePreset``, or the ``"custom"`` preset.
    """
    model = options.get("device_model", "custom")
    return DEVICE_PRESETS.get(model, DEVICE_PRESETS["custom"])


def default_font_family(options: Mapping[str, Any]) -> FontFamily:
    """Return the default font family for a display.

    Device presets carry their own default.  Custom displays (and
    entries without a device model) use the TRMNL pixel font when the
    shorter side of the canvas is at most ``LOW_RES_MAX_SHORT_SIDE``
    pixels, and Roboto otherwise.

    Args:
        options: Config entry options with ``device_model``, ``width``
            and ``height``.

    Returns:
        The ``FontFamily`` to render with.
    """
    model = options.get("device_model", "custom")
    if model != "custom" and model in DEVICE_PRESETS:
        return resolve_device_preset(options).font_family
    width = options.get("width", DEFAULT_WIDTH)
    height = options.get("height", DEFAULT_HEIGHT)
    if min(width, height) <= LOW_RES_MAX_SHORT_SIDE:
        return LOW_RES_FONT_FAMILY
    return DEFAULT_FONT_FAMILY


def resolve_font_family(options: Mapping[str, Any]) -> FontFamily:
    """Return the font family selected for a display.

    Uses the ``font_family`` option when it is set to a known family,
    otherwise the display's default from ``default_font_family()``.

    Args:
        options: Config entry options.

    Returns:
        The ``FontFamily`` to render with.
    """
    family = options.get("font_family")
    if family in FontFamily:
        return FontFamily(family)
    return default_font_family(options)


def resolve_display(
    preset_key: str,
    orientation: str,
) -> tuple[int, int, int, DevicePreset]:
    """Return (canvas_width, canvas_height, rotation, preset)."""
    if preset_key == "custom":
        raise ValueError(
            "resolve_display does not support the 'custom' preset"
        )
    p = DEVICE_PRESETS[preset_key]
    native_portrait = not p.native_landscape
    want_portrait = orientation == "portrait"
    if native_portrait == want_portrait:
        return p.width, p.height, 0, p
    return p.height, p.width, 90, p


def display_ppi(options: Mapping[str, Any]) -> int | None:
    """Return the pixel density of a display, if known.

    Args:
        options: Config entry options; ``device_model`` selects the
            preset, ``ppi`` is the custom display's density.

    Returns:
        Density in pixels per inch, or ``None`` when unknown.
    """
    model = options.get("device_model", "custom")
    if model == "custom":
        return options.get("ppi") or None
    preset = DEVICE_PRESETS.get(model)
    return preset.ppi if preset else None


def resolve_pixel_font_max_scale(options: Mapping[str, Any]) -> int | None:
    """Return the largest scale multiple drawn in the TRMNL font.

    TRMNL text larger than this multiple of its 21 px face renders in
    Inter.  The ``pixel_font_limit`` option selects a fixed multiple,
    ``"never"`` for no limit, or ``"auto"`` (the default) to derive it
    from the display's pixel density so one font pixel stays at most
    ``1 / PIXEL_FONT_PPI_PER_SCALE`` inch on the panel.

    Args:
        options: Config entry options.

    Returns:
        The scale multiple (at least 1), or ``None`` for no limit.
    """
    limit = options.get("pixel_font_limit", DEFAULT_PIXEL_FONT_LIMIT)
    if limit == PIXEL_FONT_LIMIT_NEVER:
        return None
    if limit in PIXEL_FONT_LIMIT_OPTIONS and limit != PIXEL_FONT_LIMIT_AUTO:
        return int(limit)
    ppi = display_ppi(options)
    if not ppi:
        return DEFAULT_PIXEL_FONT_MAX_SCALE
    return max(1, ppi // PIXEL_FONT_PPI_PER_SCALE)


def default_list_row_height(options: Mapping[str, Any]) -> int:
    """Return the default maximum list row height for a display.

    Scales ``DEFAULT_ROW_H`` by the display's pixel density relative
    to ``REFERENCE_PPI`` so list rows keep the same physical height:
    about 33 px on a 7.5" 800x480 panel, 79 px on a 300 ppi Kindle.
    Custom displays use the user-entered ``ppi`` option.  Displays
    with an unknown density keep ``DEFAULT_ROW_H``.

    Args:
        options: Config entry options; ``device_model`` selects the
            preset, ``ppi`` is the custom display's density.

    Returns:
        Row height in pixels.
    """
    model = options.get("device_model", "custom")
    if model == "custom":
        ppi = options.get("ppi")
    else:
        ppi = resolve_device_preset(options).ppi
    if not ppi:
        return DEFAULT_ROW_H
    return max(1, round(DEFAULT_ROW_H * ppi / REFERENCE_PPI))


def apply_screen_portion(
    width: int,
    height: int,
    portion: str,
) -> tuple[int, int]:
    """Return (width, height) adjusted for the requested screen portion."""
    if portion == "half":
        return width // 2, height
    if portion == "quarter":
        return width // 2, height // 2
    if portion == "full":
        return width, height
    raise ValueError(f"Unknown screen portion: {portion!r}")


class NumberFormat(StrEnum):
    """Number formatting styles, mirroring HA's frontend NumberFormat enum.

    Used to control how numeric entity state values are formatted in
    widget renderers.  ``LANGUAGE`` (the default) derives the format
    from the system or owner language setting.
    """

    LANGUAGE = "language"
    """Derive format from the language setting (default)."""
    SYSTEM = "system"
    """System locale (no browser on the server; treated as comma_decimal)."""
    COMMA_DECIMAL = "comma_decimal"
    """1,234.56 — US/UK style."""
    DECIMAL_COMMA = "decimal_comma"
    """1.234,56 — German/Spanish/Italian style."""
    SPACE_COMMA = "space_comma"
    """1 234,56 — French/Swedish/Czech style."""
    QUOTE_DECIMAL = "quote_decimal"
    """1'234.56 — Swiss German style."""
    NONE = "none"
    """No grouping, dot decimal: 1234.56."""


class DateFormat(StrEnum):
    """Date formatting styles, mirroring HA's frontend DateFormat enum.

    Used to control how date values are formatted in widget renderers.
    ``LANGUAGE`` (the default) derives the format from the language
    setting.
    """

    LANGUAGE = "language"
    """Derive format from the language setting (default)."""
    SYSTEM = "system"
    """System locale."""
    DMY = "dmy"
    """Day-Month-Year (31/12/2026) — European style."""
    MDY = "mdy"
    """Month-Day-Year (12/31/2026) — US style."""
    YMD = "ymd"
    """Year-Month-Day (2026-12-31) — ISO/Asian style."""


class TimeFormat(StrEnum):
    """Time formatting styles, mirroring HA's frontend TimeFormat enum.

    Used to control how time values are formatted in widget renderers.
    ``LANGUAGE`` (the default) derives the format from the language
    setting.
    """

    LANGUAGE = "language"
    """Derive format from the language setting (default)."""
    SYSTEM = "system"
    """System locale."""
    AM_PM = "12"
    """12-hour clock with AM/PM (1:30 PM)."""
    TWENTY_FOUR = "24"
    """24-hour clock (13:30)."""


class FontWeight(StrEnum):
    """Font weight for widget text roles.

    Maps a role's weight to both the Roboto face used for text
    measurement and rasterisation and the SVG ``font-weight`` value.
    Widgets expose per-role weight overrides through the ``fonts``
    widget key (see ``render.resolve_font``); this enum is the
    resolved value those overrides produce.
    """

    REGULAR = "regular"
    """Roboto Regular — SVG ``font-weight="400"``."""
    MEDIUM = "medium"
    """Roboto Medium — SVG ``font-weight="500"``."""
    BOLD = "bold"
    """Roboto Bold — SVG ``font-weight="bold"``."""


class DayLabelFormat(StrEnum):
    """Format of the meteogram's day-boundary labels.

    Selects which parts of a date the meteogram's day labels show.
    Weekday and month names resolve through the CLDR data, so a
    German display reads ``"Samstag"`` or ``"Mai 2"``.
    """

    WEEKDAY_MONTH_DAY = "weekday_month_day"
    """Abbreviated weekday, month and day -- e.g. ``"Sun Oct 18"``."""
    WEEKDAY_ABBREV = "weekday_abbrev"
    """Abbreviated weekday only -- e.g. ``"Sun"``."""
    WEEKDAY_WIDE = "weekday_wide"
    """Full weekday name only -- e.g. ``"Sunday"``."""
    MONTH_DAY = "month_day"
    """Month and day without the weekday -- e.g. ``"Oct 18"``."""


class WidgetType(StrEnum):
    """Supported widget type identifiers."""

    SEPARATOR = "separator"
    ENTITIES = "entities"
    ENTITY = "entity"
    FRAME = "frame"
    GAUGE = "gauge"
    GRAPH = "graph"
    HEADING = "heading"
    SENSOR = "sensor"
    TILE = "tile"
    WEATHER = "weather"
    DEVICE_BATTERY = "device_battery"
    WASTE_SCHEDULE = "waste_schedule"
    CALENDAR = "calendar"
    METEOGRAM = "meteogram"
    WEEK_CALENDAR = "week_calendar"

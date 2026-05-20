"""Constants, enums, and device presets for the e-ink dashboard."""

from dataclasses import dataclass
from enum import StrEnum

DOMAIN = "eink_dashboard"

DEFAULT_WIDTH = 758
DEFAULT_HEIGHT = 1024
DEFAULT_UPDATE_INTERVAL = 60
DEFAULT_GRAYSCALE_DEPTH = 8
DEFAULT_OPTIMIZE = False
DEFAULT_GRAYSCALE_LEVELS = 16
DEFAULT_SHARPNESS = 1.0
DEFAULT_CONTRAST = 1.0
DEFAULT_ROW_H = 56
# DEFAULT_METRICS = _compute_metrics(DEFAULT_ROW_H) lives in render.py
# rather than here to avoid a circular import (render.py imports const.py).
MAX_WIDGETS = 200

PADDING = 24

COLOR_BLACK = 0
COLOR_WHITE = 255
COLOR_GRAY = 120
COLOR_LIGHT_GRAY = 180

DEFAULT_CARD_STYLE = "none"

# Scale denominator for weather widget geometry: all _WX_* base
# dimensions are natural values at font_size == FONT_SIZE_WEATHER
# and are multiplied by (font_size / FONT_SIZE_WEATHER) in
# _build_weather_context().  Other per-widget font-size constants
# were removed in Step 1.7 because their widgets now derive sizes
# from _compute_metrics(); this one remains because the weather
# widget's scale-factor system depends on it as a ratio reference.
FONT_SIZE_WEATHER = 32


@dataclass(frozen=True)
class DevicePreset:
    """Static display properties for a known e-ink device model."""

    label: str
    width: int
    height: int
    grayscale_levels: int
    optimize: bool
    manufacturer: str
    native_landscape: bool = False


DEVICE_PRESETS: dict[str, DevicePreset] = {
    "kindle_4": DevicePreset(
        "Kindle 4/5",
        600,
        800,
        16,
        True,
        "Amazon",
    ),
    "kindle_pw": DevicePreset(
        "Kindle Paperwhite 1/2/3",
        758,
        1024,
        16,
        True,
        "Amazon",
    ),
    "kindle_pw4": DevicePreset(
        "Kindle Paperwhite 4",
        1072,
        1448,
        16,
        True,
        "Amazon",
    ),
    "kindle_oasis": DevicePreset(
        "Kindle Oasis 2/3",
        1264,
        1680,
        16,
        True,
        "Amazon",
    ),
    "trmnl_og": DevicePreset(
        "TRMNL OG",
        800,
        480,
        2,
        True,
        "TRMNL",
        native_landscape=True,
    ),
    "trmnl_x": DevicePreset(
        "TRMNL X",
        1872,
        1404,
        16,
        True,
        "TRMNL",
        native_landscape=True,
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
    "custom": DevicePreset(
        "Custom",
        758,
        1024,
        16,
        False,
        "",
    ),
}


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


class Align(StrEnum):
    """Horizontal text alignment options for widget rendering."""

    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


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
    DMY = "DMY"
    """Day-Month-Year (31/12/2026) — European style."""
    MDY = "MDY"
    """Month-Day-Year (12/31/2026) — US style."""
    YMD = "YMD"
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


class WidgetType(StrEnum):
    """Supported widget type identifiers."""

    TEXT = "text"
    SEPARATOR = "separator"
    ENTITY = "entity"
    HEADING = "heading"
    TILE = "tile"
    WEATHER = "weather"
    SENSOR_ROWS = "sensor_rows"
    DEVICE_BATTERY = "device_battery"
    STATUS_ICONS = "status_icons"
    WASTE_SCHEDULE = "waste_schedule"

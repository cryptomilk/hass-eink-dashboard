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
MAX_WIDGETS = 200

PADDING = 24

COLOR_BLACK = 0
COLOR_WHITE = 255
COLOR_GRAY = 120
COLOR_LIGHT_GRAY = 180

FONT_SIZE_TEXT = 32
FONT_SIZE_WEATHER = 32
FONT_SIZE_SENSOR_ROWS = 32
FONT_SIZE_DEVICE_BATTERY = 24
FONT_SIZE_STATUS_ICONS = 28
FONT_SIZE_WASTE_SCHEDULE = 28


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


class Align(StrEnum):
    """Horizontal text alignment options for widget rendering."""

    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


class WidgetType(StrEnum):
    """Supported widget type identifiers."""

    TEXT = "text"
    LINE = "line"
    SEPARATOR = "separator"
    WEATHER = "weather"
    SENSOR_ROWS = "sensor_rows"
    DEVICE_BATTERY = "device_battery"
    STATUS_ICONS = "status_icons"
    WASTE_SCHEDULE = "waste_schedule"

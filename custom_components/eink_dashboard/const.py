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
FONT_SIZE_BATTERY_BAR = 24
FONT_SIZE_STATUS_ICONS = 28
FONT_SIZE_WASTE_SCHEDULE = 28


@dataclass(frozen=True)
class DevicePreset:
    width: int
    height: int
    grayscale_levels: int
    optimize: bool
    manufacturer: str
    native_landscape: bool = False


DEVICE_PRESETS: dict[str, DevicePreset] = {
    "kindle_4": DevicePreset(
        600,
        800,
        16,
        True,
        "Amazon",
    ),
    "kindle_pw": DevicePreset(
        758,
        1024,
        16,
        True,
        "Amazon",
    ),
    "kindle_pw4": DevicePreset(
        1072,
        1448,
        16,
        True,
        "Amazon",
    ),
    "kindle_oasis": DevicePreset(
        1264,
        1680,
        16,
        True,
        "Amazon",
    ),
    "trmnl_og": DevicePreset(
        800,
        480,
        2,
        True,
        "TRMNL",
        native_landscape=True,
    ),
    "trmnl_x": DevicePreset(
        1872,
        1404,
        16,
        True,
        "TRMNL",
        native_landscape=True,
    ),
    "trmnl_rgb": DevicePreset(
        2560,
        1440,
        2,
        True,
        "TRMNL",
        native_landscape=True,
    ),
    "custom": DevicePreset(
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
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


class WidgetType(StrEnum):
    TEXT = "text"
    LINE = "line"
    SEPARATOR = "separator"
    WEATHER = "weather"
    SENSOR_ROWS = "sensor_rows"
    BATTERY_BAR = "battery_bar"
    STATUS_ICONS = "status_icons"
    WASTE_SCHEDULE = "waste_schedule"

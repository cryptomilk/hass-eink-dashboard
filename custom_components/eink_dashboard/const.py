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
COLOR_GRAY = 160
COLOR_LIGHT_GRAY = 210


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

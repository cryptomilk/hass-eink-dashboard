"""Per-widget SVG context builders.

Each submodule exports a single ``_build_<type>_context()`` function
that converts a widget config dict and a display config into a Jinja2
template context dict.  This package re-exports all builders so
``svg_render.py`` can populate ``_SVG_RENDERERS`` with a single
import.
"""

from .calendar import _build_calendar_context
from .device_battery import (
    _build_device_battery_context,
)
from .entities import (
    _build_entities_context,
)
from .entity import _build_entity_context
from .gauge import _build_gauge_context
from .graph import _build_graph_context
from .heading import _build_heading_context
from .sensor import _build_sensor_context
from .separator import _build_separator_context
from .tile import _build_tile_context
from .waste_schedule import (
    _build_waste_schedule_context,
)
from .weather import _build_weather_context

__all__ = [
    "_build_calendar_context",
    "_build_device_battery_context",
    "_build_entities_context",
    "_build_entity_context",
    "_build_gauge_context",
    "_build_graph_context",
    "_build_heading_context",
    "_build_sensor_context",
    "_build_separator_context",
    "_build_tile_context",
    "_build_waste_schedule_context",
    "_build_weather_context",
]

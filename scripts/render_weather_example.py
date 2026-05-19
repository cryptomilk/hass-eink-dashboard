#!/usr/bin/env python3
"""Render example widget images without a Home Assistant installation.

Imports render.py and const.py directly, bypassing the HA-dependent
package __init__.py so no stubs or aiohttp are required.

Usage:
    python3 scripts/render_example.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: make `custom_components.eink_dashboard.{render,const}` importable
# directly without going through the package __init__.py (which pulls in HA).
# ---------------------------------------------------------------------------
from _bootstrap import PKG, import_module

# Register in dependency order so relative imports in each module resolve
# against already-loaded siblings rather than falling back to __init__.py.
import_module(f"{PKG}.const")
import_module(f"{PKG}.optimize")
import_module(f"{PKG}.conditions")
import_module(f"{PKG}.svg_render")
render_mod = import_module(f"{PKG}.render")
render_dashboard = render_mod.render_dashboard  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
WEATHER_STATE = {
    "weather.home": {
        "state": "partlycloudy",
        "attributes": {
            "temperature": 18,
            "humidity": 62,
            "wind_speed": 15,
            "temperature_unit": "°C",
            "wind_speed_unit": "km/h",
            "pressure": 1008,
            "pressure_unit": "hPa",
            "cloud_coverage": 60,
            "precipitation_unit": "mm",
            "forecast": [
                {
                    "datetime": "2026-05-11T12:00:00",
                    "temperature": 19,
                    "templow": 12,
                    "condition": "sunny",
                    "precipitation": 0,
                },
                {
                    "datetime": "2026-05-12T12:00:00",
                    "temperature": 16,
                    "templow": 10,
                    "condition": "rainy",
                    "precipitation": 8,
                },
                {
                    "datetime": "2026-05-13T12:00:00",
                    "temperature": 17,
                    "templow": 11,
                    "condition": "cloudy",
                    "precipitation": 2,
                },
            ],
        },
    },
}

WIDGET = {
    "type": "weather",
    "entity": "weather.home",
    "x": 0,
    "y": 0,
    "width": 1,
    "height": 1,
    "forecast_days": 3,
}

RENDERS = [
    # (filename, config)
    (
        "weather_trmnl.png",
        {
            "width": 800,
            "height": 480,
            "grayscale_levels": 2,
            "states": WEATHER_STATE,
        },
    ),
    (
        "weather_kindle.png",
        {
            "width": 758,
            "height": 1024,
            "grayscale_levels": 16,
            "states": WEATHER_STATE,
        },
    ),
]

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp")

for filename, config in RENDERS:
    png = render_dashboard([WIDGET], config)
    out = output_dir / filename
    out.write_bytes(png)
    w, h = config["width"], config["height"]
    lvls = config["grayscale_levels"]
    print(f"{out}  ({w}x{h}, {lvls}-level, {len(png)} bytes)")

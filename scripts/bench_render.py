#!/usr/bin/env python3
"""Benchmark the e-ink dashboard SVG rendering pipeline.

Measures per-stage timings for the SVG pipeline.
Runs without a Home Assistant installation.

Stages measured:
  svg_render    -- per-widget Jinja2 context build + template render
  svg_rasterise -- per-widget resvg rasterisation + PIL paste
  eink_optimize -- optimize_for_eink() dithering / quantisation
  end_to_end    -- full wall-clock time including PNG encode

Usage:
    python3 scripts/bench_render.py
    python3 scripts/bench_render.py --device trmnl_og --iterations 50
    python3 scripts/bench_render.py --widget weather --iterations 20

# ---------------------------------------------------------------------------
# PIL baseline (kindle_pw, 758x1024, 16-level, optimize=True)
# Recorded before the SVG migration.  All 7 widgets, 50 iterations.
#
# Stage              min    median     p95     max  (ms)
# canvas_setup      0.01      0.04    0.06    0.07
# widget_render     2.87      2.93    3.12    3.33
# eink_optimize    19.07     19.76   20.20   20.99
# png_encode         (included in end_to_end)
# end_to_end       24.42     25.09   25.63   26.33
#
# Peak RSS: 36.3 MB
# ---------------------------------------------------------------------------
#
# SVG composed baseline (kindle_pw, 758x1024, 16-level, optimize=True)
# Recorded after SVG migration (step 2.1).  All 7 widgets, 20 iterations.
# Used _compose_svg() + single resvg call for the full dashboard.
#
# Stage              min    median     p95     max  (ms)
# svg_render        1.11      1.22    1.36    1.38
# svg_compose       0.01      0.01    0.01    0.02
# svg_rasterise   117.43    118.20  120.27  121.42
# eink_optimize    14.46     14.77   15.06   15.34
# end_to_end      143.14    144.40  146.98  148.16
#
# Peak RSS: 48.6 MB
# ---------------------------------------------------------------------------
#
# SVG per-widget (kindle_pw, 758x1024, 16-level, optimize=True)
# Per-widget resvg rasterisation + PIL paste.  All 7 widgets, 30
# iterations.  ~3.4x faster end-to-end vs composed baseline.
#
# Stage              min    median     p95     max  (ms)
# svg_render        1.28      1.36    1.47    1.47
# svg_rasterise    19.21     19.54   20.13   20.79
# eink_optimize    14.79     15.18   15.96   17.22
# end_to_end       37.81     38.55   40.48   42.26
#
# Peak RSS: 45.6 MB
# ---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import io
import math
import resource
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from _bootstrap import PKG, import_module
from PIL import Image

# ---------------------------------------------------------------------------
# Bootstrap: import const, optimize, render without HA
# ---------------------------------------------------------------------------
import_module(f"{PKG}.const")
import_module(f"{PKG}.optimize")
import_module(f"{PKG}.conditions")
import_module(f"{PKG}.svg_render")
import_module(f"{PKG}.render")

from custom_components.eink_dashboard.const import (
    DEVICE_PRESETS,
    PADDING,
    DevicePreset,
    WidgetType,
)
from custom_components.eink_dashboard.optimize import (
    optimize_for_eink,
)
from custom_components.eink_dashboard.svg_render import (
    _SVG_RENDERERS,
    _svg_to_png,
    render_widget_svg,
)

# ---------------------------------------------------------------------------
# Mock data for all 7 widget types
# ---------------------------------------------------------------------------

_WEATHER_STATES = {
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

_SENSOR_STATES = {
    "sensor.living_room_temperature": {
        "state": "22.1",
        "attributes": {
            "unit_of_measurement": "°C",
            "friendly_name": "Living Room",
            "device_class": "temperature",
        },
    },
    "sensor.bedroom_temperature": {
        "state": "19.8",
        "attributes": {
            "unit_of_measurement": "°C",
            "friendly_name": "Bedroom",
            "device_class": "temperature",
        },
    },
    "sensor.humidity": {
        "state": "45",
        "attributes": {
            "unit_of_measurement": "%",
            "friendly_name": "Humidity",
            "device_class": "humidity",
        },
    },
    "binary_sensor.front_door": {
        "state": "off",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
}

_STATUS_ICON_STATES = {
    "binary_sensor.front_door": {
        "state": "on",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "binary_sensor.kitchen_window": {
        "state": "off",
        "attributes": {
            "friendly_name": "Kitchen Window",
            "device_class": "window",
        },
    },
    "binary_sensor.water_alarm": {
        "state": "on",
        "attributes": {
            "friendly_name": "Water Alarm",
            "device_class": "moisture",
        },
    },
    "binary_sensor.motion": {
        "state": "off",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
}

# Waste dates are relative to today so entries always fall within the
# 0-3 day visibility window checked by _parse_days_until() in render.py.
_today = date.today()
_WASTE_STATES = {
    "sensor.waste_collection": {
        "state": "Restmuell tomorrow",
        "attributes": {
            "friendly_name": "Waste Collection",
            "Restmuell": str(_today + timedelta(days=1)),
            "Biotonne": str(_today + timedelta(days=2)),
            "Papier": str(_today + timedelta(days=3)),
        },
    },
}

# _MOCK_DATA maps WidgetType string -> (widget_dict, states_dict).
# For device_battery the states dict is empty; the level is injected
# as config["device_battery_level"] by _build_config().
_MOCK_DATA: dict[str, tuple[dict, dict]] = {
    WidgetType.TEXT: (
        {
            "type": "text",
            "x": 24,
            "y": 10,
            "text": "Dashboard",
            "font_size": 32,
        },
        {},
    ),
    WidgetType.SEPARATOR: (
        {
            "type": "separator",
            "x": 24,
            "y": 50,
            "style": "bar",
        },
        {},
    ),
    WidgetType.WEATHER: (
        {
            "type": "weather",
            "entity": "weather.home",
            "x": 24,
            "y": 10,
            "forecast_days": 3,
        },
        _WEATHER_STATES,
    ),
    WidgetType.SENSOR_ROWS: (
        {
            "type": "sensor_rows",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 168,
            "card_style": "border",
            "entities": [
                "sensor.living_room_temperature",
                "sensor.bedroom_temperature",
                "sensor.humidity",
                "binary_sensor.front_door",
            ],
        },
        _SENSOR_STATES,
    ),
    WidgetType.DEVICE_BATTERY: (
        {
            "type": "device_battery",
            "x": 24,
            "y": 20,
        },
        {},
    ),
    WidgetType.STATUS_ICONS: (
        {
            "type": "status_icons",
            "x": 0,
            "y": 0,
            "w": 500,
            "h": 40,
            "entities": [
                "binary_sensor.front_door",
                "binary_sensor.kitchen_window",
                "binary_sensor.water_alarm",
                "binary_sensor.motion",
            ],
        },
        _STATUS_ICON_STATES,
    ),
    WidgetType.WASTE_SCHEDULE: (
        {
            "type": "waste_schedule",
            "entity": "sensor.waste_collection",
            "entries": [
                {"attribute": "Restmuell", "label": "Restmuell"},
                {"attribute": "Biotonne", "label": "Bio"},
                {"attribute": "Papier", "label": "Papier"},
            ],
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 168,
            "card_style": "border",
        },
        _WASTE_STATES,
    ),
}

# ---------------------------------------------------------------------------
# Timing data structures
# ---------------------------------------------------------------------------


@dataclass
class _BenchResult:
    """Timing samples for one pipeline stage.

    Attributes:
        name: Stage name displayed in the report table.
        times_ns: Raw nanosecond timings, one per iteration.
    """

    name: str
    times_ns: list[int] = field(default_factory=list)

    def stats(self) -> dict[str, float]:
        """Compute summary statistics in milliseconds.

        Returns:
            Dict with keys ``min``, ``median``, ``p95``, and ``max``,
            all in milliseconds.
        """
        ms = sorted(t / 1_000_000 for t in self.times_ns)
        n = len(ms)
        # Nearest-rank method: ceil(0.95 * n) gives the rank (1-based),
        # subtract 1 for 0-based index.  For n<20 p95 collapses to max.
        p95_idx = min(math.ceil(n * 0.95) - 1, n - 1)
        return {
            "min": ms[0],
            "median": statistics.median(ms),
            "p95": ms[p95_idx],
            "max": ms[-1],
        }


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------


def _build_config(
    preset: DevicePreset,
    states: dict,
    **extra: object,
) -> dict:
    """Build a DisplayConfig dict from a device preset.

    Args:
        preset: Device preset providing width, height, grayscale
            levels, and optimize flag.
        states: Entity state dict (may be empty).
        **extra: Additional config keys, e.g.
            ``device_battery_level=72``.

    Returns:
        DisplayConfig dict ready to pass to ``render_dashboard()``
        or the decomposed ``_bench()`` function.
    """
    return {
        "width": preset.width,
        "height": preset.height,
        "grayscale_levels": preset.grayscale_levels,
        "optimize": preset.optimize,
        "states": states,
        **extra,
    }


# ---------------------------------------------------------------------------
# Benchmark core
# ---------------------------------------------------------------------------


def _bench(
    widgets: list[dict],
    config: dict,
    n: int,
) -> list[_BenchResult]:
    """Benchmark the SVG rendering pipeline with per-stage timing.

    Decomposes the SVG pipeline into four timed stages: per-widget
    Jinja2 rendering, per-widget resvg rasterisation + PIL paste,
    e-ink optimisation, and PNG encoding.  Runs ``n`` timed
    iterations; call once before this function for a warmup to
    populate font/icon LRU caches.

    Args:
        widgets: Widget config dicts to render.
        config: DisplayConfig dict.
        n: Number of measured iterations.

    Returns:
        List of four ``_BenchResult`` objects for stages
        ``svg_render``, ``svg_rasterise``, ``eink_optimize``,
        and ``end_to_end``.
    """
    config = {"width": 600, "height": 800, **config}
    w = config["width"]
    h = config["height"]

    stage_svgrender = _BenchResult("svg_render")
    stage_rasterise = _BenchResult("svg_rasterise")
    stage_opt = _BenchResult("eink_optimize")
    stage_e2e = _BenchResult("end_to_end")

    for _ in range(n):
        t_all = time.perf_counter_ns()

        # Stage 1: per-widget context build + Jinja2 template render.
        t0 = time.perf_counter_ns()
        svg_parts: list[str] = []
        positions: list[tuple[int, int]] = []
        for widget in widgets:
            wtype = widget.get("type")
            if wtype not in _SVG_RENDERERS:
                continue
            wx = widget.get("x", PADDING)
            svg_parts.append(render_widget_svg(widget, config))
            positions.append((wx, widget.get("y", 0)))
        stage_svgrender.times_ns.append(time.perf_counter_ns() - t0)

        # Stage 2: per-widget resvg rasterisation + PIL paste.
        t0 = time.perf_counter_ns()
        img = Image.new("L", (w, h), 255)
        for svg, (wx, wy) in zip(svg_parts, positions, strict=True):
            png = _svg_to_png(svg)
            wimg = Image.open(io.BytesIO(png)).convert("L")
            img.paste(wimg, (wx, wy))
        stage_rasterise.times_ns.append(time.perf_counter_ns() - t0)

        # Rotation (default presets have rotation=0, so no-op).
        rotation = config.get("rotation", 0)
        if rotation:
            img = img.rotate(rotation, expand=True)

        # Stage 3: e-ink optimisation (dithering / quantisation).
        t0 = time.perf_counter_ns()
        img = optimize_for_eink(img, config)
        stage_opt.times_ns.append(time.perf_counter_ns() - t0)

        # PNG encoding: cost captured by end_to_end, not separately.
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.getvalue()

        stage_e2e.times_ns.append(time.perf_counter_ns() - t_all)

    return [
        stage_svgrender,
        stage_rasterise,
        stage_opt,
        stage_e2e,
    ]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _report(
    label: str,
    results: list[_BenchResult],
    peak_rss_kb: int,
) -> None:
    """Print a formatted timing table to stdout.

    Args:
        label: Header line describing the benchmark run.
        results: List of stage results from ``_bench()``.
        peak_rss_kb: Peak RSS from ``resource.getrusage``, in KB
            (Linux semantics).
    """
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  {label}")
    print(sep)
    hdr = f"\n{'Stage':<18}{'min':>8}{'median':>8}{'p95':>8}{'max':>8}  (ms)"
    print(hdr)
    print("-" * 52)
    for r in results:
        s = r.stats()
        print(
            f"{r.name:<18}"
            f"{s['min']:>8.2f}"
            f"{s['median']:>8.2f}"
            f"{s['p95']:>8.2f}"
            f"{s['max']:>8.2f}"
        )
    print()
    rss_mb = peak_rss_kb / 1024
    print(f"Peak RSS: {rss_mb:.1f} MB")


# ---------------------------------------------------------------------------
# Full-dashboard widget assembly
# ---------------------------------------------------------------------------


def _all_widgets() -> tuple[list[dict], dict, dict]:
    """Assemble all widget types for a full-dashboard benchmark.

    Lays out all seven widget types vertically so every renderer is
    exercised.  The layout does not need to fit any specific device
    since the renderers clip to their configured x/y/w/h.

    Returns:
        Tuple of ``(widget_list, merged_states, extra_config)``.
        ``extra_config`` contains ``device_battery_level`` for the
        device_battery widget.
    """
    # Vertical layout: 10px gap between widgets
    layout: list[tuple[str, int]] = [
        (WidgetType.TEXT, 40),
        (WidgetType.SEPARATOR, 20),
        (WidgetType.WEATHER, 300),
        (WidgetType.SENSOR_ROWS, 168),
        (WidgetType.DEVICE_BATTERY, 60),
        (WidgetType.STATUS_ICONS, 40),
        (WidgetType.WASTE_SCHEDULE, 168),
    ]

    widget_list: list[dict] = []
    merged: dict = {}
    y = 0
    for wtype, h in layout:
        base, states = _MOCK_DATA[wtype]
        # Shallow copy: nested data (e.g. "entries") is not mutated.
        w = dict(base)
        w["y"] = y
        widget_list.append(w)
        merged.update(states)
        y += h + 10

    return widget_list, merged, {"device_battery_level": 72}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed namespace with ``device``, ``iterations``, and
        ``widget`` attributes.
    """
    parser = argparse.ArgumentParser(
        description=("Benchmark the e-ink dashboard SVG rendering pipeline.")
    )
    parser.add_argument(
        "--device",
        choices=sorted(k for k in DEVICE_PRESETS if k != "custom"),
        default="kindle_pw",
        help="Device preset (default: kindle_pw)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        metavar="N",
        help="Number of timed iterations (default: 20)",
    )
    parser.add_argument(
        "--widget",
        # WidgetType is a StrEnum; argparse compares strings directly.
        choices=sorted(_MOCK_DATA.keys()),
        default=None,
        metavar="TYPE",
        help=(
            "Widget type to benchmark.  Omit to benchmark "
            "all widgets together."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Run the benchmark and print results."""
    args = _parse_args()
    preset = DEVICE_PRESETS[args.device]

    if args.widget:
        widget_cfg, states = _MOCK_DATA[args.widget]
        widgets = [widget_cfg]
        extra: dict = {}
        if args.widget == WidgetType.DEVICE_BATTERY:
            extra["device_battery_level"] = 72
        config = _build_config(preset, states, **extra)
        label = args.widget
    else:
        widgets, states, extra = _all_widgets()
        config = _build_config(preset, states, **extra)
        label = "all widgets"

    # Warmup: populate font/icon LRU caches before measuring.
    _bench(widgets, config, 1)

    results = _bench(widgets, config, args.iterations)

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    _report(
        f"{args.device} ({preset.width}x{preset.height},"
        f" {preset.grayscale_levels}-level)"
        f" | {label}"
        f" | {args.iterations} iter",
        results,
        peak_rss_kb,
    )


if __name__ == "__main__":
    main()

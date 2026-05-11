#!/usr/bin/env python3
"""Convert weather-icons and MDI SVGs to 64x64 RGBA PNGs.

Weather icon SVGs are sourced from
custom_components/eink_dashboard/icons/svg/.  MDI (Material Design
Icons) SVGs are committed alongside at icons/svg/mdi/ (curated
subset, sourced from @mdi/svg under the Pictogrammers Free License).

Generated PNGs are written to
custom_components/eink_dashboard/icons/png/ (gitignored).

Requires: pip install cairosvg
"""

from __future__ import annotations

from pathlib import Path

import cairosvg

ICON_SIZE = 64

CONDITION_TO_SVG: dict[str, str] = {
    "sunny": "wi-day-sunny",
    "clear-night": "wi-night-clear",
    "cloudy": "wi-cloudy",
    "partlycloudy": "wi-day-cloudy",
    "fog": "wi-fog",
    "hail": "wi-hail",
    "lightning": "wi-lightning",
    "lightning-rainy": "wi-thunderstorm",
    "pouring": "wi-rain",
    "rainy": "wi-showers",
    "snowy": "wi-snow",
    "snowy-rainy": "wi-rain-mix",
    "windy": "wi-windy",
    "windy-variant": "wi-cloudy-windy",
    "exceptional": "wi-na",
}

DETAIL_TO_SVG: dict[str, str] = {
    "humidity": "wi-humidity",
    "barometer": "wi-barometer",
    "wind": "wi-strong-wind",
    "cloud": "wi-cloud",
    "raindrop": "wi-raindrop",
}

# Curated subset of MDI icons used by widget renderers.
# Covers all device_class mappings in _SENSOR_DEVICE_CLASS_ICONS and
# _BINARY_SENSOR_DEVICE_CLASS_ICONS, plus extras for new widget types
# (trash-can for WASTE_SCHEDULE, shield for ALARM).
MDI_ICONS: frozenset[str] = frozenset(
    {
        "account",
        "account-outline",
        "air-filter",
        "alert-circle",
        "battery",
        "battery-alert",
        "battery-charging",
        "blur",
        "brightness-5",
        "brightness-7",
        "check-circle",
        "crop-portrait",
        "cup-water",
        "currency-usd",
        "current-ac",
        "database",
        "door-closed",
        "door-open",
        "fire",
        "fire-alert",
        "flash",
        "flash-auto",
        "garage",
        "garage-open",
        "gauge",
        "home-account",
        "home-outline",
        "lightning-bolt",
        "lock",
        "lock-open",
        "molecule-co",
        "molecule-co2",
        "motion-sensor",
        "motion-sensor-off",
        "package",
        "package-up",
        "ph",
        "play-circle",
        "power-plug",
        "power-plug-off",
        "ruler",
        "shield",
        "shield-alert",
        "shield-check",
        "signal",
        "sine-wave",
        "smog",
        "smoke-detector-variant",
        "smoke-detector-variant-alert",
        "snowflake",
        "speedometer",
        "square",
        "square-outline",
        "stop-circle",
        "sun-wireless",
        "thermometer",
        "timer-outline",
        "trash-can",
        "vibrate",
        "volume-high",
        "volume-off",
        "water",
        "water-alert",
        "water-percent",
        "weather-dust",
        "weather-windy",
        "weight",
        "wifi",
        "wifi-off",
        "window-closed-variant",
        "window-open-variant",
    }
)

ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = ROOT / "custom_components" / "eink_dashboard"
# SVG sources are committed alongside the component.
SVG_DIR = COMPONENT_DIR / "icons" / "svg"
# Generated PNGs are gitignored; always rebuilt from SVGs.
OUT_DIR = COMPONENT_DIR / "icons" / "png"
# MDI SVGs are committed alongside the weather icons.
MDI_SVG_DIR = COMPONENT_DIR / "icons" / "svg" / "mdi"
MDI_OUT_DIR = OUT_DIR / "mdi"
WEATHER_OUT_DIR = OUT_DIR / "weather"


def _convert_weather_icons() -> None:
    """Convert weather-icons SVGs to PNGs."""
    WEATHER_OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_icons = {**CONDITION_TO_SVG, **DETAIL_TO_SVG}
    converted = 0
    skipped = 0
    for name, svg_name in all_icons.items():
        svg_path = SVG_DIR / f"{svg_name}.svg"
        png_path = WEATHER_OUT_DIR / f"{name}.png"

        if not svg_path.exists():
            print(f"SKIP {svg_name}.svg (not found)")
            skipped += 1
            continue

        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=ICON_SIZE,
            output_height=ICON_SIZE,
        )
        print(f"{svg_name}.svg -> {name}.png")
        converted += 1
    print(f"Weather icons: {converted} converted, {skipped} skipped")


def _convert_mdi_icons() -> None:
    """Convert committed MDI SVGs to PNGs.

    Sources SVGs from icons/svg/mdi/ (curated subset committed
    to the repo).  Skips all MDI conversion when the directory
    is absent.
    """
    if not MDI_SVG_DIR.is_dir():
        print("SKIP MDI icons (@mdi/svg not installed)")
        return

    MDI_OUT_DIR.mkdir(parents=True, exist_ok=True)

    converted = 0
    skipped = 0
    for name in sorted(MDI_ICONS):
        svg_path = MDI_SVG_DIR / f"{name}.svg"
        png_path = MDI_OUT_DIR / f"{name}.png"

        if not svg_path.exists():
            print(f"SKIP mdi/{name}.svg (not found)")
            skipped += 1
            continue

        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=ICON_SIZE,
            output_height=ICON_SIZE,
        )
        print(f"mdi/{name}.svg -> mdi/{name}.png")
        converted += 1
    print(f"MDI icons: {converted} converted, {skipped} skipped")


def main() -> None:
    """Build all icon PNGs from SVG sources."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _convert_weather_icons()
    _convert_mdi_icons()


if __name__ == "__main__":
    main()

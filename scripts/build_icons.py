#!/usr/bin/env python3
"""Convert weather-icons SVGs to 64x64 RGBA PNGs.

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

ROOT = Path(__file__).resolve().parent.parent
SVG_DIR = ROOT / "icons" / "svg"
OUT_DIR = ROOT / "custom_components" / "eink_dashboard" / "icons"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_icons = {**CONDITION_TO_SVG, **DETAIL_TO_SVG}
    for name, svg_name in all_icons.items():
        svg_path = SVG_DIR / f"{svg_name}.svg"
        png_path = OUT_DIR / f"{name}.png"

        if not svg_path.exists():
            print(f"SKIP {svg_name}.svg (not found)")
            continue

        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=ICON_SIZE,
            output_height=ICON_SIZE,
        )
        print(f"{svg_name}.svg -> {name}.png")


if __name__ == "__main__":
    main()

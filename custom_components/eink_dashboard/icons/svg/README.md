# Weather Icons SVGs

These SVG files are from the [Weather Icons](https://erikflowers.github.io/weather-icons/) project by Erik Flowers.

- **Source:** https://github.com/erikflowers/weather-icons
- **License:** SIL Open Font License 1.1 (see [LICENSE](LICENSE))

The 15 SVGs in this directory correspond to the Home Assistant weather condition strings.
At render time, `svg_render.py` inlines the icon path data directly into
the SVG output via Jinja2 filters (`weather_svg`, `mdi_svg`).  No PNG
conversion step is needed.

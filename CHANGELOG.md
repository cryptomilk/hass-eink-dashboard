# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Media Source platform exposing rendered dashboard PNGs in HA's Media Browser,
  enabling delivery to screens running OpenDisplay.
- TRMNL battery level support in the `device_battery` widget.
- Snap-to-widget-edges in the Lovelace editor: hold Shift while dragging a
  widget to align it to the nearest edge of any other widget.
- Design tool: interactive resize handles on the Raw SVG preview panel.
  Corner handles resize width and height; left/right edge handles resize
  width only. A dashed blue outline tracks the widget bounds, and handles
  snap to the widget's actual rendered content area.

### Changed

- Editor resize model: corner handles (nw/ne/sw/se) resize width and
  height; left/right edge handles (w/e) resize width only. Font size
  scales proportionally on corner resize for text and weather widgets.
- Bumped `resvg-py` to 0.3.2 for fontdb caching support.
- Weather widget: main temperature is now rendered in bold.

### Fixed

- Spurious `RuntimeError` logged during HA shutdown when the image
  refresh executor is already stopped is now suppressed.
- `device_battery` widget resize box now matches the rendered content
  width instead of a hardcoded 200 px default.

## [0.2.0] - 2026-05-15

### Added

- SVG rendering pipeline: all widgets are now rendered as Jinja2 SVG templates
  rasterised by `resvg-py`, replacing the PIL drawing infrastructure.
- WebSocket commands `eink_dashboard/render_widget` and
  `eink_dashboard/render_widgets` for fetching server-rendered SVG previews
  from the Lovelace editor.
- Shared SVG macro library (`_macros.svg.j2`) for card borders, dividers, and
  other reusable layout primitives.
- `mdi_svg` and `weather_svg` Jinja2 filters for inlining MDI and weather
  icons directly into SVG templates.
- State circle indicator on `status_icons` widget, controlled by the new
  `show_icon` and `show_state` options.
- Card container (`card_style`) support for the `text` widget.
- Standalone design tool (`tools/design_widget.py`) for iterating on widget
  layouts outside of Home Assistant.
- CI job publishing JUnit test results to GitHub Actions.

### Changed

- Editor canvas preview replaced by server-rendered SVGs; drag and resize
  interactions rewritten accordingly.
- `status_icons` widget redesigned from pill chips to icon-and-text labels.
- Config flow screen-portion selection step restricted to TRMNL devices only.
- TRMNL documentation URL standardised to `trmnl.com`.
- Build tooling migrated from tox to `uv`.

### Removed

- `LINE` widget type.
- PIL drawing infrastructure (`render.py` PIL helpers).
- cairosvg icon build pipeline.

### Fixed

- Widget SVG viewport clipped to the widget's content dimensions, preventing
  overflow into adjacent widgets.
- Card border inset now included in the `device_battery` natural-width
  calculation.
- Weather forecasts are now fetched in the SVG preview WebSocket handlers so
  the editor shows live forecast data.
- Config flow orientation indicator shown in the screen-portion step title.

## [0.1.0] - 2026-05-05

- Initial release.

[0.2.0]: https://github.com/cryptomilk/hass-eink-dashboard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/cryptomilk/hass-eink-dashboard/releases/tag/v0.1.0

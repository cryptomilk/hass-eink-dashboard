# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Sensor widget**: single-entity sensor card with optional sparkline history
  graph (`graph: "line"`), configurable `hours_to_show`, `detail` level, and
  fixed Y-axis `limits`.
- **Entities widget**: multi-entity list card with optional title, inline
  divider rows (`type: "divider"`), and section rows (`type: "section"`).
- **Entity widget**: large-value single-entity card showing state and unit,
  mirroring HA's Entity card.
- **Heading widget**: section heading with optional MDI icon and entity badges,
  superseding the deprecated Text widget.
- **Locale-aware number formatting**: per-device decimal and thousands
  separator override (decimal comma, decimal point, or HA default) settable
  in the integration options.
- **Visibility conditions**: all widgets now support a `visibility` list to
  show or hide based on entity state or other HA conditions.
- **Editor drag-and-drop reordering**: widget order can be changed by dragging
  rows in the widget list, replacing the previous up/down arrow buttons.
- **Editor live SVG preview scaling**: the preview panel scales
  proportionally while a widget is being resized.

### Changed

- Row dividers in Entities, Waste Schedule, and Weather widgets now render in
  light gray (`#b4b4b4`) instead of medium gray, improving visual hierarchy on
  16-level grayscale displays.  No change on 2-level (TRMNL) displays.
- Entity and Sensor widget header icon enlarged for better legibility on
  e-ink screens.
- Design tool default dashboard (no `--widget` flag) now previews all key
  widget types: Weather, Tile, Entity, Sensor (with sparkline), Waste
  Schedule, and Device Battery.

### Removed

- Deprecated widget types `text` (use `heading`), `sensor_rows`, and
  `status_icons` removed from the renderer and widget picker.  Existing
  configs that reference these types will no longer render.

### Fixed

- Entity and Sensor header icon circle now has consistent padding from the
  top card border (previously the circle clipped the border line).
- Heading widget had double padding below the title under
  `card_style: "border"`.
- Weather and Device Battery widgets: content soft-padding now applied
  consistently when `card_style: "none"`.
- Widget picker showed raw MDI icon strings instead of glyphs for Entities
  and Sensor card types.
- Waste Schedule, Tile, and Heading icon circle strokes are now widened on
  2-level (TRMNL) displays to prevent dithering artifacts.
- `recorder` integration declared in `after_dependencies` so history data is
  available when the Sensor widget fetches it at startup.
- Translation selector keys for date format settings corrected to lowercase.

## [0.3.0] - 2026-05-16

### Added

- Media Source platform exposing rendered dashboard PNGs in HA's Media Browser,
  enabling delivery to screens running [OpenDisplay](https://opendisplay.org/).
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

[Unreleased]: https://github.com/cryptomilk/hass-eink-dashboard/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/cryptomilk/hass-eink-dashboard/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/cryptomilk/hass-eink-dashboard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/cryptomilk/hass-eink-dashboard/releases/tag/v0.1.0

---
name: implement-widget-tests
description: "Write TDD tests for a widget type: structural tests (borders, dividers), alignment tests (icon centering), and scaling tests (proportional sizing). Uses test helpers from tests/helpers.py."
when_to_use: "When writing tests for a new widget or converting an existing widget from PIL to SVG (any step 1.x of the SVG migration). Always run BEFORE implementing the renderer (TDD red phase)."
argument-hint: "[widget-type]"
arguments: widget-type
allowed-tools: Bash(uv *)
---

# Write Widget Tests: $widget-type

Write comprehensive tests for the **$widget-type** widget. This is the
TDD red phase — tests must FAIL until the SVG renderer is implemented.

## Before you start

1. Read the existing PIL renderer in `custom_components/eink_dashboard/render.py`
   (if converting an existing widget) to understand the visual elements,
   config parameters, and state handling the new SVG renderer must match.
   For a new widget, read the task description / spec doc provided.
2. Read `tests/helpers.py` for available test helpers.
3. Read existing test classes in `tests/test_render.py` for patterns.
   The SEPARATOR tests (`TestRenderSeparator`) are the reference for
   structural/pixel assertions. The weather tests (`TestRenderWeather`)
   show the `_DEFAULTS` + `_config()` pattern.
4. Read `custom_components/eink_dashboard/templates/_macros.svg.j2` for
   macro signatures (`card_container`, `card_row`, `chip`) so you know
   the card container insets to use in pixel region calculations.
5. Read `const.py` for `COLOR_BLACK=0`, `COLOR_WHITE=255`,
   `COLOR_GRAY=120`, `PADDING=24`.

## Redesign vs. new widget

**Redesigning an existing widget** (SENSOR_ROWS, STATUS_ICONS,
WASTE_SCHEDULE, DEVICE_BATTERY): the old test class exists but tests the
pre-redesign layout (flat text, `font_size`-based, no `w`/`h`, no
`card_style`). **Replace the entire old test class** with a new one that
tests the redesigned layout. Also update `MOCK_*_STATES` to include
`device_class` in attributes (the old mocks may lack it — the redesigned
renderers need it for icon resolution).

**Adding a new widget** (PERSON, ALARM, LOCK, GRAPH): create a new test
class and new mock states from scratch.

## Existing test classes

!`grep -n "^class Test" tests/test_render.py`

## Current test helper signatures

!`grep -n "^def " tests/helpers.py`

## Current WidgetMetrics sizing ratios

Call `_compute_metrics(row_h)` in tests to derive expected pixel regions
from the same ratios the renderer uses — no hardcoded magic numbers.

!`grep -n "def _compute_metrics" -A 12 custom_components/eink_dashboard/render.py`

## SVG macro signatures (from _macros.svg.j2)

!`grep -n "macro card_container\|macro card_row\|macro chip" custom_components/eink_dashboard/templates/_macros.svg.j2`

## Icon resolver (in render.py)

!`grep -n "def _device_class_icon" -A 5 custom_components/eink_dashboard/render.py`

## SVG renderer registry

!`grep -n "_SVG_RENDERERS" -A 12 custom_components/eink_dashboard/svg_render.py`

## Imports

```python
from custom_components.eink_dashboard.const import (
    COLOR_BLACK, COLOR_GRAY, PADDING, DEFAULT_CARD_STYLE,
)
from custom_components.eink_dashboard.render import (
    WidgetMetrics, _compute_metrics,
    _device_class_icon, render_dashboard,
)
from tests.helpers import (
    assert_all_white, assert_card_border, assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally, assert_vertically_centered,
    content_bbox, make_config, pixel, render_to_image,
)
```

## Test structure

Create a test class `TestRender{WidgetName}` (PascalCase) in
`tests/test_render.py`. When redesigning an existing widget, replace
the old test class in-place (same position in the file).

### 1. Structural tests — verify visual elements exist

- **Card border/container**: dark pixels along edges for
  `card_style="border"`, gray pixels on left edge for
  `card_style="left_bar"`, all white for `"none"`
- **Default == none**: rendering without `card_style` must be
  byte-identical to `card_style="none"`. Add this test for every
  card-style widget:

  ```python
  def test_card_style_none_is_default(self) -> None:
      # Omitting card_style must produce the same output as "none".
      base = {"type": "$widget-type", "x": 0, "y": 0, "w": 400,
              "h": 56, "entities": ["sensor.temperature"]}
      with_none = render_dashboard(
          [{**base, "card_style": "none"}], self._config()
      )
      without = render_dashboard([base], self._config())
      assert with_none == without
  ```
- **Row dividers**: gray pixels at row boundaries (between entries)
- **Chip shape**: rounded corners (corner pixels white, nearby edge
  pixels dark)
- **Icon circle**: dark/gray pixels in the icon area

Use `assert_card_border(img, w, h, m)` for the four-edge border check
(default `bottom_margin=1` accommodates PIL stroke rounding).
Use `assert_has_dark_pixels()`, `assert_all_white()`,
`assert_has_gray_pixels()` for everything else.

### 2. Alignment tests — verify layout relationships

- **Icon ↔ text vertical centering**: icon center Y matches text
  center Y
- **Right-aligned values**: value text near the right edge of the
  widget

Use `assert_vertically_centered(img, icon_region, text_region,
tolerance=2.0)`. Each region is `(x1, y1, x2, y2)` absolute
coordinates.

### 3. Scaling tests — verify proportional sizing

- Render at `h=56` and `h=112`, compare `content_bbox` heights via
  `assert_scales_proportionally(..., expected_ratio=2.0,
  tolerance=0.25)`.

### 4. Data tests — verify state handling

- Missing entity: widget doesn't crash; missing state is skipped
  silently
- Missing attributes: handles absent `device_class`, `friendly_name`
- Edge cases: empty entity list, single entity

## Mock state setup

Define mock states at **module level** (not pytest fixtures —
conftest.py only has HA stubs). Include `device_class` in attributes
(required for icon resolution in redesigned widgets). For binary
sensors, define separate entries for `on` and `off` states to test
state-dependent icon resolution:

```python
MOCK_{WIDGET}_STATES = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
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
```

**Lesson from completed cycles:** The old `MOCK_SENSOR_STATES` lacked
`device_class`, which caused icon resolution to fall back to letter
labels. Always include `device_class` in mock attributes.

## Widget config shape (redesigned widgets)

Redesigned widgets use `w` and `h` instead of `font_size`. The `w`
parameter defines the card/chip boundary width, and `h` defines the
total widget height. All internal dimensions derive from `h`.

```python
# Card-style widget (sensor_rows, waste_schedule, person, alarm)
widget = {
    "type": "$widget-type",
    "x": PADDING, "y": 0, "w": 350, "h": 112,
    "entities": ["sensor.temperature", "sensor.humidity"],
    "card_style": "border",  # or "left_bar" or "none"
}

# Chip-style widget (status_icons, lock)
widget = {
    "type": "$widget-type",
    "x": PADDING, "y": 0, "w": 350, "h": 28,
    "entities": ["binary_sensor.front_door"],
}
```

**Do NOT use `font_size`** in redesigned widget configs. The TEXT
widget is the only widget that keeps `font_size`.

## Test class pattern

```python
class TestRender{WidgetName}:
    # Verify rendering of $widget-type widgets.
    _DEFAULTS: dict[str, object] = {
        "width": 400,
        "height": 300,
        "states": MOCK_{WIDGET}_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def test_{widget}_draws_content(self) -> None:
        # Verify that content is rendered in the expected region.
        widgets = [{
            "type": "$widget-type",
            "x": PADDING, "y": 0, "w": 350, "h": 56,
            "entities": ["sensor.temperature"],
        }]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, PADDING, 0, 350, 56)

    def test_{widget}_empty_entities_white(self) -> None:
        # Empty entity list produces blank output.
        widgets = [{
            "type": "$widget-type",
            "x": PADDING, "y": 0, "w": 350, "h": 56,
            "entities": [],
        }]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, PADDING, 0, 350, 56)

    def test_{widget}_icon_centered_with_text(self) -> None:
        # Verify icon circle is vertically centered with text block.
        m = _compute_metrics(56)
        widgets = [{
            "type": "$widget-type",
            "x": 0, "y": 0, "w": 400, "h": 56,
            "entities": ["sensor.temperature"],
        }]
        img = render_to_image(widgets, self._config())
        assert_vertically_centered(
            img,
            icon_region=(m.padding, 0, m.padding + m.icon_dia, 56),
            text_region=(
                m.padding + m.icon_dia + m.inner_gap, 0, 380, 56
            ),
        )
```

## Computing expected pixel regions

Derive regions from `_compute_metrics(row_h)` so tests stay in sync
with the renderer's own layout:

```python
m = _compute_metrics(56)  # row_h = widget h / number of rows
# Card border:
#   x in [0, m.border] and [w - m.border, w]
# Icon circle:
#   x in [x_off + m.padding, x_off + m.padding + m.icon_dia]
# Text start:
#   x = x_off + m.padding + m.icon_dia + m.inner_gap
# Row divider:
#   y = row_y + row_h  (height = m.divider)
# card_container macro passes (x_off, right_inset) to caller:
#   "border"   -> (m.padding, m.padding)
#   "left_bar" -> (bar_w + m.padding, 0)
#   "none"     -> (0, 0)
# Content width (cw):
#   cw = w - x_off - right_inset
```

## Lessons from completed TDD cycles

1. **Pixel-level assertions for borders**: The SEPARATOR tests use
   exact `pixel()` checks (e.g. `pixel(img, x, 50) == COLOR_BLACK`)
   for precise structural verification. Use these when the exact
   position is known.

2. **Region-based assertions for content**: Use
   `assert_has_dark_pixels()` for areas where content location is
   approximate (text rendering varies by font backend).

3. **`content_bbox()` for measuring**: Use it to find actual rendered
   content size for scaling and alignment tests. It returns the tight
   bounding box of non-white pixels.

4. **2-level display tests**: When the widget uses gray elements
   (dividers, bars, left_bar), test the `grayscale_levels=2` path
   that widens them. Pass it via config:
   `config = {**self._CONFIG, "grayscale_levels": 2}`.

5. **Test each `card_style` variant**: For card-style widgets, test
   all three styles (`"border"`, `"left_bar"`, `"none"`) in separate
   test methods. The SEPARATOR tests show this pattern well.

6. **Missing entity = no crash**: Always include a test that passes a
   nonexistent entity ID and verifies the widget doesn't crash.
   Also test empty entity list → all white canvas.

7. **Each test needs a comment**: Every test function must start with
   a short comment explaining what it verifies.

8. **Engine-agnostic tests only**: Tests call `render_dashboard()` and
   inspect PNG output. Do NOT import or call PIL drawing helpers
   (`_draw_card_container`, `_draw_card_row`, `_draw_chip`, etc.) from
   tests. Those helpers are deleted when the PIL pipeline is removed.
   The entry point (`render_dashboard`) dispatches transparently to the
   SVG pipeline.

## Font metric tolerance

The SVG pipeline uses resvg for text rendering, which may produce
slightly different glyph metrics than PIL. Keep the following in mind:

- Use region-based assertions (`assert_has_dark_pixels`,
  `assert_has_gray_pixels`) rather than exact pixel checks for text
  content. Text position may shift by 1-3 pixels between engines.
- Use `tolerance=3.0` (instead of 2.0) for
  `assert_vertically_centered` when testing icon-text alignment.
  resvg's `dominant-baseline="central"` differs slightly from PIL's
  ascender-based centering.
- `assert_scales_proportionally` tolerance of 0.25 remains sufficient
  — proportional scaling is engine-agnostic.
- Exact `pixel()` checks are fine for geometry (borders, dividers,
  chip corners) — these are SVG shapes, not text.

## Verification

Run tests — they should FAIL at this point (TDD red phase):

```bash
uv run --group test pytest \
    tests/test_render.py::TestRender{WidgetName} -v
```

The tests define the expected behavior. The renderer implementation
(via `/implement-widget-python`) makes them pass.

## Key references

- Widget behavior source: existing PIL renderer in `render.py` (for
  conversions), or task description (for new widgets)
- Test helpers: `tests/helpers.py`
- Reference structural tests: `TestRenderSeparator` in
  `tests/test_render.py`
- Reference `_DEFAULTS` + `_config()` pattern: `TestRenderWeather`
- Sizing ratios: `_compute_metrics()` in `render.py`
- SVG macros: `templates/_macros.svg.j2`
- Colors: `COLOR_BLACK=0`, `COLOR_WHITE=255`, `COLOR_GRAY=120` in
  `const.py`

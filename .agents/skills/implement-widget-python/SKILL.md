---
name: implement-widget-python
description: "Implement a widget renderer in render.py using shared helpers (WidgetMetrics, _draw_card_container, _draw_card_row, _draw_chip). Follows TDD green phase — makes existing tests pass."
when_to_use: "When implementing or redesigning a widget renderer in the Python PIL backend. Run AFTER tests are written (TDD green phase)."
argument-hint: "[widget-type]"
arguments: widget-type
allowed-tools: Bash(tox *)
---

# Implement Widget Renderer: $widget-type

Implement the Python PIL renderer for **$widget-type** in `render.py`.

## Before you start

1. Read the **$widget-type** section in `REDESIGN_WIDGETS.md` for the
   complete design spec (layout, sizing, icon mapping, state handling).
2. Read the existing tests for this widget (class
   `TestRender{WidgetName}`) — these define the expected behavior.
3. Read `const.py` for `WidgetType`, `COLOR_*` constants, `PADDING`,
   `DEFAULT_CARD_STYLE`.
4. Read the shared helpers in `render.py`: `_compute_metrics`,
   `_draw_card_container`, `_draw_card_row`, `_draw_chip`,
   `_draw_chip_flow`, `_chip_width`.

## Current shared helpers in render.py

!`grep -n "^def _\|^class Widget\|^_CHIP\|^type " custom_components/eink_dashboard/render.py`

## Current renderer registry

!`grep -n "_RENDERERS" -A 12 custom_components/eink_dashboard/render.py`

## Key helper signatures (injected from source)

!`grep -n "^def _compute_metrics\|^def _draw_card_\|^def _draw_chip\|^def _chip_width\|^def _device_class_icon\|^def _load_icon\|^def _load_font" -A 6 custom_components/eink_dashboard/render.py`

!`grep -n "^class WidgetMetrics" -A 10 custom_components/eink_dashboard/render.py`

### Usage notes (not derivable from signatures)

- `_draw_card_container` returns content x-offset: `"border"` →
  `m.padding`, `"left_bar"` → `bar_w + m.padding`, `"none"` → `0`.
  Always pass `grayscale_levels=config.get("grayscale_levels", 16)`.
- `_draw_card_row`: `primary` is required (keyword-only, no default).
  `icon` is `(gray, mask)` tuple from `_load_icon()`. Icons are
  resized internally to 60% of `m.icon_dia`; load at `m.icon_dia`.
  Line gap between primary/secondary: `max(2, round(row_h * 0.04))`.
- `_draw_chip` returns `x + chip_w`. `icon` and `inverted` are
  keyword-only.
- `_draw_chip_flow` returns `last_row_y + h`. `chips` is
  `list[dict]` with keys: `text` (required), `icon` (optional
  `(gray, mask)` tuple), `inverted` (optional bool).
- `_device_class_icon` returns MDI name without `"mdi:"` prefix, or
  `None`. Pass `domain="binary_sensor"` for state-dependent icons.
  Extract domain: `entity_id.split(".")[0]`.
- `_load_icon("mdi:thermometer", size)` → `(gray, mask)` or `None`.
- `_load_font(size, medium=True)` loads Roboto Medium (weight 500).

## Redesigning an existing widget

When replacing an existing renderer (SENSOR_ROWS, STATUS_ICONS,
WASTE_SCHEDULE, DEVICE_BATTERY), the old renderer uses legacy helpers
that the redesigned version must **stop using**:

**Old helpers (do NOT use in redesigned renderers):**
- `_extract_multi_entity_params()` — extracted x, y, font_size,
  title, entities, states, right_edge. Redesigned widgets read `w`
  and `h` directly and don't use `font_size`.
- `_resolve_entity()` — returned `_EntityInfo` namedtuple. Redesigned
  widgets look up state from `config["states"]` directly.
- `_draw_section_title()` — drew a title with font_size-based advance.
  Redesigned widgets draw titles above the card container using
  `_load_font(m.font_primary, medium=True)`.
- `_draw_indicator()` — drew filled/outline squares/ellipses.
  Redesigned widgets use `_draw_card_row()` with icon circles or
  `_draw_chip()` with inverted mode instead.

**Replace the old renderer function in-place.** Keep the same function
name and `_RENDERERS` registration.

**Preserve `_PROBLEM_DEVICE_CLASSES`** for STATUS_ICONS: the set
determines which device classes show as "problem" state (inverted
chip). The redesigned chip-style renderer should use it for the
`inverted` flag.

## Implementation steps

### 1. Add to WidgetType enum (if new widget)

In `custom_components/eink_dashboard/const.py`, add to `WidgetType`.
Keep alphabetical order.

### 2. Write the renderer function

Renderer signature is always 3-arg `(draw, widget, config) -> None`.
Get `img` from `config["_image"]` at the top.

**Card-style renderer pattern** (sensor_rows, waste_schedule, person,
alarm):

```python
def render_{widget_type}(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    """..."""
    img = config["_image"]
    grayscale_levels = config.get("grayscale_levels", 16)
    x, y = widget.get("x", PADDING), widget.get("y", 0)
    w, h = widget["w"], widget["h"]
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    entities = widget.get("entities", [])
    states = config.get("states", {})

    n = len(entities)
    if n == 0:
        return
    row_h = h // n
    m = _compute_metrics(row_h)
    x_off = _draw_card_container(
        draw, x, y, w, h, m, card_style, grayscale_levels
    )
    cx, cw = x + x_off, w - x_off
    # Subtract right-side padding for border so content stays
    # inside the border stroke.
    if card_style == "border":
        cw -= m.padding

    for i, entity_id in enumerate(entities):
        state = states.get(entity_id)
        if state is None:
            continue
        row_y = y + i * row_h
        attrs = state.get("attributes", {})
        domain = entity_id.split(".")[0]
        icon_name = _device_class_icon(
            attrs, state["state"], domain
        )
        icon = (
            _load_icon(f"mdi:{icon_name}", m.icon_dia)
            if icon_name else None
        )
        _draw_card_row(
            draw, img, cx, row_y, cw, row_h, m,
            primary=attrs.get("friendly_name", entity_id),
            secondary=(
                f"{state['state']}"
                f"{attrs.get('unit_of_measurement', '')}"
            ),
            icon=icon,
        )
        # Row divider between entries (not after last)
        if i < n - 1:
            div_y = row_y + row_h
            draw.line(
                [
                    (cx + m.padding, div_y),
                    (cx + cw - m.padding, div_y),
                ],
                fill=COLOR_GRAY,
                width=m.divider,
            )
```

**Chip-style renderer pattern** (status_icons, lock):

```python
def render_{widget_type}(
    draw: ImageDraw.ImageDraw,
    widget: Widget,
    config: DisplayConfig,
) -> None:
    """..."""
    img = config["_image"]
    x, y = widget.get("x", PADDING), widget.get("y", 0)
    w, h = widget["w"], widget["h"]
    entities = widget.get("entities", [])
    states = config.get("states", {})

    m = _compute_metrics(h)
    font = _load_font(round(h * 0.46))
    chips: list[dict[str, object]] = []
    for entity_id in entities:
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        domain = entity_id.split(".")[0]
        icon_name = _device_class_icon(
            attrs, state["state"], domain
        )
        icon = (
            _load_icon(
                f"mdi:{icon_name}",
                round(h * _CHIP_ICON_RATIO),
            )
            if icon_name else None
        )
        chips.append({
            "text": attrs.get("friendly_name", entity_id),
            "icon": icon,
            "inverted": state["state"] == "on",
        })
    _draw_chip_flow(
        draw, img, x, y, w, h, chips, font, m.border
    )
```

### 3. Register in _RENDERERS dict

```python
_RENDERERS: dict[WidgetType, RendererFn] = {
    ...
    WidgetType.{WIDGET_TYPE}: render_{widget_type},
}
```

### 4. Clean up old code

When redesigning, remove old constants that are no longer used
(e.g. `_SENSOR_ROW_HEIGHT`, `FONT_SIZE_SENSOR_ROWS`,
`_STATUS_ICON_SIZE`, `_STATUS_ROW_HEIGHT`, etc.). Only remove
constants that **your changes** made unused — don't remove unrelated
dead code.

### 5. Run tests

```bash
tox -e format,lint,typecheck,test
```

All tests must pass. Fix any failures — the tests define correct
behavior.

## Key constraints

- **No `font_size` parameter.** All sizes derive from `w` and `h`
  via `_compute_metrics()`. TEXT widget is the only exception.
- **Use shared helpers.** Don't duplicate card/chip/row drawing logic.
- **`img` from config.** Get the PIL Image via `config["_image"]`.
- **Missing state = skip.** Log with `_LOGGER.debug()`, don't crash.
- **Icon resizing.** `_draw_card_row` resizes icons to 60% of
  `m.icon_dia` internally. Load at `m.icon_dia` to avoid upscaling.
- **`primary` is required.** It has no default in `_draw_card_row`.
- **Line length: 79 chars.** Wrap long lines at word boundaries.

## Key references

- Design spec: `REDESIGN_WIDGETS.md`
- Shared helpers: `_compute_metrics`, `_draw_card_container`,
  `_draw_card_row`, `_draw_chip`, `_draw_chip_flow` in `render.py`
- Icon resolution: `_device_class_icon(attrs, state, domain)`,
  `_load_icon()` in `render.py`
- Colors: `COLOR_BLACK=0`, `COLOR_WHITE=255`, `COLOR_GRAY=120`

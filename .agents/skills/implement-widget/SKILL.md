---
name: implement-widget
description: "Implement a widget's SVG template and Python context builder. Creates templates/{type}.svg.j2 and _build_{type}_context() in svg_render.py. Follows TDD green phase — makes existing tests pass."
when_to_use: "When implementing the SVG template and context builder for a new widget type. Always run AFTER tests are written (TDD green phase)."
argument-hint: "[widget-type]"
arguments: widget-type
allowed-tools: Bash(uv *)
---

# Implement Widget Renderer: $widget-type

Implement the SVG template and Python context builder for **$widget-type**.
The output of this work is two artifacts:

1. `custom_components/eink_dashboard/templates/$widget-type.svg.j2`
2. `_build_$widget-type_context()` in `svg_render.py`

## Before you start

1. Read the existing tests (`TestRender{WidgetName}` in
   `tests/test_render.py`) — these define the expected behavior.
2. Read `const.py` for `WidgetType`, `COLOR_*` constants, `PADDING`,
   `DEFAULT_CARD_STYLE`.
3. Read `svg_render.py` for the Jinja2 environment, `_svg_to_png()`,
   icon filter functions (`_mdi_svg_filter`, `_weather_svg_filter`),
   and any existing `_build_*_context()` functions.
4. Read `templates/_macros.svg.j2` for the three shared macros:
   `card_container`, `card_row`, `chip`.

## Current SVG infrastructure

!`grep -n "^def \|^_SVG_RENDERERS\|^_jinja_env\|^_TEMPLATE_DIR\|^_FONTS_DIR\|^_mdi\|^_weather" custom_components/eink_dashboard/svg_render.py`

## SVG macro signatures

!`grep -n "{%- macro\|{%  macro" custom_components/eink_dashboard/templates/_macros.svg.j2`

## WidgetMetrics and _compute_metrics (in render.py)

!`grep -n "^class WidgetMetrics" -A 10 custom_components/eink_dashboard/render.py`

!`grep -n "^def _compute_metrics" -A 12 custom_components/eink_dashboard/render.py`

## Icon name resolver (in render.py)

!`grep -n "^def _device_class_icon" -A 6 custom_components/eink_dashboard/render.py`

## Current SVG renderer registry

!`grep -n "_SVG_RENDERERS" -A 12 custom_components/eink_dashboard/svg_render.py`

## Imports

Context builders need these imports from sibling modules.
`_compute_metrics`, `_device_class_icon`, and `_load_font` live in
`render.py` to avoid circular imports — `svg_render.py` imports them
lazily at call time.

```python
from custom_components.eink_dashboard.const import (
    DEFAULT_CARD_STYLE,
    PADDING,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    _device_class_icon,
    _load_font,        # chip width measurement only
)
```

`_mdi_svg_filter`, `_weather_svg_filter`, `_widget_dim`,
`_auto_row_height`, and `_DEFAULT_ROW_H` are already in
`svg_render.py` — call them directly, no import needed.

## Macro usage notes

- **`card_container`** uses Jinja2 `{% call %}` syntax. The macro
  passes `(x_off, right_inset)` back to the caller body:
  `"border"` → `(m.padding, m.padding)`;
  `"left_bar"` → `(bar_w + m.padding, 0)`;
  `"none"` → `(0, 0)`.
  Content starts at `x_off`; content width = `w - x_off - right_inset`.
  Always pass `grayscale_levels` from config.
- **`card_row`** expects all sizes from `WidgetMetrics` fields plus
  `icon_svg` (pre-built SVG string, empty string for letter fallback)
  and `letter` (single uppercase char, empty string when icon_svg is
  set). `primary` is the entity label; `secondary` is the state + unit.
- **`chip`** requires pre-computed `w` because text width depends on
  font metrics unavailable in Jinja2. The context builder must compute
  chip widths using `_load_font(size).getlength(text)` from PIL — the
  font object is used only for measurement, not for drawing.
- **Icon filters** generate the SVG string in Python. Call
  `_mdi_svg_filter(name, size)` in the context builder and pass the
  result as the `icon_svg` string to the template. Do NOT call filters
  from inside templates — pass the pre-built string via context.
- **`_device_class_icon(attrs, state_val, domain)`** returns an MDI
  icon name without the `"mdi:"` prefix, or `None`. Extract domain:
  `entity_id.split(".")[0]`.

## Implementation steps

### 1. Add to WidgetType enum (if new widget)

In `const.py`, add the new value to `WidgetType`. Keep alphabetical
order.

### 2. Create the SVG template

Create `custom_components/eink_dashboard/templates/$widget-type.svg.j2`.

The template receives a pre-computed context dict from the Python
context builder. All layout math (positions, sizes, icon SVG strings,
chip widths) is computed in Python. Templates only emit SVG markup.

Every template must begin with a white background rect so the widget
is opaque when composited onto the dashboard canvas:

```xml
<rect width="{{ w }}" height="{{ h }}" fill="white"/>
```

**Card-style template pattern** (sensor_rows, waste_schedule):

```jinja
{%- from "_macros.svg.j2" import card_container, card_row -%}
<svg xmlns="http://www.w3.org/2000/svg"
     width="{{ w }}" height="{{ h }}">
<rect width="{{ w }}" height="{{ h }}" fill="white"/>
{%- call(x_off, r_inset) card_container(
    x=0, y=0, w=w, h=h,
    card_style=card_style,
    radius=m.radius, border=m.border,
    padding=m.padding, left_bar=m.left_bar,
    grayscale_levels=grayscale_levels) -%}
{%- for row in rows -%}
{{ card_row(
    x=x_off, y=row.y,
    w=w - x_off - r_inset, row_h=row_h,
    padding=m.padding, icon_dia=m.icon_dia,
    inner_gap=m.inner_gap, border=m.border,
    font_primary=m.font_primary,
    font_secondary=m.font_secondary,
    primary=row.primary,
    secondary=row.secondary,
    value=row.value,
    icon_svg=row.icon_svg,
    letter=row.letter) }}
{%- if not loop.last -%}
<line
  x1="{{ x_off + m.padding }}"
  y1="{{ row.y + row_h }}"
  x2="{{ w - r_inset - m.padding }}"
  y2="{{ row.y + row_h }}"
  stroke="#787878" stroke-width="{{ m.divider }}"/>
{%- endif -%}
{%- endfor -%}
{%- endcall -%}
</svg>
```

**Chip-style template pattern** (status_icons):

```jinja
{%- from "_macros.svg.j2" import chip -%}
<svg xmlns="http://www.w3.org/2000/svg"
     width="{{ w }}" height="{{ h }}">
<rect width="{{ w }}" height="{{ h }}" fill="white"/>
{%- for c in chips -%}
{{ chip(
    x=c.x, y=c.y, w=c.w, h=chip_h,
    text=c.text, border=m.border,
    icon_svg=c.icon_svg,
    inverted=c.inverted) }}
{%- endfor -%}
</svg>
```

**Simple template pattern** (text, separator):

```jinja
<svg xmlns="http://www.w3.org/2000/svg"
     width="{{ w }}" height="{{ h }}">
<rect width="{{ w }}" height="{{ h }}" fill="white"/>
<!-- widget-specific SVG elements here -->
</svg>
```

Template coordinates are relative to origin (0, 0) — the outer
composition handles absolute `x`/`y` placement on the dashboard.

### 3. Write the context builder

Add `_build_$widget-type_context(widget, config) -> dict` to
`svg_render.py`. The context builder:

- Extracts widget dimensions and config from `widget` and `config`
- Calls `_compute_metrics(row_h)` to get `WidgetMetrics`
- Calls `_device_class_icon()` to resolve icon names
- Calls `_mdi_svg_filter(name, size)` to build icon SVG strings
- Computes all positions, sizes, and data — returns a plain dict

The template receives only this dict; no layout math happens in Jinja2.

**Card-style context builder pattern:**

```python
def _build_{widget_type}_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build template context for $widget-type widget.

    Args:
        widget: Widget config dict with x, w, h, entities,
            card_style, title.
        config: DisplayConfig with states and grayscale_levels.

    Returns:
        Template context dict.
    """
    x = widget.get("x", PADDING)
    w = _widget_dim(widget, "w", config["width"] - x)
    title: str = widget.get("title", "")
    card_style = widget.get(
        "card_style", DEFAULT_CARD_STYLE
    )
    entities = widget.get("entities", [])
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    n = len(entities)
    if n == 0:
        return {
            "w": w,
            "h": _widget_dim(widget, "h", _DEFAULT_ROW_H),
            "rows": [],
            "m": None,
        }
    # Row-based: auto-size height to fit n rows at
    # _DEFAULT_ROW_H px each.  An explicit "h" overrides this.
    h = _widget_dim(widget, "h", _auto_row_height(title, n))
    row_h = h // n
    m = _compute_metrics(row_h)

    rows: list[dict[str, object]] = []
    for i, entity_id in enumerate(entities):
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        domain = entity_id.split(".")[0]
        icon_name = _device_class_icon(
            attrs, state["state"], domain
        )
        # Call filter in Python; pass result as icon_svg string.
        icon_svg = (
            _mdi_svg_filter(icon_name, m.icon_dia * 6 // 10)
            if icon_name
            else ""
        )
        letter = (
            ""
            if icon_name
            else attrs.get(
                "friendly_name", entity_id
            )[:1].upper()
        )
        unit = attrs.get("unit_of_measurement", "")
        rows.append({
            "y": i * row_h,
            "primary": attrs.get(
                "friendly_name", entity_id
            ),
            "secondary": f"{state['state']}{unit}",
            "value": "",
            "icon_svg": icon_svg,
            "letter": letter,
        })
    return {
        "w": w,
        "h": h,
        "m": m,
        "card_style": card_style,
        "grayscale_levels": grayscale_levels,
        "rows": rows,
        "row_h": row_h,
    }
```

**Chip-style context builder — chip width computation:**

Chips require pre-computed widths because Jinja2 cannot measure text.
Use a PIL font object (Roboto at `round(h * 0.46)`) only for
measurement — `_load_font` is LRU-cached, so this is cheap:

```python
def _build_{widget_type}_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build template context for $widget-type widget."""
    x = widget.get("x", PADDING)
    w = _widget_dim(widget, "w", config["width"] - x)
    h = _widget_dim(widget, "h", _DEFAULT_ROW_H)
    entities = widget.get("entities", [])
    states = config.get("states", {})
    m = _compute_metrics(h)

    # Chip sizing ratios — these MUST match the ratios in the
    # chip macro in _macros.svg.j2.  If the macro changes,
    # update these values to match.  Verify before using.
    pad = round(h * 0.18)
    icon_sz = round(h * 0.29)
    icon_gap = round(h * 0.14)
    font_size = max(10, round(h * 0.46))
    font = _load_font(font_size)  # PIL, for width measurement only.

    chip_gap = m.border + 4

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
        icon_svg = (
            _mdi_svg_filter(icon_name, icon_sz)
            if icon_name
            else ""
        )
        label = attrs.get("friendly_name", entity_id)
        text_w = round(font.getlength(label))
        chip_w = (
            pad
            + (icon_sz + icon_gap if icon_svg else 0)
            + text_w
            + pad
        )
        chips.append({
            "text": label,
            "icon_svg": icon_svg,
            "inverted": state["state"] == "on",
            "w": chip_w,
        })

    # Flow layout: pack chips left-to-right with wrapping.
    cx, cy = 0, 0
    for c in chips:
        if cx > 0 and cx + c["w"] > w:
            cx, cy = 0, cy + h + chip_gap
        c["x"] = cx
        c["y"] = cy
        cx += c["w"] + chip_gap

    return {
        "w": w,
        "h": h,
        "m": m,
        "chip_h": h,
        "chips": chips,
    }
```

### 4. Register in _SVG_RENDERERS

In `svg_render.py`, add to the `_SVG_RENDERERS` dict:

```python
_SVG_RENDERERS: dict[str, SvgContextFn] = {
    ...
    WidgetType.{WIDGET_TYPE}: _build_{widget_type}_context,
}
```

### 5. Run tests

```bash
uv run --group lint ruff check . && \
uv run --group format ruff format --check . && \
uv run --group typecheck ty check && \
uv run --group test pytest
```

All tests must pass. Fix any failures — the tests define correct
behavior.

## Key constraints

- **No `font_size` parameter.** All sizes derive from `w` and `h`
  via `_compute_metrics()`. TEXT widget is the only exception.
- **Use shared macros.** Do not duplicate card/chip/row SVG markup.
  Use `card_container`, `card_row`, `chip` from `_macros.svg.j2`.
- **All layout math in Python.** Templates receive final coordinates
  and data. No arithmetic or conditionals in Jinja2 beyond what the
  macros already compute internally.
- **White background rect.** Every template starts with
  `<rect width="{{ w }}" height="{{ h }}" fill="white"/>`.
- **Missing state = skip.** If `states.get(entity_id)` returns
  `None`, skip the entity and continue. Do not crash.
- **Icon inlining via filter functions.** Call `_mdi_svg_filter(name,
  size)` or `_weather_svg_filter(condition, size)` in the context
  builder and pass the returned string as `icon_svg`.
- **Font references in SVG.** Use `font-family="Roboto"` and
  `font-weight="500"` for Roboto Medium. No `_load_font()` calls in
  templates.
- **Template coordinates are relative.** Compute row `y` positions
  relative to 0, not to the widget's absolute position on the
  dashboard. Outer composition handles `x`/`y` placement.
- **Line length: 79 chars.** Applies to Python, Jinja2 templates,
  and docstrings.

## Key references

- SVG macros: `card_container`, `card_row`, `chip` in
  `templates/_macros.svg.j2`
- SVG pipeline: `_jinja_env`, `_svg_to_png()`, `_mdi_svg_filter()`,
  `_weather_svg_filter()` in `svg_render.py`
- Layout metrics: `_compute_metrics()`, `WidgetMetrics` in `render.py`
- Icon name resolution: `_device_class_icon()` in `render.py`
- Colors: `COLOR_BLACK=0`, `COLOR_WHITE=255`, `COLOR_GRAY=120`,
  `COLOR_LIGHT_GRAY=180` in `const.py`
- Auto-sizing helpers: `_widget_dim`, `_auto_row_height`,
  `_DEFAULT_ROW_H` in `svg_render.py` (no import needed)

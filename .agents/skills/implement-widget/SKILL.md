---
name: implement-widget
description: "Implement a widget's SVG template and Python context builder. Creates templates/{type}.svg.j2 and widgets/{type}.py with _build_{type}_context(). Follows TDD green phase — makes existing tests pass."
when_to_use: "When implementing the SVG template and context builder for a new widget type. Always run AFTER tests are written (TDD green phase)."
argument-hint: "[widget-type]"
arguments: widget-type
allowed-tools: Read, Edit, Write, Bash(uv *)
---

# Implement Widget Renderer: $widget-type

Implement the SVG template and Python context builder for **$widget-type**.
The output of this work is two artifacts:

1. `custom_components/eink_dashboard/templates/$widget-type.svg.j2`
2. `_build_$widget-type_context()` in `widgets/$widget-type.py`

## Before you start

1. Read the existing tests (`TestRender{WidgetName}` in
   `tests/test_render_{widget_type}.py`) — these define the expected
   behavior.
2. Read `const.py` for `WidgetType`, `COLOR_*` constants, `PADDING`,
   `DEFAULT_CARD_STYLE`, `Widget`, `DisplayConfig`, `color_to_hex`.
3. Read `svg_render.py` for the Jinja2 environment, `_svg_to_png()`,
   icon filter functions (`_mdi_svg_filter`, `_weather_svg_filter`),
   and `_SVG_RENDERERS`.
4. Read existing widget modules in `widgets/` (e.g. `widgets/tile.py`)
   for the context builder pattern, and `widgets/_helpers.py` for
   shared layout helpers.
5. Read `templates/_macros.svg.j2` for the three shared macros:
   `card_container`, `card_row`, `chip`.

## Current SVG infrastructure (svg_render.py)

!`grep -n "^def \|^_SVG_RENDERERS\|^_jinja_env\|^_TEMPLATE_DIR\|^_FONTS_DIR\|^_mdi\|^_weather" custom_components/eink_dashboard/svg_render.py`

## Shared layout helpers (widgets/_helpers.py)

!`grep -n "^def \|^_ACTIVE" custom_components/eink_dashboard/widgets/_helpers.py`

## Existing widget context builders

!`grep -rn "^def _build_" custom_components/eink_dashboard/widgets/*.py`

## SVG macro signatures

!`grep -n "macro card_container\|macro card_row\|macro chip\|macro icon_circle" custom_components/eink_dashboard/templates/_macros.svg.j2`

## WidgetMetrics and _compute_metrics (in render.py)

!`grep -n "^class WidgetMetrics" -A 10 custom_components/eink_dashboard/render.py`

!`grep -n "^def _compute_metrics" -A 12 custom_components/eink_dashboard/render.py`

## Icon name resolver (in render.py)

!`grep -n "^def _device_class_icon" -A 6 custom_components/eink_dashboard/render.py`

## Current SVG renderer registry

!`grep -n "_SVG_RENDERERS" -A 12 custom_components/eink_dashboard/svg_render.py`

## Imports

Context builders live in `widgets/{type}.py` and use relative
imports.  `_compute_metrics`, `_device_class_icon`, and `_load_font`
live in `render.py`.  `color_to_hex`, `Widget`, `DisplayConfig`,
and constants live in `const.py`.  Layout helpers live in
`widgets/_helpers.py`.

```python
from ..const import (
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ..render import (
    _compute_metrics,
    _device_class_icon,
    _load_font,        # chip width measurement only
)
from ..svg_render import _mdi_svg_filter
from ._helpers import (
    _auto_row_height,
    _card_insets,
    _color_context,
    _fmt,
    _metrics_context,
    _widget_dim,
)
```

Use `_fmt(state_val, config)` whenever a context builder formats a
numeric entity state for display.  This applies locale-aware decimal
and thousands separators matching the owner's HA preference.  Pass
the raw state string — non-numeric strings (``"on"``, ``"unavailable"``)
are returned unchanged.

`_color_context()` in `widgets/_helpers.py` returns
`{"hex_black": ..., "hex_white": ..., "hex_gray": ...}` by calling
`color_to_hex()` on the `const.py` integer constants.  Spread it into
the context dict with `**_color_context()` so templates can use
`{{ hex_gray }}` instead of hardcoded hex literals.

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
  set). `primary` is the entity label; `secondary` is the state +
  unit. Pass `lpad`/`rpad` derived from `_card_insets()` to prevent
  double-padding when a card style already provides insets; use the
  same values for `x1`/`x2` of any divider `<line>` between rows.
  Pass `icon_no_circle=True` when `icon_style == "none"` — the macro
  hides the circle but still renders the icon glyph.
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

Widget SVGs are composited onto a white canvas using the alpha
channel as a mask (`render_dashboard()` in `render.py`).  Transparent
pixels preserve whatever is already on the canvas (white by default),
so most templates do **not** need a white background rect.

Add a full-viewport white background rect **only** when the template's
rendered geometry is smaller than its SVG viewport — i.e. when content
does not fill `w` × `h`.  The separator is the canonical example: its
bar (`bar_w` × `bar_h`) is much smaller than the widget viewport, so
surrounding transparent area would let earlier widget content bleed
through without the rect.

Card-style and chip-style templates omit the rect because the card
chrome (via `card_container`) or chip flow covers the meaningful area,
and any remaining transparent edge pixels are harmless (canvas is
white).

**Card-style template pattern** (tile, waste_schedule):

```jinja
{%- from "_macros.svg.j2" import card_container, card_row -%}
<svg xmlns="http://www.w3.org/2000/svg"
     width="{{ w }}" height="{{ h }}">
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
    letter=row.letter,
    lpad=lpad, rpad=rpad) }}
{%- if not loop.last -%}
<line
  x1="{{ x_off + lpad }}"
  y1="{{ row.y + row_h }}"
  x2="{{ w - r_inset - rpad }}"
  y2="{{ row.y + row_h }}"
  stroke="{{ hex_gray }}" stroke-width="{{ m.divider }}"/>
{%- endif -%}
{%- endfor -%}
{%- endcall -%}
</svg>
```

**Chip-style template pattern** (device_battery):

```jinja
{%- from "_macros.svg.j2" import chip -%}
<svg xmlns="http://www.w3.org/2000/svg"
     width="{{ w }}" height="{{ h }}">
{%- for c in chips -%}
{{ chip(
    x=c.x, y=c.y, w=c.w, h=chip_h,
    text=c.text, border=m.border,
    icon_svg=c.icon_svg,
    inverted=c.inverted) }}
{%- endfor -%}
</svg>
```

**Simple template pattern** (separator):

When rendered geometry (e.g. a bar or line) is smaller than the SVG
viewport, include a full-size white rect before it so the surrounding
area is not transparent:

```jinja
<svg xmlns="http://www.w3.org/2000/svg"
     width="{{ w }}" height="{{ h }}">
<rect width="{{ w }}" height="{{ h }}" fill="{{ hex_white }}"/>
<!-- widget-specific SVG elements here -->
</svg>
```

Template coordinates are relative to origin (0, 0) — the outer
composition handles absolute `x`/`y` placement on the dashboard.

### 3. Write the context builder

Create `widgets/$widget-type.py` with
`_build_$widget-type_context(widget, config) -> dict`. The context
builder:

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
            "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
            "rows": [],
        }
    # Row-based: auto-size height to fit n rows at
    # DEFAULT_ROW_H px each.  An explicit "h" overrides this.
    h = _widget_dim(widget, "h", _auto_row_height(title, n))
    row_h = h // n
    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(
        m, card_style, grayscale_levels
    )
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    rows: list[dict[str, object]] = []
    for i, entity_id in enumerate(entities):
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        domain = entity_id.split(".")[0]
        # Resolve icon: device_class → attrs["icon"] → letter.
        icon_name = _device_class_icon(
            attrs, state["state"], domain
        )
        if icon_name is None:
            raw = attrs.get("icon", "")
            if raw.startswith("mdi:"):
                icon_name = raw[4:]
        # Call filter in Python; suppress missing-icon errors.
        icon_svg: markupsafe.Markup | str = ""
        if icon_name:
            with contextlib.suppress(FileNotFoundError):
                icon_svg = _mdi_svg_filter(
                    icon_name, m.icon_inner
                )
        letter = ""
        if not icon_svg:
            friendly = attrs.get("friendly_name", entity_id)
            letter = friendly[:1].upper() if friendly else ""
        unit = attrs.get("unit_of_measurement", "")
        state_val = state["state"]
        rows.append({
            "y": i * row_h,
            "primary": attrs.get(
                "friendly_name", entity_id
            ),
            "secondary": f"{_fmt(state_val, config)}{unit}",
            "value": "",
            "icon_svg": icon_svg,
            "letter": letter,
        })
    return {
        "w": w,
        "h": h,
        "card_style": card_style,
        "grayscale_levels": grayscale_levels,
        "rows": rows,
        "row_h": row_h,
        "lpad": lpad,
        "rpad": rpad,
        **_metrics_context(m),
        **_color_context(),
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
    h = _widget_dim(widget, "h", DEFAULT_ROW_H)
    entities = widget.get("entities", [])
    states = config.get("states", {})
    m = _compute_metrics(h)

    # pad, icon_gap, and font_sz are chip-specific ratios;
    # icon_dia and icon_inner come from _compute_metrics() so
    # they match card_row at the same height.
    pad = round(h * 0.18)
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
        if icon_name is None:
            raw = attrs.get("icon", "")
            if raw.startswith("mdi:"):
                icon_name = raw[4:]
        icon_svg: markupsafe.Markup | str = ""
        if icon_name:
            with contextlib.suppress(FileNotFoundError):
                icon_svg = _mdi_svg_filter(
                    icon_name, m.icon_inner
                )
        label = attrs.get("friendly_name", entity_id)
        text_w = round(font.getlength(label))
        icon_w = (m.icon_dia + icon_gap) if icon_svg else 0
        chip_w = pad + icon_w + text_w + pad
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

### 4. Re-export from widgets/__init__.py

In `widgets/__init__.py`, add the import and `__all__` entry:

```python
from .{widget_type} import _build_{widget_type}_context

__all__ = [
    ...
    "_build_{widget_type}_context",
]
```

### 5. Register in _SVG_RENDERERS

In `svg_render.py`, import from `widgets` and add to the
`_SVG_RENDERERS` dict:

```python
from .widgets import _build_{widget_type}_context

_SVG_RENDERERS: dict[str, SvgContextFn] = {
    ...
    WidgetType.{WIDGET_TYPE}: _build_{widget_type}_context,
}
```

### 6. Run tests

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
- **Chip proportions from `WidgetMetrics`.** `icon_dia` and
  `icon_inner` come from `_compute_metrics(chip_h)` — do not
  derive them from inline ratios or `_CHIP_*_RATIO` constants
  (removed in step 0.5).  `pad`, `icon_gap`, and `font_sz` are
  chip-specific and have no `WidgetMetrics` field.
- **Use shared macros.** Do not duplicate card/chip/row SVG markup.
  Use `card_container`, `card_row`, `chip` from `_macros.svg.j2`.
- **All layout math in Python.** Templates receive final coordinates
  and data. No arithmetic or conditionals in Jinja2 beyond what the
  macros already compute internally.
- **White background rect.** Only add
  `<rect width="{{ w }}" height="{{ h }}" fill="{{ hex_white }}"/>`
  when the template's rendered geometry is smaller than its SVG
  viewport (e.g. separator bar).  Card-style and chip-style templates
  omit it — the canvas is pre-filled white and alpha masking handles
  compositing.
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
- Layout helpers: `_widget_dim`, `_auto_row_height`,
  `_card_insets`, `_metrics_context`, `_color_context`, `_fmt`,
  `_entity_info_context`, `_title_layout` in `widgets/_helpers.py`
- Constants: `DEFAULT_ROW_H`, `Widget`, `DisplayConfig`,
  `color_to_hex` in `const.py`
- Icon style pattern: `_ACTIVE_STATES` frozenset (in
  `widgets/_helpers.py`) determines active vs inactive state; use
  `contextlib.suppress(FileNotFoundError)` around every
  `_mdi_svg_filter()` call
- **Custom icon circle**: When a widget renders its own icon circle
  (not via the `card_row` macro), use the `icon_circle` macro from
  `_macros.svg.j2` — it handles filled/outlined/no-circle variants
  and glyph/letter rendering.  The context builder must pass
  `icon_cx`, `icon_cy`, `icon_r`, `icon_glyph_x`, `icon_glyph_y`,
  `icon_stroke_w`, `icon_fill`, `icon_color`, `icon_svg`,
  `icon_outline`, `icon_no_circle`, `letter`, and
  `letter_font_sz` to the template.  Widen the outline stroke on
  2-level displays to avoid dithering — compute this in the context
  builder and pass it as `icon_stroke_w`:

  ```python
  # Widen the outline stroke on 2-level displays.
  icon_stroke_w = (
      m.border * 3 if grayscale_levels <= 2 else m.border
  )
  ```

  The `card_row` macro handles this widening internally for row
  icons.  Only apply it explicitly when using `icon_circle` directly.

# Copyright 2026 Andreas Schneider
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared layout helpers for widget SVG context builders.

Functions in this module compute dimensions, colors, and template
context dicts used by multiple widget types.  They were extracted
from ``svg_render.py`` so that widget modules import layout helpers
from a sibling rather than reaching back into the rendering pipeline.

Lazy imports from ``render`` inside function bodies avoid circular
dependencies: ``render.py`` → ``svg_render.py`` → ``widgets/`` →
``_helpers.py`` → ``render.py`` would deadlock at module level.
"""

from __future__ import annotations

import contextlib
import functools
from dataclasses import dataclass
from dataclasses import fields as dc_fields
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import markupsafe

    from ..render import WidgetMetrics

from ..const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    COLOR_WHITE,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ..svg_render import _mdi_svg_filter

# Entity states treated as "active" for the filled circle
# indicator.  Covers binary_sensor/switch ("on"), cover ("open"),
# person ("home"), media_player ("playing"), sun ("above_horizon").
# Sensor entities with numeric states never match and always render
# as outlined.
_ACTIVE_STATES: frozenset[str] = frozenset(
    {"on", "open", "home", "playing", "above_horizon"}
)


def _title_layout(
    title: str,
    svg_h: int,
) -> tuple[int, int, int]:
    """Return (title_font_sz, content_y, content_h) for a titled widget.

    When ``title`` is non-empty, reserves vertical space above the
    card content area for the label.  Font size and advance are
    proportional to ``svg_h`` so the title scales with the widget.

    Args:
        title: Widget title string.  Empty string means no title.
        svg_h: Total widget height in pixels.

    Returns:
        ``(title_font_sz, content_y, content_h)`` where
        ``title_font_sz`` is 0 when ``title`` is empty,
        ``content_y`` is the top of the card area (below the
        title, or 0 when ``title`` is empty), and
        ``content_h`` is the remaining height.
    """
    if not title:
        return 0, 0, svg_h
    font_sz = max(10, round(svg_h * 0.14))
    advance = round(font_sz * 1.4)
    return font_sz, advance, svg_h - advance


def _metrics_context(m: WidgetMetrics) -> dict[str, object]:
    """Return all metric fields for a Jinja2 template context.

    Serialises every ``WidgetMetrics`` field into a ``m_``-prefixed
    dict so templates can reference any metric without the Python
    context builder having to cherry-pick individual fields.

    Args:
        m: ``WidgetMetrics`` dataclass from ``_compute_metrics``.

    Returns:
        Dict with ``m_*`` keys for every ``WidgetMetrics`` field,
        ready to unpack into a template context dict.
    """
    return {f"m_{f.name}": getattr(m, f.name) for f in dc_fields(m)}


@functools.cache
def _color_context() -> dict[str, str]:
    """Return color hex variables for Jinja2 templates.

    Converts the ``const.py`` grayscale constants to SVG hex
    strings via ``color_to_hex()``.  Spread into every context
    builder so templates can reference colors by name (e.g.
    ``{{ hex_gray }}``) instead of hardcoding hex literals.

    The result is constant and cached; callers spread it via
    ``**_color_context()`` so the shared dict is never mutated.

    Returns:
        Dict mapping ``hex_black``, ``hex_white``,
        ``hex_gray``, and ``hex_light_gray`` to their
        SVG hex color strings.
    """
    return {
        "hex_black": color_to_hex(COLOR_BLACK),
        "hex_white": color_to_hex(COLOR_WHITE),
        "hex_gray": color_to_hex(COLOR_GRAY),
        "hex_light_gray": color_to_hex(COLOR_LIGHT_GRAY),
    }


# Temperature (°C) -> RGB color stops, sorted ascending by
# temperature.  Shared by the weather widget's today min/max bar
# and (eventually) the meteogram's temperature curve, so both use
# the same color language for the same reading.
_TEMP_GRADIENT: list[tuple[float, tuple[int, int, int]]] = [
    (-20, (0, 60, 98)),
    (-10, (120, 162, 204)),
    (0, (164, 195, 210)),
    (10, (121, 210, 179)),
    (20, (252, 245, 112)),
    (30, (255, 150, 79)),
    (40, (255, 192, 159)),
]


def _temp_to_rgb(temp: float) -> tuple[int, int, int]:
    """Map a temperature to an RGB color via linear interpolation.

    Temperatures outside ``_TEMP_GRADIENT``'s range clamp to the
    nearest end color.

    Args:
        temp: Temperature in Celsius.

    Returns:
        ``(r, g, b)`` tuple, each in ``0..255``.
    """
    stops = _TEMP_GRADIENT
    if temp <= stops[0][0]:
        return stops[0][1]
    if temp >= stops[-1][0]:
        return stops[-1][1]
    for (t0, c0), (t1, c1) in pairwise(stops):
        if t0 <= temp <= t1:
            frac = (temp - t0) / (t1 - t0)
            return (
                round(c0[0] + (c1[0] - c0[0]) * frac),
                round(c0[1] + (c1[1] - c0[1]) * frac),
                round(c0[2] + (c1[2] - c0[2]) * frac),
            )
    return stops[-1][1]


def _temp_gradient_stops(values: list[float]) -> list[dict[str, str]]:
    """Compute SVG linearGradient stop entries from temperatures.

    Each value maps to an evenly-spaced offset (``"0.00%"`` for the
    first entry, ``"100.00%"`` for the last) and a color from
    ``_temp_to_rgb()``.  Mirrors the ``{"offset": ..., "color":
    ...}`` shape ``graph.py``'s ``_threshold_gradient_stops()``
    returns, so templates can loop over either the same way.

    Args:
        values: Temperatures sampled at even intervals across the
            gradient's extent.  Must have at least two entries.

    Returns:
        List of ``{"offset": "XX.XX%", "color": "#hex"}`` dicts,
        ordered start to end of the gradient.

    Raises:
        ValueError: If ``values`` has fewer than two entries.
    """
    if len(values) < 2:
        raise ValueError(f"values must have >= 2 entries, got {len(values)}")
    n = len(values) - 1
    stops: list[dict[str, str]] = []
    for i, temp in enumerate(values):
        r, g, b = _temp_to_rgb(temp)
        stops.append(
            {
                "offset": f"{i / n * 100:.2f}%",
                "color": f"#{r:02x}{g:02x}{b:02x}",
            }
        )
    return stops


def _fmt(value: str, config: DisplayConfig) -> str:
    """Format a numeric string using the locale settings in ``config``.

    Non-numeric strings pass through unchanged.  Extracts
    ``number_format`` and ``language`` from the config dict and
    delegates to :func:`~render.format_number`.

    Args:
        value: Numeric string (e.g. ``"8.41"``).
        config: Display config dict containing ``number_format`` and
            ``language`` keys.

    Returns:
        Locale-formatted string, or ``value`` unchanged if not
        numeric.
    """
    from ..render import format_number

    return format_number(
        value,
        config.get("number_format", "language"),
        config.get("language", "en"),
    )


def _card_insets(
    m: WidgetMetrics,
    card_style: str,
    display_levels: int,
) -> tuple[int, int, int]:
    """Return (x_off, r_inset, bar_width) for a card container.

    The ``card_container`` macro in ``_macros.svg.j2`` is purely
    decorative; all content positioning uses these insets computed
    in Python.  ``bar_width`` is the pre-computed left-bar width
    (including 2-level widening) so the macro never recalculates
    it — Python is the single source of truth.

    Args:
        m: ``WidgetMetrics`` dataclass from ``_compute_metrics``.
        card_style: One of ``"border"``, ``"left_bar"``, or
            ``"none"`` (or any other value treated as ``"none"``).
        display_levels: Display grayscale depth; passed to
            ``_left_bar_width`` to widen the bar on 2-level
            displays.

    Returns:
        ``(x_off, r_inset, bar_width)`` — the left and right
        pixel insets for the content area inside the card frame,
        and the rendered bar width (0 when not ``"left_bar"``).
    """
    from ..render import _left_bar_width

    if card_style == "border":
        return m.padding, m.padding, 0
    if card_style == "left_bar":
        bar_w = _left_bar_width(m, display_levels)
        return bar_w + m.padding, 0, bar_w
    return 0, 0, 0


def _resolve_icon_style(
    icon_style: str | None,
    state_val: str = "",
    display_levels: int = 16,
) -> tuple[bool, bool]:
    """Resolve icon circle style to outline/no-circle flags.

    When ``icon_style`` is ``None`` the style is chosen
    automatically: 2-level displays always use ``"outlined"``
    (maximum contrast); multi-level displays switch to
    ``"filled"`` for active entities and fall back to
    ``"outlined"`` otherwise.

    Args:
        icon_style: Explicit style override (``"filled"``,
            ``"outlined"``, ``"none"``), or ``None`` for
            automatic selection based on entity state.
        state_val: Entity state string used for active
            detection when ``icon_style`` is ``None``.
            Defaults to ``""`` (treated as inactive).
        display_levels: Display grayscale depth.  Values
            of 2 or fewer force ``"outlined"`` regardless
            of state.

    Returns:
        ``(icon_outline, icon_no_circle)`` — boolean flags
        consumed by the SVG template.
    """
    if icon_style is None:
        is_active = state_val in _ACTIVE_STATES
        resolved = (
            "outlined"
            if display_levels <= 2
            else ("filled" if is_active else "outlined")
        )
    else:
        resolved = icon_style
    return resolved == "outlined", resolved == "none"


def _resolve_icon_svg(
    icon_override: str | None,
    attrs: dict[str, object],
    state_val: str,
    domain: str,
    size: int,
    entity_id: str = "",
) -> tuple[markupsafe.Markup | str, str]:
    """Resolve an MDI icon SVG and letter fallback for an entity.

    Walks the icon resolution chain in priority order:

    1. **Explicit override** — ``icon_override`` is not ``None``.
       Strips the ``mdi:`` prefix when present and passes the
       bare name to ``_mdi_svg_filter``.  Values without the
       prefix are passed as-is.  When ``icon_override`` is set
       the remaining steps (2–3) are **never tried**.  If the
       override icon cannot be found, the function falls through
       to step 4 (letter fallback).
    2. **Device-class icon** — looked up via
       ``_device_class_icon(attrs, state_val, domain)``.
    3. **Entity icon attribute** — ``attrs["icon"]`` when it
       carries an ``mdi:`` prefix.
    4. **Letter fallback** — first character of ``friendly_name``
       (or ``entity_id``) uppercased.  Skipped when ``entity_id``
       is empty.

    Callers that only want to honour ``mdi:``-prefixed overrides
    (e.g. heading badges) must normalise non-``mdi:`` values to
    ``None`` before calling, so the chain falls through to
    device_class resolution instead of stopping at step 1.

    Args:
        icon_override: MDI icon name with optional ``mdi:``
            prefix, or ``None`` when no override is configured.
            Any non-``None`` value blocks steps 2–3.
        attrs: Entity ``attributes`` dict from the HA state.
        state_val: Entity state string (e.g. ``"on"``,
            ``"22.1"``).
        domain: HA entity domain (e.g. ``"sensor"``,
            ``"binary_sensor"``).
        size: Icon glyph size in pixels passed to
            ``_mdi_svg_filter``.
        entity_id: Full entity ID used for the letter fallback.
            Empty string suppresses the fallback.

    Returns:
        ``(icon_svg, letter)`` where ``icon_svg`` is an inline
        SVG ``Markup`` string (empty when no icon resolves) and
        ``letter`` is the uppercase first character of the
        friendly name (empty when an icon was found or when
        ``entity_id`` is empty).
    """
    from ..render import _device_class_icon

    icon_svg: markupsafe.Markup | str = ""
    if icon_override is not None:
        icon_name = str(icon_override)
        if icon_name.startswith("mdi:"):
            icon_name = icon_name[4:]
        with contextlib.suppress(FileNotFoundError, ValueError):
            icon_svg = _mdi_svg_filter(icon_name, size)
    else:
        resolved = _device_class_icon(attrs, state_val, domain)
        if resolved is None:
            raw = attrs.get("icon", "")
            if isinstance(raw, str) and raw.startswith("mdi:"):
                resolved = raw[4:]
        if resolved:
            with contextlib.suppress(FileNotFoundError, ValueError):
                icon_svg = _mdi_svg_filter(resolved, size)

    letter = ""
    if not icon_svg and entity_id:
        friendly = attrs.get("friendly_name", entity_id)
        letter = str(friendly)[:1].upper() if friendly else ""
    return icon_svg, letter


def _widget_dim(widget: Widget, key: str, fallback: int) -> int:
    """Return a widget dimension, clamped to >= 1.

    Uses the explicit ``widget[key]`` value when present,
    otherwise ``fallback``.  The clamp avoids zero-area SVG
    viewports that would crash resvg.

    Args:
        widget: Widget config dict.
        key: Dimension key (``"w"`` or ``"h"``).
        fallback: Default when ``key`` is absent from
            ``widget``.

    Returns:
        Dimension in pixels, >= 1.
    """
    return max(1, widget.get(key, fallback))


def _auto_row_height(
    title: str,
    num_rows: int,
    row_h: int = DEFAULT_ROW_H,
    *,
    content_target: int | None = None,
) -> int:
    """Compute natural widget height from content row count.

    Returns a height such that when ``_title_layout(title, result)``
    is called the resulting ``content_h`` equals ``target`` (within
    1 px rounding), where ``target`` defaults to
    ``num_rows * row_h``.  When ``title`` is empty, returns
    ``target`` directly.

    Used as the fallback for ``_widget_dim`` so row-based widgets
    size to their content instead of filling the remaining canvas.

    Args:
        title: Widget title string.  Empty means no title.
        num_rows: Number of content rows to accommodate.
            Must be at least 1.
        row_h: Target height per content row in pixels.
        content_target: Override for the default ``num_rows *
            row_h`` target content height.  Used by widgets with
            heterogeneous row types (e.g. entities with dividers
            and sections) where the total height is not a simple
            multiple of ``row_h``.

    Returns:
        Total widget height in pixels.
    """
    if num_rows < 1:
        raise ValueError(f"num_rows must be >= 1, got {num_rows}")
    target = content_target if content_target is not None else num_rows * row_h
    if not title:
        return target
    # _title_layout subtracts an advance from svg_h, creating a
    # dependency: advance depends on svg_h.  Iterate to find the
    # fixpoint.  round() in _title_layout creates a 1-px staircase
    # that can cause a 1-step oscillation, so 3 iterations (not 2)
    # guarantee convergence to within ±1 px of target.
    svg_h = target
    for _ in range(3):
        _, _, content_h = _title_layout(title, svg_h)
        svg_h = svg_h + (target - content_h)
    return svg_h


@dataclass(frozen=True, slots=True)
class EntityTextGeometry:
    """Computed font sizes and positions for entity name/value/unit text.

    Attributes:
        name_font_sz: Font size for the entity name label.
        name_x: X coordinate for the name text anchor.
        name_y: Y coordinate for the name text anchor.
        value_font_sz: Font size for the state value.
        value_x: X coordinate for the value text anchor.
        value_y: Y coordinate for the value text anchor.
        unit_font_sz: Font size for the unit label.
        unit_x: X coordinate for the unit text anchor.
        unit_y: Y coordinate for the unit text anchor.
    """

    name_font_sz: int
    name_x: int
    name_y: int
    value_font_sz: int
    value_x: int
    value_y: int
    unit_font_sz: int
    unit_x: int
    unit_y: int


def _entity_text_geometry(
    m: WidgetMetrics,
    header_h: int,
    info_h: int,
    section_h: int,
    x_off: int,
    lpad: int,
    *,
    value_text: str,
    unit_text: str,
    value_bold: bool,
) -> EntityTextGeometry:
    """Compute name/value/unit font sizes and positions.

    Isolated from icon resolution and card-inset computation so the
    text layout math can be swapped independently without touching
    the rest of ``_entity_info_context()``, the header+info layout
    shared by the Sensor and Graph widget builders.

    Args:
        m: ``WidgetMetrics`` dataclass from ``_compute_metrics``.
        header_h: Height of the header row in pixels.
        info_h: Height of the info section in pixels.
        section_h: Total height of the header + info sections.
        x_off: Left content inset (card border/bar width).
        lpad: Additional left padding when ``x_off`` is 0.
        value_text: Rendered value string, used to measure the
            value's on-screen width so the unit can be placed
            immediately to its right.
        unit_text: Rendered unit string. Empty string means no
            unit is shown, and ``unit_x`` falls back to
            ``value_x``.
        value_bold: Whether the value is rendered in bold, which
            changes the font used for measuring ``value_text``.

    Returns:
        ``EntityTextGeometry`` with font sizes and positions for
        the name, value, and unit text elements.
    """
    from ..render import _load_font

    name_font_sz = max(10, round(header_h * 0.32))
    name_x = x_off + lpad
    name_y = header_h // 2

    value_font_sz = max(10, round(section_h * 0.38))
    value_x = x_off + lpad
    value_y = header_h + round(info_h * 0.65)

    unit_font_sz = m.font_secondary
    unit_x = value_x
    if unit_text:
        value_font = _load_font(
            value_font_sz, medium=not value_bold, bold=value_bold
        )
        text_w = round(value_font.getlength(value_text))
        unit_x = value_x + text_w + m.inner_gap // 2

    return EntityTextGeometry(
        name_font_sz=name_font_sz,
        name_x=name_x,
        name_y=name_y,
        value_font_sz=value_font_sz,
        value_x=value_x,
        value_y=value_y,
        unit_font_sz=unit_font_sz,
        unit_x=unit_x,
        unit_y=value_y,
    )


def _entity_info_context(
    widget: Widget,
    config: DisplayConfig,
    section_h: int,
    svg_w: int,
    svg_h: int,
    *,
    attribute: str | None = None,
) -> dict[str, object] | None:
    """Build shared icon/name/value/unit context for entity-like widgets.

    Handles the common header + info section layout shared by the
    Sensor and Graph widget builders.  Returns ``None`` when the
    entity is missing from the state dict; callers emit a white-canvas
    fallback in that case.

    Args:
        widget: Widget config dict.  Recognised keys: ``entity``,
            ``name``, ``icon``, ``unit``, ``hide_icon``,
            ``hide_name``, ``icon_style``, ``card_style``,
            ``bold_value``.
        config: Display config with ``states`` and
            ``display_levels``.
        section_h: Height of the entity info section in pixels.
            Sensor widget passes ``entity_h`` (svg_h minus
            graph_h); Graph widget passes ``header_h``.
        svg_w: Full widget width in pixels.
        svg_h: Full widget height in pixels.
        attribute: Optional HA attribute key.  When set, the
            attribute value is shown instead of the entity state,
            and automatic ``unit_of_measurement`` is suppressed.

    Returns:
        Template context dict with icon geometry, header text, info
        section value/unit, card style, metrics, and colors.
        Returns ``None`` when the entity is missing from states.
    """
    from ..render import _compute_metrics

    entity_id: str = widget.get("entity", "")
    name_override = widget.get("name")
    icon_override = widget.get("icon")
    unit_override = widget.get("unit")
    hide_icon: bool = widget.get("hide_icon", False)
    hide_name: bool = widget.get("hide_name", False)
    icon_style = widget.get("icon_style")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    value_bold: bool = widget.get("bold_value", False)
    states = config.get("states", {})
    display_levels = config.get("display_levels", 16)

    state = states.get(entity_id) if entity_id else None
    if state is None:
        return None

    colors = _color_context()
    # Header takes 40% of section_h; info section takes the rest.
    header_h = round(section_h * 0.40)
    info_h = section_h - header_h
    # Metrics derived from header height — icon and name live in
    # the header row, so proportions (icon size, padding, font)
    # should scale with that section, not the full widget.
    m = _compute_metrics(header_h)
    # Entity header icon uses larger ratios than standard metrics because
    # the header is only 40% of the widget height — the default 0.64
    # circle / 60% glyph ratios produce an icon too small to read on
    # e-ink at default widget size.
    icon_dia = round(header_h * 0.82)
    icon_inner = icon_dia * 70 // 100
    letter_font_sz = icon_dia * 5 // 10
    x_off, r_inset, bar_width = _card_insets(m, card_style, display_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    attrs = state.get("attributes", {})
    domain = entity_id.split(".")[0]
    state_val: str = state.get("state", "")

    name_text: str = (
        str(name_override)
        if name_override is not None
        else attrs.get("friendly_name", entity_id)
    )

    # Value: show attribute value when requested, else entity state.
    if attribute is not None:
        raw_val = attrs.get(attribute)
        value_text = (
            _fmt(str(raw_val), config)
            if raw_val is not None and raw_val != ""
            else "unknown"
        )
        auto_unit = ""
    else:
        value_text = _fmt(state_val, config)
        auto_unit = attrs.get("unit_of_measurement", "")
    unit_text: str = (
        str(unit_override) if unit_override is not None else auto_unit
    )

    # Icon resolution: explicit override → device_class → attrs icon.
    # Skipped entirely when hide_icon is set.
    if hide_icon:
        icon_svg: markupsafe.Markup | str = ""
        letter = ""
        icon_outline = False
        icon_no_circle = True
    else:
        icon_svg, letter = _resolve_icon_svg(
            icon_override,
            attrs,
            state_val,
            domain,
            icon_inner,
            entity_id,
        )
        icon_outline, icon_no_circle = _resolve_icon_style(
            icon_style, state_val, display_levels
        )
    # Widen outline stroke on 2-level displays to avoid dithering.
    icon_stroke_w = m.border * 3 if display_levels <= 2 else m.border
    icon_fill = color_to_hex(COLOR_GRAY)
    icon_color = (
        colors["hex_black"]
        if (icon_outline or icon_no_circle)
        else colors["hex_white"]
    )

    # Icon: right-aligned in header row.
    icon_r = icon_dia // 2
    icon_cx = svg_w - r_inset - rpad - icon_r
    # Mirror the right inset vertically so the circle has the same
    # gap from the card border at the top as it does on the right.
    # When there is no border (r_inset == 0), centre in the header.
    icon_cy = r_inset + icon_r if r_inset else header_h // 2
    icon_glyph_x = icon_cx - icon_inner // 2
    icon_glyph_y = icon_cy - icon_inner // 2

    # Name left-aligned in header row, value left-aligned with baseline
    # at ~65% of the info section, unit positioned right of the value.
    # See _entity_text_geometry() for the exact ratios.
    geo = _entity_text_geometry(
        m,
        header_h,
        info_h,
        section_h,
        x_off,
        lpad,
        value_text=value_text,
        unit_text=unit_text,
        value_bold=value_bold,
    )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_entity": True,
        "card_style": card_style,
        "bar_width": bar_width,
        **_metrics_context(m),
        **colors,
        # Icon geometry.
        "icon_svg": icon_svg,
        "icon_cx": icon_cx,
        "icon_cy": icon_cy,
        "icon_r": icon_r,
        "icon_stroke_w": icon_stroke_w,
        "icon_fill": icon_fill,
        "icon_color": icon_color,
        "icon_outline": icon_outline,
        "icon_no_circle": icon_no_circle,
        "icon_glyph_x": icon_glyph_x,
        "icon_glyph_y": icon_glyph_y,
        "letter": letter,
        "letter_font_sz": letter_font_sz,
        # Header row text.
        "hide_name": hide_name,
        "name_text": name_text,
        "name_x": geo.name_x,
        "name_y": geo.name_y,
        "name_font_sz": geo.name_font_sz,
        # Info section.
        "value_text": value_text,
        "value_x": geo.value_x,
        "value_y": geo.value_y,
        "value_font_sz": geo.value_font_sz,
        "value_bold": value_bold,
        "unit_text": unit_text,
        "unit_x": geo.unit_x,
        "unit_y": geo.unit_y,
        "unit_font_sz": geo.unit_font_sz,
    }

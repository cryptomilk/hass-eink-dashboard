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
from dataclasses import fields as dc_fields
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
    from ..render import color_to_hex

    return {
        "hex_black": color_to_hex(COLOR_BLACK),
        "hex_white": color_to_hex(COLOR_WHITE),
        "hex_gray": color_to_hex(COLOR_GRAY),
        "hex_light_gray": color_to_hex(COLOR_LIGHT_GRAY),
    }


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
    grayscale_levels: int,
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
        grayscale_levels: Display grayscale depth; passed to
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
        bar_w = _left_bar_width(m, grayscale_levels)
        return bar_w + m.padding, 0, bar_w
    return 0, 0, 0


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
    Entity and Sensor widget builders.  Returns ``None`` when the
    entity is missing from the state dict; callers emit a white-canvas
    fallback in that case.

    Args:
        widget: Widget config dict.  Recognised keys: ``entity``,
            ``name``, ``icon``, ``unit``, ``icon_style``,
            ``card_style``.
        config: Display config with ``states`` and
            ``grayscale_levels``.
        section_h: Height of the entity info section in pixels.
            Entity widget passes ``svg_h``; Sensor widget passes
            ``entity_h`` (svg_h minus graph_h).
        svg_w: Full widget width in pixels.
        svg_h: Full widget height in pixels.
        attribute: Optional HA attribute key.  When set, the
            attribute value is shown instead of the entity state,
            and automatic ``unit_of_measurement`` is suppressed.
            Only the Entity widget passes a non-None value here.

    Returns:
        Template context dict with icon geometry, header text, info
        section value/unit, card style, metrics, and colors.
        Returns ``None`` when the entity is missing from states.
    """
    from ..render import (
        _compute_metrics,
        _device_class_icon,
        _load_font,
        color_to_hex,
    )

    entity_id: str = widget.get("entity", "")
    name_override = widget.get("name")
    icon_override = widget.get("icon")
    unit_override = widget.get("unit")
    icon_style = widget.get("icon_style")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

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
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
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
    icon_svg: markupsafe.Markup | str = ""
    if icon_override is not None:
        icon_name = str(icon_override)
        if icon_name.startswith("mdi:"):
            icon_name = icon_name[4:]
        with contextlib.suppress(FileNotFoundError):
            icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)
    else:
        resolved_name = _device_class_icon(attrs, state_val, domain)
        if resolved_name is None:
            raw = attrs.get("icon", "")
            if raw.startswith("mdi:"):
                resolved_name = raw[4:]
        if resolved_name:
            with contextlib.suppress(FileNotFoundError):
                icon_svg = _mdi_svg_filter(resolved_name, m.icon_inner)

    letter = ""
    if not icon_svg:
        friendly = attrs.get("friendly_name", entity_id)
        letter = friendly[:1].upper() if friendly else ""

    # Auto-resolve icon style: active → filled, else outlined.
    # 2-level displays always use outlined for readability.
    is_active = state_val in _ACTIVE_STATES
    if icon_style is None:
        resolved_style = (
            "outlined"
            if grayscale_levels <= 2
            else ("filled" if is_active else "outlined")
        )
    else:
        resolved_style = str(icon_style)

    icon_outline = resolved_style == "outlined"
    icon_no_circle = resolved_style == "none"
    # Widen outline stroke on 2-level displays to avoid dithering.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    icon_fill = color_to_hex(COLOR_GRAY)
    icon_color = (
        colors["hex_black"]
        if (icon_outline or icon_no_circle)
        else colors["hex_white"]
    )

    # Icon: right-aligned in header row.
    icon_r = m.icon_dia // 2
    icon_cx = svg_w - r_inset - rpad - icon_r
    icon_cy = header_h // 2
    icon_glyph_x = icon_cx - m.icon_inner // 2
    icon_glyph_y = icon_cy - m.icon_inner // 2

    # Name: left-aligned in header row, vertically centered.
    # Larger ratio than m.font_primary (0.32) — the entity name is
    # the card's primary label and should fill the header row.
    name_font_sz = round(header_h * 0.48)
    name_x = x_off + lpad
    name_y = header_h // 2

    # Value: left-aligned, baseline at ~65% of the info section so
    # the value and unit share an alphabetic baseline (HA style).
    value_font_sz = max(10, round(section_h * 0.28))
    value_x = x_off + lpad
    value_y = header_h + round(info_h * 0.65)

    # Unit: positioned to the right of the value text.
    unit_font_sz = m.font_secondary
    unit_x = value_x
    if unit_text:
        value_font = _load_font(value_font_sz, medium=True)
        text_w = round(value_font.getlength(value_text))
        unit_x = value_x + text_w + m.inner_gap // 2

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
        "letter_font_sz": m.font_letter,
        # Header row text.
        "name_text": name_text,
        "name_x": name_x,
        "name_y": name_y,
        "name_font_sz": name_font_sz,
        # Info section.
        "value_text": value_text,
        "value_x": value_x,
        "value_y": value_y,
        "value_font_sz": value_font_sz,
        "unit_text": unit_text,
        "unit_x": unit_x,
        "unit_y": value_y,
        "unit_font_sz": unit_font_sz,
    }

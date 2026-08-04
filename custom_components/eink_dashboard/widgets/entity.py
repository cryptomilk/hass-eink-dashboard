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

"""Entity widget context builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import markupsafe

from ..conditions import check_conditions
from ..const import (
    COLOR_GRAY,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    PADDING,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ._helpers import (
    _card_insets,
    _color_context,
    _fmt,
    _metrics_context,
    _resolve_icon_style,
    _resolve_icon_svg,
    _widget_dim,
)


def _build_entity_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the entity widget.

    Renders the icon left-aligned and vertically centered against
    the full widget height, the state value and unit (both black)
    to its right, and the entity name (gray, smaller) above or
    below the value+unit line. The icon is a secondary/decorative
    element next to the black value, so its non-filled states
    render gray rather than black — matching the name's weight.

    Icon style controls circle rendering, with automatic resolution
    based on entity state when ``icon_style`` is omitted:

    - ``"filled"`` — gray-filled circle, white glyph (default for
      active states when ``display_levels > 2``).
    - ``"outlined"`` — white circle with gray stroke, gray glyph
      (default for inactive states and all 2-level displays).
    - ``"none"`` — no circle; icon glyph rendered in gray.

    When ``invert_condition`` inverts the widget, the icon renders
    white on the solid black card regardless of style, matching the
    value/unit/name.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, required),
            ``name`` (display name override),
            ``icon`` (MDI icon name, e.g. ``"mdi:thermometer"``),
            ``hide_icon`` (suppress the icon; default ``False``),
            ``hide_name`` (suppress the entity name text; default
            ``False``),
            ``attribute`` (attribute key to show as value instead
            of state),
            ``unit`` (unit string override),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``),
            ``bold_value`` (render the state value in bold;
            default ``False``),
            ``name_position`` (``"top"`` / ``"bottom"``; default
            ``"bottom"`` — position of the name relative to the
            value+unit line),
            ``name_align`` (``"left"`` / ``"right"``; default
            ``"left"``),
            ``invert_condition`` (list of Lovelace condition dicts,
            same format as ``visibility``; when non-empty and all
            conditions are met the widget renders inverted — solid
            black card, white text/icon — as an e-ink "needs
            attention" signal),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``display_levels``.

    Returns:
        Template context dict consumed by ``entity.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing.
        Full context includes widget dimensions, card style,
        metrics, colors, icon geometry, value/unit/name text and
        geometry, and the ``invert`` flag.
    """
    from ..render import _compute_metrics, _load_font

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", 2 * DEFAULT_ROW_H)
    entity_id: str = widget.get("entity", "")
    name_override = widget.get("name")
    icon_override = widget.get("icon")
    unit_override = widget.get("unit")
    attribute: str | None = widget.get("attribute")
    hide_icon: bool = widget.get("hide_icon", False)
    hide_name: bool = widget.get("hide_name", False)
    icon_style = widget.get("icon_style")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    value_bold: bool = widget.get("bold_value", False)
    name_position = widget.get("name_position", "bottom")
    name_align = widget.get("name_align", "left")
    states = config.get("states", {})
    display_levels = config.get("display_levels", 16)

    state = states.get(entity_id) if entity_id else None
    if state is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            "invert": False,
            **_color_context(),
        }

    colors = _color_context()
    m = _compute_metrics(svg_h)
    # Icon geometry anchors to a single-row-equivalent height rather
    # than the full (2-row-tall) widget height, otherwise the icon
    # balloons far past the scale of the value/unit/name text next
    # to it — the widget only ever shows one icon, not one per row.
    m_icon = _compute_metrics(svg_h // 2)
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
            m_icon.icon_inner,
            entity_id,
        )
        icon_outline, icon_no_circle = _resolve_icon_style(
            icon_style, state_val, display_levels
        )
    # Widened on 2-level displays to avoid dithering, matching the
    # pattern other widgets use.
    icon_stroke_w = m_icon.border * 3 if display_levels <= 2 else m_icon.border
    icon_fill = color_to_hex(COLOR_GRAY)

    # Inverted "needs attention" signal: same condition format and
    # evaluator as `visibility`, but drives a solid black card with
    # white text/icon instead of hide/show.  `check_conditions([])`
    # returns True, so the emptiness check is required — an absent
    # or empty `invert_condition` must never invert the widget.  The
    # icon is forced to the flat, no-circle style so the glyph draws
    # cleanly on the black background.
    invert_condition = widget.get("invert_condition")
    invert = bool(invert_condition) and check_conditions(
        invert_condition, states
    )
    if invert:
        icon_no_circle = True
        icon_outline = False

    # Icon: left-aligned, vertically centered against the full
    # widget height (not a header sub-band). Sized off m_icon (see
    # above), not m, so it stays proportionate to the text next to it.
    icon_r = m_icon.icon_dia // 2
    icon_cx = x_off + lpad + icon_r
    icon_cy = svg_h // 2
    icon_glyph_x = icon_cx - m_icon.icon_inner // 2
    icon_glyph_y = icon_cy - m_icon.icon_inner // 2

    # Text column starts after the icon column, or — when the icon
    # is hidden — at a thin breathing margin rather than the icon's
    # full reserved padding, so the collapsed column visibly reclaims
    # the space instead of just shifting by the same padding amount.
    if hide_icon:
        text_x0 = x_off + m.border
    else:
        text_x0 = x_off + lpad + m_icon.icon_dia + m_icon.inner_gap
    text_x1 = svg_w - r_inset - rpad

    # Font ratios are expressed against the same single-row-equivalent
    # height as the icon (see m_icon above) so the value reads as a
    # headline number sized comparably to the icon next to it, not a
    # small caption dwarfed by it.
    row_ref = svg_h // 2
    value_font_sz = max(10, round(row_ref * 0.42))
    unit_font_sz = max(10, round(row_ref * 0.22))
    name_font_sz = max(10, round(row_ref * 0.20))

    # Value and name are stacked tightly (small line gap, mirroring
    # card_row's primary/secondary spacing) and the whole two-line
    # block is vertically centered in the widget, rather than pinned
    # to fixed fractions of svg_h — this keeps the gap between the
    # two lines minimal regardless of height.
    line_gap = max(2, round(svg_h * 0.04))
    if name_position == "top":
        block_h = name_font_sz + line_gap + value_font_sz
        top = (svg_h - block_h) // 2
        name_y = top + name_font_sz // 2
        value_y = top + name_font_sz + line_gap + value_font_sz
    else:
        block_h = value_font_sz + line_gap + name_font_sz
        top = (svg_h - block_h) // 2
        value_y = top + value_font_sz
        name_y = top + value_font_sz + line_gap + name_font_sz // 2

    value_x = text_x0
    unit_x = value_x
    if unit_text:
        value_font = _load_font(
            value_font_sz, medium=not value_bold, bold=value_bold
        )
        text_w = round(value_font.getlength(value_text))
        unit_gap = max(2, round(svg_h * 0.02))
        unit_x = value_x + text_w + unit_gap
    unit_y = value_y

    if name_align == "right":
        name_x = text_x1
        name_anchor = "end"
    else:
        name_x = text_x0
        name_anchor = "start"

    return {
        "w": svg_w,
        "h": svg_h,
        "has_entity": True,
        "card_style": card_style,
        "bar_width": bar_width,
        "invert": invert,
        **_metrics_context(m),
        **colors,
        # Icon geometry.
        "icon_svg": icon_svg,
        "icon_cx": icon_cx,
        "icon_cy": icon_cy,
        "icon_r": icon_r,
        "icon_stroke_w": icon_stroke_w,
        "icon_fill": icon_fill,
        "icon_outline": icon_outline,
        "icon_no_circle": icon_no_circle,
        "icon_glyph_x": icon_glyph_x,
        "icon_glyph_y": icon_glyph_y,
        "letter": letter,
        "letter_font_sz": m_icon.font_letter,
        # Value + unit.
        "value_text": value_text,
        "value_x": value_x,
        "value_y": value_y,
        "value_font_sz": value_font_sz,
        "value_bold": value_bold,
        "unit_text": unit_text,
        "unit_x": unit_x,
        "unit_y": unit_y,
        "unit_font_sz": unit_font_sz,
        # Name.
        "hide_name": hide_name,
        "name_text": name_text,
        "name_x": name_x,
        "name_y": name_y,
        "name_font_sz": name_font_sz,
        "name_anchor": name_anchor,
    }

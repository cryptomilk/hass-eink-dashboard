"""Heading widget context builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import markupsafe

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


class _HeadingBadgeDatum(NamedTuple):
    """Intermediate per-badge data used to compute final positions."""

    text: str
    text_w: int
    icon_w: int
    total_w: int
    show_icon: bool
    icon_svg: markupsafe.Markup | str


def _build_heading_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the heading widget.

    Renders an optional MDI icon and heading text on a single row,
    with optional entity badges flowing right-to-left from the right
    edge.  Mirrors HA's Heading card (``hui-heading-card.ts``).

    Heading style controls font size and fill:

    - ``"title"`` — Roboto Medium at ``font_primary``, black fill
      (default).
    - ``"subtitle"`` — Roboto Regular at ``font_secondary``, gray
      fill.

    Icon style controls circle rendering:

    - ``"none"`` — no circle; icon glyph sized to match the heading
      font (default).
    - ``"filled"`` — gray-filled circle at full ``icon_dia``.
    - ``"outlined"`` — white circle with black stroke at full
      ``icon_dia``.

    Badges are resolved right-to-left from the right edge; any badge
    that would overlap the heading text is silently omitted.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``heading`` (display text, default ``""``),
            ``heading_style`` (``"title"`` / ``"subtitle"``),
            ``icon`` (MDI icon name, e.g. ``"mdi:home"``),
            ``icon_style`` (``"none"`` / ``"filled"`` /
            ``"outlined"``),
            ``badges`` (list of entity ID strings or badge config
            dicts),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``heading.svg.j2``.
        Returns ``{"w": …, "h": …, "has_content": False,
        **_color_context()}`` when there is nothing to render.
        Full context includes widget dimensions, card style,
        metrics, colors, icon geometry, heading text, and
        pre-positioned badge list.
    """
    from ..render import (
        _compute_metrics,
        _load_font,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", DEFAULT_ROW_H)
    heading_text: str = widget.get("heading", "")
    heading_style: str = widget.get("heading_style", "title")
    icon_override = widget.get("icon")
    icon_style: str = widget.get("icon_style", "none")
    raw_badges = widget.get("badges", [])
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    m = _compute_metrics(svg_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    # Zero lpad/rpad when card_container already insets that side.
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Heading style: title (default) = large black;
    # subtitle = small gray.
    is_title = heading_style != "subtitle"
    font_sz = m.font_primary if is_title else m.font_secondary
    font_weight = "500" if is_title else "400"
    colors = _color_context()
    text_fill = colors["hex_black"] if is_title else colors["hex_gray"]

    # Icon resolution: glyph size depends on circle style.
    icon_outline, icon_no_circle = _resolve_icon_style(
        icon_style, grayscale_levels=grayscale_levels
    )
    # Widen the outline stroke on 2-level displays to avoid
    # dithering.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    glyph_sz = max(10, font_sz) if icon_no_circle else m.icon_inner
    icon_svg, _ = _resolve_icon_svg(
        icon_override,
        {},
        "",
        "",
        glyph_sz,
    )

    # Icon geometry: two modes depending on whether a circle
    # is drawn.
    icon_cx = icon_cy = icon_r = 0
    icon_fill = ""
    icon_glyph_x = icon_glyph_y = 0
    content_left = x_off + lpad
    if icon_svg:
        if icon_no_circle:
            # No circle: glyph sits flush at the content left
            # edge.
            icon_glyph_x = content_left
            icon_glyph_y = svg_h // 2 - glyph_sz // 2
            text_x = content_left + glyph_sz + m.inner_gap
        else:
            # Circle style: glyph is centred inside the circle.
            r = m.icon_dia // 2
            icon_cx = content_left + r
            icon_cy = svg_h // 2
            icon_r = r
            icon_fill = color_to_hex(COLOR_GRAY)
            icon_glyph_x = icon_cx - glyph_sz // 2
            icon_glyph_y = icon_cy - glyph_sz // 2
            text_x = content_left + m.icon_dia + m.inner_gap
    else:
        text_x = content_left

    text_y = svg_h // 2

    # Badge font and icon sizing.
    badge_font_sz = m.font_secondary
    badge_font = _load_font(badge_font_sz)
    badge_icon_sz = badge_font_sz

    # Resolve badge states and compute widths.
    badge_data: list[_HeadingBadgeDatum] = []
    for badge_cfg in raw_badges:
        if isinstance(badge_cfg, str):
            entity_id: str = badge_cfg
            show_icon = False
            show_state = True
            badge_icon_override = ""
        else:
            entity_id = badge_cfg.get("entity", "")
            show_icon = badge_cfg.get("show_icon", False)
            show_state = badge_cfg.get("show_state", True)
            badge_icon_override = badge_cfg.get("icon", "")
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        state_val = state.get("state", "")
        unit = attrs.get("unit_of_measurement", "")
        fmtd = _fmt(state_val, config) if show_state else ""
        badge_text = f"{fmtd}{unit}" if show_state else ""

        badge_icon_svg: markupsafe.Markup | str = ""
        if show_icon:
            # Only mdi:-prefixed overrides are recognised; other
            # values fall through to device_class resolution.
            b_override: str | None = None
            if badge_icon_override.startswith("mdi:"):
                b_override = badge_icon_override[4:]
            domain = entity_id.split(".")[0]
            badge_icon_svg, _ = _resolve_icon_svg(
                b_override,
                attrs,
                state_val,
                domain,
                badge_icon_sz,
            )

        icon_w = (badge_icon_sz + m.inner_gap) if badge_icon_svg else 0
        text_w = round(badge_font.getlength(badge_text))
        badge_data.append(
            _HeadingBadgeDatum(
                text=badge_text,
                text_w=text_w,
                icon_w=icon_w,
                total_w=icon_w + text_w,
                show_icon=show_icon,
                icon_svg=badge_icon_svg,
            )
        )

    # Position badges right-to-left.  Once a badge cannot fit
    # (its left edge would overlap the heading text), it and
    # all remaining badges to its left in config order are
    # dropped.
    badge_right = svg_w - r_inset - rpad
    rendered_badges: list[dict[str, object]] = []
    for bd in reversed(badge_data):
        new_right = badge_right - bd.total_w
        if new_right < text_x + m.inner_gap:
            break
        badge_cy = svg_h // 2
        rendered_badges.insert(
            0,
            {
                "text": bd.text,
                "text_x": badge_right - bd.text_w,
                "text_y": badge_cy,
                "show_icon": bd.show_icon,
                "icon_svg": bd.icon_svg,
                "icon_x": new_right,
                "icon_y": badge_cy - badge_icon_sz // 2,
            },
        )
        badge_right = new_right - m.inner_gap

    has_content = bool(heading_text) or bool(icon_svg) or bool(rendered_badges)

    if not has_content:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_content": False,
            **colors,
        }

    return {
        "w": svg_w,
        "h": svg_h,
        "has_content": True,
        "card_style": card_style,
        "bar_width": bar_width,
        **_metrics_context(m),
        **colors,
        # Icon geometry (only used when icon_svg is truthy).
        "icon_svg": icon_svg,
        "icon_cx": icon_cx,
        "icon_cy": icon_cy,
        "icon_r": icon_r,
        "icon_stroke_w": icon_stroke_w,
        "icon_fill": icon_fill,
        "icon_color": colors["hex_black"],
        "icon_outline": icon_outline,
        "icon_no_circle": icon_no_circle,
        "icon_glyph_x": icon_glyph_x,
        "icon_glyph_y": icon_glyph_y,
        # Heading text.
        "heading": heading_text,
        "font_sz": font_sz,
        "font_weight": font_weight,
        "text_fill": text_fill,
        "text_x": text_x,
        "text_y": text_y,
        # Badges (pre-positioned, empty list when none fit).
        "badges": rendered_badges,
        "badge_font_sz": badge_font_sz,
    }

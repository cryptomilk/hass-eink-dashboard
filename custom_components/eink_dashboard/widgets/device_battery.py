"""Device battery widget context builder."""

from __future__ import annotations

from ..const import (
    COLOR_BLACK,
    DEFAULT_CARD_STYLE,
    PADDING,
    DisplayConfig,
    Widget,
    color_to_hex,
)
from ._helpers import (
    _card_insets,
    _color_context,
    _metrics_context,
    _widget_dim,
)


def _build_device_battery_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the device_battery widget.

    Supports two layouts via the ``layout`` parameter:

    - ``"icon"`` (default): compact battery outline with percentage
      label, sized via h-based proportional ratios.  At ``h=40``
      the standard geometry applies (bw=30, bh=14, nub_w=3,
      nub_h=8).
    - ``"chip"``: pill-shaped chip with a proportional fill bar
      and percentage label, sized via ``h``.

    An optional ``card_style`` parameter wraps the content in a
    card frame.  Content insets are pre-computed from the card
    style so the template receives final absolute positions.

    Args:
        widget: Widget config dict.  Recognised keys: ``x``,
            ``y``, ``w``, ``h`` (default 40), ``layout``,
            ``card_style``, ``color``.
        config: Display config with ``device_battery_level``
            (int 0–100) and ``grayscale_levels``.

    Returns:
        Template context dict consumed by
        ``device_battery.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_level": False}`` when
        ``device_battery_level`` is absent from config.
    """
    from ..render import _compute_metrics, _load_font

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    # h: raw geometry reference for proportional calculations.
    # svg_h: clamped SVG viewport height (minimum 1 via
    # _widget_dim).
    h: int = widget.get("h", 40)
    svg_h = _widget_dim(widget, "h", 40)

    level = config.get("device_battery_level")
    if level is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_level": False,
            **_color_context(),
        }

    pct = max(0, min(100, int(level)))
    layout = widget.get("layout", "icon")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    grayscale_levels = config.get("grayscale_levels", 16)
    color: int = widget.get("color", COLOR_BLACK)
    # Force black below 20% for visual emphasis.
    if pct < 20:
        color = COLOR_BLACK
    color_hex = color_to_hex(color)

    label = f"{pct}%"
    m = _compute_metrics(svg_h)

    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)

    if layout == "chip":
        # svg_w is the available width (explicit w or remaining
        # canvas); used as upper bound for chip content before
        # svg_w is narrowed to actual content extent below.
        content_w = svg_w - x_off - r_inset
        # pad, gap, and font_sz match the chip macro ratios;
        # bar_w_nat and bar_h are battery-specific geometry.
        pad = h * 18 // 100
        gap = h * 14 // 100
        bar_w_nat = h * 120 // 100
        bar_h = h * 36 // 100
        bar_border = max(1, m.border // 2)
        font_sz = max(10, h * 46 // 100)
        # PIL font for text measurement only — resvg does not
        # expose text metrics, so widths are pre-computed here.
        font = _load_font(font_sz)
        text_w = round(font.getlength(label))

        chip_w = min(
            pad + bar_w_nat + gap + text_w + pad,
            content_w,
        )
        # Reflow bar to fit within a capped chip.
        bar_w = max(0, chip_w - pad - gap - text_w - pad)

        chip_radius = h // 2
        bar_y = (h - bar_h) // 2
        fill_w = int((bar_w - 2) * pct / 100) if bar_w > 2 else 0

        # Clip SVG width to chip content plus card insets so
        # the editor resize box matches the rendered content.
        w_override = widget.get("w")
        if w_override is not None:
            svg_w = max(1, w_override)
        else:
            svg_w = max(1, x_off + chip_w + r_inset)

        return {
            "w": svg_w,
            "h": svg_h,
            "has_level": True,
            "layout": "chip",
            "card_h": svg_h,
            "card_style": card_style,
            **_metrics_context(m),
            **_color_context(),
            "bar_width": bar_width,
            "color_hex": color_hex,
            "label": label,
            "font_sz": font_sz,
            "chip_x": x_off,
            "chip_w": chip_w,
            "chip_radius": chip_radius,
            "bar_abs_x": x_off + pad,
            "bar_y": bar_y,
            "bar_w": bar_w,
            "bar_h": bar_h,
            "bar_border": bar_border,
            "fill_abs_x": x_off + pad + 1,
            "fill_y": bar_y + 1,
            "fill_w": fill_w,
            "fill_h": max(0, bar_h - 2),
            "text_abs_x": x_off + pad + bar_w + gap,
            "text_y": h // 2,
        }

    # Icon layout: compact battery outline with proportional
    # fill bar.  Ratios chosen so that h=40 produces the standard
    # geometry (body_w=30, body_h=14, nub_w=3, nub_h=8).
    body_w = round(h * 0.75)
    body_h = round(h * 0.35)
    nub_w = round(h * 0.075)
    nub_h = round(h * 0.20)
    nub_gap = max(1, round(h * 0.025))
    gap = round(h * 0.10)
    font_sz = max(10, round(h * 0.60))
    font = _load_font(font_sz)
    # 'la' (left-ascender) is the default anchor for
    # FreeTypeFont.getbbox(), centring the battery body on the
    # visible text glyph ink rather than the full EM square.
    # Clamp to 0 so negative ascender values never push the rect
    # above the SVG canvas.
    bbox = font.getbbox(label)
    text_h = bbox[3] - bbox[1]
    icon_y = max(0, bbox[1] + (text_h - body_h) // 2)
    nub_y = icon_y + (body_h - nub_h) // 2
    fill_w = int((body_w - 2) * pct / 100)

    # Clip SVG width to icon+text content plus card insets so
    # the editor resize box matches the rendered content.
    w_override = widget.get("w")
    if w_override is not None:
        svg_w = max(1, w_override)
    else:
        svg_w = max(
            1,
            x_off + body_w + nub_gap + nub_w + gap + round(bbox[2]) + r_inset,
        )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_level": True,
        "layout": "icon",
        "card_h": svg_h,
        "card_style": card_style,
        **_metrics_context(m),
        **_color_context(),
        "bar_width": bar_width,
        "color_hex": color_hex,
        "label": label,
        "font_sz": font_sz,
        "body_x": x_off,
        "icon_y": icon_y,
        "body_w": body_w,
        "body_h": body_h,
        "nub_abs_x": x_off + body_w + nub_gap,
        "nub_y": nub_y,
        "nub_w": nub_w,
        "nub_h": nub_h,
        "fill_abs_x": x_off + 1,
        "icon_fill_y": icon_y + 1,
        "fill_w": fill_w,
        "icon_fill_h": max(0, body_h - 2),
        "text_abs_x": x_off + body_w + nub_gap + nub_w + gap,
        "text_svg_y": icon_y + body_h // 2,
    }

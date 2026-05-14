"""SVG-based widget rendering pipeline.

Provides a Jinja2 template environment for SVG widget templates and a
rasterisation helper that converts SVG strings to PNG bytes via resvg.

The font directory is passed explicitly to resvg with system fonts
disabled so rendering is identical across HA OS, Docker, and dev
machines regardless of installed system fonts.

Icon SVG files are inlined as ``<path>`` elements via Jinja2 filters
(``mdi_svg``, ``weather_svg``).  Path data is cached so file I/O
occurs only once per icon per process lifetime.
"""

import contextlib
import functools
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as ET
import jinja2
import markupsafe
import resvg_py

from .const import (
    COLOR_BLACK,
    COLOR_GRAY,
    DEFAULT_CARD_STYLE,
    FONT_SIZE_TEXT,
    FONT_SIZE_WEATHER,
    PADDING,
    Align,
    WidgetType,
)

_FONTS_DIR = Path(__file__).parent / "fonts"
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ICONS_DIR = Path(__file__).parent / "icons" / "svg"
_ICONS_DIR_RESOLVED = _ICONS_DIR.resolve()

# SVG XML namespace used by all icon files.
_SVG_NS = "http://www.w3.org/2000/svg"

# Maps HA weather condition strings to wi-*.svg filenames (without
# extension).  Sourced from scripts/build_icons.py CONDITION_TO_SVG.
_CONDITION_TO_SVG: dict[str, str] = {
    "sunny": "wi-day-sunny",
    "clear-night": "wi-night-clear",
    "cloudy": "wi-cloudy",
    "partlycloudy": "wi-day-cloudy",
    "fog": "wi-fog",
    "hail": "wi-hail",
    "lightning": "wi-lightning",
    "lightning-rainy": "wi-thunderstorm",
    "pouring": "wi-rain",
    "rainy": "wi-showers",
    "snowy": "wi-snow",
    "snowy-rainy": "wi-rain-mix",
    "windy": "wi-windy",
    "windy-variant": "wi-cloudy-windy",
    "exceptional": "wi-na",
}


def _svg_to_png(
    svg: str,
    width: int,
    height: int | None = None,
) -> bytes:
    """Rasterise an SVG string to PNG bytes via resvg.

    Uses ``skip_system_fonts=True`` so rendering is identical across
    HA OS, Docker, and dev machines.  Only fonts shipped in the
    ``fonts/`` directory are available to the renderer.

    When ``height`` is ``None``, resvg uses the SVG document's
    intrinsic height.  Widgets whose content can exceed their
    declared ``h`` (e.g. ``status_icons`` with wrapping chips)
    set the SVG height to the full content height and omit the
    explicit override so the rasterised PNG is tall enough to hold
    all rows.

    Args:
        svg: SVG document as a string.
        width: Output width in pixels.
        height: Output height in pixels, or ``None`` to use the
            SVG's intrinsic height.

    Returns:
        PNG image as raw bytes.
    """
    return bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg,
            width=width,
            height=height,
            font_dirs=[str(_FONTS_DIR)],
            skip_system_fonts=True,
        )
    )


@functools.cache
def _load_svg_paths(path: Path) -> tuple[str, ...]:
    """Parse an SVG file and return all ``<path d="...">`` values.

    Cached (unbounded ``@functools.cache``) so file I/O occurs only
    once per icon per process lifetime.  At render time only string
    interpolation occurs.

    Args:
        path: Absolute path to the SVG file.

    Returns:
        Tuple of ``d`` attribute values, one entry per ``<path>``
        element in document order.  Elements with a missing or empty
        ``d`` attribute are excluded.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
    tree = ET.parse(path)
    root = tree.getroot()
    elements = root.findall(f".//{{{_SVG_NS}}}path")
    return tuple(d for el in elements if (d := el.get("d", "")))


def _build_inline_svg(
    paths: tuple[str, ...],
    size: int,
    viewbox: str,
) -> str:
    """Assemble an inline ``<svg>`` element from extracted path data.

    Args:
        paths: Tuple of SVG ``<path d="...">`` values as returned by
            ``_load_svg_paths``.
        size: Output width and height in pixels.
        viewbox: The ``viewBox`` attribute value (e.g.
            ``"0 0 24 24"``).

    Returns:
        Inline SVG string ready to embed in a parent SVG document.
    """
    path_els = "".join(
        f'<path d={quoteattr(d)} fill="currentColor"/>' for d in paths
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{size}" height="{size}"'
        f" viewBox={quoteattr(viewbox)}>"
        f"{path_els}"
        f"</svg>"
    )


def _mdi_svg_filter(name: str, size: int) -> str:
    """Inline an MDI icon as a sized SVG element.

    Reads ``icons/svg/mdi/{name}.svg``, extracts the ``<path>``
    data, and emits an ``<svg>`` element scaled to ``size`` × ``size``
    pixels with ``viewBox="0 0 24 24"``.

    Args:
        name: MDI icon filename without extension (e.g.
            ``"thermometer"``).
        size: Output width and height in pixels.

    Returns:
        Inline SVG string ready to embed in a parent SVG document.

    Raises:
        ValueError: If ``name`` contains path traversal components.
        FileNotFoundError: If the icon file does not exist.
    """
    icon_path = (_ICONS_DIR / "mdi" / f"{name}.svg").resolve()
    if not icon_path.is_relative_to(_ICONS_DIR_RESOLVED):
        raise ValueError(f"Invalid icon name: {name!r}")
    return markupsafe.Markup(
        _build_inline_svg(_load_svg_paths(icon_path), size, "0 0 24 24")
    )


def _weather_svg_filter(condition: str, size: int) -> str:
    """Inline a weather condition icon as a sized SVG element.

    Maps the HA condition string to a ``wi-*.svg`` filename via
    ``_CONDITION_TO_SVG``, then inlines the path data with
    ``viewBox="0 0 30 30"``.

    Args:
        condition: HA weather condition string (e.g. ``"sunny"``).
        size: Output width and height in pixels.

    Returns:
        Inline SVG string ready to embed in a parent SVG document.

    Raises:
        KeyError: If ``condition`` is not in ``_CONDITION_TO_SVG``.
        FileNotFoundError: If the icon file does not exist.
    """
    filename = _CONDITION_TO_SVG[condition]
    paths = _load_svg_paths((_ICONS_DIR / f"{filename}.svg").resolve())
    return markupsafe.Markup(_build_inline_svg(paths, size, "0 0 30 30"))


# The spec (SVG_EVERYTHING.md) says autoescape=False, but we keep
# autoescape=True: user-controlled text (HA entity states) may
# contain < or & which would produce invalid SVG/XML and crash
# resvg.  Icon filters return markupsafe.Markup so they bypass
# escaping correctly.


def _make_jinja_env(
    loader: jinja2.BaseLoader,
) -> jinja2.Environment:
    """Create a Jinja2 env configured for SVG template rendering.

    Sets ``autoescape=True`` and registers the ``mdi_svg`` and
    ``weather_svg`` icon-inlining filters.

    Args:
        loader: Jinja2 template loader to use.

    Returns:
        Configured ``jinja2.Environment`` with icon filters
        registered.
    """
    env = jinja2.Environment(loader=loader, autoescape=True)
    env.filters["mdi_svg"] = _mdi_svg_filter
    env.filters["weather_svg"] = _weather_svg_filter
    return env


_jinja_env = _make_jinja_env(
    jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
)

type Widget = dict[str, Any]
type DisplayConfig = dict[str, Any]
type SvgContextFn = Callable[[Widget, DisplayConfig], dict[str, object]]


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
        title), and ``content_h`` is the remaining height.
    """
    if not title:
        return 0, 0, svg_h
    font_sz = max(10, round(svg_h * 0.14))
    advance = round(font_sz * 1.4)
    return font_sz, advance, svg_h - advance


def _metrics_context(m: Any) -> dict[str, int]:
    """Return the base card metric fields for a Jinja2 template context.

    Extracts the four fields that every card-style widget passes to its
    template (``m_border``, ``m_padding``, ``m_radius``,
    ``m_left_bar``).  Call sites merge this dict into the full context
    with ``**_metrics_context(m)`` and add extra metric fields
    (``m_icon_dia`` etc.) individually when needed.

    Args:
        m: ``WidgetMetrics`` namedtuple from ``_compute_metrics``.

    Returns:
        Dict with four ``m_*`` keys ready to unpack into a context
        dict.
    """
    return {
        "m_border": m.border,
        "m_padding": m.padding,
        "m_radius": m.radius,
        "m_left_bar": m.left_bar,
    }


def _card_insets(
    m: Any,
    card_style: str,
    grayscale_levels: int,
) -> tuple[int, int]:
    """Return (x_off, r_inset) for a card container.

    Mirrors the inset logic in the ``card_container`` macro in
    ``templates/_macros.svg.j2`` so callers can pre-compute
    absolute positions in Python rather than in Jinja2.

    Args:
        m: ``WidgetMetrics`` namedtuple from ``_compute_metrics``.
        card_style: One of ``"border"``, ``"left_bar"``, or
            ``"none"`` (or any other value treated as ``"none"``).
        grayscale_levels: Display grayscale depth; passed to
            ``_left_bar_width`` to widen the bar on 2-level
            displays.

    Returns:
        ``(x_off, r_inset)`` — the left and right pixel insets
        for the content area inside the card frame.
    """
    from .render import _left_bar_width  # noqa: PLC0415

    if card_style == "border":
        return m.padding, m.padding
    if card_style == "left_bar":
        return _left_bar_width(m, grayscale_levels) + m.padding, 0
    return 0, 0


def _build_text_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the text widget.

    Computes the SVG viewport dimensions, text anchor position,
    alignment attributes, and fill color.  All layout math
    happens here; the template receives final values only.

    The text widget has no mandatory ``w``/``h`` fields.  The
    SVG viewport defaults to the remaining canvas area so the
    widget can be pasted at its ``(x, y)`` position without
    clipping content below or to the right.

    When ``card_style`` is ``"border"`` or ``"left_bar"``, the
    text is inset by the card padding and vertically centred
    within the content area.  When ``card_style`` is ``"none"``
    (the default), behaviour is identical to the original: text
    is top-aligned at y=0 with ``dominant-baseline="hanging"``.

    Args:
        widget: Widget config dict.  Recognised keys: ``x``,
            ``y``, ``text``, ``font_size``, ``color``,
            ``align``, ``w``, ``h``, ``card_style``, ``title``.
        config: Display config with ``width``, ``height``,
            and ``grayscale_levels``.

    Returns:
        Dict with viewport size (``w``, ``h``); text rendering
        attributes (``text``, ``font_size``, ``fill``,
        ``text_x``, ``text_y``, ``text_anchor``, ``baseline``);
        optional title attributes (``title``, ``title_font_sz``,
        ``title_x``); card container inputs (``card_style``,
        ``content_y``, ``content_h``, ``grayscale_levels``,
        ``m_border``, ``m_padding``, ``m_radius``,
        ``m_left_bar``).
    """
    # Lazy import avoids circular dependency: render.py imports
    # svg_render.py at module level; importing render.py at
    # module level here would prevent initialisation.
    from .render import _compute_metrics  # noqa: PLC0415

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    text = widget.get("text", "")
    font_size = widget.get("font_size", FONT_SIZE_TEXT)
    color = widget.get("color", COLOR_BLACK)
    align = widget.get("align", Align.LEFT)
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title = widget.get("title", "")
    grayscale_levels = config.get("grayscale_levels", 16)

    # Default viewport to remaining canvas when not specified.
    # Clamp to >= 1: a widget at the canvas edge could produce a
    # zero or negative dimension, which would crash resvg.
    w_explicit = widget.get("w")
    raw_w = w_explicit if w_explicit is not None else config["width"] - x
    svg_w = max(1, raw_w)
    svg_h = max(1, widget.get("h", config["height"] - y))

    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    m = _compute_metrics(content_h)

    # Compute card container insets — mirrors the card_container
    # macro's own logic so text_x can be pre-calculated in Python.
    x_off, r_inset = _card_insets(m, card_style, grayscale_levels)

    content_w = svg_w - x_off - r_inset

    # Convert grayscale integer (0–255) to an SVG fill color.
    fill = f"rgb({color},{color},{color})"

    # Map alignment to SVG text-anchor + anchor x-position.
    # When a card container is active, text is positioned within
    # [x_off, svg_w - r_inset].  When no card is used (both
    # offsets are zero), the formulas reduce to the original
    # positions, preserving backward compatibility.
    if align == Align.RIGHT:
        text_anchor = "end"
        if x_off > 0 or r_inset > 0:
            # Card provides its own padding; anchor at content end.
            text_x = x_off + content_w
        else:
            # Original: PADDING inset from the right canvas edge.
            text_x = svg_w - PADDING
    elif align == Align.CENTER:
        text_anchor = "middle"
        text_x = x_off + content_w // 2
    else:
        text_anchor = "start"
        text_x = x_off

    # Vertical anchor: centre within the content area when a card
    # container is active; hang from y=0 otherwise (original).
    if card_style in ("border", "left_bar"):
        text_y = content_y + content_h // 2
        baseline = "central"
    else:
        text_y = 0
        baseline = "hanging"

    return {
        "w": svg_w,
        "h": svg_h,
        "text": text,
        "font_size": font_size,
        "fill": fill,
        "text_x": text_x,
        "text_y": text_y,
        "text_anchor": text_anchor,
        "baseline": baseline,
        "title": title,
        "title_font_sz": title_font_sz,
        "title_x": x_off,
        "content_y": content_y,
        "content_h": content_h,
        "card_style": card_style,
        "grayscale_levels": grayscale_levels,
        **_metrics_context(m),
    }


def _build_separator_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the separator widget.

    Computes the SVG viewport dimensions and the bounding rectangle
    for the separator element.  Both ``"line"`` and ``"bar"`` styles
    are represented as a single ``<rect>`` whose width and height are
    pre-computed here so the template needs no conditionals.

    The ``"bar"`` style widens to 10 px on 2-level displays
    (``grayscale_levels <= 2``) so the dithered dot pattern reads
    clearly as a separator.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``direction`` (``"horizontal"`` | ``"vertical"``,
            default ``"horizontal"``),
            ``style`` (``"line"`` | ``"bar"``,
            default ``"line"``),
            ``length`` (explicit pixel length; omit for full
            span), ``x`` (default ``PADDING``),
            ``y`` (default 0).
        config: Display config with ``width``, ``height``, and
            optional ``grayscale_levels`` (default 16).

    Returns:
        Dict consumed by ``separator.svg.j2``: ``w``, ``h``,
        ``bar_w``, ``bar_h``, ``fill``.
    """
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    direction = widget.get("direction", "horizontal")
    style = widget.get("style", "line")
    grayscale_levels = config.get("grayscale_levels", 16)

    # Clamp to >= 1: a widget at the canvas edge could produce a
    # zero or negative dimension, which would crash resvg.
    svg_w = max(1, widget.get("w", config["width"] - x))
    svg_h = max(1, widget.get("h", config["height"] - y))

    if style == "bar":
        color: int = COLOR_GRAY
        # Widen bar on 2-level displays so the dithered dot
        # pattern reads clearly as a separator.
        thickness = 10 if grayscale_levels <= 2 else 6
    else:
        color = COLOR_BLACK
        thickness = 2

    # Default span: viewport dimension minus one PADDING unit,
    # matching the PIL formula config[dim] - PADDING - pos.
    explicit_length: int | None = widget.get("length")
    if explicit_length is not None:
        length = explicit_length
    elif direction == "vertical":
        length = svg_h - PADDING
    else:
        length = svg_w - PADDING

    fill = f"rgb({color},{color},{color})"

    if direction == "vertical":
        bar_w: int = thickness
        bar_h: int = length
    else:
        bar_w = length
        bar_h = thickness

    return {
        "w": svg_w,
        "h": svg_h,
        "bar_w": bar_w,
        "bar_h": bar_h,
        "fill": fill,
    }


_DETAIL_ICON_MAP: dict[str, str] = {
    "humidity": "wi-humidity",
    "barometer": "wi-barometer",
    "wind": "wi-strong-wind",
    "cloud": "wi-cloud",
}


def _build_weather_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the weather widget.

    Replicates the coordinate math from ``render_weather()``,
    pre-computing every position and icon SVG string so the
    Jinja2 template contains no layout logic.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity``, ``x``, ``y``, ``w``, ``font_size``,
            ``forecast_days``, ``card_style``.
        config: Display config with ``width``, ``height``,
            ``states``, ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``weather.svg.j2``.
        Returns ``{"w": …, "h": …, "has_state": False}`` when
        the entity is absent from ``states``.
    """
    # Lazy imports avoid circular dependency: render.py imports
    # svg_render.py at module level; if svg_render.py imported
    # render.py at module level the initialisation would fail.
    from .render import (  # noqa: PLC0415
        _DAY_ABBREV,
        _compute_metrics,
        _fmt_temp,
        _left_bar_width,
        _load_font,
    )

    entity_id = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id)
    x = widget.get("x", PADDING)
    svg_w = max(1, widget.get("w", config["width"] - x))
    svg_h = max(1, widget.get("h", config["height"] - widget.get("y", 0)))

    if state is None:
        return {"w": svg_w, "h": svg_h, "has_state": False}

    font_size = widget.get("font_size", FONT_SIZE_WEATHER)
    forecast_days = widget.get("forecast_days", 5)
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    grayscale_levels = config.get("grayscale_levels", 16)

    scale = font_size / FONT_SIZE_WEATHER

    # Card width: use explicit w or natural width capped to canvas.
    w_override = widget.get("w")
    if w_override is not None:
        card_w = w_override
    else:
        card_w = min(round(380 * scale), svg_w)

    # PIL fonts for text measurement only — never used for drawing.
    font_xl = _load_font(round(64 * scale))
    font_sm = _load_font(round(16 * scale))

    # Entity attributes.
    condition = state.get("state", "")
    attrs = state.get("attributes", {})
    temp = attrs.get("temperature", "--")
    temp_unit = attrs.get("temperature_unit", "°C")
    humidity = attrs.get("humidity")
    wind = attrs.get("wind_speed")
    wind_unit = attrs.get("wind_speed_unit", "km/h")
    pressure = attrs.get("pressure")
    pressure_unit = attrs.get("pressure_unit", "hPa")
    cloud_coverage = attrs.get("cloud_coverage")
    forecast = attrs.get("forecast", [])

    # Sizing constants, all proportional to scale.
    icon_size = round(80 * scale)
    pad = round(10 * scale)
    icon_right_pad = round(16 * scale)
    detail_gap = round(2 * scale)
    detail_icon_h = round(20 * scale)
    icon_gap = round(4 * scale)
    sep_gap = round(8 * scale)
    sep_thickness = max(2, round(3 * scale))
    forecast_zone_h = round(88 * scale)
    precip_text_h = round(16 * scale)

    # Measure temperature text height (PIL) for height estimation.
    temp_text = f"{_fmt_temp(temp)}{temp_unit}"
    temp_bbox = font_xl.getbbox(temp_text)
    temp_h = temp_bbox[3] - temp_bbox[1]

    # Card metrics — always compute so they can be passed to the
    # card_container macro even when card_style is "none".
    m = _compute_metrics(round(48 * scale))
    top_pad = m.padding if card_style != "none" else pad

    # Total card height, matching PIL's formula exactly.
    row1_h = top_pad + max(icon_size, temp_h)
    detail_h = detail_gap + detail_icon_h
    has_forecast = bool(forecast) and forecast_days > 0
    if has_forecast:
        forecast_section_h = (
            sep_gap + sep_thickness + sep_gap + forecast_zone_h + precip_text_h
        )
    else:
        forecast_section_h = pad
    total_h = row1_h + detail_h + forecast_section_h + pad

    # Content insets — mirror the card_container macro in
    # templates/_macros.svg.j2 (macro card_container, lines 41-74).
    # The macro's caller(xo, ri) values are intentionally unused in
    # the template; all positions are pre-computed here so they stay
    # in Python, not Jinja2.
    if card_style == "none":
        content_left = pad
        content_w = card_w - 2 * pad
    elif card_style == "border":
        content_left = m.padding
        content_w = card_w - 2 * m.padding
    elif card_style == "left_bar":
        content_left = _left_bar_width(m, grayscale_levels) + m.padding
        content_w = card_w - content_left
    else:
        content_left = 0
        content_w = card_w

    content_top = top_pad

    # Row 1: condition icon + temperature + today hi/lo/precip.
    icon_cy = content_top + icon_size // 2
    icon_x = content_left
    icon_y = content_top
    temp_x = content_left + icon_size + icon_right_pad
    # dominant-baseline="central" in template — centres em-square
    # on icon_cy, matching PIL's visible-ink centering within a
    # few pixels.
    temp_y = icon_cy

    # vis_top: top of the visible temperature glyph, used as
    # anchor for the stacked hi/lo/precip text block.
    vis_top = icon_cy - temp_h // 2
    hilo_right = content_left + content_w - pad

    today_hi = ""
    today_lo = ""
    today_precip = ""
    lo_y = vis_top + round(temp_h * 0.4)
    precip_y = vis_top + round(temp_h * 0.72)
    precip_unit_fc = attrs.get("precipitation_unit", "mm")
    if forecast:
        today = forecast[0]
        hi_val = today.get("temperature")
        lo_val = today.get("templow")
        p_val = today.get("precipitation")
        if hi_val is not None:
            today_hi = f"{_fmt_temp(hi_val)}°"
        if lo_val is not None:
            today_lo = f"{_fmt_temp(lo_val)}°"
        if p_val is not None:
            today_precip = f"{p_val}{precip_unit_fc}"

    # row1_bottom mirrors PIL's max() between icon bottom and
    # the bottom of the temperature glyph.
    temp_y_pil = icon_cy - temp_bbox[1] - temp_h // 2
    row1_bottom = max(
        content_top + icon_size,
        temp_y_pil + temp_bbox[3],
    )

    # Condition icon SVG.
    try:
        cond_icon_svg: markupsafe.Markup | str = _weather_svg_filter(
            condition, icon_size
        )
    except (KeyError, FileNotFoundError):
        cond_icon_svg = ""

    # Detail row: icon + text pairs for weather attributes.
    detail_y = row1_bottom + detail_gap
    raw_details: list[tuple[str, str]] = []
    if humidity is not None:
        raw_details.append(("humidity", f"{humidity}%"))
    if pressure is not None:
        raw_details.append(("barometer", f"{round(pressure)}{pressure_unit}"))
    if wind is not None:
        raw_details.append(("wind", f"{round(wind)}{wind_unit}"))
    if cloud_coverage is not None:
        raw_details.append(("cloud", f"{cloud_coverage}%"))

    detail_cols = max(len(raw_details), 1)
    col_w_detail = content_w // detail_cols
    detail_items: list[dict[str, object]] = []

    for i, (icon_name, text) in enumerate(raw_details):
        col_cx = content_left + col_w_detail * i + col_w_detail // 2
        text_w_i = round(font_sm.getlength(text))
        svg_filename = _DETAIL_ICON_MAP.get(icon_name, "")
        # Wrap in Markup so Jinja2 emits the SVG verbatim.  All
        # icon strings added to the context must be Markup instances.
        detail_icon_svg: markupsafe.Markup | str = ""
        if svg_filename:
            detail_path = (_ICONS_DIR / f"{svg_filename}.svg").resolve()
            try:
                detail_paths = _load_svg_paths(detail_path)
                detail_icon_svg = markupsafe.Markup(
                    _build_inline_svg(detail_paths, detail_icon_h, "0 0 30 30")
                )
            except FileNotFoundError:
                pass
        has_detail_icon = bool(detail_icon_svg)
        icon_w = detail_icon_h + icon_gap if has_detail_icon else 0
        item_w = icon_w + text_w_i
        item_x = col_cx - item_w // 2
        detail_items.append(
            {
                "icon_svg": detail_icon_svg,
                "icon_x": item_x,
                "icon_y": detail_y,
                "text_x": (
                    item_x + detail_icon_h + icon_gap
                    if has_detail_icon
                    else item_x
                ),
                "text_y": detail_y + detail_icon_h // 2,
                "text": text,
            }
        )

    detail_bottom = detail_y + detail_icon_h

    # Forecast grid.
    forecast_entries: list[dict[str, object]] = []
    sep_x1 = 0
    sep_x2 = 0
    sep_y = 0

    if has_forecast:
        forecast_cols = max(forecast_days, 5)
        col_width = content_w // forecast_cols
        content_width = forecast_cols * col_width
        separator_y = detail_bottom + sep_gap
        sep_x1 = content_left
        sep_x2 = content_left + content_width
        sep_y = separator_y
        # sep_thickness accounts for the separator line height so
        # forecast content starts below the stroke bottom, matching
        # the sep_thickness term in forecast_section_h.
        forecast_y = separator_y + sep_thickness + sep_gap
        fc_icon_size = round(32 * scale)

        if forecast_days >= forecast_cols:
            positions = list(range(forecast_days))
        elif forecast_days <= 1:
            positions = [forecast_cols // 2]
        else:
            positions = [
                round(i * (forecast_cols - 1) / (forecast_days - 1))
                for i in range(forecast_days)
            ]

        for idx, day in enumerate(forecast[:forecast_days]):
            col_i = positions[idx]
            cx = content_left + col_width * col_i + col_width // 2
            dt_str = day.get("datetime")
            if dt_str:
                day_label = _DAY_ABBREV[
                    datetime.fromisoformat(dt_str).weekday()
                ]
            else:
                day_label = ""

            day_condition = day.get("condition", "")
            try:
                fc_icon_svg: markupsafe.Markup | str = _weather_svg_filter(
                    day_condition, fc_icon_size
                )
            except (KeyError, FileNotFoundError):
                fc_icon_svg = ""

            fc_hi_val = day.get("temperature", "")
            fc_lo_val = day.get("templow", "")
            fc_hi = f"{_fmt_temp(fc_hi_val)}°" if fc_hi_val != "" else ""
            fc_lo = f"{_fmt_temp(fc_lo_val)}°" if fc_lo_val != "" else ""
            fc_p = day.get("precipitation")
            fc_precip = (
                f"{fc_p}{precip_unit_fc}"
                if fc_p is not None and fc_p > 0
                else ""
            )
            icon_cy_fc = forecast_y + round(34 * scale)
            forecast_entries.append(
                {
                    "cx": cx,
                    "label": day_label,
                    "label_y": forecast_y,
                    "icon_svg": fc_icon_svg,
                    "icon_x": cx - fc_icon_size // 2,
                    "icon_y": icon_cy_fc - fc_icon_size // 2,
                    "hi": fc_hi,
                    "hi_y": forecast_y + round(52 * scale),
                    "lo": fc_lo,
                    "lo_y": forecast_y + round(70 * scale),
                    "precip": fc_precip,
                    "precip_y": forecast_y + round(88 * scale),
                }
            )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_state": True,
        "card_w": card_w,
        "total_h": total_h,
        "card_style": card_style,
        **_metrics_context(m),
        "grayscale_levels": grayscale_levels,
        "icon_svg": cond_icon_svg,
        "icon_x": icon_x,
        "icon_y": icon_y,
        "icon_size": icon_size,
        "temp_text": temp_text,
        "temp_x": temp_x,
        "temp_y": temp_y,
        "font_xl": round(64 * scale),
        "font_sm": round(16 * scale),
        # font_xs is template-only; no PIL measurement needed.
        "font_xs": round(14 * scale),
        "hilo_right": hilo_right,
        "hi_text": today_hi,
        "hi_y": vis_top,
        "lo_text": today_lo,
        "lo_y": lo_y,
        "precip_text": today_precip,
        "precip_y": precip_y,
        "detail_items": detail_items,
        "has_forecast": has_forecast,
        "sep_x1": sep_x1,
        "sep_x2": sep_x2,
        "sep_y": sep_y,
        "sep_thickness": sep_thickness,
        "forecast_entries": forecast_entries,
    }


def _build_sensor_rows_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the sensor_rows widget.

    Pre-computes every position and icon SVG string so the Jinja2
    template contains no layout logic.  Mirrors the coordinate math
    from ``render_sensor_rows()`` in ``render.py``.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``x`` (default ``PADDING``), ``y`` (default 0),
            ``w`` (default remaining canvas width),
            ``h`` (default remaining canvas height),
            ``entities`` (list of entity IDs),
            ``title`` (optional section label drawn above
            the card), ``card_style``.
        config: Display config with ``width``, ``height``,
            ``states``, and ``grayscale_levels``.

    Returns:
        Template context dict consumed by
        ``sensor_rows.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_entities": False}`` when
        the entities list is empty.
    """
    from .render import (  # noqa: PLC0415
        _compute_metrics,
        _device_class_icon,
    )

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    svg_w = max(1, widget.get("w", config["width"] - x))
    svg_h = max(1, widget.get("h", config["height"] - y))

    entity_ids: list[str] = widget.get("entities", [])
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title = widget.get("title", "")
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    if not entity_ids:
        return {"w": svg_w, "h": svg_h, "has_entities": False}

    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    row_h = content_h // len(entity_ids)
    m = _compute_metrics(row_h)

    rows: list[dict[str, object]] = []
    for i, entity_id in enumerate(entity_ids):
        state = states.get(entity_id)
        if state is None:
            continue

        attrs = state.get("attributes", {})
        domain = entity_id.split(".")[0]
        state_val = state.get("state", "")
        icon_name = _device_class_icon(attrs, state_val, domain)

        # Icon SVG sized to 60 % of icon_dia — the card_row
        # macro positions it centered in the circle at that
        # size, matching PIL's 60 % shrink before paste.
        icon_svg: markupsafe.Markup | str = ""
        if icon_name:
            with contextlib.suppress(FileNotFoundError):
                icon_svg = _mdi_svg_filter(icon_name, m.icon_dia * 6 // 10)

        # Letter fallback when no MDI icon is available.
        letter = ""
        if not icon_svg:
            friendly = attrs.get("friendly_name", entity_id)
            letter = friendly[:1].upper() if friendly else ""

        unit = attrs.get("unit_of_measurement", "")
        secondary = f"{state_val}{unit}" if unit else state_val

        rows.append(
            {
                "y": content_y + i * row_h,
                "primary": attrs.get("friendly_name", entity_id),
                "secondary": secondary,
                "icon_svg": icon_svg,
                "letter": letter,
            }
        )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_entities": True,
        "title": title,
        "title_font_sz": title_font_sz,
        "content_y": content_y,
        "content_h": content_h,
        "card_style": card_style,
        "grayscale_levels": grayscale_levels,
        **_metrics_context(m),
        "m_icon_dia": m.icon_dia,
        "m_inner_gap": m.inner_gap,
        "m_font_primary": m.font_primary,
        "m_font_secondary": m.font_secondary,
        "m_divider": m.divider,
        "row_h": row_h,
        "rows": rows,
    }


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
    from .render import _compute_metrics, _load_font  # noqa: PLC0415

    x = widget.get("x", PADDING)
    svg_w = max(1, widget.get("w", config["width"] - x))
    h: int = widget.get("h", 40)
    svg_h = max(1, h)

    level = config.get("device_battery_level")
    if level is None:
        return {"w": svg_w, "h": svg_h, "has_level": False}

    pct = max(0, min(100, int(level)))
    layout = widget.get("layout", "icon")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    grayscale_levels = config.get("grayscale_levels", 16)
    color: int = widget.get("color", COLOR_BLACK)
    # Force black below 20% for visual emphasis.
    if pct < 20:
        color = COLOR_BLACK
    color_hex = f"#{color:02x}{color:02x}{color:02x}"

    label = f"{pct}%"
    m = _compute_metrics(h)

    x_off, r_inset = _card_insets(m, card_style, grayscale_levels)

    if layout == "chip":
        content_w = svg_w - x_off - r_inset
        # Sizing ratios mirror _CHIP_PAD_RATIO/_CHIP_GAP_RATIO/
        # _CHIP_FONT_RATIO in render.py and the chip macro
        # parameters in _macros.svg.j2.
        pad = round(h * 0.18)
        gap = round(h * 0.14)
        bar_w_nat = round(h * 1.2)
        bar_h = round(h * 0.36)
        bar_border = max(1, m.border // 2)
        font_sz = max(10, round(h * 0.46))
        font = _load_font(font_sz)
        text_w = round(font.getlength(label))

        chip_w = min(pad + bar_w_nat + gap + text_w + pad, content_w)
        # Reflow bar to fit within a capped chip.
        bar_w = max(0, chip_w - pad - gap - text_w - pad)

        chip_radius = h // 2
        bar_y = (h - bar_h) // 2
        fill_w = int((bar_w - 2) * pct / 100) if bar_w > 2 else 0

        return {
            "w": svg_w,
            "h": svg_h,
            "has_level": True,
            "layout": "chip",
            "card_h": h,
            "card_style": card_style,
            **_metrics_context(m),
            "grayscale_levels": grayscale_levels,
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

    # Icon layout: compact battery outline with proportional fill bar.
    # Ratios chosen so that h=40 produces the standard geometry
    # (body_w=30, body_h=14, nub_w=3, nub_h=8).
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

    return {
        "w": svg_w,
        "h": svg_h,
        "has_level": True,
        "layout": "icon",
        "card_h": h,
        "card_style": card_style,
        **_metrics_context(m),
        "grayscale_levels": grayscale_levels,
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


def _build_status_icons_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the status_icons widget.

    Renders binary sensor entities as pill-shaped chips.  Problem
    entities (state ``"on"`` and device_class in
    ``_PROBLEM_DEVICE_CLASSES``) use inverted chips (black fill,
    white text/icon).  Chips flow left-to-right with row wrapping.
    An optional title is drawn in gray above the chip area.

    The SVG ``height`` is set to the full content height, which
    may exceed the declared widget ``h`` when chips wrap to
    multiple rows.  ``render_dashboard()`` calls ``_svg_to_png()``
    without an explicit height override so the rasterised PNG is
    tall enough to hold all rows.

    Args:
        widget: Widget config dict.  Recognised keys: ``x``,
            ``y``, ``w``, ``h`` (default 40), ``title``,
            ``card_style``, ``entities``.
        config: Display config with ``states`` and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by
        ``status_icons.svg.j2``.  Returns
        ``{"w": …, "h": …, "total_h": …, "has_entities": False}``
        when the entity list is empty or all listed entities are
        absent from ``states``.
    """
    from .render import (  # noqa: PLC0415
        _CHIP_FONT_RATIO,
        _CHIP_GAP_RATIO,
        _CHIP_ICON_RATIO,
        _CHIP_PAD_RATIO,
        _PROBLEM_DEVICE_CLASSES,
        _compute_metrics,
        _device_class_icon,
        _load_font,
    )

    x = widget.get("x", PADDING)
    svg_w = max(1, widget.get("w", config["width"] - x))
    svg_h = max(1, widget.get("h", 40))
    title: str = widget.get("title", "")
    card_style: str = widget.get("card_style", DEFAULT_CARD_STYLE)
    entity_ids: list[str] = widget.get("entities", [])
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    if not entity_ids:
        return {
            "w": svg_w,
            "h": svg_h,
            "total_h": svg_h,
            "has_entities": False,
            "title": title,
        }

    title_font_sz, title_advance, content_h = _title_layout(title, svg_h)

    # chip_h is the single-row chip height after the title.
    chip_h = max(1, content_h)
    m = _compute_metrics(chip_h)

    x_off, r_inset = _card_insets(m, card_style, grayscale_levels)
    content_w = svg_w - x_off - r_inset

    # Chip sizing ratios — must match the chip macro in
    # _macros.svg.j2.
    pad = round(chip_h * _CHIP_PAD_RATIO)
    icon_sz = round(chip_h * _CHIP_ICON_RATIO)
    icon_gap = round(chip_h * _CHIP_GAP_RATIO)
    font_sz = max(10, round(chip_h * _CHIP_FONT_RATIO))
    font = _load_font(font_sz)
    # Inter-chip gap equals icon size by design (same as PIL).
    inter_gap = round(chip_h * _CHIP_ICON_RATIO)

    # Build chip descriptors with pre-computed widths.
    chips: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        label: str = attrs.get("friendly_name", entity_id)
        state_val: str = state.get("state", "")
        device_class: str = attrs.get("device_class", "")
        domain = entity_id.split(".")[0]

        is_problem = (
            state_val == "on" and device_class in _PROBLEM_DEVICE_CLASSES
        )

        icon_name = _device_class_icon(attrs, state_val, domain)
        icon_svg: markupsafe.Markup | str = ""
        if icon_name:
            with contextlib.suppress(FileNotFoundError):
                icon_svg = _mdi_svg_filter(icon_name, icon_sz)

        has_icon = bool(icon_svg)
        icon_w = (icon_sz + icon_gap) if has_icon else 0
        # Ink bounding box matches _chip_width() in render.py.
        label_bbox = font.getbbox(label)
        text_w = int(label_bbox[2] - label_bbox[0])
        chip_w = pad * 2 + icon_w + text_w

        chips.append(
            {
                "text": label,
                "icon_svg": icon_svg,
                "inverted": is_problem,
                "w": chip_w,
                "x": 0,
                "y": 0,
            }
        )

    if not chips:
        return {
            "w": svg_w,
            "h": svg_h,
            "total_h": svg_h,
            "has_entities": False,
            "title": title,
        }

    # Horizontal flow layout with row wrapping.
    # Positions are absolute within the SVG viewport:
    # cur_y starts at title_advance so chip rows are
    # placed below the title.
    cur_x = x_off
    cur_y = title_advance
    for chip in chips:
        if cur_x > x_off:
            if cur_x + inter_gap + chip["w"] > x_off + content_w:
                cur_x = x_off
                cur_y += chip_h + inter_gap
            else:
                cur_x += inter_gap
        chip["x"] = cur_x
        chip["y"] = cur_y
        cur_x += chip["w"]

    # SVG height covers title + all chip rows (may exceed svg_h
    # when chips wrap to more than one row).
    total_h = chips[-1]["y"] + chip_h

    return {
        "w": svg_w,
        "h": svg_h,
        "total_h": total_h,
        "has_entities": True,
        "title": title,
        "title_font_sz": title_font_sz,
        "title_advance": title_advance,
        "chip_h": chip_h,
        "card_style": card_style,
        "grayscale_levels": grayscale_levels,
        **_metrics_context(m),
        "chips": chips,
    }


def _build_waste_schedule_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the waste_schedule widget.

    Renders waste collection entries as card rows with urgency
    styling.  Each entry maps an entity attribute (ISO date string
    or integer day offset) to a short label and colour scheme:

    - ``days <= 1``: black-filled icon circle; date text is black
      when ``days == 0`` (today) and gray otherwise.
    - ``days >= 2``: outlined icon circle (white fill, black
      stroke); date text is gray.

    Two layouts are supported via the ``layout`` parameter:

    - ``"list"`` (default): one row per visible entry, each with a
      gray horizontal divider between rows; date is shown as a
      right-aligned ``value`` string.
    - ``"card"``: only the most urgent entry (lowest day count)
      using the full widget height; date is shown as a
      ``secondary`` line below the primary label.

    Only entries within the 0–3 day range are rendered.  Entries
    with missing, unparseable, or out-of-range dates are silently
    skipped.

    Args:
        widget: Widget config dict.  Recognised keys: ``entity``
            (entity ID whose attributes hold the dates),
            ``entries`` (list of ``{"attribute": …, "label": …}``
            dicts), ``layout`` (``"list"`` or ``"card"``),
            ``card_style``, ``title``, ``x``, ``y``, ``w``, ``h``.
        config: Display config with ``states`` (entity ID →
            state dict) and ``grayscale_levels``.

    Returns:
        Template context dict consumed by
        ``waste_schedule.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_rows": False}`` when the entity
        is absent from states, ``entries`` is empty, or no entries
        fall within the visible day range.
    """
    from .render import (  # noqa: PLC0415
        _compute_metrics,
        _format_relative_date,
        _get_today,
        _parse_days_until,
    )

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    svg_w = max(1, widget.get("w", config["width"] - x))
    svg_h = max(1, widget.get("h", config["height"] - y))

    entity_id: str = widget.get("entity", "")
    entries: list[dict[str, str]] = widget.get("entries", [])
    layout: str = widget.get("layout", "list")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title: str = widget.get("title", "")
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    empty_ctx: dict[str, object] = {
        "w": svg_w,
        "h": svg_h,
        "has_rows": False,
    }
    if not entity_id or not entries:
        return empty_ctx

    entity_state = states.get(entity_id)
    if entity_state is None:
        return empty_ctx

    attrs = entity_state.get("attributes", {})
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)

    # Resolve visible entries: parse dates, filter to 0–3 days.
    # Config order is preserved — equal-day entries keep the
    # order the user configured them, matching the PIL renderer.
    # Use _get_today() from render.py so tests can patch
    # "custom_components.eink_dashboard.render.date" to control
    # the date returned here.
    today = _get_today()
    visible: list[tuple[str, str, int]] = []
    for entry in entries:
        attr_key = entry.get("attribute", "")
        label = entry.get("label") or attr_key
        raw = str(attrs.get(attr_key, ""))
        if not raw:
            continue
        days = _parse_days_until(raw, today)
        if days is None or days < 0 or days > 3:
            continue
        visible.append((label, raw, days))

    if not visible:
        return empty_ctx

    if layout == "card":
        # Most urgent entry only (stable sort: equal days keep
        # config order), displayed at full widget height.
        visible.sort(key=lambda e: e[2])
        visible = [visible[0]]
        row_h = content_h
    else:
        row_h = content_h // len(visible)

    m = _compute_metrics(row_h)

    # Build the trash-can icon SVG once; all entries share the
    # same icon, only the circle fill/outline differs.
    icon_sz = m.icon_dia * 6 // 10
    icon_svg = _mdi_svg_filter("trash-can", icon_sz)

    rows: list[dict[str, object]] = []
    for i, (label, raw, days) in enumerate(visible):
        date_str = _format_relative_date(days, raw)
        # days == 0 (today): black date text for urgency.
        # days >= 1: gray date text.
        date_fill = "#000000" if days == 0 else "#787878"
        use_outline = days >= 2
        # Outlined circles ignore icon_fill (macro uses white
        # fill + black stroke), but we still pass it correctly.
        icon_fill = "#000000" if days <= 1 else "#787878"
        rows.append(
            {
                "y": content_y + i * row_h,
                "primary": label,
                # Card layout: date as secondary (below primary).
                # List layout: date as right-aligned value.
                "secondary": date_str if layout == "card" else "",
                "value": "" if layout == "card" else date_str,
                "icon_svg": icon_svg,
                "icon_outline": use_outline,
                "icon_fill": icon_fill,
                "secondary_fill": date_fill,
                "value_fill": date_fill,
                "letter": "",
            }
        )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_rows": True,
        "title": title,
        "title_font_sz": title_font_sz,
        "content_y": content_y,
        "content_h": content_h,
        "card_style": card_style,
        "grayscale_levels": grayscale_levels,
        **_metrics_context(m),
        "m_icon_dia": m.icon_dia,
        "m_inner_gap": m.inner_gap,
        "m_font_primary": m.font_primary,
        "m_font_secondary": m.font_secondary,
        "m_divider": m.divider,
        "row_h": row_h,
        "rows": rows,
    }


def render_widget_svg(
    widget: Widget,
    config: DisplayConfig,
) -> str:
    """Render a widget to an SVG string.

    Looks up the registered context builder for the widget type,
    calls it to build the template context, then renders the
    corresponding Jinja2 template.

    Args:
        widget: Widget configuration dict.  Must contain a
            ``"type"`` key with a matching entry in
            ``_SVG_RENDERERS``.
        config: Display config with ``width``, ``height``, and
            entity ``states``.

    Returns:
        SVG document string ready to pass to ``_svg_to_png()``.

    Raises:
        KeyError: If the widget type has no registered SVG
            renderer.
    """
    wtype = widget["type"]
    ctx = _SVG_RENDERERS[wtype](widget, config)
    tmpl = _jinja_env.get_template(f"{wtype}.svg.j2")
    return tmpl.render(**ctx)


_SVG_RENDERERS: dict[str, SvgContextFn] = {
    WidgetType.DEVICE_BATTERY: _build_device_battery_context,
    WidgetType.SENSOR_ROWS: _build_sensor_rows_context,
    WidgetType.SEPARATOR: _build_separator_context,
    WidgetType.STATUS_ICONS: _build_status_icons_context,
    WidgetType.TEXT: _build_text_context,
    WidgetType.WASTE_SCHEDULE: _build_waste_schedule_context,
    WidgetType.WEATHER: _build_weather_context,
}

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


def _svg_to_png(svg: str, width: int, height: int) -> bytes:
    """Rasterise an SVG string to PNG bytes via resvg.

    Uses ``skip_system_fonts=True`` so rendering is identical across
    HA OS, Docker, and dev machines.  Only fonts shipped in the
    ``fonts/`` directory are available to the renderer.

    Args:
        svg: SVG document as a string.
        width: Output width in pixels.
        height: Output height in pixels.

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

    Args:
        widget: Widget config dict.  Recognised keys: ``x``,
            ``y``, ``text``, ``font_size``, ``color``,
            ``align``, ``w``, ``h``.
        config: Display config with ``width`` and ``height``.

    Returns:
        Dict consumed by ``text.svg.j2``: ``w``, ``h``,
        ``text``, ``font_size``, ``fill``, ``text_x``,
        ``text_anchor``.
    """
    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    text = widget.get("text", "")
    font_size = widget.get("font_size", FONT_SIZE_TEXT)
    color = widget.get("color", COLOR_BLACK)
    align = widget.get("align", Align.LEFT)

    # Default viewport to remaining canvas when not specified.
    # Clamp to >= 1: a widget at the canvas edge could produce a
    # zero or negative dimension, which would crash resvg.
    w_explicit = widget.get("w")
    raw_w = w_explicit if w_explicit is not None else config["width"] - x
    svg_w = max(1, raw_w)
    svg_h = max(1, widget.get("h", config["height"] - y))

    # Convert grayscale integer (0–255) to an SVG fill color.
    fill = f"rgb({color},{color},{color})"

    # Map alignment to SVG text-anchor + anchor x-position.
    # Coordinate algebra ensures these produce the same absolute
    # pixel positions as the PIL renderer when pasted at (x, y).
    if align == Align.RIGHT:
        # text-anchor="end" at (svg_w - PADDING) → text ends
        # at right_edge - PADDING, matching PIL's computation.
        text_anchor = "end"
        text_x = svg_w - PADDING
    elif align == Align.CENTER:
        # text-anchor="middle" at svg_w//2 → text centred in
        # the available width, matching PIL's centre formula.
        text_anchor = "middle"
        text_x = svg_w // 2
    else:
        text_anchor = "start"
        text_x = 0

    return {
        "w": svg_w,
        "h": svg_h,
        "text": text,
        "font_size": font_size,
        "fill": fill,
        "text_x": text_x,
        "text_anchor": text_anchor,
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
        _load_font,
    )

    entity_id = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id)
    wx = widget.get("x", PADDING)
    svg_w = max(1, widget.get("w", config["width"] - wx))
    svg_h = max(1, widget.get("h", config["height"] - widget.get("y", 0)))

    if state is None:
        return {"w": svg_w, "h": svg_h, "has_state": False}

    font_size = widget.get("font_size", FONT_SIZE_WEATHER)
    forecast_days = widget.get("forecast_days", 5)
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    grayscale_levels = config.get("grayscale_levels", 16)

    s = font_size / FONT_SIZE_WEATHER

    # Card width: use explicit w or natural width capped to canvas.
    w_override = widget.get("w")
    if w_override is not None:
        card_w = w_override
    else:
        card_w = min(round(380 * s), svg_w)

    # PIL fonts for text measurement only — never used for drawing.
    font_xl = _load_font(round(64 * s))
    font_sm = _load_font(round(16 * s))

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

    # Sizing constants, all proportional to s.
    icon_size = round(80 * s)
    pad = round(10 * s)
    icon_right_pad = round(16 * s)
    detail_gap = round(2 * s)
    detail_icon_h = round(20 * s)
    icon_gap = round(4 * s)
    sep_gap = round(8 * s)
    sep_thickness = max(2, round(3 * s))
    forecast_zone_h = round(88 * s)
    precip_text_h = round(16 * s)

    # Measure temperature text height (PIL) for height estimation.
    temp_text = f"{_fmt_temp(temp)}{temp_unit}"
    temp_bbox = font_xl.getbbox(temp_text)
    temp_h = temp_bbox[3] - temp_bbox[1]

    # Card metrics — always compute so they can be passed to the
    # card_container macro even when card_style is "none".
    m = _compute_metrics(round(48 * s))
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
        bar_w = (
            max(10, m.left_bar * 3) if grayscale_levels <= 2 else m.left_bar
        )
        content_left = bar_w + m.padding
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
    precip_y_val = vis_top + round(temp_h * 0.72)
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
        d_icon_svg: markupsafe.Markup | str = ""
        if svg_filename:
            d_path = (_ICONS_DIR / f"{svg_filename}.svg").resolve()
            try:
                d_paths = _load_svg_paths(d_path)
                d_icon_svg = markupsafe.Markup(
                    _build_inline_svg(d_paths, detail_icon_h, "0 0 30 30")
                )
            except FileNotFoundError:
                pass
        has_d_icon = bool(d_icon_svg)
        item_w = (detail_icon_h + icon_gap if has_d_icon else 0) + text_w_i
        item_x = col_cx - item_w // 2
        detail_items.append(
            {
                "icon_svg": d_icon_svg,
                "icon_x": item_x,
                "icon_y": detail_y,
                "text_x": (
                    item_x + detail_icon_h + icon_gap if has_d_icon else item_x
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
        fc_icon_size = round(32 * s)

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

            hi_val_fc = day.get("temperature", "")
            lo_val_fc = day.get("templow", "")
            fc_hi = f"{_fmt_temp(hi_val_fc)}°" if hi_val_fc != "" else ""
            fc_lo = f"{_fmt_temp(lo_val_fc)}°" if lo_val_fc != "" else ""
            fc_p = day.get("precipitation")
            fc_precip = (
                f"{fc_p}{precip_unit_fc}"
                if fc_p is not None and fc_p > 0
                else ""
            )
            icon_cy_fc = forecast_y + round(34 * s)
            forecast_entries.append(
                {
                    "cx": cx,
                    "label": day_label,
                    "label_y": forecast_y,
                    "icon_svg": fc_icon_svg,
                    "icon_x": cx - fc_icon_size // 2,
                    "icon_y": icon_cy_fc - fc_icon_size // 2,
                    "hi": fc_hi,
                    "hi_y": forecast_y + round(52 * s),
                    "lo": fc_lo,
                    "lo_y": forecast_y + round(70 * s),
                    "precip": fc_precip,
                    "precip_y": forecast_y + round(88 * s),
                }
            )

    return {
        "w": svg_w,
        "h": svg_h,
        "has_state": True,
        "card_w": card_w,
        "total_h": total_h,
        "card_style": card_style,
        "m_border": m.border,
        "m_padding": m.padding,
        "m_radius": m.radius,
        "m_left_bar": m.left_bar,
        "grayscale_levels": grayscale_levels,
        "icon_svg": cond_icon_svg,
        "icon_x": icon_x,
        "icon_y": icon_y,
        "icon_size": icon_size,
        "temp_text": temp_text,
        "temp_x": temp_x,
        "temp_y": temp_y,
        "font_xl": round(64 * s),
        "font_sm": round(16 * s),
        "font_xs": round(14 * s),  # template-only; no PIL measurement needed
        "hilo_right": hilo_right,
        "hi_text": today_hi,
        "hi_y": vis_top,
        "lo_text": today_lo,
        "lo_y": lo_y,
        "precip_text": today_precip,
        "precip_y": precip_y_val,
        "detail_items": detail_items,
        "has_forecast": has_forecast,
        "sep_x1": sep_x1,
        "sep_x2": sep_x2,
        "sep_y": sep_y,
        "sep_thickness": sep_thickness,
        "forecast_entries": forecast_entries,
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
    WidgetType.SEPARATOR: _build_separator_context,
    WidgetType.TEXT: _build_text_context,
    WidgetType.WEATHER: _build_weather_context,
}

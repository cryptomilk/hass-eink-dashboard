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

from __future__ import annotations

import contextlib
import functools
from collections.abc import Callable
from dataclasses import fields as dc_fields
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .render import WidgetMetrics
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as ET
import jinja2
import markupsafe
import resvg_py

from .const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_WHITE,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    FONT_SIZE_TEXT,
    FONT_SIZE_WEATHER,
    PADDING,
    Align,
    WidgetType,
)

_FONTS_DIR = Path(__file__).parent / "fonts" / "Roboto"
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ICONS_DIR = Path(__file__).parent / "icons" / "svg"
_ICONS_DIR_RESOLVED = _ICONS_DIR.resolve()
_MDI_DIR_RESOLVED = (_ICONS_DIR / "mdi").resolve()

# SVG XML namespace used by all icon files.
_SVG_NS = "http://www.w3.org/2000/svg"

# Maps HA weather condition strings to wi-*.svg filenames (without
# extension).
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

# Entity states treated as "active" for the filled circle
# indicator.  Covers binary_sensor/switch ("on"), cover ("open"),
# person ("home"), media_player ("playing"), sun ("above_horizon").
# Sensor entities with numeric states never match and always render
# as outlined.
_ACTIVE_STATES: frozenset[str] = frozenset(
    {"on", "open", "home", "playing", "above_horizon"}
)


def _svg_to_png(
    svg: str,
    width: int | None = None,
    height: int | None = None,
) -> bytes:
    """Rasterise an SVG string to PNG bytes via resvg.

    Uses ``skip_system_fonts=True`` so rendering is identical across
    HA OS, Docker, and dev machines.  Only fonts shipped in the
    ``fonts/`` directory are available to the renderer.

    When ``width`` or ``height`` is ``None``, resvg uses the SVG
    document's intrinsic dimension.  There are two usage modes:
    pass both as ``None`` (production per-widget rendering) so
    each widget renders at its declared size; or pass explicit
    values to scale to a fixed viewport (design tool, tests).

    Args:
        svg: SVG document as a string.
        width: Output width in pixels, or ``None`` to use the
            SVG's intrinsic width.
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


def _compose_svg(
    svg_parts: list[str],
    positions: list[tuple[int, int]],
    width: int,
    height: int,
) -> str:
    """Compose per-widget SVGs into a single root SVG document.

    Each widget SVG is positioned by injecting ``x``/``y`` attributes
    into its root ``<svg>`` tag.  Widget templates always produce output
    starting with ``<svg `` (Jinja2 ``{%- -%}`` strips leading
    whitespace), so the injection is a simple string prefix swap.

    Args:
        svg_parts: Rendered SVG strings, one per widget.
        positions: ``(x, y)`` pixel offset for each widget on the
            dashboard canvas, in the same order as ``svg_parts``.
        width: Dashboard canvas width in pixels.
        height: Dashboard canvas height in pixels.

    Returns:
        A single SVG document containing all widgets positioned
        within a root viewport of ``width`` × ``height``.
    """
    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}"'
        f' fill="{_color_context()["hex_white"]}"/>',
    ]
    for svg, (x, y) in zip(svg_parts, positions, strict=True):
        # Strip leading whitespace then replace '<svg ' prefix so
        # that x/y attributes position the widget viewport.
        # Templates must emit '<svg ' (space after tag name, not
        # a newline) for this prefix swap to work.
        stripped = svg.lstrip()
        if not stripped.startswith("<svg "):
            raise ValueError(f"expected <svg prefix: {stripped[:40]!r}")
        lines.append(f'<svg x="{x}" y="{y}" ' + stripped[4:])
    lines.append("</svg>")
    return "\n".join(lines)


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
    if not icon_path.is_relative_to(_MDI_DIR_RESOLVED):
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
    # No traversal guard — condition is from a fixed dict.
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
        Dict mapping ``hex_black``, ``hex_white``, and
        ``hex_gray`` to their SVG hex color strings.
    """
    # Lazy import avoids circular dependency (same pattern as
    # _compute_metrics imports elsewhere in this file).
    from .render import color_to_hex

    return {
        "hex_black": color_to_hex(COLOR_BLACK),
        "hex_white": color_to_hex(COLOR_WHITE),
        "hex_gray": color_to_hex(COLOR_GRAY),
    }


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
    from .render import _left_bar_width

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
) -> int:
    """Compute natural widget height from content row count.

    Returns a height such that when ``_title_layout(title, result)``
    is called the resulting ``content_h`` equals ``num_rows * row_h``
    (within 1 px rounding).  When ``title`` is empty, this simplifies
    to ``num_rows * row_h``.

    Used as the fallback for ``_widget_dim`` so row-based widgets size
    to their content instead of filling the remaining canvas.

    Args:
        title: Widget title string.  Empty means no title.
        num_rows: Number of content rows to accommodate.
            Must be at least 1.
        row_h: Target height per content row in pixels.

    Returns:
        Total widget height in pixels.
    """
    if num_rows < 1:
        raise ValueError(f"num_rows must be >= 1, got {num_rows}")
    target = num_rows * row_h
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
        ``content_y``, ``content_h``, ``bar_width``,
        ``m_border``, ``m_padding``, ``m_radius``,
        ``m_left_bar``).
    """
    # Lazy import avoids circular dependency: render.py imports
    # svg_render.py at module level; importing render.py at
    # module level here would prevent initialisation.
    from .render import _compute_metrics, color_to_hex

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    text = widget.get("text", "")
    font_size = widget.get("font_size", FONT_SIZE_TEXT)
    color = widget.get("color", COLOR_BLACK)
    align = widget.get("align", Align.LEFT)
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title = widget.get("title", "")
    grayscale_levels = config.get("grayscale_levels", 16)

    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", config["height"] - y)

    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    m = _compute_metrics(content_h)

    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)

    content_w = svg_w - x_off - r_inset

    # Convert grayscale integer (0–255) to an SVG fill color.
    fill = color_to_hex(color)

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
        "bar_width": bar_width,
        **_metrics_context(m),
        **_color_context(),
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
    from .render import color_to_hex

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    direction = widget.get("direction", "horizontal")
    style = widget.get("style", "line")
    grayscale_levels = config.get("grayscale_levels", 16)

    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", config["height"] - y)

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

    fill = color_to_hex(color)

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
        **_color_context(),
    }


_DETAIL_ICON_MAP: dict[str, str] = {
    "humidity": "wi-humidity",
    "barometer": "wi-barometer",
    "wind": "wi-strong-wind",
    "cloud": "wi-cloud",
}


def _cap_weather_font_xl(
    font_xl_size: int,
    font_xl: Any,
    font_sm: Any,
    font_xs: Any,
    temp_text: str,
    avail: int,
    today_hi: str,
    today_lo: str,
    today_precip: str,
) -> int:
    """Return font_xl capped so the temperature text fits in avail px.

    Measures the widest hi/lo/precipitation string to determine how far
    that column protrudes leftward from its right anchor, then reduces
    font_xl proportionally if the temperature text would overlap it.

    Args:
        font_xl_size: Nominal xl font size in pixels.
        font_xl: PIL font loaded at font_xl_size (for text measurement).
        font_sm: PIL font for hi/lo text measurement.
        font_xs: PIL font for precipitation text measurement.
        temp_text: Formatted temperature string (e.g. "13.8°C").
        avail: Pixel budget between temp_x and the hi/lo column.
        today_hi: High-temperature string (may be empty).
        today_lo: Low-temperature string (may be empty).
        today_precip: Precipitation string (may be empty).

    Returns:
        Capped font size; equals font_xl_size when text already fits.
    """
    hilo_w = 0
    if today_hi:
        hilo_w = max(hilo_w, round(font_sm.getlength(today_hi)))
    if today_lo:
        hilo_w = max(hilo_w, round(font_sm.getlength(today_lo)))
    if today_precip:
        hilo_w = max(hilo_w, round(font_xs.getlength(today_precip)))
    budget = avail - hilo_w
    temp_w = round(font_xl.getlength(temp_text))
    if budget > 0 and temp_w > budget:
        return round(font_xl_size * budget / temp_w)
    return font_xl_size


def _build_weather_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the weather widget.

    Pre-computes every position and icon SVG string so the
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
    from .render import (
        _DAY_ABBREV,
        _compute_metrics,
        _fmt_temp,
        _load_font,
    )

    entity_id = widget.get("entity", "")
    state = config.get("states", {}).get(entity_id)
    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    if state is None:
        svg_h = _widget_dim(widget, "h", config["height"] - widget.get("y", 0))
        return {"w": svg_w, "h": svg_h, "has_state": False, **_color_context()}

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
        # Clip SVG to content width so the editor resize box
        # matches the rendered content, not the full canvas.
        svg_w = _widget_dim(widget, "w", card_w)

    # PIL fonts for text measurement only — never used for
    # drawing.  Affects: temp_h, temp_bbox (getbbox) and
    # text_w_i (getlength) below.
    # Bold is used for font_xl because the temperature text renders
    # with font-weight="bold" in the SVG template.
    font_xl = _load_font(round(64 * scale), bold=True)
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

    # Card metrics — 48 at scale=1 gives card-level metrics
    # (padding~10, radius~10) matching the original PIL layout.
    # Always compute so they can be passed to the card_container
    # macro even when card_style is "none".
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
    # Default to content height so the SVG is no taller than its
    # rendered content.  Without this, the editor resize box spans
    # the full remaining canvas when no explicit h is configured.
    svg_h = _widget_dim(widget, "h", total_h)

    # Content insets — "border" and "left_bar" use the shared
    # helper; "none" applies its own pad so that the weather card
    # content never touches the viewport edge.
    if card_style == "none":
        content_left = pad
        content_w = card_w - 2 * pad
        bar_width = 0
    else:
        x_off, r_inset, bar_width = _card_insets(
            m, card_style, grayscale_levels
        )
        content_left = x_off
        content_w = card_w - x_off - r_inset

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

    # Cap font_xl so temp text doesn't overlap the hi/lo column.
    font_xl_size = _cap_weather_font_xl(
        round(64 * scale),
        font_xl,
        font_sm,
        _load_font(round(14 * scale)),
        temp_text,
        hilo_right - temp_x - pad,
        today_hi,
        today_lo,
        today_precip,
    )

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
            col_positions = list(range(forecast_days))
        elif forecast_days <= 1:
            col_positions = [forecast_cols // 2]
        else:
            col_positions = [
                round(i * (forecast_cols - 1) / (forecast_days - 1))
                for i in range(forecast_days)
            ]

        for idx, day in enumerate(forecast[:forecast_days]):
            col_i = col_positions[idx]
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
        "bar_width": bar_width,
        "icon_svg": cond_icon_svg,
        "icon_x": icon_x,
        "icon_y": icon_y,
        "icon_size": icon_size,
        "temp_text": temp_text,
        "temp_x": temp_x,
        "temp_y": temp_y,
        "font_xl": font_xl_size,
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
        **_color_context(),
    }


def _build_sensor_rows_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the sensor_rows widget.

    Pre-computes every position and icon SVG string so the Jinja2
    template contains no layout logic.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``x`` (default ``PADDING``),
            ``w`` (default remaining canvas width),
            ``h`` (default content height; auto-sized when absent),
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
    from .render import (
        _compute_metrics,
        _device_class_icon,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_ids: list[str] = widget.get("entities", [])
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title = widget.get("title", "")
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    # Resolve to present entities only so row_h is divided
    # by the actual rendered count, not the configured count.
    # Absent entities would otherwise leave silent blank gaps.
    entity_ids = [eid for eid in entity_ids if eid in states]
    if not entity_ids:
        return {
            "w": svg_w,
            "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
            "has_entities": False,
            **_color_context(),
        }

    # Auto-size: default to content height so the widget is no
    # taller than its rendered rows.  Explicit "h" in the widget
    # config overrides this, preserving backward compatibility.
    svg_h = _widget_dim(widget, "h", _auto_row_height(title, len(entity_ids)))
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    row_h = content_h // len(entity_ids)
    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    # When the card container already insets content on a side,
    # the row contributes zero padding on that side to avoid
    # double-padding.
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    rows: list[dict[str, object]] = []
    for i, entity_id in enumerate(entity_ids):
        state = states[entity_id]

        attrs = state.get("attributes", {})
        domain = entity_id.split(".")[0]
        state_val = state.get("state", "")
        icon_name = _device_class_icon(attrs, state_val, domain)

        # Icon SVG sized to icon_inner so the card_row macro
        # can centre it inside the circle with a visible ring.
        icon_svg: markupsafe.Markup | str = ""
        if icon_name:
            with contextlib.suppress(FileNotFoundError):
                icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)

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
        "bar_width": bar_width,
        **_metrics_context(m),
        **_color_context(),
        "row_h": row_h,
        "rows": rows,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
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
    from .render import _compute_metrics, _load_font, color_to_hex

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    h: int = widget.get("h", 40)
    svg_h = _widget_dim(widget, "h", 40)

    level = config.get("device_battery_level")
    if level is None:
        return {"w": svg_w, "h": svg_h, "has_level": False, **_color_context()}

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
        # Sizing ratios mirror _CHIP_PAD_RATIO/_CHIP_GAP_RATIO/
        # _CHIP_FONT_RATIO in render.py and the chip macro
        # parameters in _macros.svg.j2.
        pad = round(h * 0.18)
        gap = round(h * 0.14)
        bar_w_nat = round(h * 1.2)
        bar_h = round(h * 0.36)
        bar_border = max(1, m.border // 2)
        font_sz = max(10, round(h * 0.46))
        # PIL font for text measurement only — resvg does not
        # expose text metrics, so widths are pre-computed here.
        font = _load_font(font_sz)
        text_w = round(font.getlength(label))

        chip_w = min(pad + bar_w_nat + gap + text_w + pad, content_w)
        # Reflow bar to fit within a capped chip.
        bar_w = max(0, chip_w - pad - gap - text_w - pad)

        chip_radius = h // 2
        bar_y = (h - bar_h) // 2
        fill_w = int((bar_w - 2) * pct / 100) if bar_w > 2 else 0

        # Clip SVG width to chip content plus card insets so the
        # editor resize box matches the rendered content.
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


def _build_status_icons_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the status_icons widget.

    Renders entities as icon-and-text labels that flow
    left-to-right with row wrapping.  Each icon sits inside a
    state circle: filled gray when active (``state`` is in
    ``_ACTIVE_STATES``), outlined when inactive.  An optional title
    is drawn in gray above the label area.

    Icons are resolved from the entity's ``device_class`` via
    ``_device_class_icon``, falling back to the entity's ``icon``
    attribute (e.g. ``mdi:washing-machine``).

    When ``show_state`` is true, the entity state is appended to
    the label (e.g. "Front Door · On").

    When no explicit ``w`` is set on the widget, the SVG width
    shrinks to fit the laid-out content so the card border does
    not stretch across the full display.

    Args:
        widget: Widget config dict.  Recognised keys: ``x``,
            ``y``, ``w``, ``h`` (default 40), ``title``,
            ``card_style``, ``show_icon``, ``show_state``,
            ``entities``.
        config: Display config with ``states`` and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by
        ``status_icons.svg.j2``.  Returns
        ``{"w": …, "h": …, "total_h": …, "has_entities": False}``
        when the entity list is empty or all listed entities are
        absent from ``states``.
    """
    from .render import (
        _CHIP_FONT_RATIO,
        _CHIP_GAP_RATIO,
        _CHIP_ICON_INNER_RATIO,
        _CHIP_ICON_RATIO,
        _CHIP_PAD_RATIO,
        _compute_metrics,
        _device_class_icon,
        _load_font,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    # Chip wrapping determines total_h dynamically, so
    # _auto_row_height (fixed row count) does not apply here.
    svg_h = _widget_dim(widget, "h", 40)
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
            **_color_context(),
        }

    title_font_sz, title_advance, content_h = _title_layout(title, svg_h)

    # chip_h is the single-row chip height after the title.
    chip_h = max(1, content_h)
    m = _compute_metrics(chip_h)

    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    content_w = svg_w - x_off - r_inset

    show_icon: bool = widget.get("show_icon", True)
    show_state: bool = widget.get("show_state", False)

    # Chip sizing ratios — must match the chip macro in
    # _macros.svg.j2.
    pad = int(chip_h * _CHIP_PAD_RATIO)
    icon_dia = int(chip_h * _CHIP_ICON_RATIO)
    icon_sz = int(icon_dia * _CHIP_ICON_INNER_RATIO)
    icon_gap = int(chip_h * _CHIP_GAP_RATIO)
    font_sz = max(10, int(chip_h * _CHIP_FONT_RATIO))
    # PIL font for text measurement only — resvg does not
    # expose text metrics, so widths are pre-computed here.
    font = _load_font(font_sz)
    # Vertical gap between wrapped label rows.
    inter_gap = int(chip_h * _CHIP_PAD_RATIO)

    # Build chip descriptors with pre-computed widths.
    chips: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            continue
        attrs = state.get("attributes", {})
        label: str = attrs.get("friendly_name", entity_id)
        state_val: str = state.get("state", "")
        domain = entity_id.split(".")[0]

        # Icon resolution — skipped entirely when show_icon
        # is disabled.
        icon_svg: markupsafe.Markup | str = ""
        if show_icon:
            icon_name = _device_class_icon(
                attrs,
                state_val,
                domain,
            )
            if icon_name is None:
                raw = attrs.get("icon", "")
                if raw.startswith("mdi:"):
                    icon_name = raw[4:]
            if icon_name:
                with contextlib.suppress(FileNotFoundError):
                    icon_svg = _mdi_svg_filter(
                        icon_name,
                        icon_sz,
                    )

        has_icon = bool(icon_svg)
        icon_w = (icon_dia + icon_gap) if has_icon else 0
        # Label width: 2*pad + icon area + text ink width.
        text = f"{label} · {state_val.capitalize()}" if show_state else label
        label_bbox = font.getbbox(text)
        text_w = int(label_bbox[2] - label_bbox[0])
        chip_w = pad * 2 + icon_w + text_w

        chips.append(
            {
                "text": text,
                "icon_svg": icon_svg,
                "active": state_val in _ACTIVE_STATES,
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
            **_color_context(),
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

    # SVG height covers title + all label rows (may exceed svg_h
    # when labels wrap to more than one row).
    total_h = chips[-1]["y"] + chip_h

    # Shrink SVG width to fit content when no explicit w is set.
    if "w" not in widget:
        content_extent = max(c["x"] + c["w"] for c in chips) + r_inset
        svg_w = content_extent

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
        "bar_width": bar_width,
        **_metrics_context(m),
        **_color_context(),
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

    By default only entries within the 0–3 day range are rendered.
    When ``show_all`` is ``True``, entries with any future date are
    included regardless of distance.  Entries with missing,
    unparseable, or past dates are always silently skipped.

    Args:
        widget: Widget config dict.  Recognised keys: ``entity``
            (entity ID whose attributes hold the dates),
            ``entries`` (list of ``{"attribute": …, "label": …}``
            dicts), ``layout`` (``"list"`` or ``"card"``),
            ``show_all`` (``bool``, default ``False``),
            ``card_style``, ``title``, ``x``, ``w``, ``h``.
        config: Display config with ``states`` (entity ID →
            state dict) and ``grayscale_levels``.

    Returns:
        Template context dict consumed by
        ``waste_schedule.svg.j2``.  Returns
        ``{"w": …, "h": …, "has_rows": False}`` when the entity
        is absent from states, ``entries`` is empty, or no entries
        fall within the visible day range.
    """
    from .render import (
        _compute_metrics,
        _format_relative_date,
        _get_today,
        _parse_days_until,
        color_to_hex,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)

    entity_id: str = widget.get("entity", "")
    entries: list[dict[str, str]] = widget.get("entries", [])
    layout: str = widget.get("layout", "list")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    title: str = widget.get("title", "")
    show_all: bool = bool(widget.get("show_all", False))
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    empty_ctx: dict[str, object] = {
        "w": svg_w,
        "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
        "has_rows": False,
        **_color_context(),
    }
    if not entity_id or not entries:
        return empty_ctx

    entity_state = states.get(entity_id)
    if entity_state is None:
        return empty_ctx

    attrs = entity_state.get("attributes", {})

    # Resolve visible entries before computing height so the
    # auto-sizing fallback knows how many rows to accommodate.
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
        if days is None or days < 0:
            continue
        if not show_all and days > 3:
            continue
        visible.append((label, raw, days))

    if not visible:
        return empty_ctx

    if layout == "card":
        # Most urgent entry only (stable sort: equal days keep
        # config order), displayed at full widget height.
        visible.sort(key=lambda e: e[2])
        visible = [visible[0]]

    # Auto-size: default to content height so the widget is no
    # taller than its rendered rows.  Explicit "h" in the widget
    # config overrides this, preserving backward compatibility.
    num_display_rows = len(visible)
    svg_h = _widget_dim(widget, "h", _auto_row_height(title, num_display_rows))
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    # card layout always trims visible to one entry above, so
    # num_display_rows == 1 and the division is equivalent to content_h.
    row_h = content_h // num_display_rows

    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Build the trash-can icon SVG once; all entries share the
    # same icon, only the circle fill/outline differs.
    icon_sz = m.icon_inner
    icon_svg = _mdi_svg_filter("trash-can", icon_sz)

    rows: list[dict[str, object]] = []
    for i, (label, raw, days) in enumerate(visible):
        date_str = _format_relative_date(days, raw)
        # days == 0 (today): black date text for urgency.
        # days >= 1: gray date text.
        date_fill = (
            color_to_hex(COLOR_BLACK)
            if days == 0
            else color_to_hex(COLOR_GRAY)
        )
        use_outline = days >= 2
        # Outlined circles ignore icon_fill (macro uses white
        # fill + black stroke), but we still pass it correctly.
        icon_fill = (
            color_to_hex(COLOR_BLACK)
            if days <= 1
            else color_to_hex(COLOR_GRAY)
        )
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
        "bar_width": bar_width,
        **_metrics_context(m),
        **_color_context(),
        "row_h": row_h,
        "rows": rows,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
    }


_SVG_RENDERERS: dict[str, SvgContextFn] = {
    WidgetType.DEVICE_BATTERY: _build_device_battery_context,
    WidgetType.SENSOR_ROWS: _build_sensor_rows_context,
    WidgetType.SEPARATOR: _build_separator_context,
    WidgetType.STATUS_ICONS: _build_status_icons_context,
    WidgetType.TEXT: _build_text_context,
    WidgetType.WASTE_SCHEDULE: _build_waste_schedule_context,
    WidgetType.WEATHER: _build_weather_context,
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

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
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as ET
import jinja2
import markupsafe
import resvg_py

from .const import (
    COLOR_BLACK,
    FONT_SIZE_TEXT,
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
    WidgetType.TEXT: _build_text_context,
}

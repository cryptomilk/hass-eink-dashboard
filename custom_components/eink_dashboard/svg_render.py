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

import bisect
import functools
import json
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as ET
import jinja2
import markupsafe
import resvg_py

from .const import (
    COLOR_WHITE,
    DisplayConfig,
    Widget,
    WidgetType,
    color_to_hex,
)

_hex_white = color_to_hex(COLOR_WHITE)

_FONTS_DIR = Path(__file__).parent / "fonts" / "Roboto"
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ICONS_DIR = Path(__file__).parent / "icons" / "svg"
_ICONS_DIR_RESOLVED = _ICONS_DIR.resolve()
# npm @mdi/svg fallback: available when pnpm install has been run.
_NPM_MDI_DIR = (
    Path(__file__).parent
    / "frontend"
    / "node_modules"
    / "@mdi"
    / "svg"
    / "svg"
)

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
        # Root canvas fill — kept here unlike per-widget backgrounds
        # (removed in commit 28ede13) because _compose_svg() is the
        # preview path and has no PIL canvas to fall back on.
        f'<rect width="{width}" height="{height}" fill="{_hex_white}"/>',
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


@functools.cache
def _load_hass_mdi_metadata() -> (
    tuple[Path, list[dict[str, str]], list[str]] | None
):
    """Load MDI icon metadata from the hass_frontend pip package.

    Reads ``hass_frontend.where() / "static/mdi/iconMetadata.json"``
    which maps icon name range prefixes to chunk filenames.  The
    ``hass_frontend`` package is present on every HA installation but
    not in development environments where the npm fallback is used
    instead.

    Returns:
        ``(mdi_dir, parts, starts)`` where ``mdi_dir`` is the path
        to ``static/mdi/``, ``parts`` is the metadata list sorted by
        start prefix, and ``starts`` is the corresponding sorted list
        of chunk-start prefix strings (first entry is ``""`` because
        the first chunk has no start key).  The tuple is cached;
        callers must not mutate its contents.  Returns ``None`` if
        ``hass_frontend`` is not importable or the metadata file is
        absent.
    """
    try:
        import hass_frontend  # ty: ignore[unresolved-import]
    except ImportError:
        return None
    mdi_dir = Path(hass_frontend.where()) / "static" / "mdi"
    meta_path = mdi_dir / "iconMetadata.json"
    if not meta_path.exists():
        return None
    with open(meta_path) as f:
        meta = json.load(f)
    # Sort parts so that starts is in ascending order for bisect.
    # The JSON spec does not guarantee array ordering.
    parts: list[dict[str, str]] = sorted(
        meta.get("parts", []),
        key=lambda p: p.get("start") or "",
    )
    # The first chunk omits "start" in the JSON (undefined serialised
    # away); treat it as "" so bisect comparisons work correctly.
    starts = [p.get("start") or "" for p in parts]
    return (mdi_dir, parts, starts)


@functools.lru_cache(maxsize=32)
def _load_mdi_chunk(path: Path) -> dict[str, str]:
    """Load a chunked MDI JSON file and return name→path mapping.

    Cached (LRU, 32 entries) so file I/O occurs only once per chunk.
    HA ships ~20 MDI chunks, well within the limit.  Callers must not
    mutate the returned dict; it is shared across all callers via the
    cache.

    Args:
        path: Absolute path to the chunk JSON file.

    Returns:
        Dict mapping MDI icon names to their SVG ``d`` path strings.
    """
    with open(path) as f:
        return json.load(f)


@functools.cache
def _resolve_mdi_path(name: str) -> tuple[str, ...] | None:
    """Resolve an MDI icon name to its SVG ``<path d>`` data.

    Cached so repeated lookups for the same icon name skip the bisect
    and dict lookup on subsequent calls.

    Tries two sources in order:

    1. **hass_frontend** — reads chunked JSON from the
       ``hass_frontend`` pip package (always present on HA, never
       present in unit tests unless stubbed).
    2. **npm @mdi/svg** — falls back to individual SVG files in
       ``frontend/node_modules/@mdi/svg/svg/`` (present after
       ``pnpm install``, used by tests and development).

    Args:
        name: MDI icon name without the ``mdi:`` prefix (e.g.
            ``"thermometer"``).

    Returns:
        Tuple of ``d`` attribute values (one per ``<path>`` element)
        or ``None`` when the icon cannot be resolved from either
        source.
    """
    # 1. hass_frontend chunked JSON
    result = _load_hass_mdi_metadata()
    if result is not None:
        mdi_dir, parts, starts = result
        idx = bisect.bisect_right(starts, name) - 1
        if idx >= 0:
            chunk_file = parts[idx].get("file", "")
            if chunk_file:
                chunk = _load_mdi_chunk(mdi_dir / f"{chunk_file}.json")
                d = chunk.get(name)
                if d is not None:
                    return (d,)

    # 2. npm @mdi/svg fallback (not found above, or dev/testing)
    npm_dir = _NPM_MDI_DIR
    if npm_dir.exists():
        npm_path = (npm_dir / f"{name}.svg").resolve()
        # Defence-in-depth: _mdi_svg_filter validates the name, but
        # guard against path traversal at the filesystem level in
        # case this helper is called from new code.
        if npm_path.is_relative_to(npm_dir.resolve()) and npm_path.exists():
            return _load_svg_paths(npm_path)

    return None


def _mdi_svg_filter(name: str, size: int) -> str:
    """Inline an MDI icon as a sized SVG element.

    Resolves the icon via ``_resolve_mdi_path()``: first from the
    ``hass_frontend`` chunked JSON (always present on HA), then from
    the npm ``@mdi/svg`` package (present after ``pnpm install``).

    Args:
        name: MDI icon name without the ``mdi:`` prefix (e.g.
            ``"thermometer"``).
        size: Output width and height in pixels.

    Returns:
        Inline SVG string ready to embed in a parent SVG document.

    Raises:
        ValueError: If ``name`` contains path traversal components
            (``/`` or a leading ``.``).
        FileNotFoundError: If the icon cannot be resolved from any
            available source.
    """
    if "/" in name or name.startswith("."):
        raise ValueError(f"Invalid icon name: {name!r}")
    paths = _resolve_mdi_path(name)
    if paths is None:
        raise FileNotFoundError(name)
    return markupsafe.Markup(_build_inline_svg(paths, size, "0 0 24 24"))


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

type SvgContextFn = Callable[[Widget, DisplayConfig], dict[str, object]]

# Import widget builders at module bottom to avoid circular imports:
# widget modules import from _helpers which imports _mdi_svg_filter
# from this module; by this point all icon/filter helpers exist in
# the partially-loaded svg_render module namespace.
from .widgets import (  # noqa: E402
    _build_calendar_context,
    _build_device_battery_context,
    _build_entities_context,
    _build_entity_context,
    _build_frame_context,
    _build_gauge_context,
    _build_graph_context,
    _build_heading_context,
    _build_sensor_context,
    _build_separator_context,
    _build_tile_context,
    _build_waste_schedule_context,
    _build_weather_context,
)

_SVG_RENDERERS: dict[str, SvgContextFn] = {
    WidgetType.CALENDAR: _build_calendar_context,
    WidgetType.DEVICE_BATTERY: _build_device_battery_context,
    WidgetType.ENTITIES: _build_entities_context,
    WidgetType.ENTITY: _build_entity_context,
    WidgetType.FRAME: _build_frame_context,
    WidgetType.GAUGE: _build_gauge_context,
    WidgetType.GRAPH: _build_graph_context,
    WidgetType.HEADING: _build_heading_context,
    WidgetType.SENSOR: _build_sensor_context,
    WidgetType.SEPARATOR: _build_separator_context,
    WidgetType.TILE: _build_tile_context,
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

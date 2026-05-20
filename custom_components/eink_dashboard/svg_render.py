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
import contextlib
import functools
import json
from collections.abc import Callable
from dataclasses import fields as dc_fields
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, cast

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
    COLOR_LIGHT_GRAY,
    COLOR_WHITE,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
    FONT_SIZE_WEATHER,
    PADDING,
    Align,
    WidgetType,
)

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
        Dict mapping ``hex_black``, ``hex_white``,
        ``hex_gray``, and ``hex_light_gray`` to their
        SVG hex color strings.
    """
    # Lazy import avoids circular dependency (same pattern as
    # _compute_metrics imports elsewhere in this file).
    from .render import color_to_hex

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
    from .render import format_number  # lazy; avoids circular import

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
    from .render import DEFAULT_METRICS, _compute_metrics, color_to_hex

    x = widget.get("x", PADDING)
    y = widget.get("y", 0)
    text = widget.get("text", "")
    font_size = widget.get("font_size", DEFAULT_METRICS.font_primary)
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


# Weather base geometry at scale=1.0
# (font_size == FONT_SIZE_WEATHER == 32).  Each value is multiplied
# by `scale` in _build_weather_context() to adapt to the configured
# font_size.  These constants are weather-specific and have no
# equivalent in WidgetMetrics; padding and divider thickness are
# derived from _compute_metrics() directly inside the builder.
#
# _WX_ROW_H must be defined first; other derived constants reference it.
_WX_ROW_H = 48  # 48, not DEFAULT_ROW_H (56): matches original PIL proportions
_WX_NATURAL_W = 380  # natural card width
_WX_ICON = 80  # condition icon diameter
_WX_FONT_XL = 64  # temperature font size (bold)
_WX_FONT_SM = 16  # hi/lo, detail, and forecast font
_WX_FONT_XS = 14  # precipitation text font
_WX_ICON_R_PAD = 16  # gap: condition icon → temp text
_WX_DETAIL_GAP = 2  # vertical gap above detail row
_WX_DETAIL_ICON_H = 20  # detail icon height
_WX_ICON_GAP = 4  # gap: detail icon → its text
_WX_SEP_GAP = 8  # gap above/below separator line
_WX_FC_ZONE_H = 88  # forecast zone height
_WX_PRECIP_H = _WX_FONT_SM  # line height matches font
_WX_FC_ICON = 32  # forecast day icon diameter
_WX_FC_ICON_CY = 34  # forecast icon centre Y offset
_WX_FC_HI_Y = 52  # forecast hi-temp text Y offset
_WX_FC_LO_Y = 70  # forecast lo-temp text Y offset
_WX_FC_PRECIP_Y = _WX_FC_ZONE_H  # precip text at zone bottom
_WX_MIN_FC_COLS = 5  # minimum forecast column count
_WX_LO_Y_FRAC = 0.4  # lo temp Y as fraction of temp_h
_WX_PRECIP_Y_FRAC = 0.72  # precip text Y as fraction of temp_h

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
        card_w = min(round(_WX_NATURAL_W * scale), svg_w)
        # Clip SVG to content width so the editor resize box
        # matches the rendered content, not the full canvas.
        svg_w = _widget_dim(widget, "w", card_w)

    # PIL fonts for text measurement only — never used for
    # drawing.  Affects: temp_h, temp_bbox (getbbox) and
    # text_w_i (getlength) below.
    # Bold is used for font_xl because the temperature text renders
    # with font-weight="bold" in the SVG template.
    font_xl = _load_font(round(_WX_FONT_XL * scale), bold=True)
    font_sm = _load_font(round(_WX_FONT_SM * scale))

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

    # Card metrics — 48 at scale=1 gives card-level metrics
    # (padding~10, radius~10) matching the original PIL layout.
    m = _compute_metrics(round(_WX_ROW_H * scale))

    # Sizing constants, all proportional to scale.
    icon_size = round(_WX_ICON * scale)
    pad = m.padding
    icon_right_pad = round(_WX_ICON_R_PAD * scale)
    detail_gap = round(_WX_DETAIL_GAP * scale)
    detail_icon_h = round(_WX_DETAIL_ICON_H * scale)
    icon_gap = round(_WX_ICON_GAP * scale)
    sep_gap = round(_WX_SEP_GAP * scale)
    sep_thickness = m.divider
    forecast_zone_h = round(_WX_FC_ZONE_H * scale)
    precip_text_h = round(_WX_PRECIP_H * scale)

    # Measure temperature text height (PIL) for height estimation.
    nf = config.get("number_format", "language")
    lang = config.get("language", "en")
    temp_text = f"{_fmt_temp(temp, nf, lang)}{temp_unit}"
    temp_bbox = font_xl.getbbox(temp_text)
    temp_h = temp_bbox[3] - temp_bbox[1]

    top_pad = m.padding

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
    lo_y = vis_top + round(temp_h * _WX_LO_Y_FRAC)
    precip_y = vis_top + round(temp_h * _WX_PRECIP_Y_FRAC)
    precip_unit_fc = attrs.get("precipitation_unit", "mm")
    if forecast:
        today = forecast[0]
        hi_val = today.get("temperature")
        lo_val = today.get("templow")
        p_val = today.get("precipitation")
        if hi_val is not None:
            today_hi = f"{_fmt_temp(hi_val, nf, lang)}°"
        if lo_val is not None:
            today_lo = f"{_fmt_temp(lo_val, nf, lang)}°"
        if p_val is not None:
            today_precip = f"{_fmt(str(p_val), config)}{precip_unit_fc}"

    # Cap font_xl so temp text doesn't overlap the hi/lo column.
    font_xl_size = _cap_weather_font_xl(
        round(_WX_FONT_XL * scale),
        font_xl,
        font_sm,
        _load_font(round(_WX_FONT_XS * scale)),
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
        raw_details.append(("humidity", f"{_fmt(str(humidity), config)}%"))
    if pressure is not None:
        raw_details.append(
            (
                "barometer",
                f"{_fmt(str(round(pressure)), config)}{pressure_unit}",
            )
        )
    if wind is not None:
        raw_details.append(
            (
                "wind",
                f"{_fmt(str(round(wind)), config)}{wind_unit}",
            )
        )
    if cloud_coverage is not None:
        raw_details.append(
            (
                "cloud",
                f"{_fmt(str(cloud_coverage), config)}%",
            )
        )

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
        forecast_cols = max(forecast_days, _WX_MIN_FC_COLS)
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
        fc_icon_size = round(_WX_FC_ICON * scale)

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
            fc_hi = (
                f"{_fmt_temp(fc_hi_val, nf, lang)}°" if fc_hi_val != "" else ""
            )
            fc_lo = (
                f"{_fmt_temp(fc_lo_val, nf, lang)}°" if fc_lo_val != "" else ""
            )
            fc_p = day.get("precipitation")
            fc_precip = (
                f"{_fmt(str(fc_p), config)}{precip_unit_fc}"
                if fc_p is not None and fc_p > 0
                else ""
            )
            icon_cy_fc = forecast_y + round(_WX_FC_ICON_CY * scale)
            forecast_entries.append(
                {
                    "cx": cx,
                    "label": day_label,
                    "label_y": forecast_y,
                    "icon_svg": fc_icon_svg,
                    "icon_x": cx - fc_icon_size // 2,
                    "icon_y": icon_cy_fc - fc_icon_size // 2,
                    "hi": fc_hi,
                    "hi_y": forecast_y + round(_WX_FC_HI_Y * scale),
                    "lo": fc_lo,
                    "lo_y": forecast_y + round(_WX_FC_LO_Y * scale),
                    "precip": fc_precip,
                    "precip_y": forecast_y + round(_WX_FC_PRECIP_Y * scale),
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
        "font_sm": round(_WX_FONT_SM * scale),
        # font_xs is template-only; no PIL measurement needed.
        "font_xs": round(_WX_FONT_XS * scale),
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
        if icon_name is None:
            raw = attrs.get("icon", "")
            if raw.startswith("mdi:"):
                icon_name = raw[4:]

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
        fmtd = _fmt(state_val, config)
        secondary = f"{fmtd}{unit}" if unit else fmtd

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
    # h: raw geometry reference for proportional calculations.
    # svg_h: clamped SVG viewport height (minimum 1 via _widget_dim).
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

    # Chip sizing — icon_dia and icon_inner come from
    # _compute_metrics() so they match card_row at the same
    # height.
    pad = chip_h * 18 // 100
    icon_dia = m.icon_dia
    chip_icon_inner = m.icon_inner
    icon_gap = chip_h * 14 // 100
    font_sz = max(10, chip_h * 46 // 100)
    # PIL font for text measurement only — resvg does not
    # expose text metrics, so widths are pre-computed here.
    font = _load_font(font_sz)
    # Vertical gap between wrapped label rows.
    inter_gap = chip_h * 18 // 100

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
                        chip_icon_inner,
                    )

        has_icon = bool(icon_svg)
        icon_w = (icon_dia + icon_gap) if has_icon else 0
        # Label width: 2*pad + icon area + text ink width.
        state_display = _fmt(state_val, config)
        text = (
            f"{label} · {state_display.capitalize()}" if show_state else label
        )
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
        "chip_pad": pad,
        "chip_icon_dia": icon_dia,
        "chip_icon_inner": chip_icon_inner,
        "chip_icon_gap": icon_gap,
        "chip_font_sz": font_sz,
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


def _build_tile_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the tile widget.

    Single-entity card with icon circle on the left, entity name
    as primary text, and optional state text as secondary.  Mirrors
    HA's Tile card (``hui-tile-card.ts``).

    Icon circle style is controlled by the ``icon_style`` config
    field:

    - ``"filled"`` — gray circle background, white icon (default
      for active entities).
    - ``"outlined"`` — white fill, black stroke circle, black icon
      (default for inactive entities).
    - ``"none"`` — no circle; icon is rendered in black.

    When ``icon_style`` is absent the style is chosen automatically:
    2-level displays always use ``"outlined"``; multi-level displays
    use ``"filled"`` for active states (per ``_ACTIVE_STATES``) and
    ``"outlined"`` otherwise.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (required entity ID),
            ``name`` (display name override),
            ``icon`` (MDI icon override, e.g. ``"mdi:lightbulb"``),
            ``hide_state`` (suppress secondary text),
            ``state_content`` (attribute name or list; first element
            used when a list is provided),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``), ``card_style``,
            ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``height``,
            ``states``, and ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``tile.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False}`` when
        the entity is absent from ``states``.  Full context
        includes: widget dimensions (``w``, ``h``), layout
        geometry (``row_h``, ``x_off``, ``r_inset``, ``lpad``,
        ``rpad``), metrics fields (``m_*`` prefix), color hex
        strings (``hex_*`` prefix), text content (``primary``,
        ``secondary``), icon data (``icon_svg``, ``letter``),
        and icon style flags (``icon_fill``, ``icon_outline``,
        ``icon_no_circle``).  The ``card_row`` ``value`` key is
        intentionally omitted — tiles have no right-aligned
        value text; the macro defaults to ``""``.
    """
    from .render import (
        _compute_metrics,
        _device_class_icon,
        color_to_hex,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    entity_id: str = widget.get("entity", "")
    name_override = widget.get("name")
    icon_override = widget.get("icon")
    hide_state: bool = widget.get("hide_state", False)
    state_content = widget.get("state_content")
    icon_style = widget.get("icon_style")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)

    state = states.get(entity_id) if entity_id else None
    if state is None:
        return {
            "w": svg_w,
            "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
            "has_entity": False,
            **_color_context(),
        }

    # Single row: row_h equals svg_h.  Kept as a separate
    # variable so card_row receives the same parameter name
    # as in multi-row widgets (sensor_rows, waste_schedule).
    svg_h = _widget_dim(widget, "h", _auto_row_height("", 1))
    row_h = svg_h
    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    # Zero lpad/rpad when card_container already insets that side.
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    attrs = state.get("attributes", {})
    domain = entity_id.split(".")[0] if entity_id else ""
    state_val = state.get("state", "")

    # Primary text: name override or entity friendly_name.
    primary: str = (
        str(name_override)
        if name_override is not None
        else attrs.get("friendly_name", entity_id)
    )

    # Secondary text: attribute, default state+unit, or hidden.
    if hide_state:
        secondary: str = ""
    elif state_content is not None:
        sc: str = (
            state_content[0]
            if isinstance(state_content, list) and state_content
            else (state_content if not isinstance(state_content, list) else "")
        )
        secondary = _fmt(str(attrs.get(sc, "")), config) if sc else ""
    else:
        unit = attrs.get("unit_of_measurement", "")
        fmtd = _fmt(state_val, config)
        secondary = f"{fmtd}{unit}" if unit else fmtd

    # Icon: explicit override → letter fallback when not found.
    # No override → device_class → letter fallback.
    # When an explicit icon is requested and its file is absent,
    # skip device_class lookup so the user's intent is respected.
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

    # Icon style: explicit config overrides auto-switching.
    is_active = state_val in _ACTIVE_STATES
    if icon_style is None:
        # 2-level displays use outlined for maximum contrast.
        # Multi-level displays switch by entity state.
        if grayscale_levels <= 2:
            resolved_style = "outlined"
        elif is_active:
            resolved_style = "filled"
        else:
            resolved_style = "outlined"
    else:
        resolved_style = str(icon_style)

    icon_outline = resolved_style == "outlined"
    icon_no_circle = resolved_style == "none"
    # Filled style always uses gray; state is conveyed by
    # icon_style (filled vs outlined), not fill colour.
    icon_fill = color_to_hex(COLOR_GRAY)
    # Widen the outline stroke on 2-level displays to avoid dithering.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border

    return {
        "w": svg_w,
        "h": svg_h,
        "has_entity": True,
        "card_style": card_style,
        "bar_width": bar_width,
        **_metrics_context(m),
        **_color_context(),
        "row_h": row_h,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
        "primary": primary,
        "secondary": secondary,
        "icon_svg": icon_svg,
        "icon_fill": icon_fill,
        "icon_outline": icon_outline,
        "icon_no_circle": icon_no_circle,
        "icon_stroke_w": icon_stroke_w,
        "letter": letter,
    }


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
    - ``"subtitle"`` — Roboto Regular at ``font_secondary``, gray fill.

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
    from .render import (
        _compute_metrics,
        _device_class_icon,
        _load_font,
        color_to_hex,
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
    x_off, _r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)

    # Heading style: title (default) = large black; subtitle = small gray.
    is_title = heading_style != "subtitle"
    font_sz = m.font_primary if is_title else m.font_secondary
    font_weight = "500" if is_title else "400"
    colors = _color_context()
    text_fill = colors["hex_black"] if is_title else colors["hex_gray"]

    # Icon resolution: glyph size depends on circle style.
    icon_no_circle = icon_style == "none"
    icon_outline = icon_style == "outlined"
    # Widen the outline stroke on 2-level displays to avoid dithering.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    icon_svg: markupsafe.Markup | str = ""
    glyph_sz = max(10, font_sz) if icon_no_circle else m.icon_inner
    if icon_override is not None:
        icon_name = str(icon_override)
        if icon_name.startswith("mdi:"):
            icon_name = icon_name[4:]
        with contextlib.suppress(FileNotFoundError):
            icon_svg = _mdi_svg_filter(icon_name, glyph_sz)

    # Icon geometry: two modes depending on whether a circle is drawn.
    icon_cx = icon_cy = icon_r = 0
    icon_fill = ""
    icon_glyph_x = icon_glyph_y = 0
    content_left = x_off + m.padding
    if icon_svg:
        if icon_no_circle:
            # No circle: glyph sits flush at the content left edge.
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
            b_name: str | None = None
            # User-supplied icon override takes priority.
            if badge_icon_override.startswith("mdi:"):
                b_name = badge_icon_override[4:]
            if b_name is None:
                domain = entity_id.split(".")[0]
                b_name = _device_class_icon(attrs, state_val, domain)
            if b_name is None:
                raw = attrs.get("icon", "")
                if raw.startswith("mdi:"):
                    b_name = raw[4:]
            if b_name:
                with contextlib.suppress(FileNotFoundError):
                    badge_icon_svg = _mdi_svg_filter(b_name, badge_icon_sz)

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

    # Position badges right-to-left.  Once a badge cannot fit (its
    # left edge would overlap the heading text), it and all remaining
    # badges to its left in config order are dropped.
    badge_right = svg_w - m.padding
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
    from .render import (
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


def _build_entity_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the entity widget.

    Renders a two-section card: a header row (entity name on the
    left, optional icon on the right) and an info section below
    (large state value with optional unit).  Mirrors HA's Entity
    card (``hui-entity-card.ts``).

    Icon style controls circle rendering, with automatic resolution
    based on entity state when ``icon_style`` is omitted:

    - ``"filled"`` — gray-filled circle (default for active states
      when ``grayscale_levels > 2``).
    - ``"outlined"`` — white circle with black stroke (default for
      inactive states and all 2-level displays).
    - ``"none"`` — no circle; icon glyph rendered without decoration.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, required),
            ``name`` (display name override),
            ``icon`` (MDI icon name, e.g. ``"mdi:thermometer"``),
            ``attribute`` (attribute key to show as value instead of
            state),
            ``unit`` (unit string override),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``entity.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing.
        Full context includes widget dimensions, card style,
        metrics, colors, icon geometry, header text, and info
        section value/unit.
    """
    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", 2 * DEFAULT_ROW_H)
    attribute: str | None = widget.get("attribute")
    ctx = _entity_info_context(
        widget, config, svg_h, svg_w, svg_h, attribute=attribute
    )
    if ctx is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            **_color_context(),
        }
    return ctx


def _build_entities_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the entities widget.

    Multi-entity list card with optional title and per-row types.
    Mirrors HA's Entities card (``hui-entities-card.ts``).

    Each item in the ``entities`` config list is classified as one
    of three row types:

    - **Entity row** — a plain string entity ID, or a dict with an
      ``entity`` key (and optional ``name`` / ``icon`` overrides).
      Rendered with icon circle, primary text, and right-aligned
      state value.
    - **Divider row** — ``{"type": "divider"}``.  Rendered as a
      thin gray horizontal line.
    - **Section row** — ``{"type": "section", "label": str}``.
      Rendered as a gray sub-heading above the next group.

    Entity rows whose entity ID is absent from ``states`` are
    silently skipped.  The widget returns ``has_rows=False`` when
    no entity rows remain after filtering.

    Icon style is widget-level and applies uniformly to all entity
    rows:

    - ``"filled"`` — gray-filled circle, white icon (default for
      active states on multi-level displays).
    - ``"outlined"`` — white fill, black stroke circle, black icon
      (default for inactive states and 2-level displays).
    - ``"none"`` — no circle; icon glyph rendered in black.

    Auto-dividers — thin gray lines drawn between consecutive entity
    rows — are suppressed when a divider or section row follows the
    entity row, since those rows provide their own visual break.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entities`` (list of row configs),
            ``title`` (optional label above the card),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``), ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``entities.svg.j2``.
        Returns ``{"w": …, "h": …, "has_rows": False,
        **_color_context()}`` when no entity rows survive
        state filtering.  Full context includes ``w``, ``h``,
        ``has_rows``, title layout fields, card geometry,
        metrics (``m_*``), colors (``hex_*``), row list and
        per-row layout dicts.
    """
    from .render import (
        _compute_metrics,
        _device_class_icon,
        color_to_hex,
    )

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    title: str = widget.get("title", "")
    icon_style = widget.get("icon_style")
    card_style = widget.get("card_style", DEFAULT_CARD_STYLE)
    entity_configs: list = widget.get("entities", [])
    states = config.get("states", {})
    grayscale_levels = config.get("grayscale_levels", 16)
    colors = _color_context()

    # --- Classify rows ---
    # Absent entity states are filtered out here so layout counts
    # reflect what will actually be rendered.
    classified: list[dict[str, object]] = []
    for entry in entity_configs:
        if isinstance(entry, str):
            if entry in states:
                classified.append(
                    {
                        "row_type": "entity",
                        "entity_id": entry,
                        "name_override": None,
                        "icon_override": None,
                    }
                )
        elif isinstance(entry, dict):
            row_type = entry.get("type")
            if row_type == "divider":
                classified.append({"row_type": "divider"})
            elif row_type == "section":
                classified.append(
                    {
                        "row_type": "section",
                        "label": str(entry.get("label", "")),
                    }
                )
            else:
                eid: str = str(entry.get("entity", ""))
                if eid and eid in states:
                    classified.append(
                        {
                            "row_type": "entity",
                            "entity_id": eid,
                            "name_override": entry.get("name"),
                            "icon_override": entry.get("icon"),
                        }
                    )

    n_entity = sum(1 for r in classified if r["row_type"] == "entity")
    if n_entity == 0:
        return {
            "w": svg_w,
            "h": _widget_dim(widget, "h", DEFAULT_ROW_H),
            "has_rows": False,
            **colors,
        }

    n_divider = sum(1 for r in classified if r["row_type"] == "divider")
    n_section = sum(1 for r in classified if r["row_type"] == "section")

    # Divider takes 15% of an entity row height.
    divider_h_base = round(DEFAULT_ROW_H * 0.15)
    # Section sub-heading takes 60% of an entity row height.
    section_h_base = round(DEFAULT_ROW_H * 0.6)

    # --- Height ---
    if "h" not in widget:
        # Auto-height: delegate to the shared fixpoint helper,
        # passing a heterogeneous content_target that accounts for
        # the mix of entity, divider, and section row heights.
        content_target = (
            n_entity * DEFAULT_ROW_H
            + n_divider * divider_h_base
            + n_section * section_h_base
        )
        svg_h = _auto_row_height(
            title,
            max(1, n_entity),
            content_target=content_target,
        )
        title_font_sz, content_y, content_h = _title_layout(title, svg_h)
        row_h = DEFAULT_ROW_H
    else:
        svg_h = _widget_dim(widget, "h", DEFAULT_ROW_H)
        title_font_sz, content_y, content_h = _title_layout(title, svg_h)
        # Proportional allocation: entity rows have weight 1,
        # divider rows 0.15, section rows 0.6.
        total_weight = n_entity + n_divider * 0.15 + n_section * 0.6
        row_h = max(1, round(content_h / total_weight))

    # Sub-row heights scale with row_h.
    # Divider takes 15% of an entity row height.
    divider_h = max(1, round(row_h * 0.15))
    # Section sub-heading takes 60% of an entity row height.
    section_h = max(1, round(row_h * 0.6))

    m = _compute_metrics(row_h)
    x_off, r_inset, bar_width = _card_insets(m, card_style, grayscale_levels)
    lpad = m.padding if x_off == 0 else 0
    rpad = m.padding if r_inset == 0 else 0

    # Widen outline stroke on 2-level displays to avoid dithering.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    # Widen divider lines on 2-level displays (same rationale).
    divider_stroke_w = m.divider * 3 if grayscale_levels <= 2 else m.divider
    icon_fill = color_to_hex(COLOR_GRAY)
    # Section label font ~46% of row height (matches chip label ratio).
    section_font_sz = round(row_h * 0.46)

    # --- Build row dicts ---
    rows: list[dict[str, object]] = []
    y = content_y  # absolute SVG y pointer within the canvas

    for i, cls in enumerate(classified):
        if cls["row_type"] == "divider":
            rows.append(
                {
                    "row_type": "divider",
                    "line_y": y + divider_h // 2,
                }
            )
            y += divider_h

        elif cls["row_type"] == "section":
            rows.append(
                {
                    "row_type": "section",
                    "label": str(cls.get("label", "")),
                    "font_sz": section_font_sz,
                    "text_y": y + section_h // 2,
                }
            )
            y += section_h

        else:
            entity_id = str(cls["entity_id"])
            name_override = cls["name_override"]
            icon_override = cls["icon_override"]
            state = states[entity_id]
            attrs = state.get("attributes", {})
            domain = entity_id.split(".")[0]
            state_val: str = state.get("state", "")

            primary: str = (
                str(name_override)
                if name_override is not None
                else attrs.get("friendly_name", entity_id)
            )

            unit = attrs.get("unit_of_measurement", "")
            fmtd = _fmt(state_val, config)
            value = f"{fmtd}{unit}" if unit else fmtd

            # Icon: explicit override → device_class →
            # attrs["icon"] → letter fallback.
            icon_svg: markupsafe.Markup | str = ""
            if icon_override is not None:
                icon_name: str | None = str(icon_override)
                if icon_name.startswith("mdi:"):
                    icon_name = icon_name[4:]
                with contextlib.suppress(FileNotFoundError):
                    icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)
            else:
                icon_name = _device_class_icon(attrs, state_val, domain)
                if icon_name is None:
                    raw = attrs.get("icon", "")
                    if raw.startswith("mdi:"):
                        icon_name = raw[4:]
                if icon_name:
                    with contextlib.suppress(FileNotFoundError):
                        icon_svg = _mdi_svg_filter(icon_name, m.icon_inner)

            letter = ""
            if not icon_svg:
                friendly = attrs.get("friendly_name", entity_id)
                letter = friendly[:1].upper() if friendly else ""

            # Icon style: widget-level or auto by entity state.
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

            # Auto-divider: draw after this entity row only when
            # the immediately following row is also an entity row.
            # Explicit divider/section rows break the chain.
            draw_divider = (
                i + 1 < len(classified)
                and classified[i + 1]["row_type"] == "entity"
            )

            # Clamp so rounding in the proportional-height branch
            # cannot push the last row past the content area bottom.
            row_y = min(y, content_y + content_h - row_h)
            rows.append(
                {
                    "row_type": "entity",
                    "y": row_y,
                    "primary": primary,
                    "value": value,
                    "icon_svg": icon_svg,
                    "icon_fill": icon_fill,
                    "icon_outline": icon_outline,
                    "icon_no_circle": icon_no_circle,
                    "letter": letter,
                    "draw_divider": draw_divider,
                }
            )
            y += row_h

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
        **colors,
        "row_h": row_h,
        "rows": rows,
        "x_off": x_off,
        "r_inset": r_inset,
        "lpad": lpad,
        "rpad": rpad,
        "icon_stroke_w": icon_stroke_w,
        "divider_stroke_w": divider_stroke_w,
    }


def _build_sensor_context(
    widget: Widget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build Jinja2 template context for the sensor widget.

    Renders a header row (entity name on the left, optional icon on
    the right), an info section (large state value with unit), and an
    optional history sparkline graph below.  Mirrors HA's Sensor card.

    Icon style follows the same auto-resolution logic as the Entity
    widget: active states → filled circle; inactive or 2-level
    displays → outlined circle; ``icon_style="none"`` hides the
    circle entirely.

    Without ``graph="line"``, the default height is
    ``2 * DEFAULT_ROW_H``.  With ``graph="line"``, the default is
    ``3 * DEFAULT_ROW_H`` (entity section + graph row).  History
    data is read from ``states[entity_id]["history"]``, injected by
    ``_fetch_history()`` in ``__init__.py``.

    Args:
        widget: Widget config dict.  Recognised keys:
            ``entity`` (HA entity ID, required),
            ``name`` (display name override),
            ``icon`` (MDI icon name, e.g. ``"mdi:thermometer"``),
            ``unit`` (unit string override),
            ``icon_style`` (``"filled"`` / ``"outlined"`` /
            ``"none"``),
            ``graph`` (``"line"`` to enable history sparkline),
            ``hours_to_show`` (history window in hours; default 24),
            ``detail`` (``1`` for downsampled ~24 pts, ``2`` for
            full resolution; default 1),
            ``limits`` (dict with optional ``"min"``/``"max"``
            keys to fix the Y-axis range; editor uses flat
            ``limits_min``/``limits_max`` keys instead),
            ``card_style``, ``x``, ``w``, ``h``.
        config: Display config with ``width``, ``states``, and
            ``grayscale_levels``.

    Returns:
        Template context dict consumed by ``sensor.svg.j2``.
        Returns ``{"w": …, "h": …, "has_entity": False,
        **_color_context()}`` when the entity is missing.
        Full context includes widget dimensions, card style,
        metrics, colors, icon geometry, header text, info section
        value/unit, and graph polyline/fill data.
    """
    from .render import DEFAULT_METRICS

    x = widget.get("x", PADDING)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    graph: str | None = widget.get("graph")
    detail: int = int(float(widget.get("detail", 1)))
    hours_to_show: int = int(float(widget.get("hours_to_show", 24)))
    limits: dict[str, float] | None = widget.get("limits")
    if limits is None:
        # The frontend stores Y-axis bounds as flat keys rather than a
        # nested dict (ha-form does not support nested objects).
        lmin = widget.get("limits_min")
        lmax = widget.get("limits_max")
        if lmin is not None or lmax is not None:
            limits = {}
            if lmin is not None:
                limits["min"] = lmin
            if lmax is not None:
                limits["max"] = lmax
    grayscale_levels = config.get("grayscale_levels", 16)

    has_graph = graph == "line"
    # Default height: 3 rows with graph section, 2 rows without.
    default_h = 3 * DEFAULT_ROW_H if has_graph else 2 * DEFAULT_ROW_H
    svg_h = _widget_dim(widget, "h", default_h)
    # Graph occupies the bottom DEFAULT_ROW_H pixels; entity section
    # fills the rest.
    graph_h = DEFAULT_ROW_H if has_graph else 0
    entity_h = max(1, svg_h - graph_h)

    ctx = _entity_info_context(widget, config, entity_h, svg_w, svg_h)
    if ctx is None:
        return {
            "w": svg_w,
            "h": svg_h,
            "has_entity": False,
            **_color_context(),
        }

    # name_x = x_off + lpad (left content edge); icon_cx + icon_r =
    # svg_w - r_inset - rpad (right content edge without icon overlap).
    gx1: int = cast("int", ctx["name_x"])
    gx2: int = cast("int", ctx["icon_cx"]) + cast("int", ctx["icon_r"])

    # --- Graph section ---
    polyline_points = ""
    fill_points = ""
    # Graph stroke uses DEFAULT_METRICS (fixed at DEFAULT_ROW_H) because
    # the graph zone is always DEFAULT_ROW_H pixels tall regardless of
    # entity section height.  Widened 2× on 2-level displays.
    graph_stroke_w = (
        DEFAULT_METRICS.border * 2
        if grayscale_levels <= 2
        else DEFAULT_METRICS.border
    )

    if has_graph:
        entity_id: str = widget.get("entity", "")
        state = config.get("states", {}).get(entity_id, {})
        history: list[dict[str, object]] = state.get("history", [])
        # Apply hours_to_show window: keep only entries whose timestamp
        # falls within the most recent hours_to_show hours.
        if history:
            t_latest = max(float(str(e.get("lu", 0))) for e in history)
            cutoff = t_latest - hours_to_show * 3600
            history = [
                e for e in history if float(str(e.get("lu", 0))) > cutoff
            ]
        # Filter entries to numeric values only; skip unavailable /
        # unknown / on/off states so only plottable data remains.
        numeric: list[tuple[float, float]] = []
        for entry in history:
            s = entry.get("s", "")
            lu = entry.get("lu", 0.0)
            try:
                val = float(str(s))
                numeric.append((float(str(lu)), val))
            except (ValueError, TypeError):
                continue

        if len(numeric) >= 2:
            # Downsample to ~24 points for detail=1 to avoid
            # pixel-level noise on small sparklines.
            if detail <= 1 and len(numeric) > 24:
                step = len(numeric) / 24
                indices = {round(i * step) for i in range(24)}
                indices.add(len(numeric) - 1)
                numeric = [
                    numeric[i] for i in sorted(indices) if i < len(numeric)
                ]

            # Y range: explicit limits override auto min/max.
            # isinstance guard rejects null or string values gracefully.
            values = [v for _, v in numeric]
            y_min = (
                float(limits["min"])
                if limits
                and "min" in limits
                and isinstance(limits["min"], (int, float))
                else min(values)
            )
            y_max = (
                float(limits["max"])
                if limits
                and "max" in limits
                and isinstance(limits["max"], (int, float))
                else max(values)
            )
            if y_max == y_min:
                # Flat line: add a unit pad so the polyline is
                # centred rather than collapsed to the bottom edge.
                y_max += 1.0

            # Inset by 2× stroke width so the polyline stays
            # inside the widget bounds (wider on 2-level displays).
            margin = graph_stroke_w * 2
            gy1 = entity_h + margin
            gy2 = svg_h - margin

            timestamps = [t for t, _ in numeric]
            t_min = min(timestamps)
            t_range = max(max(timestamps) - t_min, 1.0)
            y_range = y_max - y_min

            # Map (timestamp, value) → (x, y) pixel; Y is inverted.
            pts = [
                (
                    round(gx1 + (t - t_min) / t_range * (gx2 - gx1)),
                    round(gy2 - (v - y_min) / y_range * (gy2 - gy1)),
                )
                for t, v in numeric
            ]
            polyline_points = " ".join(f"{px},{py}" for px, py in pts)
            # Fill polygon rendered on all display types; on 2-level
            # displays Floyd-Steinberg dithering in optimize.py
            # converts the light-gray fill to a dot pattern.
            bottom = gy2
            fill_pts = [
                *pts,
                (pts[-1][0], bottom),
                (pts[0][0], bottom),
            ]
            fill_points = " ".join(f"{px},{py}" for px, py in fill_pts)

    return {
        **ctx,
        # Graph.
        "has_graph": has_graph,
        "polyline_points": polyline_points,
        "fill_points": fill_points,
        "graph_stroke_w": graph_stroke_w,
    }


_SVG_RENDERERS: dict[str, SvgContextFn] = {
    WidgetType.DEVICE_BATTERY: _build_device_battery_context,
    WidgetType.ENTITIES: _build_entities_context,
    WidgetType.ENTITY: _build_entity_context,
    WidgetType.HEADING: _build_heading_context,
    WidgetType.SENSOR: _build_sensor_context,
    WidgetType.SENSOR_ROWS: _build_sensor_rows_context,
    WidgetType.SEPARATOR: _build_separator_context,
    WidgetType.STATUS_ICONS: _build_status_icons_context,
    WidgetType.TEXT: _build_text_context,
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

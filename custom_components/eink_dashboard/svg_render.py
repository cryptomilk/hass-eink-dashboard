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
    COLOR_LIGHT_GRAY,
    COLOR_WHITE,
    DEFAULT_CARD_STYLE,
    DEFAULT_ROW_H,
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


# Import widget builders at module bottom to avoid circular imports:
# widget modules import helpers defined above; by this point all
# helpers exist in the partially-loaded svg_render module namespace.
from .widgets import (  # noqa: E402
    _build_device_battery_context,
    _build_entities_context,
    _build_entity_context,
    _build_heading_context,
    _build_sensor_context,
    _build_separator_context,
    _build_tile_context,
    _build_waste_schedule_context,
    _build_weather_context,
)

_SVG_RENDERERS: dict[str, SvgContextFn] = {
    WidgetType.DEVICE_BATTERY: _build_device_battery_context,
    WidgetType.ENTITIES: _build_entities_context,
    WidgetType.ENTITY: _build_entity_context,
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

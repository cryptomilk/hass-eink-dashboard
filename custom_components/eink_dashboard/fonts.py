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

"""Bundled font selection shared by raster and SVG rendering."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from functools import cache
from pathlib import Path

from .const import DEFAULT_FONT_FAMILY, FontFamily

_FONT_SIZES = (12, 16, 21)
_FONT_ROOT = Path(__file__).parent / "fonts"
_CURRENT_FONT_FAMILY: ContextVar[FontFamily] = ContextVar(
    "eink_dashboard_font_family", default=DEFAULT_FONT_FAMILY
)
# Whether TRMNL sizes snap to their pixel grid.  Off outside a render
# context so direct measurements keep the requested size.
_PIXEL_FONTS: ContextVar[bool] = ContextVar(
    "eink_dashboard_pixel_fonts", default=False
)
# Largest integer multiple of a native TRMNL size considered when
# snapping; 12 * 20 = 240 px covers every realistic dashboard font.
_MAX_PIXEL_SCALE = 20


def coerce_font_family(value: object) -> FontFamily:
    """Return ``value`` as a ``FontFamily``.

    Every entry point that accepts a family name goes through this
    helper so unknown values resolve the same way everywhere.

    Args:
        value: Family name to look up, typically a ``FontFamily`` or
            a plain string from config or a template.

    Returns:
        The matching ``FontFamily``, or ``DEFAULT_FONT_FAMILY`` when
        ``value`` is not a known family name.
    """
    if isinstance(value, str) and value in FontFamily:
        return FontFamily(value)
    return DEFAULT_FONT_FAMILY


@contextmanager
def font_family_context(selected: str) -> Iterator[None]:
    """Temporarily select a font family for context-local measurements.

    Unknown names fall back to ``DEFAULT_FONT_FAMILY`` (see
    ``coerce_font_family()``).
    """
    token: Token[FontFamily] = _CURRENT_FONT_FAMILY.set(
        coerce_font_family(selected)
    )
    try:
        yield
    finally:
        _CURRENT_FONT_FAMILY.reset(token)


def current_font_family() -> FontFamily:
    """Return the font family selected in the current render context."""
    return _CURRENT_FONT_FAMILY.get()


@contextmanager
def pixel_fonts_context(enabled: bool) -> Iterator[None]:
    """Temporarily enable or disable TRMNL pixel-grid size snapping."""
    token: Token[bool] = _PIXEL_FONTS.set(bool(enabled))
    try:
        yield
    finally:
        _PIXEL_FONTS.reset(token)


def pixel_fonts_active() -> bool:
    """Return whether TRMNL text snaps to its pixel grid right now.

    Snapping only applies to the TRMNL family: it is a pixel font whose
    outlines sit on a 1/12, 1/16 or 1/21 em grid, while Roboto is an
    outline font that gains nothing from it.
    """
    return _PIXEL_FONTS.get() and current_font_family() == FontFamily.TRMNL


def pixel_font_size(size: float) -> int | float:
    """Return the font size to render, snapped when pixel fonts are on.

    TRMNL glyphs are drawn on a pixel grid, so they are only crisp at
    their native sizes (12, 16, 21 px) or integer multiples of them.
    At any other size the font pixels straddle device pixels and turn
    into uneven gray smudges, which a black/white threshold then
    fattens into blobs.  The nearest native size or multiple is
    chosen; ties round down so text never grows into its neighbours.

    Args:
        size: Requested font size in pixels.

    Returns:
        The snapped size when pixel fonts are active, otherwise
        ``size`` unchanged.
    """
    if not pixel_fonts_active():
        return size
    return _snap_pixel_size(size)[0]


@cache
def _snap_pixel_size(size: float) -> tuple[int, int]:
    """Return ``(snapped_size, native_size)`` for a TRMNL font size."""
    best: tuple[int, int] | None = None
    for native in _FONT_SIZES:
        for scale in range(1, _MAX_PIXEL_SCALE + 1):
            candidate = native * scale
            if best is None:
                best = (candidate, native)
                continue
            dist = abs(candidate - size)
            best_dist = abs(best[0] - size)
            # Prefer the closer size; on a tie prefer the smaller size,
            # and for equal sizes (48 = 4 x 12 = 3 x 16) the larger
            # native face, whose design is finer at that scale.
            if (dist, candidate, -native) < (best_dist, best[0], -best[1]):
                best = (candidate, native)
    assert best is not None
    return best


def font_family(size: float, selected: str | None = None) -> str:
    """Return the SVG ``font-family`` value for text at ``size``.

    Registered as the ``font_family`` Jinja filter.  TRMNL ships one
    family per optical size (``TRMNL12``, ``TRMNL16``, ``TRMNL21``), so
    the TRMNL entry always names the face matching ``size`` in the
    current render context (see ``_optical_size()``).

    Args:
        size: Font size in pixels the text is rendered at.
        selected: Family that should come first in the stack.  ``None``
            returns the bare TRMNL optical family name.  Unknown values
            fall back to ``DEFAULT_FONT_FAMILY``, exactly like
            ``font_family_context()``.

    Returns:
        ``"TRMNL<n>"`` when ``selected`` is ``None``, otherwise a
        two-entry stack with the selected family first and the other
        bundled family as glyph fallback, e.g. ``"Roboto, TRMNL16"``.
    """
    trmnl = f"TRMNL{_optical_size(size)}"
    if selected is None:
        return trmnl
    if coerce_font_family(selected) == FontFamily.ROBOTO:
        return f"{FontFamily.ROBOTO}, {trmnl}"
    return f"{trmnl}, {FontFamily.ROBOTO}"


def _optical_size(size: float) -> int:
    """Return the TRMNL face for ``size`` in the current render context.

    With pixel fonts active this is the native face whose grid divides
    the snapped size (24 px renders TRMNL12 at 2x); otherwise it is the
    closest optical size.
    """
    if pixel_fonts_active():
        return _snap_pixel_size(size)[1]
    return _closest_optical_size(size)


def _closest_optical_size(size: float) -> int:
    """Return the TRMNL optical size closest to the requested size."""
    optical_size = min(
        _FONT_SIZES, key=lambda candidate: abs(candidate - size)
    )
    return optical_size


def font_path(
    size: int,
    bold: bool = False,
    medium: bool = False,
    family: str | None = None,
) -> Path:
    """Return the bundled TTF path for a family, size, and weight.

    TRMNL ships only Regular and Bold faces, so ``medium`` is ignored
    for it and Regular is returned.  This matches what resvg draws for
    ``font-weight="500"``: with no 500 face, CSS font matching falls
    back to the closest lighter weight, 400.

    Args:
        size: Font size in pixels; selects the TRMNL optical size
            (Roboto has a single face per weight).
        bold: Return the Bold face.  Takes precedence over ``medium``.
        medium: Return Roboto Medium; ignored for TRMNL.
        family: Family to use.  ``None`` uses the family of the current
            render context; unknown names fall back to
            ``DEFAULT_FONT_FAMILY``.

    Returns:
        Path to the TTF file inside the bundled ``fonts/`` directory.
    """
    family = (
        current_font_family() if family is None else coerce_font_family(family)
    )
    if family == FontFamily.ROBOTO:
        weight = "Bold" if bold else "Medium" if medium else "Regular"
        return _FONT_ROOT / "Roboto" / f"Roboto-{weight}.ttf"
    weight = "Bold" if bold else "Regular"
    optical_size = _optical_size(size)
    return _FONT_ROOT / "TRMNL" / f"TRMNL{optical_size}-{weight}.ttf"

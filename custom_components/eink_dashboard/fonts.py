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
from pathlib import Path

from .const import DEFAULT_FONT_FAMILY, FONT_FAMILY_OPTIONS

_FONT_SIZES = (12, 16, 21)
_FONT_ROOT = Path(__file__).parent / "fonts"
_CURRENT_FONT_FAMILY: ContextVar[str] = ContextVar(
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


@contextmanager
def font_family_context(selected: str) -> Iterator[None]:
    """Temporarily select a font family for context-local measurements."""
    if selected not in FONT_FAMILY_OPTIONS:
        selected = DEFAULT_FONT_FAMILY
    token: Token[str] = _CURRENT_FONT_FAMILY.set(selected)
    try:
        yield
    finally:
        _CURRENT_FONT_FAMILY.reset(token)


def current_font_family() -> str:
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
    return _PIXEL_FONTS.get() and _CURRENT_FONT_FAMILY.get() == "TRMNL"


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


def font_family(size: int, selected: str | None = None) -> str:
    """Return an optical family name or selected-family-first SVG stack."""
    optical_size = _optical_size(size)
    if selected is None:
        return f"TRMNL{optical_size}"
    if selected == "Roboto":
        return f"Roboto, TRMNL{optical_size}"
    return f"TRMNL{optical_size}, Roboto"


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
    """Return the bundled TTF path for family, size, and weight."""
    family = family or _CURRENT_FONT_FAMILY.get()
    if family == "Roboto":
        weight = "Bold" if bold else "Medium" if medium else "Regular"
        return _FONT_ROOT / "Roboto" / f"Roboto-{weight}.ttf"
    weight = "Bold" if bold else "Regular"
    optical_size = _optical_size(size)
    return _FONT_ROOT / "TRMNL" / f"TRMNL{optical_size}-{weight}.ttf"

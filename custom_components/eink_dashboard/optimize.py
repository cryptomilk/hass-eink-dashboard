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

"""Post-render image optimization pipeline for e-ink displays."""

from __future__ import annotations

import logging

from epaper_dithering import (
    DitherMode,
    DitherOptions,
    Palette,
    dither_image,
)
from PIL import Image, ImageOps

from .const import (
    DEFAULT_DISPLAY_LEVELS,
    DEFAULT_DITHER_ALGORITHM,
    DEFAULT_EXPOSURE,
    DEFAULT_MEASURED_PALETTE,
    DEFAULT_SATURATION,
)

_LOGGER = logging.getLogger(__name__)

type _RGB = tuple[int, int, int]

# sRGB color that requests each named ink. epaper-dithering snaps a
# pixel of exactly this color to the ink without dithering it, so pure
# black text stays solid even on a measured palette whose black is
# lighter than #000000.
_INK_NOMINALS: dict[str, _RGB] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "green": (0, 255, 0),
}


def _ink_palette(inks: dict[str, _RGB], *, measured: bool = False) -> Palette:
    """Build an epaper-dithering palette of named inks.

    epaper-dithering 7 ships no built-in palettes, so every palette is
    built here from sRGB values. ``Palette.from_srgb()`` normalises all
    colors to the white ink, so a measured gray paper white becomes
    the panel's reference white.

    Args:
        inks: Mapping of ink name to the sRGB color the panel shows for
            that ink, in palette index order. Every name must be a key
            of ``_INK_NOMINALS``.
        measured: Whether the colors were measured on real hardware.
            Metadata only; it does not change the dithering.

    Returns:
        The validated palette.
    """
    return Palette.from_srgb(
        [(rgb, name, _INK_NOMINALS[name]) for name, rgb in inks.items()],
        measured=measured,
    )


def _ideal_palette(*names: str) -> Palette:
    """Build an idealized palette whose inks show their nominal color."""
    return _ink_palette({name: _INK_NOMINALS[name] for name in names})


def _gray_palette(levels: int) -> Palette:
    """Build an idealized palette of evenly spaced gray levels.

    Black and white keep their ink names. The levels in between are
    named ``gray1``, ``gray2``, ... and requested by their own sRGB
    value, so an exact gray level is kept without dithering.

    Args:
        levels: Number of gray levels including black and white.

    Returns:
        The validated palette, ordered from black to white.
    """
    entries: list[tuple[_RGB, str, _RGB]] = []
    for i in range(levels):
        value = round(i * 255 / (levels - 1))
        gray = (value, value, value)
        if i == 0:
            name = "black"
        elif i == levels - 1:
            name = "white"
        else:
            name = f"gray{i}"
        entries.append((gray, name, gray))
    return Palette.from_srgb(entries)


# Maps display_levels config values to idealized gray palettes.
_GRAYSCALE_PALETTES: dict[int, Palette] = {
    2: _gray_palette(2),
    4: _gray_palette(4),
    8: _gray_palette(8),  # Reserved for future Inkplate support
    16: _gray_palette(16),
}

# Maps color_scheme config strings to idealized palettes for color
# e-ink displays (BWR, BWY, Spectra, etc.). The ink order matches the
# color schemes of epaper-dithering 6.
_COLOR_PALETTES: dict[str, Palette] = {
    "bwr": _ideal_palette("black", "white", "red"),
    "bwy": _ideal_palette("black", "white", "yellow"),
    "bwry": _ideal_palette("black", "white", "yellow", "red"),
    "bwgbry": _ideal_palette(
        "black", "white", "yellow", "red", "blue", "green"
    ),
}

# Maps dither_algorithm config strings to epaper-dithering DitherMode.
# Only the algorithms exposed in the UI are included.  "none" maps each
# pixel to the nearest palette color without error diffusion; on a
# 2-level display that turns light grays (sRGB >= ~100) white.
_DITHER_MODES: dict[str, DitherMode] = {
    "floyd_steinberg": DitherMode.FLOYD_STEINBERG,
    "atkinson": DitherMode.ATKINSON,
    "stucki": DitherMode.STUCKI,
    "burkes": DitherMode.BURKES,
    "none": DitherMode.NONE,
}

# dither_algorithm value that bypasses the dithering library entirely
# and produces a pure black/white image in which every non-white pixel
# becomes black, so gray text and light dividers stay visible.
DITHER_THRESHOLD = "threshold"

# Maps measured_palette config strings to photographically calibrated
# palettes. "auto" is NOT a key here; it means "use the idealized
# palette" and is handled by the absence of a palette override.
# The sRGB values are the measured palettes that epaper-dithering 6
# shipped as built-in constants (e.g. BWRY_3_97); version 7 removed
# them.
_MEASURED_PALETTES: dict[str, Palette] = {
    "spectra_7_3_6color": _ink_palette(
        {
            "black": (26, 13, 35),
            "white": (185, 202, 205),
            "yellow": (202, 184, 0),
            "red": (121, 9, 0),
            "blue": (0, 69, 139),
            "green": (40, 82, 57),
        },
        measured=True,
    ),
    "spectra_7_3_6color_v2": _ink_palette(
        {
            "black": (31, 24, 41),
            "white": (168, 180, 182),
            "yellow": (180, 173, 0),
            "red": (113, 24, 19),
            "blue": (36, 70, 139),
            "green": (50, 84, 60),
        },
        measured=True,
    ),
    "mono_4_26": _ink_palette(
        {"black": (5, 5, 5), "white": (220, 220, 220)},
        measured=True,
    ),
    "bwry_4_2": _ink_palette(
        {
            "black": (5, 5, 5),
            "white": (200, 200, 200),
            "yellow": (200, 180, 0),
            "red": (120, 15, 5),
        },
        measured=True,
    ),
    "bwry_3_97": _ink_palette(
        {
            "black": (10, 7, 14),
            "white": (173, 178, 174),
            "yellow": (172, 128, 0),
            "red": (85, 24, 14),
        },
        measured=True,
    ),
    "solum_bwr": _ink_palette(
        {
            "black": (5, 5, 5),
            "white": (200, 200, 200),
            "red": (120, 15, 5),
        },
        measured=True,
    ),
    "hanshow_bwr": _ink_palette(
        {
            "black": (5, 5, 5),
            "white": (200, 200, 200),
            "red": (120, 15, 5),
        },
        measured=True,
    ),
    "hanshow_bwy": _ink_palette(
        {
            "black": (5, 5, 5),
            "white": (200, 200, 200),
            "yellow": (200, 180, 0),
        },
        measured=True,
    ),
}


def optimize_for_eink(
    img: Image.Image,
    config: dict,
) -> Image.Image:
    """Apply autocontrast and dithering to an image for e-ink display.

    Two dithering paths are supported:

    **Grayscale path** (``color_scheme`` absent or ``None``): the
    pipeline image is grayscale (``"L"`` mode). ``dither_image()``
    reads it as RGB. OKLab perceptual colour matching offered by
    epaper-dithering has no effect on equal-channel RGB triples
    derived from a grayscale source; quantisation is effectively
    luminance-only.

    **Color path** (``color_scheme`` set): the pipeline image must
    be ``"RGB"`` before calling this function; ``render_dashboard()``
    creates an ``"RGB"`` canvas when ``color_scheme`` is set. The
    idealized color palette is passed directly to ``dither_image()``.
    Output is converted from palette mode (``"P"``) to ``"RGB"``.
    The caller is responsible for passing an ``"RGB"`` image on this
    path; no silent mode conversion is performed.

    Args:
        img: PIL image from the render pipeline. ``"L"`` for grayscale
            displays, ``"RGB"`` for color displays.
        config: Display config dict. Recognised keys: ``optimize``
            (bool, required to enable the pipeline), ``exposure``
            (float, default 1.0; linear-RGB brightness multiplier
            applied inside ``dither_image()``; no effect when
            ``display_levels`` is 256), ``saturation``
            (float, default 1.0; OKLab chroma multiplier applied
            inside ``dither_image()``; no effect when
            ``display_levels`` is 256), ``color_scheme`` (str, one
            of ``"bwr"``, ``"bwy"``, ``"bwry"``, ``"bwgbry"``; ``None``
            or absent means grayscale), ``display_levels`` (int,
            one of 2/4/16/256, default 16; ignored when
            ``color_scheme`` is set; 256 means passthrough (only
            autocontrast is applied); 8 is reserved for future
            Inkplate support but is not offered in the UI),
            ``dither_algorithm`` (str, one of ``floyd_steinberg``,
            ``atkinson``, ``stucki``, ``burkes``, ``none``,
            ``threshold``; default ``floyd_steinberg``; ``none`` maps
            each pixel to the nearest palette color without error
            diffusion; ``threshold`` skips dithering and
            turns every non-white pixel black, producing a ``"1"``
            image on the grayscale path whenever ``display_levels``
            is below 256), ``measured_palette`` (str, one of
            the keys in ``_MEASURED_PALETTES`` or ``"auto"``; default
            ``"auto"``). When a non-auto measured palette is selected
            its calibrated ``Palette`` is passed to
            ``dither_image()`` instead of the idealized
            palette. The output mode (``"1"`` / ``"L"`` /
            ``"RGB"``) is derived from ``display_levels`` /
            ``color_scheme`` regardless of palette type.

    Returns:
        Processed PIL image. Mode is ``"RGB"`` for color schemes,
        ``"1"`` when ``display_levels`` is 2 or ``dither_algorithm``
        is ``threshold``, ``"L"`` for all other grayscale levels.

    Raises:
        ValueError: If ``color_scheme`` is set but not in
            ``_COLOR_PALETTES``, or if ``display_levels`` is less
            than 256 but not in ``_GRAYSCALE_PALETTES``.
    """
    if not config.get("optimize", False):
        return img

    img = ImageOps.autocontrast(img, preserve_tone=img.mode == "RGB")

    exposure = config.get("exposure", DEFAULT_EXPOSURE)
    saturation = config.get("saturation", DEFAULT_SATURATION)

    algo = config.get("dither_algorithm", DEFAULT_DITHER_ALGORITHM)
    color_scheme_key = config.get("color_scheme")
    if algo == DITHER_THRESHOLD and color_scheme_key:
        _LOGGER.warning(
            "dither_algorithm 'threshold' is only supported on grayscale"
            " displays; falling back to floyd_steinberg"
        )
        algo = DEFAULT_DITHER_ALGORITHM
    if algo == DITHER_THRESHOLD:
        if config.get("display_levels", DEFAULT_DISPLAY_LEVELS) >= 256:
            return img
        # Only pure white (255) stays white; anti-aliased edges and all
        # gray shades become black.
        return img.convert("L").point(
            lambda p: 255 if p == 255 else 0, mode="1"
        )
    if algo not in _DITHER_MODES:
        _LOGGER.warning(
            "Unknown dither_algorithm %r; falling back to floyd_steinberg",
            algo,
        )
        algo = DEFAULT_DITHER_ALGORITHM
    # TODO: expose serpentine as a config option (DITHER.md Step 4)
    options = DitherOptions(
        mode=_DITHER_MODES[algo],
        exposure=exposure,
        saturation=saturation,
    )

    # Resolve measured palette override. "auto" (the default) skips the
    # lookup and uses the idealized palette. Unknown keys fall back
    # to "auto" with a warning.
    measured_palette_key = config.get(
        "measured_palette", DEFAULT_MEASURED_PALETTE
    )
    measured_palette = _MEASURED_PALETTES.get(measured_palette_key)
    if measured_palette is None and measured_palette_key != "auto":
        _LOGGER.warning(
            "Unknown measured_palette %r; falling back to auto",
            measured_palette_key,
        )

    # Color e-ink path: dither to a specific color palette (BWR, etc.).
    if color_scheme_key:
        palette = _COLOR_PALETTES.get(color_scheme_key)
        if palette is None:
            raise ValueError(
                f"Unsupported color_scheme value {color_scheme_key!r};"
                f" expected one of {sorted(_COLOR_PALETTES)}."
            )
        if measured_palette is not None and len(measured_palette) < 3:
            _LOGGER.warning(
                "Measured palette %r has only %d color(s); a mono "
                "palette on a color display may produce unexpected "
                "output",
                measured_palette_key,
                len(measured_palette),
            )
        if measured_palette is not None:
            palette = measured_palette
        img = dither_image(img, palette, options)
        return img.convert("RGB")

    # Grayscale path: quantise to the configured number of levels.
    colors = config.get("display_levels", DEFAULT_DISPLAY_LEVELS)
    if colors < 256:
        palette = _GRAYSCALE_PALETTES.get(colors)
        if palette is None:
            raise ValueError(
                f"Unsupported display_levels value {colors!r}; "
                f"expected one of {sorted(_GRAYSCALE_PALETTES)}."
            )
        if measured_palette is not None and len(measured_palette) > 2:
            _LOGGER.warning(
                "Measured palette %r has %d colors but the grayscale "
                "path is active; a color palette on a grayscale "
                "display may produce unexpected output",
                measured_palette_key,
                len(measured_palette),
            )
        if measured_palette is not None:
            palette = measured_palette
        img = dither_image(img, palette, options)
        # Output mode is derived from display_levels, not the palette,
        # so mono_4_26 (a measured palette for a 2-color display)
        # still produces mode "1" when display_levels == 2.
        img = img.convert("1") if colors == 2 else img.convert("L")

    return img

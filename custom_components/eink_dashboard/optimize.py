"""Post-render image optimization pipeline for e-ink displays."""

from __future__ import annotations

import logging

from epaper_dithering import (
    BWRY_3_97,
    BWRY_4_2,
    HANSHOW_BWR,
    HANSHOW_BWY,
    MONO_4_26,
    SOLUM_BWR,
    SPECTRA_7_3_6COLOR,
    SPECTRA_7_3_6COLOR_V2,
    ColorPalette,
    ColorScheme,
    DitherMode,
    dither_image,
)
from PIL import Image, ImageEnhance, ImageOps

from .const import (
    DEFAULT_CONTRAST,
    DEFAULT_DITHER_ALGORITHM,
    DEFAULT_GRAYSCALE_LEVELS,
    DEFAULT_MEASURED_PALETTE,
    DEFAULT_SHARPNESS,
)

_LOGGER = logging.getLogger(__name__)

# Maps grayscale_levels config values to epaper-dithering color schemes.
_GRAYSCALE_SCHEMES: dict[int, ColorScheme] = {
    2: ColorScheme.MONO,
    4: ColorScheme.GRAYSCALE_4,
    8: ColorScheme.GRAYSCALE_8,  # Reserved for future Inkplate support
    16: ColorScheme.GRAYSCALE_16,
}

# Maps color_scheme config strings to epaper-dithering color schemes
# for color e-ink displays (BWR, BWY, Spectra, etc.).
_COLOR_SCHEMES: dict[str, ColorScheme] = {
    "bwr": ColorScheme.BWR,
    "bwy": ColorScheme.BWY,
    "bwry": ColorScheme.BWRY,
    "bwgbry": ColorScheme.BWGBRY,
}

# Maps dither_algorithm config strings to epaper-dithering DitherMode.
# Only the four algorithms exposed in the UI are included.
_DITHER_MODES: dict[str, DitherMode] = {
    "floyd_steinberg": DitherMode.FLOYD_STEINBERG,
    "atkinson": DitherMode.ATKINSON,
    "stucki": DitherMode.STUCKI,
    "burkes": DitherMode.BURKES,
}

# Maps measured_palette config strings to epaper-dithering ColorPalette
# objects. "auto" is NOT a key here; it means "use the idealized
# ColorScheme" and is handled by the absence of a palette override.
_MEASURED_PALETTES: dict[str, ColorPalette] = {
    "spectra_7_3_6color": SPECTRA_7_3_6COLOR,
    "spectra_7_3_6color_v2": SPECTRA_7_3_6COLOR_V2,
    "mono_4_26": MONO_4_26,
    "bwry_4_2": BWRY_4_2,
    "bwry_3_97": BWRY_3_97,
    "solum_bwr": SOLUM_BWR,
    "hanshow_bwr": HANSHOW_BWR,
    "hanshow_bwy": HANSHOW_BWY,
}


def optimize_for_eink(
    img: Image.Image,
    config: dict,
) -> Image.Image:
    """Apply autocontrast, sharpness, contrast, and dithering to an image.

    Two dithering paths are supported:

    **Grayscale path** (``color_scheme`` absent or ``None``): the
    pipeline image is grayscale (``"L"`` mode). ``dither_image()``
    requires RGB input, so the image is temporarily converted. OKLab
    perceptual colour matching offered by epaper-dithering has no
    effect on equal-channel RGB triples derived from a grayscale
    source; quantisation is effectively luminance-only.

    **Color path** (``color_scheme`` set): the pipeline image must
    be ``"RGB"`` before calling this function; ``render_dashboard()``
    creates an ``"RGB"`` canvas when ``color_scheme`` is set. The
    color ``ColorScheme`` is passed directly to ``dither_image()``.
    Output is converted from palette mode (``"P"``) to ``"RGB"``.
    The caller is responsible for passing an ``"RGB"`` image on this
    path; no silent mode conversion is performed.

    Args:
        img: PIL image from the render pipeline. ``"L"`` for grayscale
            displays, ``"RGB"`` for color displays.
        config: Display config dict. Recognised keys: ``optimize``
            (bool, required to enable the pipeline), ``sharpness``
            (float, default 1.0), ``contrast`` (float, default 1.0),
            ``color_scheme`` (str, one of ``"bwr"``, ``"bwy"``,
            ``"bwry"``, ``"bwgbry"``; ``None`` or absent means
            grayscale), ``grayscale_levels`` (int, one of 2/4/16/256,
            default 16; ignored when ``color_scheme`` is set; 8 is
            reserved for future Inkplate support but is not offered
            in the UI), ``dither_algorithm`` (str, one of
            ``floyd_steinberg``, ``atkinson``, ``stucki``,
            ``burkes``; default ``floyd_steinberg``),
            ``measured_palette`` (str, one of the keys in
            ``_MEASURED_PALETTES`` or ``"auto"``; default
            ``"auto"``). When a non-auto measured palette is
            selected its calibrated ``ColorPalette`` is passed to
            ``dither_image()`` instead of the idealized
            ``ColorScheme``. The output mode (``"1"`` / ``"L"`` /
            ``"RGB"``) is derived from ``grayscale_levels`` /
            ``color_scheme`` regardless of palette type.

    Returns:
        Processed PIL image. Mode is ``"RGB"`` for color schemes,
        ``"1"`` when ``grayscale_levels`` maps to
        ``ColorScheme.MONO``, ``"L"`` for all other grayscale
        schemes.

    Raises:
        ValueError: If ``color_scheme`` is set but not in
            ``_COLOR_SCHEMES``, or if ``grayscale_levels`` is less
            than 256 but not in ``_GRAYSCALE_SCHEMES``.
    """
    if not config.get("optimize", False):
        return img

    img = ImageOps.autocontrast(img, preserve_tone=img.mode == "RGB")

    factor = config.get("sharpness", DEFAULT_SHARPNESS)
    if factor != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(factor)

    factor = config.get("contrast", DEFAULT_CONTRAST)
    if factor != 1.0:
        img = ImageEnhance.Contrast(img).enhance(factor)

    algo = config.get("dither_algorithm", DEFAULT_DITHER_ALGORITHM)
    if algo not in _DITHER_MODES:
        _LOGGER.warning(
            "Unknown dither_algorithm %r; falling back to floyd_steinberg",
            algo,
        )
        algo = DEFAULT_DITHER_ALGORITHM
    mode = _DITHER_MODES[algo]

    # Resolve measured palette override. "auto" (the default) skips the
    # lookup and uses the idealized ColorScheme. Unknown keys fall back
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
    color_scheme_key = config.get("color_scheme")
    if color_scheme_key:
        scheme = _COLOR_SCHEMES.get(color_scheme_key)
        if scheme is None:
            raise ValueError(
                f"Unsupported color_scheme value {color_scheme_key!r};"
                f" expected one of {sorted(_COLOR_SCHEMES)}."
            )
        if measured_palette is not None and len(measured_palette.colors) < 3:
            _LOGGER.warning(
                "Measured palette %r has only %d color(s); a mono "
                "palette on a color display may produce unexpected "
                "output",
                measured_palette_key,
                len(measured_palette.colors),
            )
        palette_or_scheme: ColorPalette | ColorScheme = (
            measured_palette if measured_palette is not None else scheme
        )
        # TODO: expose serpentine as a config option (DITHER.md Step 4)
        img = dither_image(img, palette_or_scheme, mode=mode)
        return img.convert("RGB")

    # Grayscale path: quantise to the configured number of levels.
    colors = config.get("grayscale_levels", DEFAULT_GRAYSCALE_LEVELS)
    if colors < 256:
        scheme = _GRAYSCALE_SCHEMES.get(colors)
        if scheme is None:
            raise ValueError(
                f"Unsupported grayscale_levels value {colors!r}; "
                f"expected one of {sorted(_GRAYSCALE_SCHEMES)}."
            )
        if measured_palette is not None and len(measured_palette.colors) > 2:
            _LOGGER.warning(
                "Measured palette %r has %d colors but the grayscale "
                "path is active; a color palette on a grayscale "
                "display may produce unexpected output",
                measured_palette_key,
                len(measured_palette.colors),
            )
        palette_or_scheme = (
            measured_palette if measured_palette is not None else scheme
        )
        # dither_image() expects RGB input; pipeline image is "L".
        # TODO: expose serpentine as a config option (DITHER.md Step 4)
        img = dither_image(img.convert("RGB"), palette_or_scheme, mode=mode)
        # Output mode is derived from grayscale_levels, not the palette
        # type, so MONO_4_26 (a measured palette for a 2-color display)
        # still produces mode "1" when grayscale_levels == 2.
        img = (
            img.convert("1")
            if scheme is ColorScheme.MONO
            else img.convert("L")
        )

    return img

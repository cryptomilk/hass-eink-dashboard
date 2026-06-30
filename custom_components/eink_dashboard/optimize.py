"""Post-render image optimization pipeline for e-ink displays."""

from __future__ import annotations

from epaper_dithering import ColorScheme, DitherMode, dither_image
from PIL import Image, ImageEnhance, ImageOps

from .const import (
    DEFAULT_CONTRAST,
    DEFAULT_GRAYSCALE_LEVELS,
    DEFAULT_SHARPNESS,
)

# Maps grayscale_levels config values to epaper-dithering color schemes.
_GRAYSCALE_SCHEMES: dict[int, ColorScheme] = {
    2: ColorScheme.MONO,
    4: ColorScheme.GRAYSCALE_4,
    8: ColorScheme.GRAYSCALE_8,
    16: ColorScheme.GRAYSCALE_16,
}


def optimize_for_eink(
    img: Image.Image,
    config: dict,
) -> Image.Image:
    """Apply autocontrast, sharpness, contrast, and dithering to an image.

    Note: the pipeline image is grayscale (``"L"`` mode).
    ``dither_image()`` requires RGB input, so the image is temporarily
    converted. OKLab perceptual colour matching offered by
    epaper-dithering has no effect on equal-channel RGB triples
    derived from a grayscale source; quantisation is effectively
    luminance-only.

    Args:
        img: Grayscale (``"L"``) PIL image from the render pipeline.
        config: Display config dict. Recognised keys: ``optimize``
            (bool, required to enable the pipeline), ``sharpness``
            (float, default 1.0), ``contrast`` (float, default 1.0),
            ``grayscale_levels`` (int, one of 2/4/8/16/256,
            default 16).

    Returns:
        Processed PIL image. Mode is ``"1"`` when
        ``grayscale_levels`` maps to ``ColorScheme.MONO``, ``"L"``
        otherwise.

    Raises:
        ValueError: If ``grayscale_levels`` is less than 256 but not
            in ``_GRAYSCALE_SCHEMES``.
    """
    if not config.get("optimize", False):
        return img

    img = ImageOps.autocontrast(img)

    factor = config.get("sharpness", DEFAULT_SHARPNESS)
    if factor != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(factor)

    factor = config.get("contrast", DEFAULT_CONTRAST)
    if factor != 1.0:
        img = ImageEnhance.Contrast(img).enhance(factor)

    colors = config.get("grayscale_levels", DEFAULT_GRAYSCALE_LEVELS)
    if colors < 256:
        scheme = _GRAYSCALE_SCHEMES.get(colors)
        if scheme is None:
            raise ValueError(
                f"Unsupported grayscale_levels value {colors!r}; "
                f"expected one of {sorted(_GRAYSCALE_SCHEMES)}."
            )
        # dither_image() expects RGB input; pipeline image is "L".
        img = dither_image(
            img.convert("RGB"),
            scheme,
            mode=DitherMode.FLOYD_STEINBERG,
        )
        img = (
            img.convert("1")
            if scheme is ColorScheme.MONO
            else img.convert("L")
        )

    return img

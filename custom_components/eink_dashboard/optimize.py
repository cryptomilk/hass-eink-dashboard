from __future__ import annotations

from PIL import Image, ImageEnhance, ImageOps

from .const import (
    DEFAULT_CONTRAST,
    DEFAULT_GRAYSCALE_LEVELS,
    DEFAULT_SHARPNESS,
)


def optimize_for_eink(
    img: Image.Image,
    config: dict,
) -> Image.Image:
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
        img = img.quantize(
            colors=colors,
            dither=Image.Dither.FLOYDSTEINBERG,
        )
        img = img.convert("L")
        if colors <= 2:
            img = img.convert("1", dither=Image.Dither.NONE)

    return img

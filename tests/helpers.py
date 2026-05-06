from __future__ import annotations

import io

from PIL import Image, ImageChops


def png_to_image(png_bytes: bytes) -> Image.Image:
    """Convert PNG bytes to a PIL Image."""
    return Image.open(io.BytesIO(png_bytes))


def pixel(img: Image.Image, x: int, y: int) -> int:
    """Read a grayscale pixel value from an image.

    Args:
        img: A grayscale ("L" mode) PIL image.
        x: Horizontal coordinate.
        y: Vertical coordinate.

    Returns:
        Pixel value in range 0 (black) to 255 (white).
    """
    val = img.getpixel((x, y))
    if not isinstance(val, int):
        raise TypeError(
            f"expected grayscale image (mode 'L'), got mode '{img.mode}'"
        )
    return val


def content_bbox(
    img: Image.Image, x1: int, y1: int, x2: int, y2: int
) -> tuple[int, int, int, int] | None:
    """Return the tight bounding box of non-white pixels in a region.

    Scans the rectangular region (x1, y1)–(x2, y2) and returns the smallest
    rectangle that contains all pixels darker than 255.  Coordinates are
    absolute (relative to the full image, not the cropped region).

    Args:
        img: A grayscale ("L" mode) PIL image.
        x1: Left edge of the region.
        y1: Top edge of the region.
        x2: Right edge of the region.
        y2: Bottom edge of the region.

    Returns:
        (left, top, right, bottom) of non-white content in absolute image
        coordinates, or None if the entire region is white.
    """
    crop = img.crop((x1, y1, x2, y2))
    inv = ImageChops.invert(crop)
    bbox = inv.getbbox()
    if bbox is None:
        return None
    return (x1 + bbox[0], y1 + bbox[1], x1 + bbox[2], y1 + bbox[3])


def assert_has_dark_pixels(
    img: Image.Image,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    threshold: int = 128,
) -> None:
    """Assert that at least one pixel in the region is darker than threshold.

    Args:
        img: A grayscale ("L" mode) PIL image.
        x1: Left edge of the region.
        y1: Top edge of the region.
        x2: Right edge of the region.
        y2: Bottom edge of the region.
        threshold: Pixels strictly below this value are considered dark.
    """
    assert any(
        pixel(img, x, y) < threshold
        for y in range(y1, y2)
        for x in range(x1, x2)
    ), f"no dark pixels (< {threshold}) in ({x1},{y1})–({x2},{y2})"


def assert_all_white(
    img: Image.Image, x1: int, y1: int, x2: int, y2: int
) -> None:
    """Assert that every pixel in the region is white (255).

    Args:
        img: A grayscale ("L" mode) PIL image.
        x1: Left edge of the region.
        y1: Top edge of the region.
        x2: Right edge of the region.
        y2: Bottom edge of the region.
    """
    for y in range(y1, y2):
        for x in range(x1, x2):
            v = pixel(img, x, y)
            assert v == 255, f"non-white pixel at ({x},{y}): {v}"


def assert_has_gray_pixels(
    img: Image.Image,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    low: int = 100,
    high: int = 140,
) -> None:
    """Assert that at least one pixel in the region is gray.

    The pixel value must be strictly between ``low`` and ``high``.

    Args:
        img: A grayscale ("L" mode) PIL image.
        x1: Left edge of the region.
        y1: Top edge of the region.
        x2: Right edge of the region.
        y2: Bottom edge of the region.
        low: Lower bound (exclusive) for gray range.
        high: Upper bound (exclusive) for gray range.
    """
    assert any(
        low < pixel(img, x, y) < high
        for y in range(y1, y2)
        for x in range(x1, x2)
    ), f"no gray pixels ({low}–{high}) in ({x1},{y1})–({x2},{y2})"


def assert_vertically_centered(
    img: Image.Image,
    icon_region: tuple[int, int, int, int],
    text_region: tuple[int, int, int, int],
    tolerance: float = 2.0,
) -> None:
    """Assert that icon_region and text_region share the same vertical center.

    Locates the tight bounding box of non-white content in each region and
    compares their vertical midpoints.

    Args:
        img: A grayscale ("L" mode) PIL image.
        icon_region: (x1, y1, x2, y2) of the icon area.
        text_region: (x1, y1, x2, y2) of the text area.
        tolerance: Maximum allowed pixel difference between the two vertical
            centers.
    """
    icon_bb = content_bbox(img, *icon_region)
    text_bb = content_bbox(img, *text_region)
    assert icon_bb is not None, "no icon content found"
    assert text_bb is not None, "no text content found"
    icon_cy = (icon_bb[1] + icon_bb[3]) / 2
    text_cy = (text_bb[1] + text_bb[3]) / 2
    assert abs(icon_cy - text_cy) <= tolerance, (
        f"vertical center mismatch: icon={icon_cy:.1f}, text={text_cy:.1f}"
    )


def assert_scales_proportionally(
    img_small: Image.Image,
    img_large: Image.Image,
    region_small: tuple[int, int, int, int],
    region_large: tuple[int, int, int, int],
    expected_ratio: float,
    tolerance: float = 0.25,
) -> None:
    """Assert content height scales by ~expected_ratio between two renders.

    Used to verify that internal widget dimensions scale with the widget's `h`
    parameter rather than using fixed pixel values.

    Args:
        img_small: Rendered image at the smaller size.
        img_large: Rendered image at the larger size.
        region_small: (x1, y1, x2, y2) region to measure in img_small.
        region_large: (x1, y1, x2, y2) region to measure in img_large.
        expected_ratio: Expected height ratio (img_large content / img_small
            content), e.g. 2.0 when `h` is doubled.
        tolerance: Allowed absolute deviation from expected_ratio.
    """
    bb_s = content_bbox(img_small, *region_small)
    bb_l = content_bbox(img_large, *region_large)
    assert bb_s is not None, "no content found in small render region"
    assert bb_l is not None, "no content found in large render region"
    h_s = bb_s[3] - bb_s[1]
    h_l = bb_l[3] - bb_l[1]
    assert h_s > 0, "small region content has zero height"
    assert h_l > 0, "large region content has zero height"
    ratio = h_l / h_s
    assert abs(ratio - expected_ratio) <= tolerance, (
        f"scaling ratio {ratio:.2f}, expected ~{expected_ratio:.2f}"
    )

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageChops

from custom_components.eink_dashboard.render import (
    WidgetMetrics,
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.widgets._helpers import _card_insets


def make_config(defaults: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Build a display config dict from defaults with overrides.

    Args:
        defaults: Base config dict (not mutated).
        **overrides: Keys to add or replace in the base config.

    Returns:
        Merged config dict.
    """
    cfg = dict(defaults)
    cfg.update(overrides)
    return cfg


def png_to_image(png_bytes: bytes) -> Image.Image:
    """Convert PNG bytes to a PIL Image."""
    return Image.open(io.BytesIO(png_bytes))


def render_to_image(
    widgets: list[dict[str, Any]],
    config: dict[str, Any],
) -> Image.Image:
    """Render widgets to a grayscale PIL Image.

    Convenience wrapper combining ``render_dashboard`` and
    ``png_to_image`` into a single call.

    Args:
        widgets: Widget description dicts.
        config: Display configuration dict (width, height, states…).

    Returns:
        Grayscale PIL Image.
    """
    return png_to_image(render_dashboard(widgets, config))


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


def assert_card_border(
    img: Image.Image,
    w: int,
    h: int,
    m: WidgetMetrics,
    *,
    x0: int = 0,
    y0: int = 0,
    bottom_margin: int = 1,
) -> None:
    """Assert dark pixels on all four edges of a card border at ``(x0, y0)``.

    Checks the top, bottom, left, and right edges of a rounded-rectangle
    card frame.  Corner regions (inset by ``m.radius``) are skipped to
    avoid false negatives from corner rounding.

    Args:
        img: A grayscale ("L" mode) PIL image.
        w: Widget width in pixels.
        h: Widget height in pixels.
        m: WidgetMetrics computed for the card's row height.
        x0: Left origin of the card in image coordinates.  Default 0.
        y0: Top origin of the card in image coordinates.  Default 0.
        bottom_margin: Extra pixels subtracted from the bottom-edge top
            bound and added to the bottom bound.  Default 1 accommodates
            PIL stroke rounding at the border edge.  Pass 0 when the
            widget fills the image vertically, leaving no pixel row
            below ``h``.
    """
    # Top edge
    assert_has_dark_pixels(
        img, x0 + m.radius, y0, x0 + w - m.radius, y0 + m.border
    )
    # Bottom edge
    assert_has_dark_pixels(
        img,
        x0 + m.radius,
        y0 + h - m.border - bottom_margin,
        x0 + w - m.radius,
        min(y0 + h + bottom_margin, img.height),
    )
    # Left edge
    assert_has_dark_pixels(
        img, x0, y0 + m.radius, x0 + m.border, y0 + h - m.radius
    )
    # Right edge
    assert_has_dark_pixels(
        img,
        x0 + w - m.border,
        y0 + m.radius,
        x0 + w,
        y0 + h - m.radius,
    )


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


def _icon_ring_region(
    row_h: int,
    m: WidgetMetrics,
    *,
    stroke_inset: int = 0,
) -> tuple[int, int, int, int]:
    """Return the top-arc bounding box of the icon circle.

    The returned region sits above the icon glyph area, between the
    top of the circle and the top of the inner icon bounding box.
    Used in icon-style tests to check for gray fill (filled) or white
    fill (outlined / none).

    Args:
        row_h: Height of the row that contains the icon.
        m: WidgetMetrics computed for that row height.
        stroke_inset: Additional inward offset on the top edge to
            account for thickened strokes (e.g. ``m.border * 3 // 2``
            on 2-level displays).  Defaults to 0.

    Returns:
        ``(x1, y1, x2, y2)`` bounding box of the ring region.
    """
    cy = row_h // 2
    r = m.icon_dia // 2
    cx = m.padding + r
    ring_y1 = cy - r + stroke_inset + 3
    ring_y2 = cy - m.icon_inner // 2 - 1
    ring_x1 = cx - r // 2 + 3
    ring_x2 = cx + r // 2 - 3
    return ring_x1, ring_y1, ring_x2, ring_y2


def _right_icon_ring_region(
    w: int,
    h: int,
    card_style: str = "none",
    grayscale_levels: int = 16,
) -> tuple[int, int, int, int, int, int]:
    """Return the icon ring region for right-aligned icon style tests.

    Used by widgets where the icon sits on the right side of a header
    row — Entity and Sensor.  The header height is computed as 40% of
    the total widget height ``h``.

    Returns ``(icon_cx, icon_cy, ring_x1, ring_y1, ring_x2, ring_y2)``
    — the centre of the icon circle and the bounding box of the top arc
    above the icon glyph area.

    Args:
        w: Canvas width in pixels.
        h: Total widget height in pixels; header_h (40%) is computed
            internally.
        card_style: Card decoration style string.
        grayscale_levels: Display grayscale depth.

    Returns:
        Six-tuple (icon_cx, icon_cy, ring_x1, ring_y1, ring_x2,
        ring_y2).
    """
    header_h = round(h * 0.40)
    m = _compute_metrics(header_h)
    _, r_inset, _ = _card_insets(m, card_style, grayscale_levels)
    rpad = m.padding if r_inset == 0 else 0
    icon_r = m.icon_dia // 2
    icon_cx = w - r_inset - rpad - icon_r
    icon_cy = header_h // 2
    # Mirror the context builder's icon_stroke_w so the ring region
    # starts past the inner edge of a widened stroke on 2-level.
    icon_stroke_w = m.border * 3 if grayscale_levels <= 2 else m.border
    ring_y1 = icon_cy - icon_r + icon_stroke_w // 2 + 3
    ring_y2 = icon_cy - m.icon_inner // 2 - 1
    ring_x1 = icon_cx - icon_r // 2 + 3
    ring_x2 = icon_cx + icon_r // 2 - 3
    return icon_cx, icon_cy, ring_x1, ring_y1, ring_x2, ring_y2


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

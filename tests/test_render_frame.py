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

"""Tests for the frame widget (decorative rounded-corner rectangle)."""

from __future__ import annotations

from typing import ClassVar

from custom_components.eink_dashboard.const import COLOR_GRAY, PADDING
from custom_components.eink_dashboard.render import DEFAULT_METRICS
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    content_bbox,
    pixel,
    render_to_image,
)


class TestRenderFrame:
    """Tests for the frame widget — a decorative rounded-corner rectangle."""

    _CONFIG: ClassVar[dict[str, object]] = {"width": 400, "height": 300}

    def test_frame_border_all_edges(self) -> None:
        # Default frame draws a black border on all four edges.
        W, H = 300, 200
        widgets = [{"type": "frame", "x": 0, "y": 0, "w": W, "h": H}]
        img = render_to_image(widgets, self._CONFIG)
        assert_card_border(img, W, H, DEFAULT_METRICS, x0=0, y0=0)

    def test_frame_interior_white_by_default(self) -> None:
        # Without fill_color the interior of the frame is transparent (white).
        W, H = 200, 150
        border = DEFAULT_METRICS.border
        radius = DEFAULT_METRICS.radius
        widgets = [{"type": "frame", "x": 0, "y": 0, "w": W, "h": H}]
        img = render_to_image(widgets, self._CONFIG)
        # Sample a region well inside the border and rounded corners.
        inset = radius + border + 5
        assert_all_white(img, inset, inset, W - inset, H - inset)

    def test_frame_fill_color_gray(self) -> None:
        # fill_color fills the interior with the given grayscale value.
        W, H = 200, 150
        widgets = [
            {
                "type": "frame",
                "x": 0,
                "y": 0,
                "w": W,
                "h": H,
                "fill_color": COLOR_GRAY,
            }
        ]
        img = render_to_image(widgets, self._CONFIG)
        border = DEFAULT_METRICS.border
        radius = DEFAULT_METRICS.radius
        inset = radius + border + 5
        assert_has_gray_pixels(img, inset, inset, W - inset, H - inset)

    def test_frame_fill_color_black(self) -> None:
        # fill_color=0 fills the interior black.
        W, H = 200, 150
        widgets = [
            {
                "type": "frame",
                "x": 0,
                "y": 0,
                "w": W,
                "h": H,
                "fill_color": 0,
            }
        ]
        img = render_to_image(widgets, self._CONFIG)
        border = DEFAULT_METRICS.border
        radius = DEFAULT_METRICS.radius
        inset = radius + border + 5
        assert_has_dark_pixels(img, inset, inset, W - inset, H - inset)

    def test_frame_gray_border(self) -> None:
        # color=COLOR_GRAY produces a gray border instead of black.
        W, H = 200, 150
        m = DEFAULT_METRICS
        widgets = [
            {
                "type": "frame",
                "x": 0,
                "y": 0,
                "w": W,
                "h": H,
                "color": COLOR_GRAY,
            }
        ]
        img = render_to_image(widgets, self._CONFIG)
        # Top edge mid-span should have gray pixels (not black).
        assert_has_gray_pixels(img, m.radius, 0, W - m.radius, m.border + 2)

    def test_frame_corner_pixels_white(self) -> None:
        # Rounded corners: exact corner pixels are white (not inside border).
        W, H = 200, 150
        widgets = [{"type": "frame", "x": 0, "y": 0, "w": W, "h": H}]
        img = render_to_image(widgets, self._CONFIG)
        assert pixel(img, 0, 0) == 255
        assert pixel(img, W - 1, 0) == 255
        assert pixel(img, 0, H - 1) == 255
        assert pixel(img, W - 1, H - 1) == 255

    def test_frame_no_rounding(self) -> None:
        # border_radius=0 produces sharp corners (corner pixels are dark).
        W, H = 200, 150
        widgets = [
            {
                "type": "frame",
                "x": 0,
                "y": 0,
                "w": W,
                "h": H,
                "border_radius": 0,
            }
        ]
        img = render_to_image(widgets, self._CONFIG)
        # Top edge all the way to the corners should have dark pixels.
        assert_has_dark_pixels(img, 0, 0, W, DEFAULT_METRICS.border + 1)

    def test_frame_positioned_offset(self) -> None:
        # Frame placed at (x, y) renders at the correct canvas location.
        X, Y, W, H = 50, 40, 200, 150
        widgets = [{"type": "frame", "x": X, "y": Y, "w": W, "h": H}]
        img = render_to_image(widgets, self._CONFIG)
        assert_card_border(img, W, H, DEFAULT_METRICS, x0=X, y0=Y)
        # The region before x=X and before y=Y should be all white.
        assert_all_white(img, 0, 0, X - 1, img.height)

    def test_frame_default_x_is_padding(self) -> None:
        # When x is omitted, x defaults to PADDING.
        W, H = 200, 100
        widgets_explicit = [
            {"type": "frame", "x": PADDING, "y": 0, "w": W, "h": H}
        ]
        widgets_default = [{"type": "frame", "y": 0, "w": W, "h": H}]
        img_e = render_to_image(widgets_explicit, self._CONFIG)
        img_d = render_to_image(widgets_default, self._CONFIG)
        # Both should have dark pixels at the same horizontal position.
        assert_has_dark_pixels(
            img_d, PADDING, 0, PADDING + DEFAULT_METRICS.border + 1, H
        )
        assert_all_white(img_d, 0, 0, PADDING - 1, H)
        # Confirm both renders agree on border presence.
        bb_e = content_bbox(img_e, 0, 0, PADDING + W, H)
        bb_d = content_bbox(img_d, 0, 0, PADDING + W, H)
        assert bb_e == bb_d

    def test_frame_custom_border_width(self) -> None:
        # border_width=8 produces a visibly wider border.
        W, H = 200, 150
        bw = 8
        widgets = [
            {
                "type": "frame",
                "x": 0,
                "y": 0,
                "w": W,
                "h": H,
                "border_width": bw,
            }
        ]
        img = render_to_image(widgets, self._CONFIG)
        # The full border_width band at the top edge should be dark.
        assert_has_dark_pixels(img, W // 4, 0, W * 3 // 4, bw)

    def test_frame_scales_proportionally(self) -> None:
        # Doubling the frame height doubles the rendered bounding box height.
        W = 200
        widgets_small = [{"type": "frame", "x": 0, "y": 0, "w": W, "h": 100}]
        widgets_large = [{"type": "frame", "x": 0, "y": 0, "w": W, "h": 200}]
        img_s = render_to_image(widgets_small, self._CONFIG)
        img_l = render_to_image(widgets_large, self._CONFIG)
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(0, 0, W, 100),
            region_large=(0, 0, W, 200),
            expected_ratio=2.0,
            tolerance=0.25,
        )

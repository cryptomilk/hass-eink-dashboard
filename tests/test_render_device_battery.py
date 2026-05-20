from __future__ import annotations

from typing import ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_BLACK,
    COLOR_GRAY,
    PADDING,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    assert_vertically_centered,
    make_config,
    pixel,
    render_to_image,
)


class TestRenderDeviceBattery:
    # Verify rendering of device battery widgets in both icon and chip
    # layouts.  Icon layout renders a compact battery outline with fill
    # bar sized proportionally from h (default h=40 → 30×14 body).
    # Chip layout uses w/h-based sizing with a pill-shaped container.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 100,
        "device_battery_level": 75,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    # -- Icon layout (default): bigger battery icon (30x14) ----------

    def test_icon_draws_fill(self) -> None:
        # Verify the fill bar renders inside the battery body.
        # At 75%: fill_w = int((30-2)*75/100) = 21 px.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Fill region: (PADDING+1, icon_y+1) to (PADDING+22, icon_y+bh-1)
        # icon_y=30, bh=14 → fill at (25, 31) to (46, 43)
        assert_has_dark_pixels(img, PADDING + 1, 31, PADDING + 22, 43)

    def test_icon_draws_percentage_text(self) -> None:
        # Verify percentage label appears to the right of the icon.
        # Text starts at x + 30 + 1 + 3 + 4 = x + 38
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, PADDING + 38, 29, PADDING + 80, 47)

    def test_icon_draws_nub(self) -> None:
        # Verify the nub (battery terminal) renders in gray.
        # Nub at (PADDING+31, nub_y) to (PADDING+33, nub_y+8)
        # nub_y = icon_y + (14-8)//2 = 30 + 3 = 33
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img,
            PADDING + 31,
            33,
            PADDING + 34,
            41,
            threshold=200,
        )

    def test_icon_draws_outline(self) -> None:
        # Verify the battery body outline (gray rectangle).
        # Body from (PADDING, 30) to (PADDING+30, 44)
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Top edge of body
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 30, 31, threshold=200
        )
        # Left edge of body
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 1, 44, threshold=200
        )

    def test_icon_vertically_centers_with_text(self) -> None:
        # Verify the battery icon is vertically centred against
        # the text label.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Icon region: battery body area
        # Text region: right of nub+gap
        assert_vertically_centered(
            img,
            icon_region=(PADDING, 28, PADDING + 34, 46),
            text_region=(PADDING + 38, 20, PADDING + 90, 50),
            tolerance=3.0,
        )

    def test_icon_zero_percent(self) -> None:
        # Verify 0% shows outline only, no fill.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config(device_battery_level=0))
        # Outline is present (gray, threshold=200)
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 34, 44, threshold=200
        )
        # Interior should be white (no fill bar)
        assert_all_white(img, PADDING + 2, 32, PADDING + 28, 42)

    def test_icon_100_percent(self) -> None:
        # Verify 100% fills the entire battery body interior.
        # fill_w = int((30-2)*100/100) = 28
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config(device_battery_level=100))
        assert_has_dark_pixels(img, PADDING + 1, 31, PADDING + 29, 43)

    def test_icon_scales_with_h(self) -> None:
        # Doubling h doubles the battery icon body dimensions.
        # At h=40: body is 30×14. At h=80: body is ~60×28.
        cfg_small = make_config(
            {"width": 400, "height": 60, "device_battery_level": 75}
        )
        cfg_large = make_config(
            {
                "width": 400,
                "height": 100,
                "device_battery_level": 75,
            }
        )
        img_small = render_to_image(
            [
                {
                    "type": "device_battery",
                    "x": 0,
                    "y": 0,
                    "h": 40,
                }
            ],
            cfg_small,
        )
        img_large = render_to_image(
            [
                {
                    "type": "device_battery",
                    "x": 0,
                    "y": 0,
                    "h": 80,
                }
            ],
            cfg_large,
        )
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(0, 0, 400, 60),
            region_large=(0, 0, 400, 100),
            expected_ratio=2.0,
            tolerance=0.35,
        )

    def test_icon_default_layout(self) -> None:
        # Verify that omitting layout defaults to "icon" and renders
        # the battery body (not a chip).
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config())
        # Battery body outline at (PADDING, 30)
        assert_has_dark_pixels(
            img, PADDING, 30, PADDING + 30, 44, threshold=200
        )

    # -- Data edge cases (shared by both layouts) --------------------

    def test_none_level_is_noop(self) -> None:
        # Verify null battery level produces a blank canvas.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, self._config(device_battery_level=None))
        assert_all_white(img, 0, 0, 400, 100)

    def test_missing_key_is_noop(self) -> None:
        # Verify absent device_battery_level key produces blank canvas.
        widgets = [{"type": "device_battery", "x": PADDING, "y": 20}]
        img = render_to_image(widgets, {"width": 400, "height": 100})
        assert_all_white(img, 0, 0, 400, 100)

    def test_icon_low_battery_forces_black(self) -> None:
        # Below 20% overrides color to black for emphasis; both colors
        # produce identical output and the widget actually draws pixels.
        base = {
            "type": "device_battery",
            "x": PADDING,
            "y": 20,
        }
        cfg = self._config(device_battery_level=15)
        gray_img = render_to_image([{**base, "color": COLOR_GRAY}], cfg)
        black_img = render_to_image([{**base, "color": COLOR_BLACK}], cfg)
        assert gray_img.tobytes() == black_img.tobytes()
        # Verify something was actually drawn (guards against both
        # renders producing blank images, which would also be equal).
        assert_has_dark_pixels(
            gray_img, PADDING, 30, PADDING + 35, 44, threshold=200
        )

    def test_chip_low_battery_forces_black(self) -> None:
        # Below 20% chip overrides color to black for emphasis; both
        # colors produce identical output and the widget draws pixels.
        base = {
            "type": "device_battery",
            "x": PADDING,
            "y": 10,
            "h": 40,
            "layout": "chip",
        }
        cfg = self._config(device_battery_level=10)
        gray_img = render_to_image([{**base, "color": COLOR_GRAY}], cfg)
        black_img = render_to_image([{**base, "color": COLOR_BLACK}], cfg)
        assert gray_img.tobytes() == black_img.tobytes()
        # Verify the chip was actually rendered with dark pixels.
        assert_has_dark_pixels(
            gray_img, PADDING, 10, PADDING + 80, 50, threshold=200
        )

    # -- Chip layout -------------------------------------------------

    def test_chip_draws_pill_shape(self) -> None:
        # Verify the chip has a pill-shaped border (rounded corners).
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Extreme corner should be white (outside pill radius)
        assert pixel(img, PADDING, 10) == 255
        # A few pixels inward along the top edge should have border
        assert_has_dark_pixels(img, PADDING + 10, 10, PADDING + 30, 12)

    def test_chip_draws_fill_bar(self) -> None:
        # Verify the fill bar appears inside the chip at 75%.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Fill bar should exist in the left portion of the bar
        assert_has_dark_pixels(img, PADDING + 8, 18, PADDING + 42, 36)
        # Right 25% of bar interior should be unfilled
        assert_all_white(img, PADDING + 43, 24, PADDING + 54, 36)

    def test_chip_draws_percentage_text(self) -> None:
        # Verify percentage label appears inside the chip.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Text should appear in the right portion of the chip
        assert_has_dark_pixels(img, PADDING + 60, 14, PADDING + 150, 46)

    def test_chip_zero_percent_shows_outline_only(self) -> None:
        # Verify 0% chip has the bar outline but no fill inside.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config(device_battery_level=0))
        # The chip outline should still be present
        assert_has_dark_pixels(img, PADDING + 10, 10, PADDING + 150, 50)
        # Interior of the bar should be white (no fill)
        assert_all_white(img, PADDING + 8, 24, PADDING + 54, 36)

    def test_chip_100_percent_fills_bar(self) -> None:
        # Verify 100% chip fills the entire bar interior.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 10,
                "w": 200,
                "h": 40,
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config(device_battery_level=100))
        # Right portion that is white at 75% should be filled
        assert_has_dark_pixels(img, PADDING + 43, 24, PADDING + 54, 36)

    def test_chip_scales_with_h(self) -> None:
        # Verify doubling h roughly doubles the chip content height.
        small_widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 30,
                "layout": "chip",
            }
        ]
        large_widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 300,
                "h": 60,
                "layout": "chip",
            }
        ]
        cfg = self._config()
        img_small = render_to_image(small_widgets, cfg)
        img_large = render_to_image(large_widgets, cfg)
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(0, 0, 200, 30),
            region_large=(0, 0, 300, 60),
            expected_ratio=2.0,
            tolerance=0.35,
        )

    # -- Card style (shared by both layouts) -------------------------

    def test_card_style_border_icon(self) -> None:
        # Border style draws a rounded rectangle frame around
        # the icon layout; content still renders inside.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "border",
                "layout": "icon",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 200, 56, m)
        # Content (battery icon) renders inside the card
        assert_has_dark_pixels(
            img, m.padding, 5, m.padding + 40, 56, threshold=200
        )

    def test_card_style_border_chip(self) -> None:
        # Border style draws a rounded rectangle frame around
        # the chip layout; content still renders inside.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "border",
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 200, 56, m)
        # Content (fill bar) renders inside the card
        assert_has_dark_pixels(img, m.padding + 5, 15, m.padding + 60, 45)

    def test_card_style_left_bar_icon(self) -> None:
        # Left_bar style draws a gray vertical bar spanning the
        # full card height.  Checking below y≈25 avoids the
        # battery body outline (y≈6–20) which is also gray.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "left_bar",
                "layout": "icon",
            }
        ]
        img = render_to_image(widgets, self._config())
        # The bar must extend into the lower portion of the card
        # (below the battery icon at ~y=6–20).
        assert_has_gray_pixels(
            img,
            0,
            35,
            m.left_bar,
            54,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Right edge should be white
        assert_all_white(img, 197, 0, 200, 3)

    def test_card_style_left_bar_chip(self) -> None:
        # Left_bar style draws a gray vertical bar on the left
        # edge for the chip layout.
        m = _compute_metrics(56)
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "left_bar",
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            54,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        # Right edge should be white
        assert_all_white(img, 197, 0, 200, 3)

    def test_card_style_none_is_default(self) -> None:
        # Omitting card_style produces identical output to
        # explicit card_style="none".
        base: dict[str, object] = {
            "type": "device_battery",
            "x": PADDING,
            "y": 10,
            "w": 200,
            "h": 56,
            "layout": "chip",
        }
        cfg = self._config()
        with_none = render_dashboard([{**base, "card_style": "none"}], cfg)
        without = render_dashboard([base], cfg)
        assert with_none == without

    def test_card_style_none_no_border(self) -> None:
        # Explicit card_style="none" has no border decoration
        # on any edge.
        widgets = [
            {
                "type": "device_battery",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 56,
                "card_style": "none",
                "layout": "chip",
            }
        ]
        img = render_to_image(widgets, self._config())
        # Top-left corner: white (no border)
        assert_all_white(img, 0, 0, 3, 3)
        # Right edge: white (no border)
        assert_all_white(img, 197, 0, 200, 3)

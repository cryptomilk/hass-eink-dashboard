from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image

from custom_components.eink_dashboard.optimize import optimize_for_eink


def _gradient(width: int = 256, height: int = 100) -> Image.Image:
    img = Image.new("L", (width, height))
    for x in range(width):
        for y in range(height):
            img.putpixel((x, y), x)
    return img


class TestOptimizeDisabled:
    def test_returns_same_image_when_disabled(self) -> None:
        img = _gradient()
        result = optimize_for_eink(img, {"optimize": False})
        assert result is img

    def test_returns_same_image_when_key_missing(self) -> None:
        img = _gradient()
        result = optimize_for_eink(img, {})
        assert result is img


class TestOptimizeEnabled:
    def test_output_is_grayscale(self) -> None:
        img = _gradient()
        result = optimize_for_eink(img, {"optimize": True})
        assert result.mode == "L"

    def test_size_preserved(self) -> None:
        img = _gradient(800, 480)
        result = optimize_for_eink(img, {"optimize": True})
        assert result.size == (800, 480)

    def test_quantize_16_colors(self) -> None:
        img = _gradient()
        result = optimize_for_eink(
            img, {"optimize": True, "grayscale_levels": 16}
        )
        assert len(set(result.get_flattened_data())) <= 16

    def test_quantize_4_colors(self) -> None:
        img = _gradient()
        result = optimize_for_eink(
            img, {"optimize": True, "grayscale_levels": 4}
        )
        assert len(set(result.get_flattened_data())) <= 4

    def test_quantize_2_colors(self) -> None:
        img = _gradient()
        result = optimize_for_eink(
            img, {"optimize": True, "grayscale_levels": 2}
        )
        assert result.mode == "1"
        assert len(set(result.get_flattened_data())) <= 2

    def test_quantize_2_preserves_content(self) -> None:
        img = Image.new("L", (200, 100), 255)
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 10, 190, 90), fill=0)
        result = optimize_for_eink(
            img, {"optimize": True, "grayscale_levels": 2}
        )
        assert result.mode == "1"
        dark = sum(1 for b in result.convert("L").tobytes() if b == 0)
        assert dark > 0

    def test_256_levels_skips_quantize(self) -> None:
        img = _gradient()
        # Precondition: the default 256-wide gradient has 256 distinct values.
        assert len(set(img.get_flattened_data())) == 256
        result = optimize_for_eink(
            img,
            {
                "optimize": True,
                "grayscale_levels": 256,
                "sharpness": 1.0,
                "contrast": 1.0,
            },
        )
        assert result.mode == "L"
        assert len(set(result.get_flattened_data())) == 256

    def test_autocontrast_stretches_range(self) -> None:
        # Narrow-range image: pixel values 100..199
        img = Image.new("L", (100, 100))
        for x in range(100):
            for y in range(100):
                img.putpixel((x, y), 100 + x)
        result = optimize_for_eink(
            img,
            {
                "optimize": True,
                "grayscale_levels": 256,
                "sharpness": 1.0,
                "contrast": 1.0,
            },
        )
        data = list(result.get_flattened_data())
        assert min(data) <= 5
        assert max(data) >= 250

    def test_sharpness_1_skips_enhance(self) -> None:
        img = _gradient()
        with patch(
            "custom_components.eink_dashboard.optimize.ImageEnhance.Sharpness"
        ) as mock_sharpness:
            optimize_for_eink(
                img,
                {
                    "optimize": True,
                    "grayscale_levels": 256,
                    "sharpness": 1.0,
                    "contrast": 1.0,
                },
            )
            mock_sharpness.assert_not_called()

    def test_custom_sharpness_applied(self) -> None:
        img = _gradient()
        with patch(
            "custom_components.eink_dashboard.optimize.ImageEnhance.Sharpness"
        ) as mock_sharpness:
            mock_enhancer = mock_sharpness.return_value
            mock_enhancer.enhance.return_value = img.copy()
            optimize_for_eink(
                img,
                {
                    "optimize": True,
                    "grayscale_levels": 256,
                    "sharpness": 2.0,
                    "contrast": 1.0,
                },
            )
            mock_sharpness.assert_called_once()
            mock_enhancer.enhance.assert_called_once_with(2.0)

    def test_custom_contrast_applied(self) -> None:
        img = _gradient()
        result = optimize_for_eink(
            img,
            {
                "optimize": True,
                "grayscale_levels": 256,
                "sharpness": 1.0,
                "contrast": 1.5,
            },
        )
        assert result.mode == "L"
        assert result.size == img.size


class TestDitherAlgorithmSelection:
    def _run_with_mock(self, config: dict) -> MagicMock:
        """Run optimize_for_eink with a mocked dither_image; return mock."""
        img = _gradient()
        mock = MagicMock(
            return_value=img.convert("RGB").quantize(
                colors=16, dither=Image.Dither.FLOYDSTEINBERG
            )
        )
        with patch(
            "custom_components.eink_dashboard.optimize.dither_image",
            mock,
        ):
            optimize_for_eink(img, config)
        return mock

    def test_default_uses_floyd_steinberg(self) -> None:
        # Config without dither_algorithm defaults to Floyd-Steinberg.
        from epaper_dithering import DitherMode

        mock = self._run_with_mock({"optimize": True, "grayscale_levels": 16})
        mock.assert_called_once()
        assert mock.call_args[1]["mode"] is DitherMode.FLOYD_STEINBERG

    def test_explicit_floyd_steinberg(self) -> None:
        # Explicit floyd_steinberg selects Floyd-Steinberg mode.
        from epaper_dithering import DitherMode

        mock = self._run_with_mock(
            {
                "optimize": True,
                "grayscale_levels": 16,
                "dither_algorithm": "floyd_steinberg",
            }
        )
        mock.assert_called_once()
        assert mock.call_args[1]["mode"] is DitherMode.FLOYD_STEINBERG

    def test_atkinson_selected(self) -> None:
        # Config with dither_algorithm='atkinson' uses Atkinson mode.
        from epaper_dithering import DitherMode

        mock = self._run_with_mock(
            {
                "optimize": True,
                "grayscale_levels": 16,
                "dither_algorithm": "atkinson",
            }
        )
        mock.assert_called_once()
        assert mock.call_args[1]["mode"] is DitherMode.ATKINSON

    def test_stucki_selected(self) -> None:
        # Config with dither_algorithm='stucki' uses Stucki mode.
        from epaper_dithering import DitherMode

        mock = self._run_with_mock(
            {
                "optimize": True,
                "grayscale_levels": 16,
                "dither_algorithm": "stucki",
            }
        )
        mock.assert_called_once()
        assert mock.call_args[1]["mode"] is DitherMode.STUCKI

    def test_burkes_selected(self) -> None:
        # Config with dither_algorithm='burkes' uses Burkes mode.
        from epaper_dithering import DitherMode

        mock = self._run_with_mock(
            {
                "optimize": True,
                "grayscale_levels": 16,
                "dither_algorithm": "burkes",
            }
        )
        mock.assert_called_once()
        assert mock.call_args[1]["mode"] is DitherMode.BURKES

    def test_unknown_algorithm_falls_back_to_floyd_steinberg(
        self,
    ) -> None:
        # An unrecognised algorithm string falls back to Floyd-Steinberg.
        from epaper_dithering import DitherMode

        mock = self._run_with_mock(
            {
                "optimize": True,
                "grayscale_levels": 16,
                "dither_algorithm": "nonexistent_algo",
            }
        )
        mock.assert_called_once()
        assert mock.call_args[1]["mode"] is DitherMode.FLOYD_STEINBERG


class TestColorSchemeDithering:
    def test_color_scheme_produces_rgb_output(self) -> None:
        # BWR dithering should return an RGB image, not grayscale.
        img = _gradient()
        result = optimize_for_eink(
            img.convert("RGB"),
            {"optimize": True, "color_scheme": "bwr"},
        )
        assert result.mode == "RGB"

    def test_color_scheme_passes_correct_colorscheme(self) -> None:
        # Verify that dither_image receives ColorScheme.BWR for "bwr".
        from epaper_dithering import ColorScheme

        img = _gradient()
        mock = MagicMock(
            return_value=img.convert("RGB").quantize(
                colors=3, dither=Image.Dither.FLOYDSTEINBERG
            )
        )
        with patch(
            "custom_components.eink_dashboard.optimize.dither_image",
            mock,
        ):
            optimize_for_eink(
                img.convert("RGB"),
                {"optimize": True, "color_scheme": "bwr"},
            )
        mock.assert_called_once()
        assert mock.call_args[0][1] is ColorScheme.BWR

    def test_unknown_color_scheme_raises(self) -> None:
        # An unrecognised color_scheme key must raise ValueError.
        import pytest

        img = _gradient()
        with pytest.raises(ValueError, match="Unsupported color_scheme"):
            optimize_for_eink(
                img.convert("RGB"),
                {"optimize": True, "color_scheme": "xyz_unknown"},
            )

    def test_color_scheme_disabled_optimize_returns_unchanged(self) -> None:
        # optimize=False skips the entire pipeline including color dithering.
        img = _gradient().convert("RGB")
        result = optimize_for_eink(
            img, {"optimize": False, "color_scheme": "bwr"}
        )
        assert result is img


class TestOptimizeIntegration:
    def test_render_with_optimize_limits_colors(self) -> None:
        from custom_components.eink_dashboard.render import (
            render_dashboard,
        )

        config = {
            "width": 200,
            "height": 100,
            "optimize": True,
            "grayscale_levels": 4,
        }
        widgets = [{"type": "heading", "x": 10, "y": 10, "heading": "Hi"}]
        png = render_dashboard(widgets, config)
        img = Image.open(io.BytesIO(png))
        assert img.mode == "L"
        assert len(set(img.get_flattened_data())) <= 4

    def test_render_2_levels_produces_1bit_png(self) -> None:
        from custom_components.eink_dashboard.render import (
            render_dashboard,
        )

        config = {
            "width": 200,
            "height": 100,
            "optimize": True,
            "grayscale_levels": 2,
        }
        widgets = [{"type": "heading", "x": 10, "y": 10, "heading": "Hi"}]
        png = render_dashboard(widgets, config)
        img = Image.open(io.BytesIO(png))
        assert img.mode == "1"

    def test_render_without_optimize_has_more_colors(self) -> None:
        from custom_components.eink_dashboard.render import (
            render_dashboard,
        )

        config = {"width": 200, "height": 100, "optimize": False}
        widgets = [{"type": "heading", "x": 10, "y": 10, "heading": "Hi"}]
        png = render_dashboard(widgets, config)
        img = Image.open(io.BytesIO(png))
        assert img.mode == "L"
        assert len(set(img.get_flattened_data())) > 4

    def test_bwr_produces_at_most_3_colors(self) -> None:
        # BWR palette has 3 colors; real dither_image output uses <= 3
        # unique (r, g, b) triples.
        img = _gradient()
        result = optimize_for_eink(
            img.convert("RGB"),
            {"optimize": True, "color_scheme": "bwr"},
        )
        assert result.mode == "RGB"
        w, h = result.size
        pixels = {result.getpixel((x, y)) for x in range(w) for y in range(h)}
        assert len(pixels) <= 3

    def test_render_with_color_scheme_produces_rgb_png(self) -> None:
        # render_dashboard with color_scheme and optimize=True
        # returns an RGB PNG.
        from custom_components.eink_dashboard.render import (
            render_dashboard,
        )

        config = {
            "width": 200,
            "height": 100,
            "optimize": True,
            "color_scheme": "bwr",
        }
        widgets = [{"type": "heading", "x": 10, "y": 10, "heading": "Hi"}]
        png = render_dashboard(widgets, config)
        img = Image.open(io.BytesIO(png))
        assert img.mode == "RGB"

    def test_render_color_scheme_no_optimize_produces_rgb_png(self) -> None:
        # render_dashboard with color_scheme and optimize=False still
        # creates an RGB canvas (for the OpenDisplay integration path).
        from custom_components.eink_dashboard.render import (
            render_dashboard,
        )

        config = {
            "width": 200,
            "height": 100,
            "optimize": False,
            "color_scheme": "bwr",
        }
        widgets = [{"type": "heading", "x": 10, "y": 10, "heading": "Hi"}]
        png = render_dashboard(widgets, config)
        img = Image.open(io.BytesIO(png))
        assert img.mode == "RGB"

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

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
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
            {"optimize": True, "grayscale_levels": 256},
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
            {"optimize": True, "grayscale_levels": 256},
        )
        data = list(result.get_flattened_data())
        assert min(data) <= 5
        assert max(data) >= 250


class TestExposureSaturation:
    def _run_with_mock(self, config: dict) -> MagicMock:
        """Run optimize_for_eink with mocked dither_image; return the mock."""
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

    def test_default_exposure_saturation_passed(self) -> None:
        # When not configured, dither_image receives the defaults (1.0/1.0).
        mock = self._run_with_mock({"optimize": True, "grayscale_levels": 16})
        mock.assert_called_once()
        assert mock.call_args[1]["exposure"] == 1.0
        assert mock.call_args[1]["saturation"] == 1.0

    def test_custom_exposure_passed(self) -> None:
        # A custom exposure value is forwarded to dither_image.
        mock = self._run_with_mock(
            {"optimize": True, "grayscale_levels": 16, "exposure": 1.5}
        )
        mock.assert_called_once()
        assert mock.call_args[1]["exposure"] == 1.5

    def test_custom_saturation_passed(self) -> None:
        # A custom saturation value is forwarded to dither_image.
        mock = self._run_with_mock(
            {"optimize": True, "grayscale_levels": 16, "saturation": 0.5}
        )
        mock.assert_called_once()
        assert mock.call_args[1]["saturation"] == 0.5

    def test_exposure_saturation_on_color_path(self) -> None:
        # exposure/saturation are forwarded on the color path too.
        img = _gradient().convert("RGB")
        mock = MagicMock(
            return_value=img.quantize(
                colors=3, dither=Image.Dither.FLOYDSTEINBERG
            )
        )
        with patch(
            "custom_components.eink_dashboard.optimize.dither_image",
            mock,
        ):
            optimize_for_eink(
                img,
                {
                    "optimize": True,
                    "color_scheme": "bwr",
                    "exposure": 1.2,
                    "saturation": 0.8,
                },
            )
        mock.assert_called_once()
        assert mock.call_args[1]["exposure"] == 1.2
        assert mock.call_args[1]["saturation"] == 0.8

    def test_grayscale_256_skips_dither_image(self) -> None:
        # grayscale_levels=256 is the passthrough path: dither_image() is
        # never called, so exposure/saturation have no effect.
        img = _gradient()
        mock = MagicMock()
        with patch(
            "custom_components.eink_dashboard.optimize.dither_image",
            mock,
        ):
            optimize_for_eink(
                img,
                {
                    "optimize": True,
                    "grayscale_levels": 256,
                    "exposure": 1.5,
                    "saturation": 0.5,
                },
            )
        mock.assert_not_called()


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


class TestMeasuredPaletteDithering:
    """Verify measured palette resolution and usage in optimize_for_eink."""

    def _run_with_mock(
        self, config: dict, return_colors: int = 16
    ) -> MagicMock:
        """Run optimize_for_eink with a mocked dither_image.

        Returns the mock (not the image) for call-argument inspection.
        The return value of optimize_for_eink is discarded; use
        optimize_for_eink directly when the output image matters.
        """
        img = _gradient()
        mock = MagicMock(
            return_value=img.convert("RGB").quantize(
                colors=return_colors, dither=Image.Dither.FLOYDSTEINBERG
            )
        )
        with patch(
            "custom_components.eink_dashboard.optimize.dither_image",
            mock,
        ):
            optimize_for_eink(img, config)
        return mock

    @pytest.mark.parametrize(
        "config",
        [
            {
                "optimize": True,
                "grayscale_levels": 16,
                "measured_palette": "auto",
            },
            {"optimize": True, "grayscale_levels": 16},
        ],
        ids=["explicit-auto", "absent-key"],
    )
    def test_auto_uses_idealized_scheme(self, config: dict) -> None:
        # "auto" and absent measured_palette both pass a ColorScheme
        # (not a ColorPalette) to dither_image.
        from epaper_dithering import ColorScheme

        mock = self._run_with_mock(config)
        mock.assert_called_once()
        assert isinstance(mock.call_args[0][1], ColorScheme)

    def test_measured_palette_overrides_color_scheme(self) -> None:
        # When measured_palette is set, dither_image receives a
        # ColorPalette instead of a ColorScheme.
        from epaper_dithering import SPECTRA_7_3_6COLOR, ColorPalette

        img = _gradient().convert("RGB")
        mock = MagicMock(
            return_value=img.quantize(
                colors=6, dither=Image.Dither.FLOYDSTEINBERG
            )
        )
        with patch(
            "custom_components.eink_dashboard.optimize.dither_image",
            mock,
        ):
            optimize_for_eink(
                img,
                {
                    "optimize": True,
                    "color_scheme": "bwgbry",
                    "measured_palette": "spectra_7_3_6color",
                },
            )
        mock.assert_called_once()
        palette_arg = mock.call_args[0][1]
        assert isinstance(palette_arg, ColorPalette)
        assert palette_arg is SPECTRA_7_3_6COLOR

    def test_measured_palette_with_grayscale(self) -> None:
        # Measured palette applies to the grayscale path too (e.g. mono_4_26).
        from epaper_dithering import MONO_4_26, ColorPalette

        mock = self._run_with_mock(
            {
                "optimize": True,
                "grayscale_levels": 2,
                "measured_palette": "mono_4_26",
            },
            return_colors=2,
        )
        mock.assert_called_once()
        palette_arg = mock.call_args[0][1]
        assert isinstance(palette_arg, ColorPalette)
        assert palette_arg is MONO_4_26

    def test_unknown_measured_palette_falls_back_to_scheme(self) -> None:
        # An unrecognised measured_palette key falls back to the idealized
        # ColorScheme without raising.
        from epaper_dithering import ColorScheme

        mock = self._run_with_mock(
            {
                "optimize": True,
                "grayscale_levels": 16,
                "measured_palette": "nonexistent_palette",
            }
        )
        mock.assert_called_once()
        assert isinstance(mock.call_args[0][1], ColorScheme)

    def test_measured_palette_produces_rgb_output(self) -> None:
        # End-to-end: measured palette with a color scheme yields RGB output.
        img = _gradient().convert("RGB")
        result = optimize_for_eink(
            img,
            {
                "optimize": True,
                "color_scheme": "bwgbry",
                "measured_palette": "spectra_7_3_6color",
            },
        )
        assert result.mode == "RGB"

    def test_measured_palette_produces_mono_output(self) -> None:
        # End-to-end: measured MONO palette with grayscale_levels=2 still
        # produces mode "1" (binary) output, not "L".
        img = _gradient()
        result = optimize_for_eink(
            img,
            {
                "optimize": True,
                "grayscale_levels": 2,
                "measured_palette": "mono_4_26",
            },
        )
        assert result.mode == "1"


def test_measured_palette_options_match_optimize_keys() -> None:
    # UI option list (minus "auto") must match the runtime lookup dict.
    # This guard catches the two lists drifting out of sync when a new
    # palette is added to one but not the other.
    from custom_components.eink_dashboard.config_flow import (
        _MEASURED_PALETTE_OPTIONS,
    )
    from custom_components.eink_dashboard.optimize import _MEASURED_PALETTES

    ui_keys = {k for k in _MEASURED_PALETTE_OPTIONS if k != "auto"}
    assert ui_keys == set(_MEASURED_PALETTES)

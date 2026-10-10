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

import dataclasses
import re
from datetime import date
from typing import ClassVar

import pytest
from PIL import ImageFont

from custom_components.eink_dashboard.const import (
    DEFAULT_ROW_H,
    NumberFormat,
    color_to_hex,
)
from custom_components.eink_dashboard.fonts import (
    font_family,
    font_family_context,
    pixel_font_size,
    pixel_fonts_context,
)
from custom_components.eink_dashboard.render import (
    DEFAULT_METRICS,
    WidgetMetrics,
    _compute_metrics,
    _load_font,
    _month_abbrev,
    _weekday_abbrev,
    format_number,
    resolve_number_format,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets._helpers import (
    _auto_row_height,
    _card_insets,
    _metrics_context,
    _resolve_icon_style,
    _temp_gradient_stops,
    _temp_to_rgb,
    _title_layout,
)
from tests.helpers import (
    assert_all_white,
    assert_has_dark_pixels,
    pixel,
    render_to_image,
)


class TestColorToHex:
    def test_black(self) -> None:
        # 0 is COLOR_BLACK — must convert to #000000.
        assert color_to_hex(0) == "#000000"

    def test_white(self) -> None:
        # 255 is COLOR_WHITE — must convert to #ffffff.
        assert color_to_hex(255) == "#ffffff"

    def test_gray(self) -> None:
        # 120 is COLOR_GRAY — must convert to #787878.
        assert color_to_hex(120) == "#787878"

    def test_light_gray(self) -> None:
        # 180 is COLOR_LIGHT_GRAY — must convert to #b4b4b4.
        assert color_to_hex(180) == "#b4b4b4"


class TestRenderDashboard:
    def test_roboto_font_family_renders_text(self) -> None:
        # The selected Roboto face rasterizes through the full pipeline.
        config = {"width": 200, "height": 80, "font_family": "Roboto"}
        widgets = [{"type": "heading", "x": 0, "y": 0, "heading": "Roboto"}]
        img = render_to_image(widgets, config)
        assert_has_dark_pixels(img, 0, 0, 200, 80)

    def test_empty_widget_list_returns_white_image(self) -> None:
        # An empty widget list renders a plain white canvas.
        config = {"width": 100, "height": 100}
        img = render_to_image([], config)
        assert img.mode == "L"
        assert img.size == (100, 100)
        assert pixel(img, 50, 50) == 255

    def test_returns_valid_png(self) -> None:
        # render_dashboard returns a valid PNG with the correct dimensions.
        config = {"width": 200, "height": 300}
        img = render_to_image([], config)
        assert img.format == "PNG"
        assert img.size == (200, 300)

    def test_rotation_90(self) -> None:
        # rotation=90 swaps width and height in the output image.
        config = {"width": 200, "height": 100, "rotation": 90}
        img = render_to_image([], config)
        assert img.size == (100, 200)

    def test_rotation_270(self) -> None:
        # rotation=270 swaps width and height in the output image.
        config = {"width": 200, "height": 100, "rotation": 270}
        img = render_to_image([], config)
        assert img.size == (100, 200)

    def test_unknown_widget_type_is_skipped(self) -> None:
        # An unrecognized widget type is silently skipped; no crash.
        config = {"width": 100, "height": 100}
        widgets = [{"type": "nonexistent", "x": 10, "y": 10}]
        img = render_to_image(widgets, config)
        assert img.size == (100, 100)

    def test_font_dir_passed_to_svg_to_png(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        # A configured font_dir is forwarded to _svg_to_png() as
        # extra_font_dirs so resvg can fall back to it for glyphs
        # missing from the bundled TRMNL fonts.
        import custom_components.eink_dashboard.render as render_module

        seen: list[list[str] | None] = []
        original = render_module._svg_to_png

        def spy(
            svg,
            width=None,
            height=None,
            extra_font_dirs=None,
            use_system_fonts=False,
        ):
            seen.append(extra_font_dirs)
            return original(
                svg,
                width=width,
                height=height,
                extra_font_dirs=extra_font_dirs,
                use_system_fonts=use_system_fonts,
            )

        monkeypatch.setattr(render_module, "_svg_to_png", spy)
        font_dir = str(tmp_path)
        config = {
            "width": 100,
            "height": 100,
            "font_dir": font_dir,
        }
        widgets = [{"type": "heading", "heading": "Hi", "x": 0, "y": 0}]
        render_to_image(widgets, config)
        assert seen == [[font_dir]]

    def test_no_font_dir_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without a configured font_dir, extra_font_dirs is None so
        # only the bundled TRMNL directory is used.
        import custom_components.eink_dashboard.render as render_module

        seen: list[list[str] | None] = []
        original = render_module._svg_to_png

        def spy(
            svg,
            width=None,
            height=None,
            extra_font_dirs=None,
            use_system_fonts=False,
        ):
            seen.append(extra_font_dirs)
            return original(
                svg,
                width=width,
                height=height,
                extra_font_dirs=extra_font_dirs,
                use_system_fonts=use_system_fonts,
            )

        monkeypatch.setattr(render_module, "_svg_to_png", spy)
        config = {"width": 100, "height": 100}
        widgets = [{"type": "heading", "heading": "Hi", "x": 0, "y": 0}]
        render_to_image(widgets, config)
        assert seen == [None]

    def test_use_system_fonts_passed_to_svg_to_png(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A configured use_system_fonts=True is forwarded to
        # _svg_to_png() so resvg also loads host-installed fonts.
        import custom_components.eink_dashboard.render as render_module

        seen: list[bool] = []
        original = render_module._svg_to_png

        def spy(
            svg,
            width=None,
            height=None,
            extra_font_dirs=None,
            use_system_fonts=False,
        ):
            seen.append(use_system_fonts)
            return original(
                svg,
                width=width,
                height=height,
                extra_font_dirs=extra_font_dirs,
                use_system_fonts=use_system_fonts,
            )

        monkeypatch.setattr(render_module, "_svg_to_png", spy)
        config = {
            "width": 100,
            "height": 100,
            "use_system_fonts": True,
        }
        widgets = [{"type": "heading", "heading": "Hi", "x": 0, "y": 0}]
        render_to_image(widgets, config)
        assert seen == [True]

    def test_no_use_system_fonts_defaults_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without use_system_fonts configured, it defaults to False so
        # rendering stays reproducible across environments.
        import custom_components.eink_dashboard.render as render_module

        seen: list[bool] = []
        original = render_module._svg_to_png

        def spy(
            svg,
            width=None,
            height=None,
            extra_font_dirs=None,
            use_system_fonts=False,
        ):
            seen.append(use_system_fonts)
            return original(
                svg,
                width=width,
                height=height,
                extra_font_dirs=extra_font_dirs,
                use_system_fonts=use_system_fonts,
            )

        monkeypatch.setattr(render_module, "_svg_to_png", spy)
        config = {"width": 100, "height": 100}
        widgets = [{"type": "heading", "heading": "Hi", "x": 0, "y": 0}]
        render_to_image(widgets, config)
        assert seen == [False]


class TestVisibilityConditions:
    # Verify that widget visibility conditions are evaluated during
    # render_dashboard() and that hidden widgets leave the canvas
    # untouched.

    _HEADING: ClassVar[dict[str, object]] = {
        "type": "heading",
        "x": 10,
        "y": 10,
        "w": 180,
        "h": 30,
        "heading": "hello",
    }

    def _config(self, states: dict | None = None) -> dict:
        """Build a minimal render config with optional entity states."""
        return {
            "width": 200,
            "height": 100,
            "states": states or {},
        }

    def test_widget_without_visibility_always_renders(self) -> None:
        # No visibility field — widget must appear regardless.
        img = render_to_image([self._HEADING], self._config())
        assert_has_dark_pixels(img, 10, 10, 190, 45)

    def test_widget_with_empty_visibility_always_renders(self) -> None:
        # An empty conditions list is equivalent to no visibility field.
        widget = {**self._HEADING, "visibility": []}
        img = render_to_image([widget], self._config())
        assert_has_dark_pixels(img, 10, 10, 190, 45)

    def test_widget_with_met_state_condition_renders(self) -> None:
        # When the state condition is satisfied the widget is rendered.
        widget = {
            **self._HEADING,
            "visibility": [
                {
                    "condition": "state",
                    "entity": "input_boolean.show",
                    "state": "on",
                }
            ],
        }
        states = {"input_boolean.show": {"state": "on", "attributes": {}}}
        img = render_to_image([widget], self._config(states))
        assert_has_dark_pixels(img, 10, 10, 190, 45)

    def test_widget_with_unmet_state_condition_is_skipped(self) -> None:
        # When the state condition is not satisfied the widget region
        # remains white (canvas is untouched).
        widget = {
            **self._HEADING,
            "visibility": [
                {
                    "condition": "state",
                    "entity": "input_boolean.show",
                    "state": "on",
                }
            ],
        }
        states = {"input_boolean.show": {"state": "off", "attributes": {}}}
        img = render_to_image([widget], self._config(states))
        assert_all_white(img, 10, 10, 190, 45)

    def test_two_widgets_one_hidden_renders_correctly(self) -> None:
        # First widget has an unmet condition (hidden); second widget
        # has no condition and must render normally.
        hidden = {
            **self._HEADING,
            "y": 10,
            "visibility": [
                {
                    "condition": "state",
                    "entity": "s.x",
                    "state": "on",
                }
            ],
        }
        visible = {**self._HEADING, "y": 60}
        states = {"s.x": {"state": "off", "attributes": {}}}
        img = render_to_image([hidden, visible], self._config(states))
        assert_all_white(img, 10, 10, 190, 44)
        assert_has_dark_pixels(img, 10, 60, 190, 95)


class TestPixelFonts:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            (8, 12),
            (10, 12),
            (12, 12),
            (13, 12),
            (14, 12),
            (15, 16),
            (19, 21),
            (23, 24),
            (30, 32),
            (40, 42),
            (47, 48),
        ],
    )
    def test_snaps_to_native_size_or_multiple(
        self, size: int, expected: int
    ) -> None:
        # TRMNL is a pixel font: sizes snap to the nearest native size
        # (12/16/21) or an integer multiple of one, ties round down.
        with pixel_fonts_context(True):
            assert pixel_font_size(size) == expected

    def test_disabled_keeps_size(self) -> None:
        # Without the pixel-font context, sizes pass through unchanged.
        assert pixel_font_size(10) == 10
        with pixel_fonts_context(False):
            assert pixel_font_size(13) == 13

    def test_roboto_keeps_size(self) -> None:
        # Roboto is an outline font, so snapping does not apply.
        with font_family_context("Roboto"), pixel_fonts_context(True):
            assert pixel_font_size(13) == 13

    @pytest.mark.parametrize(
        ("size", "expected_family"),
        [(10, "TRMNL12"), (24, "TRMNL12"), (32, "TRMNL16"), (42, "TRMNL21")],
    )
    def test_family_matches_snapped_size(
        self, size: int, expected_family: str
    ) -> None:
        # The face is the one whose pixel grid divides the snapped size,
        # so 24 px uses TRMNL12 at 2x rather than TRMNL21.
        with pixel_fonts_context(True):
            assert font_family(size) == expected_family
            loaded = _load_font(size)
        assert isinstance(loaded, ImageFont.FreeTypeFont)
        assert loaded.getname()[0] == expected_family
        assert loaded.size == pixel_font_size_for(size)

    def test_widget_svg_uses_snapped_sizes(self) -> None:
        # Template font-size attributes use the snapped size and the
        # root SVG disables text anti-aliasing.
        config = {"width": 200, "height": 60, "pixel_fonts": True}
        w = {"type": "heading", "heading": "Hi", "w": 200, "h": 60}
        svg = render_widget_svg(w, config)
        sizes = {int(v) for v in re.findall(r'font-size="(\d+)"', svg)}
        assert sizes
        assert all(any(s % n == 0 for n in (12, 16, 21)) for s in sizes), sizes
        assert 'text-rendering="optimizeSpeed"' in svg

    def test_widget_svg_disabled_keeps_antialiasing(self) -> None:
        # pixel_fonts=False keeps the anti-aliased renderer default.
        config = {"width": 200, "height": 60, "pixel_fonts": False}
        w = {"type": "heading", "heading": "Hi", "w": 200, "h": 60}
        svg = render_widget_svg(w, config)
        assert "text-rendering" not in svg

    def test_pixel_fonts_default_on(self) -> None:
        # Pixel-perfect text is the default when the option is absent.
        config = {"width": 200, "height": 60}
        w = {"type": "heading", "heading": "Hi", "w": 200, "h": 60}
        assert 'text-rendering="optimizeSpeed"' in render_widget_svg(w, config)

    def test_rendered_text_has_no_gray_edges(self) -> None:
        # Snapped, non-anti-aliased text rasterises to pure black and
        # white, so a black/white threshold cannot fatten glyphs.
        config = {"width": 300, "height": 40, "pixel_fonts": True}
        widgets = [
            {
                "type": "heading",
                "x": 0,
                "y": 0,
                "w": 300,
                "h": 40,
                "heading": "Keller aufräumen 18:00",
            }
        ]
        img = render_to_image(widgets, config)
        values = {v for v, n in enumerate(img.histogram()) if n}
        assert values <= {0, 255}, values


class TestBlackText:
    _STATES: ClassVar[dict[str, object]] = {
        "sensor.temp": {
            "state": "21.5",
            "attributes": {
                "friendly_name": "Living Room",
                "unit_of_measurement": "°C",
            },
        },
    }

    def _svg(self, **overrides: object) -> str:
        """Render an entity widget whose name text is gray by default."""
        config = {"width": 400, "height": 120, "states": self._STATES}
        config.update(overrides)
        w = {
            "type": "entity",
            "entity": "sensor.temp",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 120,
        }
        return render_widget_svg(w, config)

    @staticmethod
    def _text_fills(svg: str) -> set[str]:
        """Return the fill colours of every <text> element in ``svg``."""
        return {
            fill.lower()
            for tag in re.findall(r"<text\b[^>]*>", svg)
            for fill in re.findall(r'fill="([^"]+)"', tag)
        }

    def test_default_keeps_gray_text(self) -> None:
        # Without the option the entity name keeps its gray colour.
        assert "#787878" in self._text_fills(self._svg())

    def test_black_text_turns_gray_text_black(self) -> None:
        # black_text=True recolours every non-white text fill to black.
        fills = self._text_fills(self._svg(black_text=True))
        assert fills <= {"#000000", "#ffffff"}, fills
        assert "#000000" in fills

    def test_black_text_keeps_white_text(self) -> None:
        # White text sits on a dark fill (inverted styles), so it must
        # stay white or it would vanish.
        fixed = TestBlackText._force(
            '<text x="1" fill="#ffffff">a</text>'
            '<text x="2" fill="#787878">b</text>'
        )
        assert 'fill="#ffffff">a' in fixed
        assert 'fill="#000000">b' in fixed

    def test_black_text_leaves_shapes_alone(self) -> None:
        # Only text is recoloured; gray shapes such as icon circles
        # keep their colour.
        fixed = TestBlackText._force(
            '<circle fill="#787878"/><text fill="#787878">b</text>'
        )
        assert '<circle fill="#787878"/>' in fixed

    def test_black_text_renders_no_gray_text_pixels(self) -> None:
        # The gray name renders as pure black, with no gray pixels in
        # the text column.
        config = {
            "width": 400,
            "height": 120,
            "states": self._STATES,
            "black_text": True,
        }
        widgets = [
            {
                "type": "entity",
                "entity": "sensor.temp",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 120,
                "hide_icon": True,
            }
        ]
        img = render_to_image(widgets, config)
        values = {v for v, n in enumerate(img.histogram()) if n}
        assert values <= {0, 255}, values

    @staticmethod
    def _force(svg: str) -> str:
        """Apply the black-text recolouring to a raw SVG snippet."""
        from custom_components.eink_dashboard.svg_render import (
            _force_black_text,
        )

        return _force_black_text(svg)


def pixel_font_size_for(size: int) -> int:
    """Return the snapped size for ``size`` with pixel fonts enabled."""
    with pixel_fonts_context(True):
        return pixel_font_size(size)


class TestLoadFont:
    @pytest.mark.parametrize(
        ("size", "expected_family"),
        [(10, "TRMNL12"), (15, "TRMNL16"), (20, "TRMNL21")],
    )
    def test_uses_closest_optical_size(
        self, size: int, expected_family: str
    ) -> None:
        # PIL measurement and SVG rendering use the same optical-size map.
        assert font_family(size) == expected_family
        loaded = _load_font(size)
        assert isinstance(loaded, ImageFont.FreeTypeFont)
        assert loaded.getname()[0] == expected_family

    def test_roboto_context_selects_roboto_for_measurement(self) -> None:
        # Pillow measurement follows the primary family selected for SVG.
        with font_family_context("Roboto"):
            loaded = _load_font(18)
        assert isinstance(loaded, ImageFont.FreeTypeFont)
        assert loaded.getname()[0] == "Roboto"

    def test_medium_returns_different_object(self) -> None:
        # medium=True must produce a distinct cached object
        regular = _load_font(18)
        medium = _load_font(18, medium=True)
        assert regular is not medium
        # When the TTF is available, verify the actual font style
        if hasattr(medium, "getname"):
            _family, style = medium.getname()
            if style != "Regular":
                assert style == "Medium"

    def test_bold_returns_different_object(self) -> None:
        # bold=True must produce a distinct cached object
        regular = _load_font(18)
        bold = _load_font(18, bold=True)
        assert regular is not bold
        # When the TTF is available, verify the actual font style
        if hasattr(bold, "getname"):
            _family, style = bold.getname()
            if style != "Regular":
                assert style == "Bold"

    def test_regular_is_cached(self) -> None:
        # Calling _load_font twice with the same args returns the same object.
        assert _load_font(18) is _load_font(18)

    def test_medium_is_cached(self) -> None:
        # Medium variant is also LRU-cached.
        assert _load_font(18, medium=True) is _load_font(18, medium=True)

    def test_size_clamped_to_minimum(self) -> None:
        # Zero or negative sizes must not crash; the minimum is enforced.
        assert _load_font(0) is not None
        assert _load_font(-5) is not None
        assert _load_font(0, medium=True) is not None
        assert _load_font(-5, medium=True) is not None


class TestComputeMetrics:
    def test_returns_frozen_dataclass(self) -> None:
        # _compute_metrics returns a frozen WidgetMetrics instance.
        m = _compute_metrics(56)
        assert isinstance(m, WidgetMetrics)
        with pytest.raises(AttributeError):
            m.border = 99  # type: ignore[misc]

    def test_reference_baseline_h56(self) -> None:
        """Reference values at the default row height."""
        m = _compute_metrics(56)
        assert m.border == 2
        assert m.padding == 12
        assert m.radius == 12
        assert m.icon_dia == 36
        assert m.icon_inner == 21
        assert m.font_letter == 18
        assert m.font_primary == 18
        assert m.font_secondary == 14
        assert m.divider == 4
        assert m.inner_gap == 12
        assert m.left_bar == 4

    def test_minimum_clamps_small_row_h(self) -> None:
        # Small row heights clamp border, font_primary, font_secondary, etc.
        m = _compute_metrics(10)
        assert m.border == 2
        assert m.font_primary == 10
        assert m.font_secondary == 10
        assert m.divider == 2
        assert m.left_bar == 2

    def test_unclamped_fields_small_row_h(self) -> None:
        """Unclamped fields scale proportionally at small heights."""
        m = _compute_metrics(10)
        assert m.padding == 2
        assert m.radius == 2
        assert m.icon_dia == 6
        assert m.icon_inner == 3
        assert m.font_letter == 3
        assert m.inner_gap == 2

    def test_scales_at_large_row_h(self) -> None:
        """All fields scale proportionally at large heights."""
        m = _compute_metrics(200)
        assert m.border == 8
        assert m.padding == 42
        assert m.radius == 42
        assert m.icon_dia == 128
        assert m.icon_inner == 76
        assert m.font_letter == 64
        assert m.font_primary == 64
        assert m.font_secondary == 50
        assert m.divider == 14
        assert m.inner_gap == 42
        assert m.left_bar == 14

    def test_reference_h40(self) -> None:
        """All fields at a compact row height."""
        m = _compute_metrics(40)
        assert m.border == 2
        assert m.padding == 8
        assert m.radius == 8
        assert m.icon_dia == 26
        assert m.icon_inner == 15
        assert m.font_letter == 13
        assert m.font_primary == 13
        assert m.font_secondary == 10
        assert m.divider == 3
        assert m.inner_gap == 8
        assert m.left_bar == 3

    def test_reference_h72(self) -> None:
        """All fields at a spacious row height."""
        m = _compute_metrics(72)
        assert m.border == 3
        assert m.padding == 15
        assert m.radius == 15
        assert m.icon_dia == 46
        assert m.icon_inner == 27
        assert m.font_letter == 23
        assert m.font_primary == 23
        assert m.font_secondary == 18
        assert m.divider == 5
        assert m.inner_gap == 15
        assert m.left_bar == 5

    def test_clamp_boundary_border(self) -> None:
        # Boundary test: border clamps at 2 below the natural value.
        assert _compute_metrics(37).border == 2  # clamped: round(1.48) = 1 < 2
        assert _compute_metrics(100).border == 4  # natural: round(4) = 4 > 2

    def test_all_fields_present(self) -> None:
        # Every field in the WidgetMetrics dataclass is an integer.
        m = _compute_metrics(56)
        for f in dataclasses.fields(WidgetMetrics):
            assert isinstance(getattr(m, f.name), int), f"{f.name} is not int"

    def test_default_metrics_matches_default_row_h(
        self,
    ) -> None:
        """Module-level DEFAULT_METRICS matches DEFAULT_ROW_H."""
        # Verify the module-level constant equals
        # _compute_metrics(DEFAULT_ROW_H).
        assert _compute_metrics(DEFAULT_ROW_H) == DEFAULT_METRICS

    def test_default_metrics_is_frozen(self) -> None:
        """DEFAULT_METRICS is immutable."""
        # Assignment to a frozen dataclass field must raise AttributeError.
        with pytest.raises(AttributeError):
            DEFAULT_METRICS.border = 99  # type: ignore[misc]


class TestHelperFunctions:
    """Unit tests for shared helpers in svg_render.py."""

    def test_metrics_context_keys(self) -> None:
        """All keys are m_-prefixed and include baseline values."""
        ctx = _metrics_context(_compute_metrics(56))
        assert all(k.startswith("m_") for k in ctx)
        assert ctx["m_padding"] == 12

    def test_card_insets_border(self) -> None:
        """Border style insets padding on both sides."""
        m = _compute_metrics(56)
        assert _card_insets(m, "border", 16) == (
            m.padding,
            m.padding,
            0,
        )

    def test_card_insets_left_bar(self) -> None:
        """Left-bar style insets bar_w + padding on the left."""
        m = _compute_metrics(56)
        assert _card_insets(m, "left_bar", 16) == (
            m.left_bar + m.padding,
            0,
            m.left_bar,
        )

    def test_card_insets_left_bar_2level(self) -> None:
        """2-level display widens the bar via max(10, left_bar*3)."""
        m = _compute_metrics(56)
        bar_w = max(10, m.left_bar * 3)
        assert _card_insets(m, "left_bar", 2) == (
            bar_w + m.padding,
            0,
            bar_w,
        )

    def test_card_insets_none(self) -> None:
        """No card style produces zero insets."""
        m = _compute_metrics(56)
        assert _card_insets(m, "none", 16) == (0, 0, 0)

    def test_auto_row_height_no_title(self) -> None:
        """Without title, height is num_rows * DEFAULT_ROW_H."""
        assert _auto_row_height("", 2) == 2 * DEFAULT_ROW_H

    def test_auto_row_height_with_title(self) -> None:
        """With title, content_h matches target within 1 px."""
        h = _auto_row_height("Title", 2)
        _, _, content_h = _title_layout("Title", h)
        assert abs(content_h - 2 * DEFAULT_ROW_H) <= 1

    def test_auto_row_height_rejects_zero_rows(self) -> None:
        """num_rows < 1 raises ValueError."""
        with pytest.raises(ValueError, match="num_rows"):
            _auto_row_height("", 0)

    def test_temp_to_rgb_endpoint_colors(self) -> None:
        """Gradient endpoints map to their exact defined colors."""
        assert _temp_to_rgb(-20) == (0, 60, 98)
        assert _temp_to_rgb(40) == (255, 192, 159)

    def test_temp_to_rgb_clamps_beyond_range(self) -> None:
        """Temperatures outside -20..40 clamp to the nearest end."""
        assert _temp_to_rgb(-30) == _temp_to_rgb(-20)
        assert _temp_to_rgb(50) == _temp_to_rgb(40)

    def test_temp_to_rgb_interpolates_midpoint(self) -> None:
        """A value halfway between two stops averages their colors."""
        assert _temp_to_rgb(-15) == (60, 111, 151)

    def test_temp_gradient_stops_offsets_and_colors(self) -> None:
        """Stops are evenly spaced and match _temp_to_rgb per value."""
        stops = _temp_gradient_stops([0, 10, 20])
        assert [s["offset"] for s in stops] == [
            "0.00%",
            "50.00%",
            "100.00%",
        ]
        assert stops[0]["color"] == "#{:02x}{:02x}{:02x}".format(
            *_temp_to_rgb(0)
        )
        assert stops[1]["color"] == "#{:02x}{:02x}{:02x}".format(
            *_temp_to_rgb(10)
        )
        assert stops[2]["color"] == "#{:02x}{:02x}{:02x}".format(
            *_temp_to_rgb(20)
        )

    def test_temp_gradient_stops_rejects_single_value(self) -> None:
        """Fewer than 2 values raises ValueError, not ZeroDivisionError."""
        with pytest.raises(ValueError, match="values"):
            _temp_gradient_stops([10])


class TestResolveNumberFormat:
    def test_language_en_returns_comma_decimal(self) -> None:
        # English defaults to dot decimal (comma thousands).
        result = resolve_number_format("language", "en")
        assert result == NumberFormat.COMMA_DECIMAL

    def test_language_de_returns_decimal_comma(self) -> None:
        # German defaults to comma decimal (dot thousands).
        result = resolve_number_format("language", "de")
        assert result == NumberFormat.DECIMAL_COMMA

    def test_language_fr_returns_space_comma(self) -> None:
        # French defaults to space thousands + comma decimal.
        result = resolve_number_format("language", "fr")
        assert result == NumberFormat.SPACE_COMMA

    def test_language_de_ch_uses_primary_subtag(self) -> None:
        # "de-CH" primary subtag is "de" → decimal_comma.
        result = resolve_number_format("language", "de-CH")
        assert result == NumberFormat.DECIMAL_COMMA

    def test_language_ja_returns_comma_decimal(self) -> None:
        # Japanese: not in comma/space sets → defaults to comma_decimal.
        result = resolve_number_format("language", "ja")
        assert result == NumberFormat.COMMA_DECIMAL

    def test_explicit_decimal_comma_returned_as_is(self) -> None:
        # Explicit formats bypass language lookup.
        assert (
            resolve_number_format("decimal_comma", "en")
            == NumberFormat.DECIMAL_COMMA
        )

    def test_system_treated_as_comma_decimal(self) -> None:
        # Server-side has no browser locale; "system" falls back to
        # dot decimal.
        result = resolve_number_format("system", "en")
        assert result == NumberFormat.COMMA_DECIMAL

    def test_none_returned_as_is(self) -> None:
        # "none" format disables number formatting entirely.
        assert resolve_number_format("none", "en") == NumberFormat.NONE


class TestWeekdayAbbrev:
    _SATURDAY = date(2026, 5, 2)

    def test_english_returns_english_abbrev(self) -> None:
        # Baseline: "en" gives the same abbreviation as before.
        assert _weekday_abbrev(self._SATURDAY, "en") == "Sat"

    def test_german_returns_localized_abbrev(self) -> None:
        # German CLDR abbreviation for Saturday is "Sa.".
        assert _weekday_abbrev(self._SATURDAY, "de") == "Sa."

    def test_regional_subtag_resolves(self) -> None:
        # "de-CH" (BCP 47 hyphen form) resolves via babel's
        # underscore-separated locale identifiers.
        assert _weekday_abbrev(self._SATURDAY, "de-CH") == "Sa."

    def test_unknown_language_falls_back_to_english(self) -> None:
        # A language babel doesn't recognise falls back to English
        # rather than raising.
        assert _weekday_abbrev(self._SATURDAY, "xx-YY") == "Sat"

    def test_malformed_language_falls_back_to_english(self) -> None:
        # A malformed tag makes babel raise ValueError (not
        # UnknownLocaleError); this must also fall back to English
        # rather than propagating the exception.
        assert _weekday_abbrev(self._SATURDAY, "123") == "Sat"

    def test_unknown_region_falls_back_to_primary_language(self) -> None:
        # "de-XX" has an unrecognised region, but the primary
        # subtag "de" is still usable and should be preferred over
        # falling straight through to English.
        assert _weekday_abbrev(self._SATURDAY, "de-XX") == "Sa."


class TestMonthAbbrev:
    _MAY = date(2026, 5, 2)

    def test_english_returns_english_abbrev(self) -> None:
        # Baseline: "en" gives the same abbreviation as before.
        assert _month_abbrev(self._MAY, "en") == "May"

    def test_german_returns_localized_abbrev(self) -> None:
        # German CLDR abbreviation for May is "Mai".
        assert _month_abbrev(self._MAY, "de") == "Mai"

    def test_unknown_language_falls_back_to_english(self) -> None:
        # A language babel doesn't recognise falls back to English
        # rather than raising.
        assert _month_abbrev(self._MAY, "xx-YY") == "May"

    def test_malformed_language_falls_back_to_english(self) -> None:
        # A malformed tag makes babel raise ValueError (not
        # UnknownLocaleError); this must also fall back to English
        # rather than propagating the exception.
        assert _month_abbrev(self._MAY, "123") == "May"


class TestFormatNumber:
    def test_non_numeric_string_passes_through(self) -> None:
        # "on", "off", and HA sentinels must not be modified.
        assert format_number("on", "decimal_comma", "de") == "on"

    def test_unavailable_passes_through(self) -> None:
        # HA "unavailable" sentinel must not be modified.
        result = format_number("unavailable", "decimal_comma", "de")
        assert result == "unavailable"

    def test_double_dash_passes_through(self) -> None:
        # "--" placeholder must pass through unchanged.
        assert format_number("--", "decimal_comma", "de") == "--"

    def test_integer_no_decimal_unchanged(self) -> None:
        # Integers have no decimal separator to swap.
        assert format_number("22", "decimal_comma", "de") == "22"

    def test_comma_decimal_preserves_dot(self) -> None:
        # US/UK style: decimal separator stays as ".".
        assert format_number("8.41", "comma_decimal", "en") == "8.4"

    def test_decimal_comma_swaps_to_comma(self) -> None:
        # German style: "8.41" → "8,4".
        assert format_number("8.41", "decimal_comma", "de") == "8,4"

    def test_space_comma_swaps_to_comma(self) -> None:
        # French style: decimal separator is ",".
        assert format_number("8.41", "space_comma", "fr") == "8,4"

    def test_quote_decimal_preserves_dot(self) -> None:
        # Swiss German style: decimal separator is ".".
        assert format_number("8.41", "quote_decimal", "de-CH") == "8.4"

    def test_none_format_no_grouping(self) -> None:
        # No formatting: keep dot decimal, no grouping.
        assert format_number("1234.56", "none", "en") == "1234.6"

    def test_thousands_grouping_comma_decimal(self) -> None:
        # 1,234.56 for US style.
        assert format_number("1234.56", "comma_decimal", "en") == "1,234.6"

    def test_thousands_grouping_decimal_comma(self) -> None:
        # 1.234,56 for German style.
        assert format_number("1234.56", "decimal_comma", "de") == "1.234,6"

    def test_thousands_grouping_space_comma(self) -> None:
        # French: narrow non-breaking space + comma decimal.
        result = format_number("1234.56", "space_comma", "fr")
        assert result == "1 234,6"

    def test_thousands_grouping_quote_decimal(self) -> None:
        # Swiss: apostrophe thousands + dot decimal.
        assert format_number("1234.56", "quote_decimal", "de-CH") == "1'234.6"

    def test_decimal_places_capped_at_one(self) -> None:
        # Values with more than 1 decimal place are capped at 1 —
        # e-ink displays are small and extra precision is noise.
        assert format_number("8.410", "decimal_comma", "de") == "8,4"
        assert format_number("15.600000", "decimal_comma", "de") == "15,6"

    def test_language_de_inferred(self) -> None:
        # "language" + "de" → decimal_comma.
        assert format_number("8.41", "language", "de") == "8,4"

    def test_language_en_inferred(self) -> None:
        # "language" + "en" → comma_decimal (dot decimal, no change for small
        # values without thousands).
        assert format_number("8.41", "language", "en") == "8.4"

    def test_negative_value(self) -> None:
        # Negative numbers should preserve the minus sign.
        assert format_number("-8.41", "decimal_comma", "de") == "-8,4"


class TestResolveIconStyle:
    def test_auto_active_multilevel_filled(self) -> None:
        # Active entity on a multi-level display auto-resolves to
        # filled (icon_outline=False, icon_no_circle=False).
        icon_outline, icon_no_circle = _resolve_icon_style(None, "on", 16)
        assert not icon_outline
        assert not icon_no_circle

    def test_auto_inactive_multilevel_outlined(self) -> None:
        # Inactive entity on a multi-level display auto-resolves to
        # outlined (icon_outline=True, icon_no_circle=False).
        icon_outline, icon_no_circle = _resolve_icon_style(None, "off", 16)
        assert icon_outline
        assert not icon_no_circle

    def test_auto_active_2level_always_outlined(self) -> None:
        # 2-level display forces outlined even for active entities.
        icon_outline, icon_no_circle = _resolve_icon_style(None, "on", 2)
        assert icon_outline
        assert not icon_no_circle

    def test_explicit_filled_overrides_state(self) -> None:
        # Explicit "filled" forces filled regardless of entity state.
        icon_outline, icon_no_circle = _resolve_icon_style("filled", "off", 16)
        assert not icon_outline
        assert not icon_no_circle

    def test_explicit_outlined_overrides_state(self) -> None:
        # Explicit "outlined" forces outlined regardless of state.
        icon_outline, icon_no_circle = _resolve_icon_style(
            "outlined", "on", 16
        )
        assert icon_outline
        assert not icon_no_circle

    def test_explicit_none_suppresses_circle(self) -> None:
        # Explicit "none" sets icon_no_circle=True.
        icon_outline, icon_no_circle = _resolve_icon_style("none", "on", 16)
        assert not icon_outline
        assert icon_no_circle

    def test_default_state_val_treated_as_inactive(self) -> None:
        # Omitting state_val uses the default "" which is not an
        # active state, so auto-resolves to outlined on multi-level.
        icon_outline, icon_no_circle = _resolve_icon_style(
            None, display_levels=16
        )
        assert icon_outline
        assert not icon_no_circle

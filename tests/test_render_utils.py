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
from typing import ClassVar

import pytest

from custom_components.eink_dashboard.const import (
    DEFAULT_ROW_H,
    NumberFormat,
    color_to_hex,
)
from custom_components.eink_dashboard.render import (
    DEFAULT_METRICS,
    WidgetMetrics,
    _compute_metrics,
    _load_font,
    format_number,
    resolve_number_format,
)
from custom_components.eink_dashboard.widgets._helpers import (
    _auto_row_height,
    _card_insets,
    _metrics_context,
    _resolve_icon_style,
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


class TestLoadFont:
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
            None, grayscale_levels=16
        )
        assert icon_outline
        assert not icon_no_circle

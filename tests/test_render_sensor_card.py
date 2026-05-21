from __future__ import annotations

import re
from typing import ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    DEFAULT_ROW_H,
    color_to_hex,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets._helpers import _card_insets
from tests.helpers import (
    _right_icon_ring_region,
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    make_config,
    pixel,
    render_to_image,
)

MOCK_SENSOR_CARD_STATES: dict[str, dict[str, object]] = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    },
    "binary_sensor.motion": {
        "state": "on",
        "attributes": {
            "friendly_name": "Motion",
            "device_class": "motion",
        },
    },
    "binary_sensor.front_door": {
        "state": "off",
        "attributes": {
            "friendly_name": "Front Door",
            "device_class": "door",
        },
    },
    "sensor.no_class": {
        "state": "42",
        "attributes": {
            "friendly_name": "Plain",
        },
    },
}

# History points for graph tests.  Injected directly into the states
# dict using the compressed format {"s": value, "lu": unix_timestamp}
# that _fetch_history() produces, so tests run without the recorder.
# 9 data points spanning ~22 hours (last timestamp 1747699200) so that
# no point sits exactly on the 24-hour hours_to_show boundary.
_SENSOR_CARD_HISTORY = [
    {"s": "20.0", "lu": 1747620000.0},
    {"s": "21.0", "lu": 1747623600.0},
    {"s": "22.5", "lu": 1747634400.0},
    {"s": "23.0", "lu": 1747645200.0},
    {"s": "22.5", "lu": 1747656000.0},
    {"s": "21.5", "lu": 1747666800.0},
    {"s": "20.0", "lu": 1747677600.0},
    {"s": "21.0", "lu": 1747688400.0},
    {"s": "22.5", "lu": 1747699200.0},
]

MOCK_SENSOR_WITH_HISTORY: dict[str, dict[str, object]] = {
    **MOCK_SENSOR_CARD_STATES,
    "sensor.temperature": {
        **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
        "history": _SENSOR_CARD_HISTORY,
    },
}


class TestRenderSensor:
    # Verify rendering of the Sensor widget: header row (name left,
    # icon right), large value in the info section, and an optional
    # history sparkline graph below.
    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 300,
        "states": MOCK_SENSOR_CARD_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def _icon_ring(
        self,
        h: int,
        card_style: str = "none",
        grayscale_levels: int = 16,
    ) -> tuple[int, int, int, int, int, int]:
        """Delegate to module-level _right_icon_ring_region."""
        return _right_icon_ring_region(400, h, card_style, grayscale_levels)

    # ── Structural tests ──────────────────────────────

    def test_sensor_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        h = 112
        # Border metrics use header_h (40% of h) — same convention as
        # the Entity widget; border/radius/left_bar scale from the
        # header row, not the full card height.
        m = _compute_metrics(round(h * 0.40))
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "card_style": "border",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_card_border(img, 400, h, m)

    def test_sensor_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge; right
        # edge should be white.
        h = 112
        m = _compute_metrics(round(h * 0.40))
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "card_style": "left_bar",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            0,
            2,
            m.left_bar,
            h - 2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )
        assert_all_white(img, 395, 0, 400, 1)

    def test_sensor_card_none(self) -> None:
        # No-decoration style has white edges — only content draws
        # pixels inside the card.
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 112,
                "entity": "sensor.temperature",
                "card_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)

    def test_sensor_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none".
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── Icon style tests ──────────────────────────────
    # Use h=224 so the header section (40% = ~90px) gives an icon
    # circle large enough to reliably sample the ring region.

    def test_sensor_icon_circle_gray_fill_active(self) -> None:
        # Active entity (state "on") without explicit icon_style draws
        # a filled gray circle in the right portion of the header.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_sensor_icon_circle_outlined_inactive(self) -> None:
        # Inactive entity (state "off") without explicit icon_style
        # draws an outlined circle: interior is white, not gray.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.front_door",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "outlined circle should have white fill (no gray) "
            "in the top ring above the icon glyph"
        )

    def test_sensor_icon_style_filled_explicit(self) -> None:
        # icon_style="filled" forces gray circle even for inactive
        # entity (state "off").
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.front_door",
                "icon_style": "filled",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_gray_pixels(
            img,
            rx1,
            ry1,
            rx2,
            ry2,
            low=COLOR_GRAY - 20,
            high=COLOR_GRAY + 20,
        )

    def test_sensor_icon_style_outlined_explicit(self) -> None:
        # icon_style="outlined" forces outlined circle even for active
        # entity (state "on").  No gray in the ring.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
                "icon_style": "outlined",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "explicitly outlined circle should have white fill"
        )

    def test_sensor_icon_style_none_no_circle(self) -> None:
        # icon_style="none" suppresses the circle entirely; no gray
        # fill in the ring area above the icon glyph.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
                "icon_style": "none",
            }
        ]
        img = render_to_image(widgets, self._config())
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "icon_style='none' should not draw a gray circle"
        )

    def test_sensor_2level_always_outlined(self) -> None:
        # On 2-level displays (grayscale_levels=2), active entity is
        # forced to outlined style regardless of state.
        h = 224
        _, _, rx1, ry1, rx2, ry2 = self._icon_ring(h, grayscale_levels=2)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "binary_sensor.motion",
            }
        ]
        img = render_to_image(widgets, self._config(grayscale_levels=2))
        found_gray = False
        for y in range(ry1, ry2):
            for x in range(rx1, rx2):
                if COLOR_GRAY - 20 < pixel(img, x, y) < COLOR_GRAY + 20:
                    found_gray = True
                    break
        assert not found_gray, (
            "2-level display must force outlined (no gray fill) "
            "even for active entity"
        )

    # ── Content tests ─────────────────────────────────

    def test_sensor_draws_name_and_value(self) -> None:
        # Header row (top ~40%) has name on the left; info section
        # (bottom ~60%) has the large state value.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, m.padding, 0, 200, header_h)
        assert_has_dark_pixels(img, m.padding, header_h, 350, h)

    def test_sensor_name_override(self) -> None:
        # name= overrides the entity friendly_name; renders differ.
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        named_render = render_dashboard(
            [{**base, "name": "Override"}], self._config()
        )
        assert default_render != named_render, (
            "name= override should change rendered output"
        )

    def test_sensor_icon_override(self) -> None:
        # icon= overrides the MDI icon resolved from device_class.
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        override_render = render_dashboard(
            [{**base, "icon": "mdi:star"}], self._config()
        )
        assert default_render != override_render, (
            "icon= override should change rendered output"
        )

    def test_sensor_shows_unit(self) -> None:
        # unit_of_measurement appears alongside the value; renders
        # with and without unit differ.
        base: dict[str, object] = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        states_no_unit = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    # No unit_of_measurement.
                },
            },
        }
        with_unit = render_dashboard([base], self._config())
        without_unit = render_dashboard(
            [base], self._config(states=states_no_unit)
        )
        assert with_unit != without_unit, (
            "unit_of_measurement should change rendered output"
        )

    def test_sensor_unit_override(self) -> None:
        # unit= overrides the automatically detected unit.
        base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 112,
            "entity": "sensor.temperature",
        }
        default_render = render_dashboard([base], self._config())
        unit_render = render_dashboard([{**base, "unit": "F"}], self._config())
        assert default_render != unit_render, (
            "unit= override should change rendered output"
        )

    def test_sensor_no_device_class_letter_fallback(self) -> None:
        # Entity without device_class renders a letter in the icon
        # area on the right side of the header row.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        _, r_inset, _ = _card_insets(m, "none", 16)
        rpad = m.padding if r_inset == 0 else 0
        icon_r = m.icon_dia // 2
        icon_x1 = 400 - r_inset - rpad - icon_r * 2
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.no_class",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, icon_x1, 0, 400, header_h, threshold=200)

    # ── Graph tests ───────────────────────────────────

    def test_sensor_graph_has_polyline(self) -> None:
        # With graph="line" and history data, the SVG contains a
        # <polyline> element.
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget, self._config(states=MOCK_SENSOR_WITH_HISTORY)
        )
        assert "<polyline" in svg

    def test_sensor_no_graph_no_polyline(self) -> None:
        # Without graph="line", no <polyline> appears in the SVG.
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 2 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(
            widget, self._config(states=MOCK_SENSOR_WITH_HISTORY)
        )
        assert "<polyline" not in svg

    def test_sensor_graph_draws_dark_pixels(self) -> None:
        # With graph="line" and history data, dark pixels appear in
        # the graph region (bottom DEFAULT_ROW_H of the widget).
        # Layout split: entity section = 2 * DEFAULT_ROW_H, graph
        # section = 1 * DEFAULT_ROW_H.  Matches auto-height tests:
        # no-graph → 2×, with-graph → 3× DEFAULT_ROW_H.
        entity_h = 2 * DEFAULT_ROW_H
        graph_h = DEFAULT_ROW_H
        h = entity_h + graph_h
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
                "graph": "line",
            }
        ]
        img = render_to_image(
            widgets, self._config(states=MOCK_SENSOR_WITH_HISTORY)
        )
        # Polyline falls within the bottom graph_h rows.
        assert_has_dark_pixels(img, 0, entity_h, 400, h)

    def test_sensor_graph_no_history_no_polyline(self) -> None:
        # graph="line" with no history in the state dict produces no
        # <polyline> (graceful degradation).
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        # _DEFAULTS states have no "history" key.
        svg = render_widget_svg(widget, self._config())
        assert "<polyline" not in svg

    def test_sensor_graph_non_numeric_filtered(self) -> None:
        # History entries with non-numeric states are filtered out;
        # the widget renders without crashing.
        history_with_bad = [
            {"s": "unavailable", "lu": 1747612800.0},
            {"s": "unknown", "lu": 1747623600.0},
            {"s": "22.5", "lu": 1747634400.0},
            {"s": "on", "lu": 1747645200.0},
            {"s": "23.0", "lu": 1747656000.0},
        ]
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": history_with_bad,
            },
        }
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(widget, self._config(states=states))
        assert "<svg" in svg
        # Two numeric entries survive filtering → polyline is rendered.
        assert "<polyline" in svg

    def test_sensor_graph_all_non_numeric_no_crash(self) -> None:
        # When every history entry is non-numeric the renderer must not
        # crash and must not produce a polyline (zero valid data points).
        all_bad = [
            {"s": "unavailable", "lu": 1747620000.0},
            {"s": "unknown", "lu": 1747630800.0},
            {"s": "unavailable", "lu": 1747641600.0},
        ]
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": all_bad,
            },
        }
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(widget, self._config(states=states))
        assert "<svg" in svg, (
            "renderer must not crash on all-non-numeric history"
        )
        assert "<polyline" not in svg, (
            "no polyline expected when all history entries are non-numeric"
        )

    def test_sensor_graph_single_point_no_crash(self) -> None:
        # A single valid history data point must not crash the renderer.
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": [{"s": "22.5", "lu": 1747634400.0}],
            },
        }
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(widget, self._config(states=states))
        assert "<svg" in svg

    def test_sensor_graph_8bit_fill(self) -> None:
        # At grayscale_levels=16 (8-bit), a light-gray filled area
        # appears below the polyline.  Checked via fill color rather
        # than a specific SVG element name (<polygon> or <path>).
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget,
            self._config(
                states=MOCK_SENSOR_WITH_HISTORY,
                grayscale_levels=16,
            ),
        )
        fill_hex = color_to_hex(COLOR_LIGHT_GRAY)
        assert fill_hex in svg

    def test_sensor_graph_2level_fill_present(self) -> None:
        # At grayscale_levels=2 the fill polygon is rendered; Floyd-Steinberg
        # dithering in the optimize pipeline converts it to a dot pattern.
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget,
            self._config(
                states=MOCK_SENSOR_WITH_HISTORY,
                grayscale_levels=2,
            ),
        )
        fill_hex = color_to_hex(COLOR_LIGHT_GRAY)
        assert fill_hex in svg

    def test_sensor_graph_2level_stroke_widened(self) -> None:
        # On a 2-level display the graph polyline stroke-width must be
        # 2× m.border to keep the line readable without being too thick.
        # With graph="line" the graph occupies the bottom DEFAULT_ROW_H,
        # so entity_h = h - DEFAULT_ROW_H, and header_h = 40% of that.
        h = 3 * DEFAULT_ROW_H
        entity_h = h - DEFAULT_ROW_H
        header_h = round(entity_h * 0.40)
        m = _compute_metrics(header_h)
        widget = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(
            widget,
            self._config(
                states=MOCK_SENSOR_WITH_HISTORY,
                grayscale_levels=2,
            ),
        )
        expected_sw = m.border * 2
        assert f'stroke-width="{expected_sw}"' in svg, (
            f"2-level graph stroke-width should be {expected_sw}"
            f" (2 × m.border={m.border})"
        )

    def test_sensor_graph_limits(self) -> None:
        # limits= alters the Y-axis range, changing the polyline
        # coordinate positions and therefore the rendered output.
        widget_base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        config = self._config(states=MOCK_SENSOR_WITH_HISTORY)
        auto_render = render_dashboard([widget_base], config)
        limited_render = render_dashboard(
            [{**widget_base, "limits": {"min": 0, "max": 100}}],
            config,
        )
        assert auto_render != limited_render

    def test_sensor_graph_detail_changes_output(self) -> None:
        # detail affects polyline point count in the SVG string, so
        # render_widget_svg is the right level here (not rasterisation).
        # detail=1 (downsampled) must produce different output than
        # detail=2 (full resolution) when history has many data points.
        many_points = [
            {
                "s": str(round(20.0 + i * 0.1, 1)),
                "lu": 1747612800.0 + i * 1800,
            }
            for i in range(48)
        ]
        states = {
            **MOCK_SENSOR_CARD_STATES,
            "sensor.temperature": {
                **MOCK_SENSOR_CARD_STATES["sensor.temperature"],  # type: ignore[dict-item]
                "history": many_points,
            },
        }
        widget_base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        config = self._config(states=states)
        detail1 = render_widget_svg({**widget_base, "detail": 1}, config)
        detail2 = render_widget_svg({**widget_base, "detail": 2}, config)
        assert detail1 != detail2

    def test_sensor_graph_hours_to_show(self) -> None:
        # hours_to_show limits the time window rendered in the graph.
        # A 12-hour window omits older points, producing different
        # polyline coordinates than a 24-hour window.
        widget_base = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 3 * DEFAULT_ROW_H,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        config = self._config(states=MOCK_SENSOR_WITH_HISTORY)
        svg_24h = render_widget_svg(
            {**widget_base, "hours_to_show": 24}, config
        )
        svg_12h = render_widget_svg(
            {**widget_base, "hours_to_show": 12}, config
        )
        assert svg_24h != svg_12h, (
            "hours_to_show=12 should produce different output than 24"
        )

    # ── Data edge cases ───────────────────────────────

    def test_sensor_missing_entity_white_canvas(self) -> None:
        # A missing entity produces a white canvas without crashing.
        h = 112
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.nonexistent",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, h)

    def test_sensor_no_entity_field_white_canvas(self) -> None:
        # Omitting entity entirely produces a white canvas.
        h = 112
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_all_white(img, 0, 0, 400, h)

    # ── Alignment tests ───────────────────────────────

    def test_sensor_icon_in_header_right(self) -> None:
        # Icon appears in the right portion of the header row and
        # contains dark pixels (circle + glyph).
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        _, r_inset, _ = _card_insets(m, "none", 16)
        rpad = m.padding if r_inset == 0 else 0
        icon_r = m.icon_dia // 2
        icon_cx = 400 - r_inset - rpad - icon_r
        icon_x1 = icon_cx - icon_r
        icon_x2 = min(icon_cx + icon_r + 1, 400)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(
            img, icon_x1, 0, icon_x2, header_h, threshold=200
        )

    def test_sensor_name_in_header_left(self) -> None:
        # Entity name appears in the left portion of the header row.
        h = 112
        header_h = round(h * 0.40)
        m = _compute_metrics(header_h)
        widgets = [
            {
                "type": "sensor",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": h,
                "entity": "sensor.temperature",
            }
        ]
        img = render_to_image(widgets, self._config())
        assert_has_dark_pixels(img, m.padding, 0, 200, header_h)

    # ── Scaling tests ─────────────────────────────────

    def test_sensor_scales_with_h(self) -> None:
        # Doubling h roughly doubles the bounding box height of
        # rendered content.
        h_small = 112
        h_large = 224
        widget_small = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h_small,
            "entity": "sensor.temperature",
        }
        widget_large = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": h_large,
            "entity": "sensor.temperature",
        }
        img_s = render_to_image([widget_small], self._config())
        img_l = render_to_image([widget_large], self._config())
        assert_scales_proportionally(
            img_s,
            img_l,
            region_small=(0, 0, 400, h_small),
            region_large=(0, 0, 400, h_large),
            expected_ratio=2.0,
        )

    # ── Auto-sizing tests ─────────────────────────────

    def test_sensor_auto_height_no_graph(self) -> None:
        # Without graph, default height is 2 * DEFAULT_ROW_H.
        w = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 2 * DEFAULT_ROW_H

    def test_sensor_auto_height_with_graph(self) -> None:
        # With graph="line", default height is 3 * DEFAULT_ROW_H.
        w = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "entity": "sensor.temperature",
            "graph": "line",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 3 * DEFAULT_ROW_H

    def test_sensor_explicit_h_preserved(self) -> None:
        # An explicit h overrides the auto-sized default.
        w = {
            "type": "sensor",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 200,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(w, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200

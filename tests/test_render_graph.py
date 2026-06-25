from __future__ import annotations

import re
from typing import ClassVar

from custom_components.eink_dashboard.const import (
    COLOR_GRAY,
    DEFAULT_ROW_H,
    PADDING,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
    render_dashboard,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from tests.helpers import (
    assert_all_white,
    assert_card_border,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    assert_scales_proportionally,
    make_config,
    render_to_image,
)

# History data: 9 numeric points spanning ~22 hours so no point sits
# exactly on the 24-hour hours_to_show boundary.
_GRAPH_HISTORY = [
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

# History designed so avg and last produce distinct polylines.
# bucket_size = 3600 / points_per_hour=2 = 1800s; t_max is the
# largest lu value (1747697400), NOT the final clock time.
# First two entries (10.0, 30.0) are 600s apart, both in bucket
# 1; third entry (20.0) is in bucket 0.  avg([10.0, 30.0]) = 20.0,
# matching bucket 0's 20.0, so avg yields a flat line and the
# flat-line guard fires (y_max += 1.0).  last picks the later of
# the two (30.0), giving a non-flat line with different coordinates.
_AGGREGATE_HISTORY = [
    {"s": "10.0", "lu": 1747699200.0 - 4800},
    {"s": "30.0", "lu": 1747699200.0 - 4200},
    {"s": "20.0", "lu": 1747699200.0 - 1800},
]

MOCK_GRAPH_STATES: dict[str, dict[str, object]] = {
    "sensor.temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
        "history": _GRAPH_HISTORY,
    },
    "sensor.humidity": {
        "state": "8.41",
        "attributes": {
            "friendly_name": "Humidity",
            "device_class": "humidity",
            "unit_of_measurement": "%",
        },
        "history": [
            {"s": "65.0", "lu": 1747620000.0},
            {"s": "67.5", "lu": 1747645200.0},
            {"s": "70.0", "lu": 1747699200.0},
        ],
    },
}


class TestRenderGraph:
    """Verify rendering of graph widgets.

    Phase 1 covers single-entity line graphs with header, polyline,
    optional fill, Y-axis auto-scaling, hours_to_show, aggregate
    functions, and card styles.
    """

    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 400,
        "states": MOCK_GRAPH_STATES,
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        """Return display config merged with overrides."""
        return make_config(self._DEFAULTS, **overrides)

    def _base_widget(self, **overrides: object) -> dict[str, object]:
        """Return a 400×280 graph widget dict merged with overrides."""
        w: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entity": "sensor.temperature",
        }
        w.update(overrides)
        return w

    # ── Structural tests ──────────────────────────────────────────────

    def test_graph_card_border(self) -> None:
        # Border style draws dark pixels on all four edges.
        h = 280
        m = _compute_metrics(DEFAULT_ROW_H)
        widget = self._base_widget(h=h, card_style="border")
        img = render_to_image([widget], self._config())
        assert_card_border(img, 400, h, m)

    def test_graph_card_left_bar(self) -> None:
        # Left_bar style draws gray pixels on the left edge; right
        # edge is white.
        h = 280
        m = _compute_metrics(DEFAULT_ROW_H)
        widget = self._base_widget(h=h, card_style="left_bar")
        img = render_to_image([widget], self._config())
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

    def test_graph_card_none(self) -> None:
        # No-decoration style has white corners — only inner content
        # draws pixels.
        widget = self._base_widget(card_style="none")
        img = render_to_image([widget], self._config())
        assert_all_white(img, 0, 0, 3, 3)
        assert_all_white(img, 397, 0, 400, 3)

    def test_graph_card_style_none_is_default(self) -> None:
        # Omitting card_style must produce byte-identical output to
        # card_style="none".
        base: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entity": "sensor.temperature",
        }
        with_none = render_dashboard(
            [{**base, "card_style": "none"}], self._config()
        )
        without = render_dashboard([base], self._config())
        assert with_none == without

    # ── SVG content tests ─────────────────────────────────────────────

    def test_graph_has_polyline(self) -> None:
        # With history data, the SVG contains a <polyline> element for
        # the line graph.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "<polyline" in svg

    def test_graph_fill_shown_by_default(self) -> None:
        # With show_fill not set (default true), SVG contains a
        # <polygon> fill area below the line.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "<polygon" in svg

    def test_graph_fill_hidden_when_show_fill_false(self) -> None:
        # With show_fill=False, no <polygon> appears in the SVG.
        widget = self._base_widget(show_fill=False)
        svg = render_widget_svg(widget, self._config())
        assert "<polygon" not in svg

    def test_graph_no_history_no_polyline(self) -> None:
        # When no history key is present in the state, no <polyline>
        # is rendered; the widget still produces valid SVG.
        states_no_hist: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
            }
        }
        svg = render_widget_svg(
            self._base_widget(), self._config(states=states_no_hist)
        )
        assert "<svg" in svg
        assert "<polyline" not in svg

    def test_graph_non_numeric_history_filtered(self) -> None:
        # Non-numeric history entries (unavailable, unknown, on/off)
        # are filtered; widget does not crash, and polyline is rendered
        # when at least 2 numeric entries survive.
        history_mixed: list[dict[str, object]] = [
            {"s": "unavailable", "lu": 1747612800.0},
            {"s": "unknown", "lu": 1747623600.0},
            {"s": "22.5", "lu": 1747634400.0},
            {"s": "on", "lu": 1747645200.0},
            {"s": "23.0", "lu": 1747656000.0},
        ]
        states: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
                "history": history_mixed,
            }
        }
        svg = render_widget_svg(
            self._base_widget(), self._config(states=states)
        )
        assert "<svg" in svg
        # Two numeric entries survive → polyline is rendered.
        assert "<polyline" in svg

    def test_graph_all_non_numeric_no_crash(self) -> None:
        # When every history entry is non-numeric, the renderer must
        # not crash and must not produce a <polyline>.
        states: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "unavailable",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
                "history": [
                    {"s": "unavailable", "lu": 1747612800.0},
                    {"s": "unknown", "lu": 1747623600.0},
                ],
            }
        }
        svg = render_widget_svg(
            self._base_widget(), self._config(states=states)
        )
        assert "<svg" in svg
        assert "<polyline" not in svg

    def test_graph_missing_entity_renders(self) -> None:
        # A missing entity does not crash; widget produces valid SVG.
        widget = self._base_widget(entity="sensor.nonexistent")
        svg = render_widget_svg(widget, self._config())
        assert "<svg" in svg

    # ── Pixel region tests ────────────────────────────────────────────

    def test_graph_header_has_dark_pixels(self) -> None:
        # Top header row (name + value text) has dark pixels within
        # the header height.
        h = 280
        header_h = DEFAULT_ROW_H
        widget = self._base_widget(h=h)
        img = render_to_image([widget], self._config())
        assert_has_dark_pixels(img, PADDING, 0, 350, header_h)

    def test_graph_area_has_dark_pixels(self) -> None:
        # Graph area (everything below the header) has dark pixels
        # from the rendered polyline.
        h = 280
        header_h = DEFAULT_ROW_H
        widget = self._base_widget(h=h)
        img = render_to_image([widget], self._config())
        assert_has_dark_pixels(img, 0, header_h, 400, h)

    def test_graph_2level_fill_still_renders(self) -> None:
        # On 2-level displays (grayscale_levels=2), the fill polygon
        # is still included in the SVG; dithering happens at the
        # optimize stage, not the render stage.
        svg = render_widget_svg(
            self._base_widget(), self._config(grayscale_levels=2)
        )
        assert "<polygon" in svg

    # ── Scaling tests ─────────────────────────────────────────────────

    def test_graph_scales_proportionally(self) -> None:
        # Content bbox height scales proportionally with widget height
        # (2× height → ~2× content height).
        widgets_small = [self._base_widget(h=140)]
        widgets_large = [self._base_widget(h=280)]
        img_small = render_to_image(widgets_small, self._config())
        img_large = render_to_image(widgets_large, self._config())
        assert_scales_proportionally(
            img_small,
            img_large,
            region_small=(0, 0, 400, 140),
            region_large=(0, 0, 400, 280),
            expected_ratio=2.0,
            tolerance=0.5,
        )

    # ── Override / option tests ───────────────────────────────────────

    def test_graph_name_override(self) -> None:
        # name= overrides the entity friendly_name and changes the
        # rendered output.
        base = self._base_widget()
        default_render = render_dashboard([base], self._config())
        named_render = render_dashboard(
            [{**base, "name": "Custom Name"}], self._config()
        )
        assert default_render != named_render

    def test_graph_unit_override(self) -> None:
        # unit= overrides the auto-detected unit_of_measurement and
        # changes the rendered output.
        base = self._base_widget()
        default_render = render_dashboard([base], self._config())
        unit_render = render_dashboard([{**base, "unit": "F"}], self._config())
        assert default_render != unit_render

    def test_graph_upper_lower_bound_affects_rendering(self) -> None:
        # Explicit upper_bound/lower_bound change the Y scale,
        # altering the polyline coordinates and thus the output.
        base = self._base_widget()
        default_render = render_dashboard([base], self._config())
        bounded_render = render_dashboard(
            [{**base, "upper_bound": 30.0, "lower_bound": 0.0}],
            self._config(),
        )
        assert default_render != bounded_render

    def test_graph_line_width_affects_rendering(self) -> None:
        # Non-default line_width changes the stroke-width attribute in
        # the SVG, altering the rendered output.
        svg_default = render_widget_svg(self._base_widget(), self._config())
        svg_wide = render_widget_svg(
            self._base_widget(line_width=6), self._config()
        )
        assert svg_default != svg_wide

    def test_graph_hours_to_show_affects_data(self) -> None:
        # Shorter hours_to_show window reduces visible history, which
        # changes the polyline coordinates and thus the output.
        svg_full = render_widget_svg(
            self._base_widget(hours_to_show=24), self._config()
        )
        svg_short = render_widget_svg(
            self._base_widget(hours_to_show=3), self._config()
        )
        assert svg_full != svg_short

    def test_graph_aggregate_avg_accepted(self) -> None:
        # aggregate_func="avg" is accepted without error and produces a
        # polyline.
        widget = self._base_widget(aggregate_func="avg")
        svg = render_widget_svg(widget, self._config())
        assert "<polyline" in svg

    def test_graph_aggregate_last_accepted(self) -> None:
        # aggregate_func="last" is accepted without error and produces a
        # polyline.
        widget = self._base_widget(aggregate_func="last")
        svg = render_widget_svg(widget, self._config())
        assert "<polyline" in svg

    def test_graph_aggregate_avg_vs_last_differ(self) -> None:
        # avg and last aggregation produce distinct polyline coordinates
        # when a bucket contains multiple values (10.0 and 30.0 in the
        # same bucket → avg=20.0, last=30.0 → different Y positions).
        states: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "20.0",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
                "history": _AGGREGATE_HISTORY,
            }
        }
        widget = self._base_widget(
            hours_to_show=2,
            points_per_hour=2,
        )
        svg_avg = render_widget_svg(
            {**widget, "aggregate_func": "avg"},
            self._config(states=states),
        )
        svg_last = render_widget_svg(
            {**widget, "aggregate_func": "last"},
            self._config(states=states),
        )
        assert svg_avg != svg_last

    def test_graph_show_state_false(self) -> None:
        # show_state=False suppresses the current value in the header;
        # output differs from the default.
        base = self._base_widget()
        default_svg = render_widget_svg(base, self._config())
        no_state_svg = render_widget_svg(
            {**base, "show_state": False}, self._config()
        )
        assert default_svg != no_state_svg

    def test_graph_show_name_false(self) -> None:
        # show_name=False suppresses the entity name in the header;
        # output differs from the default.
        base = self._base_widget()
        default_svg = render_widget_svg(base, self._config())
        no_name_svg = render_widget_svg(
            {**base, "show_name": False}, self._config()
        )
        assert default_svg != no_name_svg

    def test_graph_show_icon_false(self) -> None:
        # show_icon=False suppresses the icon in the header; output
        # differs from the default.
        base = self._base_widget()
        default_svg = render_widget_svg(base, self._config())
        no_icon_svg = render_widget_svg(
            {**base, "show_icon": False}, self._config()
        )
        assert default_svg != no_icon_svg

    def test_graph_auto_height(self) -> None:
        # Without an explicit h, the widget falls back to a sensible
        # default height (at least DEFAULT_ROW_H).
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(widget, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) >= DEFAULT_ROW_H

    def test_graph_explicit_h_preserved(self) -> None:
        # An explicit h is reflected in the SVG height attribute.
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 200,
            "entity": "sensor.temperature",
        }
        svg = render_widget_svg(widget, self._config())
        m = re.search(r'height="(\d+)"', svg)
        assert m is not None
        assert int(m.group(1)) == 200

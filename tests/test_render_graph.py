from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    import pytest

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

# History spanning multiple days for group_by testing.
# 6 points in 3 day-pairs: days at ~0h, ~24h, and ~48h from the
# oldest entry.  group_by="date" collapses to 3 buckets (avg per
# day); group_by="hour" produces 6 separate buckets.
_MULTIDAY_HISTORY = [
    {"s": "20.0", "lu": 1747620000.0},
    {"s": "21.0", "lu": 1747630000.0},
    {"s": "22.0", "lu": 1747706400.0},
    {"s": "23.0", "lu": 1747716400.0},
    {"s": "24.0", "lu": 1747792800.0},
    {"s": "25.0", "lu": 1747802800.0},
]

# History with a narrow value range (0.5) to test min_bound_range.
_NARROW_HISTORY = [
    {"s": "20.0", "lu": 1747620000.0},
    {"s": "20.3", "lu": 1747634400.0},
    {"s": "20.5", "lu": 1747648800.0},
    {"s": "20.2", "lu": 1747663200.0},
    {"s": "20.1", "lu": 1747677600.0},
    {"s": "20.4", "lu": 1747692000.0},
    {"s": "20.5", "lu": 1747699200.0},
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
    "sensor.pressure": {
        "state": "1013.0",
        "attributes": {
            "friendly_name": "Pressure",
            "device_class": "pressure",
            "unit_of_measurement": "hPa",
        },
        "history": [
            {"s": "1013.0", "lu": 1747620000.0},
            {"s": "1014.5", "lu": 1747645200.0},
            {"s": "1015.0", "lu": 1747699200.0},
        ],
    },
}


class TestRenderGraph:
    """Verify rendering of graph widgets.

    Phase 1 covers single-entity line graphs with header, polyline,
    optional fill, Y-axis auto-scaling, hours_to_show, aggregate
    functions, and card styles.

    Phase 2 adds path smoothing, axis labels, grid lines, group_by,
    extrema display, and min_bound_range.

    Phase 3 adds multi-entity overlay with distinct dash patterns,
    secondary Y-axis, and legend.

    Phase 4 adds bar chart mode (graph="bar") with grouped multi-entity
    bars, distinct fill shades, and <rect> legend swatches.
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

    # ── SVG content tests (Phase 1 — explicit smoothing=False) ────────

    def test_graph_has_polyline(self) -> None:
        # With smoothing disabled, history data produces a <polyline>.
        svg = render_widget_svg(
            self._base_widget(smoothing=False), self._config()
        )
        assert "<polyline" in svg

    def test_graph_fill_shown_by_default(self) -> None:
        # With show_fill not set (default true) and smoothing off,
        # SVG contains a <polygon> fill area below the line.
        svg = render_widget_svg(
            self._base_widget(smoothing=False), self._config()
        )
        assert "<polygon" in svg

    def test_graph_fill_hidden_when_show_fill_false(self) -> None:
        # With show_fill=False and smoothing=False, no fill element
        # (polygon or filled path) appears below the graph line.
        widget = self._base_widget(show_fill=False, smoothing=False)
        svg = render_widget_svg(widget, self._config())
        assert "<polygon" not in svg

    def test_graph_no_history_no_polyline(self) -> None:
        # When no history key is present in the state, no <polyline>
        # or graph <path> is rendered; the widget still produces valid
        # SVG.
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
            self._base_widget(smoothing=False),
            self._config(states=states_no_hist),
        )
        assert "<svg" in svg
        assert "<polyline" not in svg

    def test_graph_non_numeric_history_filtered(self) -> None:
        # Non-numeric history entries (unavailable, unknown, on/off)
        # are filtered; widget does not crash, and a graph element is
        # rendered when at least 2 numeric entries survive.
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
            self._base_widget(smoothing=False),
            self._config(states=states),
        )
        assert "<svg" in svg
        # Two numeric entries survive → polyline is rendered.
        assert "<polyline" in svg

    def test_graph_all_non_numeric_no_crash(self) -> None:
        # When every history entry is non-numeric, the renderer must
        # not crash and must not produce a graph element.
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
            self._base_widget(smoothing=False),
            self._config(states=states),
        )
        assert "<svg" in svg
        assert "<polyline" not in svg

    def test_graph_missing_entity_renders(self) -> None:
        # A missing entity does not crash; widget produces valid SVG.
        widget = self._base_widget(entity="sensor.nonexistent")
        svg = render_widget_svg(widget, self._config())
        assert "<svg" in svg

    def test_graph_2level_fill_still_renders(self) -> None:
        # On 2-level displays (grayscale_levels=2), the fill element
        # is still included in the SVG; dithering happens at the
        # optimize stage, not the render stage.
        svg = render_widget_svg(
            self._base_widget(smoothing=False),
            self._config(grayscale_levels=2),
        )
        assert "<polygon" in svg

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
        # from the rendered graph line.
        h = 280
        header_h = DEFAULT_ROW_H
        widget = self._base_widget(h=h)
        img = render_to_image([widget], self._config())
        assert_has_dark_pixels(img, 0, header_h, 400, h)

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
        # changes the graph coordinates and thus the output.
        svg_full = render_widget_svg(
            self._base_widget(hours_to_show=24), self._config()
        )
        svg_short = render_widget_svg(
            self._base_widget(hours_to_show=3), self._config()
        )
        assert svg_full != svg_short

    def test_graph_aggregate_avg_accepted(self) -> None:
        # aggregate_func="avg" is accepted without error and produces a
        # graph element.
        widget = self._base_widget(aggregate_func="avg", smoothing=False)
        svg = render_widget_svg(widget, self._config())
        assert "<polyline" in svg

    def test_graph_aggregate_last_accepted(self) -> None:
        # aggregate_func="last" is accepted without error and produces a
        # graph element.
        widget = self._base_widget(aggregate_func="last", smoothing=False)
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

    # ── Phase 2: Smoothing tests ───────────────────────────────────────

    def test_graph_smoothing_default_uses_path(self) -> None:
        # Default config (smoothing=True) renders a <path> element,
        # not a <polyline>.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "<path" in svg
        assert "<polyline" not in svg

    def test_graph_smoothing_false_uses_polyline(self) -> None:
        # smoothing=False renders a <polyline> and no graph <path>.
        svg = render_widget_svg(
            self._base_widget(smoothing=False), self._config()
        )
        assert "<polyline" in svg
        # Ensure no smoothed path is present (d="M...Q..." pattern).
        assert " Q " not in svg

    def test_graph_smoothing_path_has_q_command(self) -> None:
        # The smoothed <path> d attribute contains at least one
        # quadratic Bezier "Q" command.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert " Q " in svg

    def test_graph_smoothing_fill_uses_path(self) -> None:
        # With smoothing=True and show_fill=True (default), the fill
        # is a <path> element (not a <polygon>).
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "<polygon" not in svg
        # At least one <path> with a non-"none" fill color exists.
        assert 'fill="' in svg
        # The fill path should close with Z.
        assert " Z" in svg or 'Z"' in svg

    def test_graph_smoothing_false_fill_uses_polygon(self) -> None:
        # With smoothing=False and show_fill=True, fill uses a
        # <polygon> element (backward compat).
        svg = render_widget_svg(
            self._base_widget(smoothing=False, show_fill=True),
            self._config(),
        )
        assert "<polygon" in svg

    def test_graph_smoothing_differs_from_unsmoothed(self) -> None:
        # Smoothed and unsmoothed renders produce different SVG output
        # because coordinates are shifted to midpoints.
        svg_smooth = render_widget_svg(
            self._base_widget(smoothing=True), self._config()
        )
        svg_raw = render_widget_svg(
            self._base_widget(smoothing=False), self._config()
        )
        assert svg_smooth != svg_raw

    # ── Phase 2: Y-axis label tests ───────────────────────────────────

    def test_graph_labels_shown_by_default(self) -> None:
        # Default config (show_labels=True) renders y_min and y_max
        # formatted values as <text> elements in the SVG.
        svg = render_widget_svg(self._base_widget(), self._config())
        # Data range is 20.0–23.0; expect these values to appear.
        assert "20.0" in svg or "20" in svg
        assert "23.0" in svg or "23" in svg

    def test_graph_labels_false_no_y_text(self) -> None:
        # show_labels=False removes y-axis label text from the SVG;
        # the axis text elements are absent.
        svg_with = render_widget_svg(self._base_widget(), self._config())
        svg_without = render_widget_svg(
            self._base_widget(show_labels=False), self._config()
        )
        assert svg_with != svg_without

    def test_graph_labels_shift_graph_right(self) -> None:
        # When show_labels=True, the graph area starts further right
        # than with show_labels=False to make room for y-axis labels.
        # The rendered outputs differ.
        svg_labeled = render_widget_svg(self._base_widget(), self._config())
        svg_unlabeled = render_widget_svg(
            self._base_widget(show_labels=False), self._config()
        )
        assert svg_labeled != svg_unlabeled

    def test_graph_labels_pixel_region(self) -> None:
        # With show_labels=True, there are dark pixels in the left
        # margin area (where y-axis labels render).
        h = 280
        widget = self._base_widget(h=h, show_labels=True)
        img = render_to_image([widget], self._config())
        # y-axis labels appear in the left portion below the header.
        assert_has_dark_pixels(img, 0, DEFAULT_ROW_H, PADDING * 2, h)

    # ── Phase 2: X-axis label tests ───────────────────────────────────

    def test_graph_x_labels_shown(self) -> None:
        # With show_labels=True, the SVG contains HH:MM time strings
        # (formatted timestamps for oldest and newest data points).
        svg = render_widget_svg(self._base_widget(), self._config())
        # Look for HH:MM pattern (24-hour format).
        assert re.search(r"\d{2}:\d{2}", svg) is not None

    def test_graph_x_labels_reduce_graph_height(self) -> None:
        # With show_labels=True, the graph area is shorter than with
        # show_labels=False because x-axis labels reserve bottom space.
        svg_labeled = render_widget_svg(self._base_widget(), self._config())
        svg_unlabeled = render_widget_svg(
            self._base_widget(show_labels=False), self._config()
        )
        # The outputs must differ (labeled graph has less vertical
        # space for the graph line, changing its coordinates).
        assert svg_labeled != svg_unlabeled

    # ── Phase 2: Grid line tests ──────────────────────────────────────

    def test_graph_grid_lines_present_multigrayscale(self) -> None:
        # With show_labels=True and a multi-level display, the SVG
        # contains <line> elements for horizontal grid lines.
        svg = render_widget_svg(
            self._base_widget(show_labels=True),
            self._config(grayscale_levels=16),
        )
        assert "<line" in svg

    def test_graph_grid_lines_absent_2level(self) -> None:
        # On 2-level displays (grayscale_levels=2), grid lines are
        # suppressed (fine gray lines cannot be rendered on B&W).
        svg = render_widget_svg(
            self._base_widget(show_labels=True),
            self._config(grayscale_levels=2),
        )
        assert "<line" not in svg

    def test_graph_grid_lines_use_light_gray(self) -> None:
        # Grid <line> elements use the light-gray color constant.
        from custom_components.eink_dashboard.const import (
            COLOR_LIGHT_GRAY,
            color_to_hex,
        )

        expected_color = color_to_hex(COLOR_LIGHT_GRAY)
        svg = render_widget_svg(
            self._base_widget(show_labels=True),
            self._config(grayscale_levels=16),
        )
        assert expected_color in svg

    # ── Phase 2: group_by tests ───────────────────────────────────────

    def test_graph_group_by_hour_differs_from_default(self) -> None:
        # group_by="hour" forces 1 point per hour, changing bucket
        # size and thus the rendered coordinates.
        svg_default = render_widget_svg(self._base_widget(), self._config())
        svg_hour = render_widget_svg(
            self._base_widget(group_by="hour"), self._config()
        )
        assert svg_default != svg_hour

    def test_graph_group_by_date_differs_from_hour(self) -> None:
        # group_by="date" collapses multi-day data to one point per
        # day (3 buckets), while group_by="hour" keeps each data point
        # in its own bucket (6 buckets), producing different outputs.
        states: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "25.0",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
                "history": _MULTIDAY_HISTORY,
            }
        }
        widget = self._base_widget(hours_to_show=72)
        svg_hour = render_widget_svg(
            {**widget, "group_by": "hour"},
            self._config(states=states),
        )
        svg_date = render_widget_svg(
            {**widget, "group_by": "date"},
            self._config(states=states),
        )
        assert svg_hour != svg_date

    def test_graph_group_by_interval_same_as_default(self) -> None:
        # Explicit group_by="interval" is identical to omitting
        # group_by (both use the configured points_per_hour).
        svg_explicit = render_widget_svg(
            self._base_widget(group_by="interval"), self._config()
        )
        svg_default = render_widget_svg(self._base_widget(), self._config())
        assert svg_explicit == svg_default

    # ── Phase 2: Extrema tests ────────────────────────────────────────

    def test_graph_extrema_shown_when_enabled(self) -> None:
        # With show_extrema=True, the SVG contains "Min:" and "Max:"
        # text labels showing minimum and maximum values.
        svg = render_widget_svg(
            self._base_widget(show_extrema=True), self._config()
        )
        assert "Min:" in svg
        assert "Max:" in svg

    def test_graph_extrema_hidden_by_default(self) -> None:
        # Default config (show_extrema=False) produces no "Min:" or
        # "Max:" text in the SVG.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "Min:" not in svg
        assert "Max:" not in svg

    def test_graph_extrema_has_pixels_below_graph(self) -> None:
        # With show_extrema=True, dark pixels appear in the bottom
        # portion of the widget (where extrema text renders).
        h = 280
        widget = self._base_widget(h=h, show_extrema=True)
        img = render_to_image([widget], self._config())
        # Bottom 20% of the widget should have extrema text pixels.
        bottom_y = int(h * 0.8)
        assert_has_dark_pixels(img, 0, bottom_y, 400, h)

    def test_graph_extrema_changes_output(self) -> None:
        # Enabling show_extrema changes the rendered output.
        svg_default = render_widget_svg(self._base_widget(), self._config())
        svg_extrema = render_widget_svg(
            self._base_widget(show_extrema=True), self._config()
        )
        assert svg_default != svg_extrema

    # ── Phase 2: min_bound_range tests ───────────────────────────────

    def test_graph_min_bound_range_expands_scale(self) -> None:
        # With narrow-range data (0.5 range) and min_bound_range=10,
        # the Y-axis is expanded, changing the graph coordinates.
        states: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "20.5",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
                "history": _NARROW_HISTORY,
            }
        }
        svg_no_mbr = render_widget_svg(
            self._base_widget(smoothing=False),
            self._config(states=states),
        )
        svg_with_mbr = render_widget_svg(
            self._base_widget(smoothing=False, min_bound_range=10),
            self._config(states=states),
        )
        # Expanded range changes Y coordinate mapping.
        assert svg_no_mbr != svg_with_mbr

    def test_graph_min_bound_range_no_effect_when_sufficient(self) -> None:
        # When the data range (3.0) already exceeds min_bound_range
        # (1.0), the output is identical to no min_bound_range.
        svg_no_mbr = render_widget_svg(
            self._base_widget(smoothing=False), self._config()
        )
        svg_with_mbr = render_widget_svg(
            self._base_widget(smoothing=False, min_bound_range=1.0),
            self._config(),
        )
        # Data range is ~3.0 (20.0-23.0), which exceeds 1.0, so
        # min_bound_range has no effect.
        assert svg_no_mbr == svg_with_mbr

    # ── Phase 3: Multi-entity tests ───────────────────────────────────

    def _multi_widget(self, **overrides: object) -> dict[str, object]:
        """Return a 400×280 graph widget with two entities."""
        w: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {"entity": "sensor.temperature"},
                {"entity": "sensor.humidity"},
            ],
        }
        w.update(overrides)
        return w

    # ── Phase 3: Backward compatibility tests ────────────────────────

    def test_graph_single_entity_key_still_works(self) -> None:
        # Single entity= key (no entities list) still renders a graph
        # line when Phase 3 normalization is in place.
        svg = render_widget_svg(
            self._base_widget(smoothing=False), self._config()
        )
        assert "<polyline" in svg

    def test_graph_entities_single_item_matches_entity_key(
        self,
    ) -> None:
        # entities=[{entity: ...}] produces identical SVG to entity=...
        # for a single entity, confirming the normalization path.
        svg_key = render_widget_svg(
            self._base_widget(smoothing=False), self._config()
        )
        svg_list = render_widget_svg(
            {
                "type": "graph",
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 280,
                "entities": [{"entity": "sensor.temperature"}],
                "smoothing": False,
            },
            self._config(),
        )
        assert svg_key == svg_list

    # ── Phase 3: Multi-entity line rendering tests ────────────────────

    def test_graph_multi_entity_two_polylines(self) -> None:
        # With two entities and smoothing=False, the SVG contains
        # exactly two <polyline elements — one per series.
        svg = render_widget_svg(
            self._multi_widget(smoothing=False), self._config()
        )
        assert svg.count("<polyline") == 2

    def test_graph_multi_entity_two_paths_smoothed(self) -> None:
        # With two entities and default smoothing, the SVG contains
        # multiple Q commands (at least two series worth of curves).
        svg = render_widget_svg(self._multi_widget(), self._config())
        assert svg.count(" Q ") >= 2

    def test_graph_multi_entity_distinct_dash_patterns(self) -> None:
        # Two entities produce one solid line (no stroke-dasharray)
        # and one dashed line (stroke-dasharray="8,4").
        svg = render_widget_svg(
            self._multi_widget(smoothing=False), self._config()
        )
        assert 'stroke-dasharray="8,4"' in svg

    def test_graph_three_entities_three_dash_patterns(self) -> None:
        # Three entities produce solid, dashed, and dotted lines;
        # all three dash patterns appear in the SVG.
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {"entity": "sensor.temperature"},
                {"entity": "sensor.humidity"},
                {"entity": "sensor.pressure"},
            ],
            "smoothing": False,
        }
        svg = render_widget_svg(widget, self._config())
        assert 'stroke-dasharray="8,4"' in svg
        assert 'stroke-dasharray="2,4"' in svg

    # ── Phase 3: Multi-entity fill tests ─────────────────────────────

    def test_graph_multi_entity_only_first_entity_gets_fill(
        self,
    ) -> None:
        # With two entities and show_fill=True (default), only the
        # first entity gets a fill area — overlapping fills produce
        # visual noise on e-ink.
        svg = render_widget_svg(
            self._multi_widget(smoothing=False), self._config()
        )
        assert svg.count("<polygon") == 1

    def test_graph_multi_entity_no_fill_when_disabled(self) -> None:
        # With show_fill=False and two entities, no fill element
        # appears in the SVG.
        svg = render_widget_svg(
            self._multi_widget(smoothing=False, show_fill=False),
            self._config(),
        )
        assert "<polygon" not in svg

    # ── Phase 3: Secondary Y-axis tests ──────────────────────────────

    def test_graph_secondary_y_axis_labels_both_sides(self) -> None:
        # With one primary and one secondary entity, Y-axis labels
        # appear for both scales: temperature (20.0–23.0) on the
        # left and humidity (65.0–70.0) on the right.
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {"entity": "sensor.temperature"},
                {
                    "entity": "sensor.humidity",
                    "y_axis": "secondary",
                },
            ],
            "show_labels": True,
        }
        svg = render_widget_svg(widget, self._config())
        # Primary axis: temperature range.
        assert "20.0" in svg
        # Secondary axis: humidity range.
        assert "65.0" in svg

    def test_graph_secondary_y_axis_changes_output(self) -> None:
        # A secondary-axis entity shifts gx2 inward to make room for
        # right-side labels, producing different SVG output.
        svg_primary = render_widget_svg(self._multi_widget(), self._config())
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {"entity": "sensor.temperature"},
                {
                    "entity": "sensor.humidity",
                    "y_axis": "secondary",
                },
            ],
        }
        svg_secondary = render_widget_svg(widget, self._config())
        assert svg_primary != svg_secondary

    def test_graph_all_primary_no_right_secondary_labels(
        self,
    ) -> None:
        # When both entities use primary Y-axis (default), no secondary
        # Y-axis labels appear on the right.  Verify by comparing against
        # a configuration where one entity is on the secondary axis: the
        # secondary version must have more right-aligned text elements.
        svg_all_primary = render_widget_svg(
            self._multi_widget(show_labels=True), self._config()
        )
        widget_secondary: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {"entity": "sensor.temperature"},
                {"entity": "sensor.humidity", "y_axis": "secondary"},
            ],
            "show_labels": True,
        }
        svg_with_secondary = render_widget_svg(
            widget_secondary, self._config()
        )
        count_primary = svg_all_primary.count('text-anchor="end"')
        count_secondary = svg_with_secondary.count('text-anchor="end"')
        assert count_primary < count_secondary

    # ── Phase 3: Legend tests ─────────────────────────────────────────

    def test_graph_legend_shown_for_multi_entity(self) -> None:
        # With two entities, the SVG contains both entity names in the
        # legend area below the graph.
        svg = render_widget_svg(self._multi_widget(), self._config())
        assert "Living Room" in svg
        assert "Humidity" in svg

    def test_graph_legend_hidden_for_single_entity(self) -> None:
        # A single-entity widget does not render a legend; the second
        # entity's name does not appear.
        svg = render_widget_svg(self._base_widget(), self._config())
        assert "Humidity" not in svg

    def test_graph_legend_has_line_sample_elements(self) -> None:
        # Legend entries include <line> elements as dash-pattern
        # samples (at least one per legend entry).
        svg = render_widget_svg(
            self._multi_widget(smoothing=False),
            self._config(grayscale_levels=2),
        )
        # On 2-level display, grid lines are absent so any <line>
        # must come from legend samples.
        assert "<line" in svg

    def test_graph_legend_reserves_vertical_space(self) -> None:
        # Multi-entity render (with legend) differs from single-entity
        # at same dimensions because the legend shifts the graph up.
        svg_single = render_widget_svg(self._base_widget(), self._config())
        svg_multi = render_widget_svg(self._multi_widget(), self._config())
        assert svg_single != svg_multi

    def test_graph_legend_pixel_region(self) -> None:
        # With two entities, dark pixels appear in the bottom 20% of
        # the widget height where legend text renders.
        h = 280
        widget = self._multi_widget(h=h)
        img = render_to_image([widget], self._config())
        bottom_y = int(h * 0.8)
        assert_has_dark_pixels(img, 0, bottom_y, 400, h)

    def test_graph_legend_name_override(self) -> None:
        # A name override in the entities list appears in the legend
        # instead of the entity friendly_name.
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {
                    "entity": "sensor.temperature",
                    "name": "Temp Override",
                },
                {"entity": "sensor.humidity"},
            ],
        }
        svg = render_widget_svg(widget, self._config())
        assert "Temp Override" in svg

    # ── Phase 3: Header test ──────────────────────────────────────────

    def test_graph_multi_entity_header_shows_first_entity(
        self,
    ) -> None:
        # The header still shows the first entity's friendly name even
        # in multi-entity mode.
        svg = render_widget_svg(self._multi_widget(), self._config())
        assert "Living Room" in svg

    # ── Phase 3: Edge case tests ──────────────────────────────────────

    def test_graph_multi_entity_one_missing_still_renders(
        self,
    ) -> None:
        # When the first entity is missing, the widget still renders
        # the second entity's graph line without crashing.
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {"entity": "sensor.nonexistent"},
                {"entity": "sensor.temperature"},
            ],
            "smoothing": False,
        }
        svg = render_widget_svg(widget, self._config())
        assert "<svg" in svg
        assert "<polyline" in svg

    def test_graph_multi_entity_all_missing_renders_blank(
        self,
    ) -> None:
        # When all entities are missing from states, the widget
        # renders valid SVG but no graph line.
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [
                {"entity": "sensor.nonexistent1"},
                {"entity": "sensor.nonexistent2"},
            ],
            "smoothing": False,
        }
        svg = render_widget_svg(widget, self._config())
        assert "<svg" in svg
        assert "<polyline" not in svg

    def test_graph_entities_empty_list_renders_blank(self) -> None:
        # An empty entities list renders valid SVG with no graph line.
        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [],
            "smoothing": False,
        }
        svg = render_widget_svg(widget, self._config())
        assert "<svg" in svg
        assert "<polyline" not in svg

    def test_graph_entities_all_invalid_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A non-empty entities list where all items lack the 'entity'
        # key should log a warning before falling through to single-
        # entity mode.
        import logging

        widget: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entities": [{"bad": "data"}, {"also": "bad"}],
        }
        with caplog.at_level(logging.WARNING):
            render_widget_svg(widget, self._config())
        assert "no valid items" in caplog.text

    def test_graph_12h_time_format(self) -> None:
        # time_format="12" renders AM/PM labels on the x-axis.
        svg = render_widget_svg(
            self._base_widget(show_labels=True),
            self._config(time_format="12"),
        )
        assert "AM" in svg or "PM" in svg

    def test_format_timestamp_12h_no_leading_zero(self) -> None:
        # _format_timestamp with time_fmt="12" must not produce a
        # leading zero (e.g. "9:30 AM" not "09:30 AM").
        from custom_components.eink_dashboard.widgets.graph import (
            _format_timestamp,
        )

        # 2025-05-19 09:30 UTC
        ts = 1747647000.0
        result = _format_timestamp(ts, "12")
        assert result[0] != "0"
        assert "AM" in result or "PM" in result

    # ── Phase 4: Bar graph tests ──────────────────────────────────────

    def test_graph_bar_renders_rects(self) -> None:
        # graph="bar" produces <rect> elements for the bar columns.
        svg = render_widget_svg(self._base_widget(graph="bar"), self._config())
        assert "<rect" in svg

    def test_graph_bar_no_polyline_or_bezier(self) -> None:
        # Bar mode must not produce <polyline> or Bezier Q-curve graph
        # paths — those are line-graph elements, not bar elements.
        svg = render_widget_svg(self._base_widget(graph="bar"), self._config())
        assert "<polyline" not in svg
        assert " Q " not in svg

    def test_graph_bar_default_is_line(self) -> None:
        # Omitting the graph key defaults to line mode; bar mode must
        # produce different SVG (confirms the key is recognized).
        svg_default = render_widget_svg(self._base_widget(), self._config())
        svg_bar = render_widget_svg(
            self._base_widget(graph="bar"), self._config()
        )
        assert svg_default != svg_bar

    def test_graph_bar_differs_from_explicit_line(self) -> None:
        # Explicit graph="line" and graph="bar" produce different SVG
        # for the same entity and config.
        svg_line = render_widget_svg(
            self._base_widget(graph="line"), self._config()
        )
        svg_bar = render_widget_svg(
            self._base_widget(graph="bar"), self._config()
        )
        assert svg_line != svg_bar

    def test_graph_bar_no_data_no_rects(self) -> None:
        # When the entity has no history, bar mode renders valid SVG
        # but produces no <rect> graph elements.
        states: dict[str, dict[str, object]] = {
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
            self._base_widget(graph="bar"),
            self._config(states=states),
        )
        assert "<svg" in svg
        # No bars without history data.  The full-SVG substring check
        # is safe here because _base_widget() uses card_style="none"
        # (no card-border rect) and single-entity mode (no legend
        # swatches) — both are the only other sources of <rect> in
        # the graph template.
        assert "<rect" not in svg

    def test_graph_bar_ignores_smoothing(self) -> None:
        # smoothing=True with graph="bar" still renders <rect> bar
        # elements — smoothing is not applicable to bar charts.
        svg = render_widget_svg(
            self._base_widget(graph="bar", smoothing=True),
            self._config(),
        )
        assert "<rect" in svg
        assert " Q " not in svg

    def test_graph_bar_show_fill_ignored(self) -> None:
        # In bar mode, show_fill has no effect — bars are filled shapes
        # by definition.  Both renders must produce identical SVG.
        svg_fill_on = render_widget_svg(
            self._base_widget(graph="bar", show_fill=True),
            self._config(),
        )
        svg_fill_off = render_widget_svg(
            self._base_widget(graph="bar", show_fill=False),
            self._config(),
        )
        assert svg_fill_on == svg_fill_off

    def test_graph_bar_labels_still_shown(self) -> None:
        # Y-axis and X-axis labels render in bar mode just as they do
        # in line mode.
        svg = render_widget_svg(
            self._base_widget(graph="bar", show_labels=True),
            self._config(),
        )
        # Data range 20.0–23.0 must appear as Y-axis labels.
        assert "20.0" in svg or "20" in svg
        assert "23.0" in svg or "23" in svg
        # X-axis labels must contain HH:MM time strings.
        assert re.search(r"\d{2}:\d{2}", svg) is not None

    def test_graph_bar_extrema_works(self) -> None:
        # show_extrema=True produces "Min:" and "Max:" text in bar
        # mode, just as in line mode.
        svg = render_widget_svg(
            self._base_widget(graph="bar", show_extrema=True),
            self._config(),
        )
        assert "Min:" in svg
        assert "Max:" in svg

    def test_graph_bar_has_dark_pixels(self) -> None:
        # The graph area (below the header) contains dark pixels from
        # the bar rectangles.
        h = 280
        header_h = DEFAULT_ROW_H
        widget = self._base_widget(h=h, graph="bar")
        img = render_to_image([widget], self._config())
        assert_has_dark_pixels(img, 0, header_h, 400, h)

    def test_graph_bar_upper_lower_bound_affects_rendering(
        self,
    ) -> None:
        # Explicit Y-axis bounds change the bar heights, altering the
        # SVG coordinates.
        svg_auto = render_widget_svg(
            self._base_widget(graph="bar"), self._config()
        )
        svg_bounded = render_widget_svg(
            self._base_widget(graph="bar", upper_bound=30.0, lower_bound=0.0),
            self._config(),
        )
        assert svg_auto != svg_bounded

    def test_graph_bar_group_by_date_fewer_bars_than_hour(
        self,
    ) -> None:
        # group_by="date" collapses multi-day data to one bucket per
        # day (3 buckets for _MULTIDAY_HISTORY), while group_by="hour"
        # produces one bucket per entry (6 buckets).  Fewer buckets
        # means fewer <rect> elements.
        states: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "25.0",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
                "history": _MULTIDAY_HISTORY,
            }
        }
        widget_base = self._base_widget(graph="bar", hours_to_show=72)
        svg_hour = render_widget_svg(
            {**widget_base, "group_by": "hour"},
            self._config(states=states),
        )
        svg_date = render_widget_svg(
            {**widget_base, "group_by": "date"},
            self._config(states=states),
        )
        count_hour = svg_hour.count("<rect")
        count_date = svg_date.count("<rect")
        assert count_date < count_hour

    # ── Phase 4: Multi-entity bar tests ──────────────────────────────

    def _bar_multi_widget(self, **overrides: object) -> dict[str, object]:
        """Return a 400×280 bar graph widget with two entities."""
        w: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "graph": "bar",
            "entities": [
                {"entity": "sensor.temperature"},
                {"entity": "sensor.humidity"},
            ],
        }
        w.update(overrides)
        return w

    def test_graph_bar_multi_entity_more_rects_than_single(
        self,
    ) -> None:
        # Multi-entity bar mode renders more <rect> elements than
        # single-entity mode: two full series of bars instead of one.
        svg_single = render_widget_svg(
            self._base_widget(graph="bar"), self._config()
        )
        svg_multi = render_widget_svg(self._bar_multi_widget(), self._config())
        assert svg_multi.count("<rect") > svg_single.count("<rect")

    def test_graph_bar_multi_entity_distinct_fill_colors(
        self,
    ) -> None:
        # With two entities in bar mode (no card decoration to add
        # extra grays), the second entity's bars use hex_gray as fill,
        # which does not appear in the single-entity bar render.
        from custom_components.eink_dashboard.const import (
            COLOR_GRAY,
            color_to_hex,
        )

        gray_hex = color_to_hex(COLOR_GRAY)
        svg_single = render_widget_svg(
            self._base_widget(graph="bar", card_style="none"),
            self._config(),
        )
        svg_multi = render_widget_svg(
            self._bar_multi_widget(card_style="none"), self._config()
        )
        # Second-entity bars use gray fill; single-entity does not.
        assert svg_multi.count(gray_hex) > svg_single.count(gray_hex)

    def test_graph_bar_legend_shows_entity_names(self) -> None:
        # Multi-entity bar mode includes a legend with each entity's
        # friendly name, just as in line mode.
        svg = render_widget_svg(self._bar_multi_widget(), self._config())
        assert "Living Room" in svg
        assert "Humidity" in svg

    def test_graph_bar_single_entity_no_legend(self) -> None:
        # Single-entity bar mode does not show a legend; the second
        # entity's name must not appear.
        svg = render_widget_svg(self._base_widget(graph="bar"), self._config())
        assert "Humidity" not in svg

    def test_graph_bar_legend_uses_rect_swatches(self) -> None:
        # Bar-mode legend uses <rect> swatches rather than <line>
        # samples (lines show dash patterns; bars show fill shades).
        # On 2-level displays, grid lines are suppressed, so any
        # remaining <line> elements would be line-graph legend
        # samples.  With bar mode, no <line> elements should appear.
        svg = render_widget_svg(
            self._bar_multi_widget(),
            self._config(grayscale_levels=2),
        )
        # Legend entity names appear.
        assert "Living Room" in svg
        assert "Humidity" in svg
        # No <line> elements: grid is suppressed on 2-level and
        # legend uses <rect> swatches instead.
        assert "<line" not in svg

    # ── Phase 5: Color thresholds ─────────────────────────────────────

    # History that crosses multiple threshold boundaries so every
    # threshold band is exercised.  Values range from 5 to 35,
    # crossing boundaries at 10, 20, and 30.
    _THRESHOLD_HISTORY: ClassVar[list[dict[str, object]]] = [
        {"s": "5.0", "lu": 1747620000.0},
        {"s": "15.0", "lu": 1747634400.0},
        {"s": "25.0", "lu": 1747648800.0},
        {"s": "35.0", "lu": 1747663200.0},
        {"s": "25.0", "lu": 1747677600.0},
        {"s": "10.0", "lu": 1747692000.0},
        {"s": "20.0", "lu": 1747699200.0},
    ]

    def _threshold_config(self, **overrides: object) -> dict[str, object]:
        """Return config with threshold history for sensor.temperature."""
        states: dict[str, dict[str, object]] = {
            "sensor.temperature": {
                "state": "20.0",
                "attributes": {
                    "friendly_name": "Living Room",
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                },
                "history": self._THRESHOLD_HISTORY,
            },
            "sensor.humidity": {
                "state": "65.0",
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
        return make_config(self._DEFAULTS, states=states, **overrides)

    def _threshold_widget(self, **overrides: object) -> dict[str, object]:
        """Return a 400×280 line graph widget with three color thresholds."""
        w: dict[str, object] = {
            "type": "graph",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 280,
            "entity": "sensor.temperature",
            "color_thresholds": [
                {"value": 10, "color": "#0000ff"},
                {"value": 20, "color": "#00ff00"},
                {"value": 30, "color": "#ff0000"},
            ],
        }
        w.update(overrides)
        return w

    def test_graph_thresholds_line_has_gradient_def(self) -> None:
        # With thresholds on a line graph, the SVG output contains a
        # <linearGradient> element inside <defs>.
        svg = render_widget_svg(
            self._threshold_widget(), self._threshold_config()
        )
        assert "<linearGradient" in svg
        assert "<defs>" in svg

    def test_graph_thresholds_line_uses_gradient_stroke(self) -> None:
        # The line <path> uses a gradient URL for stroke color instead
        # of the default hex_black when thresholds are active.
        svg = render_widget_svg(
            self._threshold_widget(), self._threshold_config()
        )
        assert 'stroke="url(#thresh-stroke-0)"' in svg

    def test_graph_thresholds_smooth_single_stop_per_threshold(
        self,
    ) -> None:
        # With color_thresholds_transition="smooth" (default), each
        # threshold produces exactly one <stop> element in the gradient
        # (no duplicate stops at boundaries).
        svg = render_widget_svg(
            self._threshold_widget(color_thresholds_transition="smooth"),
            self._threshold_config(),
        )
        # 3 thresholds → 3 stops for stroke gradient + 3 for fill
        # gradient = 6 total.  Count via the stop tag.
        stop_count = svg.count("<stop ")
        # Expect 2 gradients × 3 thresholds = 6 stops.
        assert stop_count == 6

    def test_graph_thresholds_hard_double_stops_at_boundaries(
        self,
    ) -> None:
        # With color_thresholds_transition="hard", each threshold
        # boundary gets two adjacent <stop> elements so colors snap
        # rather than blend.
        svg_smooth = render_widget_svg(
            self._threshold_widget(color_thresholds_transition="smooth"),
            self._threshold_config(),
        )
        svg_hard = render_widget_svg(
            self._threshold_widget(color_thresholds_transition="hard"),
            self._threshold_config(),
        )
        # Hard mode has strictly more stop elements than smooth mode.
        assert svg_hard.count("<stop ") > svg_smooth.count("<stop ")

    def test_graph_thresholds_changes_output(self) -> None:
        # SVG with thresholds configured differs from SVG without any
        # threshold configuration.
        svg_no_thresh = render_widget_svg(
            self._base_widget(), self._threshold_config()
        )
        svg_thresh = render_widget_svg(
            self._threshold_widget(), self._threshold_config()
        )
        assert svg_no_thresh != svg_thresh

    def test_graph_thresholds_bar_per_bar_fill(self) -> None:
        # In bar mode with thresholds, bars at different value levels
        # must get different fill colors because each bar's fill is
        # determined by the threshold band containing its value.
        # Resolved grayscale for blue (#0000ff): luminance ≈ 0.
        # Resolved grayscale for red (#ff0000): luminance ≈ 76.
        # They should map to different grayscale hex values.
        svg = render_widget_svg(
            self._threshold_widget(graph="bar"),
            self._threshold_config(),
        )
        # Multiple distinct fill= values appear since bars span
        # different threshold bands.
        fill_hits = re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg)
        unique_fills = set(fill_hits)
        # At least two distinct grayscale fill colors from thresholds.
        assert len(unique_fills) >= 2

    def test_graph_thresholds_bar_no_gradient(self) -> None:
        # Bar mode with thresholds uses per-bar fill colors rather than
        # SVG linearGradient — no <linearGradient> element is expected.
        svg = render_widget_svg(
            self._threshold_widget(graph="bar"),
            self._threshold_config(),
        )
        assert "<linearGradient" not in svg

    def test_graph_thresholds_rgb_mapped_to_grayscale(self) -> None:
        # Threshold colors are auto-mapped to grayscale on e-ink
        # displays.  The original RGB values (pure blue, green, red)
        # must not appear as-is in the stop-color attributes; grayscale
        # equivalents are expected instead.
        svg = render_widget_svg(
            self._threshold_widget(), self._threshold_config()
        )
        # Original saturated colors must not appear verbatim.
        assert "#0000ff" not in svg
        assert "#00ff00" not in svg
        assert "#ff0000" not in svg

    def test_graph_thresholds_shade_dark_maps_to_gray(self) -> None:
        # A threshold entry with shade="dark" must resolve to the
        # COLOR_GRAY hex value regardless of any color key.
        from custom_components.eink_dashboard.const import (
            COLOR_GRAY,
            color_to_hex,
        )

        gray_hex = color_to_hex(COLOR_GRAY)
        svg = render_widget_svg(
            self._threshold_widget(
                color_thresholds=[
                    {"value": 10, "shade": "dark", "color": "#ff0000"},
                    {"value": 20, "shade": "medium"},
                ]
            ),
            self._threshold_config(),
        )
        # COLOR_GRAY hex must appear as a stop-color (shade overrides).
        assert f'stop-color="{gray_hex}"' in svg

    def test_graph_thresholds_shade_only_no_color_key(self) -> None:
        # A threshold entry with only shade (no color key) resolves to
        # the appropriate constant without crashing.
        from custom_components.eink_dashboard.const import (
            COLOR_LIGHT_GRAY,
            color_to_hex,
        )

        light_gray_hex = color_to_hex(COLOR_LIGHT_GRAY)
        svg = render_widget_svg(
            self._threshold_widget(
                color_thresholds=[
                    {"value": 10, "shade": "light"},
                    {"value": 25, "shade": "dark"},
                ]
            ),
            self._threshold_config(),
        )
        assert f'stop-color="{light_gray_hex}"' in svg

    def test_graph_thresholds_suppressed_on_2level(self) -> None:
        # On 2-level (B&W) displays, color thresholds are suppressed
        # entirely: no <linearGradient> appears even when configured.
        svg = render_widget_svg(
            self._threshold_widget(),
            self._threshold_config(grayscale_levels=2),
        )
        assert "<linearGradient" not in svg

    def test_graph_thresholds_line_stroke_black_on_2level(self) -> None:
        # On 2-level displays with thresholds suppressed, the line
        # uses the default hex_black stroke, not a gradient URL.
        from custom_components.eink_dashboard.const import (
            COLOR_BLACK,
            color_to_hex,
        )

        black_hex = color_to_hex(COLOR_BLACK)
        svg = render_widget_svg(
            self._threshold_widget(),
            self._threshold_config(grayscale_levels=2),
        )
        # Gradient URL must not appear for stroke; black must be present.
        assert "thresh-stroke" not in svg
        assert black_hex in svg

    def test_graph_thresholds_bar_suppressed_on_2level(self) -> None:
        # On 2-level displays with bar mode, per-bar threshold fills
        # are suppressed and entity-level _BAR_FILL_COLORS are used.
        # _BAR_FILL_COLORS[0] = black (#000000) for entity 0.
        from custom_components.eink_dashboard.const import (
            COLOR_BLACK,
            color_to_hex,
        )

        black_hex = color_to_hex(COLOR_BLACK)
        svg = render_widget_svg(
            self._threshold_widget(graph="bar"),
            self._threshold_config(grayscale_levels=2),
        )
        # All bar fills should be black (entity-level), not per-bar.
        assert black_hex in svg
        # Verify no threshold-derived non-black fills appear.  With
        # thresholds suppressed, only black should appear in fill=
        # attributes on rects (the entity-level color for entity 0).
        fill_hits = re.findall(r'<rect[^>]*fill="(#[0-9a-fA-F]{6})"', svg)
        # Should only contain the entity-level black fill.
        assert all(f == black_hex for f in fill_hits)

    def test_graph_thresholds_empty_list_no_effect(self) -> None:
        # An empty color_thresholds list produces the same output as
        # no threshold configuration at all.
        svg_no_thresh = render_widget_svg(
            self._base_widget(), self._threshold_config()
        )
        svg_empty_thresh = render_widget_svg(
            self._base_widget(color_thresholds=[]),
            self._threshold_config(),
        )
        assert svg_no_thresh == svg_empty_thresh

    def test_graph_thresholds_single_entry_no_effect(self) -> None:
        # A single threshold entry (fewer than 2) is not enough to
        # activate the feature; output equals no-threshold baseline.
        svg_no_thresh = render_widget_svg(
            self._base_widget(), self._threshold_config()
        )
        svg_one_thresh = render_widget_svg(
            self._base_widget(
                color_thresholds=[{"value": 20, "color": "#ff0000"}]
            ),
            self._threshold_config(),
        )
        assert svg_no_thresh == svg_one_thresh

    def test_graph_thresholds_default_transition_is_smooth(self) -> None:
        # Omitting color_thresholds_transition defaults to "smooth"
        # behavior, producing the same output as explicit "smooth".
        svg_default = render_widget_svg(
            self._threshold_widget(), self._threshold_config()
        )
        svg_smooth = render_widget_svg(
            self._threshold_widget(color_thresholds_transition="smooth"),
            self._threshold_config(),
        )
        assert svg_default == svg_smooth

    def test_graph_thresholds_multi_entity_line_each_series_gets_gradient(
        self,
    ) -> None:
        # With two entities and thresholds, both series get their own
        # gradient definition (thresh-stroke-0 and thresh-stroke-1).
        svg = render_widget_svg(
            self._threshold_widget(
                entities=[
                    {"entity": "sensor.temperature"},
                    {"entity": "sensor.humidity"},
                ]
            ),
            self._threshold_config(),
        )
        assert "thresh-stroke-0" in svg
        assert "thresh-stroke-1" in svg

    def test_graph_thresholds_works_with_labels_and_extrema(self) -> None:
        # Color thresholds render without conflict when axis labels and
        # extrema text are also enabled.
        svg = render_widget_svg(
            self._threshold_widget(show_labels=True, show_extrema=True),
            self._threshold_config(),
        )
        # Gradient still present alongside labels.
        assert "<linearGradient" in svg
        # Extrema strings also present.
        assert "Min:" in svg

    def test_graph_thresholds_has_gray_pixels_in_graph_area(
        self,
    ) -> None:
        # When thresholds map to gray shades on a multi-grayscale
        # display, the rendered graph area contains gray (non-black)
        # pixels from the gradient.
        h = 280
        widget = self._threshold_widget(
            h=h,
            color_thresholds=[
                {"value": 10, "shade": "medium"},
                {"value": 25, "shade": "dark"},
            ],
        )
        img = render_to_image([widget], self._threshold_config())
        header_h = DEFAULT_ROW_H
        # Check the graph region (below header) for gray pixels.
        assert_has_gray_pixels(img, 0, header_h, 400, h)

    def test_graph_thresholds_flat_keys_accepted(self) -> None:
        # Flat editor keys (threshold_1_value, threshold_1_color, etc.)
        # produce the same gradient output as the canonical
        # color_thresholds list format.
        svg_canonical = render_widget_svg(
            self._threshold_widget(
                color_thresholds=[
                    {"value": 10, "color": "#0000ff"},
                    {"value": 20, "color": "#ff0000"},
                ]
            ),
            self._threshold_config(),
        )
        svg_flat = render_widget_svg(
            self._base_widget(
                threshold_1_value=10,
                threshold_1_color="#0000ff",
                threshold_2_value=20,
                threshold_2_color="#ff0000",
            ),
            self._threshold_config(),
        )
        assert svg_canonical == svg_flat

    def test_graph_thresholds_canonical_list_overrides_flat_keys(
        self,
    ) -> None:
        # When both color_thresholds list and flat keys are present,
        # the canonical list takes precedence and the flat keys are
        # ignored.
        svg_list_only = render_widget_svg(
            self._threshold_widget(
                color_thresholds=[
                    {"value": 10, "color": "#0000ff"},
                    {"value": 20, "color": "#ff0000"},
                ]
            ),
            self._threshold_config(),
        )
        svg_both = render_widget_svg(
            self._threshold_widget(
                color_thresholds=[
                    {"value": 10, "color": "#0000ff"},
                    {"value": 20, "color": "#ff0000"},
                ],
                # Flat keys present but should be ignored.
                threshold_1_value=5,
                threshold_1_color="#00ff00",
                threshold_2_value=15,
                threshold_2_color="#ff00ff",
            ),
            self._threshold_config(),
        )
        assert svg_list_only == svg_both

    # ── Unit tests for threshold helper functions ──────────────────────

    def test_rgb_hex_to_grayscale_pure_red(self) -> None:
        # Pure red (#ff0000): BT.601 luminance = 0.299*255 ≈ 76 → gray.
        from custom_components.eink_dashboard.widgets.graph import (
            _rgb_hex_to_grayscale,
        )

        result = _rgb_hex_to_grayscale("#ff0000", 16)
        # Luminance of pure red is 76; quantized on 16 levels.
        assert result.startswith("#")
        assert len(result) == 7

    def test_rgb_hex_to_grayscale_pure_white(self) -> None:
        # Pure white (#ffffff) must map to white on any display depth.
        from custom_components.eink_dashboard.widgets.graph import (
            _rgb_hex_to_grayscale,
        )

        assert _rgb_hex_to_grayscale("#ffffff", 16) == "#ffffff"

    def test_rgb_hex_to_grayscale_pure_black(self) -> None:
        # Pure black (#000000) must remain black on any display depth.
        from custom_components.eink_dashboard.widgets.graph import (
            _rgb_hex_to_grayscale,
        )

        assert _rgb_hex_to_grayscale("#000000", 16) == "#000000"

    def test_rgb_hex_to_grayscale_2level_threshold(self) -> None:
        # On a 2-level display, mid-gray (127) maps to black and
        # near-white (200) maps to white.
        from custom_components.eink_dashboard.widgets.graph import (
            _rgb_hex_to_grayscale,
        )

        # Gray 127 → below 128 threshold → black.
        dark = _rgb_hex_to_grayscale("#7f7f7f", 2)
        assert dark == "#000000"
        # Gray 200 → at or above 128 threshold → white.
        light = _rgb_hex_to_grayscale("#c8c8c8", 2)
        assert light == "#ffffff"

    def test_rgb_hex_to_grayscale_bad_input(self) -> None:
        # Inputs that cannot be parsed fall back to black.
        from custom_components.eink_dashboard.widgets.graph import (
            _rgb_hex_to_grayscale,
        )

        assert _rgb_hex_to_grayscale("notacolor", 16) == "#000000"
        assert _rgb_hex_to_grayscale("#gg0000", 16) == "#000000"

    def test_lighter_hex_black_gives_mid_gray(self) -> None:
        # _lighter_hex shifts 50% toward white: black (#000000) → 127.
        from custom_components.eink_dashboard.const import color_to_hex
        from custom_components.eink_dashboard.widgets.graph import _lighter_hex

        result = _lighter_hex("#000000")
        # (0 + 255) // 2 = 127.
        assert result == color_to_hex(127)

    def test_lighter_hex_white_stays_white(self) -> None:
        # Shifting white 50% toward white produces white.
        from custom_components.eink_dashboard.widgets.graph import _lighter_hex

        assert _lighter_hex("#ffffff") == "#ffffff"

    def test_lighter_hex_bad_input(self) -> None:
        # A non-hex input falls back to COLOR_LIGHT_GRAY.
        # "#gg0000" → slice [1:3] = "gg" → int("gg", 16) raises ValueError.
        from custom_components.eink_dashboard.const import (
            COLOR_LIGHT_GRAY,
            color_to_hex,
        )
        from custom_components.eink_dashboard.widgets.graph import _lighter_hex

        assert _lighter_hex("#gg0000") == color_to_hex(COLOR_LIGHT_GRAY)

    def test_shade_to_hex_known_shades(self) -> None:
        # Each named shade must map to the expected constant.
        from custom_components.eink_dashboard.const import (
            COLOR_BLACK,
            COLOR_GRAY,
            COLOR_LIGHT_GRAY,
            COLOR_MEDIUM_GRAY,
            color_to_hex,
        )
        from custom_components.eink_dashboard.widgets.graph import (
            _shade_to_hex,
        )

        assert _shade_to_hex("black") == color_to_hex(COLOR_BLACK)
        assert _shade_to_hex("dark") == color_to_hex(COLOR_GRAY)
        assert _shade_to_hex("medium") == color_to_hex(COLOR_MEDIUM_GRAY)
        assert _shade_to_hex("light") == color_to_hex(COLOR_LIGHT_GRAY)

    def test_shade_to_hex_unknown_falls_back_to_black(self) -> None:
        # An unrecognised shade string falls back to black.
        from custom_components.eink_dashboard.widgets.graph import (
            _shade_to_hex,
        )

        assert _shade_to_hex("neon") == "#000000"

    def test_resolve_threshold_color_shade_overrides_color(self) -> None:
        # shade takes precedence over color in the same entry.
        from custom_components.eink_dashboard.const import (
            COLOR_GRAY,
            color_to_hex,
        )
        from custom_components.eink_dashboard.widgets.graph import (
            _resolve_threshold_color,
        )

        entry = {"shade": "dark", "color": "#ff0000"}
        assert _resolve_threshold_color(entry, 16) == color_to_hex(COLOR_GRAY)

    def test_resolve_threshold_color_no_keys_gives_black(self) -> None:
        # An entry with neither shade nor color resolves to black.
        from custom_components.eink_dashboard.widgets.graph import (
            _resolve_threshold_color,
        )

        assert _resolve_threshold_color({"value": 10}, 16) == "#000000"

    def test_bar_threshold_fill_below_first_threshold(self) -> None:
        # A value below all thresholds uses the lowest threshold's color.
        from custom_components.eink_dashboard.widgets.graph import (
            _bar_threshold_fill,
        )

        thresholds = [
            {"value": 10, "shade": "light"},
            {"value": 20, "shade": "dark"},
        ]
        result = _bar_threshold_fill(5.0, thresholds, 16)
        from custom_components.eink_dashboard.const import (
            COLOR_LIGHT_GRAY,
            color_to_hex,
        )

        assert result == color_to_hex(COLOR_LIGHT_GRAY)

    def test_bar_threshold_fill_above_all_thresholds(self) -> None:
        # A value at or above the highest threshold uses the top band.
        from custom_components.eink_dashboard.widgets.graph import (
            _bar_threshold_fill,
        )

        thresholds = [
            {"value": 10, "shade": "light"},
            {"value": 20, "shade": "dark"},
        ]
        result = _bar_threshold_fill(25.0, thresholds, 16)
        from custom_components.eink_dashboard.const import (
            COLOR_GRAY,
            color_to_hex,
        )

        assert result == color_to_hex(COLOR_GRAY)

    def test_bar_threshold_fill_at_boundary(self) -> None:
        # A value exactly equal to a threshold boundary uses that band.
        from custom_components.eink_dashboard.widgets.graph import (
            _bar_threshold_fill,
        )

        thresholds = [
            {"value": 10, "shade": "light"},
            {"value": 20, "shade": "dark"},
        ]
        result = _bar_threshold_fill(20.0, thresholds, 16)
        from custom_components.eink_dashboard.const import (
            COLOR_GRAY,
            color_to_hex,
        )

        assert result == color_to_hex(COLOR_GRAY)

    def test_normalize_thresholds_duplicate_values_sorted(self) -> None:
        # Duplicate threshold values are accepted and the result is
        # sorted ascending by value.
        from custom_components.eink_dashboard.widgets.graph import (
            _normalize_thresholds,
        )

        widget: dict[str, object] = {
            "color_thresholds": [
                {"value": 20, "color": "#ff0000"},
                {"value": 10, "color": "#0000ff"},
                {"value": 20, "color": "#00ff00"},
            ]
        }
        result = _normalize_thresholds(widget)
        values = [float(str(t["value"])) for t in result]
        assert values == sorted(values)

    def test_normalize_thresholds_skips_non_numeric_values(self) -> None:
        # Entries with non-numeric value strings are silently skipped.
        from custom_components.eink_dashboard.widgets.graph import (
            _normalize_thresholds,
        )

        widget: dict[str, object] = {
            "color_thresholds": [
                {"value": "bad", "color": "#ff0000"},
                {"value": 15, "color": "#00ff00"},
            ]
        }
        result = _normalize_thresholds(widget)
        assert len(result) == 1
        assert float(str(result[0]["value"])) == 15.0

    def test_threshold_gradient_stops_out_of_range(self) -> None:
        # Threshold values outside [y_min, y_max] are clamped to the
        # 0% or 100% offset boundaries, not dropped.
        from custom_components.eink_dashboard.widgets.graph import (
            _threshold_gradient_stops,
        )

        thresholds = [
            {"value": -100, "shade": "light"},
            {"value": 200, "shade": "dark"},
        ]
        stops = _threshold_gradient_stops(
            thresholds, "smooth", y_min=0.0, y_max=100.0, grayscale_levels=16
        )
        # Both stops must still be present; offsets are clamped.
        assert len(stops) == 2
        offsets = [s["offset"] for s in stops]
        # High value (200) → offset at 0% (top); low (-100) → 100% (bot).
        assert "0.00%" in offsets
        assert "100.00%" in offsets

    # ── R7: Fill gradient presence test ───────────────────────────────

    def test_graph_thresholds_fill_gradient_present(self) -> None:
        # When thresholds are active, the SVG must contain both a
        # stroke gradient (thresh-stroke-0) and a fill gradient
        # (thresh-fill-0) for the first series.
        svg = render_widget_svg(
            self._threshold_widget(), self._threshold_config()
        )
        assert "thresh-stroke-0" in svg
        assert "thresh-fill-0" in svg

    def test_graph_thresholds_fill_gradient_uses_lighter_colors(
        self,
    ) -> None:
        # The fill gradient stops must use lighter colors than the
        # stroke gradient stops (each fill stop is 50% shifted toward
        # white relative to the corresponding stroke stop).
        import re as _re

        svg = render_widget_svg(
            self._threshold_widget(
                color_thresholds=[
                    {"value": 10, "shade": "black"},
                    {"value": 25, "shade": "dark"},
                ]
            ),
            self._threshold_config(),
        )
        # Extract all stop-color values in document order.
        stop_colors = _re.findall(r'stop-color="(#[0-9a-fA-F]{6})"', svg)
        # First half = stroke stops, second half = fill stops.
        # (2 thresholds × 2 gradients = 4 stops total)
        assert len(stop_colors) == 4
        stroke_stops = stop_colors[:2]
        fill_stops = stop_colors[2:]
        for stroke_hex, fill_hex in zip(stroke_stops, fill_stops, strict=True):
            stroke_val = int(stroke_hex[1:3], 16)
            fill_val = int(fill_hex[1:3], 16)
            # Fill is lighter (higher value) than stroke.
            assert fill_val >= stroke_val

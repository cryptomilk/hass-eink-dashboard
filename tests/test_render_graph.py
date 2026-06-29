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
}


class TestRenderGraph:
    """Verify rendering of graph widgets.

    Phase 1 covers single-entity line graphs with header, polyline,
    optional fill, Y-axis auto-scaling, hours_to_show, aggregate
    functions, and card styles.

    Phase 2 adds path smoothing, axis labels, grid lines, group_by,
    extrema display, and min_bound_range.
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

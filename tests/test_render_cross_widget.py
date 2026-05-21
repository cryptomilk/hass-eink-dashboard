from __future__ import annotations

import datetime as dt
import re
from typing import ClassVar
from unittest.mock import patch

from custom_components.eink_dashboard.const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    COLOR_WHITE,
    PADDING,
    color_to_hex,
)
from custom_components.eink_dashboard.render import (
    _compute_metrics,
)
from custom_components.eink_dashboard.svg_render import render_widget_svg
from tests.helpers import (
    assert_has_dark_pixels,
    content_bbox,
    make_config,
    render_to_image,
)
from tests.test_render_waste_schedule import (
    _PATCH_NOW,
    _TODAY,
    MOCK_WASTE_SCHEDULE_STATES,
)
from tests.test_render_weather import MOCK_WEATHER_STATE

# Used only by TestConsistencyContract — not shared with other files.
MOCK_SENSOR_STATES = {
    "sensor.living_room_temperature": {
        "state": "22.5",
        "attributes": {
            "friendly_name": "Living Room",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    },
}


class TestFontSizeControls:
    """Verify that font_size config is respected per widget type."""

    def test_weather_custom_font_size(self) -> None:
        # font_size=11 → s=11/32≈0.34; icon_size=22, temp at x+26
        # detail_y = y+icon_size+round(8*s) = 10+22+3 = 35
        widgets = [
            {
                "type": "weather",
                "entity": "weather.home",
                "x": PADDING,
                "y": 10,
                "font_size": 11,
            }
        ]
        img = render_to_image(
            widgets,
            {"width": 400, "height": 200, "states": MOCK_WEATHER_STATE},
        )
        assert_has_dark_pixels(img, PADDING + 22, 10, PADDING + 100, 40)
        # Detail chips at detail_y=35 (wrong /22 divisor shifts them to y=46)
        assert_has_dark_pixels(img, PADDING, 35, PADDING + 200, 46)

    def test_device_battery_default_render(self) -> None:
        # device_battery derives font size from h (not font_size);
        # verify that a default h=40 render produces dark pixels in
        # the icon and label region at 75% charge.
        widgets = [
            {
                "type": "device_battery",
                "x": PADDING,
                "y": 20,
            }
        ]
        img = render_to_image(
            widgets,
            {"width": 400, "height": 100, "device_battery_level": 75},
        )
        assert_has_dark_pixels(img, PADDING + 32, 10, PADDING + 90, 40)


class TestConsistencyContract:
    """Regression guards for cross-widget layout consistency.

    These tests assert that shared layout primitives (icon position,
    icon diameter, text position, color palette) remain consistent
    across widget types as the codebase evolves.
    """

    _ROW_H = 56
    _W = 400

    @classmethod
    def setup_class(cls) -> None:
        """Render reference images once for all tests in this class."""
        tile_widget: dict[str, object] = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": cls._W,
            "h": cls._ROW_H,
            "entity": "sensor.living_room_temperature",
        }
        tile_cfg = make_config(
            {
                "width": cls._W,
                "height": cls._ROW_H,
                "states": MOCK_SENSOR_STATES,
            }
        )
        cls._tile_img = render_to_image([tile_widget], tile_cfg)

        ws_widget: dict[str, object] = {
            "type": "waste_schedule",
            "x": 0,
            "y": 0,
            "w": cls._W,
            "h": cls._ROW_H,
            "entity": "sensor.waste_collection",
            "entries": [{"attribute": "Restmuell", "label": "Restmuell"}],
        }
        ws_cfg = make_config(
            {
                "width": cls._W,
                "height": cls._ROW_H,
                "states": MOCK_WASTE_SCHEDULE_STATES,
            }
        )
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            cls._ws_img = render_to_image([ws_widget], ws_cfg)

    def test_card_row_widgets_share_icon_position(self) -> None:
        # Two card_row widgets at the same row_h place the icon circle
        # at the same x offset from the widget left edge.
        m = _compute_metrics(self._ROW_H)
        # Strip exactly wide enough to contain the icon circle, no wider,
        # to avoid glyph ink from the text region affecting the bbox.
        icon_x2 = m.padding + m.icon_dia
        tile_bbox = content_bbox(self._tile_img, 0, 0, icon_x2, self._ROW_H)
        ws_bbox = content_bbox(self._ws_img, 0, 0, icon_x2, self._ROW_H)

        assert tile_bbox is not None, "tile: no icon pixels found"
        assert ws_bbox is not None, "waste_schedule: no icon pixels found"
        assert abs(tile_bbox[0] - ws_bbox[0]) <= 1, (
            f"icon left edge differs: tile={tile_bbox[0]}, "
            f"waste_schedule={ws_bbox[0]}"
        )

    def test_card_row_widgets_share_icon_diameter(self) -> None:
        # Two card_row widgets at the same row_h produce the same icon
        # circle width (icon_dia from _compute_metrics).
        m = _compute_metrics(self._ROW_H)
        icon_x2 = m.padding + m.icon_dia
        tile_bbox = content_bbox(self._tile_img, 0, 0, icon_x2, self._ROW_H)
        ws_bbox = content_bbox(self._ws_img, 0, 0, icon_x2, self._ROW_H)

        assert tile_bbox is not None
        assert ws_bbox is not None
        tile_dia = tile_bbox[2] - tile_bbox[0]
        ws_dia = ws_bbox[2] - ws_bbox[0]
        assert abs(tile_dia - ws_dia) <= 1, (
            f"icon diameter differs: tile={tile_dia}, waste_schedule={ws_dia}"
        )

    def test_card_row_widgets_share_text_position(self) -> None:
        # Two card_row widgets at the same row_h place primary text at
        # the same x offset.  Tolerance of 1px accounts for glyph-edge
        # variation between different first characters (e.g. 'L' vs 'R'
        # have slightly different leftmost ink pixels in Roboto).
        m = _compute_metrics(self._ROW_H)
        # Expected text x: lpad + icon_dia + inner_gap with no card frame.
        tx = m.padding + m.icon_dia + m.inner_gap

        # Crop just the text area (right of icon).
        tile_bbox = content_bbox(
            self._tile_img, tx - 2, 0, tx + 200, self._ROW_H
        )
        ws_bbox = content_bbox(self._ws_img, tx - 2, 0, tx + 200, self._ROW_H)

        assert tile_bbox is not None, "tile: no text pixels found"
        assert ws_bbox is not None, "waste_schedule: no text pixels found"
        assert abs(tile_bbox[0] - ws_bbox[0]) <= 1, (
            f"text left edge differs by more than 1px: "
            f"tile={tile_bbox[0]}, waste_schedule={ws_bbox[0]}"
        )

    def test_svg_colors_match_palette_tile(self) -> None:
        # All hex colors in a rendered tile SVG come from
        # color_to_hex() applied to known const.py color constants.
        widget: dict[str, object] = {
            "type": "tile",
            "x": 0,
            "y": 0,
            "w": self._W,
            "h": self._ROW_H,
            "entity": "sensor.living_room_temperature",
        }
        cfg = make_config(
            {
                "width": self._W,
                "height": self._ROW_H,
                "states": MOCK_SENSOR_STATES,
            }
        )
        svg = render_widget_svg(widget, cfg)
        palette = {
            color_to_hex(COLOR_BLACK),
            color_to_hex(COLOR_WHITE),
            color_to_hex(COLOR_GRAY),
            color_to_hex(COLOR_LIGHT_GRAY),
        }
        colors = set(re.findall(r"#[0-9a-f]{6}", svg.lower()))
        assert colors <= palette, (
            f"Unexpected hex colors in tile SVG: {colors - palette}"
        )

    def test_svg_colors_match_palette_waste_schedule(self) -> None:
        # All hex colors in a rendered waste_schedule SVG come from
        # color_to_hex() — including per-row dynamic fills for urgency
        # styling (date_fill, icon_fill).
        widget: dict[str, object] = {
            "type": "waste_schedule",
            "x": 0,
            "y": 0,
            "w": self._W,
            "h": self._ROW_H,
            "entity": "sensor.waste_collection",
            "entries": [{"attribute": "Restmuell", "label": "Restmuell"}],
        }
        cfg = make_config(
            {
                "width": self._W,
                "height": self._ROW_H,
                "states": MOCK_WASTE_SCHEDULE_STATES,
            }
        )
        palette = {
            color_to_hex(COLOR_BLACK),
            color_to_hex(COLOR_WHITE),
            color_to_hex(COLOR_GRAY),
            color_to_hex(COLOR_LIGHT_GRAY),
        }
        with patch(_PATCH_NOW, wraps=dt.date) as mock_dt:
            mock_dt.today.return_value = _TODAY
            svg = render_widget_svg(widget, cfg)
        colors = set(re.findall(r"#[0-9a-f]{6}", svg.lower()))
        assert colors <= palette, (
            f"Unexpected hex colors in waste_schedule SVG: {colors - palette}"
        )


class TestLocaleFormattingInWidgets:
    """Verify that locale number format is applied in SVG output."""

    _DEFAULTS: ClassVar[dict[str, object]] = {
        "width": 400,
        "height": 100,
        "number_format": "comma_decimal",
        "language": "en",
    }

    def _config(self, **overrides: object) -> dict[str, object]:
        return make_config(self._DEFAULTS, **overrides)

    def test_entity_widget_decimal_comma(self) -> None:
        # Entity widget with German locale must render comma decimal.
        widget = {
            "type": "entity",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

    def test_entity_widget_comma_decimal(self) -> None:
        # Entity widget with US locale must keep dot decimal.
        widget = {
            "type": "entity",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="comma_decimal",
            language="en",
        )
        svg = render_widget_svg(widget, config)
        assert "8.4" in svg

    def test_sensor_row_decimal_comma(self) -> None:
        # Entity widget secondary text must be formatted for German locale.
        widget = {
            "type": "entity",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {
                        "unit_of_measurement": "g/m³",
                        "friendly_name": "Humidity",
                    },
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg

    def test_non_numeric_state_unchanged(self) -> None:
        # "unavailable" should not be mangled by format_number.
        widget = {
            "type": "entity",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "unavailable",
                    "attributes": {},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "unavailable" in svg

    def test_tile_widget_decimal_comma(self) -> None:
        # Tile secondary text must use comma decimal for German locale.
        widget = {
            "type": "tile",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

    def test_heading_badge_decimal_comma(self) -> None:
        # Heading badge state must use comma decimal for German locale.
        widget = {
            "type": "heading",
            "heading": "Room",
            "badges": ["sensor.humidity"],
            "w": 400,
            "h": 56,
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

    def test_entities_decimal_comma(self) -> None:
        # Entities state value must use comma decimal for German locale.
        widget = {
            "type": "entities",
            "entities": ["sensor.humidity"],
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {
                        "unit_of_measurement": "g/m³",
                        "friendly_name": "Humidity",
                    },
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

    def test_weather_decimal_comma(self) -> None:
        # Weather detail values must use dot-thousands for German locale.
        # Pressure 1013 → "1.013" with decimal_comma thousands separator.
        widget = {
            "type": "weather",
            "entity": "weather.home",
        }
        config = self._config(
            width=600,
            height=400,
            states=MOCK_WEATHER_STATE,
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "1.013" in svg

    def test_sensor_widget_decimal_comma(self) -> None:
        # Sensor widget value must use comma decimal for German locale.
        widget = {
            "type": "sensor",
            "entity": "sensor.humidity",
        }
        config = self._config(
            states={
                "sensor.humidity": {
                    "state": "8.41",
                    "attributes": {"unit_of_measurement": "g/m³"},
                }
            },
            number_format="decimal_comma",
            language="de",
        )
        svg = render_widget_svg(widget, config)
        assert "8,4" in svg
        assert "8.41" not in svg

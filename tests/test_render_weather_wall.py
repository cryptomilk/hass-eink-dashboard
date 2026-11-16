# Copyright 2026 Kit Lerman
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

"""Tests for the weather wall widget."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.eink_dashboard.exceptions import RenderNotReady
from custom_components.eink_dashboard.svg_render import render_widget_svg
from custom_components.eink_dashboard.widgets import weather_wall
from custom_components.eink_dashboard.widgets.weather_wall import (
    _build_weather_wall_context,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = "custom_components.eink_dashboard.widgets.weather_wall._now"


@pytest.fixture(autouse=True)
def _no_installed_climatology(tmp_path: Path):
    """Keep a climatology table on the developer's machine out of tests.

    Without a ``climatology_file`` option the widget falls back to the
    component directory, where a real installation may keep its own
    table; point that fallback somewhere empty, and start each test
    with an empty cache.
    """
    absent = tmp_path / "no-climatology.json"
    with patch.object(weather_wall, "_LEGACY_CLIMATOLOGY_PATH", absent):
        weather_wall._CLIMATOLOGY_CACHE.clear()
        weather_wall._CLIMATOLOGY_WARNED.clear()
        yield
        weather_wall._CLIMATOLOGY_CACHE.clear()


def _at(month: int, day: int, hour: int) -> datetime:
    """Return a time in Home Assistant's default zone.

    Built in whichever zone the test environment has set, so that the
    clock, the forecast timestamps and the widget's local-time
    conversions all agree.
    """
    return datetime(
        2026, month, day, hour, 0, tzinfo=dt_util.get_default_time_zone()
    )


def _states(
    now: datetime,
    *,
    highs: tuple[float, ...] = (10, 8, 7, 12, 12, 9, 6, 11),
    lows: tuple[float, ...] = (5, 2, 0, 3, 7, 1, -1, 4),
    hourly: tuple[float, ...] = (9, 10, 10, 9, 8),
    sun_up: bool = False,
) -> dict[str, Any]:
    """Build a states snapshot with daily and hourly forecasts.

    Args:
        now: The render time; forecasts start from its date and hour.
        highs: Daily maxima in degrees Celsius, today first.
        lows: Daily minima in degrees Celsius, today first.
        hourly: Hourly temperatures, repeated over two days.
        sun_up: Whether ``sun.sun`` is above the horizon.

    Returns:
        A states dict with ``weather.home``, ``sun.sun`` and
        ``sensor.moon_phase``.
    """
    midnight = now.replace(hour=0)
    conditions = ("rainy", "sunny", "partlycloudy", "fog", "cloudy")
    daily = [
        {
            "datetime": (midnight + timedelta(days=i)).isoformat(),
            "temperature": highs[i],
            "templow": lows[i],
            "condition": conditions[i % len(conditions)],
            "precipitation": None,
            "precipitation_probability": (55, 0, 23, 40, 80, 10, 5, 36)[i],
            "wind_speed": 15,
            "wind_gust_speed": 20,
            "wind_bearing": 45,
            "uv_index": 1,
        }
        for i in range(len(highs))
    ]
    hours = [
        {
            "datetime": (now + timedelta(hours=i)).isoformat(),
            "temperature": hourly[i % len(hourly)],
            "condition": "cloudy",
            "precipitation_probability": 20,
            "wind_speed": 5,
            "cloud_coverage": 10,
        }
        for i in range(48)
    ]
    return {
        "weather.home": {
            "state": "rainy",
            "attributes": {
                "temperature": highs[0],
                "temperature_unit": "°C",
                "wind_speed_unit": "km/h",
                "precipitation_unit": "mm",
                "forecast": daily,
                "forecast_hourly": hours,
            },
        },
        "sun.sun": {
            "state": "above_horizon" if sun_up else "below_horizon",
            "attributes": {
                "next_setting": (
                    midnight + timedelta(hours=16, minutes=18)
                ).isoformat(),
                "next_rising": (
                    midnight + timedelta(days=1, hours=7, minutes=12)
                ).isoformat(),
            },
        },
        "sensor.moon_phase": {"state": "waning_crescent", "attributes": {}},
    }


def _widget(**overrides: Any) -> dict[str, Any]:
    """Return a full-panel weather wall widget dict."""
    widget: dict[str, Any] = {
        "type": "weather_wall",
        "entity": "weather.home",
        "x": 0,
        "y": 0,
        "w": 800,
        "h": 480,
    }
    widget.update(overrides)
    return widget


def _config(states: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Return an 800 x 480 display config for ``states``."""
    config: dict[str, Any] = {
        "width": 800,
        "height": 480,
        "states": states,
        "language": "en",
    }
    config.update(overrides)
    return config


def _ctx(
    now: datetime,
    states: dict[str, Any] | None = None,
    widget: dict[str, Any] | None = None,
    **config: Any,
) -> dict[str, Any]:
    """Build the template context with a patched clock."""
    with patch(_NOW, return_value=now):
        return _build_weather_wall_context(
            widget or _widget(),  # type: ignore[arg-type]
            _config(states if states is not None else _states(now), **config),
        )


def _texts(svg: str) -> list[str]:
    """Return the non-empty text content of every text element."""
    return [t for t in re.findall(r">([^<]*?)</text>", svg) if t.strip()]


def _fahrenheit(states: dict[str, Any]) -> dict[str, Any]:
    """Express the same weather in degrees F, mph and inches."""
    out = copy.deepcopy(states)
    attrs = out["weather.home"]["attributes"]
    attrs.update(
        temperature_unit="°F", wind_speed_unit="mph", precipitation_unit="in"
    )
    for entry in attrs["forecast"] + attrs["forecast_hourly"]:
        for key in ("temperature", "templow"):
            if entry.get(key) is not None:
                entry[key] = entry[key] * 9 / 5 + 32
        for key in ("wind_speed", "wind_gust_speed"):
            if entry.get(key) is not None:
                entry[key] = entry[key] / 1.609344
    return out


class TestWeatherWallStates:
    """Morning, evening and night layouts."""

    def test_morning_headline_is_todays_maximum(self) -> None:
        ctx = _ctx(_at(11, 12, 8))
        assert ctx["state"] == "morning"
        assert ctx["headline"]["text"] == "10°"
        assert ctx["line2_text"] == "5° overnight"
        assert ctx["header_left"] == ""

    def test_evening_with_sun_up_shows_sunset_and_sunrise(self) -> None:
        now = _at(7, 2, 19)
        ctx = _ctx(now, _states(now, sun_up=True))
        assert ctx["state"] == "evening"
        assert ctx["line2_kind"] == "solar"
        assert ctx["line2_text"] == "16:18 – 07:12"

    def test_evening_after_sunset_is_night(self) -> None:
        ctx = _ctx(_at(11, 12, 20))
        assert ctx["state"] == "night"
        assert ctx["is_night"] is True
        assert ctx["headline"]["text"] == "5°"
        assert ctx["header_left"] == "Tomorrow"
        assert ctx["header_max"] == "max 8°"

    def test_force_state_overrides_the_clock(self) -> None:
        ctx = _ctx(_at(11, 12, 8), widget=_widget(force_state="night"))
        assert ctx["state"] == "night"

    def test_day_strip_starts_after_the_day_on_the_top_right(self) -> None:
        morning = _ctx(_at(11, 12, 8))
        night = _ctx(_at(11, 12, 20))
        assert morning["days"][0]["label"] != night["days"][0]["label"]
        assert len(night["days"]) == len(morning["days"]) - 1

    def test_hour_strip_marks_hours_after_sunset_dark(self) -> None:
        ctx = _ctx(_at(11, 12, 8))
        dark = [h["dark"] for h in ctx["hours"]]
        assert True in dark
        assert False in dark


class TestWeatherWallFrost:
    """Frost warnings derived from the overnight hours."""

    def test_severe_frost(self) -> None:
        now = _at(1, 20, 19)
        ctx = _ctx(now, _states(now, hourly=(1, -1, -2, -3, -4)))
        assert ctx["line2_kind"] == "warn"
        assert ctx["line2_text"] == "Severe frost"

    def test_air_frost(self) -> None:
        now = _at(1, 20, 19)
        ctx = _ctx(now, _states(now, hourly=(2, 1, 0, -1, -2)))
        assert ctx["line2_text"] == "Frost"

    def test_no_warning_on_a_mild_night(self) -> None:
        ctx = _ctx(_at(11, 12, 20))
        assert ctx["line2_kind"] == ""


class TestWeatherWallMissingData:
    """Missing entities and forecasts."""

    def test_missing_entity_keeps_the_last_image(self) -> None:
        with pytest.raises(RenderNotReady):
            _ctx(_at(11, 12, 8), widget=_widget(entity="weather.absent"))

    def test_missing_daily_forecast_keeps_the_last_image(self) -> None:
        now = _at(11, 12, 8)
        states = _states(now)
        states["weather.home"]["attributes"]["forecast"] = []
        with pytest.raises(RenderNotReady):
            _ctx(now, states)

    def test_missing_hourly_forecast_shows_a_note(self) -> None:
        now = _at(11, 12, 8)
        states = _states(now)
        states["weather.home"]["attributes"]["forecast_hourly"] = []
        ctx = _ctx(now, states)
        assert ctx["hours"] == []
        assert ctx["hours_note"] == "No hourly forecast"
        assert ctx["days"]

    def test_hourly_forecast_present_has_no_note(self) -> None:
        assert _ctx(_at(11, 12, 8))["hours_note"] == ""


class TestWeatherWallClimatology:
    """Notes on unusual days, from the climatology table."""

    _BAND: ClassVar[dict[str, Any]] = {
        "tmin": {"p10": -3, "p90": 6},
        "gust": {"p90": 50},
        "uv": {"p90": 4},
    }

    def _table(self, path: Path) -> Path:
        days = {
            f"{m:02d}-{d:02d}": self._BAND
            for m in range(1, 13)
            for d in range(1, 32)
        }
        path.write_text(json.dumps({"meta": {}, "days": days}))
        return path

    def test_mild_night_noted_from_the_table(self, tmp_path: Path) -> None:
        table = self._table(tmp_path / "climatology.json")
        ctx = _ctx(_at(11, 12, 8), widget=_widget(climatology_file=str(table)))
        remarks = [d["remark"] for d in ctx["days"]]
        assert "mild 7°" in remarks

    def test_without_a_table_only_cold_nights_are_noted(self) -> None:
        remarks = [d["remark"] for d in _ctx(_at(11, 12, 8))["days"]]
        assert "mild 7°" not in remarks
        assert "min 0°" in remarks

    def test_missing_file_does_not_stop_the_panel(
        self, tmp_path: Path
    ) -> None:
        widget = _widget(climatology_file=str(tmp_path / "absent.json"))
        ctx = _ctx(_at(11, 12, 8), widget=widget)
        assert ctx["days"]

    def test_corrupt_file_does_not_stop_the_panel(
        self, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        ctx = _ctx(_at(11, 12, 8), widget=_widget(climatology_file=str(bad)))
        assert ctx["days"]

    def test_a_directory_is_ignored(self) -> None:
        assert weather_wall._climatology("/") == {}


class TestWeatherWallUnits:
    """Forecasts in units other than metric."""

    def test_fahrenheit_figures_are_converted_back(self) -> None:
        now = _at(11, 12, 8)
        ctx = _ctx(now, _fahrenheit(_states(now)))
        assert ctx["headline"]["text"] == "50°"
        assert ctx["line2_text"] == "41° overnight"
        assert ctx["wind_text"] == "NE 9 mph"

    def test_fahrenheit_decisions_match_celsius(self) -> None:
        # The same weather in either unit system must trigger the same
        # warnings, icons and notes.
        now = _at(1, 20, 19)
        metric = _states(now, hourly=(1, -1, -2, -3, -4))
        a = _ctx(now, metric)
        b = _ctx(now, _fahrenheit(metric))
        assert a["line2_text"] == b["line2_text"] == "Severe frost"
        assert [h["icon"] for h in a["hours"]] == [
            h["icon"] for h in b["hours"]
        ]
        assert a["hero_icon"] == b["hero_icon"]

    def test_celsius_sensor_on_fahrenheit_entity(self) -> None:
        now = _at(11, 12, 8)
        states = _fahrenheit(_states(now))
        states["sensor.outside"] = {
            "state": "13.4",
            "attributes": {"unit_of_measurement": "°C"},
        }
        ctx = _ctx(
            now, states, widget=_widget(temperature_entity="sensor.outside")
        )
        assert ctx["headline"]["text"] == "56°"

    def test_metric_entries_pass_through_untouched(self) -> None:
        units = weather_wall._Units({"temperature_unit": "°C"})
        entry = {"temperature": 10}
        assert units.metric(entry) is entry


class TestWeatherWallFonts:
    """Font family override and weight-only font roles."""

    def test_default_weights(self) -> None:
        ctx = _ctx(_at(11, 12, 8))
        assert ctx["fw_headline"] == "500"
        assert ctx["fw_temperature"] == "500"
        assert ctx["fw_uv"] == "500"
        assert ctx["fw_text"] == "400"

    def test_role_weight_applies_and_size_is_ignored(self) -> None:
        widget = _widget(fonts={"headline": {"weight": "bold", "size": 200}})
        ctx = _ctx(_at(11, 12, 8), widget=widget)
        assert ctx["fw_headline"] == "bold"
        assert ctx["font_xl"] == weather_wall.FONT_XL

    def test_font_family_override(self) -> None:
        ctx = _ctx(_at(11, 12, 8), widget=_widget(font_family="Example"))
        assert ctx["font_override"] is True
        assert ctx["ff_xl"] == "Example, Roboto"
        assert ctx["font_xl"] == weather_wall.FONT_XL


class TestWeatherWallLanguage:
    """Panel text through Babel and the phrase table."""

    def test_polish(self) -> None:
        ctx = _ctx(_at(11, 12, 20), language="pl")
        assert ctx["date_text"] == "czwartek 12 listopada"
        assert ctx["header_left"] == "Jutro"

    def test_unknown_language_falls_back_to_english(self) -> None:
        ctx = _ctx(_at(11, 12, 20), language="xx")
        assert ctx["header_left"] == "Tomorrow"


class TestWeatherWallRender:
    """End-to-end SVG rendering."""

    def test_renders_a_full_panel(self) -> None:
        now = _at(11, 12, 8)
        with patch(_NOW, return_value=now):
            svg = render_widget_svg(_widget(), _config(_states(now)))
        assert svg.startswith("<svg")
        assert 'viewBox="0 0 800 480"' in svg
        texts = _texts(svg)
        assert "Thursday 12 November" in texts
        assert "5° overnight" in texts

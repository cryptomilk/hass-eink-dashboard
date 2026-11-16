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

"""Weather wall widget context builder.

A full-panel weather layout for a wall-mounted e-ink display.
Unlike the stock weather widget this one owns the entire canvas: it
paints its own ground, selects one of three layouts by time of day,
and reads both the daily and the hourly forecast.

The layout is drawn in an 800 x 480 design space, so the numbers
here and the numbers in the design drawings are the same numbers.
The template's viewBox scales it to the widget's actual size,
keeping its proportions; a 5:3 widget fills exactly.

Three layouts:

* **morning** -- today's maximum as the headline, the next hours on
  the right, the following days below.
* **evening** -- from 17:00 while the sun is up: tonight's minimum
  as the headline with the times of sunset and sunrise, tomorrow's
  hours on the right, the days from the day after tomorrow below.
* **night** -- as evening once the sun has set, with the tonight
  block on a dark ground, the moon and any cloud as its icon, and a
  frost warning when the hours ahead call for one.

Colours come from a palette matched to the display's colour scheme;
text follows the dashboard's font unless the widget names one.
Forecasts in other units are converted to metric for the widget's
thresholds and printed in their own units.

Icons are named here and drawn in the template.  The integration's
``_build_inline_svg()`` flattens every path to a single colour, which
would lose the yellow sun and the black rain-bearing cloud, so this
widget does not use the shared icon loader.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import RenderNotReady
from ._helpers import _color_context, _widget_dim

if TYPE_CHECKING:
    from ..const import DisplayConfig
    from ..widget_config import WeatherWallWidget

_LOGGER = logging.getLogger(__name__)

# Climatological percentile thresholds, keyed by "MM-DD", built by
# scripts/build_climatology.py (see docs/climatology.md).  The file
# belongs outside the component directory, at the path given by the
# widget's climatology_file option, because an update replaces that
# directory wholesale and would delete it.  Without the option the
# component directory is still tried, for installations that put it
# there before the option existed.
_LEGACY_CLIMATOLOGY_PATH = Path(__file__).parent.parent / "climatology.json"

# Path -> (modification time, table).  The file is read on first use
# and again only when it changes.  Rendering runs in an executor
# thread, so the read does not block the event loop.
_CLIMATOLOGY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CLIMATOLOGY_WARNED: set[str] = set()


def _climatology(option: object) -> dict[str, Any]:
    """Return the climatology table for a widget, or ``{}``.

    A missing or unreadable table only suppresses the remarks under
    each day; it never stops the panel rendering.

    Args:
        option: The widget's ``climatology_file``: an absolute path,
            or empty to try the component directory.

    Returns:
        Percentile bands keyed by ``"MM-DD"``.
    """
    path = Path(str(option)) if option else _LEGACY_CLIMATOLOGY_PATH
    key = str(path)
    if path.is_dir():
        # A path still being typed in the editor, whose live preview
        # renders after each change; "/" and "/config" are not worth
        # a warning.
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        # Only a file someone asked for is worth a warning; without
        # the option, having no table is the normal state.
        if option and key not in _CLIMATOLOGY_WARNED:
            _CLIMATOLOGY_WARNED.add(key)
            _LOGGER.warning(
                "weather_wall: climatology file %s not found (%s); "
                "the remarks under each day will be suppressed",
                key,
                exc,
            )
        return {}
    cached = _CLIMATOLOGY_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        days = json.loads(path.read_text()).get("days", {})
        table = days if isinstance(days, dict) else {}
    except (OSError, ValueError, AttributeError) as exc:
        _LOGGER.warning(
            "weather_wall: could not read climatology file %s (%s)",
            key,
            exc,
        )
        table = {}
    _CLIMATOLOGY_CACHE[key] = (mtime, table)
    return table


# ---------------------------------------------------------------
# Layout constants.  All values are 800 x 480 panel pixels.
# ---------------------------------------------------------------

MARGIN = 28

# The design field.  All geometry below is expressed in this
# space rather than in panel pixels, and the template's viewBox
# maps it onto the real display.
DESIGN_W = 800
DESIGN_H = 480

# Retained under the old names so the existing geometry reads
# unchanged; they are the same numbers.
CANVAS_W = DESIGN_W
CANVAS_H = DESIGN_H

# Type scale, four sizes on a root-two progression.
FONT_XL = 80  # headline temperature
FONT_L = 40  # ultraviolet figure
FONT_M = 28  # any temperature sitting in a column
FONT_S = 20  # everything else

# Reduced-width minus sign, and the gap after it.  A full-width
# minus makes negative values collide with their neighbours; 0.7 is
# the conventional proportion for a tabular sign.
MINUS_SCALE = 0.7
MINUS_DX = 0.10  # as a fraction of the font size

# The degree sign's advance, in ems, per typeface.  Column figures
# are centred with text-anchor="middle", which centres the whole
# string; the eye centres on the digits, so the figure is shifted
# right by half the degree sign to hang it outside the measure.
#
# The integration's own families (Roboto, TRMNL, Inter) are measured
# from their font files, so they need no entry here.  These tables
# serve only a per-widget font_family override, whose face the
# integration cannot measure.  Values are set by eye: raise one if
# that face's figures still sit left of their column, lower it if
# they drift right.
_DEGREE_EM = {
    "Roboto": 0.36,
    "Drogowskaz": 0.42,
}
_DEGREE_EM_DEFAULT = 0.38
# The same treatment for the per cent sign under each day, so the
# digits of the percentage share a centre line with the digits of
# the temperature above.  Wider than the degree in every face, so
# it has its own table.
_PERCENT_EM = {
    "Roboto": 0.76,
    "Drogowskaz": 0.70,
}
_PERCENT_EM_DEFAULT = 0.0

# Palettes, keyed as the integration's color_scheme reports them.
#
# Every glyph is drawn from three names: c_fg for the main strokes
# and fills, c_dark for the interior of a rain-bearing cloud, and
# c_sun for the sun and the storm bolt.  On the six-colour panel
# that gives white icons on blue; on a light ground, setting c_fg
# and c_dark both to black inverts the set without redrawing it,
# at the cost of light and dark clouds looking the same.
#
# c_night fills the night block and the post-sunset tiles.  On a
# light ground it matches the ground, so both simply vanish: night
# is then carried by the moon and stars.
#
# c_warn_stroke draws an outline round the warning badge; "none"
# where the badge is a filled block.
_LIGHT = {
    "c_bg": "#FFFFFF",
    "c_fg": "#000000",
    "c_dark": "#000000",
    "c_night": "#FFFFFF",
}

_PALETTES = {
    "bwgbry": {
        "c_bg": "#0000FF",
        "c_fg": "#FFFFFF",
        "c_dark": "#000000",
        "c_night": "#000000",
        "c_sun": "#FFFF00",
        "c_warn": "#FF0000",
        "c_warn_fg": "#FFFFFF",
        "c_warn_stroke": "none",
    },
    "bwry": {
        **_LIGHT,
        "c_sun": "#FFFF00",
        "c_warn": "#FF0000",
        "c_warn_fg": "#FFFFFF",
        "c_warn_stroke": "none",
    },
    "bwr": {
        **_LIGHT,
        "c_sun": "#000000",
        "c_warn": "#FF0000",
        "c_warn_fg": "#FFFFFF",
        "c_warn_stroke": "none",
    },
    "bwy": {
        **_LIGHT,
        "c_sun": "#FFFF00",
        "c_warn": "#FFFF00",
        "c_warn_fg": "#000000",
        "c_warn_stroke": "none",
    },
    # Greyscale is a compatibility mode: black on white throughout,
    # and an outlined badge, since a filled one would be a block of
    # dithered grey.
    "grey": {
        **_LIGHT,
        "c_sun": "#000000",
        "c_warn": "none",
        "c_warn_fg": "#000000",
        "c_warn_stroke": "#000000",
    },
}

# Greyscale panels report no color_scheme.
_PALETTE_GREY = "grey"


def _palette(
    widget: WeatherWallWidget, config: DisplayConfig
) -> dict[str, str]:
    """Choose the palette for this render.

    The widget's own ``palette`` option wins when set, which is how
    a panel you do not own can be previewed; otherwise the display's
    configured colour scheme decides, and anything unrecognised is
    treated as greyscale.
    """
    chosen = str(widget.get("palette") or "auto")
    if chosen == "auto":
        chosen = str(config.get("color_scheme") or _PALETTE_GREY)
    return dict(_PALETTES.get(chosen, _PALETTES[_PALETTE_GREY]))


# Curated panel vocabulary, in the manner of render.py's
# _RELATIVE_DAY_PHRASES.  The same rule applies: only languages
# where each phrase is an invariant substitution.  None of these
# phrases makes a word agree with a number, so languages with
# complex plural or case rules, Polish among them, are safe here.
# Anything missing falls back to English key by key, so a partial
# entry can never leave a blank on the panel.  Dates and weekday
# names are not here: they come from Babel.
_WALL_PHRASES: dict[str, dict[str, Any]] = {
    "en": {
        "tomorrow": "Tomorrow",
        "overnight": "{t} overnight",
        "max": "max {t}",
        "min": "min {t}",
        "mild": "mild {t}",
        "cold": "cold {t}",
        "gust": "gust {v}",
        "uv": "UV",
        "uv_value": "UV {v}",
        "no_hourly": "No hourly forecast",
        "chance": {
            "rain": "Chance of rain",
            "snow": "Chance of snow",
            "sleet": "Chance of sleet",
        },
        "warnings": {
            "icy": "Icy",
            "severe_frost": "Severe frost",
            "frost": "Frost",
            "ground_frost": "Ground frost",
        },
    },
    "pl": {
        "tomorrow": "Jutro",
        "overnight": "{t} w nocy",
        "max": "maks. {t}",
        "min": "min. {t}",
        "mild": "ciepło {t}",
        "cold": "zimno {t}",
        "gust": "porywy {v}",
        "no_hourly": "Brak prognozy godzinowej",
        "chance": {
            "rain": "Szansa na deszcz",
            "snow": "Szansa na śnieg",
            "sleet": "Szansa na deszcz ze śniegiem",
        },
        "warnings": {
            "icy": "Gołoledź",
            "severe_frost": "Silny mróz",
            "frost": "Mróz",
            "ground_frost": "Przymrozek",
        },
    },
}


def _phrases(language: str) -> dict[str, Any]:
    """Return the panel vocabulary for a language, English as base.

    Args:
        language: BCP 47 language code.  Only the primary subtag is
            used, as in _relative_day_phrases().
    """
    lang = language.split("-")[0].lower()
    merged: dict[str, Any] = {
        k: dict(v) if isinstance(v, dict) else v
        for k, v in _WALL_PHRASES["en"].items()
    }
    for key, value in _WALL_PHRASES.get(lang, {}).items():
        if isinstance(value, dict):
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


# Left block: the headline.
LEFT_X = MARGIN
LEFT_RIGHT = 320
HERO_CX = 72
HERO_CY = 126
HERO_SCALE = 3.51  # icons are drawn in a 24-unit box
TEMP_X = 128
Y_DATE = 44
Y_UV_LABEL = 110
UV_BADGE_W = 56
UV_BADGE_H = 80
Y_UV_BADGE = 88
Y_HEADLINE = 154  # shared by the headline and the UV figure
Y_LINE2 = 190  # shared with the hourly temperatures
Y_METRICS = 264  # shared with the rain caption
LINE2_ICON_X = 142
LINE2_TEXT_X = 164
WIND_ICON_X = 40
WIND_TEXT_X = 64
SOLAR_ICON_X = 242

# Right block: the two-hourly strip.
RIGHT_X = 370
RIGHT_RIGHT = 772
HOUR_SLOTS = 7
HOUR_W = (RIGHT_RIGHT - RIGHT_X) / HOUR_SLOTS
Y_HOUR_LABEL = 92
HOUR_ICON_CY = 130
# A provider without an hourly forecast leaves the strip empty; a
# note sits at the height of its icons instead, so the space does
# not read as a fault.
Y_NO_HOURLY = HOUR_ICON_CY + 7
# A black tile behind any hourly icon falling after sunset, so the
# stars and clouds sit against night rather than against the day
# ground.  Offset left of the column centre because the icons are
# not centred on their own origin: a cloud spans -11 to +14 units,
# so its mass sits slightly right and a centred tile would clip the
# dark cloud's rim.  Two pixels deeper than wide, since the icons
# hang below their centre rather than straddling it.
NIGHT_TILE_W = 50
NIGHT_TILE_H = 87
NIGHT_TILE_DX = -22
NIGHT_TILE_DY = -60
NIGHT_TILE_R = 6
HOUR_SCALE = 1.58
Y_HOUR_TEMP = Y_LINE2
BAND_BOTTOM = 242
BAND_H = 46
Y_CAPTION = Y_METRICS

# The rule, and the day strip below it.
Y_RULE = 284
DAY_COLS = 7
DAY_GUTTER = 12
Y_DAY_LABEL = 316
DAY_ICON_CY = 348
DAY_SCALE = 1.89
Y_DAY_TEMP = 400
Y_DAY_PROB = 426
Y_DAY_REMARK = 450

# Night block.
NIGHT_W = RIGHT_X - MARGIN
NIGHT_H = Y_RULE

# ---------------------------------------------------------------
# Behaviour constants.
# ---------------------------------------------------------------

# Local hour at which the layout changes.  Hard-coded rather than
# configurable: the board wakes at fixed times and the layout should
# follow the day, not a preference.
EVENING_FROM = 17
NIGHT_FROM = 21

# Hours shown in the evening and night strips.
EVENING_HOURS = (7, 9, 11, 13, 15, 17, 19)

# Ultraviolet index thresholds.
UV_HIDE_BELOW = 4
UV_WARN_ABOVE = 5.5

# Frost and ice derivation, applied to the overnight hourly slice.
FROST_AIR = 0.0  # air frost at or below, degrees Celsius
FROST_SEVERE = -3.0
FROST_GROUND = 4.0  # with clear skies and light wind
FROST_GROUND_CLOUD = 30  # per cent cloud cover
FROST_GROUND_WIND = 10  # km/h
ICE_PRECIP_MM = 0.2  # antecedent rainfall needed to freeze

# Overnight cloud cover deciding what the night hero shows.  Set
# near the okta boundaries: under 30 per cent is a clear sky, 70
# and above is mostly cloudy to overcast.  The figure used is the
# mean across the overnight hours rather than the minimum, since
# one clear hour at four in the morning should not earn a full
# moon.  Cloud cover is reported only in the hourly forecast; the
# daily entry carries none at all, which is why an earlier version
# never suppressed the moon.
MOON_CLEAR_BELOW = 30
MOON_HIDDEN_AT = 70

# Cloud cover at or above which a cloud is drawn black rather than
# white.
CLOUD_IS_DARK = 80

# The moon behind a cloud: its size as a fraction of the clear-night
# hero, and its offset in panel pixels, so the cloud covers its
# lower left and the phase still shows above.
MOON_BEHIND_SCALE = 0.64
MOON_BEHIND_DX = 28
MOON_BEHIND_DY = -36

# Precipitation intensity bands, millimetres per hour, giving one,
# two or three marks.
PRECIP_LIGHT = 0.5
PRECIP_HEAVY = 2.0

# Probability bands used where no amount is forecast.
PROB_LIGHT = 40
PROB_HEAVY = 70

# Lowest precipitation probability worth printing.
PROB_MIN = 15
# The hero icon needs a higher bar than the columns.  A drop under
# the largest glyph on the panel reads as a forecast of rain, so it
# should not appear for a day that is merely not certainly dry.
HERO_PROB_MIN = 25

# The gust is shown only when it clears both of these: a ratio
# above the mean, and an absolute margin.  A ratio alone fails at
# the bottom of the scale, where 2 to 4 km/h is a doubling and
# tells you nothing, while 20 to 40 is a gale.  Both tests have to
# pass, so a light day shows one figure and a blustery one shows
# the range.
GUST_RATIO = 1.9
GUST_MARGIN = 9.0

# A minimum at or below this is noted whatever the climatology
# says.  Four degrees is entirely ordinary in January and still
# means scraping the car, so the percentile test is the wrong
# instrument for it.
COLD_NOTE_AT = 4.0

# A day's measure is remarked on when it falls outside these
# percentiles for the calendar date.  Any value stored by
# build_climatology.py may be used: 1, 2, 5, 10, 20, 30, 40, 50,
# 60, 70, 80, 90, 95, 98, 99.  Raise p90 toward p98 to quieten the
# line; lower it toward p80 to make it chattier.
REMARK_HIGH = "p90"
REMARK_LOW = "p10"

# Absolute floors, applied as well as the percentile.  Without them
# a December ultraviolet index of 1.2 counts as high for December,
# which is true and useless.
REMARK_UV_MIN = 5.0
REMARK_GUST_MIN = 45.0

_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# HA moon phase states to the key used by the template.
_MOON_PHASES = {
    "new_moon": "new",
    "waxing_crescent": "wax_crescent",
    "first_quarter": "first_quarter",
    "waxing_gibbous": "wax_gibbous",
    "full_moon": "full",
    "waning_gibbous": "wane_gibbous",
    "last_quarter": "last_quarter",
    "waning_crescent": "wane_crescent",
}


def _num(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when not numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Conversions into the units the thresholds above are written in:
# degrees Celsius, kilometres per hour and millimetres.  Each entry
# is (factor, offset) such that metric = value * factor + offset.
_TO_CELSIUS: dict[str, tuple[float, float]] = {
    "°C": (1.0, 0.0),
    "°F": (5 / 9, -32 * 5 / 9),
    "K": (1.0, -273.15),
}
_TO_KMH: dict[str, tuple[float, float]] = {
    "km/h": (1.0, 0.0),
    "m/s": (3.6, 0.0),
    "mph": (1.609344, 0.0),
    "kn": (1.852, 0.0),
    "ft/s": (1.09728, 0.0),
}
_TO_MM: dict[str, tuple[float, float]] = {
    "mm": (1.0, 0.0),
    "cm": (10.0, 0.0),
    "in": (25.4, 0.0),
}
_IDENTITY = (1.0, 0.0)


def _rate(
    table: dict[str, tuple[float, float]], unit: str, what: str
) -> tuple[float, float]:
    """Return the conversion for ``unit``, or identity if unknown."""
    rate = table.get(unit)
    if rate is None:
        _LOGGER.debug(
            "weather_wall: unknown %s unit %r, treated as metric", what, unit
        )
        return _IDENTITY
    return rate


class _Units:
    """Convert a weather entity's units to metric and back.

    Every threshold in this module, and the climatology table, is in
    degrees Celsius, kilometres per hour and millimetres.  Rather
    than restate each threshold per unit system, forecast entries are
    converted to metric once on arrival, and figures are converted
    back to the entity's own units only where they are printed.  For
    a metric entity both directions are the identity, and entries are
    passed through untouched.
    """

    def __init__(self, attrs: dict[str, Any]) -> None:
        """Read the units from the weather entity's attributes."""
        self.speed_unit = str(attrs.get("wind_speed_unit") or "km/h")
        self._temp = _rate(
            _TO_CELSIUS,
            str(attrs.get("temperature_unit") or "°C"),
            "temperature",
        )
        self._speed = _rate(_TO_KMH, self.speed_unit, "wind speed")
        self._precip = _rate(
            _TO_MM,
            str(attrs.get("precipitation_unit") or "mm"),
            "precipitation",
        )
        self.metric_already = (
            self._temp == self._speed == self._precip == _IDENTITY
        )

    @staticmethod
    def _apply(value: Any, rate: tuple[float, float]) -> Any:
        """Return ``value`` converted by ``rate``, or as it was."""
        n = _num(value)
        if n is None or rate == _IDENTITY:
            return value
        return n * rate[0] + rate[1]

    @staticmethod
    def _invert(value: Any, rate: tuple[float, float]) -> Any:
        """Return a metric ``value`` in the entity's own unit."""
        n = _num(value)
        if n is None or rate == _IDENTITY:
            return value
        # Rounded so that a round trip cannot turn the 49.5 a
        # provider sent into 49.4999999 and round it the other way.
        return round((n - rate[1]) / rate[0], 6)

    def metric(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Return a forecast entry with its values in metric units."""
        if self.metric_already:
            return entry
        out = dict(entry)
        for key, rate in (
            ("temperature", self._temp),
            ("templow", self._temp),
            ("wind_speed", self._speed),
            ("wind_gust_speed", self._speed),
            ("precipitation", self._precip),
        ):
            if key in out:
                out[key] = self._apply(out[key], rate)
        return out

    def temp(self, celsius: Any) -> Any:
        """Return a Celsius temperature in the entity's unit."""
        return self._invert(celsius, self._temp)

    def speed(self, kmh: Any) -> Any:
        """Return a km/h speed in the entity's unit."""
        return self._invert(kmh, self._speed)

    def sensor_temp(self, value: Any, unit: Any) -> Any:
        """Return a sensor's reading in the weather entity's unit.

        A sensor in the same unit as the weather entity, or one with
        no recognised unit, is shown as it reads.
        """
        rate = _TO_CELSIUS.get(str(unit or ""))
        if rate is None or rate == self._temp:
            return value
        return self.temp(self._apply(value, rate))


def _temp(value: Any) -> dict[str, object]:
    """Format a temperature for display as whole degrees.

    Returns a dict rather than a string so the template can set the
    minus sign at a reduced size; a full-width minus would push
    negative values into their neighbouring columns.

    Args:
        value: Temperature in the entity's own unit, or ``None``.

    Returns:
        ``{"show": bool, "neg": bool, "text": str}`` where ``text``
        carries the digits and degree sign without any sign.
    """
    n = _num(value)
    if n is None:
        return {"show": False, "neg": False, "text": ""}
    r = round(n)
    return {"show": True, "neg": r < 0, "text": f"{abs(r)}\u00b0"}


def _signed(t: dict[str, object]) -> str:
    """Return a formatted temperature as a plain string with sign."""
    if not t["show"]:
        return ""
    return f"{'\u2212' if t['neg'] else ''}{t['text']}"


def _compass(bearing: Any) -> str:
    """Return an eight-point compass abbreviation for a bearing."""
    n = _num(bearing)
    if n is None:
        return ""
    return _COMPASS[int((n % 360) / 45.0 + 0.5) % 8]


def _local(hass_dt: Any, raw: str | None):
    """Parse an ISO timestamp into local time, or return ``None``."""
    if not raw:
        return None
    parsed = hass_dt.parse_datetime(raw)
    return hass_dt.as_local(parsed) if parsed else None


def _drop_count(entry: dict[str, Any], prob_min: float = PROB_MIN) -> int:
    """Return 0-3 precipitation marks for a forecast entry.

    Prefers a forecast amount where the provider gives one and falls
    back to probability otherwise.  The Met Office daily forecast
    reports ``precipitation`` as ``None`` on every day and carries
    the information in ``precipitation_probability``.
    """
    amount = _num(entry.get("precipitation"))
    if amount is not None and amount > 0:
        if amount >= PRECIP_HEAVY:
            return 3
        if amount >= PRECIP_LIGHT:
            return 2
        return 1
    prob = _num(entry.get("precipitation_probability"))
    if prob is None or prob < prob_min:
        return 0
    if prob >= PROB_HEAVY:
        return 3
    if prob >= PROB_LIGHT:
        return 2
    return 1


def _is_dark_cloud(entry: dict[str, Any]) -> bool:
    """True when the cloud in this entry should be drawn black.

    Home Assistant's condition strings distinguish only cloudy from
    partlycloudy, which is not enough, so darkness is derived from
    cloud cover with precipitation as a secondary trigger: a shower
    cloud is dark regardless of how much sky it covers.
    """
    if _drop_count(entry) >= 2:
        return True
    cover = _num(entry.get("cloud_coverage"))
    return cover is not None and cover >= CLOUD_IS_DARK


def _icon_name(
    entry: dict[str, Any],
    night: bool = False,
    prob_min: float = PROB_MIN,
) -> str:
    """Return the icon key for a forecast entry.

    Args:
        entry: A forecast entry.
        night: True to prefer the night variant of clear or partly
            clear skies.  The day strip always passes False, since
            those columns describe daytime whatever the hour.
        prob_min: Lowest precipitation probability that earns a
            drop.  The hero passes a higher value than the columns.

    Returns:
        A key matching a ``<g id="wx-...">`` in the template.
    """
    cond = str(entry.get("condition", ""))
    drops = _drop_count(entry, prob_min)

    if cond in ("lightning", "lightning-rainy"):
        return "wx-storm"
    if cond == "fog":
        return "wx-fog"
    if cond in ("snowy", "snowy-rainy", "hail"):
        return f"wx-snow{drops}" if drops else "wx-cloud-dark"
    if drops:
        return f"wx-rain{drops}"
    if cond in ("rainy", "pouring"):
        return "wx-cloud-dark"
    if cond == "cloudy":
        return "wx-cloud-dark" if _is_dark_cloud(entry) else "wx-cloud"
    if cond == "partlycloudy":
        return "wx-moon-cloud" if night else "wx-sun-cloud"
    if cond in ("windy", "windy-variant"):
        return "wx-cloud"
    # Clear sky.  The provider's condition says what the sky is
    # doing; whether it is dark is a separate question, answered by
    # our own sunrise and sunset test rather than by the string.
    # The two disagree at the edges: the Met Office labels an hour
    # by its start, so 07:00 reads clear-night when sunrise is at
    # 07:04, while the hour itself is light for fifty-six of its
    # sixty minutes.  Taking darkness from one source keeps the icon
    # and its background tile in step.
    #
    # Stars rather than a moon, because the phase is drawn properly
    # on the hero where there is room for it, and a fixed gibbous in
    # a 42 px column would be wrong most nights.
    return "wx-stars" if night else "wx-sun"


def _precip_word(entries: list[dict[str, Any]]) -> str:
    """Return rain, snow or sleet for the caption under the strip.

    Chosen by the predominant condition across the hours shown, not
    by any single hour, so one snowy hour at the far end of the day
    does not relabel the whole strip.
    """
    snow = sleet = 0
    for e in entries:
        cond = str(e.get("condition", ""))
        if cond == "snowy":
            snow += 1
        elif cond in ("snowy-rainy", "hail"):
            sleet += 1
    if snow > sleet and snow:
        return "snow"
    if sleet:
        return "sleet"
    return "rain"


def _overnight_slice(
    hourly: list[dict[str, Any]],
    hass_dt: Any,
    now: Any,
) -> list[dict[str, Any]]:
    """Return the hourly entries covering tonight, 22:00 to 08:00."""
    out: list[dict[str, Any]] = []
    for e in hourly:
        when = _local(hass_dt, e.get("datetime"))
        if when is None or when < now:
            continue
        if when.hour >= 22 or when.hour <= 8:
            out.append(e)
        if len(out) >= 12:
            break
    return out


def _overnight_summary(
    overnight: list[dict[str, Any]],
) -> tuple[float | None, dict[str, Any]]:
    """Summarise the night ahead for the hero icon.

    Args:
        overnight: Hourly entries covering tonight.

    Returns:
        ``(cover, worst)`` where ``cover`` is the mean cloud cover
        across the hours, or ``None`` when none is reported, and
        ``worst`` is the hour carrying the most precipitation, which
        is the one the icon should describe.
    """
    if not overnight:
        return None, {}
    covers = [
        c
        for e in overnight
        if (c := _num(e.get("cloud_coverage"))) is not None
    ]
    cover = sum(covers) / len(covers) if covers else None
    worst = max(overnight, key=lambda e: _drop_count(e, HERO_PROB_MIN))
    return cover, worst


def _frost_warning(
    overnight: list[dict[str, Any]],
    preceding: list[dict[str, Any]],
) -> str:
    """Derive a frost or ice warning key, or an empty string.

    Returns a key into the phrase table rather than text, so the
    wording follows the panel's language.  The Met Office
    integration exposes no warnings, and a National Severe Weather
    Warning would be the wrong instrument anyway: it is issued
    regionally at an impact threshold, whereas a kitchen panel
    should answer whether the car will need scraping.

    Returns:
        One of ``"icy"``, ``"severe_frost"``, ``"frost"``,
        ``"ground_frost"`` or ``""``.
    """
    temps = [
        t for e in overnight if (t := _num(e.get("temperature"))) is not None
    ]
    if not temps:
        return ""
    low = min(temps)

    wet = (
        sum(_num(e.get("precipitation")) or 0.0 for e in preceding)
        >= ICE_PRECIP_MM
    )

    if low <= FROST_AIR and wet:
        return "icy"
    if low <= FROST_SEVERE:
        return "severe_frost"
    if low <= FROST_AIR:
        return "frost"

    if low <= FROST_GROUND:
        clouds = [
            c
            for e in overnight
            if (c := _num(e.get("cloud_coverage"))) is not None
        ]
        winds = [
            w
            for e in overnight
            if (w := _num(e.get("wind_speed"))) is not None
        ]
        clear = not clouds or min(clouds) < FROST_GROUND_CLOUD
        calm = not winds or max(winds) < FROST_GROUND_WIND
        if clear and calm:
            return "ground_frost"
    return ""


def _remarkable(
    day: dict[str, Any],
    when: Any,
    s: dict,
    climate: dict[str, Any],
    units: _Units,
) -> str:
    """Return a short note when one measure is unusual, else "".

    Each candidate is compared against a percentile for the calendar
    date from the climatology table.  Whichever measure exceeds its
    threshold by the largest relative margin wins.  Failing that, a
    cold night is noted anyway, since four degrees is ordinary in
    January and still means scraping the car.

    Args:
        day: One daily forecast entry.
        when: The entry's local date and time, or None.
        s: The panel phrases for the display language.
        climate: The climatology table, possibly empty.
        units: Converts the figures shown back to the entity's units.
    """
    low = _num(day.get("templow"))
    candidates: list[tuple[float, str]] = []

    bands = None
    if when is not None and climate:
        bands = climate.get(f"{when.month:02d}-{when.day:02d}")

    if bands:

        def over(measure: str, value: float | None, floor: float):
            """Relative margin above the upper percentile, or None."""
            limit = bands.get(measure, {}).get(REMARK_HIGH)
            if value is None or limit is None or value < floor:
                return None
            if limit <= 0 or value <= limit:
                return None
            return (value - limit) / limit

        uv = _num(day.get("uv_index"))
        margin = over("uv", uv, REMARK_UV_MIN)
        if margin is not None and uv is not None:
            candidates.append((margin, s["uv_value"].format(v=round(uv))))

        gust = _num(day.get("wind_gust_speed"))
        margin = over("gust", gust, REMARK_GUST_MIN)
        if margin is not None and gust is not None:
            shown = round(_num(units.speed(gust)) or 0)
            candidates.append((margin, s["gust"].format(v=shown)))

        # Two-tailed, measured against the width of the band rather
        # than the value, since a minimum near zero would otherwise
        # give an enormous margin.
        band = bands.get("tmin", {})
        cold = band.get(REMARK_LOW)
        warm = band.get(REMARK_HIGH)
        if low is not None and cold is not None and warm is not None:
            width = max(1.0, warm - cold)
            t = _signed(_temp(units.temp(low)))
            if low < cold:
                candidates.append(
                    ((cold - low) / width, s["cold"].format(t=t))
                )
            elif low > warm:
                candidates.append(
                    ((low - warm) / width, s["mild"].format(t=t))
                )

    if candidates:
        return max(candidates, key=lambda c: c[0])[1]
    if low is not None and low <= COLD_NOTE_AT:
        return s["min"].format(t=_signed(_temp(units.temp(low))))
    return ""


def _rain_path(entries: list[dict[str, Any]]) -> tuple[str, float]:
    """Build the stepped rain-probability profile.

    A continuous profile reads as the shape of the day, which is the
    question actually being asked, and the fifty per cent rule gives
    the eye a reference so the shape is not merely decorative.

    Returns:
        ``(path_d, mid_y)`` where ``mid_y`` is the fifty per cent
        rule's vertical position.  ``path_d`` is empty when there is
        nothing to draw.
    """
    if not entries:
        return "", BAND_BOTTOM - BAND_H / 2
    parts = [f"M {RIGHT_X} {BAND_BOTTOM}"]
    for i, e in enumerate(entries):
        prob = _num(e.get("precipitation_probability")) or 0.0
        top = BAND_BOTTOM - BAND_H * max(0.0, min(100.0, prob)) / 100.0
        x1 = RIGHT_X + HOUR_W * i
        x2 = RIGHT_X + HOUR_W * (i + 1)
        parts.append(f"L {x1:.1f} {top:.1f} L {x2:.1f} {top:.1f}")
    parts.append(f"L {RIGHT_RIGHT} {BAND_BOTTOM} Z")
    return " ".join(parts), BAND_BOTTOM - BAND_H / 2


def _pick_hours(
    hourly: list[dict[str, Any]],
    hass_dt: Any,
    now: Any,
    state: str,
) -> list[dict[str, Any]]:
    """Choose the seven two-hourly entries for the right-hand strip.

    In the morning this is the next seven even hours from now; in the
    evening and at night it is tomorrow's seven fixed slots, so the
    panel always frames the following day the same way.
    """
    parsed = []
    for e in hourly:
        when = _local(hass_dt, e.get("datetime"))
        if when is not None:
            parsed.append((when, e))
    if not parsed:
        return []

    if state == "morning":
        out = []
        for when, e in parsed:
            if when <= now or when.hour % 2:
                continue
            out.append(dict(e, _label=f"{when.hour:02d}"))
            if len(out) == HOUR_SLOTS:
                break
        return out

    tomorrow = (now + _dt.timedelta(days=1)).date()
    out = []
    for hour in EVENING_HOURS:
        for when, e in parsed:
            if when.date() == tomorrow and when.hour == hour:
                out.append(dict(e, _label=f"{hour:02d}"))
                break
    return out


# Font roles, in the manner of the stock weather widget: weight-only.
# The layout is fixed in the 800 x 480 design space and every
# position is set for these sizes, so a size override could only
# make text collide.  resolve_font's size half is therefore
# discarded, as weather.py does; each role's weight can still be
# changed through the widget's ``fonts`` key.
_FONT_ROLES: tuple[tuple[str, int, str], ...] = (
    # role, design size, default weight
    ("headline", FONT_XL, "medium"),
    ("temperature", FONT_M, "medium"),
    ("uv", FONT_L, "medium"),
    ("text", FONT_S, "regular"),
)


def _role_weights(widget: WeatherWallWidget) -> dict[str, Any]:
    """Return each font role's resolved weight.

    Args:
        widget: Widget config, possibly carrying a ``fonts`` mapping.

    Returns:
        Role name to ``FontWeight``.
    """
    from ..const import FontWeight
    from ..render import resolve_font

    return {
        role: resolve_font(widget, role, size, FontWeight(default))[1]
        for role, size, default in _FONT_ROLES
    }


def _font_context(override: str, weights: dict[str, Any]) -> dict[str, object]:
    """Return the template's font stacks, sizes and figure offsets.

    Must be called inside the render context that
    ``render_widget_svg()`` sets up, because the dashboard's font
    family and pixel-font settings are read from it.

    Args:
        override: The widget's ``font_family``, or an empty string
            to follow the dashboard.
        weights: Each role's resolved weight, from ``_role_weights``.

    Returns:
        ``ff_*`` font-family stacks and ``font_*`` sizes for the four
        sizes of the type scale, ``fw_*`` weights for the four font
        roles, the reduced minus sign's size and gap, the
        half-widths that centre column figures on their digits, and
        ``font_override`` for the template.
    """
    from ..render import _font_weight_svg

    design = {"xl": FONT_XL, "l": FONT_L, "m": FONT_M, "s": FONT_S}

    if override:
        sizes: dict[str, int | float] = dict(design)
        stacks = dict.fromkeys(design, f"{override}, Roboto")
        deg_shift = round(
            FONT_M * _DEGREE_EM.get(override, _DEGREE_EM_DEFAULT) / 2, 1
        )
        pct_shift = round(
            FONT_S * _PERCENT_EM.get(override, _PERCENT_EM_DEFAULT) / 2, 1
        )
    else:
        from ..fonts import current_font_family, font_family, pixel_font_size
        from ..render import _load_role_font

        family = current_font_family()
        sizes = {k: pixel_font_size(v) for k, v in design.items()}
        stacks = {k: font_family(v, family) for k, v in design.items()}
        # Measured in the weights the figures are drawn in: column
        # temperatures in the temperature role, percentages as text.
        deg_shift = round(
            _load_role_font(FONT_M, weights["temperature"]).getlength("\u00b0")
            / 2,
            1,
        )
        pct_shift = round(
            _load_role_font(FONT_S, weights["text"]).getlength("%") / 2, 1
        )

    ctx: dict[str, object] = {
        "font_override": bool(override),
        "deg_shift_m": deg_shift,
        "pct_shift_s": pct_shift,
        "minus_xl": round(sizes["xl"] * MINUS_SCALE),
        "minus_m": round(sizes["m"] * MINUS_SCALE),
        "dx_xl": round(sizes["xl"] * MINUS_DX),
        "dx_m": round(sizes["m"] * MINUS_DX),
    }
    for key in design:
        ctx[f"font_{key}"] = sizes[key]
        ctx[f"ff_{key}"] = stacks[key]
    for role, weight in weights.items():
        ctx[f"fw_{role}"] = _font_weight_svg(weight)
    return ctx


def _now() -> _dt.datetime:
    """Return the current local time.  Isolated so tests can patch it."""
    from homeassistant.util import dt as hass_dt

    return hass_dt.now()


def _layout_context() -> dict[str, object]:
    """Return the fixed geometry the template draws with.

    All of it is in the 800 x 480 design space; the template's
    viewBox scales it to the widget's actual size.
    """
    return {
        "design_w": DESIGN_W,
        "design_h": DESIGN_H,
        "night_w": NIGHT_W,
        "night_h": NIGHT_H,
        "margin": MARGIN,
        "left_x": LEFT_X,
        "left_right": LEFT_RIGHT,
        "right_x": RIGHT_X,
        "right_right": RIGHT_RIGHT,
        "hero_cx": HERO_CX,
        "hero_cy": HERO_CY,
        "hero_scale": HERO_SCALE,
        "hour_scale": HOUR_SCALE,
        "day_scale": DAY_SCALE,
        "temp_x": TEMP_X,
        "y_date": Y_DATE,
        "y_uv_label": Y_UV_LABEL,
        "uv_badge_w": UV_BADGE_W,
        "uv_badge_h": UV_BADGE_H,
        "y_uv_badge": Y_UV_BADGE,
        "y_headline": Y_HEADLINE,
        "y_line2": Y_LINE2,
        "y_metrics": Y_METRICS,
        "line2_icon_x": LINE2_ICON_X,
        "line2_text_x": LINE2_TEXT_X,
        "wind_icon_x": WIND_ICON_X,
        "wind_text_x": WIND_TEXT_X,
        "solar_icon_x": SOLAR_ICON_X,
        "y_hour_label": Y_HOUR_LABEL,
        "hour_icon_cy": HOUR_ICON_CY,
        "y_no_hourly": Y_NO_HOURLY,
        "tile_w": NIGHT_TILE_W,
        "tile_h": NIGHT_TILE_H,
        "tile_dx": NIGHT_TILE_DX,
        "tile_dy": NIGHT_TILE_DY,
        "tile_r": NIGHT_TILE_R,
        "y_hour_temp": Y_HOUR_TEMP,
        "y_caption": Y_CAPTION,
        "y_rule": Y_RULE,
        "y_day_label": Y_DAY_LABEL,
        "day_icon_cy": DAY_ICON_CY,
        "y_day_temp": Y_DAY_TEMP,
        "y_day_prob": Y_DAY_PROB,
        "y_day_remark": Y_DAY_REMARK,
    }


def _clock_state(forced: object, now: _dt.datetime) -> str:
    """Return the layout decided on the clock alone.

    A ``force_state`` of morning, evening or night wins.  Otherwise
    it is evening from ``EVENING_FROM`` and morning before; whether
    the evening is in fact night depends on the sun, which the
    caller decides once it has the states snapshot.
    """
    if forced in ("morning", "evening", "night"):
        return str(forced)
    if now.hour >= EVENING_FROM:
        return "evening"
    return "morning"


def _second_line(
    state: str,
    today: dict[str, Any],
    hourly: list[dict[str, Any]],
    sun: tuple[Any, Any, bool],
    hass_dt: Any,
    now: _dt.datetime,
    s: dict[str, Any],
    units: _Units,
) -> tuple[str, str]:
    """Return the kind and text of the line under the headline.

    In the morning, the overnight low.  In the evening while the sun
    is still up, the times of sunset and sunrise.  After dark, a
    frost warning when the hours ahead call for one.

    Args:
        sun: ``(sunset, sunrise, sun_up)``.

    Returns:
        ``(kind, text)``: kind is ``"plain"``, ``"solar"``,
        ``"warn"`` or ``""`` when there is nothing to say.
    """
    sunset, sunrise, sun_up = sun
    if state == "morning":
        low = _temp(units.temp(today.get("templow")))
        if low["show"]:
            return "plain", s["overnight"].format(t=_signed(low))
        return "", ""
    if sun_up and sunset and sunrise:
        return "solar", (
            f"{sunset.strftime('%H:%M')} – {sunrise.strftime('%H:%M')}"
        )
    overnight = _overnight_slice(hourly, hass_dt, now)
    preceding = [
        e
        for e in hourly
        if (when := _local(hass_dt, e.get("datetime"))) is not None
        and now - _dt.timedelta(hours=6) <= when <= now
    ]
    warn = _frost_warning(overnight, preceding)
    if warn:
        return "warn", s["warnings"].get(warn, warn)
    return "", ""


def _wind_text(today: dict[str, Any], units: _Units) -> str:
    """Return the wind line: bearing, mean speed and any gust.

    The gust only earns its place when it is meaningfully above the
    mean; a range of a few km/h is noise dressed as detail.
    """
    gust = _num(today.get("wind_gust_speed"))
    speed = _num(today.get("wind_speed"))
    bearing = _compass(today.get("wind_bearing"))
    if speed is None:
        return ""
    if (
        gust is not None
        and speed > 0
        and gust >= speed * GUST_RATIO
        and gust - speed >= GUST_MARGIN
    ):
        lo = round(_num(units.speed(speed)) or 0)
        hi = round(_num(units.speed(gust)) or 0)
        return f"{bearing} {lo}–{hi} {units.speed_unit}"
    lo = round(_num(units.speed(speed)) or 0)
    return f"{bearing} {lo} {units.speed_unit}"


def _uv_context(
    widget: WeatherWallWidget, today: dict[str, Any], state: str
) -> dict[str, object]:
    """Return the UV badge: whether to show it, warn, and its text.

    Morning only.  The index is a daily maximum, so in the evening it
    describes a day that is over, and next to tonight's low or
    tomorrow's hours it reads as though it applied now.
    """
    hide_below = _num(widget.get("uv_hide_below"))
    hide_below = UV_HIDE_BELOW if hide_below is None else hide_below
    warn_above = _num(widget.get("uv_warn_above"))
    warn_above = UV_WARN_ABOVE if warn_above is None else warn_above
    uv = _num(today.get("uv_index"))
    show = state == "morning" and uv is not None and uv >= hide_below
    return {
        "uv_show": show,
        "uv_warn": show and uv is not None and uv > warn_above,
        "uv_text": f"{round(uv)}" if uv is not None else "",
    }


def _hour_is_dark(when: Any, sunset: Any, sunrise: Any) -> bool:
    """Return whether most of the hour starting at ``when`` is dark.

    Tested at the middle of the hour the entry describes, not at its
    start.  A column labelled 19 covers 19:00 to 20:00, so with
    sunset at 19:07 most of it is dark and the icon should say so;
    testing the instant would call it day.

    sun.sun reports only the next rising and setting, so comparing an
    arbitrary forecast hour against them gives the wrong answer as
    soon as either has passed.  Both are shifted onto the hour's own
    date before comparing.  They drift a minute or two a day, which
    is well within tolerance for a two-hourly strip.
    """
    if when is None or sunset is None or sunrise is None:
        return False
    mid = when + _dt.timedelta(minutes=30)
    up = sunrise.replace(year=mid.year, month=mid.month, day=mid.day)
    down = sunset.replace(year=mid.year, month=mid.month, day=mid.day)
    return mid < up or mid >= down


def _hour_strip(
    hours_raw: list[dict[str, Any]],
    hass_dt: Any,
    sunset: Any,
    sunrise: Any,
    units: _Units,
) -> list[dict[str, object]]:
    """Return the columns of the two-hourly strip on the right."""
    hours = []
    for i, e in enumerate(hours_raw):
        dark = _hour_is_dark(
            _local(hass_dt, e.get("datetime")), sunset, sunrise
        )
        hours.append(
            {
                "cx": round(RIGHT_X + HOUR_W * (i + 0.5), 1),
                "icon": _icon_name(e, dark),
                "dark": dark,
                "label": e.get("_label", ""),
                "temp": _temp(units.temp(e.get("temperature"))),
            }
        )
    return hours


def _percent(value: Any) -> str:
    """Return a probability as ``"40%"``, or ``""`` below ``PROB_MIN``."""
    prob = _num(value)
    if prob is None or prob < PROB_MIN:
        return ""
    return f"{round(prob)}%"


def _hero_context(
    night: bool,
    today: dict[str, Any],
    overnight: list[dict[str, Any]],
    moon_state: object,
) -> dict[str, object]:
    """Return the large icon: weather by day, moon and cloud by night.

    At night the icon is built from the overnight hourly slice rather
    than from the daily entry, which describes a day that is largely
    over and carries no cloud cover at all.  The cloud is drawn as
    its own element rather than through wx-moon-cloud, whose moon is
    a fixed gibbous; composing the two lets the real phase show
    behind it.
    """
    moon_phase = ""
    hero_icon = ""
    if night:
        cover, worst = _overnight_summary(overnight)
        if not worst:
            worst = today
        wet = _drop_count(worst, HERO_PROB_MIN) > 0

        # Without an hourly slice there is no cover to judge by, so
        # the condition string stands in: clear or nothing.
        if cover is None:
            clear = str(worst.get("condition", "")) in (
                "clear-night",
                "sunny",
            )
            cover = 0.0 if clear else 100.0

        if not wet and cover < MOON_HIDDEN_AT:
            moon_phase = _MOON_PHASES.get(str(moon_state), "")

        if wet:
            hero_icon = _icon_name(worst, True, HERO_PROB_MIN)
        elif cover >= CLOUD_IS_DARK:
            hero_icon = "wx-cloud-dark"
        elif cover >= MOON_CLEAR_BELOW:
            hero_icon = "wx-cloud"
    else:
        hero_icon = _icon_name(today, False, HERO_PROB_MIN)

    behind = bool(moon_phase and hero_icon)
    return {
        "hero_icon": hero_icon,
        "moon_phase": moon_phase,
        "moon_scale": (
            round(HERO_SCALE * MOON_BEHIND_SCALE, 3) if behind else HERO_SCALE
        ),
        "moon_dx": MOON_BEHIND_DX if behind else 0,
        "moon_dy": MOON_BEHIND_DY if behind else 0,
    }


def _day_strip(
    daily: list[dict[str, Any]],
    forecast_days: Any,
    state: str,
    hass_dt: Any,
    lang: str,
    s: dict[str, Any],
    climate: dict[str, Any],
    units: _Units,
) -> list[dict[str, object]]:
    """Return the columns of the week's outlook along the bottom.

    The provider gives a fixed number of days, so the strip is
    shorter in the evening, where tomorrow has already been spent on
    the top right.  The width is divided by what actually arrived
    rather than by the requested count, or the last column would sit
    in a gap and read as missing data.
    """
    from ..render import _weekday_abbrev

    try:
        want = max(3, min(DAY_COLS, int(forecast_days)))
    except (TypeError, ValueError):
        want = DAY_COLS
    first = 1 if state == "morning" else 2
    week = daily[first : first + want]
    n_days = max(1, len(week))
    day_w = (CANVAS_W - 2 * MARGIN - (n_days - 1) * DAY_GUTTER) / n_days
    days = []
    for i, e in enumerate(week):
        when = _local(hass_dt, e.get("datetime"))
        days.append(
            {
                "cx": round(MARGIN + (day_w + DAY_GUTTER) * i + day_w / 2, 1),
                # The day strip always describes daytime, whatever
                # the hour the panel is rendered at, so never the
                # night icon.
                "icon": _icon_name(e, False),
                "label": _weekday_abbrev(when.date(), lang) if when else "",
                "temp": _temp(units.temp(e.get("temperature"))),
                "prob": _percent(e.get("precipitation_probability")),
                "remark": _remarkable(e, when, s, climate, units),
            }
        )
    return days


def _build_weather_wall_context(
    widget: WeatherWallWidget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build the Jinja2 template context for the weather wall widget.

    Args:
        widget: Widget config.  Recognised keys: ``entity``,
            ``moon_entity``, ``temperature_entity``,
            ``forecast_days``, ``uv_hide_below``, ``uv_warn_above``,
            ``force_state``, ``font_family``, ``palette``,
            ``climatology_file``, ``x``, ``y``, ``w``, ``h``.
        config: Display config with ``width``, ``height``,
            ``states``, ``language`` and ``color_scheme``.

    Returns:
        Template context dict consumed by ``weather_wall.svg.j2``.

    Raises:
        RenderNotReady: The weather entity or its daily forecast is
            missing, so the last good image should be kept.
    """
    from homeassistant.util import dt as hass_dt

    # Dates and weekday names come from Babel through the
    # integration's own helpers, so they match its other widgets;
    # the remaining vocabulary comes from _WALL_PHRASES.
    from ..render import _babel_format_date

    x = widget.get("x", 0)
    y = widget.get("y", 0)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", config["height"] - y)

    states = config.get("states", {})
    entity_id = widget.get("entity", "")
    entity = states.get(entity_id)
    now = _now()
    lang = str(config.get("language") or "en")
    s = _phrases(lang)

    # The typeface.  By default the widget follows the dashboard's
    # font family, through the same helpers as the stock templates,
    # so a TRMNL dashboard gets the pixel font at its snapped sizes
    # and Inter for the large figures.
    #
    # A per-widget font_family overrides that with any face the
    # renderer can find, such as one in the custom font directory.
    # It is drawn at the design sizes, unsnapped and anti-aliased,
    # whatever the dashboard's settings, and Roboto stays behind it
    # in the stack so a glyph the face lacks, such as the true minus,
    # falls back rather than rendering nothing.
    fonts = _font_context(
        str(widget.get("font_family") or "").strip(), _role_weights(widget)
    )

    if entity is None:
        raise RenderNotReady(
            f"weather_wall: entity {entity_id!r} is not in the states "
            "snapshot; refusing to render a panel with no forecast"
        )

    attrs = entity.get("attributes", {})
    units = _Units(attrs)
    daily: list[dict[str, Any]] = [
        units.metric(e) for e in attrs.get("forecast", []) or []
    ]
    hourly: list[dict[str, Any]] = [
        units.metric(e) for e in attrs.get("forecast_hourly", []) or []
    ]

    if not daily:
        raise RenderNotReady(
            f"weather_wall: no daily forecast for {entity_id!r}; "
            "refusing to render a panel with no forecast"
        )

    today = daily[0]
    tomorrow = daily[1] if len(daily) > 1 else {}

    # Sunrise and sunset come from sun.sun, which is always loaded.
    # It reports only the *next* rising and the *next* setting, so
    # after sunset next_setting is tomorrow's, and comparing it
    # against now says the sun has not gone down.  The entity's own
    # state answers the question directly.
    sun_state = states.get("sun.sun", {})
    sun = sun_state.get("attributes", {})
    sunset = _local(hass_dt, sun.get("next_setting"))
    sunrise = _local(hass_dt, sun.get("next_rising"))
    sun_up = sun_state.get("state") == "above_horizon"

    # Night is defined by the sun rather than the clock: in December
    # the panel should go dark at six, in June not until ten.
    forced = widget.get("force_state", "auto")
    state = _clock_state(forced, now)
    if forced == "auto" and state == "evening" and not sun_up:
        state = "night"
    morning = state == "morning"

    # ---- headline --------------------------------------------
    headline = _temp(
        units.temp(today.get("temperature" if morning else "templow"))
    )
    # A temperature sensor applies only to the morning headline,
    # where the number is a live reading rather than a forecast.
    temp_entity = widget.get("temperature_entity", "")
    if morning and temp_entity:
        reading = states.get(temp_entity)
        if reading is not None:
            headline = _temp(
                units.sensor_temp(
                    reading.get("state"),
                    reading.get("attributes", {}).get("unit_of_measurement"),
                )
            )

    line2_kind, line2_text = _second_line(
        state,
        today,
        hourly,
        (sunset, sunrise, sun_up),
        hass_dt,
        now,
        s,
        units,
    )

    # ---- the bottom metrics line -----------------------------
    if morning:
        solar_text = sunset.strftime("%H:%M") if sunset else ""
    elif line2_kind == "solar":
        # Both times are already on the line above.
        solar_text = ""
    else:
        solar_text = sunrise.strftime("%H:%M") if sunrise else ""

    # ---- the right-hand strip --------------------------------
    hours_raw = _pick_hours(hourly, hass_dt, now, state)
    rain_d, rain_mid = _rain_path(hours_raw)
    # The daily figure for whichever day the strip covers, not the
    # peak across its hours: a maximum overstates, since fifteen per
    # cent for one hour is not fifteen per cent all day.
    rain_day = today if morning else tomorrow

    header_max = ""
    if not morning:
        hi = _temp(units.temp(tomorrow.get("temperature")))
        header_max = s["max"].format(t=_signed(hi)) if hi["show"] else ""

    moon_state = states.get(
        widget.get("moon_entity", "sensor.moon_phase"), {}
    ).get("state", "")

    return {
        "w": svg_w,
        "h": svg_h,
        **_layout_context(),
        **fonts,
        "s_uv": s["uv"],
        **_palette(widget, config),
        **_color_context(),
        "state": state,
        "is_night": state == "night",
        "has_state": True,
        "date_text": _babel_format_date(now.date(), "EEEE d MMMM", lang),
        **_hero_context(
            not morning,
            today,
            _overnight_slice(hourly, hass_dt, now) if not morning else [],
            moon_state,
        ),
        "headline": headline,
        "line2_kind": line2_kind,
        "line2_text": line2_text,
        "wind_text": _wind_text(today, units),
        "solar_text": solar_text,
        **_uv_context(widget, today, state),
        "header_left": "" if morning else s["tomorrow"],
        "header_max": header_max,
        "header_uv": "",
        "hours": _hour_strip(hours_raw, hass_dt, sunset, sunrise, units),
        "rain_d": rain_d,
        "rain_mid": round(rain_mid, 1),
        "rain_peak": _percent(rain_day.get("precipitation_probability")),
        "caption": s["chance"][_precip_word(hours_raw)],
        "hours_note": "" if hours_raw else s["no_hourly"],
        "days": _day_strip(
            daily,
            widget.get("forecast_days", 7),
            state,
            hass_dt,
            lang,
            s,
            _climatology(widget.get("climatology_file")),
            units,
        ),
    }

#!/usr/bin/env python3
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

"""Build a daily climatology table for the weather wall widget.

Downloads daily reanalysis values for one location from Open-Meteo
and writes percentile thresholds for each calendar date to a JSON
file.  The widget reads that file once at import, so nothing here
runs at render time: no network call, no API key, no rate limit, and
no dependency on a service being up when the panel refreshes.

Why percentiles against a window rather than against the days on
screen: a five-day sample gives a standard deviation with an
enormous confidence interval, and it measures "unusual for this
week" rather than "unusual for September".  Gathering every value
within a window of the target date across every year of record gives
several hundred samples, which is the standard practice for
percentile-based climate indices.

Why a full ladder of percentiles rather than the two or three the
widget currently uses: the raw samples are discarded once a
percentile is taken, so a threshold that was not stored cannot be
recovered without rerunning this script.  Storing fifteen costs
about a fifth of a megabyte and means the widget can be retuned by
editing one constant.

Two sources, because no single one has everything:

* Temperature, wind gust and rainfall come from the ERA5 archive,
  over the 1991 to 2020 WMO standard normal period.  That is what
  the Met Office publish their own averages against, and a longer
  record would carry enough warming to flag most warm days and
  almost no cold ones.

* Ultraviolet comes from the air quality endpoint, which derives it
  from CAMS.  The ERA5 archive has no ultraviolet index at all: it
  carries broadband shortwave radiation, from which ultraviolet
  cannot be recovered without modelling solar geometry and the
  ozone column, since the ratio between them moves strongly with
  both.  That archive only begins in mid-2022, so ultraviolet gets
  a wider window to compensate; it varies smoothly with the season
  rather than synoptically, so this costs little.

Usage, from the repository root:

    python3 scripts/build_climatology.py \\
        --latitude 51.48 --longitude -0.01 --output climatology.json

Then copy the file somewhere in the Home Assistant configuration
directory, outside custom_components, and give its path in the
widget's climatology_file option; see docs/climatology.md.

The location is taken from the command line and is not written into
the output, so the table cannot disclose it wherever it ends up.  A
location a kilometre or two away gives the same answer: the
reanalysis grid is about 25 km across.

Uses only the standard library, so it runs with any Python 3.

Open-Meteo data is CC BY 4.0; see https://open-meteo.com/en/license

Run once.  The output does not need regenerating until the 2001 to
2030 normals are published, though rerunning it occasionally will
lengthen the ultraviolet baseline.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---- configuration -------------------------------------------------

# WMO standard normal period, for everything from the archive.
START = "1991-01-01"
END = "2020-12-31"

# Ultraviolet baseline.  The air quality archive begins in mid-2022;
# the script tries each year in turn and keeps what it can get, so
# these bounds are deliberately optimistic at both ends.
UV_FIRST_YEAR = 2013
UV_LAST_YEAR = dt.date.today().year

# Half-width of the window around each calendar date, in days.
# Seven gives fifteen days per year of record, so 450 samples over
# a thirty-year baseline.
WINDOW_DAYS = 7

# Ultraviolet gets a wider window.  With only a few years of record
# a seven-day window yields around thirty samples, which puts a 90th
# percentile between the second and third highest values and makes
# it lurch with any one unusual day.  Fifteen days gives roughly
# 150, and because ultraviolet is governed by solar elevation and
# ozone rather than by passing weather systems, a month-wide window
# still describes a meaningfully specific time of year.
UV_WINDOW_DAYS = 15

# Percentiles recorded for every measure, upper and lower tails
# alike.  A one-tailed measure such as gust will never use its lower
# values, but storing them costs almost nothing and keeps the file
# format uniform.
PERCENTILES = (1, 2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 98, 99)

MEASURES = {
    "tmax": "temperature_2m_max",
    "tmin": "temperature_2m_min",
    "gust": "wind_gusts_10m_max",
    "rain": "precipitation_sum",
}

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# Courtesy pause between requests.  The service is free and asks
# only that it is not hammered.
PAUSE_SECONDS = 1.0

# ---- helpers -------------------------------------------------------


def get_json(url: str, params: dict) -> dict:
    """Fetch and parse a JSON response.

    Args:
        url: The endpoint.
        params: Query parameters.

    Returns:
        The decoded response.

    Raises:
        urllib.error.HTTPError: If the endpoint rejects the request,
            which is how an unsupported variable or an out-of-range
            date presents.
    """
    full = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(full, timeout=180) as response:
        return json.load(response)


def fetch_daily(
    place: dict[str, object], variable: str
) -> tuple[list[str], list[float | None]]:
    """Fetch one daily archive variable for the whole baseline.

    Args:
        place: ``latitude``, ``longitude`` and ``timezone`` query
            parameters.
        variable: An Open-Meteo daily variable name.

    Returns:
        ``(dates, values)`` as parallel lists.
    """
    payload = get_json(
        ARCHIVE_URL,
        {
            **place,
            "start_date": START,
            "end_date": END,
            "daily": variable,
        },
    )
    daily = payload.get("daily", {})
    return daily.get("time", []), daily.get(variable, [])


def fetch_uv_year(place: dict[str, object], year: int) -> dict[str, float]:
    """Fetch one year of hourly ultraviolet and reduce to daily peaks.

    The air quality endpoint offers ultraviolet only hourly, and the
    World Health Organization's guidance is that the index should be
    presented as a daily maximum, which is also what the Met Office
    forecast gives.  So the hourly series is reduced here.

    Fetched a year at a time so that one large response cannot time
    out and take the whole run with it.

    Args:
        place: ``latitude``, ``longitude`` and ``timezone`` query
            parameters.
        year: Calendar year to fetch.

    Returns:
        A mapping of ISO date to that day's peak index.
    """
    end = f"{year}-12-31"
    today = dt.date.today()
    if year == today.year:
        # The endpoint refuses a range that runs past the data, so
        # the current year stops at yesterday.
        end = (today - dt.timedelta(days=1)).isoformat()
    payload = get_json(
        AIR_QUALITY_URL,
        {
            **place,
            "start_date": f"{year}-01-01",
            "end_date": end,
            "hourly": "uv_index",
        },
    )
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    values = hourly.get("uv_index", [])
    peaks: dict[str, float] = {}
    for stamp, value in zip(times, values, strict=False):
        if value is None:
            continue
        day = stamp[:10]
        if float(value) > peaks.get(day, -1.0):
            peaks[day] = float(value)
    return peaks


def day_key(date: dt.date) -> str:
    """Return the calendar key for a date, folding 29 February.

    The 29th appears in only a quarter of years, so it is given the
    28th's distribution rather than a sample a quarter the size.
    """
    if date.month == 2 and date.day == 29:
        return "02-28"
    return f"{date.month:02d}-{date.day:02d}"


def all_keys() -> list[str]:
    """Return the 365 calendar keys in order, starting 1 January."""
    base = dt.date(2001, 1, 1)  # a non-leap year
    out = []
    for i in range(365):
        date = base + dt.timedelta(days=i)
        out.append(f"{date.month:02d}-{date.day:02d}")
    return out


def percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile by linear interpolation.

    Args:
        values: A non-empty list of numbers.  Sorted in place.
        p: The percentile, 0 to 100.

    Returns:
        The interpolated value.
    """
    values.sort()
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * p / 100.0
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def gather(
    pairs: list[tuple[str, float]],
    window: int,
) -> dict[str, list[float]]:
    """Group observations into a window around each calendar date.

    Each observation is filed against every calendar key within
    ``window`` days of its own date, so one value contributes to
    several windows.  The year is discarded: what matters is the
    time of year, not which year it was.

    Args:
        pairs: ``(iso_date, value)`` tuples.
        window: Half-width of the window, in days.

    Returns:
        A mapping of calendar key to every value in its window.
    """
    buckets: dict[str, list[float]] = {k: [] for k in all_keys()}
    for raw, value in pairs:
        date = dt.date.fromisoformat(raw)
        for offset in range(-window, window + 1):
            buckets[day_key(date + dt.timedelta(days=offset))].append(value)
    return buckets


def store(
    table: dict[str, dict[str, dict[str, float]]],
    name: str,
    pairs: list[tuple[str, float]],
    window: int,
) -> int:
    """Compute and record thresholds for one measure.

    Args:
        table: The table being built, keyed by calendar date.
        name: Short measure name used as the key in the output.
        pairs: ``(iso_date, value)`` tuples.
        window: Half-width of the window, in days.

    Returns:
        The sample count for a mid-year window, as a sanity check.
    """
    buckets = gather(pairs, window)
    for key, samples in buckets.items():
        if not samples:
            continue
        ordered = sorted(samples)
        table[key][name] = {
            f"p{p}": round(percentile(ordered, p), 2) for p in PERCENTILES
        }
    return len(buckets["07-01"])


# ---- main ----------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Build the climatology table for the weather wall widget "
            "from Open-Meteo reanalysis data (CC BY 4.0)."
        )
    )
    parser.add_argument(
        "--latitude", type=float, required=True, help="decimal degrees"
    )
    parser.add_argument(
        "--longitude",
        type=float,
        required=True,
        help="decimal degrees, negative west of Greenwich",
    )
    parser.add_argument(
        "--timezone",
        default="auto",
        help=(
            "IANA time zone for daily aggregation, e.g. Europe/London; "
            "the default, auto, takes it from the coordinates"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("climatology.json"),
        help="file to write (default: climatology.json here)",
    )
    args = parser.parse_args(argv)
    if not -90 <= args.latitude <= 90:
        parser.error("latitude must be between -90 and 90")
    if not -180 <= args.longitude <= 180:
        parser.error("longitude must be between -180 and 180")
    return args


def main(argv: list[str] | None = None) -> int:
    """Download, compute and write the climatology table."""
    args = parse_args(argv)
    place: dict[str, object] = {
        "latitude": args.latitude,
        "longitude": args.longitude,
        "timezone": args.timezone,
    }
    print(f"Archive:  {START} to {END}, window +/- {WINDOW_DAYS} days")
    print(
        f"UV:       {UV_FIRST_YEAR} onward, window +/- {UV_WINDOW_DAYS} days"
    )
    print(f"Storing:  {len(PERCENTILES)} percentiles per measure\n")

    table: dict[str, dict[str, dict[str, float]]] = {
        key: {} for key in all_keys()
    }
    obtained: list[str] = []
    notes: dict[str, str] = {}

    # ---- the archive measures ----
    for name, variable in MEASURES.items():
        print(f"{name:6s} {variable:24s} ... ", end="", flush=True)
        try:
            dates, values = fetch_daily(place, variable)
        except urllib.error.HTTPError as exc:
            print(f"unavailable ({exc.code})")
            continue
        except Exception as exc:
            print(f"failed ({exc})")
            continue

        pairs = [
            (d, float(v))
            for d, v in zip(dates, values, strict=False)
            if v is not None
        ]
        if not pairs:
            print("no data")
            continue
        count = store(table, name, pairs, WINDOW_DAYS)
        print(f"ok ({len(pairs)} days, {count} per window)")
        obtained.append(name)
        notes[name] = f"ERA5 archive {START} to {END}"
        time.sleep(PAUSE_SECONDS)

    # ---- ultraviolet, from the air quality endpoint ----
    print(f"\n{'uv':6s} {'uv_index (CAMS)':24s}")
    uv_pairs: list[tuple[str, float]] = []
    years_got: list[int] = []
    for year in range(UV_FIRST_YEAR, UV_LAST_YEAR + 1):
        print(f"       {year} ... ", end="", flush=True)
        try:
            peaks = fetch_uv_year(place, year)
        except urllib.error.HTTPError as exc:
            print(f"unavailable ({exc.code})")
            continue
        except Exception as exc:
            print(f"failed ({exc})")
            continue
        if not peaks:
            print("no data")
            continue
        uv_pairs.extend(peaks.items())
        years_got.append(year)
        print(f"ok ({len(peaks)} days)")
        time.sleep(PAUSE_SECONDS)

    if uv_pairs:
        count = store(table, "uv", uv_pairs, UV_WINDOW_DAYS)
        span = f"{min(years_got)} to {max(years_got)}"
        print(
            f"       total: {len(uv_pairs)} days over {span}, "
            f"{count} per window"
        )
        obtained.append("uv")
        notes["uv"] = f"CAMS air quality {span}"
    else:
        print("       no ultraviolet data obtained")

    if not obtained:
        print("\nNothing was downloaded; the file has not been written.")
        return 1

    # The coordinates are deliberately left out: the widget does not
    # need them, and the file should disclose nothing about where it
    # was built for.
    document = {
        "meta": {
            "timezone": args.timezone,
            "window_days": WINDOW_DAYS,
            "uv_window_days": UV_WINDOW_DAYS,
            "percentiles": list(PERCENTILES),
            "measures": obtained,
            "sources": notes,
            "licence": "Open-Meteo, CC BY 4.0",
            "generated": dt.date.today().isoformat(),
        },
        "days": table,
    }

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, separators=(",", ":")))
    size = output.stat().st_size
    print(f"\nWrote {output} ({size // 1024} kB)")
    print(f"Measures: {', '.join(obtained)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

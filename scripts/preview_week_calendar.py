#!/usr/bin/env python3
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

"""Render the week calendar widget from mock data to PNG files.

Lets you tweak the widget's look without releasing: edit
``widgets/week_calendar.py`` or ``templates/week_calendar.svg.j2``,
run this script (or use ``--watch``), and open the PNGs.  Runs
without a Home Assistant installation.

The mock week is fixed (Monday 2026-10-19) and the clock is pinned,
so the output only changes when the code does.  It covers
overlapping events (including 30 minute ones), events before and
after the grid, an event crossing the grid edge, all-day events, an
overnight event, long titles and a busy day.

Two files are written to the output directory:
  week_calendar_raw.png   -- the rendered widget before dithering
  week_calendar_eink.png  -- after the e-ink optimisation pipeline,
                             quantised to the device's gray levels

Usage:
    python3 scripts/preview_week_calendar.py
    python3 scripts/preview_week_calendar.py --watch
    python3 scripts/preview_week_calendar.py --device reterminal_e1002
    python3 scripts/preview_week_calendar.py --data my_events.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from _bootstrap import PKG, ROOT, import_module

import_module(f"{PKG}.const")
import_module(f"{PKG}.optimize")
import_module(f"{PKG}.conditions")
import_module(f"{PKG}.svg_render")
import_module(f"{PKG}.render")

from custom_components.eink_dashboard.const import DEVICE_PRESETS
from custom_components.eink_dashboard.render import render_dashboard

_PKG_DIR = ROOT / "custom_components" / "eink_dashboard"
_WATCHED = (
    _PKG_DIR / "widgets" / "week_calendar.py",
    _PKG_DIR / "templates" / "week_calendar.svg.j2",
)
_CLOCK = "custom_components.eink_dashboard.widgets.week_calendar._now"
_ENTITY = "calendar.mock"

# Wednesday of the mock week, so today's column is in the middle.
_NOW = dt.datetime(2026, 10, 21, 10, 15)


def _ev(start: str, end: str, summary: str) -> dict[str, str]:
    """Build an event as returned by ``calendar.get_events``."""
    return {"start": start, "end": end, "summary": summary}


MOCK_EVENTS: list[dict[str, str]] = [
    # Monday: a long event overlapped by a 30 minute one, and a lunch.
    _ev("2026-10-19T09:00:00", "2026-10-19T10:30:00", "Team meeting"),
    _ev("2026-10-19T09:30:00", "2026-10-19T10:00:00", "Dentist"),
    _ev("2026-10-19T12:00:00", "2026-10-19T13:00:00", "Lunch with Anna"),
    # Tuesday: events before and after the grid (chips).
    _ev("2026-10-20T05:00:00", "2026-10-20T05:45:00", "Early run"),
    _ev("2026-10-20T14:00:00", "2026-10-20T16:00:00", "Project review"),
    _ev("2026-10-20T22:30:00", "2026-10-20T23:30:00", "Late call"),
    # Tuesday noon to Wednesday noon: split into one box per day.
    _ev("2026-10-20T12:00:00", "2026-10-21T12:00:00", "Conference trip"),
    # Wednesday (today): a long title and back-to-back events.
    _ev("2026-10-21T09:00:00", "2026-10-21T09:15:00", "Standup"),
    _ev(
        "2026-10-21T10:00:00",
        "2026-10-21T11:30:00",
        "Parent-teacher meeting at school",
    ),
    _ev("2026-10-21T18:00:00", "2026-10-21T19:00:00", "Gym"),
    _ev("2026-10-21T19:00:00", "2026-10-21T21:00:00", "Dinner"),
    # Thursday/Friday: multi-day all-day event, two simultaneous
    # 30 minute events.
    _ev("2026-10-22", "2026-10-24", "Company holiday"),
    _ev("2026-10-22T13:00:00", "2026-10-22T13:30:00", "Quick sync"),
    _ev("2026-10-22T13:00:00", "2026-10-22T13:30:00", "Coffee"),
    # Friday: a long event with two overlapping 30 minute ones.
    _ev("2026-10-23T15:00:00", "2026-10-23T17:00:00", "Workshop"),
    _ev("2026-10-23T15:30:00", "2026-10-23T16:00:00", "Call"),
    _ev("2026-10-23T15:45:00", "2026-10-23T16:15:00", "Review"),
    # Saturday: all-day plus a long event; overnight into Sunday.
    _ev("2026-10-24", "2026-10-25", "Market"),
    _ev("2026-10-24T14:00:00", "2026-10-24T18:00:00", "Birthday party"),
    _ev("2026-10-24T23:00:00", "2026-10-25T09:00:00", "Night shift"),
    # Sunday: crosses the grid start and the grid end.
    _ev("2026-10-25T07:00:00", "2026-10-25T09:00:00", "Flight"),
    _ev("2026-10-25T20:00:00", "2026-10-25T22:30:00", "Movie night"),
]


def render(args: argparse.Namespace) -> None:
    """Render the mock week to the raw and e-ink PNG files.

    Args:
        args: Parsed command-line arguments.
    """
    preset = DEVICE_PRESETS[args.device]
    events = MOCK_EVENTS
    if args.data:
        events = json.loads(Path(args.data).read_text(encoding="utf-8"))

    widget = {
        "type": "week_calendar",
        "entity": _ENTITY,
        "x": 0,
        "y": 0,
        "w": preset.width,
        "h": preset.height,
    }
    config = {
        "width": preset.width,
        "height": preset.height,
        "display_levels": preset.display_levels,
        "language": args.language,
        "first_weekday": args.first_weekday,
        "time_format": args.time_format,
        "states": {
            _ENTITY: {
                "state": "off",
                "attributes": {"week_events": events},
            }
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    with patch(_CLOCK, return_value=_NOW):
        raw = render_dashboard([widget], {**config, "optimize": False})
        eink = render_dashboard([widget], {**config, "optimize": True})
    (args.out / "week_calendar_raw.png").write_bytes(raw)
    (args.out / "week_calendar_eink.png").write_bytes(eink)
    print(
        f"{preset.label} {preset.width}x{preset.height}, "
        f"{preset.display_levels} levels -> {args.out}"
    )


def watch(args: argparse.Namespace) -> None:
    """Re-render whenever a watched source file changes.

    Each render runs in a fresh subprocess so edits to the Python
    builder are picked up without reloading modules.

    Args:
        args: Parsed command-line arguments, forwarded to the
            subprocess minus ``--watch``.
    """
    forwarded = [
        "--device",
        args.device,
        "--language",
        args.language,
        "--first-weekday",
        args.first_weekday,
        "--time-format",
        args.time_format,
        "--out",
        str(args.out),
        *(["--data", args.data] if args.data else []),
    ]
    sources = [*_WATCHED, Path(__file__)]
    seen: dict[Path, float] = {}
    print("Watching for changes (Ctrl+C to stop)")
    while True:
        mtimes = {p: p.stat().st_mtime for p in sources if p.exists()}
        if mtimes != seen:
            seen = mtimes
            subprocess.run(
                [sys.executable, str(Path(__file__)), *forwarded],
                check=False,
            )
        time.sleep(0.5)


def main() -> None:
    """Parse arguments and render once or in watch mode."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--device",
        default="reterminal_e1001",
        choices=sorted(DEVICE_PRESETS),
        help="Device preset for size and gray levels",
    )
    parser.add_argument("--language", default="de")
    parser.add_argument(
        "--first-weekday",
        default="monday",
        help='"monday" … "sunday", or "language"',
    )
    parser.add_argument("--time-format", default="24", choices=["12", "24"])
    parser.add_argument(
        "--data",
        help="JSON file with a list of events to use instead of the mock",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / ".tmp" / "preview",
        help="Output directory (default: .tmp/preview)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Re-render when the widget code or template changes",
    )
    args = parser.parse_args()
    if args.watch:
        watch(args)
    else:
        render(args)


if __name__ == "__main__":
    main()

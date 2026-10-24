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

"""Axis tick computation for the graph widget.

Pure helpers that choose tick values for the value (Y) and time (X)
axes, format their labels, and map them to pixel positions.  The
context builder in ``context.py`` decides where the axes go; this
module only answers "which ticks, with which labels, where".
"""

from __future__ import annotations

import datetime
import itertools
import math
from typing import TYPE_CHECKING, Any

from .._helpers import _fmt, _resolve_tz

if TYPE_CHECKING:
    from ...const import DisplayConfig

# Candidate time steps for round X-axis ticks, smallest first.
_TIME_STEPS: tuple[int, ...] = (
    60,
    120,
    300,
    600,
    900,
    1800,
    3600,
    2 * 3600,
    3 * 3600,
    4 * 3600,
    6 * 3600,
    12 * 3600,
    86400,
    2 * 86400,
    7 * 86400,
)

# Mantissas of "nice" value steps (1, 2, 2.5 and 5 times a power of
# ten), the usual choice for human-readable axis labels.
_NICE_MANTISSAS: tuple[float, ...] = (1.0, 2.0, 2.5, 5.0)

# Tolerance for float comparisons when stepping through tick values.
_EPS = 1e-9


def _format_timestamp(
    ts: float,
    time_fmt: str,
    tz: datetime.tzinfo = datetime.UTC,
) -> str:
    """Format a Unix timestamp as a short time string.

    Args:
        ts: Unix timestamp (seconds since epoch).
        time_fmt: ``"12"`` for 12-hour with AM/PM, any other value
            for 24-hour ``HH:MM`` format.
        tz: Time zone the time is shown in (default UTC).

    Returns:
        Formatted time string.
    """
    dt = datetime.datetime.fromtimestamp(ts, tz=tz)
    if time_fmt == "12":
        # %-I is GNU libc-only; lstrip("0") is portable.
        return dt.strftime("%I:%M %p").lstrip("0")
    return dt.strftime("%H:%M")


def _nice_steps(raw: float) -> list[float]:
    """Return ascending nice step sizes, the first one ``>= raw``."""
    exp = math.floor(math.log10(raw)) if raw > 0 else 0
    steps = [
        m * 10.0**e for e in (exp, exp + 1, exp + 2) for m in _NICE_MANTISSAS
    ]
    return [s for s in steps if s >= raw - _EPS]


def _step_decimals(step: float) -> int:
    """Return how many decimals are needed to print multiples of step."""
    for decimals in range(6):
        if abs(round(step, decimals) - step) < _EPS:
            return decimals
    return 6


def _value_tick_values(
    y_min: float, y_max: float, count: int
) -> tuple[list[float], int]:
    """Choose value-axis tick values and their decimal places.

    ``count <= 2`` keeps the classic min/max pair with one decimal.
    Larger counts pick the smallest nice step that yields at most
    ``count`` multiples of the step inside ``[y_min, y_max]``.

    Args:
        y_min: Axis lower bound.
        y_max: Axis upper bound.
        count: Maximum number of ticks requested.

    Returns:
        ``(values, decimals)`` with values in ascending order.
    """
    if count <= 2:
        return [y_min, y_max], 1
    for step in _nice_steps((y_max - y_min) / (count - 1)):
        first = math.ceil(y_min / step - _EPS)
        last = math.floor(y_max / step + _EPS)
        if last - first + 1 <= count:
            values = [k * step for k in range(first, last + 1)]
            if len(values) >= 2:
                return values, _step_decimals(step)
            break
    return [y_min, y_max], 1


def _value_axis_labels(
    y_min: float,
    y_max: float,
    count: int,
    unit: str,
    config: DisplayConfig,
) -> list[tuple[float, str]]:
    """Return ``(value, label)`` pairs for a value axis.

    Args:
        y_min: Axis lower bound.
        y_max: Axis upper bound.
        count: Requested tick count (2 = min/max only).
        unit: Unit appended to every label after a space, or ``""``.
        config: Display config for locale number formatting.

    Returns:
        Ascending list of tick values with their formatted labels.
    """
    values, decimals = _value_tick_values(y_min, y_max, count)
    suffix = f" {unit}" if unit else ""
    return [(v, _fmt(f"{v:.{decimals}f}", config) + suffix) for v in values]


def _place_value_ticks(
    labels: list[tuple[float, str]],
    y_min: float,
    y_max: float,
    gy1: int,
    gy2: int,
    font_sz: int,
) -> list[dict[str, object]]:
    """Map value-axis labels to pixel rows.

    Each tick gets ``y`` (the tick's exact row on the plot),
    ``label``, ``label_y`` and ``baseline``.  Labels on the plot's
    top and bottom edges hang below / sit on the edge like the
    classic min/max labels; others are vertically centred on their
    row but kept inside the plot's vertical extent.

    Args:
        labels: ``(value, label)`` pairs from ``_value_axis_labels``.
        y_min: Axis lower bound.
        y_max: Axis upper bound.
        gy1: Plot top edge.
        gy2: Plot bottom edge.
        font_sz: Label font size in pixels.

    Returns:
        List of tick dicts in ascending value order.
    """
    y_range = y_max - y_min
    half = font_sz / 2
    ticks: list[dict[str, object]] = []
    for value, label in labels:
        y = round(gy2 - (value - y_min) / y_range * (gy2 - gy1))
        if y >= gy2:
            label_y, baseline = gy2, "auto"
        elif y <= gy1:
            label_y, baseline = gy1, "hanging"
        else:
            label_y = round(min(max(y, gy1 + half), gy2 - half))
            baseline = "central"
        ticks.append(
            {
                "y": y,
                "label": label,
                "label_y": label_y,
                "baseline": baseline,
            }
        )
    return ticks


def _value_label_extent(
    tick: dict[str, object], font_sz: int
) -> tuple[float, float]:
    """Return the ``(top, bottom)`` rows covered by a value label.

    The label box is approximated by one em, positioned according to
    the baseline chosen by ``_place_value_ticks``.
    """
    label_y = float(str(tick["label_y"]))
    if tick["baseline"] == "auto":
        return label_y - font_sz, label_y
    if tick["baseline"] == "hanging":
        return label_y, label_y + font_sz
    return label_y - font_sz / 2, label_y + font_sz / 2


def _value_ticks_fit(ticks: list[dict[str, object]], font_sz: int) -> bool:
    """Return whether placed value labels keep a gap between them.

    Checks the final (edge-clamped) label boxes, so labels pushed
    inward at the plot edges are validated too.
    """
    gap = font_sz / 4
    # Ticks ascend in value, so each next label sits higher (smaller y).
    extents = [_value_label_extent(t, font_sz) for t in ticks]
    return all(
        lower[0] - upper[1] >= gap
        for lower, upper in itertools.pairwise(extents)
    )


def _value_axis_ticks(
    y_min: float,
    y_max: float,
    count: int,
    unit: str,
    gy1: int,
    gy2: int,
    font_sz: int,
    config: DisplayConfig,
) -> list[dict[str, object]]:
    """Choose, label and place value-axis ticks that do not overlap.

    Starts with up to ``count`` ticks and lowers the count until the
    placed labels keep a gap between each other on the plot's
    height.  When no count above two fits, the classic min/max pair
    is used.

    Args:
        y_min: Axis lower bound.
        y_max: Axis upper bound.
        count: Requested maximum number of ticks.
        unit: Unit appended to every label, or ``""``.
        gy1: Plot top edge.
        gy2: Plot bottom edge.
        font_sz: Label font size in pixels.
        config: Display config for locale number formatting.

    Returns:
        List of tick dicts (see ``_place_value_ticks``).
    """
    for k in range(count, 2, -1):
        labels = _value_axis_labels(y_min, y_max, k, unit, config)
        ticks = _place_value_ticks(labels, y_min, y_max, gy1, gy2, font_sz)
        if _value_ticks_fit(ticks, font_sz):
            return ticks
    labels = _value_axis_labels(y_min, y_max, 2, unit, config)
    return _place_value_ticks(labels, y_min, y_max, gy1, gy2, font_sz)


def _fit_centred_labels(
    xs: list[int],
    widths: list[float],
    gx1: int,
    gx2: int,
    gap: float,
) -> list[int] | None:
    """Clamp centred labels into the plot and check they do not overlap.

    Labels near the plot edges are pushed inward to stay inside
    ``[gx1, gx2]``; the overlap check runs on these final positions,
    so a clamped edge label never ends up closer to its neighbour
    than ``gap``.

    Args:
        xs: Tick x positions, left to right.
        widths: Label widths in pixels, same order.
        gx1: Plot left edge.
        gx2: Plot right edge.
        gap: Minimum horizontal gap between neighbouring labels.

    Returns:
        The label centre x positions, or ``None`` when they overlap.
    """
    label_xs = [
        round(min(max(x, gx1 + w / 2), gx2 - w / 2))
        for x, w in zip(xs, widths, strict=True)
    ]
    for j in range(len(label_xs) - 1):
        right_edge = label_xs[j] + widths[j] / 2
        left_edge = label_xs[j + 1] - widths[j + 1] / 2
        if left_edge - right_edge < gap:
            return None
    return label_xs


def _time_label(
    ts: float,
    step: int,
    time_fmt: str,
    tz: datetime.tzinfo,
    language: str,
) -> str:
    """Format a time tick: weekday for day steps, clock time otherwise."""
    if step >= 86400:
        from ...render import _weekday_abbrev

        return _weekday_abbrev(
            datetime.datetime.fromtimestamp(ts, tz=tz).date(), language
        )
    return _format_timestamp(ts, time_fmt, tz)


def _aligned_times(
    t_min: float, t_max: float, step: int, tz: datetime.tzinfo
) -> list[float]:
    """Return multiples of ``step`` past local midnight in the range.

    Ticks are aligned to the local day (in ``tz``) so a 6 h step
    lands on 00:00, 06:00, 12:00 and 18:00 local time.
    """
    start = datetime.datetime.fromtimestamp(t_min, tz=tz)
    midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if step >= 7 * 86400:
        # Weekly steps start on the first day of the ISO week.
        midnight -= datetime.timedelta(days=midnight.weekday())
    origin = midnight.timestamp()
    k = math.ceil((t_min - origin) / step - _EPS)
    times: list[float] = []
    t = origin + k * step
    while t <= t_max + _EPS:
        times.append(t)
        t += step
    return times


def _edge_ticks(
    t_min: float,
    t_max: float,
    gx1: int,
    gx2: int,
    config: DisplayConfig,
) -> list[dict[str, object]]:
    """Return the classic oldest/newest pair pinned to the plot edges."""
    tz = _resolve_tz(config)
    time_fmt = str(config.get("time_format", "24"))
    return [
        {
            "x": gx1,
            "label": _format_timestamp(t_min, time_fmt, tz),
            "label_x": gx1,
            "anchor": "start",
        },
        {
            "x": gx2,
            "label": _format_timestamp(t_max, time_fmt, tz),
            "label_x": gx2,
            "anchor": "end",
        },
    ]


def _time_axis_ticks(
    t_min: float,
    t_max: float,
    count: int,
    gx1: int,
    gx2: int,
    font: Any,
    config: DisplayConfig,
) -> list[dict[str, object]]:
    """Choose and place time-axis ticks for a line graph.

    ``count <= 2`` keeps the classic oldest/newest labels pinned to
    the plot edges.  Larger counts use the smallest round step
    (minutes, hours, days) that gives at most ``count`` ticks whose
    labels do not overlap; when no step fits, the classic pair is
    used.

    Args:
        t_min: Timestamp mapped to ``gx1``.
        t_max: Timestamp mapped to ``gx2``.
        count: Requested maximum number of ticks.
        gx1: Plot left edge.
        gx2: Plot right edge.
        font: Loaded label font used to measure label widths.
        config: Display config (``time_format``, ``time_zone``,
            ``language``).

    Returns:
        List of tick dicts with ``x``, ``label``, ``label_x`` and
        ``anchor`` (SVG ``text-anchor``), in left-to-right order.
    """
    tz = _resolve_tz(config)
    time_fmt = str(config.get("time_format", "24"))
    language = str(config.get("language", "en"))
    span = max(t_max - t_min, 1.0)
    plot_w = gx2 - gx1

    if count <= 2:
        return _edge_ticks(t_min, t_max, gx1, gx2, config)

    raw = span / (count - 1)
    for step in _TIME_STEPS:
        if step < raw - _EPS:
            continue
        times = _aligned_times(t_min, t_max, step, tz)
        if not 2 <= len(times) <= count:
            continue
        labels = [_time_label(t, step, time_fmt, tz, language) for t in times]
        widths = [font.getlength(lbl) for lbl in labels]
        gap = font.size / 2 if hasattr(font, "size") else 4
        xs = [round(gx1 + (t - t_min) / span * plot_w) for t in times]
        label_xs = _fit_centred_labels(xs, widths, gx1, gx2, gap)
        if label_xs is None:
            continue
        return [
            {
                "x": x,
                "label": label,
                "label_x": label_x,
                "anchor": "middle",
            }
            for x, label, label_x in zip(xs, labels, label_xs, strict=True)
        ]
    return _edge_ticks(t_min, t_max, gx1, gx2, config)


def _bar_axis_ticks(
    bars: list[dict[str, object]],
    timestamps: list[float],
    count: int,
    gx1: int,
    gx2: int,
    font: Any,
    config: DisplayConfig,
) -> list[dict[str, object]]:
    """Choose and place time-axis ticks for a bar chart.

    Bars are laid out by index, so ticks label individual bars at
    their centres.  Up to ``count`` evenly spaced bars (always
    including the first and last) are picked, reducing the number
    until neighbouring labels do not overlap.

    Args:
        bars: Bar geometry dicts (``x``, ``w``) of the labelled series.
        timestamps: Bucket timestamp of each bar, same order.
        count: Requested maximum number of ticks.
        gx1: Plot left edge.
        gx2: Plot right edge.
        font: Loaded label font used to measure label widths.
        config: Display config (``time_format``, ``time_zone``).

    Returns:
        List of tick dicts like ``_time_axis_ticks``, or an empty
        list when fewer than two labels fit (the caller then falls
        back to ``_edge_ticks``).
    """
    tz = _resolve_tz(config)
    time_fmt = str(config.get("time_format", "24"))
    n = min(len(bars), len(timestamps))
    if n < 2:
        return []
    centres = [
        round(float(str(b["x"])) + float(str(b["w"])) / 2) for b in bars[:n]
    ]
    labels = [_format_timestamp(t, time_fmt, tz) for t in timestamps[:n]]
    gap = font.size / 2 if hasattr(font, "size") else 4
    for k in range(min(count, n), 1, -1):
        idx = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
        widths = [font.getlength(labels[i]) for i in idx]
        xs = [centres[i] for i in idx]
        label_xs = _fit_centred_labels(xs, widths, gx1, gx2, gap)
        if label_xs is not None:
            return [
                {
                    "x": centres[i],
                    "label": labels[i],
                    "label_x": label_x,
                    "anchor": "middle",
                }
                for i, label_x in zip(idx, label_xs, strict=True)
            ]
    return []

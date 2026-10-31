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

"""Week calendar widget context builder."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from babel import Locale, UnknownLocaleError

from ..const import COLOR_LIGHT_GRAY, FontWeight, color_to_hex
from ._helpers import (
    _color_context,
    _resolve_tz,
    _title_layout,
    _widget_dim,
)
from .graph.geometry import _truncate_to_width

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..const import DisplayConfig
    from ..widget_config import WeekCalendarWidget

_LOGGER = logging.getLogger(__name__)

DEFAULT_START_HOUR = 8
DEFAULT_END_HOUR = 20

# Caps that keep the grid usable when a week is crowded.  Extra
# all-day spans and extra out-of-grid events collapse into "+N" markers.
_MAX_ALL_DAY_LANES = 3
_MAX_CHIPS = 2

# The time grid needs at least this many pixels per hour.  A widget too
# short to guarantee that, even with every strip and chip row used,
# shows the agenda layout instead (see ``_grid_fits``).
_MIN_PX_PER_HOUR = 6

# Event, chip and all-day text uses fixed pixel sizes instead of
# scaling with the widget, which keeps small text legible.  The start
# time uses ``_DEFAULT_TIME_SIZE`` and a title ``_DEFAULT_EVENT_SIZE``.
# Both are multiplied by the display's ``font_scale``, and the ``time``
# and ``event`` font roles can pin them.
_DEFAULT_TIME_SIZE = 9
_DEFAULT_EVENT_SIZE = 12


def _ev_line_h(size: int) -> int:
    """Return the line height used for event text of ``size`` pixels."""
    return size + 2


# How many times lane packing is repeated while events that end up
# side by side grow to their taller minimum height.
_PACK_PASSES = 3

# Height given to zero-length events so they stay visible.
_ZERO_LENGTH_MINUTES = 30

_WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True, slots=True)
class _AllDaySpan:
    """An all-day event, as a run of day columns."""

    first: int
    """Index of the first day column it covers."""
    last: int
    """Index of the last day column it covers."""
    text: str
    """Event title."""
    lane: int = 0
    """Horizontal strip lane, set by ``_place_all_day``."""


@dataclass(slots=True)
class _Segment:
    """One day's slice of a timed event, in minutes since midnight."""

    sm: int
    """Start minute of the slice."""
    em: int
    """End minute of the slice."""
    text: str
    """Event title."""
    label_sm: int
    """Start minute of the whole event, shown as the time label."""
    end: int = 0
    """Minute the drawn box reaches; set by ``_pack_day``."""
    lane: int = 0
    """Side-by-side lane; set by ``_assign_lanes``."""
    lanes: int = 1
    """Lane count of the cluster; set by ``_assign_lanes``."""


@dataclass(frozen=True, slots=True)
class _Overflow:
    """Stand-in chip for the out-of-grid events a column cannot list."""

    count: int
    """Number of events it stands for."""


class _AllDayStrip(NamedTuple):
    """The all-day spans that fit the strip, and what did not."""

    spans: list[_AllDaySpan]
    """Spans with their lane set."""
    hidden: list[int]
    """Per day, how many spans are folded into a "+N" marker."""
    lanes: int
    """Lanes the strip takes, including the one with the markers."""


class _WeekEvents(NamedTuple):
    """The events of one week, sorted by where they are drawn."""

    all_day: list[_AllDaySpan]
    """All-day spans in the strip under the day headers."""
    timed: list[list[_Segment]]
    """Per day, the segments inside the grid, clipped to it."""
    before: list[list[_Segment]]
    """Per day, the segments that end before the grid starts."""
    after: list[list[_Segment]]
    """Per day, the segments that start after the grid ends."""


def _snap_gray(value: int, levels: int) -> str:
    """Return the display gray level nearest to ``value`` as hex.

    Only grays the display can show exactly stay solid after
    dithering; any other gray is mixed from black and white dots,
    which makes a thin line look dotted.  Levels are evenly spaced
    from black to white, so a 2-level display snaps gray to black.

    Args:
        value: Gray intensity 0-255 to approximate.
        levels: Number of gray levels the display shows.

    Returns:
        SVG hex color of the nearest level.
    """
    step = 255 / max(1, levels - 1)
    return color_to_hex(round(round(value / step) * step))


def _now(config: DisplayConfig) -> datetime:
    """Return the current local wall-clock time as a naive datetime.

    Isolated so tests can patch the clock.

    Args:
        config: Display config; ``time_zone`` selects the zone.

    Returns:
        Naive ``datetime`` in HA's configured time zone (UTC when
        unset).
    """
    return datetime.now(_resolve_tz(config)).replace(tzinfo=None)


def _first_weekday_index(first_weekday: str, language: str) -> int:
    """Resolve a ``first_weekday`` setting to a weekday index.

    Args:
        first_weekday: ``"monday"`` … ``"sunday"``, or ``"language"``
            to use the first weekday of the display language.
        language: BCP 47 language code (e.g. ``"de"``).

    Returns:
        Index with Monday = 0 … Sunday = 6.  Falls back to Monday
        when the language is unknown to babel.
    """
    idx = _WEEKDAY_INDEX.get(first_weekday.lower())
    if idx is not None:
        return idx
    try:
        return int(Locale.parse(language.replace("-", "_")).first_week_day)
    except (UnknownLocaleError, ValueError):
        return 0


def week_calendar_entity_ids(widget: Mapping[str, object]) -> list[str]:
    """Return the calendar entity IDs a week calendar widget shows.

    Args:
        widget: Widget config whose ``entity`` is a calendar entity ID
            or a list of entity IDs.

    Returns:
        The non-empty entity IDs in configured order, without
        duplicates.
    """
    raw = widget.get("entity", "")
    items = raw if isinstance(raw, list) else [raw]
    return list(dict.fromkeys(str(e) for e in items if e))


def _to_naive(raw: object) -> datetime | None:
    """Parse a calendar start/end value into a naive datetime.

    Unlike the regular calendar widget's parser this one never falls
    back to today, so a malformed event can be skipped instead of
    showing up as a bogus one.

    Args:
        raw: ``"YYYY-MM-DD"`` or an ISO 8601 datetime; any timezone
            offset is ignored (HA returns local wall-clock values).

    Returns:
        The parsed datetime (date-only strings give midnight), or
        ``None`` if ``raw`` is not a non-empty, parseable string.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        if len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), time.min)
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        return None


def _fmt_hm(minutes: int, time_format: str) -> str:
    """Format minutes since midnight as a short clock time.

    Args:
        minutes: Minutes since local midnight (0..1440).
        time_format: ``"12"`` for AM/PM, anything else for 24-hour.

    Returns:
        A string such as ``"9:30"`` or ``"9:30 PM"``.
    """
    hour, minute = divmod(minutes % 1440, 60)
    if time_format == "12":
        return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
    return f"{hour}:{minute:02d}"


def _wrap_text(
    text: str,
    font: Any,
    max_w: float,
    max_lines: int,
    first_offset: float = 0.0,
) -> list[str]:
    """Greedy word-wrap ``text`` into at most ``max_lines`` lines.

    Every line is cut with an ellipsis if it is wider than its
    available width, so a single long word or unplaced words never
    overflow the box.

    Args:
        text: Text to wrap.
        font: PIL font used for measuring.
        max_w: Maximum line width in pixels.
        max_lines: Maximum number of lines (>= 1).
        first_offset: Width already taken on the first line by a
            prefix drawn separately (the start time).  When not even
            the first word fits beside it, the first line is left
            empty so the text starts on the second line.

    Returns:
        The wrapped lines.
    """
    words = text.split()
    lines: list[str] = []
    cur = ""
    i = 0

    def avail() -> float:
        """Return the width left on the line being filled."""
        return max_w - (0 if lines else first_offset)

    while i < len(words):
        cand = f"{cur} {words[i]}".strip()
        if (
            not cur
            and not lines
            and first_offset
            and max_lines > 1
            and font.getlength(words[i]) > avail()
        ):
            lines.append("")
            continue
        if cur and font.getlength(cand) > avail():
            if len(lines) + 1 >= max_lines:
                break
            lines.append(_truncate_to_width(cur, font, avail()))
            cur = ""
            continue
        cur = cand
        i += 1
    # Whatever is left (current line plus unplaced words) goes on the
    # final line, truncated with an ellipsis if it overflows.
    last = " ".join([cur, *words[i:]]).strip()
    if last or not lines:
        lines.append(_truncate_to_width(last, font, avail()))
    return lines


def _assign_lanes(segs: list[_Segment]) -> None:
    """Assign side-by-side lanes to overlapping event segments.

    Segments are grouped into clusters of transitively overlapping
    events; within a cluster each gets the first free lane, and all
    share the cluster's lane count so they split the column evenly.

    Args:
        segs: Segments with ``sm`` (start) and ``end`` minute bounds,
            where ``end`` is the minute the drawn box reaches.  Sorted
            and annotated in place with ``lane`` and ``lanes``.
    """
    segs.sort(key=lambda s: (s.sm, -s.end))
    clusters: list[list[_Segment]] = []
    cur: list[_Segment] = []
    cur_end = -1
    for seg in segs:
        if cur and seg.sm >= cur_end:
            clusters.append(cur)
            cur = []
            cur_end = -1
        cur.append(seg)
        cur_end = max(cur_end, seg.end)
    if cur:
        clusters.append(cur)
    for cluster in clusters:
        lane_ends: list[int] = []
        for seg in cluster:
            for li, end in enumerate(lane_ends):
                if end <= seg.sm:
                    seg.lane = li
                    lane_ends[li] = seg.end
                    break
            else:
                seg.lane = len(lane_ends)
                lane_ends.append(seg.end)
        for seg in cluster:
            seg.lanes = len(lane_ends)


def _collect_week_events(
    raw_events: list[dict[str, Any]],
    days: list[date],
    gs: int,
    ge: int,
) -> _WeekEvents:
    """Sort raw events into all-day spans, grid segments and chips.

    Timed events are split at midnight so multi-day events appear on
    every day they touch.  A segment ending before the grid goes to
    ``before``, one starting after it to ``after``; the rest are
    clipped to ``[gs, ge]`` and returned in ``timed``.

    Args:
        raw_events: Events as returned by ``calendar.get_events``.
        days: The seven displayed dates.
        gs: Grid start in minutes since midnight.
        ge: Grid end in minutes since midnight.

    Returns:
        The all-day spans and, per day, the in-grid, before-grid and
        after-grid segments.
    """
    all_day: list[_AllDaySpan] = []
    timed: list[list[_Segment]] = [[] for _ in days]
    before: list[list[_Segment]] = [[] for _ in days]
    after: list[list[_Segment]] = [[] for _ in days]
    week_start = days[0]
    for ev in raw_events:
        if not isinstance(ev, dict):
            _LOGGER.debug("Skipping week calendar event %r: not a dict", ev)
            continue
        summary = str(ev.get("summary", ""))
        start_raw = ev.get("start")
        start_dt, end_dt = _to_naive(start_raw), _to_naive(ev.get("end"))
        if start_dt is None or end_dt is None:
            _LOGGER.debug(
                "Skipping week calendar event %r: invalid start or end", ev
            )
            continue
        if bool(ev.get("all_day")) or len(str(start_raw)) == 10:
            # The end date of an all-day event is exclusive.
            last = max(start_dt.date(), end_dt.date() - timedelta(days=1))
            first_i = max(0, (start_dt.date() - week_start).days)
            last_i = min(len(days) - 1, (last - week_start).days)
            if first_i <= last_i:
                all_day.append(_AllDaySpan(first_i, last_i, summary))
            continue
        for i, day in enumerate(days):
            day_start = datetime.combine(day, time.min)
            day_end = day_start + timedelta(days=1)
            seg_s, seg_e = max(start_dt, day_start), min(end_dt, day_end)
            sm = int((seg_s - day_start).total_seconds() // 60)
            em = int((seg_e - day_start).total_seconds() // 60)
            if end_dt <= start_dt:
                # Zero-length event: only on its own day.
                if not day_start <= start_dt < day_end:
                    continue
                em = min(sm + _ZERO_LENGTH_MINUTES, 1440)
            if em <= sm:
                continue
            # Label with the event's real start, not the midnight cut
            # of a continuation segment.
            label_sm = start_dt.hour * 60 + start_dt.minute
            seg = _Segment(sm, em, summary, label_sm)
            if em <= gs:
                before[i].append(seg)
            elif sm >= ge:
                after[i].append(seg)
            else:
                seg.sm, seg.em = max(sm, gs), min(em, ge)
                timed[i].append(seg)
    return _WeekEvents(all_day, timed, before, after)


def _place_all_day(all_day: list[_AllDaySpan]) -> _AllDayStrip:
    """Assign all-day spans to horizontal lanes.

    Each span takes the first lane whose days are all free.  If more
    than ``_MAX_ALL_DAY_LANES`` lanes would be needed, the last lane
    and everything below it are not drawn; each day they cover shows
    a "+N" marker in the last lane instead.

    Args:
        all_day: Spans to place.

    Returns:
        The spans to draw with their lanes, the per-day counts of
        hidden spans and the number of lanes the strip takes.
    """
    lanes: list[list[bool]] = []
    placed: list[_AllDaySpan] = []
    for item in sorted(all_day, key=lambda a: (a.first, -a.last)):
        span = range(item.first, item.last + 1)
        lane = next(
            (
                li
                for li, used in enumerate(lanes)
                if not any(used[d] for d in span)
            ),
            len(lanes),
        )
        if lane == len(lanes):
            lanes.append([False] * 7)
        for d in span:
            lanes[lane][d] = True
        placed.append(replace(item, lane=lane))
    hidden = [0] * 7
    if len(lanes) <= _MAX_ALL_DAY_LANES:
        return _AllDayStrip(placed, hidden, len(lanes))
    last = _MAX_ALL_DAY_LANES - 1
    for item in placed:
        if item.lane >= last:
            for d in range(item.first, item.last + 1):
                hidden[d] += 1
    shown = [item for item in placed if item.lane < last]
    return _AllDayStrip(shown, hidden, _MAX_ALL_DAY_LANES)


def _pack_day(
    segs: list[_Segment],
    px_per_min: float,
    single_px: int,
    multi_px: int,
) -> None:
    """Assign lanes using each event's drawn height, not its duration.

    A short event is drawn at least ``single_px`` tall, or
    ``multi_px`` once it shares its column.  Packing by duration alone
    would put two nearby short events in the same lane although their
    boxes collide, so each event occupies the minutes its box covers.
    Growing to ``multi_px`` can create new collisions, hence the
    repeated passes.

    Args:
        segs: Segments with ``sm``/``em`` minute bounds; annotated in
            place with ``end``, ``lane`` and ``lanes``.
        px_per_min: Vertical pixels per minute.
        single_px: Minimum box height of an event alone in its lane.
        multi_px: Minimum box height of an event sharing its column.
    """
    multi: set[int] = set()
    for _ in range(_PACK_PASSES):
        for seg in segs:
            px = multi_px if id(seg) in multi else single_px
            seg.end = max(seg.em, seg.sm + math.ceil(px / px_per_min))
        _assign_lanes(segs)
        now = {id(seg) for seg in segs if seg.lanes > 1}
        if now == multi:
            return
        multi = now


def _hour_setting(widget: Mapping[str, object], key: str, default: int) -> int:
    """Return an hour setting, or ``default`` when it is empty or invalid.

    The editor can store a cleared field as an empty string or ``None``.

    Args:
        widget: Widget config.
        key: Setting key, ``"start_hour"`` or ``"end_hour"``.
        default: Value used when the setting cannot be read as a number.

    Returns:
        The setting as an int, not yet clamped to the time axis.
    """
    try:
        return int(float(str(widget.get(key, default))))
    except (ValueError, TypeError, OverflowError):
        return default


@dataclass(frozen=True, slots=True)
class _Geometry:
    """Horizontal geometry of the seven day columns."""

    gutter_w: int
    """Width of the hour-label column on the left."""
    col_w: float
    """Width of one day column, before rounding."""

    def col_x(self, i: int) -> int:
        """Return the left pixel edge of day column ``i``."""
        return self.gutter_w + round(i * self.col_w)

    def edge_px(self, i: int) -> int:
        """Return the pixel column of the vertical gridline at edge ``i``.

        The template draws each separator on the pixel column
        ``col_x(i)``, except the last one, which is pulled in by one
        pixel so it is not clipped at the widget's right edge.
        """
        return self.col_x(i) - (1 if i == 7 else 0)

    def day_span(self, first: int, last: int) -> tuple[int, int]:
        """Return ``(x, width)`` of a box over days ``first``..``last``.

        The box starts on a gridline and ends one pixel before the
        next, so it never merges into the gridline after it.
        """
        x0 = self.edge_px(first)
        return x0, self.edge_px(last + 1) - x0 - 1


@dataclass(frozen=True, slots=True)
class _Layout:
    """Vertical layout of the widget, in pixels."""

    content_y: int
    """Top of the calendar, below the optional title."""
    content_h: int
    """Height of the calendar."""
    header_h: int
    """Height of the day header row."""
    lane_h: int
    """Height of one all-day lane."""
    chip_h: int
    """Height of one out-of-grid chip."""
    strip_h: int
    """Height of the all-day strip."""
    top_chips: int
    """Chip rows reserved above the grid."""
    bottom_chips: int
    """Chip rows reserved below the grid."""
    grid_top: int
    """Top of the time grid."""
    grid_bottom: int
    """Bottom of the time grid."""
    grid_start: int
    """Minute of the day at the top of the grid."""
    px_per_min: float
    """Vertical pixels per minute."""
    single_px: int
    """Minimum box height of an event alone in its lane."""
    multi_px: int
    """Minimum box height of an event sharing its column."""


@dataclass(frozen=True, slots=True)
class _Fonts:
    """Text sizes and the fonts that measure them."""

    day_size: int
    """Size of the day headers."""
    hour_size: int
    """Size of the hour labels."""
    time_size: int
    """Size of an event's start time."""
    event_size: int
    """Size of event titles."""
    day: Any
    """PIL font measuring the day headers."""
    time: Any
    """PIL font measuring the start time."""
    event: Any
    """PIL font measuring an event title."""
    day_weight: str
    """SVG ``font-weight`` of the day headers."""
    hour_weight: str
    """SVG ``font-weight`` of the hour labels."""
    time_weight: str
    """SVG ``font-weight`` of an event's start time."""
    event_weight: str
    """SVG ``font-weight`` of event titles."""

    def context(self) -> dict[str, object]:
        """Return the font entries of the template context."""
        return {
            "day_font": self.day_size,
            "day_weight": self.day_weight,
            "hour_font": self.hour_size,
            "hour_weight": self.hour_weight,
            "time_font_sz": self.time_size,
            "time_weight": self.time_weight,
            "event_weight": self.event_weight,
        }


def _title_band(
    widget: WeekCalendarWidget,
    title: str,
    svg_h: int,
    font_scale: float,
) -> tuple[int, str, int, int]:
    """Resolve the title font and the band it takes above the calendar.

    Args:
        widget: Widget config; its ``fonts`` may override ``title``.
        title: Header text, or ``""`` for none.
        svg_h: Total widget height in pixels.
        font_scale: Display-level font scale.

    Returns:
        ``(title_font_sz, title_weight, content_y, content_h)``, with
        the weight as an SVG ``font-weight`` value.
    """
    from ..render import _font_weight_svg, resolve_font

    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    weight = FontWeight.REGULAR
    if title:
        title_font_sz, weight = resolve_font(
            widget,
            "title",
            title_font_sz,
            FontWeight.REGULAR,
            scale=font_scale,
        )
        # Re-derive the title band from the resolved size, as the other
        # titled widgets do, so a larger title keeps its clearance.
        content_y = round(title_font_sz * 1.4)
        content_h = svg_h - content_y
    return title_font_sz, _font_weight_svg(weight), content_y, content_h


def _resolve_fonts(
    widget: WeekCalendarWidget,
    day_default: int,
    font_scale: float,
) -> _Fonts:
    """Resolve the text roles of the calendar body.

    Roles resolve through the shared API so the widget's ``fonts``
    overrides and the display-level ``font_scale`` apply.

    Args:
        widget: Widget config; its ``fonts`` may override the roles
            ``day``, ``hour``, ``time`` and ``event``.
        day_default: Derived default size of the day headers; the
            hour labels follow it.
        font_scale: Display-level font scale.

    Returns:
        The resolved sizes and weights with the fonts that measure them.
    """
    from ..render import _font_weight_svg, _load_role_font, resolve_font

    day_size, day_weight = resolve_font(
        widget, "day", day_default, FontWeight.MEDIUM, scale=font_scale
    )
    hour_size, hour_weight = resolve_font(
        widget,
        "hour",
        max(8, round(day_default * 0.8)),
        FontWeight.REGULAR,
        scale=font_scale,
    )
    time_size, time_weight = resolve_font(
        widget,
        "time",
        _DEFAULT_TIME_SIZE,
        FontWeight.REGULAR,
        scale=font_scale,
    )
    event_size, event_weight = resolve_font(
        widget,
        "event",
        _DEFAULT_EVENT_SIZE,
        FontWeight.REGULAR,
        scale=font_scale,
    )
    return _Fonts(
        day_size=day_size,
        hour_size=hour_size,
        time_size=time_size,
        event_size=event_size,
        day=_load_role_font(day_size, day_weight),
        time=_load_role_font(time_size, time_weight),
        event=_load_role_font(event_size, event_weight),
        day_weight=_font_weight_svg(day_weight),
        hour_weight=_font_weight_svg(hour_weight),
        time_weight=_font_weight_svg(time_weight),
        event_weight=_font_weight_svg(event_weight),
    )


def _fit_title(
    fonts: _Fonts,
    title: str,
    x0: int,
    y0: int,
    w: int,
    h: int,
    label: str = "",
    pad: int = 2,
    max_lines: int | None = None,
) -> dict[str, object]:
    """Lay out ``title`` beside the start ``label`` in a box.

    Text that does not fit the box is wrapped onto as many lines as
    fit and cut with an ellipsis.  The label is drawn in the time font
    ahead of the first line, so the room it takes there is measured
    with that font.

    Args:
        fonts: Text sizes and measuring fonts.
        title: Event title.
        x0: Left edge of the box.
        y0: Top edge of the box.
        w: Box width.
        h: Box height.
        label: Start time, or ``""`` for none.
        pad: Vertical room kept free inside the box.
        max_lines: Upper limit for the number of lines.

    Returns:
        The box with its font size and the vertically centred
        ``lines``, for the template.
    """
    inner_w = w - 6
    time_w = fonts.time.getlength(label) if label else 0
    size = fonts.event_size
    fits = (h - pad) // _ev_line_h(size)
    if max_lines is not None:
        fits = min(fits, max_lines)
    lines: list[str] = []
    if inner_w > 0 and fits >= 1:
        gap = fonts.event.getlength(" ")
        lines = _wrap_text(
            title,
            fonts.event,
            inner_w,
            fits,
            first_offset=time_w + gap if label else 0,
        )
    # Even with no room for the title, the start time is drawn.
    lines = lines or [""]
    lh = _ev_line_h(size)
    top = y0 + (h - len(lines) * lh) // 2
    return {
        "x": x0,
        "y": y0,
        "w": w,
        "h": h,
        "font_sz": size,
        "lines": [
            {
                "text": t,
                "time": label if k == 0 else "",
                "x": x0 + 3,
                "y": top + k * lh + lh // 2,
            }
            for k, t in enumerate(lines)
        ],
    }


def _day_headers(
    days: list[date],
    today: date,
    geo: _Geometry,
    fonts: _Fonts,
    language: str,
) -> list[dict[str, object]]:
    """Return the day header cells.

    Args:
        days: The seven displayed dates.
        today: The current date, drawn inverted.
        geo: Column geometry.
        fonts: Text sizes and measuring fonts.
        language: BCP 47 language code for the weekday names.

    Returns:
        One cell per day, for the template.
    """
    from ..render import _weekday_abbrev

    headers: list[dict[str, object]] = []
    for i, day in enumerate(days):
        w_i = geo.col_x(i + 1) - geo.col_x(i)
        label = _truncate_to_width(
            f"{_weekday_abbrev(day, language)} {day.day}",
            fonts.day,
            w_i - 4,
        )
        headers.append(
            {
                "x": geo.col_x(i),
                "w": w_i,
                "cx": geo.col_x(i) + w_i // 2,
                "label": label,
                "is_today": day == today,
            }
        )
    return headers


def _all_day_boxes(
    strip: _AllDayStrip,
    geo: _Geometry,
    layout: _Layout,
    fonts: _Fonts,
) -> list[dict[str, object]]:
    """Return the boxes of the all-day strip.

    Args:
        strip: Placed spans and the counts of hidden ones.
        geo: Column geometry.
        layout: Vertical layout.
        fonts: Text sizes and measuring fonts.

    Returns:
        One box per span, then one "+N" box per day with hidden
        spans, for the template.
    """
    top = layout.content_y + layout.header_h
    boxes: list[dict[str, object]] = []
    for item in strip.spans:
        bx, bw = geo.day_span(item.first, item.last)
        by = top + item.lane * layout.lane_h + 1
        boxes.append(
            _fit_title(
                fonts,
                item.text,
                bx,
                by,
                bw,
                layout.lane_h - 2,
                pad=0,
                max_lines=1,
            )
        )
    for day, count in enumerate(strip.hidden):
        if count:
            bx, bw = geo.day_span(day, day)
            by = top + (_MAX_ALL_DAY_LANES - 1) * layout.lane_h + 1
            boxes.append(
                _fit_title(
                    fonts,
                    f"+{count}",
                    bx,
                    by,
                    bw,
                    layout.lane_h - 2,
                    pad=0,
                    max_lines=1,
                )
            )
    return boxes


def _chip_boxes(
    before: list[list[_Segment]],
    after: list[list[_Segment]],
    geo: _Geometry,
    layout: _Layout,
    fonts: _Fonts,
    time_format: str,
) -> list[dict[str, object]]:
    """Return the chips for events outside the grid.

    Chips are stacked at the top or bottom of their day's column; more
    than ``_MAX_CHIPS`` collapse into a "+N" chip.

    Args:
        before: Per day, the segments that end before the grid.
        after: Per day, the segments that start after the grid.
        geo: Column geometry.
        layout: Vertical layout.
        fonts: Text sizes and measuring fonts.
        time_format: ``"12"`` for AM/PM, anything else for 24-hour.

    Returns:
        One box per chip, for the template.
    """
    chips: list[dict[str, object]] = []
    for i in range(7):
        bx, bw = geo.day_span(i, i)
        for segs, count, base_y in (
            (
                before[i],
                layout.top_chips,
                layout.content_y + layout.header_h + layout.strip_h,
            ),
            (after[i], layout.bottom_chips, layout.grid_bottom),
        ):
            ordered = sorted(segs, key=lambda s: s.sm)
            shown: list[_Segment | _Overflow] = [*ordered]
            if len(shown) > _MAX_CHIPS:
                extra = len(shown) - _MAX_CHIPS + 1
                shown = [*shown[: _MAX_CHIPS - 1], _Overflow(extra)]
            for k, chip in enumerate(shown[:count]):
                cy = base_y + k * layout.chip_h + 1
                if isinstance(chip, _Overflow):
                    label = ""
                    chip_text = f"+{chip.count}"
                else:
                    label = _fmt_hm(chip.label_sm, time_format)
                    chip_text = chip.text
                chips.append(
                    _fit_title(
                        fonts,
                        chip_text,
                        bx,
                        cy,
                        bw,
                        layout.chip_h - 2,
                        label,
                        pad=0,
                        max_lines=1,
                    )
                )
    return chips


def _event_boxes(
    timed: list[list[_Segment]],
    geo: _Geometry,
    layout: _Layout,
    fonts: _Fonts,
    time_format: str,
) -> list[dict[str, object]]:
    """Return the boxes of the events inside the grid.

    Args:
        timed: Per day, the segments inside the grid; lanes are
            assigned in place.
        geo: Column geometry.
        layout: Vertical layout.
        fonts: Text sizes and measuring fonts.
        time_format: ``"12"`` for AM/PM, anything else for 24-hour.

    Returns:
        One box per event segment, for the template.
    """
    events: list[dict[str, object]] = []
    for i in range(7):
        _pack_day(
            timed[i], layout.px_per_min, layout.single_px, layout.multi_px
        )
        left, right = geo.edge_px(i), geo.edge_px(i + 1)
        for seg in timed[i]:
            # Lanes split the span between the gridlines.  Every box
            # ends one pixel before its right neighbour (the next lane
            # or the gridline), so boxes never merge into each other
            # or into the gridline.
            lanes_n = seg.lanes
            ex = left + round(seg.lane * (right - left) / lanes_n)
            ex_right = left + round((seg.lane + 1) * (right - left) / lanes_n)
            ew = ex_right - ex - 1
            ey = layout.grid_top + round(
                (seg.sm - layout.grid_start) * layout.px_per_min
            )
            eh = max(
                layout.multi_px if lanes_n > 1 else layout.single_px,
                round((seg.em - seg.sm) * layout.px_per_min) - 1,
            )
            ey = max(layout.grid_top, min(ey, layout.grid_bottom - eh))
            label = _fmt_hm(seg.label_sm, time_format)
            events.append(_fit_title(fonts, seg.text, ex, ey, ew, eh, label))
    return events


def _hour_lines(
    start_hour: int,
    end_hour: int,
    layout: _Layout,
    fonts: _Fonts,
    time_format: str,
) -> list[dict[str, object]]:
    """Return the hour gridlines with their labels.

    Every other hour is labelled when the rows are tight.

    Args:
        start_hour: First hour on the time axis.
        end_hour: Hour at which the axis ends.
        layout: Vertical layout.
        fonts: Text sizes and measuring fonts.
        time_format: ``"12"`` for AM/PM, anything else for 24-hour.

    Returns:
        One entry per line, for the template.
    """
    hour_px = 60 * layout.px_per_min
    step = 1 if hour_px >= fonts.hour_size * 1.8 else 2
    hours: list[dict[str, object]] = []
    for hr in range(start_hour, end_hour + 1):
        hy = layout.grid_top + round(
            (hr * 60 - layout.grid_start) * layout.px_per_min
        )
        show = (hr - start_hour) % step == 0
        label = (
            _fmt_hm(hr * 60, time_format).replace(":00", "") if show else ""
        )
        # The baseline puts the digits (cap height about 0.71 em) a
        # couple of pixels under the line.  A label that would not fit
        # above the widget's bottom edge, as for the last line, is
        # dropped.
        label_y = hy + 3 + round(fonts.hour_size * 0.71)
        if label_y > layout.content_y + layout.content_h - 1:
            label = ""
        hours.append({"y": hy, "label": label, "label_y": label_y})
    return hours


def _grid_fits(
    content_h: int,
    header_h: int,
    lane_h: int,
    chip_h: int,
    hours: int,
) -> bool:
    """Return whether the time grid is guaranteed to fit the widget.

    The all-day strip and the chip rows are capped, so the tallest the
    rows above and below the grid can get is known without looking at
    any event.  Deciding on that worst case keeps the layout from
    changing when events are added or removed.

    Args:
        content_h: Height of the calendar.
        header_h: Height of the day header row.
        lane_h: Height of one all-day lane.
        chip_h: Height of one chip row.
        hours: Hours on the time axis.

    Returns:
        ``True`` if the grid keeps ``_MIN_PX_PER_HOUR`` with every
        strip lane and chip row in use.
    """
    worst_rows = _MAX_ALL_DAY_LANES * lane_h + 2 * _MAX_CHIPS * chip_h
    return content_h >= header_h + worst_rows + _MIN_PX_PER_HOUR * hours


def _agenda_boxes(
    week: _WeekEvents,
    geo: _Geometry,
    top: int,
    rows: int,
    row_h: int,
    fonts: _Fonts,
    time_format: str,
) -> list[dict[str, object]]:
    """Return the event rows of the agenda layout.

    Each day lists its all-day events, then its timed events by start
    time, one row each.  If a day has more events than rows, the last
    row reads "+N" for the ones that do not fit.

    Args:
        week: Events sorted for the whole day, as the agenda has no
            time axis to cut them off.
        geo: Column geometry.
        top: Top of the first row.
        rows: Rows that fit under the header.
        row_h: Height of one row.
        fonts: Text sizes and measuring fonts.
        time_format: ``"12"`` for AM/PM, anything else for 24-hour.

    Returns:
        One box per row, for the template.
    """
    boxes: list[dict[str, object]] = []
    if rows < 1:
        return boxes
    spans = sorted(week.all_day, key=lambda a: (a.first, -a.last))
    for i in range(7):
        items = [("", a.text) for a in spans if a.first <= i <= a.last]
        items += [
            (_fmt_hm(seg.label_sm, time_format), seg.text)
            for seg in sorted(week.timed[i], key=lambda s: s.sm)
        ]
        if len(items) > rows:
            extra = len(items) - rows + 1
            items = [*items[: rows - 1], ("", f"+{extra}")]
        bx, bw = geo.day_span(i, i)
        for k, (label, text) in enumerate(items):
            boxes.append(
                _fit_title(
                    fonts,
                    text,
                    bx,
                    top + k * row_h + 1,
                    bw,
                    row_h - 2,
                    label,
                    pad=0,
                    max_lines=1,
                )
            )
    return boxes


def _build_week_calendar_context(
    widget: WeekCalendarWidget,
    config: DisplayConfig,
) -> dict[str, object]:
    """Build the Jinja2 context for the week calendar widget.

    Shows the week containing today as one column per day, starting
    on the display's first weekday, with hours ``start_hour`` to
    ``end_hour`` on the vertical axis.  Events are positioned by
    start and end time; overlapping events share the column width.
    Events entirely before or after the grid are stacked as chips at
    the top or bottom of their day's column, and all-day events fill
    a strip under the day headers.  A widget too short to give the
    grid its minimum height switches, by size alone, to an agenda of
    one row per event under each day.  Events are read from
    ``states[entity]["attributes"]["week_events"]``, injected by
    ``_fetch_week_calendar_events()``.

    Args:
        widget: Widget config.  Recognised keys: ``entity``
            (calendar entity ID or list of IDs), ``title``,
            ``start_hour`` (default 8), ``end_hour`` (default 20),
            ``fonts`` (roles ``title``, ``day``, ``hour``, ``time``
            and ``event``), ``x``, ``y``, ``w``, ``h``.
        config: Display config with ``states``, ``language``,
            ``first_weekday``, ``time_format``, ``display_levels``,
            ``font_scale``, ``time_zone``, ``width`` and ``height``.

    Returns:
        Template context consumed by ``week_calendar.svg.j2``.
    """
    x = widget.get("x", 0)
    y = widget.get("y", 0)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", config["height"] - y)
    title: str = widget.get("title", "")
    time_format: str = config.get("time_format", "24")
    language: str = config.get("language", "en")
    display_levels: int = config.get("display_levels", 16)
    font_scale: float = config.get("font_scale", 1.0)

    start_hour = max(
        0, min(23, _hour_setting(widget, "start_hour", DEFAULT_START_HOUR))
    )
    end_hour = max(
        start_hour + 1,
        min(24, _hour_setting(widget, "end_hour", DEFAULT_END_HOUR)),
    )
    gs, ge = start_hour * 60, end_hour * 60

    # Week boundaries.
    now = _now(config)
    today = now.date()
    fw = _first_weekday_index(
        str(config.get("first_weekday", "language")), language
    )
    week_start = today - timedelta(days=(today.weekday() - fw) % 7)
    days: list[date] = [week_start + timedelta(days=i) for i in range(7)]

    states = config.get("states", {})
    raw_events: list[dict[str, Any]] = []
    for entity_id in week_calendar_entity_ids(widget):
        entity_state = states.get(entity_id)
        attrs = entity_state.get("attributes") if entity_state else None
        events = attrs.get("week_events") if isinstance(attrs, dict) else None
        if isinstance(events, list):
            raw_events.extend(events)

    # Font roles and vertical layout.
    title_font_sz, title_weight, content_y, content_h = _title_band(
        widget, title, svg_h, font_scale
    )
    header_h = max(18, min(40, round(content_h * 0.07)))
    fonts = _resolve_fonts(widget, round(header_h * 0.55), font_scale)
    # A larger day font makes the header row grow with it.
    header_h = max(header_h, fonts.day_size + 6)
    line_h = _ev_line_h(fonts.event_size)
    chip_h = line_h + 2
    # A lane is at least as tall as a chip row, so a bar always fits
    # one line of event text however small the day font is.
    lane_h = max(round(fonts.day_size * 1.3), chip_h)

    # The layout depends on the widget's size and settings only, never
    # on its events, so it does not change when events come and go.
    agenda = not _grid_fits(
        content_h, header_h, lane_h, chip_h, end_hour - start_hour
    )
    context: dict[str, object]
    if agenda:
        gutter_w = 0
        # The agenda has no time axis, so no event is cut off.
        week = _collect_week_events(raw_events, days, 0, 24 * 60)
        geo = _Geometry(gutter_w=gutter_w, col_w=svg_w / 7)
        grid_top = content_y + header_h
        grid_bottom = content_y + content_h
        context = {
            "hours": [],
            "all_day": [],
            "chips": [],
            "events": _agenda_boxes(
                week,
                geo,
                grid_top,
                (content_h - header_h) // chip_h,
                chip_h,
                fonts,
                time_format,
            ),
        }
    else:
        gutter_w = round(
            fonts.hour_size * (3.4 if time_format == "12" else 2.2)
        )
        week = _collect_week_events(raw_events, days, gs, ge)
        timed, before, after = week.timed, week.before, week.after

        all_day_strip = _place_all_day(week.all_day)
        strip_h = all_day_strip.lanes * lane_h
        top_chips = min(max(len(c) for c in before), _MAX_CHIPS)
        bottom_chips = min(max(len(c) for c in after), _MAX_CHIPS)

        grid_top = content_y + header_h + strip_h + top_chips * chip_h
        grid_bottom = max(
            grid_top + 1, content_y + content_h - bottom_chips * chip_h
        )
        layout = _Layout(
            content_y=content_y,
            content_h=content_h,
            header_h=header_h,
            lane_h=lane_h,
            chip_h=chip_h,
            strip_h=strip_h,
            top_chips=top_chips,
            bottom_chips=bottom_chips,
            grid_top=grid_top,
            grid_bottom=grid_bottom,
            grid_start=gs,
            px_per_min=(grid_bottom - grid_top) / (ge - gs),
            # One line alone in a lane; time plus one title line (two
            # lines) when sharing a column.
            single_px=line_h + 2,
            multi_px=2 * line_h + 2,
        )
        geo = _Geometry(gutter_w=gutter_w, col_w=(svg_w - gutter_w) / 7)
        context = {
            "hours": _hour_lines(
                start_hour, end_hour, layout, fonts, time_format
            ),
            "all_day": _all_day_boxes(all_day_strip, geo, layout, fonts),
            "chips": _chip_boxes(
                before, after, geo, layout, fonts, time_format
            ),
            "events": _event_boxes(timed, geo, layout, fonts, time_format),
        }

    return {
        "w": svg_w,
        "h": svg_h,
        "title": title,
        "title_font_sz": title_font_sz,
        "title_weight": title_weight,
        "content_y": content_y,
        "content_bottom": content_y + content_h,
        "header_h": header_h,
        **fonts.context(),
        "gutter_w": gutter_w,
        "grid_top": grid_top,
        "grid_bottom": grid_bottom,
        "col_xs": [geo.col_x(i) for i in range(8)],
        "headers": _day_headers(days, today, geo, fonts, language),
        "agenda": agenda,
        **context,
        "grid_line_color": _snap_gray(COLOR_LIGHT_GRAY, display_levels),
        "corner_r": max(3, round(line_h * 0.33)),
        **_color_context(),
    }

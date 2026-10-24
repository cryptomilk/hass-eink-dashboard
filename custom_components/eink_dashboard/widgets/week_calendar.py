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

import math
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from babel import Locale, UnknownLocaleError

from ..const import COLOR_LIGHT_GRAY, color_to_hex
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

DEFAULT_START_HOUR = 8
DEFAULT_END_HOUR = 20

# Caps that keep the grid usable when a week is crowded.  Extra
# all-day lanes are dropped; extra out-of-grid events collapse into
# a "+N" chip.
_MAX_ALL_DAY_LANES = 3
_MAX_CHIPS = 2

# Event, chip and all-day text uses a small set of fixed pixel sizes
# instead of scaling with the widget, which keeps small text legible.
# The start time always uses ``_EV_TIME_SIZE``; a title uses the largest
# of ``_EV_TITLE_SIZES`` whose text fits its box without being cut.
_EV_TIME_SIZE = 9
_EV_TITLE_SIZES = (14, 12)


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


def _week_calendar_entity_ids(widget: Mapping[str, object]) -> list[str]:
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


def _to_naive(raw: str) -> datetime:
    """Parse a calendar start/end string into a naive datetime.

    Args:
        raw: ``"YYYY-MM-DD"`` or an ISO 8601 datetime; any timezone
            offset is ignored (HA returns local wall-clock values).

    Returns:
        The parsed datetime; date-only strings give midnight.
    """
    from ..render import _parse_calendar_dt

    day, hm = _parse_calendar_dt(raw)
    if hm is None:
        return datetime.combine(day, time.min)
    return datetime.combine(day, time(hm[0], hm[1]))


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


def _assign_lanes(segs: list[dict[str, Any]]) -> None:
    """Assign side-by-side lanes to overlapping event segments.

    Segments are grouped into clusters of transitively overlapping
    events; within a cluster each gets the first free lane, and all
    share the cluster's lane count so they split the column evenly.

    Args:
        segs: Segments with ``sm`` (start) and ``end`` minute bounds,
            where ``end`` is the minute the drawn box reaches.  Sorted
            and annotated in place with ``lane`` and ``lanes``.
    """
    segs.sort(key=lambda s: (s["sm"], -s["end"]))
    clusters: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    cur_end = -1
    for seg in segs:
        if cur and seg["sm"] >= cur_end:
            clusters.append(cur)
            cur = []
            cur_end = -1
        cur.append(seg)
        cur_end = max(cur_end, seg["end"])
    if cur:
        clusters.append(cur)
    for cluster in clusters:
        lane_ends: list[int] = []
        for seg in cluster:
            for li, end in enumerate(lane_ends):
                if end <= seg["sm"]:
                    seg["lane"] = li
                    lane_ends[li] = seg["end"]
                    break
            else:
                seg["lane"] = len(lane_ends)
                lane_ends.append(seg["end"])
        for seg in cluster:
            seg["lanes"] = len(lane_ends)


def _collect_week_events(
    raw_events: list[dict[str, Any]],
    days: list[date],
    gs: int,
    ge: int,
) -> tuple[
    list[dict[str, Any]],
    list[list[dict[str, Any]]],
    list[list[dict[str, Any]]],
    list[list[dict[str, Any]]],
]:
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
        ``(all_day, timed, before, after)``.  ``all_day`` holds
        ``first``/``last`` day indices and ``text``; the other three
        hold one list of ``sm``/``em`` segments per day.
    """
    all_day: list[dict[str, Any]] = []
    timed: list[list[dict[str, Any]]] = [[] for _ in days]
    before: list[list[dict[str, Any]]] = [[] for _ in days]
    after: list[list[dict[str, Any]]] = [[] for _ in days]
    week_start = days[0]
    for ev in raw_events:
        summary = str(ev.get("summary", ""))
        start_raw, end_raw = str(ev.get("start", "")), str(ev.get("end", ""))
        start_dt, end_dt = _to_naive(start_raw), _to_naive(end_raw)
        if bool(ev.get("all_day")) or len(start_raw) == 10:
            # The end date of an all-day event is exclusive.
            last = max(start_dt.date(), end_dt.date() - timedelta(days=1))
            first_i = max(0, (start_dt.date() - week_start).days)
            last_i = min(len(days) - 1, (last - week_start).days)
            if first_i <= last_i:
                all_day.append(
                    {"first": first_i, "last": last_i, "text": summary}
                )
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
            seg = {"sm": sm, "em": em, "text": summary, "label_sm": label_sm}
            if em <= gs:
                before[i].append(seg)
            elif sm >= ge:
                after[i].append(seg)
            else:
                seg["sm"], seg["em"] = max(sm, gs), min(em, ge)
                timed[i].append(seg)
    return all_day, timed, before, after


def _place_all_day(all_day: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign all-day spans to horizontal lanes.

    Each span takes the first lane whose days are all free.  Spans
    that would need more than ``_MAX_ALL_DAY_LANES`` lanes are
    dropped.

    Args:
        all_day: Spans with ``first``/``last`` day indices.

    Returns:
        The placed spans, each with an added ``lane`` index.
    """
    lanes: list[list[bool]] = []
    placed: list[dict[str, Any]] = []
    for item in sorted(all_day, key=lambda a: (a["first"], -a["last"])):
        span = range(item["first"], item["last"] + 1)
        lane = next(
            (
                li
                for li, used in enumerate(lanes)
                if not any(used[d] for d in span)
            ),
            len(lanes),
        )
        if lane >= _MAX_ALL_DAY_LANES:
            continue
        if lane == len(lanes):
            lanes.append([False] * 7)
        for d in span:
            lanes[lane][d] = True
        placed.append({**item, "lane": lane})
    return placed


def _pack_day(
    segs: list[dict[str, Any]],
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
            seg["end"] = max(seg["em"], seg["sm"] + math.ceil(px / px_per_min))
        _assign_lanes(segs)
        now = {id(seg) for seg in segs if seg["lanes"] > 1}
        if now == multi:
            return
        multi = now


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
    a strip under the day headers.  Events are read from
    ``states[entity]["attributes"]["week_events"]``, injected by
    ``_fetch_week_calendar_events()``.

    Args:
        widget: Widget config.  Recognised keys: ``entity``
            (calendar entity ID or list of IDs), ``title``,
            ``start_hour`` (default 8), ``end_hour`` (default 20),
            ``x``, ``y``, ``w``, ``h``.
        config: Display config with ``states``, ``language``,
            ``first_weekday``, ``time_format``, ``display_levels``,
            ``time_zone``, ``width`` and ``height``.

    Returns:
        Template context consumed by ``week_calendar.svg.j2``.
    """
    from ..render import _load_font, _weekday_abbrev

    x = widget.get("x", 0)
    y = widget.get("y", 0)
    svg_w = _widget_dim(widget, "w", config["width"] - x)
    svg_h = _widget_dim(widget, "h", config["height"] - y)
    title: str = widget.get("title", "")
    time_format: str = config.get("time_format", "24")
    language: str = config.get("language", "en")
    display_levels: int = config.get("display_levels", 16)

    start_hour = max(
        0, min(23, int(widget.get("start_hour", DEFAULT_START_HOUR)))
    )
    end_hour = max(
        start_hour + 1, min(24, int(widget.get("end_hour", DEFAULT_END_HOUR)))
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

    # Sort events into all-day spans, in-grid segments and chips.
    states = config.get("states", {})
    raw_events: list[dict[str, Any]] = []
    for entity_id in _week_calendar_entity_ids(widget):
        entity_state = states.get(entity_id)
        if entity_state:
            raw_events.extend(
                entity_state.get("attributes", {}).get("week_events", [])
            )
    all_day, timed, before, after = _collect_week_events(
        raw_events, days, gs, ge
    )

    # Font sizes and vertical layout.
    title_font_sz, content_y, content_h = _title_layout(title, svg_h)
    header_h = max(18, min(40, round(content_h * 0.07)))
    day_font = round(header_h * 0.55)
    # Boxes are sized for the smallest title font; a roomier box may
    # still draw its title larger (see ``fit_title``).
    line_h = _ev_line_h(min(_EV_TITLE_SIZES))
    hour_font = max(8, round(day_font * 0.8))
    gutter_w = round(hour_font * (3.4 if time_format == "12" else 2.2))
    lane_h = round(day_font * 1.3)

    placed_all_day = _place_all_day(all_day)
    n_lanes = max((p["lane"] + 1 for p in placed_all_day), default=0)
    strip_h = n_lanes * lane_h
    chip_h = line_h + 2
    top_chips = min(max(len(c) for c in before), _MAX_CHIPS)
    bottom_chips = min(max(len(c) for c in after), _MAX_CHIPS)

    grid_top = content_y + header_h + strip_h + top_chips * chip_h
    grid_bottom = max(
        grid_top + 1, content_y + content_h - bottom_chips * chip_h
    )
    grid_h = grid_bottom - grid_top
    px_per_min = grid_h / (ge - gs)

    col_w_f = (svg_w - gutter_w) / 7

    def col_x(i: int) -> int:
        """Return the left pixel edge of day column ``i``."""
        return gutter_w + round(i * col_w_f)

    def edge_px(i: int) -> int:
        """Pixel column of the vertical gridline at column edge ``i``.

        The template draws each separator on the pixel column
        ``col_x(i)``, except the last one, which is pulled in by one
        pixel so it is not clipped at the widget's right edge.
        """
        return col_x(i) - (1 if i == 7 else 0)

    def day_span(first: int, last: int) -> tuple[int, int]:
        """Return ``(x, width)`` of a box over days ``first``..``last``.

        The box starts on a gridline and ends one pixel before the
        next, so it never merges into the gridline after it.
        """
        x0 = edge_px(first)
        return x0, edge_px(last + 1) - x0 - 1

    day_font_obj = _load_font(day_font, medium=True)
    time_font = _load_font(_EV_TIME_SIZE)
    title_fonts = {s: _load_font(s) for s in _EV_TITLE_SIZES}

    def fit_title(
        title: str,
        x0: int,
        y0: int,
        w: int,
        h: int,
        label: str = "",
        pad: int = 2,
        max_lines: int | None = None,
    ) -> dict[str, Any]:
        """Lay out ``title`` beside the start ``label`` in a box.

        Tries the title sizes from the largest down and keeps the
        first whose wrapped text is not cut; when every size cuts the
        text, the smallest one is used.  The label is drawn in the
        time font ahead of the first line, so the room it takes there
        is measured with that font.

        Args:
            title: Event title.
            x0: Left edge of the box.
            y0: Top edge of the box.
            w: Box width.
            h: Box height.
            label: Start time, or ``""`` for none.
            pad: Vertical room kept free inside the box.
            max_lines: Upper limit for the number of lines.

        Returns:
            The font size (``font_sz``) and the vertically centred
            ``lines`` for the template.
        """
        inner_w = w - 6
        time_w = time_font.getlength(label) if label else 0
        chosen = min(_EV_TITLE_SIZES)
        lines: list[str] = []
        for size in sorted(_EV_TITLE_SIZES, reverse=True):
            fits = (h - pad) // _ev_line_h(size)
            if max_lines is not None:
                fits = min(fits, max_lines)
            if inner_w <= 0 or fits < 1:
                continue
            gap = title_fonts[size].getlength(" ")
            chosen = size
            lines = _wrap_text(
                title,
                title_fonts[size],
                inner_w,
                fits,
                first_offset=time_w + gap if label else 0,
            )
            if " ".join(lines).split() == title.split():
                break
        # Even with no room for the title, the start time is drawn.
        lines = lines or [""]
        lh = _ev_line_h(chosen)
        top = y0 + (h - len(lines) * lh) // 2
        return {
            "font_sz": chosen,
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

    # Day headers.
    headers: list[dict[str, object]] = []
    for i, day in enumerate(days):
        w_i = col_x(i + 1) - col_x(i)
        label = _truncate_to_width(
            f"{_weekday_abbrev(day, language)} {day.day}",
            day_font_obj,
            w_i - 4,
        )
        headers.append(
            {
                "x": col_x(i),
                "w": w_i,
                "cx": col_x(i) + w_i // 2,
                "label": label,
                "is_today": day == today,
            }
        )

    # All-day bars.
    all_day_out: list[dict[str, Any]] = []
    for item in placed_all_day:
        bx, bw = day_span(item["first"], item["last"])
        by = content_y + header_h + item["lane"] * lane_h + 1
        all_day_out.append(
            {
                "x": bx,
                "y": by,
                "w": bw,
                "h": lane_h - 2,
                **fit_title(item["text"], bx, by, bw, lane_h - 2, max_lines=1),
            }
        )

    # Out-of-grid chips, stacked at the column's top/bottom.
    chips: list[dict[str, Any]] = []
    for i in range(7):
        bx, bw = day_span(i, i)
        for segs, count, base_y in (
            (before[i], top_chips, content_y + header_h + strip_h),
            (after[i], bottom_chips, grid_bottom),
        ):
            shown = sorted(segs, key=lambda s: s["sm"])
            if len(shown) > _MAX_CHIPS:
                extra = len(shown) - _MAX_CHIPS + 1
                shown = [*shown[: _MAX_CHIPS - 1], {"overflow": extra}]
            for k, seg in enumerate(shown[:count]):
                cy = base_y + k * chip_h + 1
                if "overflow" in seg:
                    label = ""
                    chip_text = f"+{seg['overflow']}"
                else:
                    label = _fmt_hm(seg["label_sm"], time_format)
                    chip_text = str(seg["text"])
                chips.append(
                    {
                        "x": bx,
                        "y": cy,
                        "w": bw,
                        "h": chip_h - 2,
                        **fit_title(
                            chip_text,
                            bx,
                            cy,
                            bw,
                            chip_h - 2,
                            label,
                            pad=0,
                            max_lines=1,
                        ),
                    }
                )

    # In-grid events.
    events: list[dict[str, Any]] = []
    # Minimum box heights: one line alone in a lane; time plus one
    # title line (two lines) when sharing a column.
    single_px = line_h + 2
    multi_px = 2 * line_h + 2
    for i in range(7):
        _pack_day(timed[i], px_per_min, single_px, multi_px)
        left, right = edge_px(i), edge_px(i + 1)
        for seg in timed[i]:
            # Lanes split the span between the gridlines.  Every box
            # ends one pixel before its right neighbour (the next lane
            # or the gridline), so boxes never merge into each other
            # or into the gridline.
            lanes_n = seg["lanes"]
            ex = left + round(seg["lane"] * (right - left) / lanes_n)
            ex_right = left + round(
                (seg["lane"] + 1) * (right - left) / lanes_n
            )
            ew = ex_right - ex - 1
            ey = grid_top + round((seg["sm"] - gs) * px_per_min)
            eh = max(
                multi_px if lanes_n > 1 else single_px,
                round((seg["em"] - seg["sm"]) * px_per_min) - 1,
            )
            ey = max(grid_top, min(ey, grid_bottom - eh))
            label = _fmt_hm(seg["label_sm"], time_format)
            events.append(
                {
                    "x": ex,
                    "y": ey,
                    "w": ew,
                    "h": eh,
                    **fit_title(seg["text"], ex, ey, ew, eh, label),
                }
            )

    # Hour gridlines; label every other hour when rows are tight.
    hour_px = 60 * px_per_min
    step = 1 if hour_px >= hour_font * 1.8 else 2
    hours: list[dict[str, object]] = []
    for hr in range(start_hour, end_hour + 1):
        hy = grid_top + round((hr * 60 - gs) * px_per_min)
        show = (hr - start_hour) % step == 0
        label = (
            _fmt_hm(hr * 60, time_format).replace(":00", "") if show else ""
        )
        # The baseline puts the digits (cap height about 0.71 em) a
        # couple of pixels under the line.  A label that would not fit
        # above the widget's bottom edge, as for the last line, is
        # dropped.
        label_y = hy + 3 + round(hour_font * 0.71)
        if label_y > content_y + content_h - 1:
            label = ""
        hours.append({"y": hy, "label": label, "label_y": label_y})

    return {
        "w": svg_w,
        "h": svg_h,
        "title": title,
        "title_font_sz": title_font_sz,
        "content_y": content_y,
        "content_bottom": content_y + content_h,
        "header_h": header_h,
        "day_font": day_font,
        "time_font_sz": _EV_TIME_SIZE,
        "hour_font": hour_font,
        "gutter_w": gutter_w,
        "grid_top": grid_top,
        "grid_bottom": grid_bottom,
        "col_xs": [col_x(i) for i in range(8)],
        "headers": headers,
        "hours": hours,
        "all_day": all_day_out,
        "chips": chips,
        "events": events,
        "grid_line_color": _snap_gray(COLOR_LIGHT_GRAY, display_levels),
        "corner_r": max(3, round(line_h * 0.33)),
        **_color_context(),
    }

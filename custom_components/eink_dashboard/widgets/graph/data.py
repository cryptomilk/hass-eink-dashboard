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

"""Graph widget data extraction, normalization, and aggregation."""

from __future__ import annotations

import datetime
import logging
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...const import Widget

_LOGGER = logging.getLogger(__name__)

# SVG stroke-dasharray patterns for multi-entity line styles.
# Index 0 (solid) has no dasharray; index 1 is dashed; index 2
# is dotted.  Empty string means attribute is omitted in template.
_DASH_PATTERNS: tuple[str, ...] = ("", "8,4", "2,4")

# Maximum data points kept from attribute sources.  Exceeding this
# triggers stride-based downsampling to cap render cost.  Typical
# forecasts (48-96 entries) are never affected.
_MAX_ATTRIBUTE_POINTS: int = 500


def _resolve_start_cutoff(
    start_time_str: str, now: datetime.datetime
) -> float | None:
    """Resolve a ``start_time`` config string to today's Unix timestamp.

    ``now`` is treated as local time: HA sets the system timezone to
    match its configured timezone, so local time is the correct frame
    of reference for server-side rendering (see the same assumption
    in ``conditions.py``'s time-condition evaluation).

    Args:
        start_time_str: Time-of-day string parseable by
            ``datetime.time.fromisoformat`` (e.g. ``"00:00"``), or
            empty to disable the fixed start time.
        now: Current local datetime; only its date is used, so tests
            can pass a fixed value for deterministic results.

    Returns:
        Unix timestamp for ``now``'s date at the given time, or
        ``None`` when ``start_time_str`` is empty or unparsable. If
        the resolved timestamp is still in the future relative to
        ``now``, it is returned as-is (the graph will show no data
        until that time is reached later today) and a warning is
        logged.
    """
    if not start_time_str:
        return None
    try:
        parsed = datetime.time.fromisoformat(start_time_str)
    except ValueError:
        _LOGGER.warning(
            "Graph widget 'start_time' %r is not a valid HH:MM time; "
            "ignoring it",
            start_time_str,
        )
        return None
    cutoff = datetime.datetime.combine(now.date(), parsed)
    if cutoff > now:
        _LOGGER.warning(
            "Graph widget 'start_time' %s has not occurred yet "
            "today; the graph will show no data until then",
            start_time_str,
        )
    return cutoff.timestamp()


def _extract_entity_points(
    desc: dict[str, object],
    states_dict: dict[str, Any],
    hours_to_show: int,
    points_per_hour: float,
    aggregate_func: str,
    start_cutoff: float | None = None,
) -> list[tuple[float, float]]:
    """Extract and aggregate history data for one entity descriptor.

    Reads the entity's raw history from ``states_dict``, filters to
    the ``hours_to_show`` time window (or ``start_cutoff`` when
    given), strips non-numeric entries, and buckets the result via
    ``_aggregate_history``.

    Args:
        desc: Entity descriptor dict from ``_normalize_entities()``.
        states_dict: States dict from the display config.
        hours_to_show: History window in hours.  Ignored when
            ``start_cutoff`` is not ``None``.
        points_per_hour: Target data density for bucketing.
        aggregate_func: Bucket reduction function name.
        start_cutoff: Optional fixed Unix timestamp cutoff (from the
            widget's ``start_time`` setting).  When given, only
            history entries at or after this timestamp are kept,
            replacing the rolling ``hours_to_show`` window entirely.

    Returns:
        Sorted oldest-to-newest list of ``(timestamp, value)`` pairs,
        or an empty list when fewer than two numeric entries remain
        after filtering.
    """
    eid = str(desc["entity"])
    state = states_dict.get(eid, {})
    raw_hist: list[dict[str, object]] = (
        list(state.get("history", [])) if isinstance(state, dict) else []
    )
    if raw_hist:
        if start_cutoff is not None:
            raw_hist = [
                e
                for e in raw_hist
                if math.isfinite(float(str(e.get("lu", 0))))
                and float(str(e.get("lu", 0))) >= start_cutoff
            ]
        else:
            t_latest = max(
                (
                    float(str(e.get("lu", 0)))
                    for e in raw_hist
                    if math.isfinite(float(str(e.get("lu", 0))))
                ),
                default=None,
            )
            if t_latest is None:
                raw_hist = []
            else:
                cutoff = t_latest - hours_to_show * 3600
                raw_hist = [
                    e
                    for e in raw_hist
                    if math.isfinite(float(str(e.get("lu", 0))))
                    and float(str(e.get("lu", 0))) > cutoff
                ]
    numeric: list[tuple[float, float]] = []
    for entry in raw_hist:
        s = entry.get("s", "")
        lu = entry.get("lu", 0.0)
        try:
            val = float(str(s))
            ts = float(str(lu))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(val) or not math.isfinite(ts):
            continue
        numeric.append((ts, val))
    if len(numeric) >= 2:
        return _aggregate_history(numeric, points_per_hour, aggregate_func)
    return []


def _parse_attribute_timestamp(value: object) -> float | None:
    """Parse a timestamp field from an attribute time-series entry.

    Accepts either a Unix timestamp (int/float, or a numeric string)
    or an ISO 8601 string (e.g. ``"2026-07-01T04:00:00+00:00"``).

    Args:
        value: Raw timestamp value from the attribute entry.

    Returns:
        Unix timestamp in seconds, or ``None`` if unparseable.
    """
    try:
        result = float(str(value))
        if not math.isfinite(result):
            return None
        return result
    except (ValueError, TypeError):
        pass
    try:
        return datetime.datetime.fromisoformat(str(value)).timestamp()
    except (ValueError, TypeError):
        return None


def _extract_attribute_points(
    desc: dict[str, object],
    states_dict: dict[str, Any],
) -> list[tuple[float, float]]:
    """Extract time-series data from an entity attribute.

    Reads a list of dicts from ``states_dict[entity]["attributes"]
    [attribute]``, pulling the timestamp and value out of each entry
    via the descriptor's configured key names. Used for forward-
    looking forecast data (solar production, energy prices, etc.)
    that is not available through the recorder.

    Args:
        desc: Entity descriptor dict from ``_normalize_entities()``,
            with ``attribute``, ``attribute_timestamp_key``, and
            ``attribute_value_key`` keys.
        states_dict: States dict from the display config.

    Returns:
        Sorted oldest-to-newest list of ``(timestamp, value)`` pairs,
        or an empty list when the attribute is missing or fewer than
        two numeric entries survive parsing.
    """
    eid = str(desc["entity"])
    attribute = str(desc.get("attribute", ""))
    ts_key = str(desc.get("attribute_timestamp_key", "timestamp"))
    value_key = str(desc.get("attribute_value_key", ""))
    state = states_dict.get(eid, {})
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    raw_list = attrs.get(attribute, []) if isinstance(attrs, dict) else []

    numeric: list[tuple[float, float]] = []
    if isinstance(raw_list, list):
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            ts = _parse_attribute_timestamp(entry.get(ts_key))
            if ts is None:
                continue
            try:
                val = float(str(entry.get(value_key)))
            except (ValueError, TypeError):
                continue
            if not math.isfinite(val):
                continue
            numeric.append((ts, val))

    if len(numeric) >= 2:
        numeric.sort(key=lambda p: p[0])
        if len(numeric) > _MAX_ATTRIBUTE_POINTS:
            stride = len(numeric) / _MAX_ATTRIBUTE_POINTS
            numeric = [
                numeric[round(i * stride)]
                for i in range(_MAX_ATTRIBUTE_POINTS)
            ]
        return numeric
    return []


def _normalize_entities(
    widget: Widget,
) -> list[dict[str, object]]:
    """Normalize widget config into a canonical entity descriptor list.

    Accepts either the single-entity format (``entity`` string key)
    or the multi-entity format (``entities`` list of dicts).  When
    both are present ``entities`` takes precedence.  Flat editor keys
    ``entity_2`` / ``entity_3`` are also handled for widgets saved by
    the editor UI.  These flat secondary-entity keys always default
    to ``data_source="history"`` because the editor does not expose
    attribute-source fields for them; use the ``entities`` list
    format to configure an attribute source on a secondary entity.

    Args:
        widget: Widget config dict.

    Returns:
        List of entity descriptor dicts, each with keys ``entity``
        (str), ``name`` (str, empty when not overridden), ``y_axis``
        (``"primary"`` or ``"secondary"``), ``line_style``
        (``"solid"``, ``"dashed"``, or ``"dotted"``), ``dash``
        (the SVG ``stroke-dasharray`` value, empty for solid),
        ``data_source`` (``"history"`` or ``"attribute"``),
        ``attribute`` (str, the attribute name holding a time-series
        list when ``data_source`` is ``"attribute"``),
        ``attribute_timestamp_key`` (str, default ``"timestamp"``),
        and ``attribute_value_key`` (str).  Maximum 3 entries.
        Returns an empty list when no entity source is found.
    """
    _STYLE_MAP: dict[str, int] = {"solid": 0, "dashed": 1, "dotted": 2}
    raw: list[dict[str, object]] = []

    entities_cfg = widget.get("entities")
    if isinstance(entities_cfg, list) and entities_cfg:
        raw.extend(
            item
            for item in entities_cfg
            if isinstance(item, dict) and item.get("entity")
        )
        if not raw:
            _LOGGER.warning(
                "Graph widget 'entities' list has no valid items "
                "(each item must be a dict with an 'entity' key); "
                "widget will render without a graph"
            )
    else:
        eid = str(widget.get("entity", ""))
        if eid:
            raw.append(
                {
                    "entity": eid,
                    "name": str(widget.get("name") or ""),
                    "data_source": str(widget.get("data_source", "history")),
                    "attribute": str(widget.get("attribute", "")),
                    "attribute_timestamp_key": str(
                        widget.get("attribute_timestamp_key", "timestamp")
                    ),
                    "attribute_value_key": str(
                        widget.get("attribute_value_key", "")
                    ),
                }
            )
        for suffix in ("_2", "_3"):
            eid2 = str(widget.get(f"entity{suffix}", ""))
            if eid2:
                raw.append(
                    {
                        "entity": eid2,
                        "name": str(widget.get(f"name{suffix}") or ""),
                        "y_axis": str(
                            widget.get(f"y_axis{suffix}", "primary")
                        ),
                    }
                )

    result: list[dict[str, object]] = []
    for i, item in enumerate(raw[:3]):
        style = str(item.get("line_style", ""))
        idx = _STYLE_MAP.get(style, i)
        idx = min(idx, 2)
        style_name = ("solid", "dashed", "dotted")[idx]
        result.append(
            {
                "entity": str(item.get("entity", "")),
                "name": str(item.get("name") or ""),
                "y_axis": str(item.get("y_axis", "primary")),
                "line_style": style_name,
                "dash": _DASH_PATTERNS[idx],
                "data_source": str(item.get("data_source", "history")),
                "attribute": str(item.get("attribute", "")),
                "attribute_timestamp_key": str(
                    item.get("attribute_timestamp_key", "timestamp")
                ),
                "attribute_value_key": str(
                    item.get("attribute_value_key", "")
                ),
            }
        )
    return result


def _aggregate_history(
    numeric: list[tuple[float, float]],
    points_per_hour: float,
    aggregate_func: str,
) -> list[tuple[float, float]]:
    """Bucket and aggregate numeric history into representative points.

    Groups (timestamp, value) pairs into fixed-width time buckets based
    on ``points_per_hour``, then reduces each bucket to a single value
    using ``aggregate_func``.  Falls back to ``numeric`` sorted
    oldest-to-newest only when no buckets are produced (degenerate
    input).

    Args:
        numeric: Numeric (timestamp, value) pairs to aggregate, in any
            order.
        points_per_hour: Target data density; bucket width in seconds
            is ``3600 / points_per_hour``.
        aggregate_func: Reduction function per bucket — one of
            ``"avg"``, ``"min"``, ``"max"``, ``"first"``, ``"last"``,
            ``"sum"``.

    Returns:
        Sorted oldest-to-newest list of (timestamp, value) pairs, one
        per non-empty bucket, or ``numeric`` sorted when bucketing
        produces no entries.
    """
    bucket_size = 3600.0 / max(points_per_hour, 0.001)
    t_max = max(t for t, _ in numeric)

    buckets: dict[int, list[tuple[float, float]]] = {}
    for t, v in numeric:
        idx = int((t_max - t) / bucket_size)
        if idx not in buckets:
            buckets[idx] = []
        buckets[idx].append((t, v))

    bucketed: list[tuple[float, float]] = []
    for idx, entries in buckets.items():
        # Right edge of the bucket so the newest bucket aligns with
        # t_max (the graph's right edge) without leaving dead space.
        t_repr = t_max - idx * bucket_size
        vals = [v for _, v in entries]
        if aggregate_func == "min":
            agg_val: float = min(vals)
        elif aggregate_func == "max":
            agg_val = max(vals)
        elif aggregate_func == "first":
            agg_val = min(entries, key=lambda e: e[0])[1]
        elif aggregate_func == "last":
            agg_val = max(entries, key=lambda e: e[0])[1]
        elif aggregate_func == "sum":
            agg_val = sum(vals)
        else:
            agg_val = sum(vals) / len(vals)
        bucketed.append((t_repr, agg_val))

    bucketed.sort(key=lambda p: p[0])
    if bucketed:
        return bucketed
    return sorted(numeric, key=lambda p: p[0])


def _y_bounds(
    values: list[float],
    lower_bound: object,
    upper_bound: object,
    min_bound_range: object,
) -> tuple[float, float]:
    """Compute Y-axis lower and upper bounds from data and config.

    Applies explicit bounds, a flat-line guard, and an optional minimum
    range expansion so the graph is never distorted by tiny fluctuations.

    Args:
        values: All numeric data values in the visible window.
        lower_bound: Optional explicit lower bound (widget config).
        upper_bound: Optional explicit upper bound (widget config).
        min_bound_range: Optional minimum Y-axis range; when the
            auto-computed range is smaller, both bounds are expanded
            symmetrically around the midpoint.

    Returns:
        ``(y_min, y_max)`` — guaranteed ``y_max > y_min``.
    """
    try:
        y_min = (
            float(str(lower_bound)) if lower_bound is not None else min(values)
        )
    except (ValueError, TypeError):
        y_min = min(values)
    try:
        y_max = (
            float(str(upper_bound)) if upper_bound is not None else max(values)
        )
    except (ValueError, TypeError):
        y_max = max(values)

    # Flat-line or inverted-bounds guard: ensure a positive range.
    if y_max <= y_min:
        y_max = y_min + 1.0

    # Enforce minimum Y-axis range to prevent over-amplifying small
    # fluctuations (e.g. temperature stable at ±0.1°C).
    if min_bound_range is not None:
        try:
            mbr = float(str(min_bound_range))
        except (ValueError, TypeError):
            mbr = 0.0
        if mbr > 0 and (y_max - y_min) < mbr:
            center = (y_max + y_min) / 2.0
            y_min = center - mbr / 2.0
            y_max = center + mbr / 2.0

    return y_min, y_max

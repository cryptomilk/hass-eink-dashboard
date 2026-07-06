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

"""Server-side evaluation of Lovelace visibility conditions.

Mirrors the logic in HA's frontend ``validate-condition.ts``.  Only
conditions that are meaningful at render time are implemented:
``state``, ``numeric_state``, ``time``, and the logical combinators
``and``, ``or``, ``not``.  Browser-only conditions (``screen``,
``view_columns``) and user/location conditions (``user``,
``location``) always return ``True`` because the required context is
not available during a server-side PNG render.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Maps Python's weekday() (0=Monday) to HA short names.
_WEEKDAY_MAP: dict[int, str] = {
    0: "mon",
    1: "tue",
    2: "wed",
    3: "thu",
    4: "fri",
    5: "sat",
    6: "sun",
}

# Entity ID pattern: word.word (matches HA's isValidEntityId regex).
_ENTITY_ID_RE = re.compile(r"^\w+\.\w+$")


def _get_now() -> datetime.datetime:
    """Return the current local datetime.

    Thin wrapper around ``datetime.datetime.now()`` so tests can patch
    it without patching the entire ``datetime`` module.

    Returns:
        Current local datetime.
    """
    return datetime.datetime.now()


def _is_entity_id(value: str) -> bool:
    """Return True if ``value`` looks like a HA entity ID.

    Args:
        value: String to test.

    Returns:
        True when the value matches ``domain.entity`` format.
    """
    return bool(_ENTITY_ID_RE.fullmatch(value))


def _resolve_entity_state(value: str, states: dict[str, Any]) -> str:
    """Resolve an entity ID to its state string, if ``value`` is one.

    When ``value`` is a valid entity ID present in ``states``, the
    entity's state string is returned.  Otherwise ``value`` itself is
    returned unchanged.

    Args:
        value: A literal string or entity ID.
        states: Entity states dict from ``DisplayConfig["states"]``.

    Returns:
        The entity's state string, or ``value`` unchanged.
    """
    if _is_entity_id(value) and value in states:
        return str(states[value]["state"])
    return value


def _check_state_condition(
    condition: dict[str, Any], states: dict[str, Any]
) -> bool:
    """Evaluate a state or legacy state condition.

    The entity's current state is looked up in ``states``; if the
    entity is absent its state is treated as ``"unknown"`` (matching
    HA's behaviour).

    When ``state`` is provided the condition passes if the entity state
    is one of the given values.  When ``state_not`` is provided the
    condition passes if the entity state is NOT one of the given
    values.  If neither is provided the condition always fails.

    Values that look like entity IDs are resolved to their states
    before comparison (indirect state reference).

    Args:
        condition: Condition dict (may or may not have a ``condition``
            key — legacy format without it is also accepted).
        states: Entity states dict from ``DisplayConfig["states"]``.

    Returns:
        True when the condition is satisfied.
    """
    entity_id = condition.get("entity")
    if entity_id and entity_id in states:
        entity_state = str(states[entity_id]["state"])
    else:
        entity_state = "unknown"

    raw_state = condition.get("state")
    raw_state_not = condition.get("state_not")

    if raw_state is None and raw_state_not is None:
        return False

    def _match_set(raw: object) -> set[str]:
        """Build a matching set from a raw state value or list."""
        items: list[str] = (
            [str(v) for v in raw] if isinstance(raw, list) else [str(raw)]
        )
        return {_resolve_entity_state(v, states) for v in items}

    if raw_state is not None:
        return entity_state in _match_set(raw_state)

    # state_not path
    return entity_state not in _match_set(raw_state_not)


def _check_numeric_state_condition(
    condition: dict[str, Any], states: dict[str, Any]
) -> bool:
    """Evaluate a numeric_state condition.

    The entity's state is converted to a float.  Non-numeric states
    return ``False``.  The ``above`` bound is a lower exclusive limit
    (state > above) and ``below`` is an upper exclusive limit
    (state < below).  Either or both bounds may be given.  If a bound
    value is an entity ID it is resolved to that entity's numeric state.

    Args:
        condition: Condition dict with optional ``entity``, ``above``,
            and ``below`` keys.
        states: Entity states dict from ``DisplayConfig["states"]``.

    Returns:
        True when the entity's numeric state satisfies all bounds.
    """
    entity_id = condition.get("entity")
    raw_state = states.get(entity_id, {}).get("state") if entity_id else None
    try:
        numeric_state = float(raw_state or "")
    except (TypeError, ValueError):
        return False

    def _resolve_bound(raw: str | int | float | None) -> float | None:
        if raw is None:
            return None
        if isinstance(raw, str):
            resolved = _resolve_entity_state(raw, states)
            try:
                return float(resolved)
            except ValueError:
                return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    above = _resolve_bound(condition.get("above"))
    below = _resolve_bound(condition.get("below"))

    if above is not None and numeric_state <= above:
        return False
    return not (below is not None and numeric_state >= below)


def _parse_time_string(time_str: str) -> datetime.time:
    """Parse an HH:MM or HH:MM:SS time string into a ``datetime.time``.

    Args:
        time_str: Time string in HH:MM or HH:MM:SS format.

    Returns:
        Parsed ``datetime.time`` object.

    Raises:
        ValueError: When the string does not match HH:MM or HH:MM:SS.
    """
    parts = time_str.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time string: {time_str!r}")
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) == 3 else 0
    return datetime.time(h, m, s)


def _check_time_condition(
    condition: dict[str, Any],
    _states: dict[str, Any],
) -> bool:
    """Evaluate a time condition.

    Checks whether the current local time falls within the given range
    and/or on one of the specified weekdays.  Both checks must pass
    when both are specified.

    Time range logic mirrors HA's ``checkTimeInRange()``
    (check_time.ts).  Midnight-crossing ranges (``after`` > ``before``)
    are supported: e.g. after=22:00, before=06:00 means the range
    spans 22:00–midnight and midnight–06:00.

    Python's ``datetime.now()`` returns local time.  HA sets the
    system timezone to match its configured timezone, so local time is
    the correct frame of reference for server-side rendering.

    Args:
        condition: Condition dict with optional ``after``, ``before``,
            and ``weekdays`` keys.
        _states: Unused; present for a uniform call signature.

    Returns:
        True when the current time satisfies the condition.
    """
    now = _get_now()

    weekdays = condition.get("weekdays")
    if weekdays:
        # Python weekday(): 0=Monday … 6=Sunday
        current_wd = _WEEKDAY_MAP[now.weekday()]
        if current_wd not in weekdays:
            return False

    after_str = condition.get("after")
    before_str = condition.get("before")

    if not after_str and not before_str:
        return True

    try:
        after = _parse_time_string(after_str) if after_str else None
        before = _parse_time_string(before_str) if before_str else None
    except ValueError:
        _LOGGER.warning(
            "check_conditions: invalid time string in condition %r",
            condition,
        )
        return False

    current = now.time().replace(microsecond=0)

    if after is not None and before is not None:
        if before < after:
            # Midnight-crossing range: matches before midnight OR
            # after midnight.
            return current >= after or current <= before
        return after <= current <= before

    if after is not None:
        return current >= after
    if before is not None:
        # before only — after is None, guaranteed by the
        # `not after_str and not before_str` guard above.
        return current <= before
    return True  # unreachable


def _check_condition(
    condition: dict[str, Any], states: dict[str, Any]
) -> bool:
    """Dispatch a single condition to its evaluator.

    Conditions without a ``condition`` key are treated as legacy state
    conditions.  Unknown condition types return ``True`` (pass-through)
    to avoid hiding widgets due to unrecognised future condition types.

    Args:
        condition: Single condition dict.
        states: Entity states dict from ``DisplayConfig["states"]``.

    Returns:
        True when the condition is satisfied.
    """
    ctype = condition.get("condition")

    if ctype is None:
        # Legacy format: no condition discriminant, treat as state.
        return _check_state_condition(condition, states)

    if ctype == "state":
        return _check_state_condition(condition, states)
    if ctype == "numeric_state":
        return _check_numeric_state_condition(condition, states)
    if ctype == "time":
        return _check_time_condition(condition, states)
    if ctype == "and":
        nested = condition.get("conditions") or []
        return check_conditions(nested, states)
    if ctype == "or":
        nested = condition.get("conditions") or []
        if not nested:
            return True
        return any(check_conditions([c], states) for c in nested)
    if ctype == "not":
        nested = condition.get("conditions") or []
        if not nested:
            return True
        return not check_conditions(nested, states)

    # screen, view_columns, user, location — no server-side context.
    return True


def check_conditions(
    conditions: list[dict[str, Any]],
    states: dict[str, Any],
) -> bool:
    """Return True only when all conditions are met.

    Implements the same top-level AND logic as HA's frontend
    ``checkConditionsMet()``.  An empty list always returns ``True``
    so that widgets without a ``visibility`` field are always rendered.

    Args:
        conditions: List of condition dicts from the widget's
            ``visibility`` field.
        states: Entity states dict from ``DisplayConfig["states"]``
            (keyed by entity ID, each value has ``"state"`` and
            ``"attributes"`` keys).

    Returns:
        True when every condition in the list is satisfied.
    """
    return all(_check_condition(c, states) for c in conditions)

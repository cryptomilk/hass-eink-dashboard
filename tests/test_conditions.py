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

"""Unit tests for conditions.py visibility condition evaluation."""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import patch

from custom_components.eink_dashboard.conditions import (
    check_conditions,
)

# ── Test helpers ──────────────────────────────────────────────────


def _states(**kwargs: str) -> dict[str, Any]:
    """Build a minimal states dict from entity_id=state pairs."""
    return {eid: {"state": s, "attributes": {}} for eid, s in kwargs.items()}


def _freeze(hour: int, minute: int, second: int = 0, weekday: int = 0) -> Any:
    """Return a context manager that freezes _get_now() to the given time.

    weekday: 0=Monday … 6=Sunday (Python convention).
    """
    # 2026-05-18 is a Monday (weekday=0); timedelta advances by day.
    base = datetime.datetime(2026, 5, 18, hour, minute, second)
    fixed = base + datetime.timedelta(days=weekday)
    return patch(
        "custom_components.eink_dashboard.conditions._get_now",
        return_value=fixed,
    )


# ── Top-level check_conditions ────────────────────────────────────


class TestCheckConditions:
    def test_empty_conditions_returns_true(self) -> None:
        # An empty list means "always visible".
        assert check_conditions([], {}) is True

    def test_all_conditions_met_returns_true(self) -> None:
        # All individual conditions pass → overall result is True.
        conditions = [
            {"condition": "state", "entity": "sensor.a", "state": "on"},
            {"condition": "state", "entity": "sensor.b", "state": "off"},
        ]
        states = _states(**{"sensor.a": "on", "sensor.b": "off"})
        assert check_conditions(conditions, states) is True

    def test_any_condition_unmet_returns_false(self) -> None:
        # One failing condition makes the whole list False (AND logic).
        conditions = [
            {"condition": "state", "entity": "sensor.a", "state": "on"},
            {"condition": "state", "entity": "sensor.b", "state": "on"},
        ]
        states = _states(**{"sensor.a": "on", "sensor.b": "off"})
        assert check_conditions(conditions, states) is False


# ── State condition ───────────────────────────────────────────────


class TestStateCondition:
    def test_state_matches_single_value(self) -> None:
        # Entity in the expected state → passes.
        c = [{"condition": "state", "entity": "light.x", "state": "on"}]
        assert check_conditions(c, _states(**{"light.x": "on"})) is True

    def test_state_does_not_match(self) -> None:
        # Entity not in the expected state → fails.
        c = [{"condition": "state", "entity": "light.x", "state": "on"}]
        assert check_conditions(c, _states(**{"light.x": "off"})) is False

    def test_state_matches_one_of_multiple_values(self) -> None:
        # Entity state is one of a list → passes.
        c = [{"condition": "state", "entity": "s.x", "state": ["on", "home"]}]
        assert check_conditions(c, _states(**{"s.x": "home"})) is True

    def test_state_matches_none_of_multiple_values(self) -> None:
        # Entity state is not in the list → fails.
        c = [{"condition": "state", "entity": "s.x", "state": ["on", "home"]}]
        assert check_conditions(c, _states(**{"s.x": "away"})) is False

    def test_state_not_excludes_value(self) -> None:
        # state_not: entity IS in the excluded list → fails.
        c = [{"condition": "state", "entity": "s.x", "state_not": "off"}]
        assert check_conditions(c, _states(**{"s.x": "off"})) is False

    def test_state_not_does_not_exclude(self) -> None:
        # state_not: entity NOT in the excluded list → passes.
        c = [{"condition": "state", "entity": "s.x", "state_not": "off"}]
        assert check_conditions(c, _states(**{"s.x": "on"})) is True

    def test_entity_not_found_uses_unknown(self) -> None:
        # Missing entity is treated as state "unknown".
        c = [
            {
                "condition": "state",
                "entity": "sensor.missing",
                "state": "unknown",
            }
        ]
        assert check_conditions(c, {}) is True

    def test_entity_not_found_fails_when_not_unknown(self) -> None:
        # Missing entity treated as "unknown"; won't match "on".
        c = [{"condition": "state", "entity": "sensor.missing", "state": "on"}]
        assert check_conditions(c, {}) is False

    def test_value_is_entity_id_resolved(self) -> None:
        # When the expected value is an entity ID, it's resolved
        # to that entity's state before comparison.
        c = [
            {
                "condition": "state",
                "entity": "sensor.a",
                "state": "sensor.b",  # entity ID as reference value
            }
        ]
        # sensor.a == sensor.b's state == "on" → True
        states = _states(**{"sensor.a": "on", "sensor.b": "on"})
        assert check_conditions(c, states) is True

    def test_no_state_or_state_not_returns_false(self) -> None:
        # Condition without state or state_not is always false.
        c = [{"condition": "state", "entity": "sensor.x"}]
        assert check_conditions(c, _states(**{"sensor.x": "on"})) is False

    def test_legacy_condition_without_condition_key(self) -> None:
        # Legacy format: no "condition" key, treated as state condition.
        c = [{"entity": "sensor.x", "state": "active"}]
        assert check_conditions(c, _states(**{"sensor.x": "active"})) is True


# ── Numeric state condition ───────────────────────────────────────


class TestNumericStateCondition:
    def test_above_threshold(self) -> None:
        # State 15 is above threshold 10 → passes.
        c = [{"condition": "numeric_state", "entity": "s.x", "above": 10}]
        assert check_conditions(c, _states(**{"s.x": "15"})) is True

    def test_below_threshold(self) -> None:
        # State 5 is below threshold 10 → passes.
        c = [{"condition": "numeric_state", "entity": "s.x", "below": 10}]
        assert check_conditions(c, _states(**{"s.x": "5"})) is True

    def test_within_both_bounds(self) -> None:
        # State 50 is between 20 (above) and 80 (below) → passes.
        c = [
            {
                "condition": "numeric_state",
                "entity": "s.x",
                "above": 20,
                "below": 80,
            }
        ]
        assert check_conditions(c, _states(**{"s.x": "50"})) is True

    def test_equal_to_above_bound_is_exclusive(self) -> None:
        # State == above → fails (exclusive bound).
        c = [{"condition": "numeric_state", "entity": "s.x", "above": 10}]
        assert check_conditions(c, _states(**{"s.x": "10"})) is False

    def test_equal_to_below_bound_is_exclusive(self) -> None:
        # State == below → fails (exclusive bound).
        c = [{"condition": "numeric_state", "entity": "s.x", "below": 10}]
        assert check_conditions(c, _states(**{"s.x": "10"})) is False

    def test_non_numeric_state_returns_false(self) -> None:
        # Non-numeric entity state → always false.
        c = [{"condition": "numeric_state", "entity": "s.x", "above": 0}]
        assert check_conditions(c, _states(**{"s.x": "unavailable"})) is False

    def test_bound_is_entity_id(self) -> None:
        # above/below may be entity IDs, resolved to their numeric state.
        c = [
            {
                "condition": "numeric_state",
                "entity": "s.x",
                "above": "s.threshold",
            }
        ]
        # s.x=15 > s.threshold=10 → passes.
        states = _states(**{"s.x": "15", "s.threshold": "10"})
        assert check_conditions(c, states) is True

    def test_only_above_provided(self) -> None:
        # Only above bound — state must be strictly greater.
        c = [{"condition": "numeric_state", "entity": "s.x", "above": 5}]
        assert check_conditions(c, _states(**{"s.x": "4.9"})) is False
        assert check_conditions(c, _states(**{"s.x": "5.1"})) is True

    def test_only_below_provided(self) -> None:
        # Only below bound — state must be strictly less.
        c = [{"condition": "numeric_state", "entity": "s.x", "below": 5}]
        assert check_conditions(c, _states(**{"s.x": "5.1"})) is False
        assert check_conditions(c, _states(**{"s.x": "4.9"})) is True


# ── Time condition ────────────────────────────────────────────────


class TestTimeCondition:
    def test_within_time_range(self) -> None:
        # Current time 14:30 is within 09:00–18:00 → passes.
        c = [{"condition": "time", "after": "09:00", "before": "18:00"}]
        with _freeze(14, 30):
            assert check_conditions(c, {}) is True

    def test_outside_time_range(self) -> None:
        # Current time 07:00 is before 09:00 → fails.
        c = [{"condition": "time", "after": "09:00", "before": "18:00"}]
        with _freeze(7, 0):
            assert check_conditions(c, {}) is False

    def test_midnight_crossing_before_midnight(self) -> None:
        # Range 22:00–06:00; current time 23:00 → passes.
        c = [{"condition": "time", "after": "22:00", "before": "06:00"}]
        with _freeze(23, 0):
            assert check_conditions(c, {}) is True

    def test_midnight_crossing_after_midnight(self) -> None:
        # Range 22:00–06:00; current time 04:00 → passes.
        c = [{"condition": "time", "after": "22:00", "before": "06:00"}]
        with _freeze(4, 0):
            assert check_conditions(c, {}) is True

    def test_midnight_crossing_outside(self) -> None:
        # Range 22:00–06:00; current time 12:00 → fails.
        c = [{"condition": "time", "after": "22:00", "before": "06:00"}]
        with _freeze(12, 0):
            assert check_conditions(c, {}) is False

    def test_weekday_matches(self) -> None:
        # Monday (weekday=0) is in the allowed list → passes.
        c = [{"condition": "time", "weekdays": ["mon", "tue"]}]
        with _freeze(12, 0, weekday=0):  # Monday
            assert check_conditions(c, {}) is True

    def test_weekday_does_not_match(self) -> None:
        # Wednesday (weekday=2) is not in ["mon", "tue"] → fails.
        c = [{"condition": "time", "weekdays": ["mon", "tue"]}]
        with _freeze(12, 0, weekday=2):  # Wednesday
            assert check_conditions(c, {}) is False

    def test_only_weekdays_no_time(self) -> None:
        # weekdays-only condition: any time on that day passes.
        c = [{"condition": "time", "weekdays": ["fri"]}]
        with _freeze(3, 0, weekday=4):  # Friday, very early
            assert check_conditions(c, {}) is True

    def test_only_time_no_weekdays(self) -> None:
        # time-only condition: any day at the right time passes.
        c = [{"condition": "time", "after": "08:00", "before": "09:00"}]
        with _freeze(8, 30, weekday=6):  # Sunday
            assert check_conditions(c, {}) is True

    def test_hh_mm_ss_format_supported(self) -> None:
        # HH:MM:SS time strings are accepted and compared correctly.
        c = [{"condition": "time", "after": "14:00:00", "before": "14:00:30"}]
        with _freeze(14, 0, 15):  # 14:00:15 is within range
            assert check_conditions(c, {}) is True

    def test_after_boundary_is_inclusive(self) -> None:
        # current == after boundary → passes (inclusive lower bound).
        c = [{"condition": "time", "after": "09:00", "before": "18:00"}]
        with _freeze(9, 0):
            assert check_conditions(c, {}) is True

    def test_before_boundary_is_inclusive(self) -> None:
        # current == before boundary → passes (inclusive upper bound).
        c = [{"condition": "time", "after": "09:00", "before": "18:00"}]
        with _freeze(18, 0):
            assert check_conditions(c, {}) is True

    def test_after_only_passes(self) -> None:
        # after-only: current after the threshold → passes.
        c = [{"condition": "time", "after": "09:00"}]
        with _freeze(10, 0):
            assert check_conditions(c, {}) is True

    def test_after_only_fails(self) -> None:
        # after-only: current before the threshold → fails.
        c = [{"condition": "time", "after": "09:00"}]
        with _freeze(8, 0):
            assert check_conditions(c, {}) is False

    def test_after_only_at_boundary(self) -> None:
        # after-only: current == threshold → passes (inclusive).
        c = [{"condition": "time", "after": "09:00"}]
        with _freeze(9, 0):
            assert check_conditions(c, {}) is True

    def test_before_only_passes(self) -> None:
        # before-only: current before the threshold → passes.
        c = [{"condition": "time", "before": "18:00"}]
        with _freeze(12, 0):
            assert check_conditions(c, {}) is True

    def test_before_only_fails(self) -> None:
        # before-only: current after the threshold → fails.
        c = [{"condition": "time", "before": "18:00"}]
        with _freeze(20, 0):
            assert check_conditions(c, {}) is False

    def test_before_only_at_boundary(self) -> None:
        # before-only: current == threshold → passes (inclusive).
        c = [{"condition": "time", "before": "18:00"}]
        with _freeze(18, 0):
            assert check_conditions(c, {}) is True


# ── Logical combinators ───────────────────────────────────────────


class TestLogicalCombinators:
    def _on(self) -> dict[str, Any]:
        return {"condition": "state", "entity": "s.x", "state": "on"}

    def _off(self) -> dict[str, Any]:
        return {"condition": "state", "entity": "s.x", "state": "off"}

    def _states(self) -> dict[str, Any]:
        return _states(**{"s.x": "on"})

    def test_and_all_pass(self) -> None:
        # and: both nested conditions pass → True.
        c = [{"condition": "and", "conditions": [self._on(), self._on()]}]
        assert check_conditions(c, self._states()) is True

    def test_and_one_fails(self) -> None:
        # and: one nested condition fails → False.
        c = [{"condition": "and", "conditions": [self._on(), self._off()]}]
        assert check_conditions(c, self._states()) is False

    def test_and_empty_conditions(self) -> None:
        # and with empty list → True.
        c = [{"condition": "and", "conditions": []}]
        assert check_conditions(c, {}) is True

    def test_or_one_passes(self) -> None:
        # or: one of the nested conditions passes → True.
        c = [{"condition": "or", "conditions": [self._off(), self._on()]}]
        assert check_conditions(c, self._states()) is True

    def test_or_none_pass(self) -> None:
        # or: no nested condition passes → False.
        c = [{"condition": "or", "conditions": [self._off(), self._off()]}]
        assert check_conditions(c, self._states()) is False

    def test_or_empty_conditions(self) -> None:
        # or with empty list → True.
        c = [{"condition": "or", "conditions": []}]
        assert check_conditions(c, {}) is True

    def test_not_none_pass(self) -> None:
        # not: no nested condition passes (all fail) → True.
        c = [{"condition": "not", "conditions": [self._off()]}]
        assert check_conditions(c, self._states()) is True

    def test_not_one_passes(self) -> None:
        # not: a nested condition passes → False.
        c = [{"condition": "not", "conditions": [self._on()]}]
        assert check_conditions(c, self._states()) is False

    def test_not_empty_conditions(self) -> None:
        # not with empty list → True.
        c = [{"condition": "not", "conditions": []}]
        assert check_conditions(c, {}) is True


# ── Always-pass conditions (browser/user-context types) ──────────


class TestAlwaysPassConditions:
    def test_screen_condition_passes(self) -> None:
        # screen conditions always pass server-side.
        c = [{"condition": "screen", "media_query": "(min-width: 768px)"}]
        assert check_conditions(c, {}) is True

    def test_view_columns_condition_passes(self) -> None:
        # view_columns conditions always pass server-side.
        c = [{"condition": "view_columns", "min": 2}]
        assert check_conditions(c, {}) is True

    def test_user_condition_passes(self) -> None:
        # user conditions always pass server-side.
        c = [{"condition": "user", "users": ["abc123"]}]
        assert check_conditions(c, {}) is True

    def test_location_condition_passes(self) -> None:
        # location conditions always pass server-side.
        c = [{"condition": "location", "locations": ["home"]}]
        assert check_conditions(c, {}) is True

    def test_unknown_condition_type_passes(self) -> None:
        # Unknown condition types pass through (forward-compat).
        c = [{"condition": "future_type", "some_key": "value"}]
        assert check_conditions(c, {}) is True


# ── Nested / compound conditions ──────────────────────────────────


class TestNestedConditions:
    def test_and_containing_or(self) -> None:
        # and wrapping or: outer AND passes only when inner OR passes.
        states = _states(**{"s.a": "on", "s.b": "off"})
        # Inner OR: sensor.a==on OR sensor.b==on → True (a is on)
        inner_or = {
            "condition": "or",
            "conditions": [
                {"condition": "state", "entity": "s.a", "state": "on"},
                {"condition": "state", "entity": "s.b", "state": "on"},
            ],
        }
        c = [{"condition": "and", "conditions": [inner_or]}]
        assert check_conditions(c, states) is True

    def test_not_containing_state(self) -> None:
        # not wrapping state: inverts the state check.
        states = _states(**{"s.x": "unavailable"})
        inner = {"condition": "state", "entity": "s.x", "state": "on"}
        c = [{"condition": "not", "conditions": [inner]}]
        assert check_conditions(c, states) is True

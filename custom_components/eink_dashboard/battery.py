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

"""Battery level resolution helper."""

from __future__ import annotations

from typing import Any


def build_entity_state(hass: Any, entity_id: str) -> dict[str, Any] | None:
    """Return a state snapshot dict for a single HA entity.

    Args:
        hass: The Home Assistant instance.
        entity_id: The entity to look up.

    Returns:
        Dict with ``"state"`` and ``"attributes"`` keys, or None when
        the entity does not exist in the state machine.
    """
    ha_state = hass.states.get(entity_id)
    if ha_state is None:
        return None
    return {
        "state": ha_state.state,
        "attributes": dict(ha_state.attributes),
    }


def resolve_battery_level(
    battery_entity_id: str | None,
    states: dict[str, Any],
    battery_sensor: Any,
) -> tuple[int | None, bool]:
    """Return (level, is_charging) from the best available source.

    Priority: configured entity ID > internal battery sensor.
    Returns (None, False) when no battery data is available.

    Args:
        battery_entity_id: Entity ID configured in entry options, or
            None when not configured.
        states: Snapshot of all HA entity states, keyed by entity_id.
            Each value is a dict with ``"state"`` and ``"attributes"``.
        battery_sensor: The internal EinkDashboardBatterySensor, or
            None when not registered.

    Returns:
        Tuple of (level, is_charging) where level is an integer
        0–100 or None, and is_charging is a bool.
    """
    if battery_entity_id:
        entity_state = states.get(battery_entity_id)
        if entity_state:
            raw = entity_state.get("state")
            try:
                attrs = entity_state.get("attributes", {})
                is_charging = bool(attrs.get("is_charging", False))
                return (
                    max(0, min(100, int(float(raw)))),
                    is_charging,
                )
            except (ValueError, TypeError):
                pass
    if battery_sensor is not None:
        level = battery_sensor.native_value
        if level is not None:
            is_charging = battery_sensor.extra_state_attributes.get(
                "is_charging", False
            )
            return level, is_charging
    return None, False

"""Tests for the MDI device_class → icon name resolver."""

from __future__ import annotations

from custom_components.eink_dashboard.render import (
    _device_class_icon,
)

_EXPECTED_SENSOR_ICONS: dict[str, str] = {
    "temperature": "thermometer",
    "humidity": "water-percent",
    "pressure": "gauge",
    "battery": "battery",
    "power": "flash",
    "energy": "lightning-bolt",
    "gas": "fire",
    "illuminance": "brightness-5",
    "moisture": "water-alert",
    "apparent_power": "flash-auto",
    "aqi": "air-filter",
    "carbon_dioxide": "molecule-co2",
    "carbon_monoxide": "molecule-co",
    "current": "current-ac",
    "data_size": "database",
    "distance": "ruler",
    "duration": "timer-outline",
    "frequency": "sine-wave",
    "irradiance": "sun-wireless",
    "monetary": "currency-usd",
    "nitrogen_dioxide": "smog",
    "ozone": "weather-dust",
    "ph": "ph",
    "pm25": "blur",
    "signal_strength": "signal",
    "speed": "speedometer",
    "voltage": "flash",
    "volume": "cup-water",
    "water": "water",
    "weight": "weight",
    "wind_speed": "weather-windy",
}

# (off_icon, on_icon)
_EXPECTED_BINARY_ICONS: dict[str, tuple[str, str]] = {
    "door": ("door-closed", "door-open"),
    "window": ("window-closed-variant", "window-open-variant"),
    "garage_door": ("garage", "garage-open"),
    "lock": ("lock", "lock-open"),
    "motion": ("motion-sensor-off", "motion-sensor"),
    "smoke": (
        "smoke-detector-variant",
        "smoke-detector-variant-alert",
    ),
    "battery": ("battery", "battery-alert"),
    "battery_charging": ("battery-charging", "battery-charging"),
    "cold": ("thermometer", "snowflake"),
    "connectivity": ("wifi-off", "wifi"),
    "heat": ("thermometer", "fire-alert"),
    "light": ("brightness-5", "brightness-7"),
    "occupancy": ("home-outline", "home-account"),
    "opening": ("square-outline", "square"),
    "plug": ("power-plug-off", "power-plug"),
    "presence": ("account-outline", "account"),
    "problem": ("check-circle", "alert-circle"),
    "running": ("stop-circle", "play-circle"),
    "safety": ("shield-check", "shield-alert"),
    "sound": ("volume-off", "volume-high"),
    "tamper": ("shield-check", "shield-alert"),
    "update": ("package", "package-up"),
    "vibration": ("crop-portrait", "vibrate"),
}


class TestDeviceClassIcon:
    """Unit tests for _device_class_icon(attrs, state, domain).

    These tests verify the mapping logic only — no rendering,
    no PIL, no image assertions.
    """

    # ── Sensor device classes ─────────────────────────────────────

    def test_sensor_temperature(self) -> None:
        # Numeric state should use the sensor map.
        assert (
            _device_class_icon({"device_class": "temperature"}, "22.1")
            == "thermometer"
        )

    def test_sensor_humidity(self) -> None:
        # Verifies a second sensor device_class resolves correctly.
        assert (
            _device_class_icon({"device_class": "humidity"}, "58")
            == "water-percent"
        )

    def test_sensor_battery_numeric_state(self) -> None:
        # Regular sensor.battery has a numeric state, not on/off.
        assert (
            _device_class_icon({"device_class": "battery"}, "75") == "battery"
        )

    def test_all_sensor_device_classes_mapped(self) -> None:
        # Every sensor device_class maps to the exact expected icon.
        for dc, expected in _EXPECTED_SENSOR_ICONS.items():
            result = _device_class_icon({"device_class": dc}, "42")
            assert result == expected, (
                f"sensor device_class {dc!r}: "
                f"expected {expected!r}, got {result!r}"
            )

    # ── Binary sensor device classes ──────────────────────────────

    def test_binary_door_off(self) -> None:
        # Closed door (off state) shows the closed-door icon.
        assert (
            _device_class_icon(
                {"device_class": "door"}, "off", domain="binary_sensor"
            )
            == "door-closed"
        )

    def test_binary_door_on(self) -> None:
        # Open door (on state) shows the open-door icon.
        assert (
            _device_class_icon(
                {"device_class": "door"}, "on", domain="binary_sensor"
            )
            == "door-open"
        )

    def test_binary_window_off(self) -> None:
        # Closed window shows window-closed-variant.
        assert (
            _device_class_icon(
                {"device_class": "window"}, "off", domain="binary_sensor"
            )
            == "window-closed-variant"
        )

    def test_binary_window_on(self) -> None:
        # Open window shows window-open-variant.
        assert (
            _device_class_icon(
                {"device_class": "window"}, "on", domain="binary_sensor"
            )
            == "window-open-variant"
        )

    def test_binary_lock_off(self) -> None:
        # Locked (off) shows the plain lock icon.
        assert (
            _device_class_icon(
                {"device_class": "lock"}, "off", domain="binary_sensor"
            )
            == "lock"
        )

    def test_binary_lock_on(self) -> None:
        # Unlocked (on) shows lock-open.
        assert (
            _device_class_icon(
                {"device_class": "lock"}, "on", domain="binary_sensor"
            )
            == "lock-open"
        )

    def test_binary_motion_off(self) -> None:
        # No motion (off) shows motion-sensor-off.
        assert (
            _device_class_icon(
                {"device_class": "motion"}, "off", domain="binary_sensor"
            )
            == "motion-sensor-off"
        )

    def test_binary_motion_on(self) -> None:
        # Motion detected (on) shows motion-sensor.
        assert (
            _device_class_icon(
                {"device_class": "motion"}, "on", domain="binary_sensor"
            )
            == "motion-sensor"
        )

    def test_all_binary_device_classes_mapped(self) -> None:
        # Every binary sensor device_class maps to the exact expected icons.
        for dc, (exp_off, exp_on) in _EXPECTED_BINARY_ICONS.items():
            off = _device_class_icon(
                {"device_class": dc}, "off", domain="binary_sensor"
            )
            on = _device_class_icon(
                {"device_class": dc}, "on", domain="binary_sensor"
            )
            assert off == exp_off, (
                f"binary {dc!r} off: expected {exp_off!r}, got {off!r}"
            )
            assert on == exp_on, (
                f"binary {dc!r} on: expected {exp_on!r}, got {on!r}"
            )

    # ── Fallback behaviour ────────────────────────────────────────

    def test_unknown_device_class_returns_none(self) -> None:
        # Unrecognised device_class → None (caller uses letter).
        assert _device_class_icon({"device_class": "unicorn"}, "42") is None

    def test_missing_device_class_returns_none(self) -> None:
        # Attrs without a device_class key → None.
        assert _device_class_icon({}, "22.1") is None

    def test_empty_device_class_returns_none(self) -> None:
        # Explicit empty string device_class → None.
        assert (
            _device_class_icon(
                {"device_class": ""}, "on", domain="binary_sensor"
            )
            is None
        )

    # ── Overlap disambiguation ────────────────────────────────────

    def test_battery_binary_off(self) -> None:
        # binary_sensor.battery in off state → battery icon.
        assert (
            _device_class_icon(
                {"device_class": "battery"}, "off", domain="binary_sensor"
            )
            == "battery"
        )

    def test_battery_binary_on(self) -> None:
        # binary_sensor.battery in on (problem) state → alert icon.
        assert (
            _device_class_icon(
                {"device_class": "battery"}, "on", domain="binary_sensor"
            )
            == "battery-alert"
        )

    def test_non_binary_domain_ignores_binary_map(self) -> None:
        # A switch or sensor with device_class="battery" and state="on"
        # must use the sensor map, not the binary map.
        for dom in ("sensor", "switch", "input_boolean", ""):
            result = _device_class_icon(
                {"device_class": "battery"}, "on", domain=dom
            )
            assert result == "battery", (
                f"domain={dom!r}: expected 'battery', got {result!r}"
            )

    # ── Edge cases ────────────────────────────────────────────────

    def test_battery_charging_same_icon_both_states(
        self,
    ) -> None:
        # battery_charging shows the same icon regardless of state.
        off = _device_class_icon(
            {"device_class": "battery_charging"}, "off", domain="binary_sensor"
        )
        on = _device_class_icon(
            {"device_class": "battery_charging"}, "on", domain="binary_sensor"
        )
        assert off == "battery-charging"
        assert on == "battery-charging"

    def test_safety_and_tamper_share_icon_pair(self) -> None:
        # Both safety and tamper map to shield-check (off) / shield-alert (on).
        for dc in ("safety", "tamper"):
            assert (
                _device_class_icon(
                    {"device_class": dc}, "off", domain="binary_sensor"
                )
                == "shield-check"
            )
            assert (
                _device_class_icon(
                    {"device_class": dc}, "on", domain="binary_sensor"
                )
                == "shield-alert"
            )

    def test_sensor_class_with_on_state_falls_through_to_sensor_map(
        self,
    ) -> None:
        # Without domain="binary_sensor", the sensor map is always used.
        assert (
            _device_class_icon({"device_class": "temperature"}, "on")
            == "thermometer"
        )

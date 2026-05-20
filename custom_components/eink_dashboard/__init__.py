"""E-ink dashboard Home Assistant integration setup."""

from __future__ import annotations

import datetime as dt
import json
import logging
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .battery import resolve_battery_level
from .const import (
    DEFAULT_GRAYSCALE_LEVELS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DEVICE_PRESETS,
    DOMAIN,
    DateFormat,
    NumberFormat,
    TimeFormat,
    WidgetType,
)
from .http import EinkLayoutView, EinkPublicImageView
from .store import EinkDashboardStore
from .svg_render import render_widget_svg

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["image", "sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _area_name(hass: HomeAssistant, area_id: str | None) -> str | None:
    """Return the area name for the given area_id, or None."""
    if not area_id:
        return None
    area_reg = ar.async_get(hass)
    area_entry = area_reg.async_get_area(area_id)
    return area_entry.name if area_entry else None


def _register_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or update the HA device registry entry for this config entry."""
    preset = DEVICE_PRESETS.get(entry.options.get("device_model", "custom"))
    device_reg = dr.async_get(hass)
    device_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=(
            preset.manufacturer if preset and preset.manufacturer else None
        ),
        model=preset.label if preset else "Custom",
        suggested_area=_area_name(hass, entry.options.get("area_id")),
    )


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Re-register the device when options are updated."""
    _register_device(hass, entry)


async def _async_get_locale(
    hass: HomeAssistant,
    options: Mapping[str, Any] | None = None,
) -> tuple[str, str, str, str, str]:
    """Return locale settings for server-side rendering.

    Returns a 5-tuple
    ``(number_format, language, first_weekday, date_format,
    time_format)``.

    Reads the owner's frontend locale preferences (the ``language``
    key stored via ``frontend/set_user_data``) and falls back to
    ``hass.config.language`` when the owner cannot be determined or
    when the frontend component is not available.  Per-device
    overrides in ``options`` (``locale_number_format``,
    ``locale_language``, ``locale_first_weekday``,
    ``locale_date_format``, ``locale_time_format``) take precedence
    over the owner's preferences when non-empty.

    Args:
        hass: Home Assistant instance.
        options: Config entry options dict, used to apply per-device
            locale overrides.  ``None`` means no overrides.

    Returns:
        A 5-tuple suitable for passing into a ``DisplayConfig`` dict:
        ``number_format`` (a ``NumberFormat`` string value),
        ``language`` (BCP 47 tag),
        ``first_weekday`` (e.g. ``"monday"``),
        ``date_format`` (a ``DateFormat`` string value),
        ``time_format`` (a ``TimeFormat`` string value).
    """
    fallback_language = hass.config.language
    number_format: str = NumberFormat.LANGUAGE
    language: str = fallback_language
    first_weekday: str = "language"
    date_format: str = DateFormat.LANGUAGE
    time_format: str = TimeFormat.LANGUAGE
    try:
        from homeassistant.components.frontend.storage import (
            async_user_store,
        )
    except ImportError:
        pass
    else:
        try:
            owner = await hass.auth.async_get_owner()
            if owner is not None:
                store = await async_user_store(hass, owner.id)
                locale_data = store.data.get("language")
                if isinstance(locale_data, dict):
                    number_format = str(
                        locale_data.get("number_format", NumberFormat.LANGUAGE)
                    )
                    language = str(
                        locale_data.get("language", fallback_language)
                    )
                    first_weekday = str(
                        locale_data.get("first_weekday", "language")
                    )
                    date_format = str(
                        locale_data.get("date_format", DateFormat.LANGUAGE)
                    )
                    time_format = str(
                        locale_data.get("time_format", TimeFormat.LANGUAGE)
                    )
        except (AttributeError, KeyError, TypeError) as exc:
            # Owner lookup or store access failed — log and fall back.
            _LOGGER.debug(
                "Could not read owner locale from frontend storage: %s",
                exc,
            )
    # Apply per-device overrides from the config entry options.
    # Reject unrecognised values so stale or hand-edited configs
    # cannot inject garbage into the renderer.
    _valid_fw = {
        "language",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    if options is not None:
        override_nf = options.get("locale_number_format", "")
        if override_nf:
            if override_nf in NumberFormat._value2member_map_:
                number_format = override_nf
            else:
                _LOGGER.warning(
                    "Ignoring unrecognised locale_number_format %r",
                    override_nf,
                )
        override_lang = options.get("locale_language", "")
        if override_lang:
            language = override_lang
        override_fw = options.get("locale_first_weekday", "")
        if override_fw:
            if override_fw in _valid_fw:
                first_weekday = override_fw
            else:
                _LOGGER.warning(
                    "Ignoring unrecognised locale_first_weekday %r",
                    override_fw,
                )
        override_df = options.get("locale_date_format", "")
        if override_df:
            if override_df in DateFormat._value2member_map_:
                date_format = override_df
            else:
                _LOGGER.warning(
                    "Ignoring unrecognised locale_date_format %r",
                    override_df,
                )
        override_tf = options.get("locale_time_format", "")
        if override_tf:
            if override_tf in TimeFormat._value2member_map_:
                time_format = override_tf
            else:
                _LOGGER.warning(
                    "Ignoring unrecognised locale_time_format %r",
                    override_tf,
                )
    return number_format, language, first_weekday, date_format, time_format


async def _build_display_config(
    hass: HomeAssistant, entry_id: str
) -> dict[str, Any]:
    """Build a DisplayConfig for rendering a widget preview.

    Snapshots current HA entity states, reads display dimensions from
    the config entry options, and reads the owner's locale preferences
    via :func:`_async_get_locale`.  Caller must ensure
    ``entry_id`` exists in ``hass.data[DOMAIN]``.

    Args:
        hass: Home Assistant instance.
        entry_id: Config entry ID present in ``hass.data[DOMAIN]``.

    Returns:
        Dict with ``width``, ``height``, ``grayscale_levels``,
        ``number_format``, ``language``, ``first_weekday``,
        ``date_format``, ``time_format``, ``states``, and (when
        battery data is available) ``device_battery_level`` and
        ``device_battery_charging`` keys suitable for
        ``render_widget_svg()``.
    """
    entry_data = hass.data[DOMAIN][entry_id]
    entry = entry_data["entry"]
    states: dict[str, Any] = {}
    for state in hass.states.async_all():
        states[state.entity_id] = {
            "state": state.state,
            # Shallow copy: _fetch_forecasts adds a "forecast"
            # key to this dict.  A shallow copy is sufficient
            # because it only assigns new keys, never mutates
            # existing nested values.
            "attributes": dict(state.attributes),
        }
    (
        number_format,
        language,
        first_weekday,
        date_format,
        time_format,
    ) = await _async_get_locale(hass, entry.options)
    config: dict[str, Any] = {
        "width": entry.options.get("width", DEFAULT_WIDTH),
        "height": entry.options.get("height", DEFAULT_HEIGHT),
        "grayscale_levels": entry.options.get(
            "grayscale_levels", DEFAULT_GRAYSCALE_LEVELS
        ),
        "number_format": number_format,
        "language": language,
        "first_weekday": first_weekday,
        "date_format": date_format,
        "time_format": time_format,
        "states": states,
    }
    level, is_charging = resolve_battery_level(
        entry.options.get("battery_entity_id"),
        states,
        entry_data.get("battery_sensor"),
    )
    if level is not None:
        config["device_battery_level"] = level
        config["device_battery_charging"] = is_charging
    return config


async def _fetch_forecasts(
    hass: HomeAssistant,
    widgets: list[dict[str, Any]],
    states: dict[str, Any],
) -> None:
    """Fetch daily forecasts for weather widgets and inject into states.

    Calls the ``weather.get_forecasts`` service for each unique
    weather entity referenced by ``widgets`` and writes the forecast
    list into ``states[entity_id]["attributes"]["forecast"]`` so
    ``render_widget_svg`` sees the same data as the scheduled image
    render path.

    Args:
        hass: Home Assistant instance.
        widgets: Widget dicts to scan for weather entity IDs.
        states: Mutable states dict built by ``_build_display_config``.
    """
    weather_entities: set[str] = set()
    for w in widgets:
        # WidgetType is a StrEnum: wire-format strings compare equal.
        if w.get("type") == WidgetType.WEATHER:
            eid = w.get("entity", "")
            if eid and eid in states:
                weather_entities.add(eid)

    for entity_id in weather_entities:
        try:
            result = await hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
            if result is None:
                continue
            entity_data = result.get(entity_id)
            forecast = (
                entity_data.get("forecast")
                if isinstance(entity_data, dict)
                else None
            ) or []
            states[entity_id]["attributes"]["forecast"] = forecast
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not fetch forecast for %s", entity_id)


async def _fetch_history(
    hass: HomeAssistant,
    widgets: list[dict[str, Any]],
    states: dict[str, Any],
) -> None:
    """Fetch state history for sensor widgets and inject into states.

    Scans ``widgets`` for sensor widgets with ``graph == "line"``,
    then fetches compressed state history from the recorder component
    for each referenced entity and writes it into
    ``states[entity_id]["history"]`` as a list of
    ``{"s": state_str, "lu": unix_timestamp_float}`` dicts so
    ``_build_sensor_context`` can compute sparkline coordinates
    without real-time HA access.

    Silently skips if the recorder is not loaded or if fetching fails
    for any individual entity.  Tests inject history data directly
    into the states dict and never call this function.

    Args:
        hass: Home Assistant instance.
        widgets: Widget dicts to scan for sensor widgets needing
            history data.
        states: Mutable states dict built by ``_build_display_config``.
    """
    # Build a map of entity_id → maximum hours_to_show across all
    # sensor widgets referencing that entity.
    sensor_entities: dict[str, int] = {}
    for w in widgets:
        if w.get("type") == WidgetType.SENSOR and w.get("graph") == "line":
            eid = w.get("entity", "")
            if eid and eid in states:
                try:
                    hours = max(1, int(w.get("hours_to_show", 24)))
                except (ValueError, TypeError):
                    hours = 24
                if hours > sensor_entities.get(eid, 0):
                    sensor_entities[eid] = hours

    if not sensor_entities:
        return

    if "recorder" not in hass.config.components:
        _LOGGER.debug("_fetch_history: recorder not loaded, skipping history")
        return

    from homeassistant.components.recorder.history import (
        get_significant_states,
    )

    now = dt.datetime.now(dt.UTC)
    for entity_id, hours in sensor_entities.items():
        start_time = now - timedelta(hours=hours)
        try:
            result = await hass.async_add_executor_job(
                partial(
                    get_significant_states,
                    hass,
                    start_time,
                    end_time=None,
                    entity_ids=[entity_id],
                    filters=None,
                    include_start_time_state=True,
                    significant_changes_only=True,
                    minimal_response=False,
                    no_attributes=True,
                    compressed_state_format=True,
                ),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "_fetch_history: could not fetch history for %s",
                entity_id,
            )
            continue

        raw = cast("list[dict[str, Any]]", result.get(entity_id, []))
        entries: list[dict[str, object]] = [
            {"s": str(e.get("s", "")), "lu": float(e.get("lu", 0.0))}
            for e in raw
        ]

        if entries:
            states[entity_id]["history"] = entries


@websocket_api.websocket_command(
    {
        vol.Required("type"): "eink_dashboard/render_widget",
        vol.Required("entry_id"): str,
        vol.Required("widget_index"): vol.All(int, vol.Range(min=0)),
        vol.Optional("widget"): dict,
    }
)
@websocket_api.async_response
async def ws_render_widget(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the SVG string for a single widget.

    When ``widget`` is provided it is used as-is instead of the
    stored widget at ``widget_index``.  This allows the frontend
    editor to preview unsaved local changes.

    Args:
        hass: Home Assistant instance.
        connection: Active WebSocket connection.
        msg: Validated message dict containing ``entry_id`` (str),
            ``widget_index`` (int), and an optional ``widget``
            (dict) override.
    """
    entry_id = msg["entry_id"]
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if entry_data is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            f"Config entry not found: {entry_id}",
        )
        return

    widget = msg.get("widget")
    if widget is None:
        widgets = list(entry_data["widgets"])
        idx = msg["widget_index"]
        if idx < 0 or idx >= len(widgets):
            connection.send_error(
                msg["id"],
                websocket_api.ERR_NOT_FOUND,
                f"Widget index out of range: {idx}",
            )
            return
        widget = widgets[idx]
    config = await _build_display_config(hass, entry_id)
    await _fetch_forecasts(hass, [widget], config["states"])
    await _fetch_history(hass, [widget], config["states"])
    try:
        svg = await hass.async_add_executor_job(
            render_widget_svg, widget, config
        )
    except KeyError as exc:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            f"Unknown widget type: {exc}",
        )
        return
    except Exception as exc:  # noqa: BLE001
        connection.send_error(
            msg["id"],
            websocket_api.ERR_UNKNOWN_ERROR,
            str(exc),
        )
        return
    connection.send_result(msg["id"], {"svg": svg})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "eink_dashboard/render_widgets",
        vol.Required("entry_id"): str,
        vol.Optional("widgets"): [dict],
    }
)
@websocket_api.async_response
async def ws_render_widgets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return SVG strings for all widgets in one call.

    Renders every widget for the given config entry and returns
    their SVG strings as a list in widget-list order.  Use this
    command on initial load or full refresh to avoid N sequential
    round-trips.

    When ``widgets`` is provided it overrides the stored widget
    list.  This allows the frontend editor to preview unsaved
    local changes without saving first.

    Args:
        hass: Home Assistant instance.
        connection: Active WebSocket connection.
        msg: Validated message dict containing ``entry_id`` (str)
            and an optional ``widgets`` (list) override.
    """
    entry_id = msg["entry_id"]
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if entry_data is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            f"Config entry not found: {entry_id}",
        )
        return

    widgets = msg.get("widgets") or list(entry_data["widgets"])
    config = await _build_display_config(hass, entry_id)
    await _fetch_forecasts(hass, widgets, config["states"])
    await _fetch_history(hass, widgets, config["states"])

    # Render all widgets in a single executor job: render_widget_svg
    # is CPU-bound (Jinja2 + resvg), and one thread per widget would
    # add overhead without parallelism gains under the GIL.  If any
    # widget fails the entire batch errors out -- partial results are
    # not returned.
    def _render_all() -> list[str]:
        return [render_widget_svg(w, config) for w in widgets]

    try:
        svgs = await hass.async_add_executor_job(_render_all)
    except KeyError as exc:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            f"Unknown widget type: {exc}",
        )
        return
    except Exception as exc:  # noqa: BLE001
        connection.send_error(
            msg["id"],
            websocket_api.ERR_UNKNOWN_ERROR,
            str(exc),
        )
        return
    connection.send_result(msg["id"], {"svgs": svgs})


_FRONTEND_DIR = Path(__file__).parent / "frontend"
_FONTS_DIR = Path(__file__).parent / "fonts"
_ICONS_DIR = Path(__file__).parent / "icons"
_MANIFEST = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)
_VERSION = _MANIFEST["version"]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register HTTP views and static paths for the integration."""
    _LOGGER.debug("async_setup: registering HTTP views and static paths")
    hass.data.setdefault(DOMAIN, {})

    hass.http.register_view(EinkPublicImageView())
    hass.http.register_view(EinkLayoutView())
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/eink_dashboard/frontend",
                str(_FRONTEND_DIR),
                False,
            ),
            StaticPathConfig(
                "/eink_dashboard/fonts",
                str(_FONTS_DIR),
                True,
            ),
            StaticPathConfig(
                "/eink_dashboard/icons",
                str(_ICONS_DIR),
                True,
            ),
        ]
    )
    add_extra_js_url(
        hass,
        f"/eink_dashboard/frontend/eink-dashboard-card.js?v={_VERSION}",
    )
    websocket_api.async_register_command(hass, ws_render_widget)
    websocket_api.async_register_command(hass, ws_render_widgets)
    _LOGGER.debug("async_setup: complete")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load persisted widgets and forward setup to the image platform."""
    _LOGGER.debug(
        "async_setup_entry: entry_id=%s title=%r", entry.entry_id, entry.title
    )
    store = EinkDashboardStore(hass, entry.entry_id)
    widgets = await store.async_load()
    _LOGGER.debug(
        "async_setup_entry: loaded %d widgets for %s",
        len(widgets),
        entry.entry_id,
    )
    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "widgets": widgets,
        "entry": entry,
    }

    _register_device(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug(
        "async_setup_entry: platforms forwarded for %s", entry.entry_id
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and clean up runtime data for the entry."""
    _LOGGER.debug("async_unload_entry: %s", entry.entry_id)
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    _LOGGER.debug("async_unload_entry: %s ok=%s", entry.entry_id, ok)
    return ok

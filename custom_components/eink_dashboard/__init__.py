"""E-ink dashboard Home Assistant integration setup."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DEVICE_PRESETS, DOMAIN
from .http import EinkLayoutView, EinkPublicImageView
from .store import EinkDashboardStore

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

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .http import EinkLayoutView, EinkPublicImageView
from .store import EinkDashboardStore

PLATFORMS = ["image"]

_FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    hass.data.setdefault(DOMAIN, {})

    hass.http.register_view(EinkPublicImageView())
    hass.http.register_view(EinkLayoutView())
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/eink_dashboard/frontend",
                str(_FRONTEND_DIR),
                False,
            )
        ]
    )
    add_extra_js_url(
        hass,
        "/eink_dashboard/frontend/eink-dashboard-card.js",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = EinkDashboardStore(hass, entry.entry_id)
    widgets = await store.async_load()
    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "widgets": widgets,
        "entry": entry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok

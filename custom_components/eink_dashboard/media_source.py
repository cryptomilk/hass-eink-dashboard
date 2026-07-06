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

"""Expose e-ink dashboard images as a Media Source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.media_player import (
    BrowseError,
    MediaClass,
)
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_media_source(
    hass: HomeAssistant,
) -> EinkDashboardMediaSource:
    """Return the e-ink dashboard media source."""
    return EinkDashboardMediaSource(hass)


class EinkDashboardMediaSource(MediaSource):
    """Provide rendered dashboard PNGs as browsable media."""

    name = "E-Ink Dashboard"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(
        self,
        item: MediaSourceItem,
    ) -> PlayMedia:
        """Resolve a dashboard entry to its image proxy URL.

        Args:
            item: Parsed media source item whose identifier
                is a config entry ID.

        Returns:
            PlayMedia pointing at the authenticated image
            proxy endpoint.

        Raises:
            Unresolvable: If the entry ID is not found.
        """
        entry_data = self.hass.data.get(DOMAIN, {}).get(
            item.identifier,
        )
        if not isinstance(entry_data, dict) or "entry" not in entry_data:
            raise Unresolvable(f"Unknown dashboard: {item.identifier}")
        entity = entry_data["entity"]
        return PlayMedia(
            f"/api/image_proxy/{entity.entity_id}",
            "image/png",
        )

    async def async_browse_media(
        self,
        item: MediaSourceItem,
    ) -> BrowseMediaSource:
        """List configured dashboards as browsable media items.

        When called with an empty identifier, returns a root
        node whose children are the individual dashboards.
        Each child is directly playable (can_play=True)
        and cannot be expanded further.

        Args:
            item: Parsed media source item.  Only the root
                (empty identifier) is supported.

        Returns:
            Root BrowseMediaSource with one child per
            dashboard config entry.

        Raises:
            BrowseError: If a non-root identifier is requested.
        """
        if item.identifier:
            raise BrowseError(f"Unknown item: {item.identifier}")

        entries = self.hass.data.get(DOMAIN, {})
        children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=entry_id,
                media_class=MediaClass.IMAGE,
                media_content_type="image/png",
                title=entry_data["entry"].title,
                thumbnail=f"/api/image_proxy/{entry_data['entity'].entity_id}",
                can_play=True,
                can_expand=False,
            )
            for entry_id, entry_data in entries.items()
            if isinstance(entry_data, dict) and "entry" in entry_data
        ]

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.APP,
            media_content_type="",
            title="E-Ink Dashboard",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.IMAGE,
            children=children,
        )

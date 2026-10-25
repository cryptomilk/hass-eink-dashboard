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

"""Tests for the e-ink dashboard Media Source platform."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from homeassistant.components.media_player import BrowseError
from homeassistant.components.media_source import (
    MediaSourceItem,
    Unresolvable,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eink_dashboard.const import DOMAIN
from custom_components.eink_dashboard.data import EinkDashboardRuntimeData
from custom_components.eink_dashboard.media_source import (
    EinkDashboardMediaSource,
    async_get_media_source,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _make_item(
    hass: HomeAssistant,
    identifier: str = "",
) -> MediaSourceItem:
    """Build a MediaSourceItem with the given identifier."""
    return MediaSourceItem(hass, DOMAIN, identifier, None)


async def test_async_get_media_source(hass: HomeAssistant) -> None:
    # Factory returns an EinkDashboardMediaSource instance.
    source = await async_get_media_source(hass)
    assert isinstance(source, EinkDashboardMediaSource)
    assert source.name == "E-Ink Dashboard"


async def test_browse_root_lists_entries(hass: HomeAssistant) -> None:
    # Root browse returns one child per dashboard entry.
    entry_a = MockConfigEntry(domain=DOMAIN, entry_id="aaa", title="Kitchen")
    entry_a.add_to_hass(hass)
    entity_a = MagicMock()
    entity_a.entity_id = "image.kitchen"
    entry_a.runtime_data = EinkDashboardRuntimeData(
        store=MagicMock(), widgets=[], entity=entity_a
    )
    entry_b = MockConfigEntry(domain=DOMAIN, entry_id="bbb", title="Office")
    entry_b.add_to_hass(hass)
    entity_b = MagicMock()
    entity_b.entity_id = "image.office"
    entry_b.runtime_data = EinkDashboardRuntimeData(
        store=MagicMock(), widgets=[], entity=entity_b
    )
    source = EinkDashboardMediaSource(hass)

    result = await source.async_browse_media(
        _make_item(hass),
    )

    assert result.can_expand is True
    assert result.can_play is False
    assert result.title == "E-Ink Dashboard"
    assert len(result.children) == 2

    ids = {c.identifier for c in result.children}
    assert ids == {"aaa", "bbb"}
    for child in result.children:
        assert child.can_play is True
        assert child.can_expand is False
        assert child.media_content_type == "image/png"
        expected_entity = (
            "image.kitchen" if child.identifier == "aaa" else "image.office"
        )
        assert child.thumbnail == (f"/api/image_proxy/{expected_entity}")


async def test_browse_root_empty_when_no_entries(
    hass: HomeAssistant,
) -> None:
    # Root browse returns an empty children list with no entries.
    source = EinkDashboardMediaSource(hass)

    result = await source.async_browse_media(
        _make_item(hass),
    )
    assert result.children == []


async def test_browse_non_root_raises(hass: HomeAssistant) -> None:
    # Browsing a non-root identifier raises BrowseError.
    source = EinkDashboardMediaSource(hass)

    with pytest.raises(BrowseError):
        await source.async_browse_media(
            _make_item(hass, "some_id"),
        )


async def test_resolve_valid_entry(hass: HomeAssistant) -> None:
    # Resolving a known entry returns the image proxy URL.
    entry = MockConfigEntry(domain=DOMAIN, entry_id="abc123", title="Kitchen")
    entry.add_to_hass(hass)
    entity = MagicMock()
    entity.entity_id = "image.kitchen"
    entry.runtime_data = EinkDashboardRuntimeData(
        store=MagicMock(), widgets=[], entity=entity
    )
    source = EinkDashboardMediaSource(hass)

    result = await source.async_resolve_media(
        _make_item(hass, "abc123"),
    )
    assert result.url == "/api/image_proxy/image.kitchen"
    assert result.mime_type == "image/png"


async def test_resolve_unknown_entry_raises(hass: HomeAssistant) -> None:
    # Resolving an unknown entry raises Unresolvable.
    source = EinkDashboardMediaSource(hass)

    with pytest.raises(Unresolvable):
        await source.async_resolve_media(
            _make_item(hass, "nonexistent"),
        )

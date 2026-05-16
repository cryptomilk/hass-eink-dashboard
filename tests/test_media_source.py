"""Tests for the e-ink dashboard Media Source platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.media_player import BrowseError
from homeassistant.components.media_source import (
    MediaSourceItem,
    Unresolvable,
)

from custom_components.eink_dashboard.media_source import (
    EinkDashboardMediaSource,
    async_get_media_source,
)

DOMAIN = "eink_dashboard"


def _make_hass(
    entries: dict | None = None,
) -> MagicMock:
    """Build a minimal stub hass with the given entry data."""
    hass = MagicMock()
    hass.data = {DOMAIN: entries or {}}
    return hass


def _make_item(
    hass: object,
    identifier: str = "",
) -> MediaSourceItem:
    """Build a MediaSourceItem with the given identifier."""
    return MediaSourceItem(hass, DOMAIN, identifier)


@pytest.mark.asyncio
async def test_async_get_media_source() -> None:
    """Factory returns an EinkDashboardMediaSource instance."""
    hass = _make_hass()
    source = await async_get_media_source(hass)
    assert isinstance(source, EinkDashboardMediaSource)
    assert source.name == "E-Ink Dashboard"


@pytest.mark.asyncio
async def test_browse_root_lists_entries() -> None:
    """Root browse returns one child per dashboard entry."""
    entry_a = MagicMock()
    entry_a.title = "Kitchen"
    entity_a = MagicMock()
    entity_a.entity_id = "image.kitchen"
    entry_b = MagicMock()
    entry_b.title = "Office"
    entity_b = MagicMock()
    entity_b.entity_id = "image.office"
    entries = {
        "aaa": {
            "entry": entry_a,
            "entity": entity_a,
            "widgets": [],
        },
        "bbb": {
            "entry": entry_b,
            "entity": entity_b,
            "widgets": [],
        },
    }
    hass = _make_hass(entries)
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


@pytest.mark.asyncio
async def test_browse_root_empty_when_no_entries() -> None:
    """Root browse returns an empty children list with no entries."""
    hass = _make_hass({})
    source = EinkDashboardMediaSource(hass)

    result = await source.async_browse_media(
        _make_item(hass),
    )
    assert result.children == []


@pytest.mark.asyncio
async def test_browse_non_root_raises() -> None:
    """Browsing a non-root identifier raises BrowseError."""
    hass = _make_hass()
    source = EinkDashboardMediaSource(hass)

    with pytest.raises(BrowseError):
        await source.async_browse_media(
            _make_item(hass, "some_id"),
        )


@pytest.mark.asyncio
async def test_resolve_valid_entry() -> None:
    """Resolving a known entry returns the image proxy URL."""
    entry = MagicMock()
    entry.title = "Kitchen"
    entity = MagicMock()
    entity.entity_id = "image.kitchen"
    entries = {
        "abc123": {
            "entry": entry,
            "entity": entity,
            "widgets": [],
        },
    }
    hass = _make_hass(entries)
    source = EinkDashboardMediaSource(hass)

    result = await source.async_resolve_media(
        _make_item(hass, "abc123"),
    )
    assert result.url == "/api/image_proxy/image.kitchen"
    assert result.mime_type == "image/png"


@pytest.mark.asyncio
async def test_resolve_unknown_entry_raises() -> None:
    """Resolving an unknown entry raises Unresolvable."""
    hass = _make_hass({})
    source = EinkDashboardMediaSource(hass)

    with pytest.raises(Unresolvable):
        await source.async_resolve_media(
            _make_item(hass, "nonexistent"),
        )

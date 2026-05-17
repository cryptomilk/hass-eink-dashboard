"""HTTP push of dashboard images to webhook URLs."""

from __future__ import annotations

import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)


async def async_push_image(
    session: aiohttp.ClientSession,
    url: str,
    image_bytes: bytes,
) -> None:
    """POST raw PNG bytes to a webhook URL, logging failures
    without raising.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.post(
            url,
            data=image_bytes,
            headers={"Content-Type": "image/png"},
            timeout=timeout,
        ) as resp:
            if resp.status >= 400:
                _LOGGER.warning(
                    "Webhook push to %s returned HTTP %s",
                    url,
                    resp.status,
                )
    except TimeoutError:
        _LOGGER.warning("Webhook push to %s timed out", url)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Webhook push to %s failed", url, exc_info=True)

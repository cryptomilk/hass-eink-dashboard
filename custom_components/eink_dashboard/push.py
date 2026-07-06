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

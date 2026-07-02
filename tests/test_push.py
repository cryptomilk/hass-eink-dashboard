from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from custom_components.eink_dashboard.push import async_push_image

_URL = "https://trmnl.com/api/custom_plugins/test"
_PNG = b"\x89PNG\r\n"


def _make_session(
    status: int = 200,
    *,
    raise_on_post: Exception | None = None,
) -> MagicMock:
    """Build a minimal aiohttp.ClientSession mock.

    Returns a MagicMock whose .post() returns an async-context-manager
    response with the given status, or raises raise_on_post if supplied.
    """
    resp = MagicMock()
    resp.status = status
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock(spec=aiohttp.ClientSession)
    if raise_on_post is not None:
        session.post = MagicMock(side_effect=raise_on_post)
    else:
        session.post = MagicMock(return_value=resp)
    return session


class TestAsyncPushImage:
    async def test_posts_bytes_with_content_type(self) -> None:
        # PNG bytes are sent as the request body with the correct MIME type.
        session = _make_session()
        await async_push_image(session, _URL, _PNG)

        session.post.assert_called_once()
        _, kwargs = session.post.call_args
        assert kwargs["data"] == _PNG
        assert kwargs["headers"]["Content-Type"] == "image/png"

    async def test_posts_to_correct_url(self) -> None:
        # The first positional argument to session.post is the webhook URL.
        session = _make_session()
        await async_push_image(session, _URL, _PNG)

        args, _ = session.post.call_args
        assert args[0] == _URL

    async def test_no_warning_on_200(self) -> None:
        # A 200 response is silent — no log.warning emitted.
        session = _make_session(status=200)
        with patch(
            "custom_components.eink_dashboard.push._LOGGER"
        ) as mock_log:
            await async_push_image(session, _URL, _PNG)
            mock_log.warning.assert_not_called()

    async def test_warns_on_non_2xx(self) -> None:
        # A 4xx response triggers a single log.warning with the status.
        session = _make_session(status=422)
        with patch(
            "custom_components.eink_dashboard.push._LOGGER"
        ) as mock_log:
            await async_push_image(session, _URL, _PNG)
            mock_log.warning.assert_called_once()

    async def test_catches_and_logs_connection_error(self) -> None:
        # Network errors are caught and logged without re-raising.
        session = _make_session(
            raise_on_post=aiohttp.ClientError("connection refused")
        )
        with patch(
            "custom_components.eink_dashboard.push._LOGGER"
        ) as mock_log:
            await async_push_image(session, _URL, _PNG)
            mock_log.warning.assert_called_once()

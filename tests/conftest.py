from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

_HASS_FRONTEND_FIXTURE = Path(__file__).parent / "fixtures" / "hass_frontend"

# Set sys.modules["hass_frontend"] once at module load — before any
# production code imports it — so that _load_hass_mdi_metadata() (which
# is decorated with @functools.cache and runs exactly once per process)
# picks up the fixture path on its first and only call.
_hass_frontend_stub = ModuleType("hass_frontend")
_hass_frontend_stub.where = lambda: str(_HASS_FRONTEND_FIXTURE)  # type: ignore[attr-defined]
sys.modules["hass_frontend"] = _hass_frontend_stub


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    """Replace @async_response before collection.

    The decorator is applied at function-definition time when
    custom_components.eink_dashboard.websocket is imported.  Patching
    here (before collection starts) means ws_render_widget remains a
    plain awaitable coroutine that tests can call directly with
    ``await handler(hass, conn, msg)``.  Restored by pytest_unconfigure.
    """
    import homeassistant.components.websocket_api as ws

    config._orig_async_response = ws.async_response  # type: ignore[attr-defined]
    ws.async_response = lambda f: f  # type: ignore[attr-defined]


def pytest_unconfigure(config) -> None:  # type: ignore[no-untyped-def]
    """Restore @async_response after the test session."""
    import homeassistant.components.websocket_api as ws

    ws.async_response = config._orig_async_response  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow phacc's hass fixture to discover custom_components/.

    phacc exposes ``enable_custom_integrations`` as a non-autouse
    fixture; requesting it here makes it active for every test so
    the hass fixture can discover custom_components/.
    """
    yield

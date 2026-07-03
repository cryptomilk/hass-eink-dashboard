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


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow phacc's hass fixture to discover custom_components/.

    phacc exposes ``enable_custom_integrations`` as a non-autouse
    fixture; requesting it here makes it active for every test so
    the hass fixture can discover custom_components/.
    """
    yield

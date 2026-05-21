"""Shared bootstrap helpers for eink_dashboard scripts.

Loads eink_dashboard submodules directly from their .py files,
bypassing the package __init__.py (which requires Home Assistant).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parent.parent
PKG = "custom_components.eink_dashboard"

sys.path.insert(0, str(ROOT))

# Register dummy packages so relative imports between submodules
# (e.g. ``from .svg_render import ...`` in render.py) resolve
# against already-bootstrapped siblings instead of triggering
# __init__.py (which requires Home Assistant).
# __path__ must point to real directories so Python can find
# subpackages like ``widgets/``.
_PKG_PATHS: dict[str, list[str]] = {
    "custom_components": [
        str(ROOT / "custom_components"),
    ],
    PKG: [
        str(ROOT / "custom_components" / "eink_dashboard"),
    ],
}
for _pkg in ("custom_components", PKG):
    if _pkg not in sys.modules:
        _m = ModuleType(_pkg)
        _m.__path__ = _PKG_PATHS[_pkg]  # type: ignore[attr-defined]
        sys.modules[_pkg] = _m


def import_module(name: str) -> object:
    """Import an eink_dashboard submodule by file path.

    Loads the module directly from its .py file so the package
    __init__.py (which pulls in Home Assistant) is never executed.

    Args:
        name: Fully-qualified module name, e.g.
            ``custom_components.eink_dashboard.render``.

    Returns:
        The loaded module object.
    """
    pkg_dir = ROOT / "custom_components" / "eink_dashboard"
    short = name.split(".")[-1]
    spec = importlib.util.spec_from_file_location(
        name, pkg_dir / f"{short}.py"
    )
    mod = importlib.util.module_from_spec(  # type: ignore[arg-type]
        spec
    )
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod

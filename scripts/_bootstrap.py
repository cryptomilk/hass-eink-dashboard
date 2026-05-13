"""Shared bootstrap helpers for eink_dashboard scripts.

Loads eink_dashboard submodules directly from their .py files,
bypassing the package __init__.py (which requires Home Assistant).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PKG = "custom_components.eink_dashboard"

sys.path.insert(0, str(ROOT))


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

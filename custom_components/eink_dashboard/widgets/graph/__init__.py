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

"""Graph widget package.

Split into ``colors``, ``data``, ``geometry``, ``series``, and
``context`` submodules; this file re-exports the symbols consumed
outside the package (by ``widgets/__init__.py``, tests, and design
scripts) so existing imports of ``widgets.graph`` keep working.
"""

from __future__ import annotations

from .colors import (
    _bar_threshold_fill,
    _lighter_hex,
    _normalize_thresholds,
    _resolve_threshold_color,
    _rgb_hex_to_grayscale,
    _shade_to_hex,
    _threshold_gradient_stops,
)
from .context import _build_graph_context
from .data import _extract_entity_points, _resolve_start_cutoff, _y_bounds
from .geometry import (
    _format_timestamp,
    _legend_geometry,
    _smooth_path,
    _truncate_to_width,
)
from .series import _bar_series, _line_series

__all__ = [
    "_bar_series",
    "_bar_threshold_fill",
    "_build_graph_context",
    "_extract_entity_points",
    "_format_timestamp",
    "_legend_geometry",
    "_lighter_hex",
    "_line_series",
    "_normalize_thresholds",
    "_resolve_start_cutoff",
    "_resolve_threshold_color",
    "_rgb_hex_to_grayscale",
    "_shade_to_hex",
    "_smooth_path",
    "_threshold_gradient_stops",
    "_truncate_to_width",
    "_y_bounds",
]

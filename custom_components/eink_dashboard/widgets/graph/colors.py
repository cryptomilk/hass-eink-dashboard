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

"""Graph widget threshold and gradient color helpers."""

from __future__ import annotations

from ...const import (
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_LIGHT_GRAY,
    COLOR_MEDIUM_GRAY,
    Widget,
    color_to_hex,
)

# Fill colors for bar chart entity series: first entity is black,
# second is gray, third is light gray.  E-ink displays distinguish
# shades rather than hues; these three values give maximum contrast.
_BAR_FILL_COLORS: tuple[str, ...] = (
    color_to_hex(COLOR_BLACK),
    color_to_hex(COLOR_GRAY),
    color_to_hex(COLOR_LIGHT_GRAY),
)

# Named shade → grayscale constant mapping for explicit threshold
# overrides.  The four named levels map to the standard e-ink palette:
# black, dark gray, light gray, and a near-white value that is still
# visually distinct from the white background.
_SHADE_VALUES: dict[str, int] = {
    "black": COLOR_BLACK,
    "dark": COLOR_GRAY,
    "medium": COLOR_MEDIUM_GRAY,
    "light": COLOR_LIGHT_GRAY,
}


def _rgb_hex_to_grayscale(
    hex_color: str,
    display_levels: int,
) -> str:
    """Convert an RGB hex color string to a grayscale hex string.

    Parses a ``#RRGGBB`` string, computes the ITU-R BT.601 luminance,
    and quantizes the result to the number of levels available on the
    display.  On 2-level (B&W) displays the result is clamped to pure
    black or white.

    Args:
        hex_color: CSS hex color string, e.g. ``"#ff0000"``.  Must
            start with ``#`` followed by exactly six hex digits.
            Values that do not match this form are treated as black.
        display_levels: Number of distinct gray levels on the
            display.  ``2`` produces only black or white; higher
            values quantize to the nearest available step.

    Returns:
        Grayscale ``#rrggbb`` hex string suitable for SVG attributes.
        Falls back to ``color_to_hex(COLOR_BLACK)`` on parse error.
    """
    try:
        hex_clean = hex_color[1:]
        if len(hex_clean) != 6:
            raise ValueError("bad length")
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
    except (ValueError, AttributeError):
        return color_to_hex(COLOR_BLACK)
    # ITU-R BT.601 luminance coefficients.
    gray = round(0.299 * r + 0.587 * g + 0.114 * b)
    if display_levels <= 2:
        # Hard threshold at mid-gray.
        return color_to_hex(0 if gray < 128 else 255)
    # Quantize to the nearest available step.
    steps = display_levels - 1
    quantized = round(gray / 255 * steps) * 255 // steps
    return color_to_hex(quantized)


def _shade_to_hex(shade: str) -> str:
    """Convert a named shade string to a grayscale hex color.

    Args:
        shade: One of ``"black"``, ``"dark"``, ``"medium"``,
            or ``"light"``.  Unknown values fall back to black.

    Returns:
        Grayscale ``#rrggbb`` hex string.
    """
    return color_to_hex(_SHADE_VALUES.get(shade, COLOR_BLACK))


def _resolve_threshold_color(
    entry: dict[str, object],
    display_levels: int,
) -> str:
    """Resolve the final hex color for one threshold entry.

    ``shade`` takes precedence over ``color`` on all displays.  When
    neither key is present the fallback is black.

    Args:
        entry: Threshold dict with optional ``"shade"`` and
            ``"color"`` keys.
        display_levels: Display grayscale depth, used when mapping
            RGB colors to grayscale.

    Returns:
        Resolved ``#rrggbb`` hex string.
    """
    shade = str(entry.get("shade", ""))
    if shade:
        return _shade_to_hex(shade)
    color = str(entry.get("color", ""))
    if color:
        return _rgb_hex_to_grayscale(color, display_levels)
    return color_to_hex(COLOR_BLACK)


def _lighter_hex(hex_color: str) -> str:
    """Shift a grayscale hex color 50% toward white.

    Used to produce a softer fill gradient from the same threshold
    colors as the stroke gradient.  Assumes the input is already a
    grayscale color (all three channels equal).

    Args:
        hex_color: Grayscale ``#rrggbb`` hex string.

    Returns:
        Lightened ``#rrggbb`` hex string.  Falls back to
        ``color_to_hex(COLOR_LIGHT_GRAY)`` on parse error.
    """
    try:
        gray = int(hex_color[1:3], 16)
    except (ValueError, AttributeError, IndexError):
        return color_to_hex(COLOR_LIGHT_GRAY)
    lighter = gray + (255 - gray) // 2
    return color_to_hex(lighter)


def _threshold_gradient_stops(
    thresholds: list[dict[str, object]],
    transition: str,
    y_min: float,
    y_max: float,
    display_levels: int,
) -> list[dict[str, str]]:
    """Compute SVG linearGradient stop entries for color thresholds.

    The gradient runs top-to-bottom in SVG space.  Because the Y
    axis is inverted (high data values map to small Y coordinates),
    a high threshold value maps to a small offset percentage.

    For ``"smooth"`` transitions each threshold produces one stop.
    For ``"hard"`` transitions the boundary between consecutive
    threshold bands is duplicated — two stops at the same offset with
    different colors create a sharp edge with no blending.

    Args:
        thresholds: Sorted ascending by ``"value"``.  Must contain
            at least two entries (enforced by caller).
        transition: ``"smooth"`` or ``"hard"``.
        y_min: Y-axis lower bound (bottom of graph area).
        y_max: Y-axis upper bound (top of graph area).
        display_levels: Display grayscale depth for color mapping.

    Returns:
        List of ``{"offset": "XX.XX%", "color": "#hex"}`` dicts,
        ordered top (0%) to bottom (100%) of the gradient.
    """
    y_range = y_max - y_min

    def _offset(val: float) -> str:
        """Convert a data value to an SVG gradient offset percentage."""
        # High value → small offset (near top of SVG gradient).
        pct = (y_max - val) / y_range * 100.0
        pct = max(0.0, min(100.0, pct))
        return f"{pct:.2f}%"

    colors = [_resolve_threshold_color(t, display_levels) for t in thresholds]

    if transition == "hard":
        # Descending by value so we build stops top → bottom.
        desc = list(reversed(thresholds))
        desc_colors = list(reversed(colors))
        stops: list[dict[str, str]] = [
            {"offset": "0.00%", "color": desc_colors[0]},
        ]
        for i in range(1, len(desc)):
            off = _offset(float(str(desc[i]["value"])))
            # Stop for the color of the band ABOVE the boundary.
            stops.append({"offset": off, "color": desc_colors[i - 1]})
            # Stop for the color of the band BELOW — same offset.
            stops.append({"offset": off, "color": desc_colors[i]})
        stops.append({"offset": "100.00%", "color": desc_colors[-1]})
        return stops

    # Smooth: one stop per threshold, descending (top → bottom).
    return [
        {
            "offset": _offset(float(str(t["value"]))),
            "color": c,
        }
        for t, c in zip(reversed(thresholds), reversed(colors), strict=True)
    ]


def _bar_threshold_fill(
    value: float,
    thresholds: list[dict[str, object]],
    display_levels: int,
) -> str:
    """Resolve the threshold fill color for a single bar value.

    Walks the threshold list (sorted ascending) to find the highest
    threshold boundary that the data value meets or exceeds.

    Args:
        value: The bar's data value.
        thresholds: Sorted ascending by ``"value"``.
        display_levels: Display grayscale depth for color mapping.

    Returns:
        Resolved ``#rrggbb`` hex string for the bar's fill.
    """
    chosen = thresholds[0]
    for t in thresholds:
        if value >= float(str(t["value"])):
            chosen = t
        else:
            break
    return _resolve_threshold_color(chosen, display_levels)


def _normalize_thresholds(
    widget: Widget,
) -> list[dict[str, object]]:
    """Normalize widget config into a canonical threshold list.

    Accepts either the canonical ``color_thresholds`` list or flat
    editor keys ``threshold_{1..4}_{value,color,shade}``.  When both
    are present, the canonical list takes precedence.

    Args:
        widget: Widget config dict.

    Returns:
        List of threshold dicts each with keys ``value`` (float),
        ``color`` (str, empty when absent), and ``shade`` (str, empty
        when absent).  Sorted ascending by ``value``.  May be empty.
    """
    canonical = widget.get("color_thresholds")
    if isinstance(canonical, list) and canonical:
        result: list[dict[str, object]] = []
        for item in canonical:
            if not isinstance(item, dict):
                continue
            try:
                v = float(str(item.get("value", "")))
            except (ValueError, TypeError):
                continue
            result.append(
                {
                    "value": v,
                    "color": str(item.get("color", "")),
                    "shade": str(item.get("shade", "")),
                }
            )
        return sorted(result, key=lambda t: float(str(t["value"])))

    # Flat editor keys: threshold_1_value ... threshold_4_value.
    result = []
    for n in range(1, 5):
        raw_v = widget.get(f"threshold_{n}_value")
        if raw_v is None:
            continue
        try:
            v = float(str(raw_v))
        except (ValueError, TypeError):
            continue
        result.append(
            {
                "value": v,
                "color": str(widget.get(f"threshold_{n}_color", "")),
                "shade": str(widget.get(f"threshold_{n}_shade", "")),
            }
        )
    return sorted(result, key=lambda t: float(str(t["value"])))

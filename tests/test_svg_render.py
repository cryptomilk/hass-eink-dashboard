"""Tests for the SVG rendering pipeline."""

import io

import pytest
import resvg_py
from PIL import Image

from custom_components.eink_dashboard.svg_render import (
    _TEMPLATE_DIR,
    _jinja_env,
    _mdi_svg_filter,
    _svg_to_png,
    _weather_svg_filter,
)


def test_resvg_rasterises_simple_svg():
    """Verify resvg_py can rasterise a trivial SVG to valid PNG bytes."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
        '<rect width="100" height="50" fill="white"/>'
        '<text x="10" y="30" font-size="16">hi</text>'
        "</svg>"
    )
    result = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=100, height=50))
    # PNG magic header: \x89PNG\r\n\x1a\n
    assert result[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(result) > 0


def test_svg_to_png_produces_valid_png():
    """Verify _svg_to_png() rasterises Roboto text to a valid PNG."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="80">'
        '<rect width="200" height="80" fill="white"/>'
        '<text x="10" y="50" font-family="Roboto" font-size="24">Test</text>'
        "</svg>"
    )
    result = _svg_to_png(svg, 200, 80)
    assert result[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(result) > 0


def test_jinja_env_loads_template(tmp_path):
    """Verify _jinja_env loads templates from the templates directory."""
    # Write a temporary template into the templates directory and clean up
    # after the test so the working tree stays unmodified.
    tmp_template = _TEMPLATE_DIR / "_test_step02.svg.j2"
    tmp_template.write_text("<svg>{{ value }}</svg>")
    try:
        tmpl = _jinja_env.get_template("_test_step02.svg.j2")
        output = tmpl.render(value="hello")
        assert "hello" in output
    finally:
        tmp_template.unlink(missing_ok=True)


def test_mdi_svg_filter_returns_svg_with_path():
    """Verify _mdi_svg_filter emits a sized SVG with the icon path."""
    result = _mdi_svg_filter("thermometer", 32)
    assert "<svg" in result
    assert 'viewBox="0 0 24 24"' in result
    assert 'width="32"' in result
    assert "<path" in result


def test_weather_svg_filter_returns_svg_with_path():
    """Verify _weather_svg_filter emits a sized SVG with the icon path."""
    result = _weather_svg_filter("sunny", 48)
    assert "<svg" in result
    assert 'viewBox="0 0 30 30"' in result
    assert 'width="48"' in result
    assert "<path" in result


def test_unknown_mdi_name_raises():
    """Verify an unknown MDI icon name raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        _mdi_svg_filter("nonexistent_icon_xyz", 32)


def test_mdi_path_traversal_raises():
    """Verify a path traversal icon name raises ValueError."""
    with pytest.raises(ValueError):
        _mdi_svg_filter("../../etc/passwd", 32)


def test_unknown_weather_condition_raises():
    """Verify an unknown weather condition raises KeyError."""
    with pytest.raises(KeyError):
        _weather_svg_filter("nonexistent_condition", 48)


def test_inlined_icon_rasterises_with_dark_pixels():
    """Verify an SVG with an inlined MDI icon has dark pixels in the
    icon region after rasterisation."""
    icon_svg = _mdi_svg_filter("thermometer", 40)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<rect width="100" height="100" fill="white"/>'
        f'<g transform="translate(30, 30)">{icon_svg}</g>'
        "</svg>"
    )
    png = _svg_to_png(svg, 100, 100)
    img = Image.open(io.BytesIO(png)).convert("L")
    # The 40×40 icon is placed at (30, 30); check for non-white pixels.
    region = img.crop((30, 30, 70, 70))
    assert any(p < 200 for p in region.get_flattened_data())

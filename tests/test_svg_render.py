"""Tests for the SVG rendering pipeline."""

import resvg_py

from custom_components.eink_dashboard.svg_render import (
    _TEMPLATE_DIR,
    _jinja_env,
    _svg_to_png,
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

"""Smoke tests for the SVG rendering pipeline (Step 0.1)."""

import resvg_py


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

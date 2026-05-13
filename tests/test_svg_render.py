"""Tests for the SVG rendering pipeline."""

import io

import jinja2
import pytest
import resvg_py
from PIL import Image

from custom_components.eink_dashboard.svg_render import (
    _TEMPLATE_DIR,
    _jinja_env,
    _make_jinja_env,
    _mdi_svg_filter,
    _svg_to_png,
    _weather_svg_filter,
)
from tests.helpers import (
    assert_all_white,
    assert_has_dark_pixels,
    assert_has_gray_pixels,
    pixel,
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


# ---------------------------------------------------------------------------
# Step 0.4: _macros.svg.j2 macro tests
# ---------------------------------------------------------------------------
# The render_macro fixture (below) renders a Jinja2 template source string
# via a ChoiceLoader that resolves macro imports from _TEMPLATE_DIR while
# writing temporary templates to pytest's tmp_path, keeping _TEMPLATE_DIR
# clean.  _macros.svg.j2 itself is permanent.
# ---------------------------------------------------------------------------

_SVG_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg"'
    ' width="400" height="200">'
    '<rect width="400" height="200" fill="white"/>'
)
_SVG_CLOSE = "</svg>"


@pytest.fixture
def render_macro(tmp_path):
    """Render a Jinja2 macro template source without writing to _TEMPLATE_DIR.

    Returns a callable render(source, width=400, height=200, **ctx) that
    writes the template source to tmp_path, renders it via a ChoiceLoader
    that resolves macro imports from _TEMPLATE_DIR, rasterises the SVG, and
    returns a grayscale PIL Image.
    """

    def _render(
        source: str,
        width: int = 400,
        height: int = 200,
        **ctx: object,
    ) -> Image.Image:
        (tmp_path / "_test.svg.j2").write_text(source)
        env = _make_jinja_env(
            jinja2.ChoiceLoader(
                [
                    jinja2.FileSystemLoader(str(tmp_path)),
                    jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
                ]
            ),
        )
        svg = env.get_template("_test.svg.j2").render(**ctx)
        png = _svg_to_png(svg, width, height)
        return Image.open(io.BytesIO(png)).convert("L")

    return _render


# --- card_container --------------------------------------------------------


def test_card_container_border_draws_rounded_rect(render_macro) -> None:
    """Verify border card_container emits a rounded rectangle whose
    edges are dark and whose interior is white."""
    img = render_macro(
        "{%- from '_macros.svg.j2' import card_container -%}"
        + _SVG_OPEN
        + "{% call(xo, ri) card_container("
        "x=10, y=10, w=380, h=180,"
        " card_style='border',"
        " radius=12, border=3, padding=12) %}"
        "{% endcall %}" + _SVG_CLOSE
    )
    # Top border: dark pixels across the middle of the top edge
    # (well past the corner radius of 12).
    assert_has_dark_pixels(img, 50, 10, 350, 14)
    # Bottom border
    assert_has_dark_pixels(img, 50, 186, 350, 190)
    # Left border
    assert_has_dark_pixels(img, 10, 50, 14, 150)
    # Right border
    assert_has_dark_pixels(img, 386, 50, 390, 150)
    # Interior: well inside the border strokes and corner radii
    assert_all_white(img, 30, 30, 370, 170)


def test_card_container_left_bar_draws_gray(render_macro) -> None:
    """Verify left_bar card_container emits a gray vertical bar on
    the left and white space to the right of it."""
    # bar at x=10, width=6 → bar right edge at x=16
    img = render_macro(
        "{%- from '_macros.svg.j2' import card_container -%}"
        + _SVG_OPEN
        + "{% call(xo, ri) card_container("
        "x=10, y=10, w=380, h=180,"
        " card_style='left_bar',"
        " left_bar=6, padding=10) %}"
        "{% endcall %}" + _SVG_CLOSE
    )
    # Gray bar in the left_bar area (x=10..16, middle of height)
    assert_has_gray_pixels(img, 10, 50, 16, 150)
    # Area past the bar (x=20) should be white; x=20 gives a 4px
    # anti-aliasing margin from the bar right edge at x=16.
    assert_all_white(img, 20, 10, 390, 190)


def test_card_container_left_bar_widens_for_2_level(render_macro) -> None:
    """Verify left_bar widens to max(10, left_bar*3) on 2-level displays."""
    # left_bar=4 → bar_w = max(10, 4*3) = 12
    img = render_macro(
        "{%- from '_macros.svg.j2' import card_container -%}"
        + _SVG_OPEN
        + "{% call(xo, ri) card_container("
        "x=10, y=10, w=380, h=180,"
        " card_style='left_bar',"
        " left_bar=4, padding=8, grayscale_levels=2) %}"
        "{% endcall %}" + _SVG_CLOSE
    )
    # Widened bar covers x=10..22 (10 + 12); check near the right
    # edge of the widened bar.
    assert_has_gray_pixels(img, 10, 50, 22, 150)
    # Area well past the widened bar should be white
    assert_all_white(img, 35, 10, 390, 190)


def test_card_container_none_caller_invoked(render_macro) -> None:
    """Verify card_style='none' emits no decoration and invokes the
    caller body: a sentinel rect drawn inside {% call %} must render."""
    # The sentinel rect at (150, 90, 180, 110) is drawn by the caller body.
    # If the macro fails to call caller(), the sentinel is absent and the
    # first assertion fails.  The second assertion verifies no decoration
    # was added by the macro itself.
    img = render_macro(
        "{%- from '_macros.svg.j2' import card_container -%}"
        + _SVG_OPEN
        + "{% call(xo, ri) card_container("
        "x=10, y=10, w=380, h=180, card_style='none') %}"
        "<rect x='150' y='90' width='30' height='20' fill='black'/>"
        "{% endcall %}" + _SVG_CLOSE
    )
    # Caller body was invoked: sentinel rect is present
    assert_has_dark_pixels(img, 150, 90, 180, 110)
    # No card decoration: area well away from the sentinel is white
    assert_all_white(img, 0, 0, 140, 90)


# --- card_row --------------------------------------------------------------


def test_card_row_icon_circle_and_primary(render_macro) -> None:
    """Verify card_row draws a gray icon circle and dark primary text."""
    # row at (10, 10), row_h=56, padding=12, icon_dia=36, inner_gap=12
    img = render_macro(
        "{%- from '_macros.svg.j2' import card_row -%}"
        + _SVG_OPEN
        + "{{ card_row("
        "x=10, y=10, w=380, row_h=56,"
        " padding=12, icon_dia=36, inner_gap=12, border=2,"
        " font_primary=18, font_secondary=14,"
        " primary='Temperature', letter='T') }}" + _SVG_CLOSE
    )
    # Icon circle center: x=10+12+18=40, y=10+28=38; r=18
    # Check gray pixels in the circle area
    assert_has_gray_pixels(img, 22, 20, 58, 56)
    # Text starts after icon+gap: x=10+12+36+12=70
    assert_has_dark_pixels(img, 70, 14, 300, 62)


def test_card_row_secondary_and_value(render_macro) -> None:
    """Verify card_row renders secondary text (gray) and right-aligned
    value text."""
    img = render_macro(
        "{%- from '_macros.svg.j2' import card_row -%}"
        + _SVG_OPEN
        + "{{ card_row("
        "x=10, y=10, w=380, row_h=80,"
        " padding=12, icon_dia=36, inner_gap=12, border=2,"
        " font_primary=20, font_secondary=15,"
        " primary='Sensor', secondary='23 °C',"
        " value='now', letter='S') }}" + _SVG_CLOSE
    )
    # Text area has dark pixels (primary)
    tx = 10 + 12 + 36 + 12  # = 70
    assert_has_dark_pixels(img, tx, 15, 300, 85)
    # Secondary text is gray; check a broader region in the lower
    # half of the row where secondary sits
    assert_has_gray_pixels(img, tx, 50, 250, 85, low=50, high=200)
    # Value text near right edge (text-anchor="end" at x=10+380-12=378)
    assert_has_gray_pixels(img, 280, 15, 390, 85, low=50, high=200)


def test_card_row_icon_svg_renders(render_macro) -> None:
    """Verify card_row places an inlined MDI icon in the circle area."""
    icon_svg = _mdi_svg_filter("thermometer", 22)
    img = render_macro(
        "{%- from '_macros.svg.j2' import card_row -%}"
        + _SVG_OPEN
        + "{{ card_row("
        "x=10, y=10, w=380, row_h=56,"
        " padding=12, icon_dia=36, inner_gap=12, border=2,"
        " font_primary=18, font_secondary=14,"
        " primary='Temp', icon_svg=icon_svg) }}" + _SVG_CLOSE,
        icon_svg=icon_svg,
    )
    # Icon circle area: center ~(40, 38), check for non-white pixels
    # (icon on gray circle → mix of colors in the area)
    assert_has_dark_pixels(img, 22, 20, 58, 56)


# --- chip ------------------------------------------------------------------


def test_chip_draws_pill_with_text(render_macro) -> None:
    """Verify chip emits a pill border with dark edges and inner text."""
    # h=40: radius=20, so corners at (x+20, y) and (x+w-20, y)
    # chip at x=20, y=80, w=100, h=40
    img = render_macro(
        "{%- from '_macros.svg.j2' import chip -%}"
        + _SVG_OPEN
        + "{{ chip(x=20, y=80, w=100, h=40,"
        " text='OK', border=2) }}" + _SVG_CLOSE
    )
    # Top border: dark pixels along the flat portion of the top edge
    assert_has_dark_pixels(img, 40, 80, 100, 83)
    # Pill corners are clipped: pixels at exact corners should be white
    assert pixel(img, 20, 80) == 255  # top-left corner
    assert pixel(img, 119, 80) == 255  # top-right corner
    # Interior: text area should have dark pixels
    assert_has_dark_pixels(img, 35, 85, 110, 115)


def test_chip_inverted_has_dark_fill(render_macro) -> None:
    """Verify inverted chip fills the pill black."""
    img = render_macro(
        "{%- from '_macros.svg.j2' import chip -%}"
        + _SVG_OPEN
        + "{{ chip(x=20, y=80, w=100, h=40,"
        " text='ERR', border=2, inverted=true) }}" + _SVG_CLOSE
    )
    # Center of the chip should be black (or very dark)
    assert pixel(img, 70, 100) < 50


def test_chip_with_icon(render_macro) -> None:
    """Verify chip with an inlined icon has dark pixels in the icon area."""
    # h=40: icon_sz = 40*29//100 = 11; pad = 40*18//100 = 7
    # icon at x=20+7=27, y=80+(40-11)//2=94
    icon_svg = _mdi_svg_filter("thermometer", 11)
    img = render_macro(
        "{%- from '_macros.svg.j2' import chip -%}"
        + _SVG_OPEN
        + "{{ chip(x=20, y=80, w=120, h=40,"
        " text='Warm', border=2, icon_svg=icon_svg) }}" + _SVG_CLOSE,
        icon_svg=icon_svg,
    )
    # Icon region: left side of chip interior (roughly x=27..38, y=94..105)
    assert_has_dark_pixels(img, 27, 90, 40, 110)

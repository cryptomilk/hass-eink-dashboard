# Fonts and non-Latin scripts

The dashboard bundles three font families: the TRMNL pixel font in
12px, 16px, and 21px optical sizes, each with regular and bold
weights; Roboto in regular, medium, and bold weights; and Inter in
regular, medium, and bold weights. Rendering uses the selected font
family as its primary face and the other bundled family as a glyph
fallback. Inter is not selectable on its own — it is only used as
the large-text fallback described below.

Choose **TRMNL** or **Roboto** in **Configure → Display settings →
Font family**. Text widths are measured using the selected primary font
so layout matches the rendered output.

The default depends on the display. Low-resolution panels, where small
text is only a few pixels tall, default to TRMNL; all other displays
default to Roboto:

| Device model | Default font |
|---|---|
| TRMNL OG, reTerminal E1001, reTerminal E1002 (800 × 480) | TRMNL |
| Kindle, TRMNL X, TRMNL RGB, reTerminal E1003 | Roboto |
| Custom, shorter side 480 px or less | TRMNL |
| Custom, larger | Roboto |

Changing the **Device model** resets the font to the new model's
default; changing only the orientation keeps your choice.

The dashboard card's live preview loads the bundled TRMNL font files
from the integration (`/eink_dashboard/fonts/`), so the preview in the
browser uses the same font as the rendered image.

## Pixel-perfect text

TRMNL glyphs are drawn on a pixel grid, so they are only sharp at
their native sizes (12, 16, 21 px) or whole multiples of them (24,
32, 42, …). At other sizes the font pixels straddle screen pixels and
turn into gray smudges, which a pure black-and-white display turns
into blobs — especially for bold text.

The **Pixel-perfect text** toggle (**Configure → Display settings**,
on by default) snaps every TRMNL font size to the nearest native size
or multiple and renders text without anti-aliasing, so glyphs are
pure black and white. Text may be a pixel or two larger or smaller
than without it, and the font is never rendered below 12 px. The
option has no effect when Roboto is selected.

## Large text font

TRMNL glyphs are built from square font pixels, so scaled up they look
blocky no matter how they are rasterised. The **Large text font**
option (**Configure → Display settings**) sets how far TRMNL may be
scaled; larger text — such as a big weather temperature — renders in
Inter with anti-aliasing instead, while smaller text stays in TRMNL.

| Setting | TRMNL used up to |
|---|---|
| Automatic (default) | depends on pixel density, see below |
| 1x / 2x / 3x / 4x | 21 / 42 / 63 / 84 px |
| Never | any size (no fallback) |

Whether blocks are visible depends on how large one font pixel is on
the panel, so **Automatic** keeps it at most 1/62 inch (about 0.4 mm):
2x on 800 × 480 panels and Kindle 4/5, 3x on Kindle Paperwhite 1–3
and TRMNL X, 4x at 300 ppi. Custom displays use the entered pixel
density, or 2x when none is set. The option has no effect when Roboto
is selected.

## Black text

Names and secondary labels are drawn in gray. On displays with few
gray levels, dithering turns that gray into a speckled dot pattern
that is hard to read at small sizes. The **Black text** toggle
(**Configure → Display settings**, off by default) renders every
non-white text colour in black. White text on dark backgrounds is
kept, and icons, dividers and other shapes keep their colours.

Two additional **Display Settings** options (**Configure → Display
settings**) add glyph coverage for scripts the bundled fonts do not
cover. Both are additive: they add fonts alongside the selected
bundled family, so the renderer automatically falls back to whichever
loaded font has the glyph.

## Use system fonts

Under **Display settings**, the **Use system fonts** toggle
additionally loads whatever fonts are already installed on the Home
Assistant host, as a further fallback. It is convenient when the host
already has broad script coverage installed (for example, a
distro-packaged Noto font collection) and you don't want to source
and mount a font file yourself.

It is **off by default** because it trades away reproducibility: the
same dashboard can render with different glyph shapes — and slightly
different text widths, since layout is computed from measured text —
depending on what happens to be installed on that particular host.
HA OS and Docker images are usually minimal and often have no broad
script coverage installed, so a **Custom font directory** is more
likely to actually fix missing glyphs than this toggle.

## Custom font directory

Under **Display settings → Advanced**, set **Custom font directory**
to a path containing extra `.ttf`/`.otf` font files (for example,
[Noto Sans Hebrew](https://fonts.google.com/noto/specimen/Noto+Sans+Hebrew)
or a CJK font). This is the recommended option: it is reproducible —
the same fonts are loaded every render, regardless of host — and
works the same way on HA OS, Docker, and a plain Python install.

The directory must be reachable by Home Assistant:

- **HA OS / Docker**: mount a host directory into the container, e.g.
  `-v /host/path/to/fonts:/config/fonts` (Docker) or an equivalent
  Supervisor add-on mount, then enter the in-container path
  (`/config/fonts`) as the **Custom font directory** value.
- **Core / venv install**: any path readable by the Home Assistant
  process works directly.

Leave the field empty to use only the bundled TRMNL, Roboto, and
Inter fonts.

## Which one should I use?

- Know exactly which font you need and want identical rendering
  everywhere → **Custom font directory**.
- Know your host already has the right fonts installed and just want
  the quick option → **Use system fonts**.
- Both can be enabled together; fonts from both sources are loaded
  and resvg picks whichever one covers a given character.

## Credits

The **TRMNL** pixel font was designed by
[Renegade Fonts](https://renegadefonts.com) and published by
[Heavyweight Digital Type Foundry](http://www.heavyweight-type.com)
(© 2026 Heavyweight Digital Type Foundry s.r.o.). It is licensed under
the [SIL Open Font License 1.1](https://openfontlicense.org); the full
license ships next to the font files in
`custom_components/eink_dashboard/fonts/TRMNL/OFL.txt`. The bundled
files are the unmodified originals.

**Roboto** is by Google and licensed under the Apache License 2.0; see
`custom_components/eink_dashboard/fonts/Roboto/LICENSE`.

**Inter** was designed by [The Inter Project
Authors](https://github.com/rsms/inter) and is licensed under the
[SIL Open Font License 1.1](https://openfontlicense.org); the full
license ships next to the font files in
`custom_components/eink_dashboard/fonts/Inter/OFL.txt`.

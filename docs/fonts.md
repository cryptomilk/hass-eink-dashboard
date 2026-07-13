# Fonts and non-Latin scripts

The dashboard ships a single bundled font, Roboto, which only covers
Latin, Cyrillic, and Greek scripts. Text in other scripts — Hebrew,
Arabic, CJK, etc. — renders as empty boxes ("tofu") because Roboto has
no glyphs for those characters.

Two **Display Settings** options (**Configure → Display settings**)
add glyph coverage for those scripts. Both are additive: they add
fonts alongside Roboto, so `font-family` in widget templates never
needs to change — the renderer automatically falls back to whichever
loaded font actually has the glyph.

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

Leave the field empty to use only the bundled Roboto font (the
default).

## Which one should I use?

- Know exactly which font you need and want identical rendering
  everywhere → **Custom font directory**.
- Know your host already has the right fonts installed and just want
  the quick option → **Use system fonts**.
- Both can be enabled together; fonts from both sources are loaded
  and resvg picks whichever one covers a given character.

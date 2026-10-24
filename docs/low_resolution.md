# Sharp text on low-resolution displays

How sharp text looks depends mostly on the display's **pixel density**,
not on how many colours it can show. On a 7.5" 800 × 480 panel such as
the TRMNL OG or the Seeed reTerminal E1001 (about 125 pixels per inch),
small labels are only 12–16 px tall and a letter stroke is one or two
pixels wide. The gray, anti-aliased edge pixels that make text look
smooth on a phone are then a large share of every glyph. Once the image
is reduced to a few gray levels, those edges turn into blobs, speckles
or broken strokes, especially in bold and in secondary (gray) labels.

High-density displays such as the Kindle Paperwhite or the TRMNL X have
roughly twice as many pixels per inch. Their strokes span several
pixels, so anti-aliased Roboto at 16 gray levels already looks crisp
and the default settings are the right choice.

Black-and-white displays make the problem worse because they cannot
show gray at all, but a low-resolution panel with 4 gray levels
benefits from the same settings.

## Which displays need this

| Display | Resolution | Levels | Recommendation |
|---|---|---|---|
| TRMNL OG | 800 × 480 | 2 | [Low resolution, black and white](#low-resolution-black-and-white-displays) |
| Seeed reTerminal E1001 | 800 × 480 | 4 | [Low resolution, gray levels](#low-resolution-displays-with-gray-levels) |
| Kindle 4/5 | 600 × 800 | 16 | Defaults; consider the [gray-level settings](#low-resolution-displays-with-gray-levels) for small text |
| Kindle Paperwhite, Oasis | 758 × 1024 and up | 16 | Defaults |
| TRMNL X, reTerminal E1003 | 1872 × 1404 | 16 | Defaults |
| TRMNL RGB | 2560 × 1440 | 2 | Defaults plus the [Black and white dither algorithm](#low-resolution-black-and-white-displays) |

For a custom display, a rough rule: if the body text of your dashboard
is less than about 20 px tall, or the panel has fewer than about 150
pixels per inch, use the low-resolution settings below.

The **Font family** default already follows this split: the TRMNL OG,
the reTerminal E1001/E1002 and custom displays whose shorter side is
480 px or less start with the TRMNL pixel font; all other displays start
with Roboto. See [Fonts and non-Latin scripts](fonts.md) for the full
list.

All settings are in **Settings → Devices & Services → E-Ink Dashboard →
Configure → Display settings**.

## Low-resolution black-and-white displays

This is the most demanding case, for example the TRMNL OG. Set:

| Setting | Value | Why |
|---|---|---|
| **E-ink optimization** | On | Enables the black-and-white conversion below. |
| **Display levels** | 2 | Tells the renderer the display has no gray levels. |
| **Font family** | TRMNL (default for the TRMNL OG) | A pixel font designed for low-resolution e-ink. |
| **Pixel-perfect text** | On (default) | Draws text only at sizes where the font is sharp, without gray edges. |
| **Black text** | Off | Not needed with the setting below: gray text already turns black. |
| **Black dividers** | Off | Not needed with the setting below: gray dividers already turn black. |
| **Advanced → Dither algorithm** | Black and white (every non-white pixel black) | Turns every non-white pixel black instead of a dot pattern. |

Save the form. When you enable **E-ink optimization**, the form opens
again with the **Advanced** section expanded so you can pick the dither
algorithm before saving.

The result is an image with exactly two colours. Text, icons and
dividers are solid black; gray elements (secondary labels, gray icon
circles, light dividers) also become solid black.

On a **high-resolution** black-and-white display (for example the TRMNL
RGB) the **Black and white** dither algorithm is still useful to avoid
dot patterns, but Roboto (the default there) is sharp enough, so the
TRMNL font and pixel-perfect text are optional.

## Low-resolution displays with gray levels

Displays with 4 gray levels at about 125 pixels per inch (for example
the reTerminal E1001) can show gray areas, but small anti-aliased text
still breaks up when the edges are reduced to four shades. Set:

| Setting | Value | Why |
|---|---|---|
| **Font family** | TRMNL (default for the E1001) | Glyphs are drawn on the pixel grid. |
| **Pixel-perfect text** | On (default) | Renders text without gray edges. |
| **Black text** | On if gray labels look speckled | Keeps secondary labels solid. |
| **Black dividers** | On if dividers look dotted | Keeps list dividers solid. |

Gray icon circles, graph fills and other larger areas keep their gray
levels.

With **E-ink optimization** on, the **None (nearest color)** dither
algorithm maps every pixel to the closest of the display's gray levels
without dot patterns. It suits dashboards made of flat areas and text;
choose a dithering algorithm instead for photos or smooth gradients.
Avoid it on black-and-white displays: there it turns light grays (such
as gray text and dividers) white, so use **Black and white** instead.

## If your device dithers the image itself

Some devices, such as the Seeed reTerminal series, are driven by a Home
Assistant integration that converts the image for the display itself.
For these, leave **E-ink optimization** off to avoid processing the
image twice, and instead set:

| Setting | Value |
|---|---|
| **Pixel-perfect text** | On (default) |
| **Black text** | On |
| **Black dividers** | On |

**Black text** keeps names and labels solid black, so the device's
dithering cannot turn them into a speckled gray pattern. **Black
dividers** does the same for list dividers, separators and left card
bars, which would otherwise become dotted lines.

## If you prefer dithering

On a black-and-white display, choose a dithering algorithm (for example
**Floyd-Steinberg**) instead of **Black and white** if you want gray
areas such as graph fills or "today" markers to stay visually lighter
than black. Gray then becomes a dot pattern. On a low-resolution display
each dot is large enough to see, which makes small gray text hard to
read, so also turn on **Black text**. Thin light-gray lines such as list
dividers become dotted or broken lines; turn on **Black dividers** to
keep them solid. Chart grid lines and graph fills are not affected and
keep their lighter dithered look.

## Widget layout tips

These matter most on low-resolution displays, where every pixel counts.

- **Keep text at 12 px or larger.** TRMNL has no smaller size; with
  **Pixel-perfect text**, smaller sizes are rounded up to 12 px. In list
  widgets (calendar, waste schedule, entities) a **Max row height** of
  about 22 px or more keeps rows readable.
- **List rows scale with pixel density.** When **Max row height** is
  left empty, list rows keep the same physical size on every device
  preset: 56 px on a 212 ppi Kindle Paperwhite, about 33 px on a
  7.5" 800 x 480 panel and 79 px on a 300 ppi Kindle. For a custom
  display, enter its **Pixel density (PPI)** in the custom resolution
  step or later in **Device settings**; without it rows default to
  56 px.
- **Graph grid lines are dotted on 2-level displays.** The graph's
  optional grid lines (**Axes** section) are drawn as dotted black
  lines when the display is set to 2 levels, so they stay faint
  without dithering.
- **Hide small icons in dense lists.** At small row heights the icon
  circles are only a few pixels wide and turn into solid dots. Use
  **Hide icon** in the widget's **Appearance** section.
- **Use thin dividers.** The default divider width of 1 px stays crisp.
  Set **Divider width** to 0 to remove dividers entirely.
- **Use bold sparingly at small sizes.** Bold text needs more pixels to
  stay legible; it works best at 16 px and above.

## Troubleshooting

- **Text still looks blurry or blobby.** Check that **Font family** is
  TRMNL and **Pixel-perfect text** is on. Roboto is an outline font and
  cannot be rendered pixel-perfect.
- **Gray still appears in the image.** **Black and white (every
  non-white pixel black)** only takes effect with **E-ink optimization**
  on and **Display levels** set to 2.
- **The editor preview looks smoother than the display.** The Lovelace
  editor preview is drawn by your browser on a high-density screen,
  which hides the problems of a low-resolution panel. Check the image
  entity at 100 % zoom or the device itself for the final result.

See [Fonts and non-Latin scripts](fonts.md) for details on the font
options.

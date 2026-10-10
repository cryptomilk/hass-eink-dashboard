# Sharp text on black-and-white displays

Displays that can only show black and white (for example the TRMNL OG,
or any display configured with 2 display levels) cannot show gray. Every
gray pixel the renderer produces has to become black, white, or a dot
pattern. Text suffers most: anti-aliased edges and gray labels turn into
blobs or speckles, especially at small sizes and in bold.

Follow the steps below to get pure black-and-white output with crisp
text.

## Recommended settings

Open **Settings → Devices & Services → E-Ink Dashboard → Configure →
Display settings** and set:

| Setting | Value | Why |
|---|---|---|
| **E-ink optimization** | On | Enables the black-and-white conversion below. |
| **Display levels** | 2 | Tells the renderer the display has no gray levels. |
| **Font family** | TRMNL | TRMNL is a pixel font designed for e-ink. |
| **Pixel-perfect text** | On (default) | Draws text only at sizes where the font is sharp, without gray edges. |
| **Black text** | Off | Not needed with the setting below: gray text already turns black. |
| **Advanced → Dither algorithm** | None (pure black and white) | Turns every non-white pixel black instead of a dot pattern. |

Save the form. When you enable **E-ink optimization**, the form opens
again with the **Advanced** section expanded so you can pick the dither
algorithm before saving.

The result is an image with exactly two colours. Text, icons and
dividers are solid black; gray elements (secondary labels, gray icon
circles, light dividers) also become solid black.

## If your device dithers the image itself

Some devices, such as the Seeed reTerminal series, are driven by a Home
Assistant integration that converts the image for the display itself.
For these, leave **E-ink optimization** off to avoid processing the
image twice, and instead set:

| Setting | Value |
|---|---|
| **Pixel-perfect text** | On (default) |
| **Black text** | On |

**Black text** keeps names and labels solid black, so the device's
dithering cannot turn them into a speckled gray pattern.

## If you prefer dithering

Choose a dithering algorithm (for example **Floyd-Steinberg**) instead
of **None** if you want gray areas such as graph fills or "today"
markers to stay visually lighter than black. Gray then becomes a dot
pattern, which makes small gray text hard to read, so also turn on
**Black text**.

## Widget layout tips

- **Keep text at 12 px or larger.** TRMNL has no smaller size; with
  **Pixel-perfect text**, smaller sizes are rounded up to 12 px. In list
  widgets (calendar, waste schedule, entities) a **Max row height** of
  about 22 px or more keeps rows readable.
- **Hide small icons in dense lists.** At small row heights the icon
  circles become solid black dots. Use **Hide icon** in the widget's
  **Appearance** section.
- **Use thin dividers.** The default divider width of 1 px stays crisp.
  Set **Divider width** to 0 to remove dividers entirely.
- **Use bold sparingly at small sizes.** Bold text needs more pixels to
  stay legible; it works best at 16 px and above.

## Troubleshooting

- **Text still looks blurry or blobby.** Check that **Font family** is
  TRMNL and **Pixel-perfect text** is on. Roboto is an outline font and
  cannot be rendered pixel-perfect.
- **Gray still appears in the image.** **None (pure black and white)**
  only takes effect with **E-ink optimization** on and **Display levels**
  set to 2.
- **The editor preview looks smoother than the display.** The Lovelace
  editor preview is drawn by your browser, which may smooth text. Check
  the image entity or the device itself for the final result.

See [Fonts and non-Latin scripts](fonts.md) for details on the font
options.

# Weather Wall Widget

The **Weather Wall** widget is a full-panel forecast for a display
on the wall: the day or night ahead, a two-hourly strip with a
rain-probability profile, and the week's outlook. It is designed for
800 × 480 colour e-ink, such as a Spectra 6 panel, and scales to any
size, keeping its 5:3 proportions.

Unlike the stock **Weather** widget, it takes over the whole canvas:
it paints its own background and is meant to be the only widget on
its dashboard.

## 1. What it needs

| Entity | Required | Used for |
|---|---|---|
| A `weather` entity | Yes | Daily forecast for the headline and the outlook; hourly forecast for the two-hourly strip, frost warnings and the night icon |
| `sun.sun` | Yes (built in) | When the evening layout becomes night, and which hours are drawn dark |
| A moon phase sensor | No | The moon's phase at night; the [Moon](https://www.home-assistant.io/integrations/moon/) integration's `sensor.moon_phase` by default |
| A temperature sensor | No | A live reading for the morning headline instead of the forecast maximum |

If the weather entity or its daily forecast is missing, for example
while Home Assistant is still starting, the widget does not render a
blank panel: the last good image is kept and the render is retried
shortly. If the integration provides no hourly forecast, the strip
shows a short note instead and the rest of the panel is drawn from
the daily forecast.

## 2. Layouts

The widget chooses one of three layouts by the time of day:

- **Morning**, until 17:00: today's maximum, tonight's minimum, and
  the hours ahead.
- **Evening**, from 17:00 while the sun is up: tonight's minimum
  with the times of sunset and sunrise, and tomorrow's hours from
  07:00 to 19:00.
- **Night**, once the sun has set: as evening, with the moon and any
  cloud as the main icon and a frost warning when the night calls
  for one. On the six-colour palette the left-hand block turns
  black.

The outlook along the bottom starts with tomorrow in the morning
and with the day after in the evening, since tomorrow is then on the
right.

Notes under a day mark weather that is unusual for the time of
year; see [Climatology for the Weather Wall widget](climatology.md).
Without that table, nights of 4 °C or below are still noted.

## 3. Options

| Option | Default | Description |
|---|---|---|
| Entity | — | The weather entity |
| Forecast days | 7 | Days in the outlook, 3 to 7, limited by what the integration provides |
| Moon phase sensor | `sensor.moon_phase` | |
| Temperature sensor | — | Live reading for the morning headline |
| Climatology file | — | Path to the table described in [climatology.md](climatology.md) |
| Typeface | — | Empty uses the dashboard's font. A typeface named here, such as one in the custom font directory, is drawn at the widget's own sizes |
| Palette | From the display | Six colour, black-white-red-yellow, black-white-red, black-white-yellow or greyscale. The display's colour scheme chooses one automatically |
| Fonts | — | Weight overrides for the `headline`, `temperature`, `uv` and `text` roles |
| Hide UV below | 4 | UV index below which the morning badge is hidden |
| Warn on UV above | 5.5 | UV index above which the badge is drawn as a warning |
| Force layout (preview) | Automatic | Show the morning, evening or night layout regardless of the time, for previewing |

The layout is fixed, so the font roles change weight only, as with
the stock **Weather** widget.

## 4. Units

Figures are shown in the weather entity's own units, including
degrees Fahrenheit, miles per hour, knots and metres per second.
Frost warnings and the unusual-weather notes are worked out in
metric units internally, so they mean the same whatever units the
forecast arrives in.

# Climatology for the Weather Wall widget

The **Weather Wall** widget can add a short note under a day in its
outlook when that day's forecast is unusual for the time of year:
"mild 14°" for a warm night, "cold −6°" for a cold one, "UV 8" or
"gust 70". To judge what is unusual it needs a table of local
climate statistics, built once for your location.

Without the table the widget works normally, except that the only
note it can give is "min 2°" for a night at 4 °C or below.

## 1. Build the table

Run the script from a copy of this repository, on any computer with
Python 3. It uses only the standard library.

```bash
python3 scripts/build_climatology.py \
    --latitude 51.48 --longitude -0.01 --output climatology.json
```

| Option | Description |
|---|---|
| `--latitude`, `--longitude` | Your location in decimal degrees, negative west of Greenwich and south of the equator |
| `--timezone` | IANA time zone used to group hours into days, e.g. `Europe/London`. The default, `auto`, takes it from the coordinates |
| `--output` | File to write (default: `climatology.json` in the current directory) |

It downloads about thirty years of daily data from
[Open-Meteo](https://open-meteo.com/) and takes a few minutes. The
table does not need rebuilding until the next thirty-year normals
are published, though rerunning it now and then lengthens the
ultraviolet record.

The coordinates are used only for the download and are not written
into the table. They need not be precise: the underlying data is on
a grid about 25 km across.

## 2. Install it

Copy `climatology.json` into your Home Assistant configuration
directory, **outside** `custom_components`, for example:

```
/config/eink_dashboard/climatology.json
```

Then open the Weather Wall widget in the editor and enter that path
as **Climatology file**. The file is read on the next render, and
read again whenever it changes, so no restart is needed.

Do not put the file inside `custom_components/eink_dashboard`: an
update of the integration replaces that directory and would delete
it.

## 3. What is in the table

For each calendar date, the table holds percentiles (1st to 99th) of
the daily maximum and minimum temperature, the maximum wind gust and
the rainfall, gathered from every day within a week either side of
that date across 1991 to 2020, the standard period used for climate
normals. The ultraviolet index comes from a shorter record, from
2022, and uses a wider window to compensate.

A day is noted when its UV index or gust passes the 90th percentile
for its date, or when its overnight minimum falls outside the 10th
to 90th percentiles. UV is considered only from an index of 5 and
gusts only from 45 km/h, so a breezy day in a calm month is not
called unusually gusty. If several measures qualify, the one
furthest beyond its threshold is shown. If none does, a night at
4 °C or below still gets its "min" note.

## Data and licence

Temperature, gust and rainfall come from the ERA5 reanalysis through
the Open-Meteo historical weather API; the ultraviolet index comes
from CAMS through the Open-Meteo air quality API. Open-Meteo data is
licensed under
[CC BY 4.0](https://open-meteo.com/en/license).

# E-Ink Dashboard for Home Assistant

Home Assistant custom component that renders e-ink dashboard images as PNG
from entity state using SVG templates rasterised by resvg, and serves them
to Kindle, TRMNL, and [OpenDisplay](https://opendisplay.org/) devices. No
headless browser or other server component required running.

## Features

- **Multiple e-ink displays** - create a separate dashboard for each device
  with its own layout, resolution, and refresh interval
- **Device presets** - built-in profiles for Kindle 4/5, Paperwhite 1-4,
  Oasis 2/3, TRMNL OG/X/RGB, or enter a custom resolution
- **Portrait and landscape** - rotation is handled automatically based on the
  device preset and chosen orientation
- **WYSIWYG Lovelace editor** - drag, resize, and configure widgets on a
  server-rendered SVG preview that matches your device's exact pixel dimensions
- **Pull and push delivery** - devices can fetch the image on their own
  schedule (Kindle, OpenDisplay) or have HA push it via webhook (TRMNL)
- **E-ink optimization** - optional post-processing pipeline: autocontrast,
  sharpness, contrast adjustment, and grayscale quantization (2/4/16/256
  levels with Floyd-Steinberg dithering)
- **Jinja2 templates** - heading widgets support Home Assistant templates
  (e.g. `{{ now().strftime('%H:%M') }}`)
- **ETag support** - conditional HTTP responses so devices skip the download
  and e-ink refresh when the image has not changed
- **Webhook rate limiting** - push targets are throttled to one push per 5
  minutes with a 5 MB size cap

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance.
2. Click the three-dot menu → **Custom repositories**.
3. Add `https://github.com/cryptomilk/hass-eink-dashboard` with
   category **Integration**.
4. Search for "E-Ink Dashboard" and click **Download**.
5. Restart Home Assistant.

Once the repository is included in the HACS default store, steps 2–3 can
be skipped.

### Manual

1. Download `eink_dashboard.zip` from the
   [latest release](https://github.com/cryptomilk/hass-eink-dashboard/releases/latest).
2. Extract into `custom_components/eink_dashboard/`:

   ```bash
   mkdir -p /path/to/homeassistant/custom_components/eink_dashboard
   unzip eink_dashboard.zip -d /path/to/homeassistant/custom_components/eink_dashboard/
   ```

3. Restart Home Assistant.

## Setup

Go to **Settings -> Devices & Services -> Add Integration** and search for
**E-Ink Dashboard**.

### Step 1 -- Device

| Field | Description |
|---|---|
| Name | Label for this dashboard (e.g. "Kitchen Kindle") |
| Device model | Select your e-ink display from the preset list, or choose **Custom** to enter a resolution manually |
| Orientation | Portrait or landscape layout |
| Area | Optional - assign the device to a Home Assistant area |
| Update interval | How often to re-render, in seconds (default: 60) |

Supported device presets:

| Preset | Resolution | Grayscale levels |
|---|---|---|
| Kindle 4/5 | 600 × 800 | 16 |
| Kindle Paperwhite 1/2/3 | 758 × 1024 | 16 |
| Kindle Paperwhite 4 | 1072 × 1448 | 16 |
| Kindle Oasis 2/3 | 1264 × 1680 | 16 |
| TRMNL OG | 800 × 480 | 2 (black & white) |
| TRMNL X | 1872 × 1404 | 16 |
| TRMNL RGB | 2560 × 1440 | 2 (black & white) |
| Custom | user-defined | 16 |

### Step 2 -- Image delivery

For **Custom** devices, you get a choice:

- **Pull only** - the device fetches the image from HA on its own schedule.
  Choose this for Kindle.
- **TRMNL webhook** - HA pushes the rendered PNG to TRMNL after each render.
  See [TRMNL setup](#trmnl) below.

For **Kindle** presets, the integration is configured in pull mode
automatically. For **TRMNL** presets, you are guided through the webhook
setup.

### Reconfigure

After setup, click **Configure** on the integration entry to:

- **Device settings** - change device model, orientation, or area
- **Display settings** - update interval, e-ink optimization toggle,
  grayscale levels, sharpness, contrast
- **Add / remove push target** - manage TRMNL webhook URLs
- **Copy card YAML** - get the Lovelace card snippet for this device
- **Copy dashboard YAML** - get a full dashboard YAML with cards for all
  configured devices

## Dashboard setup

The component ships a WYSIWYG Lovelace card for editing the dashboard layout.

### Quick start

1. Go to **Settings -> Dashboards -> Add Dashboard**. Give it a name
   (e.g. "Kitchen Kindle") and save.

2. Open the new dashboard, click the three-dot menu -> **Edit dashboard** ->
   **Raw configuration editor**.

3. Paste the YAML. You can get it from the integration's **Configure** menu
   (**Copy card YAML** or **Copy dashboard YAML**), or write it manually:

   ```yaml
   views:
     - title: E-Ink Dashboard
       cards:
         - type: custom:eink-dashboard-card
           config_entry: <entry_id>
   ```

   The `config_entry` field selects which display to edit. Find the entry ID
   in the integration URL or use the **Copy card YAML** option. If you only
   have one E-Ink Dashboard entry, you can omit `config_entry` and the card
   will auto-discover it.

4. Save. The card shows a live server-rendered SVG preview at the exact pixel
   dimensions of your device.

### Editing widgets

1. Click **Edit Widgets** to open the editor panel.
2. Add widgets from the dropdown, reorder them with the up/down buttons, and
   configure each widget's properties in the form.
3. Click **Save** to persist the layout. The image entity is refreshed
   immediately.
4. Click **Show rendered image** to fetch the actual server-rendered PNG for
   a preview of what the device will display.

### Available widgets

| Type | What it renders |
|---|---|
| Heading | Static or Jinja2 template text (e.g. `{{ now().strftime('%H:%M') }}`) |
| Separator | Full-width horizontal or vertical rule |
| Entity | Label / state row for a single entity |
| Entities | Label / state rows for a list of entities, with optional title |
| Tile | Card-style tile with icon and entity state |
| Sensor | Entity state with sparkline history graph |
| Weather | Current conditions + N-day forecast with icons |
| Device Battery | Battery level indicator for a device |
| [Waste Schedule](docs/waste_schedule.md) | Upcoming waste collection dates (today, tomorrow, in N days) |

All widgets support `x`, `y` positioning. Most support a `w` (width) override
to constrain rendering to a sub-region of the display.

## Device setup

### Kindle

Use [kndl-online-screensaver](https://codeberg.org/cryptomilk/kndl-online-screensaver/)
on your Kindle. It supports ETag-based conditional fetching (skips the
download and e-ink refresh when the image has not changed) and battery
reporting.

Point it at the public image endpoint:

```
http://<ha-ip>:8123/api/eink_dashboard/<entry_id>/image.png
```

This endpoint requires no authentication.

#### Kindle and HTTPS (nginx)

Older Kindles cannot connect to modern HTTPS servers. If Home Assistant is
behind an HTTPS reverse proxy, add an HTTP-only location for the image
endpoint:

```nginx
server {
    listen 80;
    server_name homeassistant.example.com;

    # E-Ink dashboard image - plain HTTP for Kindle
    location ~ ^/api/eink_dashboard/[^/]+/image\.png$ {
        proxy_pass http://127.0.0.1:8123;
    }

    # Everything else → HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}
```

This exposes only the unauthenticated image endpoint over HTTP. The
authenticated layout API remains HTTPS-only.

### TRMNL

1. Go to [usetrmnl.com](https://usetrmnl.com) -> **Plugins** -> **Webhook Image**.
2. Give the plugin a name, set **Image Fit Mode** to **Contain**, and click
   **Save**.
3. Copy the **Webhook URL** (looks like
   `https://trmnl.com/api/custom_plugins/<uuid>`).
4. During the HA config flow, choose **TRMNL webhook** and paste the URL.

HA pushes the rendered PNG to TRMNL whenever the image changes, subject to a
minimum interval of 5 minutes and a 5 MB size cap per push.

You can add multiple TRMNL webhook targets per dashboard entry via
**Configure -> Add push target**.

### OpenDisplay

[OpenDisplay](https://opendisplay.org/) fetches images from Home Assistant's
Media Browser. The integration registers a **Media Source** platform that
exposes each dashboard entry as a media item, so OpenDisplay can pull the
latest rendered PNG without any additional configuration.

In the OpenDisplay app, point it at your Home Assistant instance and select
the dashboard entry from the Media Browser. OpenDisplay will refresh the image
on its own schedule, respecting the ETag so it only re-renders the display
when the image has actually changed.

## License

Apache 2.0 -- see [LICENSE](LICENSE).

Weather icons from [erikflowers/weather-icons](https://github.com/erikflowers/weather-icons),
licensed under SIL Open Font License 1.1.

Roboto font by Google, licensed under Apache 2.0.

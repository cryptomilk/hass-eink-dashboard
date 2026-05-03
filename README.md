# hass-eink-dashboard

Home Assistant custom component that renders e-ink dashboard images as PNG
directly from entity state using Pillow, and serves them to Kindle and TRMNL
devices. No Chromium, no ImageMagick, no Node.js.

## Installation

1. Download `eink_dashboard-<version>.tar.gz` from the
   [releases page](https://github.com/cryptomilk/hass-eink-dashboard/releases).
2. Extract it into your Home Assistant `custom_components/` directory:

   ```bash
   tar xzf eink_dashboard-0.1.0.tar.gz -C /path/to/homeassistant/custom_components/
   ```

3. Restart Home Assistant.

## Setup

Go to **Settings → Devices & Services → Add Integration** and search for
**E-Ink Dashboard**.

### Step 1 — Display

| Field | Description |
|---|---|
| Name | Label for this dashboard (e.g. "Kitchen Kindle") |
| Width / Height | Pixel dimensions — must match your device exactly |
| Update interval | How often to re-render, in seconds (default: 60) |

Common resolutions:

| Device | Width | Height |
|---|---|---|
| Kindle 4 / 5 | 600 | 800 |
| Kindle Paperwhite 1–3 | 758 | 1024 |
| Kindle Paperwhite 4 | 1072 | 1448 |
| Kindle Oasis 2 / 3 | 1264 | 1680 |
| TRMNL OG | 800 | 480 |
| TRMNL X | 1872 | 1404 |

### Step 2 — Image delivery

- **Pull only** — the device fetches the image from HA on its own schedule.
  Choose this for Kindle.
- **TRMNL webhook** — HA pushes the rendered PNG to TRMNL after each render.
  See [TRMNL setup](#trmnl-setup) below.

### Options (reconfigure)

After setup, click **Configure** on the integration to:

- Add or remove TRMNL push targets
- Adjust display settings: e-ink optimization, grayscale levels, sharpness,
  contrast

## Lovelace card

The component ships a WYSIWYG card for editing the dashboard layout. The
easiest setup is a dedicated Lovelace dashboard for each e-ink device.

1. Go to **Settings → Dashboards → Add Dashboard**. Give it a name (e.g.
   "Kitchen Kindle") and save.

2. Open the new dashboard, click the **⋮** menu → **Edit dashboard** →
   **Raw configuration editor**.

3. Replace the contents with:

   ```yaml
   views:
     - title: E-Ink Dashboard
       cards:
         - type: custom:eink-dashboard-card
   ```

   The card auto-discovers the integration's config entry. If you have
   multiple E-Ink Dashboard entries, add `config_entry: <entry_id>` to
   select a specific one (the entry ID is visible in the integration URL).
   Save.

4. The card shows a live canvas preview at the exact pixel dimensions of your
   device.

5. Click **Edit Widgets** to open the editor panel: add, reorder, and
   configure widgets.

6. Click **Save** to persist the layout. The image entity is refreshed
   immediately.

7. Click **Show rendered image** to fetch the actual Pillow-rendered PNG for
   a pixel-exact comparison with the canvas preview.

## Widgets

| Type | What it renders |
|---|---|
| `text` | Static or Jinja2 template text (e.g. `{{ now().strftime('%H:%M') }}`) |
| `line` | Horizontal or diagonal line |
| `separator` | Full-width horizontal rule |
| `weather` | Current conditions + N-day forecast with icons |
| `sensor_rows` | Label → value rows for a list of sensors |
| `battery_bar` | Horizontal battery level bar |
| `status_icons` | Row of filled/outline squares for binary sensors |
| `waste_schedule` | Upcoming waste collection dates |

## Kindle setup

Use [kndl-online-screensaver](https://codeberg.org/cryptomilk/kndl-online-screensaver/)
on your Kindle. It supports ETag-based conditional fetching (skips the
download and e-ink refresh when the image has not changed) and battery
reporting.

Point it at the public image endpoint:

```
http://<ha-ip>:8123/api/eink_dashboard/<entry_id>/image.png
```

This endpoint requires no authentication.

### Kindle and HTTPS (nginx)

Older Kindles cannot connect to modern HTTPS servers. If Home Assistant is
behind an HTTPS reverse proxy, add an HTTP-only location for the image
endpoint:

```nginx
server {
    listen 80;
    server_name homeassistant.example.com;

    # E-Ink dashboard image — plain HTTP for Kindle
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

## TRMNL setup

1. Go to [usetrmnl.com](https://usetrmnl.com) → **Plugins** → **Webhook Image**.
2. Give the plugin a name, set **Image Fit Mode** to **Contain**, and click
   **Save**.
3. Copy the **Webhook URL** (looks like
   `https://trmnl.com/api/custom_plugins/<uuid>`).
4. During the HA config flow, choose **TRMNL webhook** and paste the URL.

HA will push the rendered PNG to TRMNL after each render cycle, subject to a
minimum push interval of 60 seconds.

## Development

```bash
pip install cairosvg           # build-time only, for icon generation
tox -e test                    # run all tests
tox -e lint                    # ruff check
tox -e format                  # ruff format check
tox -e typecheck               # ty type checker

python3 scripts/build_icons.py # regenerate weather icon PNGs
bash scripts/build_dist.sh     # build distributable tar.gz into dist/
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

Weather icons from [erikflowers/weather-icons](https://github.com/erikflowers/weather-icons),
licensed under SIL Open Font License 1.1.

Roboto font by Google, licensed under Apache 2.0.

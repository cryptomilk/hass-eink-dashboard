# TRMNL Setup

## Create a Webhook Image Plugin

1. Go to [trmnl.com](https://trmnl.com) → **Plugins** → **Webhook Image**
2. Give it a name, set **Image Fit Mode** to **Contain** (shows the full image
   without cropping — correct for a pixel-matched dashboard), and click **Save**
3. Copy the **Webhook URL** — it looks like:
   `https://trmnl.com/api/custom_plugins/<uuid>`

## Send an image

```bash
curl -s -w "\nHTTP %{http_code} — %{size_upload} bytes sent\n" \
  -X POST "https://trmnl.com/api/custom_plugins/<uuid>" \
  --data-binary @tests/data/trmnl_og_test.png \
  -H "Content-Type: image/png"
```

A successful push returns HTTP 200. The image appears on the device at its next
scheduled refresh (or immediately if the device is awake and polling).

## Image requirements

| Model | Resolution | Color depth |
|---|---|---|
| TRMNL OG | 800 × 480 | 1-bit (black/white) |
| TRMNL X | 1872 × 1404 | 4-bit (16 grayscale) |

The image must match the device's color depth exactly — an 8-bit grayscale PNG
sent to a 1-bit device puts the plugin in a degraded state.

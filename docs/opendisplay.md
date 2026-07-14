# Setting Up OpenDisplay for Image Push

How to get fresh images onto a battery-powered OpenDisplay device, even
though it spends most of its time asleep.

## Why this is needed

To save battery, an OpenDisplay device spends most of its life in deep
sleep with its Bluetooth radio off. It only wakes up briefly, on a timer
or when you press its wake button, and is reachable over Bluetooth for a
short window before going back to sleep. If nothing connects and pushes an
image during that window, the display goes back to sleep with whatever was
on screen before.

So the setup has two parts:

1. Configure the device to wake up regularly (e.g. every 5 minutes).
2. Have Home Assistant notice the moment it wakes up and push a new image

**You'll need an ESPHome Bluetooth proxy nearby.** This guide uses one to
detect the device's wake-up advertisement and as the Bluetooth bridge Home
Assistant connects through to push the image. If you don't already have one
running near the display, set that up first — see [ESPHome's Home
Assistant getting started guide](https://esphome.io/guides/getting_started_hassio/).
A small ESP32 board such as the M5Stack ATOM Lite (SKU: C008) works well
and is cheap enough to dedicate one per display if needed.

## Step 1 — Configure the display's sleep timer

In the device's settings, set:

- **Deep sleep between updates**: how often it wakes up, e.g. every 5
  minutes. Shorter means fresher images but more battery use.
- **Awake timeout**: how long it stays reachable after waking before going
  back to sleep if nothing connects. 40 seconds is a typical default and is
  usually enough.

## Step 2 — Find the display's Bluetooth address

You'll need this to tell Home Assistant which device just woke up. Find it
once using any of:

- Home Assistant's Bluetooth integration device list.
- The device's serial log, if you have a cable handy.

## Step 3 — Detect the wake-up with an ESPHome Bluetooth proxy

A nearby ESPHome Bluetooth proxy can watch for the display's Bluetooth
advertisement and tell Home Assistant the instant it wakes up. This requires
the proxy to be a managed ESPHome device (not the stock "quick install"
Bluetooth Proxy firmware — see [ESPHome's Home Assistant getting started
guide](https://esphome.io/guides/getting_started_hassio/) if you need to
set one up) so you can add this configuration:

```yaml
esp32_ble_tracker:
  on_ble_advertise:
    - mac_address:
        - AA:BB:CC:DD:EE:01   # kitchen display (OD1A2B3C)
        - AA:BB:CC:DD:EE:02   # hallway display (OD4F5E6D)
      then:
        - homeassistant.event:
            event: esphome.opendisplay_awake
            data:
              mac: !lambda 'return x.address_str();'
```

List every display's MAC address here. One block covers all of them — Home
Assistant can tell which one fired the event by checking `mac` in the
automation below.

## Step 4 — Push the image when the display wakes up

Create an automation per device:

```yaml
alias: Push image to OpenDisplay - Kitchen
triggers:
  - trigger: event
    event_type: esphome.opendisplay_awake
    event_data:
      mac: AA:BB:CC:DD:EE:01
conditions:
  - condition: state
    entity_id: binary_sensor.kitchen_e_ink_display_connectivity
    state: "on"
actions:
  - action: opendisplay.upload_image
    data:
      refresh_mode: full
      device_id: 0123456789abcdef0123456789abcdef
      image:
        media_content_id: media-source://eink_dashboard/example-image-id
        media_content_type: image/png
  - delay: "00:01:00"
mode: single
max_exceeded: silent
```

The trailing `delay` keeps the automation "busy" for a minute after the push
completes. The display re-advertises many times a second while it's awake,
which would otherwise re-trigger this automation and push the same image
repeatedly; `mode: single` plus the delay ensures only one push happens per
wake-up, and `max_exceeded: silent` hides the harmless warnings that come
from the extra triggers being ignored while the delay runs.

## Troubleshooting

- **Pushes sometimes miss the window**: increase the display's awake
  timeout — the round trip (proxy sees it, forwards the event, Home
  Assistant connects and pushes) needs to fit inside it, not just a bare
  connection.
- **Automation doesn't fire at all**: double check the ESPHome proxy is in
  Bluetooth range of the display, and that the MAC address is listed
  correctly under `mac_address`.

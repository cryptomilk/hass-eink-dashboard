# TRMNL Battery Widget

The **Device Battery** widget can display your TRMNL device's battery level
by reading it from the [TRMNL](https://www.home-assistant.io/integrations/trmnl)
Home Assistant core integration.

The TRMNL integration polls the TRMNL cloud API once per hour and creates a
standard `sensor.<device>_battery` entity that reports the battery percentage.
The eink-dashboard reads this entity's state whenever it renders the battery
widget.

## 1. Install the TRMNL integration

Go to **Settings → Devices & Services → Add Integration** and search for
**TRMNL**.

When prompted, enter your API key. You can find it at
[trmnl.com/account](https://trmnl.com/account) under **Your API Key**.

After setup, the integration creates several entities for each of your
TRMNL devices, including:

- `sensor.<device>_battery` — battery percentage (0–100 %)
- `sensor.<device>_battery_voltage` — raw battery voltage (disabled by
  default)
- `sensor.<device>_rssi` — Wi-Fi signal strength (disabled by default)

## 2. Create the eink-dashboard entry for your TRMNL

If you have not done this yet:

1. Go to **Settings → Devices & Services → Add Integration** and search for
   **E-Ink Dashboard**.
2. Select your TRMNL model (OG, X, or RGB) and follow the wizard to
   configure the webhook URL for image delivery.

## 3. Wire up the battery sensor

1. Open **Settings → Devices & Services → E-Ink Dashboard** and click
   **Configure** on your TRMNL dashboard entry.
2. Select **Device Settings**.
3. In the **Battery sensor** field, pick the `sensor.<device>_battery`
   entity created by the TRMNL integration.
4. Click **Submit**.

## 4. Add the Device Battery widget

In the dashboard editor, add a **Device Battery** widget. The widget renders
the battery percentage as an icon with a fill bar. It shows nothing when no
battery data is available.

## How it works

```
TRMNL device
  → TRMNL cloud API (updated by device on each wake cycle)
    → HA TRMNL integration polls every hour
      → sensor.<device>_battery entity in Home Assistant
        → eink-dashboard reads the entity state on each render
          → Device Battery widget displays the percentage
```

The eink-dashboard does not communicate with the TRMNL API directly.
It reads the battery level from the HA sensor entity, so the value is
as fresh as the TRMNL integration's last poll (at most one hour old).

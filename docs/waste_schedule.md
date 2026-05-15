# Waste Schedule Widget

The **Waste Schedule** widget displays upcoming collection dates read from
the [Waste Collection Schedule](https://github.com/mampfes/hacs_waste_collection_schedule)
integration (available via HACS).

The widget shows entries whose next collection falls within the next three
days (today, tomorrow, in 2 days, in 3 days). Entries further in the future
are hidden until they enter that window.

## 1. Install and configure the integration

Install **Waste Collection Schedule** via HACS, then go to
**Settings → Devices & Services → Add Integration** and search for
**Waste Collection Schedule**. Follow the wizard to select your country,
service provider, and address details.

## 2. Add a sensor with `appointment_types` format

After the integration is set up, you need a sensor configured with the
`appointment_types` details format. To add one:

1. Go to **Settings → Devices & Services → Waste Collection Schedule →
   Configure**.
2. Under **Sensors To Modify**, select **Add new sensor**.
3. On the next page, set **Details Format** to **`appointment_types`** and
   give the sensor a name (e.g. `Waste Schedule`).
4. Save.

With this format each attribute of the sensor represents one waste type and
its value is the ISO date of the next scheduled collection:

```
Organic Waste  →  2026-05-17
Paper          →  2026-05-22
Recycling      →  2026-05-20
```

The other formats (`upcoming`, `generic`) produce a different data shape
that the widget cannot read — `appointment_types` is required.

### YAML configuration (alternative)

If you prefer YAML instead of the config flow, add to `configuration.yaml`:

```yaml
waste_collection_schedule:
  sources:
    - name: your_provider   # see the integration docs for provider names
      args:
        # provider-specific address fields go here
  sensors:
    - name: "Waste Schedule"
      details_format: appointment_types
```

Restart Home Assistant. The resulting entity ID will be
`sensor.waste_schedule` (lower-cased from the sensor name).

## 3. Add the widget

In the dashboard editor, add a **Waste Schedule** widget and configure it:

| Field | Value |
|---|---|
| Entity | The `sensor.*` entity created above |
| Entries | One entry per waste type you want to show |

For each entry:

| Field | Value |
|---|---|
| Attribute | Attribute name on the sensor (e.g. `Organic Waste`) — must match exactly |
| Label | Short label shown on the display (e.g. `Organic`) |

By default the widget only shows entries whose next collection is within the
next three days. Enable **Show all upcoming dates** to display every
configured waste type regardless of how far away the next collection is.

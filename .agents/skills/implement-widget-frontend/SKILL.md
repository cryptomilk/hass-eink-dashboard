---
name: implement-widget-frontend
description: "Add TypeScript types in ha.d.ts and editor schema in eink-dashboard-editor.ts for a new widget type. Canvas preview was replaced by server-rendered SVGs in step 4.1; no frontend renderer is needed."
when_to_use: "When adding or updating a widget's TypeScript types or editor form. Run AFTER the Python renderer (implement-widget) is complete."
argument-hint: "[widget-type]"
arguments: widget-type
allowed-tools: Bash(pnpm *)
---

# Implement Widget Frontend: $widget-type

Add TypeScript types and editor schema for **$widget-type**. The card
fetches SVGs from the Python backend via WebSocket — no canvas renderer
is needed here.

## Before you start

1. Read existing type definitions in `frontend/src/types/ha.d.ts`.
2. Read existing schemas in `frontend/src/eink-dashboard-editor.ts`.
3. Use the widget config specifications below as the source of truth
   for which fields to expose.

## Existing TS widget type definitions

!`grep -n "interface\|^export type" custom_components/eink_dashboard/frontend/src/types/ha.d.ts`

## Widget config specifications

These are the canonical field lists for each widget type.  Use them
to determine which fields to add to the TypeScript interface and
which controls to add to the editor schema.

### Project-specific fields (all widgets)

Every widget config extends HA's card config with these
project-specific fields:

- `card_style` — `"border"` | `"left_bar"` | `"none"` (default:
  `"none"`).  Controls decorative frame around the widget.
- `icon_style` — `"filled"` | `"outlined"` | `"none"` (default:
  `"filled"`).  Controls icon circle rendering.

### Tile

Single-entity widget modelled after HA's Tile card.

Config fields (add to interface, expose in schema):
- `entity` (required) — any HA entity
- `name` — override display name
- `icon` — override icon (default: entity's domain icon)
- `hide_state` — boolean, suppress state text
- `state_content` — which state attribute(s) to display
- `show_entity_picture` — show entity picture instead of icon
- `card_style` — project-specific (see above)
- `icon_style` — project-specific (see above)

Fields intentionally omitted: `vertical`, `color`, `features`,
`features_position`, all `tap_action` / `hold_action` /
`double_tap_action` variants.

### Heading

Section heading with optional icon and entity badges, modelled
after HA's Heading card.

Config fields:
- `heading` — heading text
- `heading_style` — `"title"` | `"subtitle"`
- `icon` — MDI icon name (e.g. `"mdi:fridge"`)
- `badges` — list of entity badge configs
- `icon_style` — project-specific (default: `"none"`)

Fields intentionally omitted: `tap_action`.

### Sensor

Single-entity sensor with optional history graph, modelled after
HA's Sensor card.

Config fields:
- `entity` (required) — sensor, counter, input_number, number
- `name` — override display name
- `icon` — override icon
- `graph` — `"line"` | none (default: none)
- `hours_to_show` — history window (default: 24)
- `detail` — graph detail level (1 or 2)
- `unit` — unit override
- `limits` — `{ min?: number, max?: number }` for graph Y-axis
- `card_style` — project-specific (see above)
- `icon_style` — project-specific (see above)

Fields intentionally omitted: `theme`.

### Entity

Single-entity display with large value, modelled after HA's
Entity card.

Config fields:
- `entity` (required) — any HA entity
- `name` — override display name
- `icon` — override icon
- `attribute` — show a specific attribute instead of state
- `unit` — unit override
- `card_style` — project-specific (see above)
- `icon_style` — project-specific (see above)

Fields intentionally omitted: `state_color`, `theme`, all
`tap_action` / `hold_action` / `double_tap_action` variants.

### Entities

Multi-entity list card, modelled after HA's Entities card.

Config fields:
- `title` — optional card header text
- `icon` — optional header icon
- `entities` (required) — list of row configs:
  - Entity row: string entity ID, or
    `{ entity, name?, icon? }` object
  - Divider row: `{ type: "divider" }`
  - Section row: `{ type: "section", label? }`
- `card_style` — project-specific (see above)
- `icon_style` — project-specific (see above)

Fields intentionally omitted: `show_header_toggle`, `header`,
`footer`, `state_color`, `theme`.

### Clock

Digital time display, modelled after HA's Clock card.

Config fields:
- `title` — optional label above the time
- `clock_size` — `"small"` | `"medium"` | `"large"`
- `time_format` — 12h or 24h override
- `time_zone` — timezone override
- `show_seconds` — boolean (default: false)
- `card_style` — project-specific (see above)

Fields intentionally omitted: `clock_style` (digital only),
`no_background`, `seconds_motion`, `border`, `ticks`,
`face_style`.

### Weather, Separator, Device Battery, Waste Schedule

Keep existing frontend definitions unchanged.

## Implementation steps

### 1. Update TypeScript type definitions

In `frontend/src/types/ha.d.ts`:

**Add the widget interface:**

```typescript
export interface {WidgetName}Widget extends WidgetBase {
  type: "$widget-type";
  h?: number;
  entities?: string[];
  card_style?: CardStyle;
  title?: string;
}
```

Include only the fields the Python renderer actually reads. Omit fields
that belong to `WidgetBase` (`x`, `y`, `w`, `font_size`, `color`) since
those are inherited.

**Add to the `Widget` union type:**

```typescript
export type Widget =
  | TextWidget
  | SeparatorWidget
  | ...
  | {WidgetName}Widget;
```

### 2. Update editor schema

In `frontend/src/eink-dashboard-editor.ts`:

**Add to `WIDGET_TYPES`:**

```typescript
"$widget-type": {
  label: "Widget Name",
  description: "One-line description shown in the widget picker.",
  icon: "mdi:some-icon",
  defaults: {
    type: "$widget-type",
    x: 24, y: 0, w: 400, h: 112,
    entities: [],
    card_style: "none",
  },
},
```

**Add to `SCHEMAS`** — use grouped sections (Content expanded,
Layout and Appearance collapsed):

```typescript
"$widget-type": (d: DisplayConfig) => [
  // Content group (expanded)
  {
    type: "expandable", title: "Content",
    icon: "mdi:text", expanded: true,
    schema: [
      { name: "entities", required: true,
        selector: { entity: {
          multiple: true,
          filter: { domain: "sensor" },
        } } },
      { name: "title", required: false,
        selector: { text: {} } },
    ],
  },
  // Appearance group (collapsed)
  {
    type: "expandable", title: "Appearance",
    icon: "mdi:palette", expanded: false,
    schema: [
      { name: "card_style", required: false,
        selector: { select: { options: [
          { value: "border", label: "Border" },
          { value: "left_bar", label: "Left Bar" },
          { value: "none", label: "None" },
        ] } } },
    ],
  },
  // Layout group (collapsed)
  {
    type: "expandable", title: "Layout",
    icon: "mdi:ruler", expanded: false,
    schema: [
      { type: "grid", name: "", flatten: true, schema: [
        { name: "x", default: 24,
          selector: { number: {
            min: 0, max: d.width, step: 8, mode: "box",
          } } },
        { name: "y", default: 0,
          selector: { number: {
            min: 0, max: d.height, step: 8, mode: "box",
          } } },
        { name: "w", default: 400,
          selector: { number: {
            min: 50, max: d.width, step: 8, mode: "box",
          } } },
        { name: "h", default: 112,
          selector: { number: {
            min: 28, max: d.height, step: 8, mode: "box",
          } } },
      ] },
    ],
  },
],
```

**Entity domain filtering:** Use the correct domain filter for each
widget type:
- `sensor_rows` → `{ domain: "sensor" }`
- `status_icons` → `{ domain: "binary_sensor" }`
- `waste_schedule` → `{ domain: "sensor" }` (single entity from
  waste_collection_schedule)

### 3. Verify

```bash
pnpm --dir custom_components/eink_dashboard/frontend typecheck && \
pnpm --dir custom_components/eink_dashboard/frontend test
```

## Default values

The Python constant `DEFAULT_ROW_H = 56` (in `const.py`) is the
standard single-row height.  Use it as the basis for `h` defaults in
`WIDGET_TYPES` and `SCHEMAS`:

- Single-row widget: `h: 56`
- Two-row widget: `h: 112`  (= 2 × DEFAULT_ROW_H)
- Chip-style widget: `h: 28`

These values keep the frontend defaults in sync with the Python
renderer's own sizing baseline.

## Key references

- Python SVG renderer: `custom_components/eink_dashboard/svg_render.py`
- Sizing baseline: `DEFAULT_ROW_H = 56` in `const.py`
- Types: `frontend/src/types/ha.d.ts`
- Editor: `frontend/src/eink-dashboard-editor.ts`

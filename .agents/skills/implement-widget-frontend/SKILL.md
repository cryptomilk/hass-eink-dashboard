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

1. Read the **$widget-type** section in `REDESIGN_WIDGETS.md` for the
   design spec.
2. Read existing type definitions in `frontend/src/types/ha.d.ts`.
3. Read existing schemas in `frontend/src/eink-dashboard-editor.ts`.

## Existing TS widget type definitions

!`grep -n "interface\|^export type" custom_components/eink_dashboard/frontend/src/types/ha.d.ts`

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

## Key references

- Design spec: `REDESIGN_WIDGETS.md`
- Python SVG renderer: `custom_components/eink_dashboard/svg_render.py`
- Types: `frontend/src/types/ha.d.ts`
- Editor: `frontend/src/eink-dashboard-editor.ts`

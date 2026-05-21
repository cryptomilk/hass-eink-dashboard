---
name: implement-widget-frontend
description: "Add TypeScript types in ha.d.ts and editor schema in eink-dashboard-editor.ts for a new or updated widget type; also handles deprecating an old type (remove from picker, keep schema, add @deprecated JSDoc). Canvas preview was replaced by server-rendered SVGs in step 4.1; no frontend renderer is needed."
when_to_use: "When adding a new widget type, deprecating an existing one, or updating a widget's TypeScript types or editor form. Run AFTER the Python renderer (implement-widget) is complete. Must also update getSummary(), LABELS, and the ALL_TYPES arrays in the frontend test file."
argument-hint: "[widget-type]"
arguments: widget-type
allowed-tools: Read, Edit, Write, Bash(pnpm *)
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
- `card_style` — project-specific (see above)

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

**Add supporting interfaces** (if the widget has structured sub-items):

```typescript
/** One badge entry displayed beside the heading. */
export interface {WidgetName}Badge {
  /** HA entity ID. */
  entity: string;
  /** Override label; unused in current renderer but reserved. */
  name?: string;
  /** MDI icon name override (e.g. "mdi:thermometer"). */
  icon?: string;
  /** Show the entity state value next to the icon. Default: true. */
  show_state?: boolean;
  /** Render an icon alongside the badge text. Default: false. */
  show_icon?: boolean;
}
```

**Add the widget interface:**

```typescript
/** One-line summary of what this widget does. */
export interface {WidgetName}Widget extends WidgetBase {
  type: "$widget-type";
  /** Description of primary content field. */
  $main_field?: string;
  /** Ordered list of entity IDs or structured badge configs. */
  badges?: (string | {WidgetName}Badge)[];
  /** Decorative frame style. */
  card_style?: CardStyle;
  /** Icon circle rendering mode. */
  icon_style?: IconStyle;
}
```

Fields prefixed with `$` are placeholders — substitute the real field
name from the widget spec (e.g. `heading` for Heading, `entity` for
Tile).

Include only the fields the Python renderer actually reads. Omit fields
that belong to `WidgetBase` (`x`, `y`, `w`, `font_size`, `color`) since
those are inherited.  Document every member with a JSDoc comment.

**Add to the `Widget` union type:**

```typescript
export type Widget =
  | TextWidget      // @deprecated — kept for existing configs
  | SeparatorWidget
  | ...
  | {WidgetName}Widget;
```

### 2. Update editor schema

In `frontend/src/eink-dashboard-editor.ts`:

**Add to `WIDGET_TYPES`** (only widgets shown in the picker — deprecated
widgets are removed from here but their `SCHEMAS` entry is kept so
existing configs remain editable):

```typescript
"$widget-type": {
  label: "Widget Name",
  description: "One-line description shown in the widget picker.",
  icon: "mdi:some-icon",
  defaults: {
    type: "$widget-type",
    x: 24, y: 0, w: 400, h: 56,  // x: 24 = PADDING for content widgets
    $main_field: "",               // content-field default
    card_style: DEFAULT_CARD_STYLE,
    icon_style: DEFAULT_ICON_STYLE, // override per widget spec
  },
},
```

Use `x: 24` (= `PADDING`) for content widgets (entity, tile — anything
with internal text and icons) so newly created widgets land at the
standard canvas inset.  Use `x: 0` only for structural widgets that
span full width (separator, heading).

Include defaults for content fields so the form is pre-populated on
first open (e.g. `heading: ""`, `heading_style: "title"`).  Override
`icon_style` when the widget spec defines a different default (e.g.
Heading uses `"none"` instead of `DEFAULT_ICON_STYLE`).

**Add to `ICON_FALLBACK` in `frontend/src/eink-widget-picker.ts`** —
every `icon` value used in `WIDGET_TYPES` must have a text/emoji entry
in `ICON_FALLBACK`.  Without it the picker renders the raw MDI string
(e.g. `"format-list-bulleted"`) instead of a glyph.  Check whether the
icon is already present; add it only if missing:

```typescript
const ICON_FALLBACK: Record<string, string> = {
  // … existing entries …
  "mdi:some-icon": "X",   // add a short text or emoji fallback
};
```

**Add to `SCHEMAS`** — use `identitySection()` plus grouped sections
(`identitySection` first, Content expanded by default, Layout and
Appearance collapsed).  The `flatten: true` flag on each expandable
section merges the contained fields directly into the widget data
object rather than nesting them under a key:

```typescript
"$widget-type": (d: DisplayConfig) => [
  identitySection(),
  {
    name: "content",
    type: "expandable",
    flatten: true,
    expanded: true,
    title: "Content",
    icon: "mdi:text",
    schema: [
      { name: "$main_field", selector: { text: {} } },
      {
        name: "badges",
        selector: { entity: { multiple: true } },
      },
    ],
  },
  {
    name: "layout",
    type: "expandable",
    flatten: true,
    title: "Layout",
    icon: "mdi:move-resize",
    schema: [{ type: "grid", name: "", schema: posXYWH(d) }],
  },
  {
    name: "appearance",
    type: "expandable",
    flatten: true,
    title: "Appearance",
    icon: "mdi:palette",
    // Pass a default when the widget overrides DEFAULT_ICON_STYLE:
    //   iconStyleSelector("none")   — for Heading
    schema: [cardStyleSelector(), iconStyleSelector()],
  },
],
```

**Add to `getSummary()`** — return a short human-readable summary for
the widget list row.  Two common patterns:

```typescript
// Text-primary widgets (heading, text):
if (t === "$widget-type") {
  const s = String(widget.$main_field || "");
  return s.length > 30 ? s.slice(0, 30) + "…" : (s || "(empty)");
}

// Entity-primary widgets (tile, weather):
if (t === "$widget-type") {
  return widget.entity || "(no entity)";
}
```

**Add to `LABELS`** — every field name used in the schema that does not
already have a label entry needs one:

```typescript
$main_field: "Editor label for primary field",
```

**Entity domain filtering:** Use the correct domain filter for each
widget type:
- `tile`, `heading` → no domain filter (accepts any entity)
- `waste_schedule` → `{ domain: "sensor" }` (single entity from
  waste_collection_schedule)
- `device_battery` → `{ domain: "sensor" }` or no filter

**Visibility conditions:** Every widget form automatically gets a
collapsible Visibility section appended by `_buildVisibilityEditor()`
in `eink-dashboard-editor.ts`. Do NOT add a `visibility` field to the
widget's `SCHEMAS` entry — it would duplicate the auto-appended
section. The `visibility` field is typed as
`(Condition | LegacyCondition)[]` (both types exported from
`ha.d.ts`) on `WidgetBase`, so all widget interfaces inherit it.

### 3. Update frontend tests

In `frontend/test/eink-dashboard-editor.test.ts` there are two
`ALL_TYPES` constant arrays that must be kept in sync manually:

- `WIDGET_TYPES > ALL_TYPES` — lists only picker-visible types
  (i.e. what is in `WIDGET_TYPES`).  Update the count in the test
  description too (e.g. "has all N widget types").
- `SCHEMAS > ALL_TYPES` — lists every type with a schema builder
  (picker-visible + deprecated types kept for editing).  Update the
  count in the test description too.

The integration test `add-widget integration > appends a widget when a
type is selected from the picker` clicks a `data-type="…"` card.  If
you removed or renamed a widget type in the picker, update the
`data-type` attribute value in this test to an existing picker type.

### 4. Verify

```bash
pnpm --dir custom_components/eink_dashboard/frontend typecheck && \
pnpm --dir custom_components/eink_dashboard/frontend test
```

## Deprecating a widget type

When a widget type is superseded (e.g. `text` → `heading`):

1. **Remove from `WIDGET_TYPES`** so it no longer appears in the picker.
2. **Keep in `SCHEMAS`** so existing configs remain editable.
3. **Add `@deprecated` JSDoc** to the TypeScript interface in `ha.d.ts`.
4. **Update `AGENTS.md`** widget type list.
5. **Keep in the `Widget` union type** — removing it would break type
   narrowing for existing config objects.

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
- Tests: `frontend/test/eink-dashboard-editor.test.ts`

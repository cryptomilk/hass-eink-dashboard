---
name: implement-widget-frontend
description: "Implement a widget's canvas preview renderer in eink-dashboard-card.ts, TypeScript types in ha.d.ts, and editor schema in eink-dashboard-editor.ts. Must match the PIL renderer output."
when_to_use: "When adding or updating a widget's frontend preview, editor form, or TypeScript types. Run AFTER the Python renderer is complete."
argument-hint: "[widget-type]"
arguments: widget-type
allowed-tools: Bash(pnpm *)
---

# Implement Widget Frontend: $widget-type

Implement the frontend (TypeScript) side for **$widget-type**: canvas
preview, type definitions, and editor schema.

## Before you start

1. Read the **$widget-type** section in `REDESIGN_WIDGETS.md` for the
   design spec.
2. Read the Python renderer in `render.py` — the canvas renderer must
   produce visually matching output.
3. Read existing frontend renderers in
   `frontend/src/eink-dashboard-card.ts`.
4. Read existing schemas in `frontend/src/eink-dashboard-editor.ts`.
5. Read type definitions in `frontend/src/types/ha.d.ts`.

## Python sizing ratios (TS must match exactly)

!`grep -n "def _compute_metrics" -A 12 custom_components/eink_dashboard/render.py`

## Existing TS widget type definitions

!`grep -n "interface\|^export type" custom_components/eink_dashboard/frontend/src/types/ha.d.ts`

## Current TS shared helper signatures

!`grep -n "^export function\|^export const CHIP_\|^export interface Widget\|^export type Card" custom_components/eink_dashboard/frontend/src/eink-dashboard-card.ts custom_components/eink_dashboard/frontend/src/types/ha.d.ts`

## Implementation steps

### 1. Update TypeScript type definitions

In `frontend/src/types/ha.d.ts`, update the widget interface to match
the redesigned Python renderer's config. For redesigned widgets, add
`h` and `card_style` (if card-style), and remove `font_size` reliance.

**Redesigned card-style widget:**

```typescript
export interface {WidgetName}Widget extends WidgetBase {
  type: "$widget-type";
  h: number;
  entities?: string[];
  card_style?: CardStyle;
  title?: string;
}
```

**Redesigned chip-style widget:**

```typescript
export interface {WidgetName}Widget extends WidgetBase {
  type: "$widget-type";
  h: number;
  entities?: string[];
}
```

**Note:** `WidgetBase` still has optional `w` and `font_size` for
backward compatibility with TEXT and WEATHER. Redesigned widgets add
`h` as required and use `w` as the card/chip boundary width.

### 2. Add canvas preview renderer

In `frontend/src/eink-dashboard-card.ts`, add a
`_render{WidgetName}()` method.

**Available shared TS helpers** (do not reimplement):

- `computeMetrics(rowH)` → `WidgetMetrics` — same ratios as Python
- `drawCardContainer(ctx, x, y, w, h, m, cardStyle,
  grayscaleLevels?)` → returns content x-offset (number)
- `drawCardRow(ctx, x, y, w, rowH, m, opts: CardRowOpts)` → void
- `drawChip(ctx, x, y, h, text, font, border, opts?: ChipOpts)` →
  returns x after chip
- `drawChipFlow(ctx, x, y, w, h, chips: ChipDescriptor[], font,
  border)` → returns y after last row
- `chipWidth(ctx, h, text, font, hasIcon)` → returns total chip width
- `loadIcon(name, size)` → `Promise<HTMLImageElement | null>` (async)
- `getIcon(name)` → `HTMLImageElement | null` (sync, cached)
- `deviceClassIcon(deviceClass, state, domain)` → `string | null`
  (resolves entity device_class to MDI icon filename)
- `grayColor(v)` → `rgb(v, v, v)` string

### Usage notes

- `drawCardContainer` returns content x-offset per `cardStyle`:
  `"border"` → `m.padding`, `"left_bar"` → `barW + m.padding`,
  `"none"` → `0`. Default for all card widgets is `DEFAULT_CARD_STYLE`
  (`"none"`) — use `w.card_style ?? DEFAULT_CARD_STYLE`, not
  `w.card_style ?? "border"`.
- `drawCardRow` takes `CardRowOpts`: `primary` (required),
  `secondary?`, `value?`, `iconFill?`, `icon?`
  (`HTMLImageElement`).
- `drawChipFlow` takes `ChipDescriptor[]`: `text` (required),
  `inverted?`, `icon?` (`HTMLImageElement`).
- `drawChip` returns x after chip. `ChipOpts`: `inverted?`, `icon?`.
- Icons are async: call `loadIcon()` in the render method and pass
  the resolved `HTMLImageElement` to `drawCardRow`/`drawChip`. Use
  `getIcon()` for synchronous access to already-cached icons.

### MDI icons in canvas renderers

MDI SVGs are committed at `icons/svg/mdi/` and served at
`/eink_dashboard/icons/svg/mdi/`. Entity-based widgets resolve
icons via `deviceClassIcon(deviceClass, state, domain)`:

```typescript
const dc = attrs.device_class ?? "";
const domain = entityId.split(".")[0];
const iconName = deviceClassIcon(dc, state.state, domain);
const icon = iconName
  ? getIcon(`${ICON_BASE}/svg/mdi/${iconName}.svg`)
  : null;
```

`_preloadIcons()` already batch-loads MDI icons for all
entity-based widgets, so `getIcon()` returns synchronously at
render time. Pass the resolved `HTMLImageElement` (or null) to
`drawCardRow`/`drawChip` via the `icon` option.

**Card-style renderer pattern:**

```typescript
private _render{WidgetName}(
  ctx: CanvasRenderingContext2D,
  w: {WidgetName}Widget,
): WidgetBounds {
  const x = w.x ?? PADDING;
  const y = w.y ?? 0;
  const width = w.w ?? 350;
  const height = w.h;
  const entities = w.entities ?? [];
  const n = entities.length;
  if (n === 0) return { x, y, w: width, h: height };
  const rowH = Math.floor(height / n);
  const m = computeMetrics(rowH);

  const xOff = drawCardContainer(
    ctx, x, y, width, height, m,
    w.card_style ?? DEFAULT_CARD_STYLE,
  );
  const cx = x + xOff;
  // Subtract right-side padding for border so content stays
  // inside the border stroke (mirrors Python render pattern).
  const cardStyle = w.card_style ?? DEFAULT_CARD_STYLE;
  const cw = width - xOff - (cardStyle === "border" ? m.padding : 0);

  for (let i = 0; i < n; i++) {
    const rowY = y + i * rowH;
    const entityId = entities[i];
    const state = this._states?.[entityId];
    if (!state) continue;
    const attrs = state.attributes ?? {};
    drawCardRow(ctx, cx, rowY, cw, rowH, m, {
      primary: attrs.friendly_name ?? entityId,
      secondary: `${state.state}${
        attrs.unit_of_measurement ?? ""
      }`,
    });
    if (i < n - 1) {
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillRect(
        cx + m.padding,
        rowY + rowH,
        cw - 2 * m.padding,
        m.divider,
      );
    }
  }
  return { x, y, w: width, h: height };
}
```

**Chip-style renderer pattern:**

```typescript
private _render{WidgetName}(
  ctx: CanvasRenderingContext2D,
  w: {WidgetName}Widget,
): WidgetBounds {
  const x = w.x ?? PADDING;
  const y = w.y ?? 0;
  const width = w.w ?? 350;
  const height = w.h;
  const m = computeMetrics(height);
  const fontSize = Math.round(height * 0.46);
  const font = `${fontSize}px Roboto, sans-serif`;
  const chips: ChipDescriptor[] = (w.entities ?? [])
    .flatMap((entityId) => {
      const state = this._states?.[entityId];
      if (!state) return [];
      const attrs = state.attributes ?? {};
      return [{
        text: attrs.friendly_name ?? entityId,
        inverted: state.state === "on",
      }];
    });
  drawChipFlow(
    ctx, x, y, width, height, chips, font, m.border,
  );
  return { x, y, w: width, h: height };
}
```

### 3. Wire into _render() dispatch

Add the widget type to the dispatch object in `_render()`:

```typescript
const dispatch: Record<string, (w: Widget) => WidgetBounds> = {
  ...
  "$widget-type": (w) =>
    this._render{WidgetName}(ctx, w as {WidgetName}Widget),
};
```

### 4. Update editor schema

In `frontend/src/eink-dashboard-editor.ts`:

**Add to `WIDGET_TYPES`:**

```typescript
"$widget-type": {
  label: "Widget Name",
  defaults: {
    type: "$widget-type",
    x: 24, y: 0, w: 400, h: 112,
    entities: [],
    card_style: DEFAULT_CARD_STYLE,
  },
},
```

**Add to `SCHEMAS`** — use grouped sections (Content expanded,
Layout collapsed, Appearance collapsed):

```typescript
"$widget-type": (d: DisplayConfig) => [
  // Content group (expanded)
  { name: "entities", required: true,
    selector: { entity: {
      multiple: true,
      filter: { domain: "sensor" },
    } } },
  { name: "title", required: false,
    selector: { text: {} } },
  // Appearance group (collapsed)
  { name: "card_style", required: false,
    selector: { select: { options: [
      { value: "border", label: "Border" },
      { value: "left_bar", label: "Left Bar" },
      { value: "none", label: "None" },
    ] } } },
  // Layout group (collapsed)
  { type: "grid", name: "", schema: [
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
```

**Entity domain filtering:** Use the correct domain filter for each
widget type:
- `sensor_rows` → `{ domain: "sensor" }`
- `status_icons` → `{ domain: "binary_sensor" }`
- `waste_schedule` → `{ domain: "sensor" }` (single entity from
  waste_collection_schedule)
- `person` → `{ domain: "person" }`
- `lock` → `{ domain: "lock" }`
- `alarm` → `{ domain: "alarm_control_panel" }`

### 5. Verify

```bash
pnpm --dir custom_components/eink_dashboard/frontend typecheck && \
pnpm --dir custom_components/eink_dashboard/frontend test
```

## Redesigning an existing widget

When redesigning, update the existing renderer and type definitions
in-place. Key changes:

1. **Type definition**: Add `h` field, add `card_style` field (if
   card-style). Don't remove `font_size` from `WidgetBase` (TEXT
   and WEATHER still use it).
2. **Renderer**: Replace the old rendering logic with shared helper
   calls. The old renderers use manual text/shape drawing; the new
   ones use `drawCardContainer`, `drawCardRow`, `drawChipFlow`.
3. **Editor schema**: Replace `font_size` field with `w`/`h` fields.
   Add `card_style` selector. Update entity domain filter.

## Critical requirement: PIL ↔ Canvas sync

The canvas renderer MUST produce visually similar output to the
Python renderer. Both use:

- Same ratio factors via `computeMetrics()` / `_compute_metrics()`
- Same color constants (`COLOR_BLACK=0`, `COLOR_WHITE=255`,
  `COLOR_GRAY=120`)
- Same `drawCardContainer` return values per `card_style`
- Same layout logic (container → rows/chips with same spacing)

Pixel-perfect match is not required (different font rasterizers), but
layout and proportions must match.

## Key references

- Design spec: `REDESIGN_WIDGETS.md`
- Python renderer: `custom_components/eink_dashboard/render.py`
- Card component: `frontend/src/eink-dashboard-card.ts`
- Editor: `frontend/src/eink-dashboard-editor.ts`
- Types: `frontend/src/types/ha.d.ts`

// E-Ink Dashboard widget list editor panel.
// Loaded on demand by eink-dashboard-card.js when edit mode is entered.

import type {
  HomeAssistant,
  HaFormSchema,
  HaFormElement,
  EinkWidgetPicker,
  Widget,
  CardStyle,
  IconStyle,
  DisplayConfig,
  WidgetTypeMeta,
  Condition,
  LegacyCondition,
} from "./types/ha.js";
import "./eink-widget-picker.js";

const EDITOR_TAG = "eink-dashboard-editor";

// ── Constants (mirror const.py / render.py) ─────────────────────

const FONT_SIZE_WEATHER = 32;

/** Default card decoration style. Mirrors DEFAULT_CARD_STYLE in const.py. */
const DEFAULT_CARD_STYLE: CardStyle = "none";

/** Default icon circle style for tile-style widgets. */
const DEFAULT_ICON_STYLE: IconStyle = "filled";

// ── Widget type registry ─────────────────────────────────────────

export const WIDGET_TYPES: Record<string, WidgetTypeMeta> = {
  heading: {
    label: "Heading",
    description: "Section heading with optional icon and badges",
    icon: "mdi:format-header-1",
    defaults: {
      type: "heading",
      x: 0,
      y: 0,
      w: 400,
      h: 56,
      heading: "",
      heading_style: "title",
      icon_style: "none",
      card_style: DEFAULT_CARD_STYLE,
    },
  },
  separator: {
    label: "Separator",
    description: "Horizontal or vertical divider line",
    icon: "mdi:minus",
    defaults: {
      type: "separator",
      x: 24,
      y: 0,
      direction: "horizontal",
      style: "line",
    },
  },
  weather: {
    label: "Weather",
    description: "Forecast with conditions and temperature",
    icon: "mdi:weather-partly-cloudy",
    defaults: {
      type: "weather",
      entity: "",
      x: 24,
      y: 0,
      forecast_days: 5,
      font_size: FONT_SIZE_WEATHER,
      card_style: DEFAULT_CARD_STYLE,
    },
  },
  entities: {
    label: "Entities",
    description: "Multi-entity list with icons and state values",
    icon: "mdi:format-list-bulleted",
    defaults: {
      type: "entities",
      x: 24,
      y: 0,
      w: 400,
      h: 168,
      entities: [],
      card_style: DEFAULT_CARD_STYLE,
      icon_style: DEFAULT_ICON_STYLE,
    },
  },
  entity: {
    label: "Entity",
    description: "Single entity with large value display",
    icon: "mdi:card-text-outline",
    defaults: {
      type: "entity",
      x: 24,
      y: 0,
      w: 400,
      h: 112,
      entity: "",
      card_style: DEFAULT_CARD_STYLE,
      icon_style: DEFAULT_ICON_STYLE,
    },
  },
  tile: {
    label: "Tile",
    description: "Single entity state with icon and label",
    icon: "mdi:card-text",
    defaults: {
      type: "tile",
      x: 24,
      y: 0,
      w: 400,
      h: 56,
      card_style: DEFAULT_CARD_STYLE,
      icon_style: DEFAULT_ICON_STYLE,
    },
  },
  device_battery: {
    label: "Device Battery",
    description: "Battery level indicator chip",
    icon: "mdi:battery",
    defaults: {
      type: "device_battery",
      x: 24,
      y: 0,
      color: 0,
      layout: "icon",
      h: 40,
      card_style: DEFAULT_CARD_STYLE,
    },
  },
  waste_schedule: {
    label: "Waste Schedule",
    description: "Waste collection schedule with relative dates",
    icon: "mdi:trash-can",
    defaults: {
      type: "waste_schedule",
      title: "",
      entity: "",
      x: 24,
      y: 0,
      w: 400,
      h: 168,
      entries: [],
      layout: "list",
      show_all: false,
      card_style: DEFAULT_CARD_STYLE,
    },
  },
  calendar: {
    label: "Calendar",
    description: "Upcoming events from a calendar entity",
    icon: "mdi:calendar",
    defaults: {
      type: "calendar",
      x: 24,
      y: 0,
      w: 400,
      h: 56,
      entity: "",
      max_events: 5,
      days_ahead: 7,
      card_style: DEFAULT_CARD_STYLE,
    },
  },
  sensor: {
    label: "Sensor",
    description: "Single sensor with optional history sparkline graph",
    icon: "mdi:chart-line",
    defaults: {
      type: "sensor",
      x: 24,
      y: 0,
      w: 400,
      h: 112,
      entity: "",
      card_style: DEFAULT_CARD_STYLE,
      icon_style: DEFAULT_ICON_STYLE,
    },
  },
};

// ── ha-form schema builders ──────────────────────────────────────

const COLOR_OPTIONS = [
  { value: "0", label: "Black" },
  { value: "160", label: "Gray" },
  { value: "210", label: "Light gray" },
  { value: "255", label: "White" },
];

/**
 * Position selectors for x and y coordinates.
 *
 * @param d - Display dimensions used as max bounds.
 * @returns Schema array with x and y number fields.
 */
function posXY(d: DisplayConfig): HaFormSchema[] {
  return [
    {
      name: "x",
      default: 24,
      selector: {
        number: { min: 0, max: d.width, step: 8, mode: "box" },
      },
    },
    {
      name: "y",
      default: 0,
      selector: {
        number: { min: 0, max: d.height, step: 8, mode: "box" },
      },
    },
  ];
}

/**
 * Position selectors for x, y, and optional width override.
 *
 * @param d - Display dimensions used as max bounds.
 * @returns Schema array with x, y, and w number fields.
 */
function posXYW(d: DisplayConfig): HaFormSchema[] {
  return [
    ...posXY(d),
    {
      name: "w",
      selector: {
        number: { min: 0, max: d.width, step: 8, mode: "box" },
      },
    },
  ];
}

/**
 * Position selectors for x, y, width, and height.
 *
 * @param d - Display dimensions used as max bounds.
 * @returns Schema array with x, y, w, and h number fields.
 */
function posXYWH(d: DisplayConfig): HaFormSchema[] {
  return [
    ...posXYW(d),
    {
      name: "h",
      selector: {
        number: {
          min: 20, max: d.height, step: 8, mode: "box",
        },
      },
    },
  ];
}

/**
 * Card style dropdown selector.
 *
 * @returns A single ha-form schema entry.
 */
function cardStyleSelector(): HaFormSchema {
  return {
    name: "card_style",
    default: DEFAULT_CARD_STYLE,
    selector: {
      select: {
        options: [
          { value: "border", label: "Border" },
          { value: "left_bar", label: "Left bar" },
          { value: "none", label: "None" },
        ],
        mode: "dropdown",
      },
    },
  };
}

/**
 * Icon style dropdown selector.
 *
 * @param defaultStyle - Default icon style value. Defaults to
 *   {@link DEFAULT_ICON_STYLE} ("filled") for most widgets; pass
 *   `"none"` for Heading, which shows no circle by default.
 * @returns A single ha-form schema entry.
 */
function iconStyleSelector(
  defaultStyle: IconStyle = DEFAULT_ICON_STYLE
): HaFormSchema {
  return {
    name: "icon_style",
    default: defaultStyle,
    selector: {
      select: {
        options: [
          { value: "filled", label: "Filled" },
          { value: "outlined", label: "Outlined" },
          { value: "none", label: "None" },
        ],
        mode: "dropdown",
      },
    },
  };
}

/**
 * Font size number selector with the given default.
 *
 * @param defaultSize - Default font size value.
 * @returns A single ha-form schema entry.
 */
function fontSizeSelector(defaultSize: number): HaFormSchema {
  return {
    name: "font_size",
    default: defaultSize,
    selector: { number: { min: 8, max: 72, mode: "box" } },
  };
}

/**
 * Color dropdown selector defaulting to black (0).
 *
 * @param defaultColor - Grayscale value (0–255).
 * @returns A single ha-form schema entry.
 */
function colorSelector(defaultColor: number = 0): HaFormSchema {
  return {
    name: "color",
    default: String(defaultColor),
    selector: {
      select: {
        options: COLOR_OPTIONS,
        mode: "dropdown",
        custom_value: true,
      },
    },
  };
}

/**
 * Common "Identity" section prepended to every widget's
 * form schema.
 *
 * Uses ``flatten: true`` so ``label`` and ``description``
 * merge into the widget data object at the top level.
 * Both names are reserved on ``WidgetBase`` in ha.d.ts —
 * do not reuse them in any widget-specific schema.
 *
 * @returns An expandable ha-form section with label and
 *   description.
 */
function identitySection(): HaFormSchema {
  return {
    name: "identity",
    type: "expandable",
    flatten: true,
    title: "Identity",
    icon: "mdi:tag",
    schema: [
      { name: "label", selector: { text: {} } },
      { name: "description", selector: { text: {} } },
    ],
  };
}

export const SCHEMAS: Record<
  string,
  (d: DisplayConfig) => HaFormSchema[]
> = {
  separator: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:minus",
      schema: [
        {
          type: "grid",
          name: "",
          schema: [
            {
              name: "direction",
              default: "horizontal",
              selector: {
                select: {
                  options: [
                    { value: "horizontal", label: "Horizontal" },
                    { value: "vertical", label: "Vertical" },
                  ],
                },
              },
            },
            {
              name: "style",
              default: "line",
              selector: {
                select: {
                  options: [
                    { value: "line", label: "Line" },
                    { value: "bar", label: "Bar" },
                  ],
                },
              },
            },
          ],
        },
      ],
    },
    {
      name: "layout",
      type: "expandable",
      flatten: true,
      title: "Layout",
      icon: "mdi:move-resize",
      schema: [
        {
          type: "grid",
          name: "",
          schema: [
            {
              name: "x",
              default: 24,
              selector: {
                number: {
                  min: 0, max: d.width, step: 8, mode: "box",
                },
              },
            },
            {
              name: "y",
              default: 0,
              selector: {
                number: {
                  min: 0, max: d.height, step: 8, mode: "box",
                },
              },
            },
            {
              name: "length",
              selector: {
                number: {
                  min: 0,
                  max: Math.max(d.width, d.height),
                  step: 8,
                  mode: "box",
                },
              },
            },
          ],
        },
      ],
    },
  ],

  weather: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:weather-partly-cloudy",
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "weather" } },
        },
        {
          name: "forecast_days",
          default: 5,
          selector: { number: { min: 0, max: 14, mode: "box" } },
        },
        {
          name: "temperature_entity",
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "humidity_entity",
          selector: { entity: { domain: "sensor" } },
        },
      ],
    },
    {
      name: "layout",
      type: "expandable",
      flatten: true,
      title: "Layout",
      icon: "mdi:move-resize",
      schema: [{ type: "grid", name: "", schema: posXYW(d) }],
    },
    {
      name: "appearance",
      type: "expandable",
      flatten: true,
      title: "Appearance",
      icon: "mdi:palette",
      schema: [fontSizeSelector(FONT_SIZE_WEATHER), cardStyleSelector()],
    },
  ],

  tile: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:card-text",
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: {} },
        },
        { name: "name", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
        {
          name: "hide_icon",
          default: false,
          selector: { boolean: {} },
        },
        {
          name: "hide_state",
          default: false,
          selector: { boolean: {} },
        },
        { name: "state_content", selector: { text: {} } },
      ],
    },
    {
      name: "layout",
      type: "expandable",
      flatten: true,
      title: "Layout",
      icon: "mdi:move-resize",
      schema: [
        { type: "grid", name: "", schema: posXYWH(d) },
      ],
    },
    {
      name: "appearance",
      type: "expandable",
      flatten: true,
      title: "Appearance",
      icon: "mdi:palette",
      schema: [cardStyleSelector(), iconStyleSelector()],
    },
  ],

  entity: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:card-text-outline",
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: {} },
        },
        { name: "name", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
        {
          name: "hide_icon",
          default: false,
          selector: { boolean: {} },
        },
        { name: "attribute", selector: { text: {} } },
        { name: "unit", selector: { text: {} } },
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
      schema: [cardStyleSelector(), iconStyleSelector()],
    },
  ],

  entities: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:format-list-bulleted",
      schema: [
        { name: "title", selector: { text: {} } },
        {
          name: "entities",
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
      schema: [cardStyleSelector(), iconStyleSelector()],
    },
  ],

  heading: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:format-header-1",
      schema: [
        { name: "heading", selector: { text: {} } },
        {
          name: "heading_style",
          default: "title",
          selector: {
            select: {
              options: [
                { value: "title", label: "Title" },
                { value: "subtitle", label: "Subtitle" },
              ],
              mode: "dropdown",
            },
          },
        },
        { name: "icon", selector: { icon: {} } },
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
      schema: [cardStyleSelector(), iconStyleSelector("none")],
    },
  ],

  device_battery: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:battery",
      schema: [
        {
          name: "layout",
          required: false,
          selector: {
            select: {
              options: [
                { value: "icon", label: "Icon" },
                { value: "chip", label: "Chip" },
              ],
            },
          },
        },
      ],
    },
    {
      name: "layout_pos",
      type: "expandable",
      flatten: true,
      title: "Layout",
      icon: "mdi:move-resize",
      schema: [
        { type: "grid", name: "", schema: posXYWH(d) },
      ],
    },
    {
      name: "appearance",
      type: "expandable",
      flatten: true,
      title: "Appearance",
      icon: "mdi:palette",
      schema: [colorSelector(), cardStyleSelector()],
    },
  ],

  sensor: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:chart-line",
      schema: [
        {
          name: "entity",
          required: true,
          selector: {
            entity: {
              domain: ["sensor", "counter", "input_number", "number"],
            },
          },
        },
        { name: "name", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
        { name: "unit", selector: { text: {} } },
        {
          name: "graph",
          selector: {
            select: {
              options: [
                { value: "", label: "None" },
                { value: "line", label: "Line" },
              ],
              mode: "dropdown",
            },
          },
        },
        {
          name: "detail",
          default: "1",
          selector: {
            select: {
              options: [
                { value: "1", label: "Standard (~24 pts)" },
                { value: "2", label: "Full resolution" },
              ],
            },
          },
        },
        // Graph-related; shown unconditionally because ha-form
        // has no field-level conditional visibility.
        {
          name: "hours_to_show",
          default: 24,
          selector: {
            number: { min: 1, max: 720, mode: "box" },
          },
        },
        {
          type: "grid",
          name: "",
          schema: [
            {
              name: "limits_min",
              selector: { number: { mode: "box" } },
            },
            {
              name: "limits_max",
              selector: { number: { mode: "box" } },
            },
          ],
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
      schema: [cardStyleSelector(), iconStyleSelector()],
    },
  ],

  waste_schedule: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:trash-can",
      schema: [
        { name: "title", selector: { text: {} } },
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "layout",
          default: "list",
          selector: {
            select: {
              options: [
                { value: "list", label: "List" },
                { value: "card", label: "Card" },
              ],
              mode: "dropdown",
            },
          },
        },
        {
          name: "show_all",
          default: false,
          selector: { boolean: {} },
        },
      ],
    },
    {
      name: "layout_pos",
      type: "expandable",
      flatten: true,
      title: "Layout",
      icon: "mdi:move-resize",
      schema: [
        { type: "grid", name: "", schema: posXYWH(d) },
      ],
    },
    {
      name: "appearance",
      type: "expandable",
      flatten: true,
      title: "Appearance",
      icon: "mdi:palette",
      schema: [cardStyleSelector()],
    },
  ],
  calendar: (d) => [
    identitySection(),
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:calendar",
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "calendar" } },
        },
        { name: "title", selector: { text: {} } },
        {
          name: "max_events",
          default: 5,
          selector: {
            number: { min: 1, max: 20, mode: "box" },
          },
        },
        {
          name: "days_ahead",
          default: 7,
          selector: {
            number: { min: 1, max: 30, mode: "box" },
          },
        },
      ],
    },
    {
      name: "layout_pos",
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
      schema: [cardStyleSelector()],
    },
  ],
};

export const HELPERS: Record<string, string> = {
  show_all:
    "When off, the widget is empty if no collection falls "
    + "within the next 3 days.",
};

export const LABELS: Record<string, string> = {
  label: "Label",
  description: "Description",
  entity: "Entity",
  entities: "Entities",
  name: "Name",
  icon: "Icon",
  hide_icon: "Hide icon",
  hide_state: "Hide state",
  state_content: "State attribute",
  title: "Title",
  x: "X", y: "Y", w: "Width", h: "Height",
  direction: "Direction", style: "Style", length: "Length",
  font_size: "Font size",
  color: "Color",
  attribute: "Attribute",
  unit: "Unit",
  heading: "Heading",
  heading_style: "Heading style",
  badges: "Badges",
  card_style: "Card style",
  icon_style: "Icon style",
  layout: "Layout",
  show_all: "Show all upcoming dates",
  entries: "Entries",
  forecast_days: "Forecast days",
  temperature_entity: "Temperature sensor",
  humidity_entity: "Humidity sensor",
  graph: "Graph",
  hours_to_show: "Hours to show",
  detail: "Detail",
  limits_min: "Y-axis minimum",
  limits_max: "Y-axis maximum",
  max_events: "Max events",
  days_ahead: "Days ahead",
};

// ── HA component loader ──────────────────────────────────────────

type HaCardClass = CustomElementConstructor & {
  getConfigElement(): Promise<unknown>;
};

export async function loadHaComponents(): Promise<void> {
  if (!customElements.get("ha-form")) {
    const cls = customElements.get(
      "hui-tile-card"
    ) as HaCardClass | undefined;
    if (cls) await cls.getConfigElement();
  }
  if (!customElements.get("ha-entity-picker")) {
    const cls = customElements.get(
      "hui-entities-card"
    ) as HaCardClass | undefined;
    if (cls) await cls.getConfigElement();
  }
  if (!customElements.get("ha-card-conditions-editor")) {
    // Loaded via hui-conditional-card's config element import chain.
    const cls = customElements.get(
      "hui-conditional-card"
    ) as HaCardClass | undefined;
    if (cls) await cls.getConfigElement();
  }
}

// ── Summary helper (extracted for testability) ───────────────────

export function getSummary(widget: Widget): string {
  const t = widget.type;
  if (t === "heading") {
    const s = String(widget.heading || "");
    return s.length > 30 ? s.slice(0, 30) + "…" : (s || "(empty)");
  }
  if (
    t === "weather" || t === "tile" || t === "entity"
    || t === "sensor" || t === "calendar"
  ) {
    return widget.entity || "(no entity)";
  }
  if (t === "device_battery") {
    return "Device battery";
  }
  if (t === "entities") {
    const title = widget.title ? `${widget.title} — ` : "";
    const count = (widget.entities || []).filter(
      (r) => typeof r === "string" || ("entity" in r && !("type" in r))
    ).length;
    return `${title}${count} entit${count === 1 ? "y" : "ies"}`;
  }
  if (t === "waste_schedule") {
    const title = widget.title ? `${widget.title} — ` : "";
    const count = (widget.entries || []).length;
    return `${title}${count} entr${count === 1 ? "y" : "ies"}`;
  }
  if (t === "separator") {
    const dir = widget.direction === "vertical"
      ? "Vertical" : "Horizontal";
    const sty = widget.style === "bar" ? "bar" : "line";
    return `${dir} ${sty} at Y:${widget.y ?? 0}`;
  }
  return t;
}

// ── Icon paths (MDI) ─────────────────────────────────────────────

const MDI_DRAG =
  "M7,19V17H9V19H7M11,19V17H13V19H11"
  + "M15,19V17H17V19H15M7,15V13H9V15H7"
  + "M11,15V13H13V15H11M15,15V13H17V15H15"
  + "M7,11V9H9V11H7M11,11V9H13V11H11"
  + "M15,11V9H17V11H15M7,7V5H9V7H7"
  + "M11,7V5H13V7H11M15,7V5H17V7H15Z";

const MDI_CHEVRON_DOWN =
  "M7.41,8.58L12,13.17L16.59,8.58"
  + "L18,10L12,16L6,10L7.41,8.58Z";

const MDI_CLOSE =
  "M19,6.41L17.59,5L12,10.59L6.41,5"
  + "L5,6.41L10.59,12L5,17.59L6.41,19"
  + "L12,13.41L17.59,19L19,17.59"
  + "L13.41,12L19,6.41Z";

/**
 * Build an inline SVG string for a Material Design icon path.
 *
 * @param path - The SVG `d` attribute value. Must be a
 *   trusted compile-time constant; user-controlled data
 *   would create an XSS vector via innerHTML.
 * @returns An `<svg>` element string with the path filled in.
 */
function svgIcon(path: string): string {
  return (
    `<svg viewBox="0 0 24 24" width="20" height="20">`
    + `<path fill="currentColor" d="${path}"/></svg>`
  );
}

// ── Editor class ─────────────────────────────────────────────────

class EinkDashboardEditor extends HTMLElement {
  private _hass: HomeAssistant | null = null;
  private _widgets: Widget[] = [];
  private _display: DisplayConfig = { width: 0, height: 0 };
  private _expandedIndex = -1;
  private _sortSelectedIndex: number | undefined;
  private _built = false;
  private _saveTimeout: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  disconnectedCallback(): void {
    if (this._saveTimeout !== null) {
      clearTimeout(this._saveTimeout);
      this._saveTimeout = null;
    }
  }

  // ── Public API ─────────────────────────────────────────────────

  set hass(hass: HomeAssistant) {
    this._hass = hass;
    this.shadowRoot!
      .querySelectorAll<HaFormElement>("ha-form")
      .forEach((el) => {
        el.hass = hass;
      });
    // ha-card-conditions-editor is a Lit element that also needs hass
    // for its entity pickers.
    this.shadowRoot!
      .querySelectorAll("ha-card-conditions-editor")
      .forEach((el) => {
        (el as unknown as Record<string, unknown>).hass = hass;
      });
  }

  setWidgets(widgets: Widget[]): void {
    this._widgets = widgets.map((w) => ({ ...w }));
    this._expandedIndex = -1;
    this._sortSelectedIndex = undefined;
    this._rebuild();
  }

  setDisplay(display: DisplayConfig): void {
    this._display = display;
    const info =
      this.shadowRoot!.querySelector<HTMLElement>(".display-info");
    if (info) {
      info.textContent = `${display.width} × ${display.height}`;
    }
  }

  // ── Shadow DOM ─────────────────────────────────────────────────

  /**
   * Build the editor outer shell: header with add button, empty
   * widget list container, and footer with display info and save
   * button. Called once; subsequent rebuilds skip this step.
   */
  private async _buildShell(): Promise<void> {
    await loadHaComponents();
    const size =
      `${this._display.width} × ${this._display.height}`;
    this.shadowRoot!.innerHTML = `
      <style>
        :host { display: block; font-size: 14px; }
        .editor {
          display: flex;
          flex-direction: column;
          gap: 0;
        }
        .editor-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 12px;
          border-bottom: 1px solid
            var(--divider-color, #e0e0e0);
          background: var(
            --secondary-background-color, #f5f5f5
          );
        }
        .editor-header span {
          font-weight: 500;
          color: var(--primary-text-color, #212121);
        }
        .add-btn {
          font-size: 13px;
          padding: 4px 10px;
          border: 1px solid var(--primary-color, #03a9f4);
          border-radius: 4px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--primary-color, #03a9f4);
        }
        .widget-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 8px 12px;
        }
        .widget-item {
          border: 1px solid
            var(--divider-color, #e0e0e0);
          border-radius:
            var(--ha-card-border-radius, 12px);
          background:
            var(--card-background-color, #fff);
          overflow: hidden;
        }
        .widget-header {
          display: flex;
          align-items: center;
          gap: 2px;
          padding: 0 4px 0 12px;
          min-height: 48px;
          cursor: default;
        }
        .widget-header:hover {
          background: rgba(0, 0, 0, 0.04);
        }
        .widget-label {
          flex: 1;
          display: flex;
          flex-direction: column;
          justify-content: center;
          overflow: hidden;
          min-width: 0;
        }
        .widget-label-primary {
          font-size: 13px;
          color: var(--primary-text-color, #212121);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .widget-secondary {
          font-size: 11px;
          color: var(--secondary-text-color, #757575);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .widget-type-badge {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
          background: var(
            --secondary-background-color, #f5f5f5
          );
          border-radius: 12px;
          padding: 2px 8px;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .handle {
          padding: 4px;
          cursor: grab;
          border-radius: 50%;
          color: var(--secondary-text-color, #757575);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          width: 36px;
          height: 36px;
        }
        .handle:hover {
          background: var(--divider-color, #e0e0e0);
        }
        .handle:focus-visible {
          outline: 2px solid
            var(--primary-color, #03a9f4);
          outline-offset: -2px;
        }
        .handle svg { pointer-events: none; }
        .widget-item.sort-selected {
          outline: 2px solid
            var(--primary-color, #03a9f4);
          outline-offset: -2px;
          border-color:
            var(--primary-color, #03a9f4);
        }
        .icon-btn {
          background: none;
          border: none;
          cursor: pointer;
          padding: 4px;
          color: var(--secondary-text-color, #757575);
          border-radius: 50%;
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .icon-btn:hover {
          background: var(--divider-color, #e0e0e0);
        }
        .icon-btn.delete:hover {
          color: var(--error-color, #b00020);
        }
        .icon-btn.expand svg {
          transition:
            transform 150ms
            cubic-bezier(0.4, 0, 0.2, 1);
        }
        .icon-btn.expand.expanded svg {
          transform: rotate(180deg);
        }
        .widget-form {
          padding: 12px;
          border-top: 1px solid
            var(--divider-color, #e0e0e0);
          background: var(
            --secondary-background-color, #fafafa
          );
        }
        .editor-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 12px;
          border-top: 1px solid
            var(--divider-color, #e0e0e0);
          background: var(
            --secondary-background-color, #f5f5f5
          );
        }
        .display-info {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
        }
        .save-btn {
          padding: 6px 16px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          background: var(--primary-color, #03a9f4);
          color: #fff;
          font-size: 13px;
          font-weight: 500;
        }
        .save-btn:hover { opacity: 0.9; }
        .save-btn.saving {
          opacity: 0.7;
          cursor: not-allowed;
        }
        .save-btn.saved {
          background: var(--success-color, #4caf50);
        }
        .entries-section {
          margin-top: 12px;
          padding: 8px 0;
        }
        .entries-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
          font-size: 13px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
        }
        .entries-hint {
          font-size: 12px;
          color: var(
            --secondary-text-color, #757575
          );
          margin-bottom: 8px;
        }
        .entry-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 4px 0;
        }
        .entry-row input[type="checkbox"] {
          margin: 0;
          flex-shrink: 0;
        }
        .entry-attr {
          font-size: 12px;
          color: var(
            --secondary-text-color, #757575
          );
          min-width: 120px;
          max-width: 200px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .entry-label-input {
          flex: 1;
          font-size: 13px;
          padding: 4px 6px;
          border: 1px solid var(
            --divider-color, #e0e0e0
          );
          border-radius: 4px;
          background: var(
            --card-background-color, #fff
          );
          color: var(
            --primary-text-color, #212121
          );
          min-width: 0;
        }
        .entry-label-input:disabled {
          opacity: 0.5;
        }
        .entry-value {
          font-size: 11px;
          color: var(
            --secondary-text-color, #999
          );
          max-width: 80px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .visibility-hint {
          font-size: 12px;
          color: var(
            --secondary-text-color, #757575
          );
          margin-bottom: 8px;
        }
      </style>
      <div class="editor">
        <div class="editor-header">
          <span>Widgets</span>
          <button class="add-btn">+ Add Widget</button>
        </div>
        <ha-sortable
          handle-selector=".handle"
          draggable-selector=".widget-item"
        ><div class="widget-list"></div></ha-sortable>
        <div class="editor-footer">
          <span class="display-info">${size}</span>
          <button class="save-btn">Save</button>
        </div>
      </div>
    `;

    this.shadowRoot!
      .querySelector<HTMLButtonElement>(".add-btn")!
      .addEventListener("click", () => this._onAddBtnClick());
    this.shadowRoot!
      .querySelector<HTMLButtonElement>(".save-btn")!
      .addEventListener("click", () => this._onSave());
    this.shadowRoot!
      .querySelector("ha-sortable")!
      .addEventListener(
        "item-moved",
        ((ev: CustomEvent<{
          oldIndex: number;
          newIndex: number;
        }>) => {
          this._onItemMoved(ev);
        }) as EventListener,
      );
    this._built = true;
  }

  /**
   * Ensure the shell is built, then re-render the widget list.
   * Entry point for full UI refreshes after state changes.
   */
  private async _rebuild(): Promise<void> {
    if (!this._built) {
      await this._buildShell();
    }
    this._renderWidgetList();
  }

  // ── Widget list rendering ──────────────────────────────────────

  /** Clear and re-populate the widget list container. */
  private _renderWidgetList(): void {
    const list =
      this.shadowRoot!.querySelector<HTMLElement>(
        ".widget-list"
      )!;
    list.innerHTML = "";
    this._widgets.forEach((widget, index) => {
      list.appendChild(this._buildWidgetItem(widget, index));
    });
  }

  /**
   * Populate a widget-label element with primary and secondary
   * text spans.
   *
   * When the widget has a user-set label the primary span shows
   * it and the secondary span shows the type summary (plus
   * description if it differs). Otherwise the primary span shows
   * the summary alone. Clears existing children before building.
   *
   * @param el     - The `.widget-label` container element.
   * @param widget - Widget data to derive text from.
   */
  private _populateLabel(
    el: HTMLElement,
    widget: Widget,
  ): void {
    el.textContent = "";
    const summary = getSummary(widget);

    if (widget.label) {
      const primary = document.createElement("span");
      primary.className = "widget-label-primary";
      primary.textContent = widget.label;
      primary.title = widget.label;

      const parts: string[] = [summary];
      if (
        widget.description
        && widget.description !== summary
      ) {
        parts.push(widget.description);
      }
      const secondary = document.createElement("span");
      secondary.className = "widget-secondary";
      secondary.textContent = parts.join(" · ");

      el.title = widget.label;
      el.append(primary, secondary);
    } else {
      const primary = document.createElement("span");
      primary.className = "widget-label-primary";
      primary.title = summary;
      primary.textContent = summary;
      el.appendChild(primary);
    }
  }

  /**
   * Create the DOM element for a single widget row including
   * its header controls (drag handle, expand, delete).
   *
   * @param widget - Widget data to render.
   * @param index  - Position in the widget array.
   * @returns The widget-item div element.
   */
  private _buildWidgetItem(
    widget: Widget,
    index: number,
  ): HTMLElement {
    const meta = WIDGET_TYPES[widget.type];
    const typeLabel = meta ? meta.label : widget.type;
    const isExpanded = this._expandedIndex === index;

    const item = document.createElement("div");
    item.className = "widget-item";
    item.dataset.index = String(index);

    const header = document.createElement("div");
    header.className = "widget-header";

    const badge = document.createElement("span");
    badge.className = "widget-type-badge";
    badge.textContent = typeLabel;

    const labelEl = document.createElement("div");
    labelEl.className = "widget-label";
    this._populateLabel(labelEl, widget);

    const handle = document.createElement("div");
    handle.className = "handle";
    handle.title = "Drag to reorder";
    handle.tabIndex = 0;
    handle.setAttribute("role", "button");
    handle.setAttribute("aria-label", "Drag to reorder");
    handle.innerHTML = svgIcon(MDI_DRAG);
    handle.addEventListener(
      "keydown",
      (ev) => this._onHandleKeyDown(ev, index),
    );

    const expandBtn = document.createElement("button");
    expandBtn.className =
      `icon-btn expand${isExpanded ? " expanded" : ""}`;
    expandBtn.title = isExpanded ? "Collapse" : "Edit";
    expandBtn.innerHTML = svgIcon(MDI_CHEVRON_DOWN);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "icon-btn delete";
    deleteBtn.title = "Delete";
    deleteBtn.innerHTML = svgIcon(MDI_CLOSE);

    header.append(badge, labelEl, handle, expandBtn, deleteBtn);

    expandBtn.addEventListener(
      "click", () => this._onToggleExpand(index),
    );
    deleteBtn.addEventListener(
      "click", () => this._onDelete(index),
    );

    item.appendChild(header);

    if (isExpanded && meta) {
      item.appendChild(
        this._buildWidgetForm(widget, index),
      );
    }

    return item;
  }

  // ── Per-widget form ────────────────────────────────────────────

  /**
   * Create the ha-form element for editing a widget's fields.
   *
   * @param widget - Widget data used to populate the form.
   * @param index  - Position in the widget array.
   * @returns Container div holding the ha-form.
   */
  private _buildWidgetForm(
    widget: Widget,
    index: number,
  ): HTMLElement {
    const container = document.createElement("div");
    container.className = "widget-form";
    const schemaFn = SCHEMAS[widget.type];
    if (!schemaFn) return container;

    const formData: Record<string, unknown> = { ...widget };
    if ("color" in formData && formData.color !== undefined) {
      formData.color = String(formData.color);
    }

    const form =
      document.createElement("ha-form") as unknown as HaFormElement;
    form.hass = this._hass;
    form.data = formData;
    form.schema = schemaFn(this._display);
    form.computeLabel = (s) => LABELS[s.name] || s.name;
    form.computeHelper = (s) => HELPERS[s.name] || "";
    form.addEventListener(
      "value-changed",
      ((ev: CustomEvent<{ value: Record<string, unknown> }>) => {
        ev.stopPropagation();
        const raw = ev.detail.value;
        const prevEntity = (
          this._widgets[index] as unknown as
            Record<string, unknown>
        ).entity;
        const data: Record<string, unknown> = {
          type: widget.type,
          ...raw,
        };
        if ("color" in data && data.color !== undefined) {
          data.color = parseInt(String(data.color), 10) || 0;
        }
        const cur = this._widgets[index] as
          unknown as Record<string, unknown>;
        // Preserve entries — ha-form doesn't know about
        // them so they'd be dropped by the spread.
        if (widget.type === "waste_schedule") {
          if (!("entries" in data) && cur.entries) {
            data.entries = cur.entries;
          }
        }
        // Preserve visibility — managed by ha-card-conditions-editor,
        // not by ha-form, so the spread would drop it.
        // cur.visibility is never [] because _buildVisibilityEditor
        // deletes the key when conditions are cleared (empty array).
        if (!("visibility" in data) && cur.visibility) {
          data.visibility = cur.visibility;
        }
        this._widgets[index] = data as unknown as Widget;
        this._fireWidgetChange();
        this._updateSummary(index);
        // Refresh entries pick-list when entity changes
        if (
          widget.type === "waste_schedule"
          && data.entity !== prevEntity
        ) {
          this._refreshEntriesEditor(
            container, index,
          );
        }
      }) as EventListener
    );
    container.appendChild(form);

    if (widget.type === "waste_schedule") {
      this._buildEntriesEditor(container, index);
    }

    this._buildVisibilityEditor(container, index);

    return container;
  }

  // ── Waste schedule entries pick-list ────────────────────────────

  /** HA-internal attributes to exclude from the pick-list. */
  private static readonly _HA_INTERNAL_ATTRS = new Set([
    "friendly_name",
    "unit_of_measurement",
    "icon",
    "device_class",
    "state_class",
    "entity_picture",
    "attribution",
  ]);

  /**
   * Remove and re-create the entries pick-list section.
   *
   * Called when the entity field changes so the attribute
   * list reflects the newly selected entity.
   *
   * @param container - Parent div holding the ha-form.
   * @param index     - Widget index in the widget array.
   */
  private _refreshEntriesEditor(
    container: HTMLElement,
    index: number,
  ): void {
    const old = container.querySelector(
      ".entries-section",
    );
    if (old) old.remove();
    this._buildEntriesEditor(container, index);
  }

  /**
   * Build an attribute pick-list for waste_schedule entries.
   *
   * Reads the selected entity's attributes from hass.states,
   * filters out HA internal attrs, and renders a checkbox +
   * label input for each attribute.  Checked attributes are
   * included in the widget's entries array.
   *
   * @param container - Parent div to append the section to.
   * @param index     - Widget index in the widget array.
   */
  private _buildEntriesEditor(
    container: HTMLElement,
    index: number,
  ): void {
    const widget = this._widgets[index];
    const section = document.createElement("div");
    section.className = "entries-section";

    const entityId = (
      widget as unknown as Record<string, unknown>
    ).entity as string | undefined;

    if (!entityId) {
      const hint = document.createElement("div");
      hint.className = "entries-hint";
      hint.textContent =
        "Select an entity to configure entries.";
      section.appendChild(hint);
      container.appendChild(section);
      return;
    }

    const stateObj = this._hass?.states[entityId];
    if (!stateObj) {
      const hint = document.createElement("div");
      hint.className = "entries-hint";
      hint.textContent = "Entity not available.";
      section.appendChild(hint);
      container.appendChild(section);
      return;
    }

    const attrs = stateObj.attributes as
      Record<string, unknown>;
    const attrKeys = Object.keys(attrs).filter(
      (k) =>
        !EinkDashboardEditor._HA_INTERNAL_ATTRS.has(k),
    );

    if (attrKeys.length === 0) {
      const hint = document.createElement("div");
      hint.className = "entries-hint";
      hint.textContent =
        "No waste type attributes found.";
      section.appendChild(hint);
      container.appendChild(section);
      return;
    }

    // Header
    const header = document.createElement("div");
    header.className = "entries-header";
    header.textContent = "Entries";
    section.appendChild(header);

    const hint = document.createElement("div");
    hint.className = "entries-hint";
    hint.textContent =
      "Select which waste types to display and set "
      + "short labels for each.";
    section.appendChild(hint);

    const docHint = document.createElement("div");
    docHint.className = "entries-hint";
    const docLink = document.createElement("a");
    docLink.href =
      "https://github.com/cryptomilk/hass-eink-dashboard"
      + "/blob/main/docs/waste_schedule.md";
    docLink.target = "_blank";
    docLink.rel = "noopener noreferrer";
    docLink.textContent = "Setup guide";
    docHint.appendChild(docLink);
    section.appendChild(docHint);

    // Build a lookup for existing entries
    const existing = new Map<string, string>();
    const entries = (
      (widget as unknown as Record<string, unknown>)
        .entries as Array<{
        attribute: string;
        label: string;
      }>
    ) ?? [];
    for (const e of entries) {
      existing.set(e.attribute, e.label);
    }

    /** Collect checked entries and update the widget. */
    const syncEntries = (): void => {
      const rows = section.querySelectorAll<
        HTMLElement
      >(".entry-row");
      const newEntries: Array<{
        attribute: string;
        label: string;
      }> = [];
      rows.forEach((row) => {
        const cb = row.querySelector<
          HTMLInputElement
        >("input[type='checkbox']");
        const labelInput = row.querySelector<
          HTMLInputElement
        >(".entry-label-input");
        if (cb?.checked && labelInput) {
          newEntries.push({
            attribute: row.dataset.attr!,
            label: labelInput.value,
          });
        }
      });
      const w = this._widgets[index] as
        unknown as Record<string, unknown>;
      w.entries = newEntries;
      this._fireWidgetChange();
      this._updateSummary(index);
    };

    // Rows — one per attribute
    for (const key of attrKeys) {
      const row = document.createElement("div");
      row.className = "entry-row";
      row.dataset.attr = key;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = existing.has(key);
      cb.addEventListener("change", syncEntries);
      row.appendChild(cb);

      const attrLabel = document.createElement(
        "span",
      );
      attrLabel.className = "entry-attr";
      attrLabel.textContent = key;
      attrLabel.title = key;
      row.appendChild(attrLabel);

      const labelInput = document.createElement(
        "input",
      );
      labelInput.type = "text";
      labelInput.className = "entry-label-input";
      labelInput.placeholder = "Label";
      labelInput.value =
        existing.get(key) ?? key;
      labelInput.disabled = !cb.checked;
      labelInput.addEventListener(
        "input", syncEntries,
      );
      // Enable/disable label input with checkbox
      cb.addEventListener("change", () => {
        labelInput.disabled = !cb.checked;
      });
      row.appendChild(labelInput);

      // Show current attribute value as hint
      const val = attrs[key];
      if (val !== undefined && val !== null) {
        const valHint = document.createElement(
          "span",
        );
        valHint.className = "entry-value";
        valHint.textContent = String(val);
        valHint.title = String(val);
        row.appendChild(valHint);
      }

      section.appendChild(row);
    }

    container.appendChild(section);
  }

  // ── Visibility conditions editor ────────────────────────────────

  /**
   * Build a visibility conditions editor using HA's built-in
   * `<ha-card-conditions-editor>` component.  Appended to every
   * widget form regardless of widget type.
   *
   * Reads the current widget's `visibility` array, passes it to the
   * conditions editor, and writes changes back on `value-changed`.
   * An empty conditions array is stored as `undefined` (field
   * removed) to avoid serialising empty arrays.
   *
   * @param container - Parent div to append the section to.
   * @param index     - Widget index in the widget array.
   */
  private _buildVisibilityEditor(
    container: HTMLElement,
    index: number,
  ): void {
    const panel = document.createElement("ha-expansion-panel");
    (panel as unknown as Record<string, unknown>).outlined = true;
    // ha-form sections have internal spacing; the visibility panel
    // is appended outside ha-form so it needs an explicit top gap.
    panel.style.marginTop = "8px";

    // Match ha-form-expandable: icon in "leading-icon" slot,
    // title in "header" slot.
    const icon = document.createElement("ha-icon");
    icon.setAttribute("slot", "leading-icon");
    (icon as unknown as Record<string, unknown>).icon = "mdi:eye";
    panel.appendChild(icon);

    const panelHeader = document.createElement("div");
    panelHeader.setAttribute("slot", "header");
    panelHeader.textContent = "Visibility";
    panel.appendChild(panelHeader);

    const hint = document.createElement("div");
    hint.className = "visibility-hint";
    hint.textContent =
      "Show this widget only when the conditions below are met.";
    panel.appendChild(hint);

    if (!customElements.get("ha-card-conditions-editor")) {
      console.warn(
        "eink-dashboard: ha-card-conditions-editor not registered;" +
          " visibility editing unavailable",
      );
      const unavailable = document.createElement("div");
      unavailable.className = "visibility-hint";
      unavailable.textContent =
        "Visibility conditions require a newer Home Assistant version.";
      panel.appendChild(unavailable);
      container.appendChild(panel);
      return;
    }

    const editor = document.createElement(
      "ha-card-conditions-editor",
    );
    const cur = this._widgets[index] as
      unknown as Record<string, unknown>;
    const conditions =
      (cur.visibility as (Condition | LegacyCondition)[] | undefined)
      ?? [];
    (editor as unknown as Record<string, unknown>).hass = this._hass;
    (editor as unknown as Record<string, unknown>).conditions =
      conditions;

    editor.addEventListener(
      "value-changed",
      ((ev: CustomEvent<{
        value: (Condition | LegacyCondition)[]
      }>) => {
        ev.stopPropagation();
        const updated = ev.detail.value;
        const w = this._widgets[index] as
          unknown as Record<string, unknown>;
        if (updated.length > 0) {
          w.visibility = updated;
        } else {
          delete w.visibility;
        }
        // Write back so the Lit component re-renders immediately,
        // showing newly added condition fields without a save+reopen.
        (editor as unknown as Record<string, unknown>).conditions =
          updated;
        this._fireWidgetChange();
      }) as EventListener
    );

    panel.appendChild(editor);
    container.appendChild(panel);
  }

  // ── Inline summary update (avoids full re-render on edits) ────

  /**
   * Refresh the summary label for a single widget row without
   * re-rendering the entire list.
   *
   * @param index - Index of the widget to update.
   */
  private _updateSummary(index: number): void {
    const item = this.shadowRoot!
      .querySelector<HTMLElement>(
        `.widget-item[data-index="${index}"]`,
      );
    if (!item) return;
    const label =
      item.querySelector<HTMLElement>(".widget-label");
    if (label) {
      this._populateLabel(label, this._widgets[index]);
    }
  }

  // ── Event handlers ─────────────────────────────────────────────

  /**
   * Handle a drag-reorder event from ha-sortable.
   *
   * Clears keyboard sort mode (pointer drag takes over),
   * then delegates to _moveWidget.
   *
   * @param ev - Custom event with oldIndex and newIndex.
   */
  private _onItemMoved(
    ev: CustomEvent<{ oldIndex: number; newIndex: number }>,
  ): void {
    const { oldIndex, newIndex } = ev.detail;
    if (oldIndex === newIndex) return;
    this._sortSelectedIndex = undefined;
    this._moveWidget(oldIndex, newIndex);
  }

  /**
   * Move a widget from oldIndex to newIndex, adjusting
   * _expandedIndex so the expanded widget stays expanded,
   * then re-renders and fires a widget-change event.
   *
   * @param oldIndex - Current position of the widget.
   * @param newIndex - Target position.
   */
  private _moveWidget(
    oldIndex: number,
    newIndex: number,
  ): void {
    const [moved] = this._widgets.splice(oldIndex, 1);
    this._widgets.splice(newIndex, 0, moved);
    // Keep _expandedIndex pointing at the same widget.
    if (this._expandedIndex === oldIndex) {
      this._expandedIndex = newIndex;
    } else if (oldIndex < newIndex) {
      if (
        this._expandedIndex > oldIndex
        && this._expandedIndex <= newIndex
      ) {
        this._expandedIndex--;
      }
    // oldIndex > newIndex: items shifted right
    } else if (
      this._expandedIndex >= newIndex
      && this._expandedIndex < oldIndex
    ) {
      this._expandedIndex++;
    }
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  /**
   * Remove a widget from the list and re-render.
   *
   * @param index - Index of the widget to remove.
   */
  private _onDelete(index: number): void {
    this._widgets.splice(index, 1);
    if (this._expandedIndex === index) {
      this._expandedIndex = -1;
    } else if (this._expandedIndex > index) {
      this._expandedIndex -= 1;
    }
    if (this._sortSelectedIndex === index) {
      this._sortSelectedIndex = undefined;
    } else if (
      this._sortSelectedIndex !== undefined
      && this._sortSelectedIndex > index
    ) {
      this._sortSelectedIndex--;
    }
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  /**
   * Toggle the expanded/collapsed state of a widget row.
   *
   * @param index - Index of the widget to toggle.
   */
  private _onToggleExpand(index: number): void {
    this._expandedIndex =
      this._expandedIndex === index ? -1 : index;
    this._renderWidgetList();
  }

  /**
   * Handle keyboard events on the drag handle for
   * accessible reordering.
   *
   * Enter/Space toggles sort-selection mode for the
   * widget at the given index. While selected,
   * ArrowUp/ArrowDown moves the widget one position.
   * Escape cancels sort mode.
   *
   * @param ev    - Keyboard event from the handle.
   * @param index - Widget index in the array.
   */
  private _onHandleKeyDown(
    ev: KeyboardEvent,
    index: number,
  ): void {
    const { key } = ev;
    if (key === "Enter" || key === " ") {
      ev.preventDefault();
      this._sortSelectedIndex =
        this._sortSelectedIndex === index
          ? undefined
          : index;
      this._applySortSelectedClass();
      return;
    }
    if (key === "Escape") {
      ev.preventDefault();
      this._sortSelectedIndex = undefined;
      this._applySortSelectedClass();
      return;
    }
    if (this._sortSelectedIndex === undefined) return;
    if (key !== "ArrowUp" && key !== "ArrowDown") return;
    ev.preventDefault();
    const newIndex =
      key === "ArrowUp" ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= this._widgets.length) {
      return;
    }
    this._sortSelectedIndex = newIndex;
    this._moveWidget(index, newIndex);
    // Restore focus to the handle at its new position
    // after _renderWidgetList has rebuilt the DOM.
    requestAnimationFrame(() => {
      const item = this.shadowRoot!
        .querySelector<HTMLElement>(
          `.widget-item[data-index="${newIndex}"]`,
        );
      item
        ?.querySelector<HTMLElement>(".handle")
        ?.focus();
      this._applySortSelectedClass();
    });
  }

  /**
   * Apply or remove `.sort-selected` on each widget item
   * based on the current value of _sortSelectedIndex.
   */
  private _applySortSelectedClass(): void {
    this.shadowRoot!
      .querySelectorAll<HTMLElement>(".widget-item")
      .forEach((el) => {
        const idx = parseInt(
          el.dataset.index ?? "",
          10,
        );
        el.classList.toggle(
          "sort-selected",
          idx === this._sortSelectedIndex,
        );
      });
  }

  /**
   * Open the widget picker dialog. Creates the picker element
   * on first use and reuses it on subsequent clicks.
   */
  private _onAddBtnClick(): void {
    let picker = this.shadowRoot!.querySelector<EinkWidgetPicker>(
      "eink-widget-picker"
    );
    if (!picker) {
      picker = document.createElement(
        "eink-widget-picker"
      ) as EinkWidgetPicker;
      picker.addEventListener(
        "type-selected",
        ((ev: CustomEvent<{ type: string }>) => {
          this._onTypeSelected(ev.detail.type);
        }) as EventListener
      );
      this.shadowRoot!.appendChild(picker);
    }
    picker.open(WIDGET_TYPES);
  }

  /**
   * Handle a widget type selection from the picker. Appends a
   * new widget with default values and expands its form.
   *
   * @param type - Widget type key (e.g. "weather").
   */
  private _onTypeSelected(type: string): void {
    const meta = WIDGET_TYPES[type];
    if (!meta) return;
    const newWidget = { ...meta.defaults };
    this._widgets.push(newWidget);
    this._expandedIndex = this._widgets.length - 1;
    this._renderWidgetList();
    this._fireWidgetChange();
    const items = this.shadowRoot!
      .querySelectorAll<HTMLElement>(".widget-item");
    const last = items[items.length - 1];
    if (last) last.scrollIntoView({ block: "nearest" });
  }

  /**
   * Drive the Save button's visual state from the card after the
   * async API call completes.
   *
   * @param state - "saving" while the request is in-flight, "saved"
   *   on success (auto-reverts to idle after 2 s), "idle" to reset.
   */
  setSaveState(state: "idle" | "saving" | "saved"): void {
    const btn = this.shadowRoot?.querySelector<HTMLButtonElement>(
      ".save-btn",
    );
    if (!btn) return;
    if (this._saveTimeout) {
      clearTimeout(this._saveTimeout);
      this._saveTimeout = null;
    }
    if (state === "saving") {
      btn.textContent = "Saving…";
      btn.classList.add("saving");
      btn.classList.remove("saved");
      btn.disabled = true;
    } else if (state === "saved") {
      btn.textContent = "Saved!";
      btn.classList.remove("saving");
      btn.classList.add("saved");
      btn.disabled = false;
      this._saveTimeout = setTimeout(() => {
        this.setSaveState("idle");
      }, 2000);
    } else {
      btn.textContent = "Save";
      btn.classList.remove("saving", "saved");
      btn.disabled = false;
    }
  }

  /** Emit a "save" event with a snapshot of the widget list. */
  private _onSave(): void {
    this.dispatchEvent(
      new CustomEvent("save", {
        detail: { widgets: this._widgets.map((w) => ({ ...w })) },
        bubbles: true,
        composed: true,
      })
    );
  }

  /**
   * Emit a "widget-change" event with a shallow copy of the
   * current widget list.
   */
  private _fireWidgetChange(): void {
    this.dispatchEvent(
      new CustomEvent("widget-change", {
        detail: { widgets: this._widgets.map((w) => ({ ...w })) },
        bubbles: true,
        composed: true,
      })
    );
  }
}

// ── Registration ─────────────────────────────────────────────────

if (!customElements.get(EDITOR_TAG)) {
  customElements.define(EDITOR_TAG, EinkDashboardEditor);
}

// E-Ink Dashboard widget list editor panel.
// Loaded on demand by eink-dashboard-card.js when edit mode is entered.

import type {
  HomeAssistant,
  HaFormSchema,
  HaFormElement,
  EinkWidgetPicker,
  Widget,
  DisplayConfig,
  WidgetTypeMeta,
} from "./types/ha.js";
import "./eink-widget-picker.js";

const EDITOR_TAG = "eink-dashboard-editor";

// ── Constants (mirror const.py) ──────────────────────────────────

const FONT_SIZE_TEXT = 32;
const FONT_SIZE_WEATHER = 32;
const FONT_SIZE_DEVICE_BATTERY = 24;

// ── Widget type registry ─────────────────────────────────────────

export const WIDGET_TYPES: Record<string, WidgetTypeMeta> = {
  text: {
    label: "Text",
    description: "Custom text or label at any position",
    icon: "mdi:format-text",
    defaults: {
      type: "text",
      x: 24,
      y: 0,
      text: "",
      font_size: FONT_SIZE_TEXT,
      color: 0,
      align: "left",
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
    },
  },
  sensor_rows: {
    label: "Sensor Rows",
    description: "Entity states in a card with icon rows",
    icon: "mdi:thermometer",
    defaults: {
      type: "sensor_rows",
      title: "",
      x: 24,
      y: 0,
      w: 400,
      h: 112,
      entities: [],
      card_style: "none",
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
      font_size: FONT_SIZE_DEVICE_BATTERY,
      w: 200,
      h: 40,
    },
  },
  status_icons: {
    label: "Status Icons",
    description: "Binary sensor states as pill-shaped chips",
    icon: "mdi:checkbox-marked-circle",
    defaults: {
      type: "status_icons",
      title: "",
      x: 24,
      y: 0,
      w: 400,
      h: 40,
      entities: [],
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
      card_style: "none",
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
    default: "none",
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

export const SCHEMAS: Record<
  string,
  (d: DisplayConfig) => HaFormSchema[]
> = {
  text: (d) => [
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:format-text",
      schema: [
        { name: "text", required: true, selector: { text: {} } },
        {
          name: "align",
          default: "left",
          selector: {
            select: {
              options: [
                { value: "left", label: "Left" },
                { value: "center", label: "Center" },
                { value: "right", label: "Right" },
              ],
            },
          },
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
      schema: [
        {
          type: "grid",
          name: "",
          schema: [fontSizeSelector(FONT_SIZE_TEXT), colorSelector()],
        },
      ],
    },
  ],

  separator: (d) => [
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
      schema: [fontSizeSelector(FONT_SIZE_WEATHER)],
    },
  ],

  sensor_rows: (d) => [
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:thermometer",
      schema: [
        { name: "title", selector: { text: {} } },
        {
          name: "entities",
          selector: {
            entity: {
              multiple: true,
              domain: ["sensor", "binary_sensor"],
            },
          },
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

  device_battery: (d) => [
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
      schema: [
        {
          type: "grid",
          name: "",
          schema: [
            colorSelector(),
            fontSizeSelector(FONT_SIZE_DEVICE_BATTERY),
          ],
        },
      ],
    },
  ],

  status_icons: (d) => [
    {
      name: "content",
      type: "expandable",
      flatten: true,
      expanded: true,
      title: "Content",
      icon: "mdi:checkbox-marked-circle",
      schema: [
        { name: "title", selector: { text: {} } },
        {
          name: "entities",
          selector: {
            entity: {
              multiple: true,
              domain: "binary_sensor",
            },
          },
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
        { type: "grid", name: "", schema: posXYWH(d) },
      ],
    },
  ],

  waste_schedule: (d) => [
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
};

export const LABELS: Record<string, string> = {
  text: "Text",
  entity: "Entity",
  entities: "Entities",
  title: "Title",
  x: "X", y: "Y", w: "Width", h: "Height",
  direction: "Direction", style: "Style", length: "Length",
  font_size: "Font size",
  color: "Color",
  align: "Align",
  card_style: "Card style",
  layout: "Layout",
  entries: "Entries",
  forecast_days: "Forecast days",
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
}

// ── Summary helper (extracted for testability) ───────────────────

export function getSummary(widget: Widget): string {
  const t = widget.type;
  if (t === "text") {
    const s = String(widget.text || "");
    return s.length > 30 ? s.slice(0, 30) + "…" : (s || "(empty)");
  }
  if (t === "weather") {
    return widget.entity || "(no entity)";
  }
  if (t === "device_battery") {
    return "Device battery";
  }
  if (t === "sensor_rows" || t === "status_icons") {
    const title = widget.title ? `${widget.title} — ` : "";
    const count = (widget.entities || []).length;
    return `${title}${count} entit${count === 1 ? "y" : "ies"}`;
  }
  if (t === "waste_schedule") {
    const title = widget.title ? `${widget.title} — ` : "";
    const count = (widget.entries || []).length;
    return `${title}${count} entr${count === 1 ? "y" : "ies"}`;
  }
  if (t === "separator") {
    const dir = widget.direction === "vertical" ? "v" : "h";
    const sty = widget.style === "bar" ? "bar" : "line";
    return `${dir} ${sty} @${widget.y ?? 0}`;
  }
  return t;
}

// ── Editor class ─────────────────────────────────────────────────

class EinkDashboardEditor extends HTMLElement {
  private _hass: HomeAssistant | null = null;
  private _widgets: Widget[] = [];
  private _display: DisplayConfig = { width: 0, height: 0 };
  private _expandedIndex = -1;
  private _built = false;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  // ── Public API ─────────────────────────────────────────────────

  set hass(hass: HomeAssistant) {
    this._hass = hass;
    this.shadowRoot!
      .querySelectorAll<HaFormElement>("ha-form")
      .forEach((el) => {
        el.hass = hass;
      });
  }

  setWidgets(widgets: Widget[]): void {
    this._widgets = widgets.map((w) => ({ ...w }));
    this._expandedIndex = -1;
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
        }
        .widget-item {
          border-bottom: 1px solid
            var(--divider-color, #e8e8e8);
        }
        .widget-header {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 8px;
          cursor: default;
        }
        .widget-label {
          flex: 1;
          font-size: 13px;
          color: var(--primary-text-color, #212121);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .widget-type-badge {
          font-size: 11px;
          color: var(--secondary-text-color, #757575);
          margin-right: 4px;
          min-width: 90px;
        }
        .icon-btn {
          background: none;
          border: none;
          cursor: pointer;
          padding: 2px 4px;
          color: var(--secondary-text-color, #757575);
          font-size: 14px;
          line-height: 1;
          border-radius: 3px;
        }
        .icon-btn:hover {
          background: var(--divider-color, #e0e0e0);
        }
        .icon-btn.delete:hover {
          color: var(--error-color, #b00020);
        }
        .icon-btn.expand {
          color: var(--primary-color, #03a9f4);
        }
        .widget-form {
          padding: 8px 12px 12px 12px;
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
      </style>
      <div class="editor">
        <div class="editor-header">
          <span>Widgets</span>
          <button class="add-btn">+ Add Widget</button>
        </div>
        <div class="widget-list"></div>
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
   * Create the DOM element for a single widget row including
   * its header controls (move, expand, delete).
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
    const summary = getSummary(widget);
    const isExpanded = this._expandedIndex === index;
    const isFirst = index === 0;
    const isLast = index === this._widgets.length - 1;

    const item = document.createElement("div");
    item.className = "widget-item";

    const header = document.createElement("div");
    header.className = "widget-header";

    const upBtn = document.createElement("button");
    upBtn.className = "icon-btn";
    upBtn.title = "Move up";
    upBtn.textContent = "▲";
    if (isFirst) upBtn.disabled = true;

    const downBtn = document.createElement("button");
    downBtn.className = "icon-btn";
    downBtn.title = "Move down";
    downBtn.textContent = "▼";
    if (isLast) downBtn.disabled = true;

    const badge = document.createElement("span");
    badge.className = "widget-type-badge";
    badge.textContent = typeLabel;

    const labelEl = document.createElement("span");
    labelEl.className = "widget-label";
    labelEl.title = summary;
    labelEl.textContent = summary;

    const expandBtn = document.createElement("button");
    expandBtn.className = "icon-btn expand";
    expandBtn.title = isExpanded ? "Collapse" : "Edit";
    expandBtn.textContent = isExpanded ? "▾" : "▸";

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "icon-btn delete";
    deleteBtn.title = "Delete";
    deleteBtn.textContent = "✕";

    header.append(upBtn, downBtn, badge, labelEl, expandBtn, deleteBtn);

    upBtn.addEventListener("click", () => this._onMoveUp(index));
    downBtn.addEventListener(
      "click", () => this._onMoveDown(index)
    );
    expandBtn.addEventListener(
      "click", () => this._onToggleExpand(index)
    );
    deleteBtn.addEventListener(
      "click", () => this._onDelete(index)
    );

    item.appendChild(header);

    if (isExpanded && meta) {
      item.appendChild(this._buildWidgetForm(widget, index));
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
        // Preserve entries — ha-form doesn't know about
        // them so they'd be dropped by the spread.
        if (widget.type === "waste_schedule") {
          const cur = this._widgets[index] as
            unknown as Record<string, unknown>;
          if (!("entries" in data) && cur.entries) {
            data.entries = cur.entries;
          }
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

  // ── Inline summary update (avoids full re-render on edits) ────

  /**
   * Refresh the summary label for a single widget row without
   * re-rendering the entire list.
   *
   * @param index - Index of the widget to update.
   */
  private _updateSummary(index: number): void {
    const items = this.shadowRoot!
      .querySelectorAll<HTMLElement>(".widget-item");
    if (!items[index]) return;
    const label =
      items[index].querySelector<HTMLElement>(".widget-label");
    if (label) {
      const summary = getSummary(this._widgets[index]);
      label.textContent = summary;
      label.title = summary;
    }
  }

  // ── Event handlers ─────────────────────────────────────────────

  /**
   * Swap a widget with its predecessor and re-render the list.
   *
   * @param index - Index of the widget to move up.
   */
  private _onMoveUp(index: number): void {
    if (index === 0) return;
    [this._widgets[index - 1], this._widgets[index]] =
      [this._widgets[index], this._widgets[index - 1]];
    if (this._expandedIndex === index) {
      this._expandedIndex = index - 1;
    } else if (this._expandedIndex === index - 1) {
      this._expandedIndex = index;
    }
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  /**
   * Swap a widget with its successor and re-render the list.
   *
   * @param index - Index of the widget to move down.
   */
  private _onMoveDown(index: number): void {
    if (index >= this._widgets.length - 1) return;
    [this._widgets[index], this._widgets[index + 1]] =
      [this._widgets[index + 1], this._widgets[index]];
    if (this._expandedIndex === index) {
      this._expandedIndex = index + 1;
    } else if (this._expandedIndex === index + 1) {
      this._expandedIndex = index;
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
    if (this._expandedIndex === index) this._expandedIndex = -1;
    else if (this._expandedIndex > index) this._expandedIndex -= 1;
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

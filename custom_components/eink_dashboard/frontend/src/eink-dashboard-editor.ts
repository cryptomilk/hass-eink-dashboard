// E-Ink Dashboard widget list editor panel.
// Loaded on demand by eink-dashboard-card.js when edit mode is entered.

import type {
  HomeAssistant,
  HaFormSchema,
  HaFormElement,
  HaSelectElement,
  Widget,
  DisplayConfig,
  WidgetTypeMeta,
} from "./types/ha.js";

const EDITOR_TAG = "eink-dashboard-editor";

// ── Constants (mirror const.py) ─────────────────────────────────────────────

const FONT_SIZE_TEXT = 32;
const FONT_SIZE_WEATHER = 32;
const FONT_SIZE_SENSOR_ROWS = 32;
const FONT_SIZE_DEVICE_BATTERY = 24;
const FONT_SIZE_STATUS_ICONS = 28;
const FONT_SIZE_WASTE_SCHEDULE = 28;

// ── Widget type registry ──────────────────────────────────────────────────────

export const WIDGET_TYPES: Record<string, WidgetTypeMeta> = {
  text: {
    label: "Text",
    defaults: { type: "text", x: 24, y: 0, text: "", font_size: FONT_SIZE_TEXT, color: 0, align: "left" },
  },
  line: {
    label: "Line",
    defaults: { type: "line", x: 24, y: 0, x2: 24, y2: 0, color: 210, width: 1 },
  },
  separator: {
    label: "Separator",
    defaults: { type: "separator", y: 0, x: 24, color: 210 },
  },
  weather: {
    label: "Weather",
    defaults: { type: "weather", entity: "", x: 24, y: 0, forecast_days: 5, font_size: FONT_SIZE_WEATHER },
  },
  sensor_rows: {
    label: "Sensor Rows",
    defaults: { type: "sensor_rows", title: "", x: 24, y: 0, entities: [], font_size: FONT_SIZE_SENSOR_ROWS },
  },
  device_battery: {
    label: "Device Battery",
    defaults: { type: "device_battery", x: 24, y: 0, color: 0, font_size: FONT_SIZE_DEVICE_BATTERY },
  },
  status_icons: {
    label: "Status Icons",
    defaults: { type: "status_icons", title: "", x: 24, y: 0, entities: [], font_size: FONT_SIZE_STATUS_ICONS },
  },
  waste_schedule: {
    label: "Waste Schedule",
    defaults: { type: "waste_schedule", title: "", x: 24, y: 0, entities: [], font_size: FONT_SIZE_WASTE_SCHEDULE },
  },
};

// ── ha-form schema builders ──────────────────────────────────────────────────

const COLOR_OPTIONS = [
  { value: "0", label: "Black" },
  { value: "160", label: "Gray" },
  { value: "210", label: "Light gray" },
  { value: "255", label: "White" },
];

export const SCHEMAS: Record<string, (d: DisplayConfig) => HaFormSchema[]> = {
  text: (d) => [
    { name: "text", required: true, selector: { text: {} } },
    {
      type: "grid", name: "", schema: [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
        { name: "w", selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
      ],
    },
    {
      type: "grid", name: "", schema: [
        { name: "font_size", default: FONT_SIZE_TEXT, selector: { number: { min: 8, max: 72, mode: "box" } } },
        { name: "color", default: 0, selector: { select: {
          options: COLOR_OPTIONS, mode: "dropdown", custom_value: true,
        } } },
        { name: "align", default: "left", selector: { select: {
          options: [
            { value: "left", label: "Left" },
            { value: "center", label: "Center" },
            { value: "right", label: "Right" },
          ],
        } } },
      ],
    },
  ],

  line: (d) => [
    {
      type: "grid", name: "", schema: [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
      ],
    },
    {
      type: "grid", name: "", schema: [
        { name: "x2", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y2", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
      ],
    },
    {
      type: "grid", name: "", schema: [
        { name: "color", default: 210, selector: { select: {
          options: COLOR_OPTIONS, mode: "dropdown", custom_value: true,
        } } },
        { name: "width", default: 1, selector: { number: { min: 1, max: 20, mode: "box" } } },
      ],
    },
  ],

  separator: (d) => [
    {
      type: "grid", name: "", schema: [
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "w", selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
      ],
    },
    { name: "color", default: 210, selector: { select: {
      options: COLOR_OPTIONS, mode: "dropdown", custom_value: true,
    } } },
  ],

  weather: (d) => [
    { name: "entity", required: true, selector: { entity: { domain: "weather" } } },
    {
      type: "grid", name: "", schema: [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
        { name: "w", selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
      ],
    },
    {
      type: "grid", name: "", schema: [
        { name: "forecast_days", default: 5, selector: { number: { min: 0, max: 14, mode: "box" } } },
        { name: "font_size", default: FONT_SIZE_WEATHER, selector: { number: { min: 8, max: 72, mode: "box" } } },
      ],
    },
  ],

  sensor_rows: (d) => [
    { name: "title", selector: { text: {} } },
    {
      type: "grid", name: "", schema: [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
        { name: "w", selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "font_size", default: FONT_SIZE_SENSOR_ROWS, selector: { number: { min: 8, max: 72, mode: "box" } } },
      ],
    },
    { name: "entities", selector: { entity: { multiple: true } } },
  ],

  device_battery: (d) => [
    {
      type: "grid", name: "", schema: [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
      ],
    },
    {
      type: "grid", name: "", schema: [
        { name: "color", default: 0, selector: { select: {
          options: COLOR_OPTIONS, mode: "dropdown", custom_value: true,
        } } },
        { name: "font_size", default: FONT_SIZE_DEVICE_BATTERY, selector: { number: { min: 8, max: 72, mode: "box" } } },
      ],
    },
  ],

  status_icons: (d) => [
    { name: "title", selector: { text: {} } },
    {
      type: "grid", name: "", schema: [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
        { name: "w", selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "font_size", default: FONT_SIZE_STATUS_ICONS, selector: { number: { min: 8, max: 72, mode: "box" } } },
      ],
    },
    { name: "entities", selector: { entity: { multiple: true } } },
  ],

  waste_schedule: (d) => [
    { name: "title", selector: { text: {} } },
    {
      type: "grid", name: "", schema: [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
        { name: "w", selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "font_size", default: FONT_SIZE_WASTE_SCHEDULE, selector: { number: { min: 8, max: 72, mode: "box" } } },
      ],
    },
    { name: "entities", selector: { entity: { multiple: true } } },
  ],
};

export const LABELS: Record<string, string> = {
  text: "Text",
  entity: "Entity",
  entities: "Entities",
  title: "Title",
  x: "X", y: "Y", w: "Width",
  x2: "X2", y2: "Y2",
  font_size: "Font size",
  color: "Color",
  align: "Align",
  width: "Line width",
  forecast_days: "Forecast days",
};

// ── HA component loader ──────────────────────────────────────────────────────

type HaCardClass = CustomElementConstructor & { getConfigElement(): Promise<unknown> };

export async function loadHaComponents(): Promise<void> {
  if (!customElements.get("ha-form")) {
    const cls = customElements.get("hui-tile-card") as HaCardClass | undefined;
    if (cls) await cls.getConfigElement();
  }
  if (!customElements.get("ha-entity-picker")) {
    const cls = customElements.get("hui-entities-card") as HaCardClass | undefined;
    if (cls) await cls.getConfigElement();
  }
}

// ── Summary helper (extracted for testability) ────────────────────────────────

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
  if (t === "sensor_rows" || t === "status_icons" || t === "waste_schedule") {
    const title = widget.title ? `${widget.title} — ` : "";
    const count = (widget.entities || []).length;
    return `${title}${count} entit${count === 1 ? "y" : "ies"}`;
  }
  if (t === "separator") return `y=${widget.y ?? 0}`;
  if (t === "line") {
    return `(${widget.x ?? 0},${widget.y ?? 0}) → (${widget.x2 ?? 0},${widget.y2 ?? 0})`;
  }
  return t;
}

// ── Editor class ──────────────────────────────────────────────────────────────

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

  // ── Public API ────────────────────────────────────────────────────────────

  set hass(hass: HomeAssistant) {
    this._hass = hass;
    this.shadowRoot!.querySelectorAll<HaFormElement>("ha-form").forEach((el) => {
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
    const info = this.shadowRoot!.querySelector<HTMLElement>(".display-info");
    if (info) {
      info.textContent = `${display.width} × ${display.height}`;
    }
  }

  // ── Shadow DOM ────────────────────────────────────────────────────────────

  private async _buildShell(): Promise<void> {
    await loadHaComponents();
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
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          background: var(--secondary-background-color, #f5f5f5);
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
        .add-select-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 12px;
          background: var(--secondary-background-color, #f5f5f5);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .add-select-row label {
          font-size: 13px;
          color: var(--secondary-text-color, #757575);
          white-space: nowrap;
        }
        .add-select-row ha-select { flex: 1; }
        .cancel-add-btn {
          font-size: 12px;
          padding: 2px 8px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 4px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--secondary-text-color, #757575);
        }
        .widget-list {
          display: flex;
          flex-direction: column;
        }
        .widget-item {
          border-bottom: 1px solid var(--divider-color, #e8e8e8);
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
        .icon-btn:hover { background: var(--divider-color, #e0e0e0); }
        .icon-btn.delete:hover { color: var(--error-color, #b00020); }
        .icon-btn.expand { color: var(--primary-color, #03a9f4); }
        .widget-form {
          padding: 8px 12px 12px 12px;
          background: var(--secondary-background-color, #fafafa);
        }
        .editor-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 12px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          background: var(--secondary-background-color, #f5f5f5);
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
      </style>
      <div class="editor">
        <div class="editor-header">
          <span>Widgets</span>
          <button class="add-btn">+ Add Widget</button>
        </div>
        <div class="add-select-row" style="display:none">
          <label>Type:</label>
          <ha-select></ha-select>
          <button class="cancel-add-btn">Cancel</button>
        </div>
        <div class="widget-list"></div>
        <div class="editor-footer">
          <span class="display-info">${this._display.width} × ${this._display.height}</span>
          <button class="save-btn">Save</button>
        </div>
      </div>
    `;

    this.shadowRoot!.querySelector<HTMLButtonElement>(".add-btn")!.addEventListener(
      "click", () => this._onAddBtnClick()
    );
    this.shadowRoot!.querySelector<HTMLButtonElement>(".cancel-add-btn")!.addEventListener(
      "click", () => this._cancelAdd()
    );
    const typeSelect = this.shadowRoot!.querySelector<HaSelectElement>(".add-select-row ha-select")!;
    typeSelect.options = Object.entries(WIDGET_TYPES).map(([k, v]) => ({
      value: k,
      label: v.label,
    }));
    typeSelect.addEventListener("selected", (ev) => {
      const value = (ev as CustomEvent<{ value?: string }>).detail?.value;
      if (value) this._onTypeSelected(value);
    });
    this.shadowRoot!.querySelector<HTMLButtonElement>(".save-btn")!.addEventListener(
      "click", () => this._onSave()
    );
    this._built = true;
  }

  private async _rebuild(): Promise<void> {
    if (!this._built) {
      await this._buildShell();
    }
    this._renderWidgetList();
  }

  // ── Widget list rendering ─────────────────────────────────────────────────

  private _renderWidgetList(): void {
    const list = this.shadowRoot!.querySelector<HTMLElement>(".widget-list")!;
    list.innerHTML = "";
    this._widgets.forEach((widget, index) => {
      list.appendChild(this._buildWidgetItem(widget, index));
    });
  }

  private _buildWidgetItem(widget: Widget, index: number): HTMLElement {
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
    downBtn.addEventListener("click", () => this._onMoveDown(index));
    expandBtn.addEventListener("click", () => this._onToggleExpand(index));
    deleteBtn.addEventListener("click", () => this._onDelete(index));

    item.appendChild(header);

    if (isExpanded && meta) {
      item.appendChild(this._buildWidgetForm(widget, index));
    }

    return item;
  }

  // ── Per-widget form ───────────────────────────────────────────────────────

  private _buildWidgetForm(widget: Widget, index: number): HTMLElement {
    const container = document.createElement("div");
    container.className = "widget-form";
    const schemaFn = SCHEMAS[widget.type];
    if (!schemaFn) return container;

    const formData: Record<string, unknown> = { ...widget };
    if ("color" in formData && formData.color !== undefined) {
      formData.color = String(formData.color);
    }

    const form = document.createElement("ha-form") as unknown as HaFormElement;
    form.hass = this._hass;
    form.data = formData;
    form.schema = schemaFn(this._display);
    form.computeLabel = (s) => LABELS[s.name] || s.name;
    form.addEventListener("value-changed", ((ev: CustomEvent<{ value: Record<string, unknown> }>) => {
      ev.stopPropagation();
      const raw = ev.detail.value;
      const data: Record<string, unknown> = { type: widget.type, ...raw };
      if ("color" in data && data.color !== undefined) {
        data.color = parseInt(String(data.color), 10) || 0;
      }
      this._widgets[index] = data as unknown as Widget;
      this._fireWidgetChange();
      this._updateSummary(index);
    }) as EventListener);
    container.appendChild(form);
    return container;
  }

  // ── Inline summary update (avoid full re-render on field edits) ───────────

  private _updateSummary(index: number): void {
    const items = this.shadowRoot!.querySelectorAll<HTMLElement>(".widget-item");
    if (!items[index]) return;
    const label = items[index].querySelector<HTMLElement>(".widget-label");
    if (label) {
      const summary = getSummary(this._widgets[index]);
      label.textContent = summary;
      label.title = summary;
    }
  }

  // ── Event handlers ────────────────────────────────────────────────────────

  private _onMoveUp(index: number): void {
    if (index === 0) return;
    [this._widgets[index - 1], this._widgets[index]] =
      [this._widgets[index], this._widgets[index - 1]];
    if (this._expandedIndex === index) this._expandedIndex = index - 1;
    else if (this._expandedIndex === index - 1) this._expandedIndex = index;
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  private _onMoveDown(index: number): void {
    if (index >= this._widgets.length - 1) return;
    [this._widgets[index], this._widgets[index + 1]] =
      [this._widgets[index + 1], this._widgets[index]];
    if (this._expandedIndex === index) this._expandedIndex = index + 1;
    else if (this._expandedIndex === index + 1) this._expandedIndex = index;
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  private _onDelete(index: number): void {
    this._widgets.splice(index, 1);
    if (this._expandedIndex === index) this._expandedIndex = -1;
    else if (this._expandedIndex > index) this._expandedIndex -= 1;
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  private _onToggleExpand(index: number): void {
    this._expandedIndex = this._expandedIndex === index ? -1 : index;
    this._renderWidgetList();
  }

  private _onAddBtnClick(): void {
    this.shadowRoot!.querySelector<HTMLElement>(".add-select-row")!.style.display = "flex";
    this.shadowRoot!.querySelector<HTMLElement>(".add-btn")!.style.display = "none";
  }

  private _cancelAdd(): void {
    this.shadowRoot!.querySelector<HTMLElement>(".add-select-row")!.style.display = "none";
    this.shadowRoot!.querySelector<HTMLElement>(".add-btn")!.style.display = "";
    const sel = this.shadowRoot!.querySelector<HaSelectElement>(".add-select-row ha-select")!;
    sel.value = "";
  }

  private _onTypeSelected(type: string): void {
    const meta = WIDGET_TYPES[type];
    if (!meta) return;
    const newWidget = { ...meta.defaults };
    this._widgets.push(newWidget);
    this._expandedIndex = this._widgets.length - 1;
    this._cancelAdd();
    this._renderWidgetList();
    this._fireWidgetChange();
    const items = this.shadowRoot!.querySelectorAll<HTMLElement>(".widget-item");
    const last = items[items.length - 1];
    if (last) last.scrollIntoView({ block: "nearest" });
  }

  private _onSave(): void {
    this.dispatchEvent(
      new CustomEvent("save", {
        detail: { widgets: this._widgets.map((w) => ({ ...w })) },
        bubbles: true,
        composed: true,
      })
    );
  }

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

// ── Registration ──────────────────────────────────────────────────────────────

if (!customElements.get(EDITOR_TAG)) {
  customElements.define(EDITOR_TAG, EinkDashboardEditor);
}

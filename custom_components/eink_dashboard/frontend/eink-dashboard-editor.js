// E-Ink Dashboard widget list editor panel.
// Loaded on demand by eink-dashboard-card.js when edit mode is entered.
const EDITOR_TAG = "eink-dashboard-editor";
// ── Constants (mirror const.py) ─────────────────────────────────────────────
const FONT_SIZE_TEXT = 32;
const FONT_SIZE_WEATHER = 32;
const FONT_SIZE_SENSOR_ROWS = 32;
const FONT_SIZE_DEVICE_BATTERY = 24;
const FONT_SIZE_STATUS_ICONS = 28;
const FONT_SIZE_WASTE_SCHEDULE = 28;
// ── Widget type registry ──────────────────────────────────────────────────────
export const WIDGET_TYPES = {
    text: {
        label: "Text (single line)",
        defaults: { type: "text", x: 24, y: 0, text: "", font_size: FONT_SIZE_TEXT, color: 0, align: "left" },
    },
    text_multiline: {
        label: "Text (multiline)",
        defaults: { type: "text_multiline", x: 24, y: 0, w: 0, text: "", font_size: FONT_SIZE_TEXT, color: 0 },
    },
    line: {
        label: "Divider",
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
    chart: {
        label: "Chart",
        defaults: { type: "chart", x: 24, y: 0, w: 0, h: 200, config: { graph_span: "24h", series: [], yaxis: [] } },
    },
};
// ── ha-form schema builders ──────────────────────────────────────────────────
const COLOR_OPTIONS = [
    { value: "0", label: "Black" },
    { value: "160", label: "Gray" },
    { value: "210", label: "Light gray" },
    { value: "255", label: "White" },
];
/** Position selectors for x and y coordinates. */
function posXY(d) {
    return [
        { name: "x", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
        { name: "y", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
    ];
}
/** Position selectors for x, y, and optional width override. */
function posXYW(d) {
    return [
        ...posXY(d),
        { name: "w", selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
    ];
}
/** Font size number selector with the given default. */
const FONT_OPTIONS = [
    { value: "roboto", label: "Roboto" },
    { value: "roboto_medium", label: "Roboto Medium" },
    { value: "ibm_plex_mono", label: "IBM Plex Mono" },
    { value: "noto_sans", label: "Noto Sans" },
];
function fontSizeSelector(defaultSize) {
    return { name: "font_size", default: defaultSize, selector: { number: { min: 8, max: 72, mode: "box" } } };
}
function fontRow(defaultSize) {
    return {
        type: "grid", name: "", schema: [
            { name: "font", default: "roboto", selector: { select: { options: FONT_OPTIONS, mode: "dropdown" } } },
            fontSizeSelector(defaultSize),
        ],
    };
}
/** Color dropdown selector with the given default (0=black). */
function colorSelector(defaultColor = 0) {
    return { name: "color", default: defaultColor, selector: { select: {
                options: COLOR_OPTIONS, mode: "dropdown", custom_value: true,
            } } };
}
export const SCHEMAS = {
    text: (d) => [
        { type: "grid", name: "", schema: posXYW(d) },
        { name: "text", required: true, selector: { text: {} } },
        fontRow(FONT_SIZE_TEXT),
        {
            type: "grid", name: "", schema: [
                colorSelector(),
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
    text_multiline: (d) => [
        { type: "grid", name: "", schema: posXYW(d) },
        { name: "text", required: true, selector: { text: { multiline: true } } },
        fontRow(FONT_SIZE_TEXT),
        {
            type: "grid", name: "", schema: [
                colorSelector(),
                { name: "line_height", selector: { number: { min: 8, max: 120, mode: "box" } } },
            ],
        },
    ],
    line: (d) => [
        { type: "grid", name: "", schema: posXY(d) },
        {
            type: "grid", name: "", schema: [
                { name: "x2", default: 24, selector: { number: { min: 0, max: d.width, step: 8, mode: "box" } } },
                { name: "y2", default: 0, selector: { number: { min: 0, max: d.height, step: 8, mode: "box" } } },
            ],
        },
        {
            type: "grid", name: "", schema: [
                colorSelector(210),
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
        colorSelector(210),
    ],
    weather: (d) => [
        { type: "grid", name: "", schema: posXYW(d) },
        { name: "entity", required: true, selector: { entity: { domain: "weather" } } },
        {
            type: "grid", name: "", schema: [
                fontRow(FONT_SIZE_WEATHER),
                { name: "forecast_days", default: 5, selector: { number: { min: 0, max: 14, mode: "box" } } },
            ],
        },
    ],
    sensor_rows: (d) => [
        { type: "grid", name: "", schema: posXYW(d) },
        fontRow(FONT_SIZE_SENSOR_ROWS),
        { name: "title", selector: { text: {} } },
        { name: "entities", selector: { entity: { multiple: true } } },
    ],
    device_battery: (d) => [
        { type: "grid", name: "", schema: posXY(d) },
        fontRow(FONT_SIZE_DEVICE_BATTERY),
        colorSelector(),
    ],
    status_icons: (d) => [
        { type: "grid", name: "", schema: posXYW(d) },
        fontRow(FONT_SIZE_STATUS_ICONS),
        { name: "title", selector: { text: {} } },
        { name: "entities", selector: { entity: { multiple: true } } },
    ],
    waste_schedule: (d) => [
        { type: "grid", name: "", schema: posXYW(d) },
        fontRow(FONT_SIZE_WASTE_SCHEDULE),
        { name: "title", selector: { text: {} } },
        { name: "entities", selector: { entity: { multiple: true } } },
    ],
    chart: (d) => [
        {
            type: "grid", name: "", schema: [
                ...posXYW(d),
                { name: "h", default: 200, selector: { number: { min: 50, max: d.height, step: 8, mode: "box" } } },
            ],
        },
        { name: "entities", selector: { entity: { multiple: true } } },
        { name: "graph_span", selector: { text: {} } },
        { type: "grid", name: "", schema: [
                { name: "title", selector: { text: {} } },
                { name: "title_font_size", default: 18, selector: { number: { min: 8, max: 72, mode: "box" } } },
            ] },
        { type: "grid", name: "", schema: [
                { name: "ylabel", selector: { text: {} } },
                { name: "xlabel", selector: { text: {} } },
            ] },
        { name: "label_font_size", default: 18, selector: { number: { min: 8, max: 48, mode: "box" } } },
        { name: "legend", default: "none", selector: { select: {
                    options: [
                        { value: "none", label: "None" },
                        { value: "top", label: "Top" },
                        { value: "bottom", label: "Bottom" },
                    ],
                    mode: "dropdown",
                } } },
    ],
};
export const LABELS = {
    text: "Text",
    entity: "Entity",
    entities: "Entities",
    title: "Title",
    x: "X", y: "Y", w: "Width",
    x2: "X2", y2: "Y2",
    font: "Font",
    font_size: "Size",
    color: "Color",
    align: "Align",
    width: "Line width",
    forecast_days: "Forecast days",
    graph_span: "Graph span (e.g. 6h, 24h, 7d)",
    h: "Height",
    ylabel: "Y-axis label",
    xlabel: "X-axis label",
    legend: "Legend",
    title_font_size: "Title font size",
    label_font_size: "Axis label font size",
};
export async function loadHaComponents() {
    if (!customElements.get("ha-form")) {
        const cls = customElements.get("hui-tile-card");
        if (cls)
            await cls.getConfigElement();
    }
    if (!customElements.get("ha-entity-picker")) {
        const cls = customElements.get("hui-entities-card");
        if (cls)
            await cls.getConfigElement();
    }
}
// ── Summary helper (extracted for testability) ────────────────────────────────
export function getSummary(widget) {
    const t = widget.type;
    if (t === "text" || t === "text_multiline") {
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
    if (t === "chart") {
        const span = widget.graph_span
            ?? widget.config?.graph_span
            ?? "24h";
        const seriesCount = (widget.config?.series ?? []).length;
        const entityCount = (widget.entities ?? []).length;
        const n = seriesCount || entityCount;
        return `${span} — ${n} sensor${n !== 1 ? "s" : ""}`;
    }
    if (t === "separator")
        return `y=${widget.y ?? 0}`;
    if (t === "line") {
        return `(${widget.x ?? 0},${widget.y ?? 0}) → (${widget.x2 ?? 0},${widget.y2 ?? 0})`;
    }
    return t;
}
// ── Editor class ──────────────────────────────────────────────────────────────
class EinkDashboardEditor extends HTMLElement {
    constructor() {
        super();
        this._hass = null;
        this._widgets = [];
        this._display = { width: 0, height: 0, rotation: 0 };
        this._expandedIndex = -1;
        this._built = false;
        this.attachShadow({ mode: "open" });
    }
    // ── Public API ────────────────────────────────────────────────────────────
    set hass(hass) {
        this._hass = hass;
        this.shadowRoot.querySelectorAll("ha-form").forEach((el) => {
            el.hass = hass;
        });
    }
    setWidgets(widgets) {
        this._widgets = widgets.map((w) => ({ ...w }));
        this._expandedIndex = -1;
        this._rebuild();
    }
    setDisplay(display) {
        this._display = display;
        const info = this.shadowRoot.querySelector(".display-info");
        if (info) {
            info.textContent = `${display.width} × ${display.height}`;
        }
    }
    // ── Shadow DOM ────────────────────────────────────────────────────────────
    async _buildShell() {
        await loadHaComponents();
        this.shadowRoot.innerHTML = `
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
        this.shadowRoot.querySelector(".add-btn").addEventListener("click", () => this._onAddBtnClick());
        this.shadowRoot.querySelector(".cancel-add-btn").addEventListener("click", () => this._cancelAdd());
        const typeSelect = this.shadowRoot.querySelector(".add-select-row ha-select");
        typeSelect.options = Object.entries(WIDGET_TYPES).map(([k, v]) => ({
            value: k,
            label: v.label,
        }));
        typeSelect.addEventListener("selected", (ev) => {
            const value = ev.detail?.value;
            if (value)
                this._onTypeSelected(value);
        });
        this.shadowRoot.querySelector(".save-btn").addEventListener("click", () => this._onSave());
        this._built = true;
    }
    async _rebuild() {
        if (!this._built) {
            await this._buildShell();
        }
        this._renderWidgetList();
    }
    // ── Widget list rendering ─────────────────────────────────────────────────
    _renderWidgetList() {
        const list = this.shadowRoot.querySelector(".widget-list");
        list.innerHTML = "";
        this._widgets.forEach((widget, index) => {
            list.appendChild(this._buildWidgetItem(widget, index));
        });
    }
    _buildWidgetItem(widget, index) {
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
        if (isFirst)
            upBtn.disabled = true;
        const downBtn = document.createElement("button");
        downBtn.className = "icon-btn";
        downBtn.title = "Move down";
        downBtn.textContent = "▼";
        if (isLast)
            downBtn.disabled = true;
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
    _buildWidgetForm(widget, index) {
        const container = document.createElement("div");
        container.className = "widget-form";
        const schemaFn = SCHEMAS[widget.type];
        if (!schemaFn)
            return container;
        const formData = { ...widget };
        if ("color" in formData && formData.color !== undefined) {
            formData.color = String(formData.color);
        }
        const form = document.createElement("ha-form");
        form.hass = this._hass;
        form.data = formData;
        form.schema = schemaFn(this._display);
        form.computeLabel = (s) => LABELS[s.name] || s.name;
        form.addEventListener("value-changed", ((ev) => {
            ev.stopPropagation();
            const raw = ev.detail.value;
            const data = { type: widget.type, ...raw };
            if ("color" in data && data.color !== undefined) {
                data.color = parseInt(String(data.color), 10) || 0;
            }
            this._widgets[index] = data;
            this._fireWidgetChange();
            this._updateSummary(index);
        }));
        container.appendChild(form);
        return container;
    }
    // ── Inline summary update (avoid full re-render on field edits) ───────────
    _updateSummary(index) {
        const items = this.shadowRoot.querySelectorAll(".widget-item");
        if (!items[index])
            return;
        const label = items[index].querySelector(".widget-label");
        if (label) {
            const summary = getSummary(this._widgets[index]);
            label.textContent = summary;
            label.title = summary;
        }
    }
    // ── Event handlers ────────────────────────────────────────────────────────
    _onMoveUp(index) {
        if (index === 0)
            return;
        [this._widgets[index - 1], this._widgets[index]] =
            [this._widgets[index], this._widgets[index - 1]];
        if (this._expandedIndex === index)
            this._expandedIndex = index - 1;
        else if (this._expandedIndex === index - 1)
            this._expandedIndex = index;
        this._renderWidgetList();
        this._fireWidgetChange();
    }
    _onMoveDown(index) {
        if (index >= this._widgets.length - 1)
            return;
        [this._widgets[index], this._widgets[index + 1]] =
            [this._widgets[index + 1], this._widgets[index]];
        if (this._expandedIndex === index)
            this._expandedIndex = index + 1;
        else if (this._expandedIndex === index + 1)
            this._expandedIndex = index;
        this._renderWidgetList();
        this._fireWidgetChange();
    }
    _onDelete(index) {
        this._widgets.splice(index, 1);
        if (this._expandedIndex === index)
            this._expandedIndex = -1;
        else if (this._expandedIndex > index)
            this._expandedIndex -= 1;
        this._renderWidgetList();
        this._fireWidgetChange();
    }
    _onToggleExpand(index) {
        this._expandedIndex = this._expandedIndex === index ? -1 : index;
        this._renderWidgetList();
    }
    _onAddBtnClick() {
        this.shadowRoot.querySelector(".add-select-row").style.display = "flex";
        this.shadowRoot.querySelector(".add-btn").style.display = "none";
    }
    _cancelAdd() {
        this.shadowRoot.querySelector(".add-select-row").style.display = "none";
        this.shadowRoot.querySelector(".add-btn").style.display = "";
        const sel = this.shadowRoot.querySelector(".add-select-row ha-select");
        sel.value = "";
    }
    _onTypeSelected(type) {
        const meta = WIDGET_TYPES[type];
        if (!meta)
            return;
        const newWidget = { ...meta.defaults };
        this._widgets.push(newWidget);
        this._expandedIndex = this._widgets.length - 1;
        this._cancelAdd();
        this._renderWidgetList();
        this._fireWidgetChange();
        const items = this.shadowRoot.querySelectorAll(".widget-item");
        const last = items[items.length - 1];
        if (last)
            last.scrollIntoView({ block: "nearest" });
    }
    _onSave() {
        this.dispatchEvent(new CustomEvent("save", {
            detail: { widgets: this._widgets.map((w) => ({ ...w })) },
            bubbles: true,
            composed: true,
        }));
    }
    _fireWidgetChange() {
        this.dispatchEvent(new CustomEvent("widget-change", {
            detail: { widgets: this._widgets.map((w) => ({ ...w })) },
            bubbles: true,
            composed: true,
        }));
    }
}
// ── Registration ──────────────────────────────────────────────────────────────
if (!customElements.get(EDITOR_TAG)) {
    customElements.define(EDITOR_TAG, EinkDashboardEditor);
}
//# sourceMappingURL=eink-dashboard-editor.js.map
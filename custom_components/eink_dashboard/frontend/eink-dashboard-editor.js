// E-Ink Dashboard widget list editor panel.
// Loaded on demand by eink-dashboard-card.js when edit mode is entered.

const EDITOR_TAG = "eink-dashboard-editor";

// ── Widget type registry ──────────────────────────────────────────────────────
// Defines the label, defaults, and form field schema for each widget type.

const WIDGET_TYPES = {
  text: {
    label: "Text",
    defaults: { type: "text", x: 24, y: 0, text: "", font_size: 22, color: 0, align: "left" },
    fields: [
      { key: "text",      label: "Text",      kind: "text"   },
      { key: "x",         label: "X",         kind: "number" },
      { key: "y",         label: "Y",         kind: "number" },
      { key: "font_size", label: "Font size", kind: "number" },
      { key: "color",     label: "Color",     kind: "number" },
      { key: "align",     label: "Align",     kind: "select",
        options: ["left", "center", "right"] },
    ],
  },
  line: {
    label: "Line",
    defaults: { type: "line", x: 24, y: 0, x2: 24, y2: 0, color: 210, width: 1 },
    fields: [
      { key: "x",     label: "X",     kind: "number" },
      { key: "y",     label: "Y",     kind: "number" },
      { key: "x2",    label: "X2",    kind: "number" },
      { key: "y2",    label: "Y2",    kind: "number" },
      { key: "color", label: "Color", kind: "number" },
      { key: "width", label: "Width", kind: "number" },
    ],
  },
  separator: {
    label: "Separator",
    defaults: { type: "separator", y: 0, x: 24, color: 210 },
    fields: [
      { key: "y",     label: "Y",     kind: "number" },
      { key: "x",     label: "X",     kind: "number" },
      { key: "color", label: "Color", kind: "number" },
    ],
  },
  weather: {
    label: "Weather",
    defaults: { type: "weather", entity: "", x: 24, y: 0, forecast_days: 3 },
    fields: [
      { key: "entity",       label: "Entity",        kind: "entity" },
      { key: "x",            label: "X",             kind: "number" },
      { key: "y",            label: "Y",             kind: "number" },
      { key: "forecast_days", label: "Forecast days", kind: "number" },
    ],
  },
  sensor_rows: {
    label: "Sensor Rows",
    defaults: { type: "sensor_rows", title: "", x: 24, y: 0, entities: [] },
    fields: [
      { key: "title",    label: "Title",    kind: "text"     },
      { key: "x",        label: "X",        kind: "number"   },
      { key: "y",        label: "Y",        kind: "number"   },
      { key: "entities", label: "Entities", kind: "entities" },
    ],
  },
  battery_bar: {
    label: "Battery Bar",
    defaults: { type: "battery_bar", entity: "", x: 24, y: 0, color: 0 },
    fields: [
      { key: "entity", label: "Entity", kind: "entity" },
      { key: "x",      label: "X",      kind: "number" },
      { key: "y",      label: "Y",      kind: "number" },
      { key: "color",  label: "Color",  kind: "number" },
    ],
  },
  status_icons: {
    label: "Status Icons",
    defaults: { type: "status_icons", title: "", x: 24, y: 0, entities: [] },
    fields: [
      { key: "title",    label: "Title",    kind: "text"     },
      { key: "x",        label: "X",        kind: "number"   },
      { key: "y",        label: "Y",        kind: "number"   },
      { key: "entities", label: "Entities", kind: "entities" },
    ],
  },
  waste_schedule: {
    label: "Waste Schedule",
    defaults: { type: "waste_schedule", title: "", x: 24, y: 0, entities: [] },
    fields: [
      { key: "title",    label: "Title",    kind: "text"     },
      { key: "x",        label: "X",        kind: "number"   },
      { key: "y",        label: "Y",        kind: "number"   },
      { key: "entities", label: "Entities", kind: "entities" },
    ],
  },
};

// ── Editor class ──────────────────────────────────────────────────────────────

class EinkDashboardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._widgets = [];
    this._display = { width: 0, height: 0 };
    this._expandedIndex = -1;
    this._addingWidget = false;
    this._built = false;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  set hass(hass) {
    this._hass = hass;
    // Propagate hass to any mounted entity pickers
    this.shadowRoot.querySelectorAll("ha-entity-picker").forEach((el) => {
      el.hass = hass;
    });
  }

  setWidgets(widgets) {
    this._widgets = widgets.map((w) => ({ ...w }));
    this._expandedIndex = -1;
    this._addingWidget = false;
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

  _buildShell() {
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
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .field-row {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .field-label {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
        }
        ha-textfield { width: 100%; }
        ha-select { width: 100%; }
        .entities-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .entity-row {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .entity-row ha-entity-picker { flex: 1; }
        .add-entity-btn {
          font-size: 12px;
          padding: 4px 10px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 4px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          align-self: flex-start;
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
          <ha-select>
            ${Object.entries(WIDGET_TYPES)
              .map(([k, v]) =>
                `<mwc-list-item value="${k}">${v.label}</mwc-list-item>`
              )
              .join("")}
          </ha-select>
          <button class="cancel-add-btn">Cancel</button>
        </div>
        <div class="widget-list"></div>
        <div class="editor-footer">
          <span class="display-info">${this._display.width} × ${this._display.height}</span>
          <button class="save-btn">Save</button>
        </div>
      </div>
    `;

    this.shadowRoot.querySelector(".add-btn").addEventListener(
      "click", () => this._onAddBtnClick()
    );
    this.shadowRoot.querySelector(".cancel-add-btn").addEventListener(
      "click", () => this._cancelAdd()
    );
    const typeSelect = this.shadowRoot.querySelector(".add-select-row ha-select");
    typeSelect.addEventListener("selected", (ev) => {
      const value = ev.detail?.item?.getAttribute("value");
      if (value) this._onTypeSelected(value);
    });
    this.shadowRoot.querySelector(".save-btn").addEventListener(
      "click", () => this._onSave()
    );
    this._built = true;
  }

  _rebuild() {
    if (!this._built) {
      this._buildShell();
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
    const summary = this._getSummary(widget);
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
      item.appendChild(this._buildForm(widget, index));
    }

    return item;
  }

  _getSummary(widget) {
    const t = widget.type;
    if (t === "text") {
      const s = String(widget.text || "");
      return s.length > 30 ? s.slice(0, 30) + "…" : (s || "(empty)");
    }
    if (t === "weather" || t === "battery_bar") {
      return widget.entity || "(no entity)";
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

  // ── Per-widget form ───────────────────────────────────────────────────────

  _buildForm(widget, index) {
    const form = document.createElement("div");
    form.className = "widget-form";
    const meta = WIDGET_TYPES[widget.type];
    if (!meta) return form;

    for (const field of meta.fields) {
      const row = document.createElement("div");
      row.className = "field-row";
      const label = document.createElement("div");
      label.className = "field-label";
      label.textContent = field.label;
      row.appendChild(label);
      row.appendChild(this._buildField(field, widget, index));
      form.appendChild(row);
    }
    return form;
  }

  _buildField(field, widget, index) {
    const { key, kind } = field;
    const value = widget[key];

    if (kind === "text" || kind === "number") {
      const el = document.createElement("ha-textfield");
      el.type = kind === "number" ? "number" : "text";
      el.value = value ?? "";
      el.label = field.label;
      el.addEventListener("input", (ev) => {
        const raw = ev.target.value;
        this._widgets[index] = {
          ...this._widgets[index],
          [key]: kind === "number" ? (Number.isNaN(parseInt(raw, 10)) ? (this._widgets[index][key] ?? 0) : parseInt(raw, 10)) : raw,
        };
        this._fireWidgetChange();
        this._updateSummary(index);
      });
      return el;
    }

    if (kind === "select") {
      const el = document.createElement("ha-select");
      el.label = field.label;
      el.value = value ?? field.options[0];
      for (const opt of field.options) {
        const item = document.createElement("mwc-list-item");
        item.setAttribute("value", opt);
        item.textContent = opt;
        if (opt === (value ?? field.options[0])) {
          item.setAttribute("selected", "");
        }
        el.appendChild(item);
      }
      el.addEventListener("selected", (ev) => {
        const v = ev.detail?.item?.getAttribute("value");
        if (v !== undefined) {
          this._widgets[index] = { ...this._widgets[index], [key]: v };
          this._fireWidgetChange();
          this._updateSummary(index);
        }
      });
      return el;
    }

    if (kind === "entity") {
      const el = document.createElement("ha-entity-picker");
      if (this._hass) el.hass = this._hass;
      el.value = value || "";
      el.label = field.label;
      el.allowCustomEntity = true;
      el.addEventListener("value-changed", (ev) => {
        this._widgets[index] = {
          ...this._widgets[index],
          [key]: ev.detail.value,
        };
        this._fireWidgetChange();
        this._updateSummary(index);
      });
      return el;
    }

    if (kind === "entities") {
      return this._buildEntitiesField(value || [], index, key);
    }

    // Fallback: plain text input
    const el = document.createElement("ha-textfield");
    el.value = value ?? "";
    return el;
  }

  _buildEntitiesField(entities, widgetIndex, key) {
    const container = document.createElement("div");
    container.className = "entities-list";

    const renderRows = () => {
      container.innerHTML = "";
      const current = this._widgets[widgetIndex][key] || [];
      current.forEach((entityId, i) => {
        const row = document.createElement("div");
        row.className = "entity-row";

        const picker = document.createElement("ha-entity-picker");
        if (this._hass) picker.hass = this._hass;
        picker.value = entityId;
        picker.allowCustomEntity = true;
        picker.addEventListener("value-changed", (ev) => {
          const list = [...(this._widgets[widgetIndex][key] || [])];
          list[i] = ev.detail.value;
          this._widgets[widgetIndex] = {
            ...this._widgets[widgetIndex],
            [key]: list,
          };
          this._fireWidgetChange();
          this._updateSummary(widgetIndex);
        });

        const delBtn = document.createElement("button");
        delBtn.className = "icon-btn delete";
        delBtn.title = "Remove";
        delBtn.textContent = "✕";
        delBtn.addEventListener("click", () => {
          const list = [...(this._widgets[widgetIndex][key] || [])];
          list.splice(i, 1);
          this._widgets[widgetIndex] = {
            ...this._widgets[widgetIndex],
            [key]: list,
          };
          this._fireWidgetChange();
          this._updateSummary(widgetIndex);
          renderRows();
        });

        row.appendChild(picker);
        row.appendChild(delBtn);
        container.appendChild(row);
      });

      const addBtn = document.createElement("button");
      addBtn.className = "add-entity-btn";
      addBtn.textContent = "+ Add Entity";
      addBtn.addEventListener("click", () => {
        const list = [...(this._widgets[widgetIndex][key] || []), ""];
        this._widgets[widgetIndex] = {
          ...this._widgets[widgetIndex],
          [key]: list,
        };
        this._fireWidgetChange();
        this._updateSummary(widgetIndex);
        renderRows();
      });
      container.appendChild(addBtn);
    };

    renderRows();
    return container;
  }

  // ── Inline summary update (avoid full re-render on field edits) ───────────

  _updateSummary(index) {
    const items = this.shadowRoot.querySelectorAll(".widget-item");
    if (!items[index]) return;
    const label = items[index].querySelector(".widget-label");
    if (label) {
      const summary = this._getSummary(this._widgets[index]);
      label.textContent = summary;
      label.title = summary;
    }
  }

  // ── Event handlers ────────────────────────────────────────────────────────

  _onMoveUp(index) {
    if (index === 0) return;
    [this._widgets[index - 1], this._widgets[index]] =
      [this._widgets[index], this._widgets[index - 1]];
    if (this._expandedIndex === index) this._expandedIndex = index - 1;
    else if (this._expandedIndex === index - 1) this._expandedIndex = index;
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  _onMoveDown(index) {
    if (index >= this._widgets.length - 1) return;
    [this._widgets[index], this._widgets[index + 1]] =
      [this._widgets[index + 1], this._widgets[index]];
    if (this._expandedIndex === index) this._expandedIndex = index + 1;
    else if (this._expandedIndex === index + 1) this._expandedIndex = index;
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  _onDelete(index) {
    this._widgets.splice(index, 1);
    if (this._expandedIndex === index) this._expandedIndex = -1;
    else if (this._expandedIndex > index) this._expandedIndex -= 1;
    this._renderWidgetList();
    this._fireWidgetChange();
  }

  _onToggleExpand(index) {
    this._expandedIndex = this._expandedIndex === index ? -1 : index;
    this._renderWidgetList();
  }

  _onAddBtnClick() {
    this._addingWidget = true;
    this.shadowRoot.querySelector(".add-select-row").style.display = "flex";
    this.shadowRoot.querySelector(".add-btn").style.display = "none";
  }

  _cancelAdd() {
    this._addingWidget = false;
    this.shadowRoot.querySelector(".add-select-row").style.display = "none";
    this.shadowRoot.querySelector(".add-btn").style.display = "";
    // Reset select value
    const sel = this.shadowRoot.querySelector(".add-select-row ha-select");
    sel.value = "";
  }

  _onTypeSelected(type) {
    const meta = WIDGET_TYPES[type];
    if (!meta) return;
    const newWidget = { ...meta.defaults };
    this._widgets.push(newWidget);
    this._expandedIndex = this._widgets.length - 1;
    this._cancelAdd();
    this._renderWidgetList();
    this._fireWidgetChange();
    // Scroll new item into view
    const items = this.shadowRoot.querySelectorAll(".widget-item");
    const last = items[items.length - 1];
    if (last) last.scrollIntoView({ block: "nearest" });
  }

  _onSave() {
    this.dispatchEvent(
      new CustomEvent("save", {
        detail: { widgets: this._widgets.map((w) => ({ ...w })) },
        bubbles: true,
        composed: true,
      })
    );
  }

  _fireWidgetChange() {
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

customElements.define(EDITOR_TAG, EinkDashboardEditor);

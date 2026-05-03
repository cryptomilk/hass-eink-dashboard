// E-Ink Dashboard Lovelace card — read-only canvas preview.
// Mirrors the rendering logic from render.py using Canvas 2D.

const CARD_TAG = "eink-dashboard-card";

// ── Constants (mirror const.py + render.py) ──────────────────────────────────

const PADDING = 24;
const COLOR_BLACK = 0;
const COLOR_WHITE = 255;
const COLOR_GRAY = 160;
const COLOR_LIGHT_GRAY = 210;

const SENSOR_ROW_HEIGHT = 30;

const BATTERY_BODY_W = 22;
const BATTERY_BODY_H = 10;
const BATTERY_NUB_W = 2;
const BATTERY_NUB_H = 4;

const STATUS_ICON_SIZE = 12;
const STATUS_ROW_HEIGHT = 26;
const PROBLEM_DEVICE_CLASSES = new Set([
  "door", "window", "garage_door", "opening",
  "moisture", "smoke", "gas", "problem", "safety",
  "tamper", "vibration",
]);

const WASTE_ROW_HEIGHT = 28;
const WASTE_ICON_SIZE = 10;

const DAY_ABBREV = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// ── Helpers ───────────────────────────────────────────────────────────────────

function grayColor(v) {
  return `rgb(${v},${v},${v})`;
}

// Parse a raw state string as days-until-today.
// Tries ISO date first, then integer. Returns null on failure.
function parseDaysUntil(raw) {
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    const [y, m, d] = raw.slice(0, 10).split("-").map(Number);
    const target = new Date(y, m - 1, d);
    if (!isNaN(target)) {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return Math.round((target - today) / 86400000);
    }
  }
  const n = parseInt(raw, 10);
  return isNaN(n) ? null : n;
}

function formatRelativeDate(days, raw) {
  if (days === null || days < 0) return raw;
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

// ── Card class ────────────────────────────────────────────────────────────────

class EinkDashboardCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._layout = null;
    this._canvas = null;
    this._ctx = null;
    this._renderPending = false;
    this._connected = false;
    this._fetching = false;
    this._showServerImage = false;
    this._serverImg = null;
    this._container = null;
    this._toggleBtn = null;
    this._editMode = false;
    this._editor = null;
    this._editorContainer = null;
    this._editBtn = null;
    this._saving = false;
    this._saveError = null;
  }

  // ── Lovelace lifecycle ────────────────────────────────────────────────────

  setConfig(config) {
    if (!config.config_entry) {
      throw new Error("config_entry is required");
    }
    const entryChanged = this._config && this._config.config_entry !== config.config_entry;
    this._config = config;
    this._buildShadowDom();
    if (entryChanged) {
      this._layout = null;
      this._canvas = null;
      this._ctx = null;
      this._serverImg = null;
      this._fetching = false;
      this._showServerImage = false;
      this._editMode = false;
      this._editor = null;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (this._editor) {
      this._editor.hass = hass;
    }
    if (this._config && !this._layout && !this._fetching) {
      this._fetchLayout();
    }
    if (this._layout) {
      this._scheduleRender();
    }
  }

  connectedCallback() {
    this._connected = true;
    if (this._layout) {
      this._scheduleRender();
    }
  }

  disconnectedCallback() {
    this._connected = false;
  }

  getCardSize() {
    if (this._layout) {
      return Math.ceil(this._layout.display.height / 50);
    }
    return 8;
  }

  // ── Shadow DOM ────────────────────────────────────────────────────────────

  _buildShadowDom() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { display: block; overflow: hidden; }
        .container {
          position: relative;
          width: 100%;
          background: #fff;
        }
        .loading, .error {
          padding: 16px;
          color: var(--secondary-text-color, #888);
          font-size: 14px;
        }
        .error { color: var(--error-color, #b00020); }
        canvas {
          display: block;
          width: 100%;
          height: auto;
          image-rendering: pixelated;
        }
        img.server-render {
          display: block;
          width: 100%;
          height: auto;
        }
        .toolbar {
          display: flex;
          justify-content: flex-end;
          gap: 6px;
          padding: 4px 8px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          background: var(--card-background-color, #fff);
        }
        .toggle-btn {
          font-size: 12px;
          padding: 4px 8px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 4px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
        }
        .toggle-btn.active {
          background: var(--primary-color, #03a9f4);
          color: #fff;
          border-color: var(--primary-color, #03a9f4);
        }
        .editor-container {
          border-top: 1px solid var(--divider-color, #e0e0e0);
          max-height: 520px;
          overflow-y: auto;
        }
        .save-error {
          padding: 8px 12px;
          color: var(--error-color, #b00020);
          font-size: 13px;
          background: var(--secondary-background-color, #fff3f3);
          border-top: 1px solid var(--error-color, #b00020);
          display: none;
        }
      </style>
      <ha-card>
        <div class="container">
          <div class="loading">Loading layout…</div>
        </div>
        <div class="toolbar">
          <button class="toggle-btn" title="Toggle between canvas preview and server-rendered image">
            Show rendered image
          </button>
          <button class="toggle-btn edit-btn" title="Edit widget layout">
            Edit Widgets
          </button>
        </div>
        <div class="editor-container" style="display:none"></div>
        <div class="save-error"></div>
      </ha-card>
    `;
    this._container = this.shadowRoot.querySelector(".container");
    this._toggleBtn = this.shadowRoot.querySelector(".toggle-btn");
    this._toggleBtn.addEventListener("click", () => this._onToggle());
    this._editBtn = this.shadowRoot.querySelector(".edit-btn");
    this._editBtn.addEventListener("click", () => this._onToggleEdit());
    this._editorContainer = this.shadowRoot.querySelector(".editor-container");
    this._saveError = this.shadowRoot.querySelector(".save-error");
  }

  // ── Edit mode ─────────────────────────────────────────────────────────────

  async _ensureEditorLoaded() {
    if (customElements.get("eink-dashboard-editor")) return;
    const script = document.createElement("script");
    script.src = "/eink_dashboard/frontend/eink-dashboard-editor.js";
    document.head.appendChild(script);
    await customElements.whenDefined("eink-dashboard-editor");
  }

  async _onToggleEdit() {
    if (!this._layout) return;
    this._editMode = !this._editMode;
    if (this._editMode) {
      await this._ensureEditorLoaded();
      this._editBtn.textContent = "Close Editor";
      this._editBtn.classList.add("active");
      this._editorContainer.style.display = "block";
      if (!this._editor) {
        this._editor = document.createElement("eink-dashboard-editor");
        this._editor.addEventListener(
          "widget-change", (ev) => this._onWidgetChange(ev)
        );
        this._editor.addEventListener(
          "save", (ev) => this._onSave(ev)
        );
        this._editor.setWidgets(this._layout.widgets);
        this._editor.setDisplay(this._layout.display);
        this._editorContainer.appendChild(this._editor);
      }
      if (this._hass) this._editor.hass = this._hass;
    } else {
      this._editBtn.textContent = "Edit Widgets";
      this._editBtn.classList.remove("active");
      this._editorContainer.style.display = "none";
    }
  }

  _onWidgetChange(ev) {
    this._layout.widgets = ev.detail.widgets;
    this._scheduleRender();
  }

  async _onSave(ev) {
    if (this._saving) return;
    this._saving = true;
    try {
      const entryId = this._config.config_entry;
      await this._hass.callApi(
        "POST",
        `eink_dashboard/${entryId}/layout`,
        ev.detail.widgets,
      );
      await this._fetchLayout();
      if (this._editor && this._layout) {
        this._editor.setWidgets(this._layout.widgets);
        this._editor.setDisplay(this._layout.display);
      }
      if (this._saveError) this._saveError.style.display = "none";
    } catch (err) {
      console.error("Failed to save layout:", err);
      if (this._saveError) {
        this._saveError.textContent = `Save failed: ${err.message || err}`;
        this._saveError.style.display = "block";
      }
    } finally {
      this._saving = false;
    }
  }

  // ── Layout fetch ──────────────────────────────────────────────────────────

  async _fetchLayout() {
    this._fetching = true;
    try {
      const entryId = this._config.config_entry;
      const resp = await this._hass.callApi(
        "GET",
        `eink_dashboard/${entryId}/layout`,
      );
      this._layout = resp;
      this._initCanvas();
      this._scheduleRender();
    } catch (err) {
      const div = document.createElement("div");
      div.className = "error";
      div.textContent = `Failed to load layout: ${err.message}`;
      this._container.replaceChildren(div);
    } finally {
      this._fetching = false;
    }
  }

  _initCanvas() {
    const { width, height } = this._layout.display;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    this._canvas = canvas;
    this._ctx = canvas.getContext("2d");

    const img = document.createElement("img");
    img.className = "server-render";
    img.style.display = "none";
    this._serverImg = img;

    this._container.innerHTML = "";
    this._container.appendChild(canvas);
    this._container.appendChild(img);
  }

  // ── Render scheduling ─────────────────────────────────────────────────────

  _scheduleRender() {
    if (!this._connected || !this._layout || this._showServerImage) return;
    if (this._renderPending) return;
    this._renderPending = true;
    requestAnimationFrame(() => {
      this._renderPending = false;
      this._render();
    });
  }

  _render() {
    if (!this._ctx || !this._layout || !this._hass) return;
    const ctx = this._ctx;
    const { width, height } = this._layout.display;

    ctx.fillStyle = grayColor(COLOR_WHITE);
    ctx.fillRect(0, 0, width, height);

    const dispatch = {
      text: (w) => this._renderText(ctx, w),
      line: (w) => this._renderLine(ctx, w),
      separator: (w) => this._renderSeparator(ctx, w),
      weather: (w) => this._renderWeather(ctx, w),
      sensor_rows: (w) => this._renderSensorRows(ctx, w),
      battery_bar: (w) => this._renderBatteryBar(ctx, w),
      status_icons: (w) => this._renderStatusIcons(ctx, w),
      waste_schedule: (w) => this._renderWasteSchedule(ctx, w),
    };

    for (const widget of this._layout.widgets) {
      const fn = dispatch[widget.type];
      if (fn) fn(widget);
    }
  }

  // ── Server image toggle ───────────────────────────────────────────────────

  _onToggle() {
    if (!this._canvas) return;
    this._showServerImage = !this._showServerImage;
    if (this._showServerImage) {
      const entryId = this._config.config_entry;
      this._serverImg.src = `/api/eink_dashboard/${entryId}/image.png?_t=${Date.now()}`;
      this._canvas.style.display = "none";
      this._serverImg.style.display = "block";
      this._toggleBtn.textContent = "Show canvas preview";
      this._toggleBtn.classList.add("active");
    } else {
      this._serverImg.style.display = "none";
      this._canvas.style.display = "block";
      this._toggleBtn.textContent = "Show rendered image";
      this._toggleBtn.classList.remove("active");
      this._scheduleRender();
    }
  }

  // ── State helper ──────────────────────────────────────────────────────────

  _getState(entityId) {
    const s = this._hass.states[entityId];
    return s || null;
  }

  // ── Widget renderers ──────────────────────────────────────────────────────

  // mirrors render.py: render_text (lines 77-100)
  _renderText(ctx, widget) {
    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    const text = String(widget.text ?? "");
    const fontSize = widget.font_size ?? 22;
    const color = widget.color ?? COLOR_BLACK;
    const align = widget.align ?? "left";
    const width = this._layout.display.width;

    ctx.font = `${fontSize}px sans-serif`;
    ctx.fillStyle = grayColor(color);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    let drawX = x;
    if (align === "right") {
      const tw = ctx.measureText(text).width;
      drawX = width - PADDING - tw;
    } else if (align === "center") {
      const tw = ctx.measureText(text).width;
      drawX = (width - tw) / 2;
    }

    ctx.fillText(text, drawX, y);
  }

  // mirrors render.py: render_line (lines 103-114)
  _renderLine(ctx, widget) {
    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    const x2 = widget.x2 ?? x;
    const y2 = widget.y2 ?? y;
    const color = widget.color ?? COLOR_LIGHT_GRAY;
    const lineWidth = widget.width ?? 1;

    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = grayColor(color);
    ctx.lineWidth = lineWidth;
    ctx.stroke();
  }

  // mirrors render.py: render_separator (lines 117-126)
  _renderSeparator(ctx, widget) {
    const y = widget.y ?? 0;
    const color = widget.color ?? COLOR_LIGHT_GRAY;
    const x0 = widget.x ?? PADDING;
    const x1 = this._layout.display.width - PADDING;

    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.strokeStyle = grayColor(color);
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // mirrors render.py: render_weather (lines 157-265)
  _renderWeather(ctx, widget) {
    const entityId = widget.entity ?? "";
    const stateObj = this._getState(entityId);
    if (!stateObj) return;

    const x = widget.x ?? PADDING;
    let y = widget.y ?? 0;
    const forecastDays = widget.forecast_days ?? 3;
    const width = this._layout.display.width;

    const condition = stateObj.state ?? "";
    const attrs = stateObj.attributes ?? {};
    const temp = attrs.temperature ?? "--";
    const humidity = attrs.humidity ?? "--";
    const wind = attrs.wind_speed ?? "--";

    // Main weather icon (placeholder "?")
    ctx.font = `64px sans-serif`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText("?", x + 45, y + 45);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    // Temperature
    ctx.font = "48px sans-serif";
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(`${temp}°C`, x + 100, y);

    // Condition label
    const condLabel = condition.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    ctx.font = "22px sans-serif";
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillText(condLabel, x + 100, y + 54);

    // Humidity (right-aligned)
    const humText = `${humidity}%`;
    ctx.font = "22px sans-serif";
    ctx.fillStyle = grayColor(COLOR_BLACK);
    const humW = ctx.measureText(humText).width;
    ctx.fillText(humText, width - PADDING - humW, y + 8);

    // Wind (right-aligned)
    const windText = `${wind} km/h`;
    const windW = ctx.measureText(windText).width;
    ctx.fillText(windText, width - PADDING - windW, y + 38);

    // Forecast
    const forecast = attrs.forecast ?? [];
    if (!forecast.length || forecastDays <= 0) return;

    const colWidth = Math.floor((width - x - PADDING) / forecastDays);
    const forecastY = y + 100;

    // Separator line
    ctx.beginPath();
    ctx.moveTo(x, forecastY - 4);
    ctx.lineTo(width - PADDING, forecastY - 4);
    ctx.strokeStyle = grayColor(COLOR_LIGHT_GRAY);
    ctx.lineWidth = 1;
    ctx.stroke();

    for (let i = 0; i < Math.min(forecastDays, forecast.length); i++) {
      const day = forecast[i];
      const cx = x + colWidth * i + Math.floor(colWidth / 2);

      // Day label
      let dayLabel = "";
      if (day.datetime) {
        const [y, m, d] = day.datetime.slice(0, 10).split("-").map(Number);
        const dt = new Date(y, m - 1, d);
        // JS getDay(): 0=Sun … 6=Sat; Python weekday(): 0=Mon … 6=Sun
        dayLabel = DAY_ABBREV[(dt.getDay() + 6) % 7];
      }
      ctx.font = "16px sans-serif";
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.textBaseline = "top";
      ctx.textAlign = "center";
      ctx.fillText(dayLabel, cx, forecastY);

      // Forecast icon placeholder
      ctx.font = "28px sans-serif";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.textBaseline = "middle";
      ctx.fillText("?", cx, forecastY + 38);

      // Hi/Lo
      const hi = day.temperature ?? "";
      const lo = day.templow ?? "";
      const hiLo = `${hi}° / ${lo}°`;
      ctx.font = "16px sans-serif";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.textBaseline = "top";
      ctx.fillText(hiLo, cx, forecastY + 60);
    }

    // Reset to defaults
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
  }

  // mirrors render.py: render_sensor_rows (lines 271-308)
  _renderSensorRows(ctx, widget) {
    const x = widget.x ?? PADDING;
    let y = widget.y ?? 0;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const width = this._layout.display.width;

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    if (title) {
      ctx.font = "22px sans-serif";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += 32;
    }

    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes ?? {};
      const label = attrs.friendly_name ?? entityId;
      const value = stateObj.state ?? "";
      const unit = attrs.unit_of_measurement ?? "";
      const displayVal = unit ? `${value}${unit}` : value;

      ctx.font = "22px sans-serif";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, x + 16, y);

      const valW = ctx.measureText(displayVal).width;
      ctx.fillText(displayVal, width - PADDING - valW, y);

      y += SENSOR_ROW_HEIGHT;
    }
  }

  // mirrors render.py: render_battery_bar (lines 317-367)
  _renderBatteryBar(ctx, widget) {
    const entityId = widget.entity ?? "";
    const stateObj = this._getState(entityId);
    if (!stateObj) return;

    const raw = stateObj.state ?? "";
    const pctFloat = parseFloat(raw);
    if (isNaN(pctFloat)) return;
    const pct = Math.max(0, Math.min(100, Math.round(pctFloat)));

    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    const color = widget.color ?? COLOR_BLACK;

    const bw = BATTERY_BODY_W;
    const bh = BATTERY_BODY_H;

    // Outline
    ctx.strokeStyle = grayColor(COLOR_GRAY);
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, bw, bh);

    // Nub
    const nubY = y + Math.floor((bh - BATTERY_NUB_H) / 2);
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillRect(x + bw + 1, nubY, BATTERY_NUB_W, BATTERY_NUB_H);

    // Fill bar
    const fillW = Math.floor((bw - 2) * pct / 100);
    if (fillW > 0) {
      ctx.fillStyle = grayColor(color);
      ctx.fillRect(x + 1, y + 1, fillW, bh - 2);
    }

    // Label
    ctx.font = "14px sans-serif";
    ctx.fillStyle = grayColor(color);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillText(`${pct}%`, x + bw + BATTERY_NUB_W + 4, y - 2);
  }

  // mirrors render.py: render_status_icons (lines 387-439)
  _renderStatusIcons(ctx, widget) {
    const x = widget.x ?? PADDING;
    let y = widget.y ?? 0;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const width = this._layout.display.width;

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    if (title) {
      ctx.font = "22px sans-serif";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += 30;
    }

    let curX = x;
    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes ?? {};
      const label = attrs.friendly_name ?? entityId;
      const isOn = stateObj.state === "on";
      const deviceClass = attrs.device_class ?? "";
      const isProblem = isOn && PROBLEM_DEVICE_CLASSES.has(deviceClass);

      ctx.font = "18px sans-serif";
      const textW = ctx.measureText(label).width;
      const itemW = STATUS_ICON_SIZE + 6 + textW + 20;

      if (curX + itemW > width - PADDING && curX > x) {
        curX = x;
        y += STATUS_ROW_HEIGHT;
      }

      const s = STATUS_ICON_SIZE;
      if (isProblem) {
        ctx.fillStyle = grayColor(COLOR_BLACK);
        ctx.fillRect(curX, y + 4, s, s);
      } else {
        ctx.strokeStyle = grayColor(COLOR_GRAY);
        ctx.lineWidth = 1;
        ctx.strokeRect(curX, y + 4, s, s);
      }

      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, curX + s + 6, y);

      curX += itemW;
    }
  }

  // mirrors render.py: render_waste_schedule (lines 468-527)
  _renderWasteSchedule(ctx, widget) {
    const x = widget.x ?? PADDING;
    let y = widget.y ?? 0;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const width = this._layout.display.width;

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    if (title) {
      ctx.font = "22px sans-serif";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += 32;
    }

    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes ?? {};
      const label = attrs.friendly_name ?? entityId;
      const raw = stateObj.state ?? "";

      const days = parseDaysUntil(raw);
      if (days !== null && (days < 0 || days > 3)) continue;

      const s = WASTE_ICON_SIZE;
      const cx = x + s / 2;
      const cy = y + 6 + s / 2;
      const r = s / 2;

      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, 2 * Math.PI);
      if (days !== null && days <= 1) {
        ctx.fillStyle = grayColor(COLOR_BLACK);
        ctx.fill();
      } else {
        ctx.strokeStyle = grayColor(COLOR_GRAY);
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      ctx.font = "18px sans-serif";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, x + s + 8, y);

      const dateStr = formatRelativeDate(days, raw);
      const dateW = ctx.measureText(dateStr).width;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillText(dateStr, width - PADDING - dateW, y);

      y += WASTE_ROW_HEIGHT;
    }
  }
}

// ── Registration ──────────────────────────────────────────────────────────────

customElements.define(CARD_TAG, EinkDashboardCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "E-Ink Dashboard",
  description: "Read-only WYSIWYG canvas preview of an e-ink dashboard",
});

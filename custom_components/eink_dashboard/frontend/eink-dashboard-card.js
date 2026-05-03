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
const SENSOR_TITLE_ADVANCE = 32;

const BATTERY_BODY_W = 22;
const BATTERY_BODY_H = 10;
const BATTERY_NUB_W = 2;
const BATTERY_NUB_H = 4;

const STATUS_ICON_SIZE = 12;
const STATUS_ROW_HEIGHT = 26;
const STATUS_TITLE_ADVANCE = 30;
const PROBLEM_DEVICE_CLASSES = new Set([
  "door", "window", "garage_door", "opening",
  "moisture", "smoke", "gas", "problem", "safety",
  "tamper", "vibration",
]);

const WASTE_ROW_HEIGHT = 28;
const WASTE_TITLE_ADVANCE = 32;
const WASTE_ICON_SIZE = 10;

const DAY_ABBREV = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const HANDLE_SIZE = 8;
const HANDLE_HIT_RADIUS = 10;

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
    this._widgetBounds = [];
    this._dragIndex = -1;
    this._dragStartCX = 0;
    this._dragStartCY = 0;
    this._dragWidgetStart = null;
    this._hoverIndex = -1;
    this._resizeIndex = -1;
    this._resizeHandle = null;
    this._resizeStartCX = 0;
    this._resizeStartCY = 0;
    this._resizeWidgetStart = null;
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
    canvas.style.touchAction = "none";
    this._canvas = canvas;
    this._ctx = canvas.getContext("2d");

    canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    canvas.addEventListener("pointerup", (e) => this._onPointerUp(e));
    canvas.addEventListener("pointercancel", (e) => this._onPointerCancel(e));
    canvas.addEventListener("pointerleave", (e) => this._onPointerLeave(e));

    const img = document.createElement("img");
    img.className = "server-render";
    img.style.display = "none";
    this._serverImg = img;

    this._container.innerHTML = "";
    this._container.appendChild(canvas);
    this._container.appendChild(img);
  }

  // ── Drag-to-reposition ────────────────────────────────────────────────────

  _canvasCoords(event) {
    const rect = this._canvas.getBoundingClientRect();
    const scaleX = this._canvas.width / rect.width;
    const scaleY = this._canvas.height / rect.height;
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  _hitTest(cx, cy) {
    for (let i = this._widgetBounds.length - 1; i >= 0; i--) {
      const b = this._widgetBounds[i];
      if (cx >= b.x && cx <= b.x + b.w && cy >= b.y && cy <= b.y + b.h) {
        return b.index;
      }
    }
    return -1;
  }

  _getHandles(bounds, widget) {
    if (widget.type === "line") {
      return [
        { id: "p1", cx: widget.x ?? 0, cy: widget.y ?? 0 },
        { id: "p2", cx: widget.x2 ?? 0, cy: widget.y2 ?? 0 },
      ];
    }
    if (widget.type === "battery_bar") return [];
    return [
      { id: "nw", cx: bounds.x, cy: bounds.y },
      { id: "ne", cx: bounds.x + bounds.w, cy: bounds.y },
      { id: "sw", cx: bounds.x, cy: bounds.y + bounds.h },
      { id: "se", cx: bounds.x + bounds.w, cy: bounds.y + bounds.h },
    ];
  }

  _handleHitTest(cx, cy) {
    for (let i = this._widgetBounds.length - 1; i >= 0; i--) {
      const b = this._widgetBounds[i];
      const widget = this._layout.widgets[b.index];
      for (const h of this._getHandles(b, widget)) {
        const dx = cx - h.cx;
        const dy = cy - h.cy;
        if (dx * dx + dy * dy <= HANDLE_HIT_RADIUS * HANDLE_HIT_RADIUS) {
          return { index: b.index, handleId: h.id };
        }
      }
    }
    return null;
  }

  _getResizeCursor(handleId) {
    if (handleId === "p1" || handleId === "p2") return "crosshair";
    return "ew-resize";
  }

  _onPointerDown(event) {
    if (!this._editMode || this._showServerImage || !this._layout) return;
    const { x: cx, y: cy } = this._canvasCoords(event);

    const handleHit = this._handleHitTest(cx, cy);
    if (handleHit) {
      event.preventDefault();
      this._canvas.setPointerCapture(event.pointerId);
      const w = this._layout.widgets[handleHit.index];
      this._resizeIndex = handleHit.index;
      this._resizeHandle = handleHit.handleId;
      this._resizeStartCX = cx;
      this._resizeStartCY = cy;
      this._resizeWidgetStart = {
        x: w.x ?? 0, y: w.y ?? 0,
        x2: w.x2 ?? 0, y2: w.y2 ?? 0,
        w: w.w,
      };
      this._canvas.style.cursor = this._getResizeCursor(handleHit.handleId);
      return;
    }

    const idx = this._hitTest(cx, cy);
    if (idx < 0) return;
    event.preventDefault();
    this._canvas.setPointerCapture(event.pointerId);
    const w = this._layout.widgets[idx];
    this._dragIndex = idx;
    this._dragStartCX = cx;
    this._dragStartCY = cy;
    this._dragWidgetStart = {
      x: w.x ?? 0,
      y: w.y ?? 0,
      x2: w.x2,
      y2: w.y2,
    };
    this._canvas.style.cursor = "grabbing";
  }

  _onPointerMove(event) {
    if (!this._editMode || this._showServerImage || !this._layout) return;
    const { x: cx, y: cy } = this._canvasCoords(event);

    if (this._resizeIndex >= 0) {
      event.preventDefault();
      const dx = Math.round(cx - this._resizeStartCX);
      const dy = Math.round(cy - this._resizeStartCY);
      const w = this._layout.widgets[this._resizeIndex];
      const s = this._resizeWidgetStart;
      const { width: dw, height: dh } = this._layout.display;
      const handle = this._resizeHandle;

      if (handle === "p1") {
        w.x = Math.max(0, Math.min(dw - 1, s.x + dx));
        w.y = Math.max(0, Math.min(dh - 1, s.y + dy));
      } else if (handle === "p2") {
        w.x2 = Math.max(0, Math.min(dw - 1, s.x2 + dx));
        w.y2 = Math.max(0, Math.min(dh - 1, s.y2 + dy));
      } else if (handle === "ne" || handle === "se") {
        const startRight = s.x + (s.w ?? (dw - PADDING - s.x));
        const newRight = Math.max(s.x + 20, Math.min(dw, startRight + dx));
        w.w = Math.round(newRight - s.x);
      } else if (handle === "nw" || handle === "sw") {
        const startRight = s.x + (s.w ?? (dw - PADDING - s.x));
        const newX = Math.max(0, Math.min(startRight - 20, s.x + dx));
        w.x = Math.round(newX);
        w.w = Math.round(startRight - newX);
      }
      this._scheduleRender();
      return;
    }

    if (this._dragIndex >= 0) {
      event.preventDefault();
      const dx = Math.round(cx - this._dragStartCX);
      const dy = Math.round(cy - this._dragStartCY);
      const w = this._layout.widgets[this._dragIndex];
      const s = this._dragWidgetStart;
      const { width, height } = this._layout.display;
      w.x = Math.max(0, Math.min(width - 1, s.x + dx));
      w.y = Math.max(0, Math.min(height - 1, s.y + dy));
      if (s.x2 !== undefined) {
        w.x2 = Math.max(0, Math.min(width - 1, s.x2 + dx));
        w.y2 = Math.max(0, Math.min(height - 1, s.y2 + dy));
      }
      this._scheduleRender();
    } else {
      const handleHit = this._handleHitTest(cx, cy);
      if (handleHit) {
        if (this._hoverIndex !== handleHit.index) {
          this._hoverIndex = handleHit.index;
          this._scheduleRender();
        }
        this._canvas.style.cursor = this._getResizeCursor(handleHit.handleId);
        return;
      }
      const hoverIdx = this._hitTest(cx, cy);
      if (hoverIdx !== this._hoverIndex) {
        this._hoverIndex = hoverIdx;
        this._canvas.style.cursor = hoverIdx >= 0 ? "grab" : "";
        this._scheduleRender();
      }
    }
  }

  _onPointerUp(event) {
    if (this._resizeIndex >= 0) {
      this._canvas.releasePointerCapture(event.pointerId);
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._hoverIndex = -1;
      this._canvas.style.cursor = "";
      this._scheduleRender();
      if (this._editor) {
        this._editor.setWidgets(this._layout.widgets);
      }
      return;
    }
    if (this._dragIndex < 0) return;
    this._canvas.releasePointerCapture(event.pointerId);
    this._dragIndex = -1;
    this._dragWidgetStart = null;
    this._hoverIndex = -1;
    this._canvas.style.cursor = "";
    this._scheduleRender();
    if (this._editor) {
      this._editor.setWidgets(this._layout.widgets);
    }
  }

  _onPointerCancel() {
    if (this._resizeIndex >= 0) {
      const w = this._layout.widgets[this._resizeIndex];
      const s = this._resizeWidgetStart;
      w.x = s.x;
      w.w = s.w;
      w.x2 = s.x2;
      w.y2 = s.y2;
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._hoverIndex = -1;
      this._canvas.style.cursor = "";
      this._scheduleRender();
      return;
    }
    if (this._dragIndex < 0) return;
    this._dragIndex = -1;
    this._dragWidgetStart = null;
    this._hoverIndex = -1;
    this._canvas.style.cursor = "";
    this._scheduleRender();
  }

  _onPointerLeave(event) {
    if (this._dragIndex >= 0 || this._resizeIndex >= 0) return;
    if (this._hoverIndex >= 0) {
      this._hoverIndex = -1;
      this._canvas.style.cursor = "";
      this._scheduleRender();
    }
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

    this._widgetBounds = [];
    for (let i = 0; i < this._layout.widgets.length; i++) {
      const widget = this._layout.widgets[i];
      const fn = dispatch[widget.type];
      if (!fn) continue;
      const bounds = fn(widget);
      if (bounds) this._widgetBounds.push({ index: i, ...bounds });
    }

    const highlightIdx =
      this._resizeIndex >= 0 ? this._resizeIndex :
      this._dragIndex >= 0 ? this._dragIndex : this._hoverIndex;
    if (this._editMode && highlightIdx >= 0) {
      const entry = this._widgetBounds.find((b) => b.index === highlightIdx);
      if (entry) {
        ctx.save();
        ctx.strokeStyle = "rgba(3, 169, 244, 0.8)";
        ctx.lineWidth = 2;
        const isActive = this._dragIndex >= 0 || this._resizeIndex >= 0;
        ctx.setLineDash(isActive ? [] : [4, 3]);
        ctx.strokeRect(entry.x - 3, entry.y - 3, entry.w + 6, entry.h + 6);

        const widget = this._layout.widgets[highlightIdx];
        const handles = this._getHandles(entry, widget);
        ctx.setLineDash([]);
        for (const h of handles) {
          ctx.fillStyle = "rgba(3, 169, 244, 0.9)";
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1;
          if (widget.type === "line") {
            ctx.beginPath();
            ctx.arc(h.cx, h.cy, HANDLE_SIZE / 2 + 1, 0, 2 * Math.PI);
            ctx.fill();
            ctx.stroke();
          } else {
            const hs = HANDLE_SIZE;
            ctx.fillRect(h.cx - hs / 2, h.cy - hs / 2, hs, hs);
            ctx.strokeRect(h.cx - hs / 2, h.cy - hs / 2, hs, hs);
          }
        }
        ctx.restore();
      }
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
    const fontSize = Math.max(1, widget.font_size ?? 22);
    const color = widget.color ?? COLOR_BLACK;
    const align = widget.align ?? "left";
    const width = this._layout.display.width;
    const rightEdge = widget.w != null ? (x + widget.w) : width;

    ctx.font = `${fontSize}px sans-serif`;
    ctx.fillStyle = grayColor(color);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    const tw = ctx.measureText(text).width;
    let drawX = x;
    if (align === "right") {
      drawX = rightEdge - PADDING - tw;
    } else if (align === "center") {
      drawX = x + (rightEdge - x - tw) / 2;
    }

    ctx.fillText(text, drawX, y);
    const bx = Math.min(drawX, x);
    const boundsW = widget.w != null ? widget.w : Math.max(drawX + tw - bx, 20);
    return { x: bx, y, w: boundsW, h: fontSize };
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
    return {
      x: Math.min(x, x2),
      y: Math.min(y, y2) - 4,
      w: Math.max(Math.abs(x2 - x), 8),
      h: Math.max(Math.abs(y2 - y), 8) + 8,
    };
  }

  // mirrors render.py: render_separator (lines 117-126)
  _renderSeparator(ctx, widget) {
    const y = widget.y ?? 0;
    const color = widget.color ?? COLOR_LIGHT_GRAY;
    const x0 = widget.x ?? PADDING;
    const x1 = widget.w != null ? (x0 + widget.w) : (this._layout.display.width - PADDING);

    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.strokeStyle = grayColor(color);
    ctx.lineWidth = 1;
    ctx.stroke();
    return { x: x0, y: y - 4, w: x1 - x0, h: 8 };
  }

  // mirrors render.py: render_weather
  _renderWeather(ctx, widget) {
    const entityId = widget.entity ?? "";
    const stateObj = this._getState(entityId);
    const x = widget.x ?? PADDING;
    const origY = widget.y ?? 0;
    const fontSize = Math.max(1, widget.font_size ?? 22);
    const s = fontSize / 22;
    if (!stateObj) return { x, y: origY, w: 200, h: Math.round(90 * s) };

    let y = origY;
    const forecastDays = widget.forecast_days ?? 3;
    const width = this._layout.display.width;
    const rightEdge = widget.w != null ? (x + widget.w) : width;

    const condition = stateObj.state ?? "";
    const attrs = stateObj.attributes ?? {};
    const temp = attrs.temperature ?? "--";
    const humidity = attrs.humidity ?? "--";
    const wind = attrs.wind_speed ?? "--";

    // Main weather icon (placeholder "?")
    ctx.font = `${Math.round(64 * s)}px sans-serif`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText("?", x + Math.round(45 * s), y + Math.round(45 * s));
    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    // Temperature
    ctx.font = `${Math.round(48 * s)}px sans-serif`;
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(`${temp}°C`, x + Math.round(100 * s), y);

    // Condition label
    const condLabel = condition.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    ctx.font = `${fontSize}px sans-serif`;
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillText(condLabel, x + Math.round(100 * s), y + Math.round(54 * s));

    // Humidity (right-aligned)
    const humText = `${humidity}%`;
    ctx.font = `${fontSize}px sans-serif`;
    ctx.fillStyle = grayColor(COLOR_BLACK);
    const humW = ctx.measureText(humText).width;
    ctx.fillText(humText, rightEdge - PADDING - humW, y + Math.round(8 * s));

    // Wind (right-aligned)
    const windText = `${wind} km/h`;
    const windW = ctx.measureText(windText).width;
    ctx.fillText(windText, rightEdge - PADDING - windW, y + Math.round(38 * s));

    // Forecast
    const forecast = attrs.forecast ?? [];
    if (!forecast.length || forecastDays <= 0) {
      return { x, y: origY, w: rightEdge - x, h: Math.round(90 * s) };
    }

    const colWidth = Math.floor((rightEdge - x - PADDING) / forecastDays);
    const forecastY = y + Math.round(100 * s);

    // Separator line
    ctx.beginPath();
    ctx.moveTo(x, forecastY - Math.round(4 * s));
    ctx.lineTo(rightEdge - PADDING, forecastY - Math.round(4 * s));
    ctx.strokeStyle = grayColor(COLOR_LIGHT_GRAY);
    ctx.lineWidth = 1;
    ctx.stroke();

    for (let i = 0; i < Math.min(forecastDays, forecast.length); i++) {
      const day = forecast[i];
      const cx = x + colWidth * i + Math.floor(colWidth / 2);

      // Day label
      let dayLabel = "";
      if (day.datetime) {
        const [yr, mo, dy] = day.datetime.slice(0, 10).split("-").map(Number);
        const dt = new Date(yr, mo - 1, dy);
        // JS getDay(): 0=Sun … 6=Sat; Python weekday(): 0=Mon … 6=Sun
        dayLabel = DAY_ABBREV[(dt.getDay() + 6) % 7];
      }
      ctx.font = `${Math.round(16 * s)}px sans-serif`;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.textBaseline = "top";
      ctx.textAlign = "center";
      ctx.fillText(dayLabel, cx, forecastY);

      // Forecast icon placeholder
      ctx.font = `${Math.round(28 * s)}px sans-serif`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.textBaseline = "middle";
      ctx.fillText("?", cx, forecastY + Math.round(38 * s));

      // Hi/Lo
      const hi = day.temperature ?? "";
      const lo = day.templow ?? "";
      const hiLo = `${hi}° / ${lo}°`;
      ctx.font = `${Math.round(16 * s)}px sans-serif`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.textBaseline = "top";
      ctx.fillText(hiLo, cx, forecastY + Math.round(60 * s));
    }

    // Reset to defaults
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    return { x, y: origY, w: rightEdge - x, h: Math.round(180 * s) };
  }

  // mirrors render.py: render_sensor_rows
  _renderSensorRows(ctx, widget) {
    const x = widget.x ?? PADDING;
    const origY = widget.y ?? 0;
    let y = origY;
    const fontSize = Math.max(1, widget.font_size ?? 22);
    const s = fontSize / 22;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const width = this._layout.display.width;
    const rightEdge = widget.w != null ? (x + widget.w) : width;
    const rowHeight = Math.round(SENSOR_ROW_HEIGHT * s);

    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.font = `${fontSize}px sans-serif`;

    if (title) {
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += Math.round(SENSOR_TITLE_ADVANCE * s);
    }

    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes ?? {};
      const label = attrs.friendly_name ?? entityId;
      const value = stateObj.state ?? "";
      const unit = attrs.unit_of_measurement ?? "";
      const displayVal = unit ? `${value}${unit}` : value;

      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, x + Math.round(16 * s), y);

      const valW = ctx.measureText(displayVal).width;
      ctx.fillText(displayVal, rightEdge - PADDING - valW, y);

      y += rowHeight;
    }
    return { x, y: origY, w: rightEdge - x, h: Math.max(y - origY, 20) };
  }

  // mirrors render.py: render_battery_bar
  _renderBatteryBar(ctx, widget) {
    const entityId = widget.entity ?? "";
    const stateObj = this._getState(entityId);
    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    if (!stateObj) return { x, y, w: 60, h: 20 };

    const raw = stateObj.state ?? "";
    const pctFloat = parseFloat(raw);
    if (isNaN(pctFloat)) return { x, y, w: 60, h: 20 };
    const pct = Math.max(0, Math.min(100, Math.floor(pctFloat)));
    const fontSize = Math.max(1, widget.font_size ?? 14);
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
    ctx.font = `${fontSize}px sans-serif`;
    const labelW = ctx.measureText(`${pct}%`).width;
    ctx.fillStyle = grayColor(color);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillText(`${pct}%`, x + bw + BATTERY_NUB_W + 4, y - 2);
    return { x, y: y - 2, w: bw + BATTERY_NUB_W + 4 + labelW, h: bh + 2 };
  }

  // mirrors render.py: render_status_icons
  _renderStatusIcons(ctx, widget) {
    const x = widget.x ?? PADDING;
    const origY = widget.y ?? 0;
    let y = origY;
    const fontSize = Math.max(1, widget.font_size ?? 18);
    const s = fontSize / 18;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const width = this._layout.display.width;
    const rightEdge = widget.w != null ? (x + widget.w) : width;
    const sz = Math.round(STATUS_ICON_SIZE * s);
    const rowH = Math.round(STATUS_ROW_HEIGHT * s);

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    if (title) {
      ctx.font = `${Math.round(22 * s)}px sans-serif`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += Math.round(STATUS_TITLE_ADVANCE * s);
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

      ctx.font = `${fontSize}px sans-serif`;
      const textW = ctx.measureText(label).width;
      const itemW = sz + Math.round(6 * s) + textW + Math.round(20 * s);

      if (curX + itemW > rightEdge - PADDING && curX > x) {
        curX = x;
        y += rowH;
      }

      const iconTop = y + Math.round(4 * s);
      if (isProblem) {
        ctx.fillStyle = grayColor(COLOR_BLACK);
        ctx.fillRect(curX, iconTop, sz, sz);
      } else {
        ctx.strokeStyle = grayColor(COLOR_GRAY);
        ctx.lineWidth = 1;
        ctx.strokeRect(curX, iconTop, sz, sz);
      }

      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, curX + sz + Math.round(6 * s), y);

      curX += itemW;
    }
    return { x, y: origY, w: rightEdge - x, h: y - origY + rowH };
  }

  // mirrors render.py: render_waste_schedule
  _renderWasteSchedule(ctx, widget) {
    const x = widget.x ?? PADDING;
    const origY = widget.y ?? 0;
    let y = origY;
    const fontSize = Math.max(1, widget.font_size ?? 18);
    const s = fontSize / 18;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const width = this._layout.display.width;
    const rightEdge = widget.w != null ? (x + widget.w) : width;
    const sz = Math.round(WASTE_ICON_SIZE * s);
    const rowH = Math.round(WASTE_ROW_HEIGHT * s);

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    if (title) {
      ctx.font = `${Math.round(22 * s)}px sans-serif`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += Math.round(WASTE_TITLE_ADVANCE * s);
    }

    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes ?? {};
      const label = attrs.friendly_name ?? entityId;
      const raw = stateObj.state ?? "";

      const days = parseDaysUntil(raw);
      if (days !== null && (days < 0 || days > 3)) continue;

      const cx = x + sz / 2;
      const cy = y + Math.round(6 * s) + sz / 2;
      const r = sz / 2;

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

      ctx.font = `${fontSize}px sans-serif`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, x + sz + Math.round(8 * s), y);

      const dateStr = formatRelativeDate(days, raw);
      const dateW = ctx.measureText(dateStr).width;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillText(dateStr, rightEdge - PADDING - dateW, y);

      y += rowH;
    }
    return { x, y: origY, w: rightEdge - x, h: Math.max(y - origY, 20) };
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

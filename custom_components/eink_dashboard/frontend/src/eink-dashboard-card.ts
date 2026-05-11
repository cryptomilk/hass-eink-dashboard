// E-Ink Dashboard Lovelace card — read-only canvas preview.
// Mirrors the rendering logic from render.py using Canvas 2D.

import type {
  HomeAssistant,
  HassEntity,
  Widget,
  TextWidget,
  LineWidget,
  SeparatorWidget,
  WeatherWidget,
  SensorRowsWidget,
  DeviceBatteryWidget,
  StatusIconsWidget,
  WasteScheduleWidget,
  LayoutResponse,
  WidgetBounds,
  WidgetMetrics,
  CardStyle,
  CardRowOpts,
  IndexedBounds,
  Handle,
  ForecastDay,
  ForecastServiceResult,
  EinkEditorElement,
  ConfigEntry,
} from "./types/ha.js";

const CARD_TAG = "eink-dashboard-card";

// ── Constants (mirror const.py + render.py) ──────────────────────────────────

const PADDING = 24;
const COLOR_BLACK = 0;
const COLOR_WHITE = 255;
const COLOR_GRAY = 120;
const COLOR_LIGHT_GRAY = 180;
const FONT_FAMILY = "Roboto, sans-serif";
const ROBOTO_URL = "/eink_dashboard/fonts/Roboto-Regular.ttf";
const ROBOTO_MEDIUM_URL = "/eink_dashboard/fonts/Roboto-Medium.ttf";

const FONT_SIZE_TEXT = 32;
const FONT_SIZE_WEATHER = 32;
const FONT_SIZE_SENSOR_ROWS = 32;
const FONT_SIZE_DEVICE_BATTERY = 24;
const FONT_SIZE_STATUS_ICONS = 28;
const FONT_SIZE_WASTE_SCHEDULE = 28;

let _robotoLoaded = false;
async function _loadRoboto(): Promise<void> {
  if (_robotoLoaded) return;
  try {
    const face = new FontFace("Roboto", `url(${ROBOTO_URL})`);
    await face.load();
    document.fonts.add(face);
    _robotoLoaded = true;
  } catch (_) { /* fall back to sans-serif */ }
}

let _robotoMediumLoaded = false;
async function _loadRobotoMedium(): Promise<void> {
  if (_robotoMediumLoaded) return;
  try {
    const face = new FontFace("Roboto", `url(${ROBOTO_MEDIUM_URL})`, { weight: "500" });
    await face.load();
    document.fonts.add(face);
    _robotoMediumLoaded = true;
  } catch (_) { /* fall back to sans-serif */ }
}

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

const CONDITION_ICONS: Record<string, string> = {
  "sunny": "☀",
  "clear-night": "☾",
  "cloudy": "☁",
  "partlycloudy": "⛅",
  "fog": "▒",
  "hail": "❄",
  "lightning": "⚡",
  "lightning-rainy": "⛈",
  "pouring": "☂",
  "rainy": "☔",
  "snowy": "❄",
  "snowy-rainy": "☖",
  "windy": "☴",
  "windy-variant": "☴",
  "exceptional": "⚠",
};

const HANDLE_SIZE = 8;
const HANDLE_HIT_RADIUS = 10;
const GRID = 8;

// ── Helpers ───────────────────────────────────────────────────────────────────

export function snap(v: number): number { return Math.round(v / GRID) * GRID; }

export function grayColor(v: number): string {
  return `rgb(${v},${v},${v})`;
}

// Parse a raw state string as days-until-today.
// Tries ISO date first, then integer. Returns null on failure.
export function parseDaysUntil(raw: string): number | null {
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    const [y, m, d] = raw.slice(0, 10).split("-").map(Number);
    const target = new Date(y, m - 1, d);
    if (!isNaN(target.getTime())) {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return Math.round((target.getTime() - today.getTime()) / 86400000);
    }
  }
  const n = parseInt(raw, 10);
  return isNaN(n) ? null : n;
}

export function formatRelativeDate(days: number | null, raw: string): string {
  if (days === null || days < 0) return raw;
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

export function buildHeaderText(
  device: { name: string },
): string {
  return device.name || "E-Ink Dashboard";
}

export function shouldShowCopyUrl(model: string, hasWebhooks: boolean): boolean {
  if (model.startsWith("kindle_")) return true;
  if (model === "custom" && !hasWebhooks) return true;
  // TRMNL devices are push-only (always have webhooks); no URL needed.
  return false;
}

/**
 * Compute proportional widget layout dimensions from a row height.
 *
 * Mirrors `_compute_metrics()` from render.py with the same ratio
 * factors and minimum clamps so that canvas previews match the PIL
 * renderer.
 *
 * @param rowH - Height of a single row in pixels.
 * @returns A WidgetMetrics object with all derived pixel sizes.
 */
export function computeMetrics(rowH: number): WidgetMetrics {
  return {
    border: Math.max(2, Math.round(rowH * 0.04)),
    padding: Math.round(rowH * 0.21),
    radius: Math.round(rowH * 0.21),
    iconDia: Math.round(rowH * 0.64),
    fontPrimary: Math.max(10, Math.round(rowH * 0.32)),
    fontSecondary: Math.max(10, Math.round(rowH * 0.25)),
    divider: Math.max(2, Math.round(rowH * 0.07)),
    innerGap: Math.round(rowH * 0.21),
    leftBar: Math.max(2, Math.round(rowH * 0.07)),
  };
}

/**
 * Draw card container decoration and return the
 * content x-offset.
 *
 * Mirrors _draw_card_container() from render.py.
 * Three decoration styles:
 * - "border": rounded rect outline, returns m.padding
 * - "left_bar": filled gray rect on the left edge,
 *   returns barW + m.padding
 * - "none": no decoration, returns 0
 *
 * @param ctx - Canvas 2D rendering context.
 * @param x - Left edge of the card area in pixels.
 * @param y - Top edge of the card area in pixels.
 * @param w - Total width of the card area in pixels.
 * @param h - Total height of the card area in pixels.
 * @param m - Pre-computed layout metrics.
 * @param cardStyle - Card decoration style.
 * @param grayscaleLevels - Display gray levels; when
 *   <= 2 the left bar is widened so the dithered dot
 *   pattern is clearly visible. Defaults to 16.
 * @returns Horizontal pixel offset from x where
 *   content should start.
 */
export function drawCardContainer(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  m: WidgetMetrics,
  cardStyle: CardStyle,
  grayscaleLevels?: number,
): number {
  if (cardStyle === "border") {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, m.radius);
    ctx.strokeStyle = grayColor(COLOR_BLACK);
    ctx.lineWidth = m.border;
    ctx.stroke();
    return m.padding;
  }
  if (cardStyle === "left_bar") {
    let barW = m.leftBar;
    // On 2-level displays (TRMNL), widen the bar so
    // the dithered dot pattern forms a visible stripe.
    if ((grayscaleLevels ?? 16) <= 2) {
      barW = Math.max(10, m.leftBar * 3);
    }
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillRect(x, y, barW, h);
    return barW + m.padding;
  }
  // "none" — no decoration
  return 0;
}

/**
 * Draw one row inside a card container.
 *
 * Mirrors _draw_card_row() from render.py. Renders a
 * gray filled icon circle with letter fallback on the
 * left, primary text (Roboto Medium) and optional
 * secondary text (gray) vertically centered in the
 * middle, and an optional right-aligned value string.
 *
 * @param ctx - Canvas 2D rendering context.
 * @param x - Left edge of the row area in pixels.
 * @param y - Top edge of the row area in pixels.
 * @param w - Width of the row area in pixels.
 * @param rowH - Height of the row in pixels.
 * @param m - Pre-computed layout metrics.
 * @param opts - Row content: primary label, optional
 *   secondary sub-label, optional right-aligned value,
 *   and optional icon circle fill color (default gray).
 */
export function drawCardRow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  rowH: number,
  m: WidgetMetrics,
  opts: CardRowOpts,
): void {
  const { primary, secondary, value } = opts;
  const iconFill = opts.iconFill ?? COLOR_GRAY;

  // Icon circle — vertically centered in the row
  const iconX = x + m.padding;
  const circleY = y + Math.floor((rowH - m.iconDia) / 2);
  const cx = iconX + m.iconDia / 2;
  const cy = circleY + m.iconDia / 2;
  ctx.beginPath();
  ctx.arc(cx, cy, m.iconDia / 2, 0, 2 * Math.PI);
  ctx.fillStyle = grayColor(iconFill);
  ctx.fill();

  // Letter fallback: first char of primary, white on
  // the gray circle, centered inside it. Skipped when
  // opts.icon is provided (loading not yet implemented).
  if (!opts.icon) {
    const letter = primary[0]?.toUpperCase() ?? "?";
    const letterSz = Math.round(m.iconDia * 0.5);
    ctx.font = `${letterSz}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    const lm = ctx.measureText(letter);
    const lw = lm.width;
    const lh = lm.actualBoundingBoxAscent
      + lm.actualBoundingBoxDescent;
    ctx.fillStyle = grayColor(COLOR_WHITE);
    ctx.fillText(
      letter,
      iconX + Math.floor((m.iconDia - lw) / 2),
      circleY + Math.floor((m.iconDia - lh) / 2),
    );
  }

  // Text block starts right of the icon + gap
  const textX = iconX + m.iconDia + m.innerGap;

  ctx.textBaseline = "top";
  if (secondary) {
    // Primary + secondary: compute combined block
    // height, then vertically center the block.
    ctx.font = `500 ${m.fontPrimary}px ${FONT_FAMILY}`;
    const pm = ctx.measureText(primary);
    const pH = pm.actualBoundingBoxAscent
      + pm.actualBoundingBoxDescent;

    ctx.font = `${m.fontSecondary}px ${FONT_FAMILY}`;
    const sm = ctx.measureText(secondary);
    const sH = sm.actualBoundingBoxAscent
      + sm.actualBoundingBoxDescent;

    // Small gap between the two text lines, matching
    // the Python line_gap formula.
    const lineGap = Math.max(2, Math.round(rowH * 0.04));
    const blockH = pH + lineGap + sH;
    const textY = y + Math.floor((rowH - blockH) / 2);

    ctx.font = `500 ${m.fontPrimary}px ${FONT_FAMILY}`;
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(primary, textX, textY);

    ctx.font = `${m.fontSecondary}px ${FONT_FAMILY}`;
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillText(secondary, textX, textY + pH + lineGap);
  } else {
    // Primary only — vertically center it alone.
    ctx.font = `500 ${m.fontPrimary}px ${FONT_FAMILY}`;
    const pm = ctx.measureText(primary);
    const pH = pm.actualBoundingBoxAscent
      + pm.actualBoundingBoxDescent;
    const textY = y + Math.floor((rowH - pH) / 2);
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(primary, textX, textY);
  }

  // Right-aligned value, vertically centered
  if (value) {
    ctx.font = `${m.fontSecondary}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    const vm = ctx.measureText(value);
    const vw = vm.width;
    const vh = vm.actualBoundingBoxAscent
      + vm.actualBoundingBoxDescent;
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillText(
      value,
      x + w - m.padding - vw,
      y + Math.floor((rowH - vh) / 2),
    );
  }
}

// ── Card class ────────────────────────────────────────────────────────────────

interface CardConfig {
  config_entry?: string;
}

interface DragStart {
  x: number;
  y: number;
  x2?: number;
  y2?: number;
}

interface ResizeStart {
  x: number;
  y: number;
  x2: number;
  y2: number;
  w?: number;
  font_size?: number;
  renderedW?: number;
  renderedH?: number;
}

type MutableWidget = Widget & { x2?: number; y2?: number };

class EinkDashboardCard extends HTMLElement {
  private _config: CardConfig | null = null;
  private _hass: HomeAssistant | null = null;
  private _layout: LayoutResponse | null = null;
  private _canvas: HTMLCanvasElement | null = null;
  private _ctx: CanvasRenderingContext2D | null = null;
  private _renderPending = false;
  private _connected = false;
  private _fetching = false;
  private _fetchGeneration = 0;
  private _showServerImage = false;
  private _serverImg: HTMLImageElement | null = null;
  private _container!: HTMLElement;
  private _toggleBtn!: HTMLButtonElement;
  private _editMode = false;
  private _editor: EinkEditorElement | null = null;
  private _editorContainer!: HTMLElement;
  private _editBtn!: HTMLButtonElement;
  private _saving = false;
  private _saveError!: HTMLElement;
  private _widgetBounds: IndexedBounds[] = [];
  private _dragIndex = -1;
  private _dragStartCX = 0;
  private _dragStartCY = 0;
  private _dragWidgetStart: DragStart | null = null;
  private _hoverIndex = -1;
  private _resizeIndex = -1;
  private _resizeHandle: string | null = null;
  private _resizeStartCX = 0;
  private _resizeStartCY = 0;
  private _resizeWidgetStart: ResizeStart | null = null;
  private _forecasts: Record<string, ForecastDay[]> = {};
  private _resolvedEntryId: string | undefined;
  private _headerEl!: HTMLElement;
  private _copyBtn!: HTMLButtonElement;
  private _copyTimeout: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  // ── Lovelace lifecycle ────────────────────────────────────────────────────

  setConfig(config: CardConfig): void {
    const entryChanged = this._config && this._config.config_entry !== config.config_entry;
    this._config = config;
    this._buildShadowDom();
    if (entryChanged) {
      this._layout = null;
      this._canvas = null;
      this._ctx = null;
      this._serverImg = null;
      this._fetching = false;
      this._fetchGeneration++;
      this._showServerImage = false;
      this._editMode = false;
      this._editor = null;
      if (this._copyTimeout) { clearTimeout(this._copyTimeout); this._copyTimeout = null; }
    }
  }

  set hass(hass: HomeAssistant) {
    this._hass = hass;
    if (this._editor) {
      this._editor.hass = hass;
    }
    if (this._config && !this._layout && !this._fetching) {
      this._fetchLayout();
    }
    if (this._layout) {
      this._scheduleRender();
      const newHeader = buildHeaderText(this._layout.device);
      if (this._headerEl.textContent !== newHeader) {
        this._headerEl.textContent = newHeader;
      }
    }
  }

  connectedCallback(): void {
    this._connected = true;
    if (this._layout) {
      this._scheduleRender();
    } else if (this._hass && this._config) {
      this._fetchLayout();
    }
  }

  disconnectedCallback(): void {
    this._connected = false;
    this._fetchGeneration++;
    this._fetching = false;
  }

  getCardSize(): number {
    if (this._layout) {
      return Math.ceil(this._layout.display.height / 50);
    }
    return 8;
  }

  // ── Shadow DOM ────────────────────────────────────────────────────────────

  private _buildShadowDom(): void {
    this.shadowRoot!.innerHTML = `
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
        .card-header {
          padding: 12px 16px 4px;
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
          line-height: 1.2;
        }
        .copy-btn {
          font-size: 12px;
          padding: 4px 8px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 4px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
        }
        .copy-btn.copied {
          background: var(--success-color, #4caf50);
          color: #fff;
          border-color: var(--success-color, #4caf50);
        }
      </style>
      <ha-card>
        <div class="card-header"></div>
        <div class="container">
          <div class="loading">Loading layout…</div>
        </div>
        <div class="toolbar">
          <button class="copy-btn" style="display:none" title="Copy image URL to clipboard">
            Copy image URL
          </button>
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
    this._container = this.shadowRoot!.querySelector<HTMLElement>(".container")!;
    this._toggleBtn = this.shadowRoot!.querySelector<HTMLButtonElement>(".toggle-btn")!;
    this._toggleBtn.addEventListener("click", () => this._onToggle());
    this._editBtn = this.shadowRoot!.querySelector<HTMLButtonElement>(".edit-btn")!;
    this._editBtn.addEventListener("click", () => this._onToggleEdit());
    this._editorContainer = this.shadowRoot!.querySelector<HTMLElement>(".editor-container")!;
    this._saveError = this.shadowRoot!.querySelector<HTMLElement>(".save-error")!;
    this._headerEl = this.shadowRoot!.querySelector<HTMLElement>(".card-header")!;
    this._copyBtn = this.shadowRoot!.querySelector<HTMLButtonElement>(".copy-btn")!;
    this._copyBtn.addEventListener("click", () => this._onCopyUrl());
  }

  // ── Edit mode ─────────────────────────────────────────────────────────────

  private async _ensureEditorLoaded(): Promise<void> {
    if (customElements.get("eink-dashboard-editor")) return;
    const script = document.createElement("script");
    script.type = "module";
    script.src = "/eink_dashboard/frontend/eink-dashboard-editor.js";
    document.head.appendChild(script);
    await customElements.whenDefined("eink-dashboard-editor");
  }

  private async _onToggleEdit(): Promise<void> {
    if (!this._layout) return;
    this._editMode = !this._editMode;
    if (this._editMode) {
      await this._ensureEditorLoaded();
      this._editBtn.textContent = "Close Editor";
      this._editBtn.classList.add("active");
      this._editorContainer.style.display = "block";
      if (!this._editor) {
        this._editor = document.createElement("eink-dashboard-editor") as unknown as EinkEditorElement;
        this._editor.addEventListener(
          "widget-change", (ev) => this._onWidgetChange(ev as CustomEvent<{ widgets: Widget[] }>)
        );
        this._editor.addEventListener(
          "save", (ev) => this._onSave(ev as CustomEvent<{ widgets: Widget[] }>)
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

  private _onWidgetChange(ev: CustomEvent<{ widgets: Widget[] }>): void {
    this._layout!.widgets = ev.detail.widgets;
    this._scheduleRender();
  }

  private async _onSave(ev: CustomEvent<{ widgets: Widget[] }>): Promise<void> {
    if (this._saving) return;
    this._saving = true;
    try {
      const entryId = this._resolvedEntryId;
      await this._hass!.callApi(
        "POST",
        `eink_dashboard/${entryId}/layout`,
        ev.detail.widgets,
      );
      await this._fetchLayout();
      if (this._editor && this._layout) {
        this._editor.setWidgets(this._layout.widgets);
        this._editor.setDisplay(this._layout.display);
      }
      this._saveError.style.display = "none";
    } catch (err) {
      console.error("Failed to save layout:", err);
      this._saveError.textContent = `Save failed: ${(err as Error).message || err}`;
      this._saveError.style.display = "block";
    } finally {
      this._saving = false;
    }
  }

  // ── Config entry resolution ────────────────────────────────────────────────

  private async _resolveEntryId(): Promise<string> {
    const configured = this._config!.config_entry;
    if (configured && !configured.includes(".")) {
      return configured;
    }
    const entries = await this._hass!.callWS<ConfigEntry[]>({
      type: "config_entries/get",
      domain: "eink_dashboard",
    });
    if (!entries || entries.length === 0) {
      throw new Error("No eink_dashboard config entries found");
    }
    if (configured) {
      const match = entries.find((e) => e.entry_id === configured);
      if (match) return match.entry_id;
    }
    return entries[0].entry_id;
  }

  // ── Layout fetch ──────────────────────────────────────────────────────────

  private async _fetchLayout(): Promise<void> {
    const gen = ++this._fetchGeneration;
    this._fetching = true;
    try {
      await _loadRoboto();
      await _loadRobotoMedium();
      if (gen !== this._fetchGeneration) return;

      const entryId = await this._resolveEntryId();
      if (gen !== this._fetchGeneration) return;
      this._resolvedEntryId = entryId;

      const resp = await this._hass!.callApi<LayoutResponse>(
        "GET",
        `eink_dashboard/${entryId}/layout`,
      );
      if (gen !== this._fetchGeneration) return;
      this._layout = resp;
      this._headerEl.textContent = buildHeaderText(resp.device);
      this._copyBtn.style.display = shouldShowCopyUrl(
        resp.device.model,
        resp.device.has_webhooks,
      ) ? "" : "none";
      this._initCanvas();
      this._fetchForecasts();
      this._scheduleRender();
    } catch (err) {
      if (gen !== this._fetchGeneration) return;
      const div = document.createElement("div");
      div.className = "error";
      div.textContent = `Failed to load layout: ${(err as Error).message}`;
      this._container.replaceChildren(div);
    } finally {
      if (gen === this._fetchGeneration) {
        this._fetching = false;
      }
    }
  }

  private async _fetchForecasts(): Promise<void> {
    if (!this._layout || !this._hass) return;
    const gen = this._fetchGeneration;
    for (const w of this._layout.widgets) {
      if (w.type !== "weather" || !w.entity) continue;
      if (gen !== this._fetchGeneration) return;
      try {
        const resp = await this._hass.callService<ForecastServiceResult>(
          "weather", "get_forecasts",
          { entity_id: w.entity, type: "daily" },
          undefined, false, true,
        );
        if (gen !== this._fetchGeneration) return;
        const forecast = resp?.response?.[w.entity]?.forecast;
        if (forecast) {
          this._forecasts[w.entity] = forecast;
          this._scheduleRender();
        }
      } catch (_) { /* forecast unavailable */ }
    }
  }

  private _initCanvas(): void {
    const { width, height } = this._layout!.display;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    canvas.style.touchAction = "none";
    this._canvas = canvas;
    this._ctx = canvas.getContext("2d");

    canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    canvas.addEventListener("pointerup", (e) => this._onPointerUp(e));
    canvas.addEventListener("pointercancel", () => this._onPointerCancel());
    canvas.addEventListener("pointerleave", () => this._onPointerLeave());

    const img = document.createElement("img");
    img.className = "server-render";
    img.style.display = "none";
    this._serverImg = img;

    this._container.innerHTML = "";
    this._container.appendChild(canvas);
    this._container.appendChild(img);
  }

  // ── Drag-to-reposition ────────────────────────────────────────────────────

  private _canvasCoords(event: PointerEvent): { x: number; y: number } {
    const rect = this._canvas!.getBoundingClientRect();
    const scaleX = this._canvas!.width / rect.width;
    const scaleY = this._canvas!.height / rect.height;
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  private _hitTest(cx: number, cy: number): number {
    for (let i = this._widgetBounds.length - 1; i >= 0; i--) {
      const b = this._widgetBounds[i];
      if (cx >= b.x && cx <= b.x + b.w && cy >= b.y && cy <= b.y + b.h) {
        return b.index;
      }
    }
    return -1;
  }

  private _getHandles(bounds: WidgetBounds, widget: Widget): Handle[] {
    if (widget.type === "line") {
      return [
        { id: "p1", cx: widget.x ?? 0, cy: widget.y ?? 0 },
        { id: "p2", cx: widget.x2 ?? 0, cy: widget.y2 ?? 0 },
      ];
    }
    if (widget.type === "device_battery") {
      return [
        { id: "se", cx: bounds.x + bounds.w, cy: bounds.y + bounds.h },
      ];
    }
    return [
      { id: "nw", cx: bounds.x, cy: bounds.y },
      { id: "ne", cx: bounds.x + bounds.w, cy: bounds.y },
      { id: "sw", cx: bounds.x, cy: bounds.y + bounds.h },
      { id: "se", cx: bounds.x + bounds.w, cy: bounds.y + bounds.h },
    ];
  }

  private _handleHitTest(cx: number, cy: number): { index: number; handleId: string } | null {
    for (let i = this._widgetBounds.length - 1; i >= 0; i--) {
      const b = this._widgetBounds[i];
      const widget = this._layout!.widgets[b.index];
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

  private _getResizeCursor(handleId: string, widget?: Widget): string {
    if (handleId === "p1" || handleId === "p2") return "crosshair";
    if (widget?.type === "device_battery") return "nwse-resize";
    return "ew-resize";
  }

  private _onPointerDown(event: PointerEvent): void {
    if (!this._editMode || this._showServerImage || !this._layout) return;
    const { x: cx, y: cy } = this._canvasCoords(event);

    const handleHit = this._handleHitTest(cx, cy);
    if (handleHit) {
      event.preventDefault();
      this._canvas!.setPointerCapture(event.pointerId);
      const w = this._layout.widgets[handleHit.index] as MutableWidget;
      this._resizeIndex = handleHit.index;
      this._resizeHandle = handleHit.handleId;
      this._resizeStartCX = cx;
      this._resizeStartCY = cy;
      const wb = this._widgetBounds.find(b => b.index === handleHit.index);
      this._resizeWidgetStart = {
        x: w.x ?? 0, y: w.y ?? 0,
        x2: w.x2 ?? 0, y2: w.y2 ?? 0,
        w: w.w,
        font_size: w.font_size,
        renderedW: wb?.w,
        renderedH: wb?.h,
      };
      this._canvas!.style.cursor = this._getResizeCursor(handleHit.handleId, w);
      return;
    }

    const idx = this._hitTest(cx, cy);
    if (idx < 0) return;
    event.preventDefault();
    this._canvas!.setPointerCapture(event.pointerId);
    const w = this._layout.widgets[idx] as MutableWidget;
    this._dragIndex = idx;
    this._dragStartCX = cx;
    this._dragStartCY = cy;
    this._dragWidgetStart = {
      x: w.x ?? 0,
      y: w.y ?? 0,
      x2: w.x2,
      y2: w.y2,
    };
    this._canvas!.style.cursor = "grabbing";
  }

  private _onPointerMove(event: PointerEvent): void {
    if (!this._editMode || this._showServerImage || !this._layout) return;
    const { x: cx, y: cy } = this._canvasCoords(event);

    if (this._resizeIndex >= 0) {
      event.preventDefault();
      const dx = Math.round(cx - this._resizeStartCX);
      const dy = Math.round(cy - this._resizeStartCY);
      const w = this._layout.widgets[this._resizeIndex] as MutableWidget;
      const s = this._resizeWidgetStart!;
      const { width: dw, height: dh } = this._layout.display;
      const handle = this._resizeHandle;

      if (handle === "p1") {
        w.x = snap(Math.max(0, Math.min(dw - 1, s.x + dx)));
        w.y = snap(Math.max(0, Math.min(dh - 1, s.y + dy)));
      } else if (handle === "p2") {
        w.x2 = snap(Math.max(0, Math.min(dw - 1, s.x2 + dx)));
        w.y2 = snap(Math.max(0, Math.min(dh - 1, s.y2 + dy)));
      } else if (w.type === "device_battery" && s.renderedW != null && s.renderedH != null) {
        const startFs = s.font_size ?? FONT_SIZE_DEVICE_BATTERY;
        const sdx = (handle === "ne" || handle === "se") ? dx : -dx;
        const sdy = (handle === "nw" || handle === "ne") ? -dy : dy;
        const startDiag = Math.sqrt(s.renderedW ** 2 + s.renderedH ** 2);
        const newDiag = Math.sqrt(
          (s.renderedW + sdx) ** 2 + (s.renderedH + sdy) ** 2
        );
        w.font_size = Math.max(8, Math.min(72,
          Math.round(startFs * newDiag / startDiag)));
      } else if (handle === "ne" || handle === "se") {
        const startRight = s.x + (s.w ?? (dw - PADDING - s.x));
        const newRight = Math.max(s.x + 20, Math.min(dw, startRight + dx));
        w.w = snap(Math.round(newRight - s.x));
      } else if (handle === "nw" || handle === "sw") {
        const startRight = s.x + (s.w ?? (dw - PADDING - s.x));
        const newX = Math.max(0, Math.min(startRight - 20, s.x + dx));
        w.x = snap(Math.round(newX));
        w.w = snap(Math.round(startRight - (w.x ?? 0)));
      }
      this._scheduleRender();
      return;
    }

    if (this._dragIndex >= 0) {
      event.preventDefault();
      const dx = Math.round(cx - this._dragStartCX);
      const dy = Math.round(cy - this._dragStartCY);
      const w = this._layout.widgets[this._dragIndex] as MutableWidget;
      const s = this._dragWidgetStart!;
      const { width, height } = this._layout.display;
      w.x = snap(Math.max(0, Math.min(width - 1, s.x + dx)));
      w.y = snap(Math.max(0, Math.min(height - 1, s.y + dy)));
      if (s.x2 !== undefined) {
        w.x2 = snap(Math.max(0, Math.min(width - 1, s.x2 + dx)));
        w.y2 = snap(Math.max(0, Math.min(height - 1, (s.y2 ?? 0) + dy)));
      }
      this._scheduleRender();
    } else {
      const handleHit = this._handleHitTest(cx, cy);
      if (handleHit) {
        if (this._hoverIndex !== handleHit.index) {
          this._hoverIndex = handleHit.index;
          this._scheduleRender();
        }
        this._canvas!.style.cursor = this._getResizeCursor(
          handleHit.handleId,
          this._layout!.widgets[handleHit.index]
        );
        return;
      }
      const hoverIdx = this._hitTest(cx, cy);
      if (hoverIdx !== this._hoverIndex) {
        this._hoverIndex = hoverIdx;
        this._canvas!.style.cursor = hoverIdx >= 0 ? "grab" : "";
        this._scheduleRender();
      }
    }
  }

  private _onPointerUp(event: PointerEvent): void {
    if (this._resizeIndex >= 0) {
      this._canvas!.releasePointerCapture(event.pointerId);
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._hoverIndex = -1;
      this._canvas!.style.cursor = "";
      this._scheduleRender();
      if (this._editor) {
        this._editor.setWidgets(this._layout!.widgets);
      }
      return;
    }
    if (this._dragIndex < 0) return;
    this._canvas!.releasePointerCapture(event.pointerId);
    this._dragIndex = -1;
    this._dragWidgetStart = null;
    this._hoverIndex = -1;
    this._canvas!.style.cursor = "";
    this._scheduleRender();
    if (this._editor) {
      this._editor.setWidgets(this._layout!.widgets);
    }
  }

  private _onPointerCancel(): void {
    if (this._resizeIndex >= 0) {
      const w = this._layout!.widgets[this._resizeIndex] as MutableWidget;
      const s = this._resizeWidgetStart!;
      w.x = s.x;
      w.y = s.y;
      w.w = s.w;
      w.x2 = s.x2;
      w.y2 = s.y2;
      w.font_size = s.font_size;
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._hoverIndex = -1;
      this._canvas!.style.cursor = "";
      this._scheduleRender();
      return;
    }
    if (this._dragIndex < 0) return;
    const wd = this._layout!.widgets[this._dragIndex] as MutableWidget;
    const sd = this._dragWidgetStart!;
    wd.x = sd.x;
    wd.y = sd.y;
    if (sd.x2 !== undefined) {
      wd.x2 = sd.x2;
      wd.y2 = sd.y2;
    }
    this._dragIndex = -1;
    this._dragWidgetStart = null;
    this._hoverIndex = -1;
    this._canvas!.style.cursor = "";
    this._scheduleRender();
  }

  private _onPointerLeave(): void {
    if (this._dragIndex >= 0 || this._resizeIndex >= 0) return;
    if (this._hoverIndex >= 0) {
      this._hoverIndex = -1;
      this._canvas!.style.cursor = "";
      this._scheduleRender();
    }
  }

  // ── Render scheduling ─────────────────────────────────────────────────────

  private _scheduleRender(): void {
    if (!this._connected || !this._layout || this._showServerImage) return;
    if (this._renderPending) return;
    this._renderPending = true;
    requestAnimationFrame(() => {
      this._renderPending = false;
      this._render();
    });
  }

  private _render(): void {
    if (!this._ctx || !this._layout || !this._hass) return;
    const ctx = this._ctx;
    const { width, height } = this._layout.display;

    ctx.fillStyle = grayColor(COLOR_WHITE);
    ctx.fillRect(0, 0, width, height);

    if (this._editMode) {
      ctx.save();
      ctx.strokeStyle = "rgba(0,0,0,0.06)";
      ctx.setLineDash([1, 3]);
      for (let gx = GRID; gx < width; gx += GRID) {
        ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, height); ctx.stroke();
      }
      for (let gy = GRID; gy < height; gy += GRID) {
        ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.restore();
    }

    const dispatch: Partial<Record<string, (w: Widget) => WidgetBounds>> = {
      text: (w) => this._renderText(ctx, w as TextWidget),
      line: (w) => this._renderLine(ctx, w as LineWidget),
      separator: (w) => this._renderSeparator(ctx, w as SeparatorWidget),
      weather: (w) => this._renderWeather(ctx, w as WeatherWidget),
      sensor_rows: (w) => this._renderSensorRows(ctx, w as SensorRowsWidget),
      device_battery: (w) => this._renderDeviceBattery(ctx, w as DeviceBatteryWidget),
      status_icons: (w) => this._renderStatusIcons(ctx, w as StatusIconsWidget),
      waste_schedule: (w) => this._renderWasteSchedule(ctx, w as WasteScheduleWidget),
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

  private async _onToggle(): Promise<void> {
    if (!this._canvas) return;
    this._showServerImage = !this._showServerImage;
    if (this._showServerImage) {
      const entryId = this._resolvedEntryId;
      if (this._layout?.widgets) {
        this._toggleBtn.disabled = true;
        try {
          await this._hass!.callApi(
            "POST",
            `eink_dashboard/${entryId}/layout`,
            this._layout.widgets,
          );
        } catch (err) {
          console.error("Failed to save before render:", err);
          this._showServerImage = false;
          this._toggleBtn.disabled = false;
          return;
        }
        this._toggleBtn.disabled = false;
      }
      this._serverImg!.src = `/api/eink_dashboard/${entryId}/image.png?_t=${Date.now()}`;
      this._canvas.style.display = "none";
      this._serverImg!.style.display = "block";
      this._toggleBtn.textContent = "Show canvas preview";
      this._toggleBtn.classList.add("active");
    } else {
      this._serverImg!.style.display = "none";
      this._canvas.style.display = "block";
      this._toggleBtn.textContent = "Show rendered image";
      this._toggleBtn.classList.remove("active");
      this._scheduleRender();
    }
  }

  // ── Copy URL ──────────────────────────────────────────────────────────────

  private _onCopyUrl(): void {
    if (!this._resolvedEntryId) return;
    const url = `${window.location.origin}/api/eink_dashboard/${this._resolvedEntryId}/image.png`;
    navigator.clipboard.writeText(url).then(() => {
      this._copyBtn.textContent = "Copied!";
      this._copyBtn.classList.add("copied");
      if (this._copyTimeout) clearTimeout(this._copyTimeout);
      this._copyTimeout = setTimeout(() => {
        this._copyBtn.textContent = "Copy image URL";
        this._copyBtn.classList.remove("copied");
        this._copyTimeout = null;
      }, 2000);
    }).catch(() => {
      this._copyBtn.textContent = "Copy failed";
      if (this._copyTimeout) clearTimeout(this._copyTimeout);
      this._copyTimeout = setTimeout(() => {
        this._copyBtn.textContent = "Copy image URL";
        this._copyTimeout = null;
      }, 2000);
    });
  }

  // ── State helper ──────────────────────────────────────────────────────────

  private _getState(entityId: string): HassEntity | null {
    const s = this._hass!.states[entityId];
    return s || null;
  }

  // ── Widget helpers ────────────────────────────────────────────────────────

  /** Extract base coordinates shared by most widget renderers. */
  private _getWidgetBase(widget: Widget, defaultFontSize: number): {
    x: number; y: number; fontSize: number; width: number; rightEdge: number;
  } {
    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    const fontSize = Math.max(1, widget.font_size ?? defaultFontSize);
    const width = this._layout!.display.width;
    const rightEdge = widget.w != null ? (x + widget.w) : width;
    return { x, y, fontSize, width, rightEdge };
  }

  // ── Widget renderers ──────────────────────────────────────────────────────

  // mirrors render.py: render_text (lines 77-100)
  private _renderText(ctx: CanvasRenderingContext2D, widget: TextWidget): WidgetBounds {
    const { x, y, fontSize, rightEdge } = this._getWidgetBase(widget, FONT_SIZE_TEXT);
    const text = String(widget.text ?? "");
    const color = widget.color ?? COLOR_BLACK;
    const align = widget.align ?? "left";

    ctx.font = `${fontSize}px ${FONT_FAMILY}`;
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
  private _renderLine(ctx: CanvasRenderingContext2D, widget: LineWidget): WidgetBounds {
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
  private _renderSeparator(ctx: CanvasRenderingContext2D, widget: SeparatorWidget): WidgetBounds {
    const y = widget.y ?? 0;
    const color = widget.color ?? COLOR_LIGHT_GRAY;
    const x0 = widget.x ?? PADDING;
    const x1 = widget.w != null ? (x0 + widget.w) : (this._layout!.display.width - PADDING);

    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.strokeStyle = grayColor(color);
    ctx.lineWidth = 1;
    ctx.stroke();
    return { x: x0, y: y - 4, w: x1 - x0, h: 8 };
  }

  // mirrors render.py: render_weather
  private _renderWeather(ctx: CanvasRenderingContext2D, widget: WeatherWidget): WidgetBounds {
    const entityId = widget.entity ?? "";
    const stateObj = this._getState(entityId);
    const { x, y: origY, fontSize, rightEdge } = this._getWidgetBase(widget, FONT_SIZE_WEATHER);
    const s = fontSize / FONT_SIZE_WEATHER;
    if (!stateObj) return { x, y: origY, w: 200, h: Math.round(90 * s) };

    let y = origY;
    const forecastDays = widget.forecast_days ?? 5;

    const condition = stateObj.state ?? "";
    const attrs = stateObj.attributes as Record<string, string | number | null>;
    const temp = attrs.temperature ?? "--";
    const tempUnit = attrs.temperature_unit ?? "°C";
    const humidity = attrs.humidity;
    const wind = attrs.wind_speed;
    const windUnit = attrs.wind_speed_unit ?? "km/h";
    const pressure = attrs.pressure;
    const pressureUnit = attrs.pressure_unit ?? "hPa";
    const cloudCoverage = attrs.cloud_coverage;

    // Row 1: condition icon + temperature
    const iconSize = Math.round(64 * s);
    const icon = CONDITION_ICONS[condition] || "?";
    ctx.font = `${iconSize}px ${FONT_FAMILY}`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(icon, x + iconSize / 2, y + iconSize / 2);

    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.font = `${Math.round(48 * s)}px ${FONT_FAMILY}`;
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(`${temp}${tempUnit}`, x + iconSize + Math.round(12 * s), y + iconSize / 2);

    // Row 2: detail chips
    const detailY = y + iconSize + Math.round(8 * s);
    const chipGap = Math.round(20 * s);
    ctx.font = `${Math.round(16 * s)}px ${FONT_FAMILY}`;
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    const DETAIL_ICONS = { humidity: "\u{1F4A7}", barometer: "◉", wind: "\u{1F32C}︎", cloud: "☁" };
    const chips: Array<{ sym: string; text: string }> = [];
    if (humidity != null) chips.push({ sym: DETAIL_ICONS.humidity, text: `${humidity}%` });
    if (pressure != null) chips.push({ sym: DETAIL_ICONS.barometer, text: `${pressure}${pressureUnit}` });
    if (wind != null) chips.push({ sym: DETAIL_ICONS.wind, text: `${wind}${windUnit}` });
    if (cloudCoverage != null) chips.push({ sym: DETAIL_ICONS.cloud, text: `${cloudCoverage}%` });

    let chipX = x;
    for (const chip of chips) {
      ctx.fillText(chip.sym, chipX, detailY);
      const symW = ctx.measureText(chip.sym).width;
      ctx.fillText(chip.text, chipX + symW + 4, detailY);
      chipX += symW + 4 + ctx.measureText(chip.text).width + chipGap;
    }

    // Forecast
    const forecast = this._forecasts[entityId] || (attrs.forecast as ForecastDay[] | null) || [];
    if (!forecast.length || forecastDays <= 0) {
      return { x, y: origY, w: rightEdge - x, h: detailY + Math.round(20 * s) - origY };
    }

    // Separator
    const separatorY = detailY + Math.round(22 * s);
    ctx.beginPath();
    ctx.moveTo(x, separatorY);
    ctx.lineTo(rightEdge - PADDING, separatorY);
    ctx.strokeStyle = grayColor(COLOR_LIGHT_GRAY);
    ctx.lineWidth = 1;
    ctx.stroke();

    const forecastY = separatorY + Math.round(6 * s);
    const colWidth = Math.floor((rightEdge - x - PADDING) / forecastDays);
    const precipUnit = String(attrs.precipitation_unit ?? "mm");

    for (let i = 0; i < Math.min(forecastDays, forecast.length); i++) {
      const day = forecast[i];
      const cx = x + colWidth * i + Math.floor(colWidth / 2);

      // Day label
      let dayLabel = "";
      if (day.datetime) {
        const [yr, mo, dy] = day.datetime.slice(0, 10).split("-").map(Number);
        const dt = new Date(yr, mo - 1, dy);
        dayLabel = DAY_ABBREV[(dt.getDay() + 6) % 7];
      }
      ctx.font = `${Math.round(16 * s)}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.textBaseline = "top";
      ctx.textAlign = "center";
      ctx.fillText(dayLabel, cx, forecastY);

      // Condition icon
      const dayIcon = CONDITION_ICONS[day.condition ?? ""] || "?";
      ctx.font = `${Math.round(28 * s)}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.textBaseline = "middle";
      ctx.fillText(dayIcon, cx, forecastY + Math.round(34 * s));

      // High temp
      const hi = day.temperature ?? "";
      ctx.font = `${Math.round(16 * s)}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.textBaseline = "top";
      ctx.fillText(hi !== "" ? `${hi}°` : "", cx, forecastY + Math.round(52 * s));

      // Low temp
      const lo = day.templow ?? "";
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillText(lo !== "" ? `${lo}°` : "", cx, forecastY + Math.round(70 * s));

      // Precipitation
      const precip = day.precipitation;
      if (precip != null && precip > 0) {
        ctx.font = `${Math.round(14 * s)}px ${FONT_FAMILY}`;
        ctx.fillStyle = grayColor(COLOR_GRAY);
        ctx.fillText(`${precip}${precipUnit}`, cx, forecastY + Math.round(88 * s));
      }
    }

    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    return { x, y: origY, w: rightEdge - x, h: Math.round(200 * s) };
  }

  // mirrors render.py: render_sensor_rows
  private _renderSensorRows(ctx: CanvasRenderingContext2D, widget: SensorRowsWidget): WidgetBounds {
    const { x, y: origY, fontSize, rightEdge } = this._getWidgetBase(widget, FONT_SIZE_SENSOR_ROWS);
    let y = origY;
    const sc = fontSize / FONT_SIZE_SENSOR_ROWS;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const rowHeight = Math.round(SENSOR_ROW_HEIGHT * sc);

    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.font = `${fontSize}px ${FONT_FAMILY}`;

    if (title) {
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += Math.round(SENSOR_TITLE_ADVANCE * sc);
    }

    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes as Record<string, string | null>;
      const label = String(attrs.friendly_name ?? entityId);
      const value = stateObj.state ?? "";
      const unit = String(attrs.unit_of_measurement ?? "");
      const displayVal = unit ? `${value}${unit}` : value;

      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, x + Math.round(16 * sc), y);

      const valW = ctx.measureText(displayVal).width;
      ctx.fillText(displayVal, rightEdge - PADDING - valW, y);

      y += rowHeight;
    }
    return { x, y: origY, w: rightEdge - x, h: Math.max(y - origY, 20) };
  }

  // mirrors render.py: render_device_battery
  private _renderDeviceBattery(ctx: CanvasRenderingContext2D, widget: DeviceBatteryWidget): WidgetBounds {
    const { x, y, fontSize } = this._getWidgetBase(widget, FONT_SIZE_DEVICE_BATTERY);
    const color = widget.color ?? COLOR_BLACK;

    const rawLevel = this._layout?.device?.device_battery_level;
    const pct = rawLevel != null ? Math.max(0, Math.min(100, Math.floor(rawLevel))) : null;
    const label = pct != null ? `${pct}%` : "---%";

    const s = fontSize / FONT_SIZE_DEVICE_BATTERY;
    const bw = Math.round(BATTERY_BODY_W * s);
    const bh = Math.round(BATTERY_BODY_H * s);
    const nubW = Math.round(BATTERY_NUB_W * s);
    const nubH = Math.round(BATTERY_NUB_H * s);
    const nubGap = Math.max(1, Math.round(s));
    const gap = Math.round(4 * s);

    // Measure label to center icon against text
    ctx.font = `${fontSize}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const metrics = ctx.measureText(label);
    const textH = metrics.actualBoundingBoxAscent + metrics.actualBoundingBoxDescent;
    const iconY = y + Math.floor((textH - bh) / 2);

    // Outline
    ctx.strokeStyle = grayColor(COLOR_GRAY);
    ctx.lineWidth = 1;
    ctx.strokeRect(x, iconY, bw, bh);

    // Nub
    const nubY = iconY + Math.floor((bh - nubH) / 2);
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillRect(x + bw + nubGap, nubY, nubW, nubH);

    // Fill bar
    if (pct != null) {
      const fillW = Math.floor((bw - 2) * pct / 100);
      if (fillW > 0) {
        ctx.fillStyle = grayColor(color);
        ctx.fillRect(x + 1, iconY + 1, fillW, bh - 2);
      }
    }

    // Label
    const labelW = metrics.width;
    ctx.fillStyle = grayColor(color);
    ctx.fillText(label, x + bw + nubGap + nubW + gap, y);
    return { x, y, w: bw + nubGap + nubW + gap + labelW, h: textH };
  }

  // mirrors render.py: render_status_icons
  private _renderStatusIcons(ctx: CanvasRenderingContext2D, widget: StatusIconsWidget): WidgetBounds {
    const { x, y: origY, fontSize, rightEdge } = this._getWidgetBase(widget, FONT_SIZE_STATUS_ICONS);
    let y = origY;
    const sc = fontSize / FONT_SIZE_STATUS_ICONS;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const sz = Math.round(STATUS_ICON_SIZE * sc);
    const rowH = Math.round(STATUS_ROW_HEIGHT * sc);

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    if (title) {
      ctx.font = `${Math.round(22 * sc)}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += Math.round(STATUS_TITLE_ADVANCE * sc);
    }

    let curX = x;
    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes as Record<string, string | null>;
      const label = String(attrs.friendly_name ?? entityId);
      const isOn = stateObj.state === "on";
      const deviceClass = String(attrs.device_class ?? "");
      const isProblem = isOn && PROBLEM_DEVICE_CLASSES.has(deviceClass);

      ctx.font = `${fontSize}px ${FONT_FAMILY}`;
      const textW = ctx.measureText(label).width;
      const itemW = sz + Math.round(6 * sc) + textW + Math.round(20 * sc);

      if (curX + itemW > rightEdge - PADDING && curX > x) {
        curX = x;
        y += rowH;
      }

      const iconTop = y + Math.round(4 * sc);
      if (isProblem) {
        ctx.fillStyle = grayColor(COLOR_BLACK);
        ctx.fillRect(curX, iconTop, sz, sz);
      } else {
        ctx.strokeStyle = grayColor(COLOR_GRAY);
        ctx.lineWidth = 1;
        ctx.strokeRect(curX, iconTop, sz, sz);
      }

      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, curX + sz + Math.round(6 * sc), y);

      curX += itemW;
    }
    return { x, y: origY, w: rightEdge - x, h: y - origY + rowH };
  }

  // mirrors render.py: render_waste_schedule
  private _renderWasteSchedule(ctx: CanvasRenderingContext2D, widget: WasteScheduleWidget): WidgetBounds {
    const { x, y: origY, fontSize, rightEdge } = this._getWidgetBase(widget, FONT_SIZE_WASTE_SCHEDULE);
    let y = origY;
    const sc = fontSize / FONT_SIZE_WASTE_SCHEDULE;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const sz = Math.round(WASTE_ICON_SIZE * sc);
    const rowH = Math.round(WASTE_ROW_HEIGHT * sc);

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    if (title) {
      ctx.font = `${Math.round(22 * sc)}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(title, x, y);
      y += Math.round(WASTE_TITLE_ADVANCE * sc);
    }

    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes as Record<string, string | null>;
      const label = String(attrs.friendly_name ?? entityId);
      const raw = stateObj.state ?? "";

      const days = parseDaysUntil(raw);
      if (days !== null && (days < 0 || days > 3)) continue;

      const wcx = x + sz / 2;
      const wcy = y + Math.round(6 * sc) + sz / 2;
      const r = sz / 2;

      ctx.beginPath();
      ctx.arc(wcx, wcy, r, 0, 2 * Math.PI);
      if (days !== null && days <= 1) {
        ctx.fillStyle = grayColor(COLOR_BLACK);
        ctx.fill();
      } else {
        ctx.strokeStyle = grayColor(COLOR_GRAY);
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      ctx.font = `${fontSize}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(label, x + sz + Math.round(8 * sc), y);

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

// HA may create cards before this module runs, producing hui-error-card
// placeholders.  We register the element, then periodically scan the DOM
// (including shadow roots) for stale error cards and force their parent
// hui-card to recreate them.

function ensureRegistered(): void {
  if (!customElements.get(CARD_TAG)) {
    customElements.define(CARD_TAG, EinkDashboardCard);
  }
}
ensureRegistered();

function queryShadow(root: Node, tag: string): Element[] {
  const results: Element[] = [];
  if (root instanceof Element) {
    if (root.localName === tag) results.push(root);
    if (root.shadowRoot) {
      results.push(...queryShadow(root.shadowRoot, tag));
    }
  }
  for (const child of (root as Element).children ?? []) {
    results.push(...queryShadow(child, tag));
  }
  return results;
}

type HuiCard = HTMLElement & { config?: Record<string, unknown> };

function findHuiCard(errorCard: Element): HuiCard | null {
  const root = errorCard.getRootNode();
  if (root instanceof ShadowRoot && root.host?.localName === "hui-card") {
    return root.host as HuiCard;
  }
  let el = errorCard.parentElement;
  while (el) {
    if (el.localName === "hui-card") return el as HuiCard;
    el = el.parentElement;
  }
  return null;
}

function forceHuiCardRebuilds(): number {
  ensureRegistered();
  let fixed = 0;
  for (const el of queryShadow(document.body, "hui-error-card")) {
    const huiCard = findHuiCard(el);
    if (!huiCard) continue;
    const cfg = huiCard.config;
    if (!cfg || cfg.type !== `custom:${CARD_TAG}`) continue;
    huiCard.config = { type: "error", error: "reloading" };
    requestAnimationFrame(() => { huiCard.config = cfg; });
    fixed++;
  }
  return fixed;
}

let _rebuildRetry = 0;
function retryRebuilds(): void {
  if (forceHuiCardRebuilds() > 0 || ++_rebuildRetry >= 10) return;
  setTimeout(retryRebuilds, 2000);
}
setTimeout(retryRebuilds, 1000);

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "E-Ink Dashboard",
  description: "Read-only WYSIWYG canvas preview of an e-ink dashboard",
});

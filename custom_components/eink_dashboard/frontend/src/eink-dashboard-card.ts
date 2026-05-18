// E-Ink Dashboard Lovelace card — SVG preview via WebSocket.

import type {
  HomeAssistant,
  Widget,
  SeparatorWidget,
  LayoutResponse,
  EinkEditorElement,
  ConfigEntry,
  RenderWidgetsResponse,
  RenderWidgetResponse,
  Handle,
  WidgetBounds,
} from "./types/ha.js";
import {
  MIN_RESIZE_DIM,
  snap,
  snapToEdges,
  applyEdgeResize,
  applyCornerResize,
} from "./resize-math.js";

const CARD_TAG = "eink-dashboard-card";
const PADDING = 24;
const HANDLE_SIZE = 12;

// ── Helpers ───────────────────────────────────────────────────────────────────

export function buildHeaderText(device: { name: string }): string {
  return device.name || "E-Ink Dashboard";
}

export function shouldShowCopyUrl(
  model: string,
  hasWebhooks: boolean,
): boolean {
  if (model.startsWith("kindle_")) return true;
  if (model === "custom" && !hasWebhooks) return true;
  // TRMNL devices are push-only (always have webhooks); no URL needed.
  return false;
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
  h?: number;
  font_size?: number;
  /** Effective (computed) length for separator resize math. */
  length?: number;
  /** Raw widget.length before resize (undefined = default span). */
  rawLength?: number;
}

type MutableWidget = Widget & { x2?: number; y2?: number };

class EinkDashboardCard extends HTMLElement {
  private _config: CardConfig | null = null;
  private _hass: HomeAssistant | null = null;
  private _layout: LayoutResponse | null = null;
  private _connected = false;
  // Guards layout fetch only; SVG fetches use _fetchGeneration.
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
  private _resolvedEntryId: string | undefined;
  private _headerEl!: HTMLElement;
  private _copyBtn!: HTMLButtonElement;
  private _copyTimeout: ReturnType<typeof setTimeout> | null = null;
  // SVG rendering state
  private _widgetSvgs: string[] = [];
  private _renderedSvgs: string[] = [];
  private _svgContainer: HTMLDivElement | null = null;
  private _scaleWrapper: HTMLDivElement | null = null;
  private _resizeObserver: ResizeObserver | null = null;
  private _stateDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  // Drag/resize/hover state
  private _dragIndex = -1;
  private _dragStartX = 0;
  private _dragStartY = 0;
  private _dragWidgetStart: DragStart | null = null;
  private _hoverIndex = -1;
  private _resizeIndex = -1;
  private _resizeHandle: string | null = null;
  private _resizeStartX = 0;
  private _resizeStartY = 0;
  private _resizeWidgetStart: ResizeStart | null = null;
  private _handleEls: HTMLDivElement[] = [];
  private _guideLineX: HTMLDivElement | null = null;
  private _guideLineY: HTMLDivElement | null = null;

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
      this._resolvedEntryId = undefined;
      this._widgetSvgs = [];
      this._renderedSvgs = [];
      this._svgContainer = null;
      this._scaleWrapper = null;
      if (this._stateDebounceTimer !== null) {
        clearTimeout(this._stateDebounceTimer);
        this._stateDebounceTimer = null;
      }
      if (this._resizeObserver) {
        this._resizeObserver.disconnect();
        this._resizeObserver = null;
      }
      this._serverImg = null;
      this._fetching = false;
      this._fetchGeneration++;
      this._showServerImage = false;
      this._editMode = false;
      this._editor = null;
      if (this._copyTimeout) { clearTimeout(this._copyTimeout); this._copyTimeout = null; }
      // Reset interaction state on entry change.
      this._dragIndex = -1;
      this._dragWidgetStart = null;
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._hoverIndex = -1;
      this._handleEls = [];
      this._guideLineX = null;
      this._guideLineY = null;
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
      this._scheduleSvgRefresh();
      const newHeader = buildHeaderText(this._layout.device);
      if (this._headerEl.textContent !== newHeader) {
        this._headerEl.textContent = newHeader;
      }
    }
  }

  connectedCallback(): void {
    this._connected = true;
    if (this._layout) {
      void this._fetchWidgetSvgs();
    } else if (this._hass && this._config) {
      this._fetchLayout();
    }
  }

  disconnectedCallback(): void {
    this._connected = false;
    this._fetchGeneration++;
    this._fetching = false;
    if (this._stateDebounceTimer !== null) {
      clearTimeout(this._stateDebounceTimer);
      this._stateDebounceTimer = null;
    }
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
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
        .scale-wrapper {
          position: relative;
          overflow: hidden;
          border: 1px solid var(--divider-color, #e0e0e0);
        }
        .svg-canvas {
          position: absolute;
          top: 0;
          left: 0;
          background: #fff;
          transform-origin: top left;
        }
        .svg-canvas.edit-mode { touch-action: none; }
        .svg-canvas.edit-mode .widget-wrapper { cursor: grab; }
        .widget-wrapper {
          position: absolute;
        }
        .widget-wrapper > svg {
          display: block;
        }
        .widget-wrapper.edit-hover {
          outline: 2px dashed rgba(3, 169, 244, 0.6);
          outline-offset: 2px;
        }
        .svg-canvas.edit-mode .widget-wrapper::before {
          content: '';
          position: absolute;
          top: -10px;
          right: -10px;
          bottom: -10px;
          left: -10px;
        }
        .resize-handle {
          position: absolute;
          width: ${HANDLE_SIZE}px;
          height: ${HANDLE_SIZE}px;
          background: rgba(3, 169, 244, 0.9);
          border: 1px solid #fff;
          z-index: 10;
          box-sizing: border-box;
        }
        .svg-canvas.edit-mode .resize-handle::before {
          content: '';
          position: absolute;
          top: -8px;
          right: -8px;
          bottom: -8px;
          left: -8px;
        }
        .guide-line {
          position: absolute;
          display: none;
          pointer-events: none;
          z-index: 5;
        }
        .guide-line-x {
          top: 0;
          bottom: 0;
          width: 1px;
          background: rgba(3, 169, 244, 0.6);
        }
        .guide-line-y {
          left: 0;
          right: 0;
          height: 1px;
          background: rgba(3, 169, 244, 0.6);
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
          background: #e0e0e0;
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
          background: #e0e0e0;
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
          <button class="toggle-btn" title="Toggle between SVG preview and server-rendered image">
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
      this._svgContainer?.classList.add("edit-mode");
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
      this._svgContainer?.classList.remove("edit-mode");
      this._clearHandles();
    }
  }

  private _onWidgetChange(ev: CustomEvent<{ widgets: Widget[] }>): void {
    this._layout!.widgets = ev.detail.widgets;
    void this._fetchWidgetSvgs();
  }

  private async _onSave(ev: CustomEvent<{ widgets: Widget[] }>): Promise<void> {
    if (this._saving) return;
    this._saving = true;
    this._editor?.setSaveState("saving");
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
      // Must follow setWidgets: _rebuild replaces shadow DOM, so the
      // button queried inside setSaveState must already be the new node.
      this._editor?.setSaveState("saved");
    } catch (err) {
      console.error("Failed to save layout:", err);
      this._saveError.textContent = `Save failed: ${(err as Error).message || err}`;
      this._saveError.style.display = "block";
      this._editor?.setSaveState("idle");
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
      this._buildSvgContainer();
      await this._fetchWidgetSvgs();
    } catch (err) {
      if (gen !== this._fetchGeneration) return;
      const div = document.createElement("div");
      div.className = "error";
      div.textContent = `Failed to load layout: ${(err as Error).message}`;
      this._container.replaceChildren(div);
    } finally {
      this._fetching = false;
    }
  }

  // ── SVG container ─────────────────────────────────────────────────────────

  /**
   * Build the DOM structure for SVG widget rendering and
   * attach it to the container. Replaces _initCanvas().
   *
   * Creates a scale-wrapper div whose height tracks the
   * scaled display height so surrounding elements flow
   * correctly, and an absolutely-positioned svg-canvas
   * that holds one .widget-wrapper div per widget.
   * A ResizeObserver keeps the CSS scale factor in sync
   * with the container's rendered width.
   *
   * Creates 6 reusable resize handle divs and attaches
   * pointer event listeners to the svg-canvas.
   */
  private _buildSvgContainer(): void {
    const { width, height } = this._layout!.display;

    const scaleWrapper = document.createElement("div");
    scaleWrapper.className = "scale-wrapper";

    const svgCanvas = document.createElement("div");
    svgCanvas.className = "svg-canvas";
    svgCanvas.style.width = `${width}px`;
    svgCanvas.style.height = `${height}px`;
    scaleWrapper.appendChild(svgCanvas);

    // Create a fixed pool of 6 handle divs reused across hover states.
    this._handleEls = [];
    const handleIds = ["nw", "ne", "sw", "se", "w", "e"];
    for (const id of handleIds) {
      const h = document.createElement("div");
      h.className = "resize-handle";
      h.dataset.handleId = id;
      h.style.display = "none";
      // Center each handle on its corner: shift left/up by half
      // the handle size so the center sits on the corner point.
      h.style.marginLeft = `${-HANDLE_SIZE / 2}px`;
      h.style.marginTop = `${-HANDLE_SIZE / 2}px`;
      svgCanvas.appendChild(h);
      this._handleEls.push(h);
    }

    const guideX = document.createElement("div");
    guideX.className = "guide-line guide-line-x";
    svgCanvas.appendChild(guideX);
    this._guideLineX = guideX;

    const guideY = document.createElement("div");
    guideY.className = "guide-line guide-line-y";
    svgCanvas.appendChild(guideY);
    this._guideLineY = guideY;

    const img = document.createElement("img");
    img.className = "server-render";
    img.style.display = "none";
    this._serverImg = img;

    this._scaleWrapper = scaleWrapper;
    this._svgContainer = svgCanvas;

    this._renderedSvgs = [];
    this._container.innerHTML = "";
    this._container.appendChild(scaleWrapper);
    // Server image is a sibling so it fills the container
    // naturally (width: 100%; height: auto) when shown.
    this._container.appendChild(img);

    // Pointer listeners on the svg-canvas for event delegation.
    svgCanvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    svgCanvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    svgCanvas.addEventListener("pointerup", (e) => this._onPointerUp(e));
    svgCanvas.addEventListener("pointercancel", (e) => this._onPointerCancel(e));
    svgCanvas.addEventListener("pointerleave", () => this._onPointerLeave());

    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
    }
    this._resizeObserver = new ResizeObserver(() => this._updateScale());
    this._resizeObserver.observe(this._container);
    this._updateScale();
  }

  /**
   * Compute the CSS scale factor (container width / display
   * width) and apply it to the svg-canvas via a CSS transform.
   * Writes an explicit height on the scale-wrapper so the
   * element participates in normal document flow at the correct
   * scaled size.
   */
  private _updateScale(): void {
    if (!this._svgContainer || !this._scaleWrapper || !this._layout) return;
    const { width, height } = this._layout.display;
    const containerWidth = this._container.clientWidth;
    if (!containerWidth) return;
    const scale = containerWidth / width;
    this._svgContainer.style.transform = `scale(${scale})`;
    this._scaleWrapper.style.height = `${Math.round(height * scale)}px`;
  }

  /**
   * Fetch SVG strings for all widgets via WebSocket and
   * update the DOM. Always passes the local widget list so
   * unsaved editor changes are reflected immediately.
   *
   * A generation counter prevents a stale response from an
   * earlier call from overwriting the result of a newer one.
   *
   * @returns Promise that resolves when the DOM is updated,
   *   or rejects silently on error.
   */
  private async _fetchWidgetSvgs(): Promise<void> {
    if (!this._connected || !this._hass || !this._layout || !this._resolvedEntryId) return;
    const gen = this._fetchGeneration;
    try {
      const result = await this._hass.callWS<RenderWidgetsResponse>({
        type: "eink_dashboard/render_widgets",
        entry_id: this._resolvedEntryId,
        widgets: this._layout.widgets,
      });
      if (gen !== this._fetchGeneration) return;
      this._widgetSvgs = result.svgs;
      this._updateSvgDom();
    } catch (err) {
      console.error("Failed to fetch widget SVGs:", err);
    }
  }

  /**
   * Synchronise .widget-wrapper divs in .svg-canvas with the
   * current widget list and SVG strings. Creates or removes
   * wrapper elements as needed. Skips innerHTML assignment
   * when the SVG string is unchanged to avoid unnecessary
   * DOM thrashing.
   *
   * Skips position and content updates during an active drag
   * or resize so the user's in-flight interaction is not
   * overwritten by a concurrent refresh.
   */
  private _updateSvgDom(): void {
    if (!this._svgContainer || !this._layout) return;
    // Skip mid-interaction: CSS is authoritative during drag/resize.
    if (this._dragIndex >= 0 || this._resizeIndex >= 0) return;

    const widgets = this._layout.widgets;
    const container = this._svgContainer;

    // Remove excess wrappers when the widget count shrank.
    // Handles live at the end of the container, so only remove
    // non-handle children past the widget count.
    const nonHandleCount = container.childElementCount - this._handleEls.length;
    for (let i = nonHandleCount - 1; i >= widgets.length; i--) {
      const candidate = container.children[i];
      if (candidate && !this._handleEls.includes(candidate as HTMLDivElement)) {
        container.removeChild(candidate);
      }
    }

    for (let i = 0; i < widgets.length; i++) {
      const w = widgets[i];
      // Wrappers are inserted before the handle elements.
      let wrapper = container.children[i] as HTMLDivElement | undefined;
      if (!wrapper || this._handleEls.includes(wrapper)) {
        wrapper = document.createElement("div");
        wrapper.className = "widget-wrapper";
        container.insertBefore(wrapper, this._handleEls[0] ?? null);
      }
      wrapper.dataset.index = String(i);
      wrapper.style.left = `${w.x ?? 24}px`;
      wrapper.style.top = `${w.y ?? 0}px`;
      const svg = this._widgetSvgs[i] ?? "";
      if (this._renderedSvgs[i] !== svg) {
        wrapper.innerHTML = svg;
        this._renderedSvgs[i] = svg;
      }
    }
  }

  /**
   * Debounce SVG refreshes triggered by entity state changes.
   * Batches rapid updates (e.g. multiple entities updating
   * at once) into a single WS call 500 ms after the last
   * hass assignment. Skips when the server image is visible
   * because the SVG container is hidden. Also skips during
   * active drag/resize to avoid overwriting in-flight CSS.
   */
  private _scheduleSvgRefresh(): void {
    if (!this._connected || !this._layout || this._showServerImage) return;
    if (this._dragIndex >= 0 || this._resizeIndex >= 0) return;
    if (this._stateDebounceTimer !== null) {
      clearTimeout(this._stateDebounceTimer);
    }
    this._stateDebounceTimer = setTimeout(() => {
      this._stateDebounceTimer = null;
      void this._fetchWidgetSvgs();
    }, 500);
  }

  // ── Server image toggle ───────────────────────────────────────────────────

  private async _onToggle(): Promise<void> {
    if (!this._scaleWrapper) return;
    this._showServerImage = !this._showServerImage;
    if (this._showServerImage) {
      const entryId = this._resolvedEntryId;
      if (this._layout?.widgets) {
        // Save the current widget list so the server image
        // reflects the editor state.  This persists unsaved
        // changes.
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
      this._scaleWrapper.style.display = "none";
      this._serverImg!.style.display = "block";
      this._toggleBtn.textContent = "Show SVG preview";
      this._toggleBtn.classList.add("active");
    } else {
      this._serverImg!.style.display = "none";
      this._scaleWrapper.style.display = "";
      this._toggleBtn.textContent = "Show rendered image";
      this._toggleBtn.classList.remove("active");
      void this._fetchWidgetSvgs();
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

  // ── Drag / resize interaction ─────────────────────────────────────────────

  /**
   * Show or hide alignment guide lines at the given display-space
   * coordinates.
   *
   * @param gx - X-coordinate for the vertical guide, or `undefined`
   *   to hide it.
   * @param gy - Y-coordinate for the horizontal guide, or `undefined`
   *   to hide it.
   */
  private _showGuides(
    gx: number | undefined,
    gy: number | undefined,
  ): void {
    if (this._guideLineX) {
      if (gx !== undefined) {
        this._guideLineX.style.left = `${gx}px`;
        this._guideLineX.style.display = "block";
      } else {
        this._guideLineX.style.display = "none";
      }
    }
    if (this._guideLineY) {
      if (gy !== undefined) {
        this._guideLineY.style.top = `${gy}px`;
        this._guideLineY.style.display = "block";
      } else {
        this._guideLineY.style.display = "none";
      }
    }
  }

  /** Hide both alignment guide lines. */
  private _hideGuides(): void {
    if (this._guideLineX) {
      this._guideLineX.style.display = "none";
    }
    if (this._guideLineY) {
      this._guideLineY.style.display = "none";
    }
  }

  /**
   * Returns the CSS scale factor mapping display-space pixels
   * to client (screen) pixels. Used to convert pointer deltas
   * from client space back into display space.
   */
  private _getScale(): number {
    if (!this._layout) return 1;
    const cw = this._container.clientWidth;
    return cw ? cw / this._layout.display.width : 1;
  }

  /**
   * Retrieve the widget wrapper element at a given index.
   *
   * @param index - Widget index in the layout widget list.
   * @returns The wrapper div, or null if out of range.
   */
  private _wrapperAt(index: number): HTMLDivElement | null {
    if (!this._svgContainer) return null;
    const el = this._svgContainer.children[index] as HTMLDivElement | undefined;
    if (!el || this._handleEls.includes(el)) return null;
    return el;
  }

  /**
   * Collect bounding boxes of all widgets except the one at
   * excludeIndex, using DOM wrapper geometry for accurate
   * rendered dimensions.
   *
   * @param excludeIndex - Index of the widget currently being
   *   dragged; it is omitted from the result.
   * @returns Array of WidgetBounds for all other widgets.
   */
  private _getSnapTargets(excludeIndex: number): WidgetBounds[] {
    const targets: WidgetBounds[] = [];
    if (!this._layout) return targets;
    const { widgets } = this._layout;
    for (let i = 0; i < widgets.length; i++) {
      if (i === excludeIndex) continue;
      const wr = this._wrapperAt(i);
      if (!wr) continue;
      targets.push({
        x: wr.offsetLeft,
        y: wr.offsetTop,
        w: wr.offsetWidth,
        h: wr.offsetHeight,
      });
    }
    return targets;
  }

  /**
   * Compute resize handle positions for the widget at index.
   *
   * Returns start/end handles for separators. All other widget
   * types get 4 corner handles (nw/ne/sw/se) for width+height
   * resize, plus left/right edge handles (w/e) for width-only
   * resize. Positions are in display space, derived from the
   * wrapper element's offset geometry.
   *
   * @param index - Widget index in the layout widget list.
   * @returns Array of Handle objects (id + position).
   */
  private _getHandles(index: number): Handle[] {
    const wrapper = this._wrapperAt(index);
    if (!wrapper) return [];
    const widget = this._layout!.widgets[index];
    const x = wrapper.offsetLeft;
    const y = wrapper.offsetTop;
    const w = wrapper.offsetWidth;
    const h = wrapper.offsetHeight;

    if (widget.type === "separator") {
      const dir = (widget as SeparatorWidget).direction ?? "horizontal";
      if (dir === "vertical") {
        const cx = x + w / 2;
        return [
          { id: "start", cx, cy: y },
          { id: "end",   cx, cy: y + h },
        ];
      }
      const cy = y + h / 2;
      return [
        { id: "start", cx: x,     cy },
        { id: "end",   cx: x + w, cy },
      ];
    }
    // All other widgets: 4 corners + left/right edge midpoints.
    return [
      { id: "nw", cx: x,         cy: y },
      { id: "ne", cx: x + w,     cy: y },
      { id: "sw", cx: x,         cy: y + h },
      { id: "se", cx: x + w,     cy: y + h },
      { id: "w",  cx: x,         cy: y + h / 2 },
      { id: "e",  cx: x + w,     cy: y + h / 2 },
    ];
  }

  /**
   * Position and show the resize handle divs for widget index.
   * Unused handles (when a widget type has fewer than 4) are
   * hidden. The hovered wrapper receives the edit-hover class.
   *
   * @param index - Widget index to show handles for.
   */
  private _updateHandles(index: number): void {
    // Clear hover class from any previously highlighted wrapper.
    if (this._hoverIndex >= 0 && this._hoverIndex !== index) {
      this._wrapperAt(this._hoverIndex)?.classList.remove("edit-hover");
    }
    this._hoverIndex = index;
    this._wrapperAt(index)?.classList.add("edit-hover");

    const handles = this._getHandles(index);
    const widget = this._layout!.widgets[index];

    // Hide unused handle slots, then position the active ones.
    for (const hEl of this._handleEls) {
      hEl.style.display = "none";
    }

    handles.forEach((h, i) => {
      const hEl = this._handleEls[i];
      if (!hEl) return;
      hEl.dataset.handleId = h.id;
      hEl.dataset.widgetIndex = String(index);
      // left/top position the center of the handle on the corner
      // point. The -HANDLE_SIZE/2 margin-left/top (set once in
      // _buildSvgContainer) handles the centering offset.
      hEl.style.left = `${h.cx}px`;
      hEl.style.top = `${h.cy}px`;
      hEl.style.cursor = this._getResizeCursor(h.id, widget);
      hEl.style.display = "block";
    });
  }

  /** Hide the resize handle squares without touching the hover outline. */
  private _hideHandles(): void {
    for (const hEl of this._handleEls) {
      hEl.style.display = "none";
    }
  }

  /**
   * Hide all resize handles and clear the hover outline from
   * the currently hovered wrapper.
   */
  private _clearHandles(): void {
    if (this._hoverIndex >= 0) {
      this._wrapperAt(this._hoverIndex)?.classList.remove("edit-hover");
    }
    this._hoverIndex = -1;
    this._hideHandles();
  }

  /**
   * Return the CSS cursor name appropriate for a resize handle.
   *
   * @param handleId - Handle identifier (e.g. "nw", "se", "w").
   * @param widget - Widget being resized.
   * @returns CSS cursor string.
   */
  private _getResizeCursor(handleId: string, widget: Widget): string {
    if (widget.type === "separator") {
      const dir = (widget as SeparatorWidget).direction ?? "horizontal";
      return dir === "vertical" ? "ns-resize" : "ew-resize";
    }
    if (handleId === "w" || handleId === "e") return "ew-resize";
    return handleId === "nw" || handleId === "se"
      ? "nwse-resize"
      : "nesw-resize";
  }

  // ── Pointer event handlers ────────────────────────────────────────────────

  private _onPointerDown(event: PointerEvent): void {
    if (!this._editMode || this._showServerImage || !this._layout) return;

    const target = event.target as HTMLElement;

    // Check resize handle hit first.
    if (target.classList.contains("resize-handle")) {
      const handleId = target.dataset.handleId!;
      const index = parseInt(target.dataset.widgetIndex!, 10);
      if (isNaN(index)) return;
      event.preventDefault();
      this._svgContainer!.setPointerCapture(event.pointerId);

      const w = this._layout.widgets[index] as MutableWidget;
      const s: ResizeStart = {
        x: w.x ?? 0,
        y: w.y ?? 0,
        x2: (w as MutableWidget).x2 ?? 0,
        y2: (w as MutableWidget).y2 ?? 0,
        w: w.w,
        h: w.h,
        font_size: w.font_size,
      };
      if (w.type === "separator") {
        const sw = w as SeparatorWidget;
        const { width: dw, height: dh } = this._layout.display;
        const dir = sw.direction ?? "horizontal";
        s.rawLength = sw.length;
        // Effective length gives a concrete start value even when
        // the widget uses the default full-span (length undefined).
        s.length = sw.length ?? (dir === "vertical"
          ? dh - PADDING - (sw.y ?? 0)
          : dw - PADDING - (sw.x ?? PADDING));
      }
      this._resizeIndex = index;
      this._resizeHandle = handleId;
      this._resizeStartX = event.clientX;
      this._resizeStartY = event.clientY;
      this._resizeWidgetStart = s;
      this._svgContainer!.style.cursor = this._getResizeCursor(handleId, w);
      // Hide handle squares during drag; keep the blue outline visible.
      this._hideHandles();
      return;
    }

    // Check widget wrapper hit (may be a descendant SVG element).
    const wrapper = (target as Element).closest?.(".widget-wrapper") as HTMLDivElement | null;
    if (!wrapper) return;
    const index = parseInt(wrapper.dataset.index!, 10);
    if (isNaN(index)) return;

    event.preventDefault();
    this._svgContainer!.setPointerCapture(event.pointerId);

    const w = this._layout.widgets[index] as MutableWidget;
    this._dragIndex = index;
    this._dragStartX = event.clientX;
    this._dragStartY = event.clientY;
    this._dragWidgetStart = {
      x: w.x ?? 0,
      y: w.y ?? 0,
      x2: w.x2,
      y2: w.y2,
    };
    this._svgContainer!.style.cursor = "grabbing";
    // Hide handles during drag; keep the blue outline on the dragged widget.
    this._clearHandles();
    wrapper.classList.add("edit-hover");
  }

  private _onPointerMove(event: PointerEvent): void {
    if (!this._editMode || this._showServerImage || !this._layout) return;

    // ── Resize drag ──────────────────────────────────────────
    if (this._resizeIndex >= 0) {
      event.preventDefault();
      const scale = this._getScale();
      const dx = Math.round((event.clientX - this._resizeStartX) / scale);
      const dy = Math.round((event.clientY - this._resizeStartY) / scale);
      const w = this._layout.widgets[this._resizeIndex] as MutableWidget;
      const s = this._resizeWidgetStart!;
      const { width: dw, height: dh } = this._layout.display;
      const handle = this._resizeHandle!;
      const wrapper = this._wrapperAt(this._resizeIndex);

      if (w.type === "separator") {
        const sw = w as SeparatorWidget;
        const dir = sw.direction ?? "horizontal";
        const sLen = s.length ?? 0;
        if (handle === "start") {
          if (dir === "vertical") {
            const endY = s.y + sLen;
            const newY = snap(Math.max(0, Math.min(endY - 20, s.y + dy)));
            sw.y = newY;
            sw.length = endY - newY;
          } else {
            const endX = s.x + sLen;
            const newX = snap(Math.max(0, Math.min(endX - 20, s.x + dx)));
            sw.x = newX;
            sw.length = endX - newX;
          }
        } else if (handle === "end") {
          const delta = dir === "vertical" ? dy : dx;
          sw.length = snap(Math.max(20, sLen + delta));
        }
        // CSS feedback for separator: update wrapper dimensions.
        if (wrapper) {
          if (dir === "vertical") {
            wrapper.style.top = `${sw.y}px`;
            wrapper.style.height = `${sw.length}px`;
          } else {
            wrapper.style.left = `${sw.x}px`;
            wrapper.style.width = `${sw.length}px`;
          }
        }
      } else if (handle === "w" || handle === "e") {
        // Edge handles: width-only resize.
        const startW = s.w ?? wrapper?.offsetWidth ?? MIN_RESIZE_DIM;
        const r = applyEdgeResize(
          handle as "w" | "e", dx, s.x, startW, dw, MIN_RESIZE_DIM,
        );
        if (r.x !== undefined) w.x = r.x;
        w.w = r.w;
        if (wrapper) {
          // "e" handle doesn't write w.x (left edge is fixed);
          // w.x ?? s.x correctly falls back to the captured start x.
          wrapper.style.left = `${w.x ?? s.x}px`;
          if (w.w != null) wrapper.style.width = `${w.w}px`;
        }
      } else {
        // Corner handles: width + height resize.
        const startW = s.w ?? wrapper?.offsetWidth ?? MIN_RESIZE_DIM;
        const startH = s.h ?? wrapper?.offsetHeight ?? MIN_RESIZE_DIM;
        const r = applyCornerResize(
          handle as "nw" | "ne" | "sw" | "se",
          dx, dy, s.x, s.y, startW, startH, MIN_RESIZE_DIM, dw, dh,
        );
        if (r.x !== undefined) w.x = r.x;
        if (r.y !== undefined) w.y = r.y;
        w.w = r.w;
        w.h = r.h;
        // Scale font proportionally for widget types where font_size
        // controls rendered text size (text, weather). Other widget
        // types derive font sizes from h directly, so no change needed.
        if (
          s.font_size != null
          && (w.type === "text" || w.type === "weather")
        ) {
          const startDiag = Math.sqrt(startW ** 2 + startH ** 2);
          const newDiag = Math.sqrt(r.w ** 2 + r.h ** 2);
          if (startDiag > 0) {
            w.font_size = Math.max(8, Math.min(72,
              Math.round(s.font_size * newDiag / startDiag)));
          }
        }
        if (wrapper) {
          wrapper.style.left = `${w.x ?? s.x}px`;
          wrapper.style.top = `${w.y ?? s.y}px`;
          if (w.w != null) wrapper.style.width = `${w.w}px`;
          if (w.h != null) wrapper.style.height = `${w.h}px`;
        }
      }
      return;
    }

    // ── Widget drag ───────────────────────────────────────────
    if (this._dragIndex >= 0) {
      event.preventDefault();
      const scale = this._getScale();
      const dx = Math.round((event.clientX - this._dragStartX) / scale);
      const dy = Math.round((event.clientY - this._dragStartY) / scale);
      const w = this._layout.widgets[this._dragIndex] as MutableWidget;
      const s = this._dragWidgetStart!;
      const { width, height } = this._layout.display;

      // Raw candidate position, clamped to display bounds.
      const rawX = Math.max(0, Math.min(width - 1, s.x + dx));
      const rawY = Math.max(0, Math.min(height - 1, s.y + dy));

      if (event.shiftKey) {
        // Shift held: snap to nearest edge of any other widget.
        const dragWrapper = this._wrapperAt(this._dragIndex);
        const candidate: WidgetBounds = {
          x: rawX,
          y: rawY,
          w: dragWrapper?.offsetWidth ?? 0,
          h: dragWrapper?.offsetHeight ?? 0,
        };
        const snapped = snapToEdges(
          candidate, this._getSnapTargets(this._dragIndex),
        );
        // Edge snap can shift the candidate past the display edge;
        // re-clamp after the snap.
        w.x = Math.max(0, Math.min(width - 1, snapped.x));
        w.y = Math.max(0, Math.min(height - 1, snapped.y));
        this._showGuides(snapped.guideX, snapped.guideY);
      } else {
        w.x = snap(rawX);
        w.y = snap(rawY);
        this._hideGuides();
      }

      // x2/y2 are absolute coordinates, not offsets, so they
      // don't follow x/y automatically — shift them by the same
      // total displacement as the primary point.
      if (s.x2 !== undefined) {
        const shiftX = w.x - s.x;
        const shiftY = w.y - s.y;
        w.x2 = Math.max(
          0, Math.min(width - 1, s.x2 + shiftX),
        );
        w.y2 = Math.max(
          0, Math.min(height - 1, (s.y2 ?? 0) + shiftY),
        );
      }

      // Update CSS directly; no server round-trip during drag.
      const wrapper = this._wrapperAt(this._dragIndex);
      if (wrapper) {
        wrapper.style.left = `${w.x}px`;
        wrapper.style.top = `${w.y}px`;
      }
      return;
    }

    // ── Hover (no button pressed) ─────────────────────────────
    const target = event.target as HTMLElement;

    if (target.classList.contains("resize-handle")) {
      // Pointer is over a handle — cursor is already set on it.
      return;
    }

    const hoverWrapper = (target as Element).closest?.(".widget-wrapper") as HTMLDivElement | null;
    const hoverIndex = hoverWrapper
      ? parseInt(hoverWrapper.dataset.index ?? "", 10)
      : -1;
    const validHover = !isNaN(hoverIndex) && hoverIndex >= 0;

    if (validHover && hoverIndex !== this._hoverIndex) {
      this._updateHandles(hoverIndex);
    } else if (!validHover && this._hoverIndex >= 0) {
      this._clearHandles();
    }
  }

  /**
   * Finalise a drag or resize interaction on pointer release.
   *
   * For resizes, clears CSS overrides on the wrapper and
   * re-fetches the accurate SVG for the widget at its new
   * dimensions via the render_widget WebSocket command.
   * For drags, the widget data was already updated on every
   * pointermove so no re-fetch is needed. In both cases the
   * editor panel is synced with the updated widget list.
   */
  private _onPointerUp(event: PointerEvent): void {
    this._svgContainer?.releasePointerCapture(event.pointerId);

    if (this._resizeIndex >= 0) {
      const index = this._resizeIndex;
      const wrapper = this._wrapperAt(index);

      // Clear CSS overrides so the server SVG renders cleanly.
      if (wrapper) {
        wrapper.style.width = "";
        wrapper.style.height = "";
        wrapper.style.transform = "";
        wrapper.style.transformOrigin = "";
        // Keep position at the committed coordinates to avoid a
        // visible jump while _refetchWidget re-renders the SVG.
        const w = this._layout!.widgets[index];
        wrapper.style.left = `${w.x ?? 24}px`;
        wrapper.style.top = `${w.y ?? 0}px`;
      }

      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._svgContainer!.style.cursor = "";

      if (this._editor) {
        this._editor.setWidgets(this._layout!.widgets);
      }

      // Re-fetch the single resized widget at its new dimensions.
      void this._refetchWidget(index);
      return;
    }

    if (this._dragIndex >= 0) {
      this._dragIndex = -1;
      this._dragWidgetStart = null;
      this._svgContainer!.style.cursor = "";
      this._hideGuides();

      if (this._editor) {
        this._editor.setWidgets(this._layout!.widgets);
      }
    }
  }

  private _onPointerCancel(event: PointerEvent): void {
    this._svgContainer?.releasePointerCapture(event.pointerId);
    if (this._resizeIndex >= 0) {
      const w = this._layout!.widgets[this._resizeIndex] as MutableWidget;
      const s = this._resizeWidgetStart!;
      // Restore the widget config snapshot.
      w.x = s.x;
      w.y = s.y;
      w.w = s.w;
      w.h = s.h;
      w.font_size = s.font_size;
      if (w.type === "separator") {
        (w as SeparatorWidget).length = s.rawLength;
      }
      const wrapper = this._wrapperAt(this._resizeIndex);
      if (wrapper) {
        wrapper.style.width = "";
        wrapper.style.height = "";
        wrapper.style.transform = "";
        wrapper.style.transformOrigin = "";
        wrapper.style.top = `${s.y}px`;
        wrapper.style.left = `${s.x}px`;
      }
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._svgContainer!.style.cursor = "";
      return;
    }

    if (this._dragIndex >= 0) {
      const w = this._layout!.widgets[this._dragIndex] as MutableWidget;
      const s = this._dragWidgetStart!;
      w.x = s.x;
      w.y = s.y;
      if (s.x2 !== undefined) {
        w.x2 = s.x2;
        w.y2 = s.y2;
      }
      const wrapper = this._wrapperAt(this._dragIndex);
      if (wrapper) {
        wrapper.style.left = `${s.x}px`;
        wrapper.style.top = `${s.y}px`;
      }
      this._dragIndex = -1;
      this._dragWidgetStart = null;
      this._svgContainer!.style.cursor = "";
      this._hideGuides();
    }
  }

  private _onPointerLeave(): void {
    if (this._dragIndex >= 0 || this._resizeIndex >= 0) return;
    this._clearHandles();
  }

  /**
   * Re-fetch the SVG for a single widget after a resize commit.
   *
   * Uses the render_widget WebSocket command with the updated
   * widget dict so the server renders at the new dimensions.
   * On success, updates the wrapper innerHTML and the cached
   * SVG string so a subsequent full refresh does not re-render.
   *
   * @param index - Widget index to refresh.
   */
  private async _refetchWidget(index: number): Promise<void> {
    if (!this._hass || !this._layout || !this._resolvedEntryId) return;
    try {
      const w = this._layout.widgets[index];
      const result = await this._hass.callWS<RenderWidgetResponse>({
        type: "eink_dashboard/render_widget",
        entry_id: this._resolvedEntryId,
        widget_index: index,
        widget: w,
      });
      const wrapper = this._wrapperAt(index);
      if (wrapper) {
        wrapper.innerHTML = result.svg;
        // Restore position from widget data after clearing CSS overrides.
        wrapper.style.left = `${w.x ?? 24}px`;
        wrapper.style.top = `${w.y ?? 0}px`;
      }
      this._renderedSvgs[index] = result.svg;
      this._widgetSvgs[index] = result.svg;
    } catch (err) {
      console.error("Failed to re-fetch widget SVG:", err);
      // Fallback: do a full refresh so the display stays consistent.
      void this._fetchWidgetSvgs();
    }
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
  description: "SVG preview of an e-ink dashboard",
});

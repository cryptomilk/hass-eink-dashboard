// E-Ink Dashboard Lovelace card — SVG preview via WebSocket.

import type {
  HomeAssistant,
  Widget,
  LayoutResponse,
  EinkEditorElement,
  ConfigEntry,
  RenderWidgetsResponse,
} from "./types/ha.js";

const CARD_TAG = "eink-dashboard-card";
const GRID = 8;

// ── Helpers ───────────────────────────────────────────────────────────────────

export function snap(v: number): number { return Math.round(v / GRID) * GRID; }

export function buildHeaderText(device: { name: string }): string {
  return device.name || "E-Ink Dashboard";
}

export function shouldShowCopyUrl(model: string, hasWebhooks: boolean): boolean {
  if (model.startsWith("kindle_")) return true;
  if (model === "custom" && !hasWebhooks) return true;
  // TRMNL devices are push-only (always have webhooks); no URL needed.
  return false;
}

// ── Card class ────────────────────────────────────────────────────────────────

interface CardConfig {
  config_entry?: string;
}

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
        }
        .svg-canvas {
          position: absolute;
          top: 0;
          left: 0;
          background: #fff;
          transform-origin: top left;
        }
        .widget-wrapper {
          position: absolute;
        }
        .widget-wrapper > svg {
          display: block;
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
        .edit-btn { display: none; }
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
    void this._fetchWidgetSvgs();
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
   */
  private _updateSvgDom(): void {
    if (!this._svgContainer || !this._layout) return;
    const widgets = this._layout.widgets;
    const container = this._svgContainer;

    // Remove excess wrappers when the widget count shrank.
    while (container.childElementCount > widgets.length) {
      container.removeChild(container.lastElementChild!);
    }

    for (let i = 0; i < widgets.length; i++) {
      const w = widgets[i];
      let wrapper = container.children[i] as HTMLDivElement | undefined;
      if (!wrapper) {
        wrapper = document.createElement("div");
        wrapper.className = "widget-wrapper";
        container.appendChild(wrapper);
      }
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
   * because the SVG container is hidden.
   */
  private _scheduleSvgRefresh(): void {
    if (!this._connected || !this._layout || this._showServerImage) return;
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

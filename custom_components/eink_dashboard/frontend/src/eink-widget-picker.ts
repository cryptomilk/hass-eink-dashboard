// Widget type picker dialog for the e-ink dashboard editor.
// Shows a grid of widget type cards with icon, name, and description.
// Fires "type-selected" (detail: { type }) on pick, "closed" on dismiss.

import type { WidgetTypeMeta } from "./types/ha.js";

const PICKER_TAG = "eink-widget-picker";

// Unicode fallbacks for MDI icon names that the browser can't load.
const ICON_FALLBACK: Record<string, string> = {
  "mdi:format-text": "T",
  "mdi:format-header-1": "#",
  "mdi:minus": "—",
  "mdi:weather-partly-cloudy": "⛅",
  "mdi:thermometer": "🌡",
  "mdi:battery": "🔋",
  "mdi:checkbox-marked-circle": "✓",
  "mdi:trash-can": "🗑",
  "mdi:card-text": "▣",
  "mdi:card-text-outline": "▢",
  "mdi:format-list-bulleted": "☰",
  "mdi:chart-line": "📈",
  "mdi:calendar": "📅",
  "mdi:gauge": "◎",
};

/**
 * Widget-type picker dialog for the e-ink dashboard editor.
 *
 * Renders a modal overlay with a grid of widget type cards.
 * The caller creates one instance (typically appended to its
 * own shadow root) and calls `open(types)` to show the picker.
 *
 * Lifecycle:
 *   1. `open(types)` builds the shadow DOM on the first call,
 *      then shows the overlay and registers an Escape listener.
 *   2. The user clicks a card or the close button, or presses
 *      Escape — the overlay hides and the Escape listener is
 *      removed.
 *
 * Events emitted (bubbles, composed):
 *   - `type-selected` (detail: `{ type: string }`) — fired
 *     when the user picks a widget type.
 *   - `closed` — fired when the dialog is dismissed without a
 *     selection (close button, backdrop click, or Escape).
 *
 * Note: `position: fixed` inside a nested shadow DOM may be
 * clipped when an ancestor uses `transform` or `will-change`,
 * which creates a new CSS containing block. The HA-idiomatic
 * fix (appending to `document.body`) requires cross-shadow
 * event plumbing. The current approach works in standard HA
 * Lovelace without ancestor transforms.
 */
class EinkWidgetPicker extends HTMLElement {
  /** True after the shadow DOM has been built on first open. */
  private _built = false;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  /**
   * Show the picker modal populated with the given widget types.
   *
   * Builds the shadow DOM on first call; subsequent calls
   * re-show the existing DOM. Each entry in the types map
   * becomes one card in the picker grid.
   *
   * @param types - Map of widget type key to metadata
   *   (label, description, icon, defaults).
   */
  open(types: Record<string, WidgetTypeMeta>): void {
    if (!this._built) {
      this._build(types);
      this._built = true;
    }
    this.shadowRoot!
      .querySelector<HTMLElement>(".overlay")!
      .style.display = "flex";
    // Remove before add so calling open() twice without an
    // intervening close() never stacks duplicate listeners.
    document.removeEventListener("keydown", this._onKeyDown);
    document.addEventListener("keydown", this._onKeyDown);
  }

  /** Hide the overlay and notify the parent via "closed". */
  private _close(): void {
    this.shadowRoot!
      .querySelector<HTMLElement>(".overlay")!
      .style.display = "none";
    document.removeEventListener("keydown", this._onKeyDown);
    this.dispatchEvent(
      new CustomEvent("closed", { bubbles: true, composed: true })
    );
  }

  /**
   * Select a widget type: close the dialog and fire
   * "type-selected" with the chosen type key.
   *
   * @param type - Widget type key (e.g. "text").
   */
  private _pick(type: string): void {
    this._close();
    this.dispatchEvent(
      new CustomEvent("type-selected", {
        detail: { type },
        bubbles: true,
        composed: true,
      })
    );
  }

  /** Close the picker when Escape is pressed. */
  private readonly _onKeyDown = (ev: KeyboardEvent): void => {
    if (ev.key === "Escape") this._close();
  };

  /**
   * Build the full shadow DOM: style, overlay, dialog header,
   * and one card per widget type. Called once on the first
   * `open()` invocation.
   *
   * @param types - Widget type registry to render.
   */
  private _build(types: Record<string, WidgetTypeMeta>): void {
    const cards = Object.entries(types)
      .map(([key, meta]) => this._buildCard(key, meta))
      .join("");

    this.shadowRoot!.innerHTML = `
      <style>
        .overlay {
          display: none;
          /* position:fixed inside nested shadow DOM may be
             clipped if an ancestor uses transform or
             will-change. Works in standard HA Lovelace. */
          position: fixed;
          inset: 0;
          z-index: 999;
          background: rgba(0, 0, 0, 0.5);
          align-items: center;
          justify-content: center;
          padding: 16px;
          box-sizing: border-box;
        }
        .dialog {
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.24);
          width: 100%;
          max-width: 560px;
          max-height: calc(100vh - 64px);
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .dialog-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid
            var(--divider-color, #e0e0e0);
        }
        .dialog-title {
          font-size: 18px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
          margin: 0;
        }
        .close-btn {
          background: none;
          border: none;
          cursor: pointer;
          padding: 4px;
          font-size: 20px;
          color: var(--secondary-text-color, #757575);
          border-radius: 4px;
          line-height: 1;
        }
        .close-btn:hover {
          background: var(--divider-color, #e0e0e0);
        }
        .grid {
          display: grid;
          grid-template-columns:
            repeat(auto-fill, minmax(220px, 1fr));
          gap: 12px;
          padding: 16px 20px;
          overflow-y: auto;
        }
        .type-card {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 6px;
          padding: 16px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          text-align: left;
          transition: border-color 0.15s, background 0.15s;
        }
        .type-card:hover {
          border-color: var(--primary-color, #03a9f4);
          background: var(
            --secondary-background-color, #f5f5f5
          );
        }
        .card-icon {
          font-size: 22px;
          line-height: 1;
          color: var(--primary-color, #03a9f4);
          margin-bottom: 4px;
        }
        .card-name {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
        }
        .card-desc {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
          line-height: 1.4;
        }
      </style>
      <div class="overlay">
        <div class="dialog">
          <div class="dialog-header">
            <h2 class="dialog-title">Add Widget</h2>
            <button class="close-btn" title="Cancel">✕</button>
          </div>
          <div class="grid">${cards}</div>
        </div>
      </div>
    `;

    // innerHTML replaces all child nodes, dropping old listeners.
    // Re-wiring targets freshly created elements, so no stale
    // references remain.
    this.shadowRoot!
      .querySelector(".close-btn")!
      .addEventListener("click", () => this._close());

    // Clicking the backdrop (overlay) but not the dialog closes
    // the picker.
    this.shadowRoot!
      .querySelector(".overlay")!
      .addEventListener("click", (ev) => {
        if (ev.target === ev.currentTarget) this._close();
      });

    this.shadowRoot!
      .querySelectorAll<HTMLElement>(".type-card")
      .forEach((card) => {
        card.addEventListener("click", () => {
          const type = card.dataset["type"]!;
          this._pick(type);
        });
      });
  }

  /**
   * Return the HTML string for a single widget-type card.
   *
   * @param key  - Widget type key used as data-type attribute.
   * @param meta - Widget metadata (label, description, icon).
   * @returns Button element HTML string.
   */
  private _buildCard(key: string, meta: WidgetTypeMeta): string {
    // Falls back to stripped MDI name (e.g. "thermometer") for
    // icons without an ICON_FALLBACK entry. _escHtml() below
    // prevents injection from that raw text.
    const icon =
      ICON_FALLBACK[meta.icon] ?? meta.icon.replace("mdi:", "");
    const name = _escHtml(meta.label);
    const desc = _escHtml(meta.description);
    return `<button class="type-card" data-type="${_escHtml(key)}">
      <span class="card-icon">${_escHtml(icon)}</span>
      <span class="card-name">${name}</span>
      <span class="card-desc">${desc}</span>
    </button>`;
  }
}

/** Escape a string for safe insertion into an HTML attribute or
 *  text node. */
function _escHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

if (!customElements.get(PICKER_TAG)) {
  customElements.define(PICKER_TAG, EinkWidgetPicker);
}

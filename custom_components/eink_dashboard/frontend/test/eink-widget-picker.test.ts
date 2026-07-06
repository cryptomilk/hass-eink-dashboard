// Copyright 2026 Andreas Schneider
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { describe, it, expect } from "vitest";
import type { WidgetTypeMeta, Widget } from "../src/types/ha.js";

// Pull in the side-effecting registration, then grab the class via the
// registry so we can instantiate it without importing the class directly.
import "../src/eink-widget-picker.js";

// ── Test fixture ─────────────────────────────────────────────────

const MOCK_TYPES: Record<string, WidgetTypeMeta> = {
  heading: {
    label: "Heading",
    description: "Section header or title",
    icon: "mdi:format-header-1",
    defaults: { type: "heading" } as Widget,
  },
  separator: {
    label: "Separator",
    description: "Horizontal or vertical divider",
    icon: "mdi:minus",
    defaults: { type: "separator" } as Widget,
  },
  weather: {
    label: "Weather",
    description: "Forecast with conditions",
    icon: "mdi:weather-partly-cloudy",
    defaults: { type: "weather" } as Widget,
  },
};

function makePicker(): HTMLElement {
  const el = document.createElement("eink-widget-picker");
  document.body.appendChild(el);
  return el;
}

// ── Registration ─────────────────────────────────────────────────

describe("eink-widget-picker registration", () => {
  it("registers as a custom element", () => {
    // The import above triggers customElements.define().
    expect(customElements.get("eink-widget-picker")).toBeDefined();
  });
});

// ── open() renders a card per widget type ────────────────────────

describe("eink-widget-picker open()", () => {
  it("renders one card per widget type passed to open()", () => {
    // After open(), the shadow DOM should contain one button per type.
    const picker = makePicker();
    (picker as unknown as {
      open: (t: typeof MOCK_TYPES) => void;
    }).open(MOCK_TYPES);
    const cards = picker.shadowRoot!.querySelectorAll(".type-card");
    expect(cards.length).toBe(Object.keys(MOCK_TYPES).length);
  });

  it("each card carries its widget type in data-type", () => {
    // Clicking a card fires "type-selected" with the correct type key.
    const picker = makePicker();
    (picker as unknown as {
      open: (t: typeof MOCK_TYPES) => void;
    }).open(MOCK_TYPES);
    const cards = picker.shadowRoot!.querySelectorAll<HTMLElement>(
      ".type-card"
    );
    const types = Array.from(cards).map((c) => c.dataset["type"]);
    expect(types.sort()).toEqual(Object.keys(MOCK_TYPES).sort());
  });

  it("each card shows the widget label and description", () => {
    // Name and description text are visible to the user in the picker.
    const picker = makePicker();
    (picker as unknown as {
      open: (t: typeof MOCK_TYPES) => void;
    }).open(MOCK_TYPES);
    const root = picker.shadowRoot!;
    const names = Array.from(
      root.querySelectorAll(".card-name")
    ).map((el) => el.textContent?.trim());
    const descs = Array.from(
      root.querySelectorAll(".card-desc")
    ).map((el) => el.textContent?.trim());
    for (const meta of Object.values(MOCK_TYPES)) {
      expect(names).toContain(meta.label);
      expect(descs).toContain(meta.description);
    }
  });

  it("makes the overlay visible after open()", () => {
    // The overlay starts hidden; open() sets display: flex.
    const picker = makePicker();
    (picker as unknown as {
      open: (t: typeof MOCK_TYPES) => void;
    }).open(MOCK_TYPES);
    const overlay =
      picker.shadowRoot!.querySelector<HTMLElement>(".overlay")!;
    expect(overlay.style.display).toBe("flex");
  });
});

// ── Closing ──────────────────────────────────────────────────────

describe("eink-widget-picker close button", () => {
  it("fires 'closed' event when the X button is clicked", () => {
    // The close button must dismiss the dialog and signal the parent.
    const picker = makePicker();
    (picker as unknown as {
      open: (t: typeof MOCK_TYPES) => void;
    }).open(MOCK_TYPES);
    let fired = false;
    picker.addEventListener("closed", () => { fired = true; });
    picker.shadowRoot!
      .querySelector<HTMLButtonElement>(".close-btn")!
      .click();
    expect(fired).toBe(true);
  });

  it("hides the overlay after close", () => {
    // After dismissal, the overlay returns to display:none.
    const picker = makePicker();
    (picker as unknown as {
      open: (t: typeof MOCK_TYPES) => void;
    }).open(MOCK_TYPES);
    picker.shadowRoot!
      .querySelector<HTMLButtonElement>(".close-btn")!
      .click();
    const overlay =
      picker.shadowRoot!.querySelector<HTMLElement>(".overlay")!;
    expect(overlay.style.display).toBe("none");
  });
});

// ── Selection ────────────────────────────────────────────────────

describe("eink-widget-picker selection", () => {
  it(
    "fires 'type-selected' with the correct type when a card "
    + "is clicked",
    () => {
      // Clicking a card must fire 'type-selected' with that type's key.
      const picker = makePicker();
      (picker as unknown as {
        open: (t: typeof MOCK_TYPES) => void;
      }).open(MOCK_TYPES);
      let selected: string | undefined;
      picker.addEventListener(
        "type-selected",
        ((ev: CustomEvent<{ type: string }>) => {
          selected = ev.detail.type;
        }) as EventListener
      );
      const weatherCard = picker.shadowRoot!.querySelector<HTMLElement>(
        '.type-card[data-type="weather"]'
      )!;
      weatherCard.click();
      expect(selected).toBe("weather");
    }
  );

  it("closes the overlay after a card is picked", () => {
    // Selecting a widget type must also close the picker.
    const picker = makePicker();
    (picker as unknown as {
      open: (t: typeof MOCK_TYPES) => void;
    }).open(MOCK_TYPES);
    picker.shadowRoot!
      .querySelector<HTMLElement>('.type-card[data-type="heading"]')!
      .click();
    const overlay =
      picker.shadowRoot!.querySelector<HTMLElement>(".overlay")!;
    expect(overlay.style.display).toBe("none");
  });
});

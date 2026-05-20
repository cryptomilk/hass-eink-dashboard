import { describe, it, expect } from "vitest";
import type {
  HaFormSchema,
  EinkEditorElement,
  EinkWidgetPicker,
  Widget,
  StateCondition,
} from "../src/types/ha.js";
import {
  WIDGET_TYPES,
  SCHEMAS,
  LABELS,
  loadHaComponents,
  getSummary,
} from "../src/eink-dashboard-editor.js";
import "../src/eink-dashboard-editor.js";

const DISPLAY = { width: 800, height: 480 };

function flattenFields(schema: HaFormSchema[]): string[] {
  const names: string[] = [];
  for (const field of schema) {
    if (field.name) names.push(field.name);
    if (field.schema) names.push(...flattenFields(field.schema));
  }
  return names;
}

function findField(
  schema: HaFormSchema[],
  name: string,
): HaFormSchema | undefined {
  for (const field of schema) {
    if (field.name === name) return field;
    if (field.schema) {
      const found = findField(field.schema, name);
      if (found) return found;
    }
  }
  return undefined;
}

// ── WIDGET_TYPES ─────────────────────────────────────────────────

describe("WIDGET_TYPES", () => {
  const ALL_TYPES = [
    "heading",
    "separator",
    "weather",
    "tile",
    "entities",
    "entity",
    "device_battery",
    "waste_schedule",
    "sensor",
  ];

  it("has all 9 widget types", () => {
    expect(Object.keys(WIDGET_TYPES).sort()).toEqual(
      ALL_TYPES.sort()
    );
  });

  it("each entry has a label and defaults with matching type field", () => {
    for (const [key, meta] of Object.entries(WIDGET_TYPES)) {
      expect(typeof meta.label).toBe("string");
      expect(meta.label.length).toBeGreaterThan(0);
      expect(meta.defaults.type).toBe(key);
    }
  });

  it("each entry has a non-empty description string", () => {
    // Picker grid shows descriptions to help users choose the right
    // widget.
    for (const meta of Object.values(WIDGET_TYPES)) {
      expect(typeof meta.description).toBe("string");
      expect(meta.description.length).toBeGreaterThan(0);
    }
  });

  it("each entry has an icon in mdi: format", () => {
    // Picker grid uses these icons as visual indicators per widget type.
    for (const meta of Object.values(WIDGET_TYPES)) {
      expect(typeof meta.icon).toBe("string");
      expect(meta.icon.startsWith("mdi:")).toBe(true);
    }
  });
});

// ── SCHEMAS ──────────────────────────────────────────────────────

describe("SCHEMAS", () => {
  const ALL_TYPES = [
    "heading",
    "separator",
    "weather",
    "tile",
    "entities",
    "entity",
    "device_battery",
    "waste_schedule",
    "sensor",
  ];

  it("has a schema builder for all 9 widget types", () => {
    expect(Object.keys(SCHEMAS).sort()).toEqual(ALL_TYPES.sort());
  });

  it("weather entity field uses domain filter 'weather'", () => {
    const schema = SCHEMAS.weather(DISPLAY);
    const entityField = findField(schema, "entity");
    expect(entityField?.selector?.entity).toMatchObject({
      domain: "weather",
    });
  });

  it("position fields respect display dimensions as max", () => {
    const schema = SCHEMAS.separator(DISPLAY);
    const xField = findField(schema, "x");
    const yField = findField(schema, "y");
    expect(xField?.selector?.number?.max).toBe(DISPLAY.width);
    expect(yField?.selector?.number?.max).toBe(DISPLAY.height);
  });

  it("waste_schedule entity field uses domain filter 'sensor'", () => {
    // Waste schedule uses a single entity selector, not multiple.
    const entityField = findField(
      SCHEMAS.waste_schedule(DISPLAY), "entity"
    );
    expect(entityField?.selector?.entity).toMatchObject({
      domain: "sensor",
    });
  });
});

// ── LABELS ───────────────────────────────────────────────────────

describe("LABELS", () => {
  it("covers common field names", () => {
    for (const name of [
      "entity", "entities", "title",
      "x", "y", "w", "font_size", "color",
    ]) {
      expect(LABELS).toHaveProperty(name);
    }
  });

  it("covers separator-specific field names", () => {
    // direction, style, and length must have readable labels so the
    // editor form does not display raw field names to the user.
    for (const name of ["direction", "style", "length"]) {
      expect(LABELS).toHaveProperty(name);
      expect(typeof LABELS[name]).toBe("string");
      expect((LABELS[name] as string).length).toBeGreaterThan(0);
    }
  });
});

// ── loadHaComponents ─────────────────────────────────────────────

describe("loadHaComponents", () => {
  it("does not throw when HA elements are absent", async () => {
    await expect(loadHaComponents()).resolves.toBeUndefined();
  });
});

// ── getSummary ───────────────────────────────────────────────────

describe("getSummary", () => {
  it("returns entity for weather widget", () => {
    expect(
      getSummary({ type: "weather", entity: "weather.home" })
    ).toBe("weather.home");
  });

  it("returns '(no entity)' for weather widget with no entity", () => {
    expect(getSummary({ type: "weather" })).toBe("(no entity)");
  });

  it("returns static text for device_battery widget", () => {
    expect(getSummary({ type: "device_battery" })).toBe(
      "Device battery"
    );
  });

  it("returns direction+style summary for separator", () => {
    expect(getSummary({ type: "separator", y: 200 })).toBe(
      "Horizontal line at Y:200"
    );
  });

  it("returns vertical bar summary for separator", () => {
    expect(
      getSummary({
        type: "separator",
        direction: "vertical",
        style: "bar",
        y: 50,
      })
    ).toBe("Vertical bar at Y:50");
  });

  it("defaults to horizontal line at Y:0 for separator with no fields", () => {
    // direction and style both default to horizontal/line, y defaults to 0
    expect(getSummary({ type: "separator" })).toBe(
      "Horizontal line at Y:0"
    );
  });

  it("returns entity for entity widget", () => {
    expect(
      getSummary({ type: "entity", entity: "sensor.temperature" })
    ).toBe("sensor.temperature");
  });

  it("returns '(no entity)' for entity widget with no entity", () => {
    expect(getSummary({ type: "entity" })).toBe("(no entity)");
  });

  it("returns entity count for entities widget", () => {
    // Entity rows (strings) are counted; dividers and sections are not.
    expect(
      getSummary({
        type: "entities",
        entities: [
          "sensor.temperature",
          "sensor.humidity",
          { type: "divider" },
        ],
      })
    ).toBe("2 entities");
  });

  it("includes title in entities summary when present", () => {
    expect(
      getSummary({
        type: "entities",
        title: "Climate",
        entities: ["sensor.temperature"],
      })
    ).toBe("Climate — 1 entity");
  });

  it("returns entity for sensor widget", () => {
    expect(
      getSummary({ type: "sensor", entity: "sensor.temperature" })
    ).toBe("sensor.temperature");
  });

  it("returns '(no entity)' for sensor widget with no entity", () => {
    expect(getSummary({ type: "sensor", entity: "" })).toBe("(no entity)");
  });
});

// ── SCHEMAS form grouping ────────────────────────────────────────

function getExpandableSections(schema: HaFormSchema[]): HaFormSchema[] {
  return schema.filter((s) => s.type === "expandable");
}

describe("SCHEMAS form grouping", () => {
  const ALL_TYPES = Object.keys(SCHEMAS);

  it("every schema uses expandable sections", () => {
    // Each widget form must be split into at least one collapsible
    // group so fields are not dumped in a flat wall of inputs.
    for (const type of ALL_TYPES) {
      const schema = SCHEMAS[type](DISPLAY);
      const sections = getExpandableSections(schema);
      expect(sections.length).toBeGreaterThan(0);
    }
  });

  it("all expandable sections have flatten: true", () => {
    // flatten keeps child values flat in the widget data object so
    // existing save/load logic does not need to change.
    for (const type of ALL_TYPES) {
      const schema = SCHEMAS[type](DISPLAY);
      for (const section of getExpandableSections(schema)) {
        expect(section.flatten).toBe(true);
      }
    }
  });

  it("content section is expanded by default", () => {
    // The content section must be open by default so users see
    // meaningful fields immediately when they open a widget form.
    for (const type of ALL_TYPES) {
      const schema = SCHEMAS[type](DISPLAY);
      const sections = getExpandableSections(schema);
      const content = sections.find((s) => s.name === "content");
      expect(content?.expanded).toBe(true);
    }
  });

  it("identity and secondary sections do not start expanded", () => {
    // The identity section (label/description) and secondary sections
    // (layout, appearance) are collapsed by default to reduce visual
    // clutter — most widgets won't have a label set.
    for (const type of ALL_TYPES) {
      const schema = SCHEMAS[type](DISPLAY);
      const sections = getExpandableSections(schema);
      for (const section of sections) {
        if (section.name !== "content") {
          expect(section.expanded).toBeFalsy();
        }
      }
    }
  });

  it("every schema has an identity section with label and description", () => {
    // All widget types expose the editor-only label and description
    // fields so users can annotate any widget in the list.
    for (const type of ALL_TYPES) {
      const schema = SCHEMAS[type](DISPLAY);
      const identity = getExpandableSections(schema).find(
        (s) => s.name === "identity"
      );
      expect(identity).toBeDefined();
      const fields = flattenFields(identity!.schema!);
      expect(fields).toContain("label");
      expect(fields).toContain("description");
    }
  });

  it("all expandable sections have a title and mdi: icon", () => {
    // Every section must have a readable header label and a visual
    // icon so users can identify groups without expanding them.
    for (const type of ALL_TYPES) {
      const schema = SCHEMAS[type](DISPLAY);
      for (const section of getExpandableSections(schema)) {
        expect(typeof section.title).toBe("string");
        expect((section.title as string).length).toBeGreaterThan(0);
        expect(typeof section.icon).toBe("string");
        expect((section.icon as string).startsWith("mdi:")).toBe(true);
      }
    }
  });

  it("heading content section contains heading field", () => {
    // Content is the primary group for heading widgets: the heading
    // text belongs in content so it is visible by default.
    const schema = SCHEMAS.heading(DISPLAY);
    const content = getExpandableSections(schema).find(
      (s) => s.name === "content"
    )!;
    const fields = flattenFields(content.schema!);
    expect(fields).toContain("heading");
  });

  it("heading layout section contains x, y, w", () => {
    // Layout is the position group: x, y, and optional width override.
    const schema = SCHEMAS.heading(DISPLAY);
    const layout = getExpandableSections(schema).find(
      (s) => s.name === "layout"
    )!;
    const fields = flattenFields(layout.schema!);
    expect(fields).toContain("x");
    expect(fields).toContain("y");
    expect(fields).toContain("w");
  });

  it("weather appearance section contains font_size", () => {
    // Appearance is the visual styling group: weather uses font_size
    // to control rendered text size.
    const schema = SCHEMAS.weather(DISPLAY);
    const appearance = getExpandableSections(schema).find(
      (s) => s.name === "appearance"
    )!;
    const fields = flattenFields(appearance.schema!);
    expect(fields).toContain("font_size");
  });

  it("device_battery appearance section contains color", () => {
    // Appearance is the visual styling group: device_battery uses
    // color to control the text colour rendered on the dashboard.
    const schema = SCHEMAS.device_battery(DISPLAY);
    const appearance = getExpandableSections(schema).find(
      (s) => s.name === "appearance"
    )!;
    const fields = flattenFields(appearance.schema!);
    expect(fields).toContain("color");
  });

  it("device_battery content section contains layout selector", () => {
    // device_battery has a layout selector (icon/chip) in content.
    const schema = SCHEMAS.device_battery(DISPLAY);
    const content = getExpandableSections(schema).find(
      (s) => s.name === "content"
    );
    expect(content).toBeDefined();
    const fields = flattenFields(content!.schema);
    expect(fields).toContain("layout");
  });

  it("separator has no appearance section", () => {
    // separator has no font_size or color fields, so no appearance
    // group is needed.
    const schema = SCHEMAS.separator(DISPLAY);
    const appearance = getExpandableSections(schema).find(
      (s) => s.name === "appearance"
    );
    expect(appearance).toBeUndefined();
  });

  it("entities schema puts entities field inside content", () => {
    // Entities are content, not layout or appearance.
    const schema = SCHEMAS.entities(DISPLAY);
    const content = getExpandableSections(schema).find(
      (s) => s.name === "content"
    )!;
    expect(content).toBeDefined();
    const fields = flattenFields(content.schema!);
    expect(fields).toContain("entities");
  });

  it("waste_schedule entity field is inside content section", () => {
    // The single entity selector for waste_schedule belongs in
    // content so it is visible by default when the form opens.
    const schema = SCHEMAS.waste_schedule(DISPLAY);
    const content = getExpandableSections(schema).find(
      (s) => s.name === "content"
    )!;
    expect(content).toBeDefined();
    const fields = flattenFields(content.schema!);
    expect(fields).toContain("entity");
  });

  it("weather entity field is inside content section", () => {
    // The primary entity selector for weather belongs in content so
    // it is visible by default when the form opens.
    const schema = SCHEMAS.weather(DISPLAY);
    const content = getExpandableSections(schema).find(
      (s) => s.name === "content"
    )!;
    const fields = flattenFields(content.schema!);
    expect(fields).toContain("entity");
  });
});

// ── add-widget integration ───────────────────────────────────────

describe("add-widget integration", () => {
  it(
    "appends a widget when a type is selected from the picker",
    async () => {
      // jsdom does not implement scrollIntoView; stub it so the
      // production call in _onTypeSelected does not throw.
      HTMLElement.prototype.scrollIntoView = () => {};
      // Exercises: add-btn click -> picker open ->
      // type-selected -> widget-change event with new widget.
      const editor = document.createElement(
        "eink-dashboard-editor"
      ) as EinkEditorElement;
      document.body.appendChild(editor);
      editor.setDisplay({ width: 800, height: 480 });
      editor.setWidgets([]);

      // Wait for async _buildShell() to complete.
      await new Promise((r) => setTimeout(r, 0));

      const addBtn = editor.shadowRoot!
        .querySelector<HTMLButtonElement>(".add-btn");
      expect(addBtn).toBeTruthy();
      addBtn!.click();

      // The picker should be created and appended to the shadow root.
      const picker = editor.shadowRoot!
        .querySelector<EinkWidgetPicker>("eink-widget-picker");
      expect(picker).toBeTruthy();

      // Listen for the widget-change event that fires when a widget
      // is appended.
      let received: Widget[] | undefined;
      editor.addEventListener(
        "widget-change",
        ((ev: CustomEvent<{ widgets: Widget[] }>) => {
          received = ev.detail.widgets;
        }) as EventListener
      );

      // Click the "heading" type card in the picker's shadow DOM.
      const card = picker!.shadowRoot!
        .querySelector<HTMLElement>(
          '.type-card[data-type="heading"]'
        );
      expect(card).toBeTruthy();
      card!.click();

      expect(received).toBeDefined();
      expect(received!.length).toBe(1);
      expect(received![0].type).toBe("heading");
    }
  );
});

// ── Visibility field types ────────────────────────────────────────

describe("Visibility field", () => {
  it("Widget type accepts a visibility array of conditions", () => {
    // Compile-time type check: a widget with a visibility field must
    // satisfy the Widget union type.
    const condition: StateCondition = {
      condition: "state",
      entity: "sensor.test",
      state: "on",
    };
    const widget: Widget = {
      type: "separator",
      visibility: [condition],
    };
    expect(widget.visibility).toHaveLength(1);
    expect(
      (widget.visibility![0] as StateCondition).entity
    ).toBe("sensor.test");
  });

  it("Widget type accepts visibility: undefined", () => {
    // Verify that omitting visibility is valid.
    const widget: Widget = { type: "separator" };
    expect(widget.visibility).toBeUndefined();
  });
});

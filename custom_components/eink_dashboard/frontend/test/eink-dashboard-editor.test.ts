import { describe, it, expect } from "vitest";
import type { HaFormSchema } from "../src/types/ha.js";
import {
  WIDGET_TYPES,
  SCHEMAS,
  LABELS,
  loadHaComponents,
  getSummary,
} from "../src/eink-dashboard-editor.js";

const DISPLAY = { width: 800, height: 480 };

function flattenFields(schema: HaFormSchema[]): string[] {
  const names: string[] = [];
  for (const field of schema) {
    if (field.name) names.push(field.name);
    if (field.schema) names.push(...flattenFields(field.schema));
  }
  return names;
}

function findField(schema: HaFormSchema[], name: string): HaFormSchema | undefined {
  for (const field of schema) {
    if (field.name === name) return field;
    if (field.schema) {
      const found = findField(field.schema, name);
      if (found) return found;
    }
  }
  return undefined;
}

// ── WIDGET_TYPES ──────────────────────────────────────────────────────────────

describe("WIDGET_TYPES", () => {
  const ALL_TYPES = ["text", "separator", "weather", "sensor_rows", "device_battery", "status_icons", "waste_schedule"];

  it("has all 7 widget types", () => {
    expect(Object.keys(WIDGET_TYPES).sort()).toEqual(ALL_TYPES.sort());
  });

  it("each entry has a label and defaults with matching type field", () => {
    for (const [key, meta] of Object.entries(WIDGET_TYPES)) {
      expect(typeof meta.label).toBe("string");
      expect(meta.label.length).toBeGreaterThan(0);
      expect(meta.defaults.type).toBe(key);
    }
  });
});

// ── SCHEMAS ───────────────────────────────────────────────────────────────────

describe("SCHEMAS", () => {
  it("has a schema builder for all 7 widget types", () => {
    const ALL_TYPES = ["text", "separator", "weather", "sensor_rows", "device_battery", "status_icons", "waste_schedule"];
    expect(Object.keys(SCHEMAS).sort()).toEqual(ALL_TYPES.sort());
  });

  it("text schema has text, x, y, font_size, color, align fields", () => {
    const fields = flattenFields(SCHEMAS.text(DISPLAY));
    expect(fields).toContain("text");
    expect(fields).toContain("x");
    expect(fields).toContain("y");
    expect(fields).toContain("font_size");
    expect(fields).toContain("color");
    expect(fields).toContain("align");
  });

  it("weather entity field uses domain filter 'weather'", () => {
    const schema = SCHEMAS.weather(DISPLAY);
    const entityField = findField(schema, "entity");
    expect(entityField?.selector?.entity).toMatchObject({ domain: "weather" });
  });

  it("position fields respect display dimensions as max", () => {
    const schema = SCHEMAS.text(DISPLAY);
    const xField = findField(schema, "x");
    const yField = findField(schema, "y");
    expect(xField?.selector?.number?.max).toBe(DISPLAY.width);
    expect(yField?.selector?.number?.max).toBe(DISPLAY.height);
  });

  it("sensor_rows entities field has multiple: true", () => {
    const schema = SCHEMAS.sensor_rows(DISPLAY);
    const entitiesField = findField(schema, "entities");
    expect(entitiesField?.selector?.entity?.multiple).toBe(true);
  });

  it("status_icons entities field has multiple: true", () => {
    const entitiesField = findField(SCHEMAS.status_icons(DISPLAY), "entities");
    expect(entitiesField?.selector?.entity?.multiple).toBe(true);
  });

  it("waste_schedule entities field has multiple: true", () => {
    const entitiesField = findField(SCHEMAS.waste_schedule(DISPLAY), "entities");
    expect(entitiesField?.selector?.entity?.multiple).toBe(true);
  });

});

// ── LABELS ────────────────────────────────────────────────────────────────────

describe("LABELS", () => {
  it("covers common field names", () => {
    for (const name of ["text", "entity", "entities", "title", "x", "y", "w", "font_size", "color", "align"]) {
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

// ── loadHaComponents ──────────────────────────────────────────────────────────

describe("loadHaComponents", () => {
  it("does not throw when HA elements are absent", async () => {
    await expect(loadHaComponents()).resolves.toBeUndefined();
  });
});

// ── getSummary ────────────────────────────────────────────────────────────────

describe("getSummary", () => {
  it("returns text content for text widget", () => {
    expect(getSummary({ type: "text", text: "Hello" })).toBe("Hello");
  });

  it("truncates long text at 30 chars with ellipsis", () => {
    const long = "A".repeat(35);
    const result = getSummary({ type: "text", text: long });
    expect(result).toBe("A".repeat(30) + "…");
  });

  it("returns '(empty)' for text widget with empty string", () => {
    expect(getSummary({ type: "text", text: "" })).toBe("(empty)");
  });

  it("returns entity for weather widget", () => {
    expect(getSummary({ type: "weather", entity: "weather.home" })).toBe("weather.home");
  });

  it("returns '(no entity)' for weather widget with no entity", () => {
    expect(getSummary({ type: "weather" })).toBe("(no entity)");
  });

  it("returns static text for device_battery widget", () => {
    expect(getSummary({ type: "device_battery" })).toBe("Device battery");
  });

  it("returns entity count for sensor_rows", () => {
    expect(getSummary({ type: "sensor_rows", entities: ["a", "b"] })).toBe("2 entities");
  });

  it("includes title in sensor_rows summary when present", () => {
    expect(getSummary({ type: "sensor_rows", title: "Temps", entities: ["a"] })).toBe("Temps — 1 entity");
  });

  it("uses singular 'entity' for count of 1", () => {
    expect(getSummary({ type: "status_icons", entities: ["x"] })).toBe("1 entity");
  });

  it("returns direction+style summary for separator", () => {
    expect(getSummary({ type: "separator", y: 200 })).toBe("h line @200");
  });

  it("returns vertical bar summary for separator", () => {
    expect(getSummary({ type: "separator", direction: "vertical", style: "bar", y: 50 })).toBe("v bar @50");
  });

  it("defaults to h line @0 for separator with no fields", () => {
    // direction and style both default to h/line, y defaults to 0
    expect(getSummary({ type: "separator" })).toBe("h line @0");
  });
});

import { describe, it, expect } from "vitest";
import {
  buildHeaderText,
  shouldShowCopyUrl,
} from "../src/eink-dashboard-card.js";

describe("buildHeaderText", () => {
  it("returns the device name", () => {
    // Header text is the device name when non-empty.
    expect(buildHeaderText({ name: "My Kindle" })).toBe("My Kindle");
  });

  it("falls back to default when name is empty", () => {
    // An empty name produces the "E-Ink Dashboard" fallback.
    expect(buildHeaderText({ name: "" })).toBe("E-Ink Dashboard");
  });
});

describe("shouldShowCopyUrl", () => {
  it("returns true for kindle_pw4", () => expect(shouldShowCopyUrl("kindle_pw4", false)).toBe(true));
  it("returns true for kindle_4 regardless of webhooks", () => expect(shouldShowCopyUrl("kindle_4", true)).toBe(true));
  it("returns true for kindle_oasis regardless of webhooks", () => expect(shouldShowCopyUrl("kindle_oasis", true)).toBe(true));
  it("returns true for custom without webhooks", () => expect(shouldShowCopyUrl("custom", false)).toBe(true));
  it("returns false for custom with webhooks", () => expect(shouldShowCopyUrl("custom", true)).toBe(false));
  it("returns false for trmnl_og", () => expect(shouldShowCopyUrl("trmnl_og", false)).toBe(false));
  it("returns false for trmnl_x", () => expect(shouldShowCopyUrl("trmnl_x", true)).toBe(false));
});

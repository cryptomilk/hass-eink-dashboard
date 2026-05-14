import { describe, it, expect } from "vitest";
import {
  snap,
  buildHeaderText,
  shouldShowCopyUrl,
} from "../src/eink-dashboard-card.js";

describe("snap", () => {
  it("snaps 0 to 0", () => expect(snap(0)).toBe(0));
  it("snaps 3 down to 0", () => expect(snap(3)).toBe(0));
  it("snaps 4 up to 8", () => expect(snap(4)).toBe(8));
  it("snaps 12 to 16 (rounds half up)", () => expect(snap(12)).toBe(16));
  it("snaps 12.1 to 16", () => expect(snap(12.1)).toBe(16));
  it("snaps 16 to 16", () => expect(snap(16)).toBe(16));
  it("snaps negative -4 near zero", () => expect(Math.abs(snap(-4))).toBe(0));
  it("snaps negative -5 to -8", () => expect(snap(-5)).toBe(-8));
});

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

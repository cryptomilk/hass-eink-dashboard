import { describe, it, expect } from "vitest";
import {
  snap,
  buildHeaderText,
  shouldShowCopyUrl,
  diagScaleFontSize,
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

describe("diagScaleFontSize", () => {
  it("SE drag right+down increases font_size", () => {
    // Dragging SE corner outward (positive dx, dy) makes the widget
    // larger so the font_size should increase.
    const result = diagScaleFontSize("se", 10, 10, 32, 100, 100, 8, 72);
    expect(result).toBeGreaterThan(32);
  });

  it("NW drag right+down decreases font_size", () => {
    // Dragging NW corner toward the centre (positive dx, dy)
    // shrinks the widget so the font_size should decrease.
    const result = diagScaleFontSize("nw", 10, 10, 32, 100, 100, 8, 72);
    expect(result).toBeLessThan(32);
  });

  it("zero delta returns original font_size", () => {
    // No movement should produce no change.
    const result = diagScaleFontSize("se", 0, 0, 32, 100, 100, 8, 72);
    expect(result).toBe(32);
  });

  it("clamps result to maxFs on large outward drag", () => {
    // Very large positive SE drag expands the widget far beyond maxFs.
    const big = diagScaleFontSize("se", 9999, 9999, 32, 100, 100, 8, 72);
    expect(big).toBe(72);
  });

  it("clamps result to minFs when drag shrinks widget near zero", () => {
    // dx/dy ≈ -90 on a 100×100 widget makes the new diagonal ≈14px
    // vs the start diagonal ≈141px, giving a ratio of ~0.1 which
    // rounds to 3 for startFs=32 — well below minFs=8.
    const small = diagScaleFontSize("se", -90, -90, 32, 100, 100, 8, 72);
    expect(small).toBe(8);
  });

  it("zero-size widget returns original font_size without crash", () => {
    // Guard against division by zero when the widget has zero dimensions.
    const result = diagScaleFontSize("se", 10, 10, 32, 0, 0, 8, 72);
    expect(result).toBe(32);
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

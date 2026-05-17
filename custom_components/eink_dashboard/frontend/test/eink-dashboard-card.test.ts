import { describe, it, expect } from "vitest";
import {
  snap,
  snapToEdges,
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

describe("snapToEdges", () => {
  it("returns grid snap when there are no targets", () => {
    // With nothing to snap to, each axis falls back to snap().
    expect(snapToEdges({ x: 13, y: 13, w: 100, h: 50 }, []))
      .toEqual({ x: 16, y: 16 });
  });

  it("snaps left edge to target left edge (alignment)", () => {
    // Candidate left=105, target left=100 — distance 5 within threshold.
    const result = snapToEdges(
      { x: 105, y: 0, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 60, h: 40 }],
    );
    expect(result.x).toBe(100);
  });

  it("snaps left edge to target right edge (abutment)", () => {
    // Candidate left=147, target right=150 — distance 3 within threshold.
    const result = snapToEdges(
      { x: 147, y: 0, w: 80, h: 40 },
      [{ x: 50, y: 200, w: 100, h: 40 }],
    );
    expect(result.x).toBe(150);
  });

  it("snaps right edge to target left edge (abutment)", () => {
    // Candidate right=190, target left=200 — distance 10 within threshold.
    // Candidate shifts right by 10 so right=200, meaning x=100.
    const result = snapToEdges(
      { x: 90, y: 0, w: 100, h: 40 },
      [{ x: 200, y: 200, w: 60, h: 40 }],
    );
    expect(result.x).toBe(100);
  });

  it("snaps right edge to target right edge (alignment)", () => {
    // Candidate right=195, target right=200 — distance 5 within threshold.
    // Candidate shifts right by 5 so right=200, meaning x=100.
    const result = snapToEdges(
      { x: 95, y: 0, w: 100, h: 40 },
      [{ x: 50, y: 200, w: 150, h: 40 }],
    );
    expect(result.x).toBe(100);
  });

  it("snaps Y axis independently of X", () => {
    // X: nearest edge is target left=300, distance=250 — beyond
    // threshold, falls back to grid. Y: top-to-top distance=5,
    // within threshold — snaps to 200.
    const result = snapToEdges(
      { x: 50, y: 195, w: 80, h: 60 },
      [{ x: 300, y: 200, w: 80, h: 60 }],
    );
    expect(result.x).toBe(snap(50)); // grid fallback
    expect(result.y).toBe(200);      // edge snap
  });

  it("falls back to grid snap when beyond threshold", () => {
    // All edges more than 12px away — grid snap applies.
    const result = snapToEdges(
      { x: 170, y: 80, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 50, h: 40 }],
    );
    expect(result.x).toBe(snap(170));
    expect(result.y).toBe(snap(80));
  });

  it("picks the closest edge when multiple targets overlap", () => {
    // Target A right=100, target B left=103. Candidate left=101.
    // Distance to A=1, distance to B=2 — snaps to A.
    const result = snapToEdges(
      { x: 101, y: 0, w: 80, h: 40 },
      [
        { x: 20, y: 200, w: 80, h: 40 },  // right edge = 100
        { x: 103, y: 200, w: 60, h: 40 }, // left edge = 103
      ],
    );
    expect(result.x).toBe(100);
  });

  it("respects a custom threshold parameter", () => {
    // Distance 5; with threshold=4 it should NOT snap.
    const result = snapToEdges(
      { x: 105, y: 0, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 60, h: 40 }],
      4,
    );
    expect(result.x).toBe(snap(105));
  });

  it("snaps when candidate edge exactly matches target edge", () => {
    // Distance 0 — no shift needed; result equals the raw position.
    const result = snapToEdges(
      { x: 100, y: 0, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 60, h: 40 }],
    );
    expect(result.x).toBe(100);
  });

  it("handles zero-dimension candidate (wrapper absent from DOM)", () => {
    // w=0/h=0 is what the call site produces when dragWrapper is
    // null. All four X pairs collapse to two distinct edges (left
    // == right), but the function must still return a valid result.
    const result = snapToEdges(
      { x: 104, y: 0, w: 0, h: 0 },
      [{ x: 100, y: 200, w: 60, h: 40 }],
    );
    // Left=104 is 4px from target left=100 — within threshold.
    expect(result.x).toBe(100);
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

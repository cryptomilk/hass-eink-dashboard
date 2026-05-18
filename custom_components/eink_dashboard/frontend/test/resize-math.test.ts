import { describe, it, expect } from "vitest";
import {
  snap,
  snapToEdges,
  applyEdgeResize,
  applyCornerResize,
} from "../src/resize-math.js";

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

describe("snapToEdges", () => {
  it("returns grid snap when there are no targets", () => {
    // With nothing to snap to, each axis falls back to snap() and
    // no guide lines are produced.
    const result = snapToEdges(
      { x: 13, y: 13, w: 100, h: 50 }, [],
    );
    expect(result.x).toBe(16);
    expect(result.y).toBe(16);
    expect(result.guideX).toBeUndefined();
    expect(result.guideY).toBeUndefined();
  });

  it("snaps left edge to target left edge (alignment)", () => {
    // Candidate left=105, target left=100 — distance 5 within threshold.
    // Guide line appears at x=100 (the matched target edge).
    const result = snapToEdges(
      { x: 105, y: 0, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 60, h: 40 }],
    );
    expect(result.x).toBe(100);
    expect(result.guideX).toBe(100);
    expect(result.guideY).toBeUndefined();
  });

  it("snaps left edge to target right edge (abutment)", () => {
    // Candidate left=147, target right=150 — distance 3 within threshold.
    // Guide line appears at x=150 (the matched target edge).
    const result = snapToEdges(
      { x: 147, y: 0, w: 80, h: 40 },
      [{ x: 50, y: 200, w: 100, h: 40 }],
    );
    expect(result.x).toBe(150);
    expect(result.guideX).toBe(150);
    expect(result.guideY).toBeUndefined();
  });

  it("snaps right edge to target left edge (abutment)", () => {
    // Candidate right=190, target left=200 — distance 10 within threshold.
    // Candidate shifts right by 10 so right=200, meaning x=100.
    // Guide line at x=200 (the target left edge both edges align on).
    const result = snapToEdges(
      { x: 90, y: 0, w: 100, h: 40 },
      [{ x: 200, y: 200, w: 60, h: 40 }],
    );
    expect(result.x).toBe(100);
    expect(result.guideX).toBe(200);
    expect(result.guideY).toBeUndefined();
  });

  it("snaps right edge to target right edge (alignment)", () => {
    // Candidate right=195, target right=200 — distance 5 within threshold.
    // Candidate shifts right by 5 so right=200, meaning x=100.
    // Guide line at x=200.
    const result = snapToEdges(
      { x: 95, y: 0, w: 100, h: 40 },
      [{ x: 50, y: 200, w: 150, h: 40 }],
    );
    expect(result.x).toBe(100);
    expect(result.guideX).toBe(200);
    expect(result.guideY).toBeUndefined();
  });

  it("snaps Y axis independently of X", () => {
    // X: nearest edge is target left=300, distance=250 — beyond
    // threshold, falls back to grid (guideX undefined). Y: top-to-top
    // distance=5, within threshold — snaps to 200 (guideY=200).
    const result = snapToEdges(
      { x: 50, y: 195, w: 80, h: 60 },
      [{ x: 300, y: 200, w: 80, h: 60 }],
    );
    expect(result.x).toBe(snap(50));   // grid fallback
    expect(result.y).toBe(200);        // edge snap
    expect(result.guideX).toBeUndefined();
    expect(result.guideY).toBe(200);
  });

  it("falls back to grid snap when beyond threshold", () => {
    // All edges more than 12px away — grid snap applies, no guides.
    const result = snapToEdges(
      { x: 170, y: 80, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 50, h: 40 }],
    );
    expect(result.x).toBe(snap(170));
    expect(result.y).toBe(snap(80));
    expect(result.guideX).toBeUndefined();
    expect(result.guideY).toBeUndefined();
  });

  it("picks the closest edge when multiple targets overlap", () => {
    // Target A right=100, target B left=103. Candidate left=101.
    // Distance to A=1, distance to B=2 — snaps to A, guide at x=100.
    const result = snapToEdges(
      { x: 101, y: 0, w: 80, h: 40 },
      [
        { x: 20, y: 200, w: 80, h: 40 },  // right edge = 100
        { x: 103, y: 200, w: 60, h: 40 }, // left edge = 103
      ],
    );
    expect(result.x).toBe(100);
    expect(result.guideX).toBe(100);
  });

  it("respects a custom threshold parameter", () => {
    // Distance 5; with threshold=4 it should NOT snap, no guide.
    const result = snapToEdges(
      { x: 105, y: 0, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 60, h: 40 }],
      4,
    );
    expect(result.x).toBe(snap(105));
    expect(result.guideX).toBeUndefined();
  });

  it("snaps when candidate edge exactly matches target edge", () => {
    // Distance 0 — no shift needed; guide appears at x=100.
    const result = snapToEdges(
      { x: 100, y: 0, w: 80, h: 40 },
      [{ x: 100, y: 200, w: 60, h: 40 }],
    );
    expect(result.x).toBe(100);
    expect(result.guideX).toBe(100);
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
    expect(result.guideX).toBe(100);
  });
});

describe("applyEdgeResize", () => {
  // "e" handle — only the right edge moves; x is absent from the result.

  it("e: expanding drag increases width", () => {
    // dx=32 moves the right edge right; width grows.
    const r = applyEdgeResize("e", 32, 24, 200, 800, 20);
    expect(r.x).toBeUndefined();
    expect(r.w).toBe(232);
  });

  it("e: clamps width at displayWidth", () => {
    // Right edge cannot exceed the display boundary.
    const r = applyEdgeResize("e", 9999, 24, 200, 800, 20);
    expect(r.w).toBe(snap(800 - 24)); // 776
  });

  it("e: clamps width at minDim", () => {
    // Shrinking past minimum clamps to minDim.
    const r = applyEdgeResize("e", -9999, 24, 200, 800, 20);
    expect(r.w).toBe(snap(20));
  });

  it("e: result snaps to grid", () => {
    // dx=3 (raw newRight = 24+200+3 = 227) snaps to 224 (nearest 8).
    const r = applyEdgeResize("e", 3, 24, 200, 800, 20);
    expect(r.w % 8).toBe(0);
  });

  // "w" handle — left edge moves; x and w both change.

  it("w: dragging right narrows widget and moves x forward", () => {
    // dx=16 shifts left edge right: startRight=224, newX=snap(40)=40,
    // w=snap(184)=184.
    const r = applyEdgeResize("w", 16, 24, 200, 800, 20);
    expect(r.x).toBe(40);
    expect(r.w).toBe(184);
  });

  it("w: clamps x at 0", () => {
    // Dragging far left cannot move x below 0.
    const r = applyEdgeResize("w", -9999, 24, 200, 800, 20);
    expect(r.x).toBe(0);
  });

  it("w: clamps to keep minDim between left and fixed right edge", () => {
    // Max newX = startRight(224) - minDim(20) = 204; snap(204) = 208.
    // w = startRight - newX = 224 - 208 = 16 (not re-snapped so the
    // fixed right edge at 224 doesn't jitter).
    const r = applyEdgeResize("w", 9999, 24, 200, 800, 20);
    expect(r.x).toBe(208);
    expect(r.w).toBe(16);
  });

  it("w: result snaps to grid", () => {
    // Both x and w must be multiples of GRID=8.
    const r = applyEdgeResize("w", 5, 24, 200, 800, 20);
    expect((r.x ?? 0) % 8).toBe(0);
    expect(r.w % 8).toBe(0);
  });
});

describe("applyCornerResize", () => {
  const DW = 800;
  const DH = 600;

  it("se: expanding drag increases width and height", () => {
    const r = applyCornerResize(
      "se", 16, 16, 24, 0, 200, 100, 20, DW, DH,
    );
    expect(r.x).toBeUndefined();
    expect(r.y).toBeUndefined();
    expect(r.w).toBe(216);
    expect(r.h).toBe(120);
  });

  it("se: clamps to minDim on inward drag", () => {
    // Shrinking past minimum clamps to minDim.
    const r = applyCornerResize(
      "se", -9999, -9999, 24, 0, 200, 100, 20, DW, DH,
    );
    expect(r.w).toBe(snap(20));
    expect(r.h).toBe(snap(20));
  });

  it("se: clamps width at display right boundary", () => {
    // Widget at x=24 cannot grow past displayWidth=800; max w=snap(776).
    const r = applyCornerResize(
      "se", 9999, 0, 24, 0, 200, 100, 20, DW, DH,
    );
    expect(r.w).toBe(snap(DW - 24));
  });

  it("se: clamps height at display bottom boundary", () => {
    // Widget at y=0 cannot grow past displayHeight=600.
    const r = applyCornerResize(
      "se", 0, 9999, 24, 0, 200, 100, 20, DW, DH,
    );
    expect(r.h).toBe(snap(DH));
  });

  // ne — right+top edges move; y changes but x is absent.
  // The top edge is clamped and derived h = startBottom - newY
  // (no re-snap), so the bottom edge stays fixed at startBottom.

  it("ne: dragging up (dy<0) moves top edge up and grows height", () => {
    // startBottom=140; newY=snap(max(0,min(120,40-16)))=snap(24)=24;
    // h = 140-24 = 116.
    const r = applyCornerResize(
      "ne", 16, -16, 24, 40, 200, 100, 20, DW, DH,
    );
    expect(r.x).toBeUndefined();
    expect(r.y).toBe(24);
    expect(r.w).toBe(216);
    expect(r.h).toBe(116);
  });

  it("ne: y clamps at 0 on extreme upward drag", () => {
    // Top edge cannot move above display origin.
    const r = applyCornerResize(
      "ne", 0, -9999, 24, 40, 200, 100, 20, DW, DH,
    );
    expect(r.y).toBe(0);
  });

  it("ne: dragging down (dy>0) moves top edge down and shrinks height", () => {
    // newY=snap(max(0,min(120,40+16)))=snap(56)=56; h=140-56=84.
    const r = applyCornerResize(
      "ne", 0, 16, 24, 40, 200, 100, 20, DW, DH,
    );
    expect(r.y).toBe(56);
    expect(r.h).toBe(84);
  });

  // sw — left+bottom edges move; x changes but y is absent.

  it("sw: dragging left (dx<0) expands width and moves x left", () => {
    // newX=snap(max(0,min(204,24-16)))=snap(8)=8;
    // w=startRight(224)-8=216.
    const r = applyCornerResize(
      "sw", -16, 16, 24, 40, 200, 100, 20, DW, DH,
    );
    expect(r.y).toBeUndefined();
    expect(r.x).toBe(8);
    expect(r.w).toBe(216);
    expect(r.h).toBe(120);
  });

  it("sw: clamps x at 0", () => {
    // Left edge cannot move past display origin.
    const r = applyCornerResize(
      "sw", -9999, 0, 24, 40, 200, 100, 20, DW, DH,
    );
    expect(r.x).toBe(0);
  });

  // nw — left+top edges move; both x and y change.

  it("nw: dragging inward shrinks width and height, moves x and y", () => {
    // newX=snap(40)=40; newY=snap(56)=56;
    // w=startRight(224)-40=184; h=startBottom(140)-56=84.
    const r = applyCornerResize(
      "nw", 16, 16, 24, 40, 200, 100, 20, DW, DH,
    );
    expect(r.x).toBe(40);
    expect(r.y).toBe(56);
    expect(r.w).toBe(184);
    expect(r.h).toBe(84);
  });

  it("moving edges snap to grid; derived dimensions hold the fixed edge", () => {
    // Moving edges (x, y, and the se-corner w/h) are grid-snapped.
    // Derived dimensions (w or h computed by startRight/Bottom - snap(x/y))
    // are not re-snapped, so the fixed opposite edge stays put.
    // startRight=224, startBottom=140.
    const sw = applyCornerResize("sw", 5, 5, 24, 40, 200, 100, 20, DW, DH);
    expect((sw.x ?? 24) % 8).toBe(0);
    expect((sw.x ?? 24) + sw.w).toBe(224);
    const nw = applyCornerResize("nw", 5, 5, 24, 40, 200, 100, 20, DW, DH);
    expect((nw.x ?? 24) % 8).toBe(0);
    expect((nw.y ?? 40) % 8).toBe(0);
    expect((nw.x ?? 24) + nw.w).toBe(224);
    expect((nw.y ?? 40) + nw.h).toBe(140);
    const ne = applyCornerResize("ne", 5, 5, 24, 40, 200, 100, 20, DW, DH);
    expect((ne.y ?? 40) % 8).toBe(0);
    expect(ne.w % 8).toBe(0);
    expect((ne.y ?? 40) + ne.h).toBe(140);
    const se = applyCornerResize("se", 5, 5, 24, 40, 200, 100, 20, DW, DH);
    expect(se.w % 8).toBe(0);
    expect(se.h % 8).toBe(0);
  });
});

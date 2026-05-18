// Pure resize math shared between the Lovelace card and the design tool.

import type { WidgetBounds } from "./types/ha.js";

const GRID = 8;
// Pre-snap floor; effective minimum after snap is 24.
export const MIN_RESIZE_DIM = 20;
const EDGE_SNAP_THRESHOLD = 12;

// ── Grid snap ────────────────────────────────────────────────────────────────

/** Round v to the nearest GRID-pixel boundary. */
export function snap(v: number): number { return Math.round(v / GRID) * GRID; }

// ── Edge-snap across widget bounds ───────────────────────────────────────────

/**
 * Snap a candidate widget to the nearest edge of any target
 * widget, per axis independently.
 *
 * For each axis the function checks all 4 edge-pair combinations
 * (left↔left, left↔right, right↔left, right↔right for X; same
 * for top/bottom on Y).  If the closest match on an axis is within
 * `threshold` pixels the candidate is shifted so those edges align.
 * When no target edge is within threshold the axis falls back to
 * grid snap.
 *
 * @param candidate - Bounding box of the widget being dragged, at
 *   the raw (unsnapped) candidate position.
 * @param targets - Bounding boxes of all other widgets.
 * @param threshold - Maximum pixel distance to trigger a snap.
 * @returns Snapped { x, y } position for the candidate widget.
 */
export function snapToEdges(
  candidate: WidgetBounds,
  targets: WidgetBounds[],
  threshold: number = EDGE_SNAP_THRESHOLD,
): { x: number; y: number } {
  const cL = candidate.x;
  const cR = candidate.x + candidate.w;
  const cT = candidate.y;
  const cB = candidate.y + candidate.h;

  // Sentinel: anything within threshold beats the initial value.
  let bestDx = threshold + 1;
  let snapX = snap(candidate.x);
  let bestDy = threshold + 1;
  let snapY = snap(candidate.y);

  for (const t of targets) {
    const tL = t.x;
    const tR = t.x + t.w;
    const tT = t.y;
    const tB = t.y + t.h;

    // X-axis: check all 4 candidate-edge / target-edge pairs.
    for (const [ce, te] of [
      [cL, tL], [cL, tR], [cR, tL], [cR, tR],
    ] as [number, number][]) {
      const dist = Math.abs(ce - te);
      if (dist < bestDx) {
        bestDx = dist;
        snapX = candidate.x + (te - ce);
      }
    }

    // Y-axis: check all 4 candidate-edge / target-edge pairs.
    for (const [ce, te] of [
      [cT, tT], [cT, tB], [cB, tT], [cB, tB],
    ] as [number, number][]) {
      const dist = Math.abs(ce - te);
      if (dist < bestDy) {
        bestDy = dist;
        snapY = candidate.y + (te - ce);
      }
    }
  }

  return { x: snapX, y: snapY };
}

// ── Handle resize math ────────────────────────────────────────────────────────

/**
 * Compute the new position/size after a left or right edge drag.
 *
 * The left ("w") handle moves the left edge and adjusts width
 * inversely; the right ("e") handle moves only the right edge.
 * Both clamp so the widget stays within [0, displayWidth] and
 * never shrinks below minDim.
 *
 * @param handle - "w" (left edge) or "e" (right edge).
 * @param dx - Horizontal drag delta in display pixels.
 * @param startX - Widget x at drag start.
 * @param startW - Widget width at drag start.
 * @param displayWidth - Dashboard display width (right boundary).
 * @param minDim - Minimum allowed dimension in pixels.
 * @returns New { x?, w } — x is absent for the "e" handle.
 */
export function applyEdgeResize(
  handle: "w" | "e",
  dx: number,
  startX: number,
  startW: number,
  displayWidth: number,
  minDim: number,
): { x?: number; w: number } {
  const startRight = startX + startW;
  if (handle === "e") {
    const rawRight = Math.max(
      startX + minDim, Math.min(displayWidth, startRight + dx),
    );
    return { w: snap(rawRight) - startX };
  }
  const newX = snap(
    Math.max(0, Math.min(startRight - minDim, startX + dx)),
  );
  return { x: newX, w: startRight - newX };
}

/**
 * Compute the new position/size after a corner handle drag.
 *
 * Each corner moves its two adjacent edges. Opposite edges stay
 * fixed via startRight/startBottom. Moving edges are grid-snapped
 * first; the derived dimension is computed by subtraction (no
 * second snap) so the fixed edge never jitters. Results are
 * clamped to minDim minimum, x/y ≥ 0, and display bounds.
 *
 * @param handle - One of "nw", "ne", "sw", "se".
 * @param dx - Horizontal drag delta in display pixels.
 * @param dy - Vertical drag delta in display pixels.
 * @param startX - Widget x at drag start.
 * @param startY - Widget y at drag start.
 * @param startW - Widget width at drag start.
 * @param startH - Widget height at drag start.
 * @param minDim - Minimum allowed dimension in pixels.
 * @param displayWidth - Dashboard display width (right boundary).
 * @param displayHeight - Dashboard display height (bottom boundary).
 * @returns New { x?, y?, w, h } — x/y absent when that edge is fixed.
 */
export function applyCornerResize(
  handle: "nw" | "ne" | "sw" | "se",
  dx: number,
  dy: number,
  startX: number,
  startY: number,
  startW: number,
  startH: number,
  minDim: number,
  displayWidth: number,
  displayHeight: number,
): { x?: number; y?: number; w: number; h: number } {
  const startRight = startX + startW;
  const startBottom = startY + startH;
  if (handle === "se") {
    return {
      w: snap(
        Math.max(minDim, Math.min(displayWidth - startX, startW + dx)),
      ),
      h: snap(
        Math.max(minDim, Math.min(displayHeight - startY, startH + dy)),
      ),
    };
  }
  if (handle === "ne") {
    const newY = snap(
      Math.max(0, Math.min(startBottom - minDim, startY + dy)),
    );
    return {
      y: newY,
      w: snap(
        Math.max(minDim, Math.min(displayWidth - startX, startW + dx)),
      ),
      h: startBottom - newY,
    };
  }
  if (handle === "sw") {
    const newX = snap(
      Math.max(0, Math.min(startRight - minDim, startX + dx)),
    );
    return {
      x: newX,
      w: startRight - newX,
      h: snap(
        Math.max(minDim, Math.min(displayHeight - startY, startH + dy)),
      ),
    };
  }
  // nw — both edges move.
  const newX = snap(
    Math.max(0, Math.min(startRight - minDim, startX + dx)),
  );
  const newY = snap(
    Math.max(0, Math.min(startBottom - minDim, startY + dy)),
  );
  return {
    x: newX,
    y: newY,
    w: startRight - newX,
    h: startBottom - newY,
  };
}

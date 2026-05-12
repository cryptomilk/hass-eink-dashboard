import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  snap,
  grayColor,
  parseDaysUntil,
  formatRelativeDate,
  buildHeaderText,
  shouldShowCopyUrl,
  computeMetrics,
  drawCardContainer,
  drawCardRow,
  CHIP_PAD_RATIO,
  CHIP_ICON_RATIO,
  CHIP_GAP_RATIO,
  chipWidth,
  drawChip,
  drawChipFlow,
  loadIcon,
  getIcon,
  clearIconCache,
  deviceClassIcon,
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

describe("grayColor", () => {
  it("produces black for 0", () => expect(grayColor(0)).toBe("rgb(0,0,0)"));
  it("produces white for 255", () => expect(grayColor(255)).toBe("rgb(255,255,255)"));
  it("produces mid-gray for 128", () => expect(grayColor(128)).toBe("rgb(128,128,128)"));
});

function localISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

describe("parseDaysUntil", () => {
  let today: Date;

  beforeEach(() => {
    today = new Date();
    today.setHours(0, 0, 0, 0);
    vi.useFakeTimers();
    vi.setSystemTime(today);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 0 for today's ISO date", () => {
    expect(parseDaysUntil(localISO(today))).toBe(0);
  });

  it("returns 1 for tomorrow's ISO date", () => {
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    expect(parseDaysUntil(localISO(tomorrow))).toBe(1);
  });

  it("returns -1 for yesterday's ISO date", () => {
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    expect(parseDaysUntil(localISO(yesterday))).toBe(-1);
  });

  it("returns 5 for integer string '5'", () => {
    expect(parseDaysUntil("5")).toBe(5);
  });

  it("returns 0 for integer string '0'", () => {
    expect(parseDaysUntil("0")).toBe(0);
  });

  it("returns null for unparseable string", () => {
    expect(parseDaysUntil("garbage")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseDaysUntil("")).toBeNull();
  });
});

describe("formatRelativeDate", () => {
  it("returns 'today' for 0", () => expect(formatRelativeDate(0, "2024-01-01")).toBe("today"));
  it("returns 'tomorrow' for 1", () => expect(formatRelativeDate(1, "2024-01-02")).toBe("tomorrow"));
  it("returns 'in N days' for values > 1", () => expect(formatRelativeDate(3, "2024-01-04")).toBe("in 3 days"));
  it("returns raw string for negative days", () => expect(formatRelativeDate(-1, "2023-12-31")).toBe("2023-12-31"));
  it("returns raw string for null", () => expect(formatRelativeDate(null, "garbage")).toBe("garbage"));
});

describe("buildHeaderText", () => {
  it("returns the device name", () => {
    expect(buildHeaderText({ name: "My Kindle" })).toBe("My Kindle");
  });

  it("falls back to default when name is empty", () => {
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

describe("computeMetrics", () => {
  it("computes correct values for reference rowH=56", () => {
    // Verifies each ratio against the baseline from REDESIGN_WIDGETS.md.
    const m = computeMetrics(56);
    expect(m.border).toBe(2);          // max(2, round(56*0.04=2.24)→2)
    expect(m.padding).toBe(12);        // round(56*0.21)=11.76→12
    expect(m.radius).toBe(12);         // round(56*0.21)=11.76→12
    expect(m.iconDia).toBe(36);        // round(56*0.64)=35.84→36
    expect(m.fontPrimary).toBe(18);    // max(10, round(56*0.32)=17.92→18)
    expect(m.fontSecondary).toBe(14);  // max(10, round(56*0.25)=14)
    expect(m.divider).toBe(4);         // max(2, round(56*0.07)=3.92→4)
    expect(m.innerGap).toBe(12);       // round(56*0.21)=11.76→12
    expect(m.leftBar).toBe(4);         // max(2, round(56*0.07)=3.92→4)
  });

  it("clamps minimums for small rowH=10", () => {
    // border, fontPrimary, fontSecondary, divider, leftBar all have min clamps.
    const m = computeMetrics(10);
    expect(m.border).toBe(2);
    expect(m.fontPrimary).toBe(10);
    expect(m.fontSecondary).toBe(10);
    expect(m.divider).toBe(2);
    expect(m.leftBar).toBe(2);
    // Unclamped fields must not gain accidental clamps.
    expect(m.padding).toBe(2);    // round(10*0.21=2.1)→2, no clamp
    expect(m.radius).toBe(2);     // round(10*0.21=2.1)→2, no clamp
    expect(m.iconDia).toBe(6);    // round(10*0.64=6.4)→6, no clamp
    expect(m.innerGap).toBe(2);   // round(10*0.21=2.1)→2, no clamp
  });

  it("returns integer values for all fields", () => {
    // Fractional pixels cause misalignment; all fields must be whole numbers.
    for (const rowH of [10, 28, 56, 100, 112]) {
      const m = computeMetrics(rowH);
      for (const [k, v] of Object.entries(m)) {
        expect(Number.isInteger(v), `${k} at rowH=${rowH}`).toBe(true);
      }
    }
  });

  it("unclamped fields scale exactly when rowH doubles (56 → 112)", () => {
    // These inputs are chosen so round(v * 2) yields
    // exact 2x multiples — other pairs may diverge by
    // ±1 px due to Math.round rounding.
    const m1 = computeMetrics(56);
    const m2 = computeMetrics(112);
    expect(m2.padding).toBe(m1.padding * 2);
    expect(m2.radius).toBe(m1.radius * 2);
    expect(m2.iconDia).toBe(m1.iconDia * 2);
    expect(m2.innerGap).toBe(m1.innerGap * 2);
    expect(m2.fontPrimary).toBe(m1.fontPrimary * 2);
    expect(m2.fontSecondary).toBe(m1.fontSecondary * 2);
    expect(m2.divider).toBe(m1.divider * 2);
    expect(m2.leftBar).toBe(m1.leftBar * 2);
  });
});

// ── Mock canvas context factory ──────────────────────────────────────────────

/**
 * Create a minimal mock of CanvasRenderingContext2D
 * with vi.fn() spies on all methods used by
 * drawCardContainer and drawCardRow.  measureText
 * returns width and bounding-box heights derived
 * from the current font size so centering arithmetic
 * produces deterministic, verifiable positions.
 */
function createMockCtx(): CanvasRenderingContext2D {
  let _font = "16px Roboto, sans-serif";
  const ctx = {
    // Writable state properties
    fillStyle: "" as string | CanvasGradient | CanvasPattern,
    strokeStyle: "" as string | CanvasGradient | CanvasPattern,
    lineWidth: 1,
    textBaseline: "alphabetic" as CanvasTextBaseline,
    textAlign: "start" as CanvasTextAlign,
    // font is a property so measureText can read it
    get font(): string { return _font; },
    set font(v: string) { _font = v; },
    // Drawing spies
    filter: "none",
    beginPath: vi.fn(),
    roundRect: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    arc: vi.fn(),
    drawImage: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    // measureText: parse font size from ctx.font and
    // return proportional width and bounding box values
    // so vertical-centering math in drawCardRow is
    // deterministic.
    measureText: vi.fn((text: string): TextMetrics => {
      const match = _font.match(/(\d+)px/);
      const fs = match ? parseInt(match[1], 10) : 16;
      return {
        width: text.length * fs * 0.6,
        actualBoundingBoxAscent: fs * 0.8,
        actualBoundingBoxDescent: fs * 0.2,
        // Unused TextMetrics fields — zero-fill
        actualBoundingBoxLeft: 0,
        actualBoundingBoxRight: text.length * fs * 0.6,
        fontBoundingBoxAscent: fs,
        fontBoundingBoxDescent: 0,
        hangingBaseline: 0,
        alphabeticBaseline: 0,
        ideographicBaseline: 0,
        emHeightAscent: fs,
        emHeightDescent: 0,
      } as TextMetrics;
    }),
  };
  return ctx as unknown as CanvasRenderingContext2D;
}

// ── drawCardContainer tests ──────────────────────────────────────────────────

describe("drawCardContainer", () => {
  it("border: returns m.padding", () => {
    // "border" style content starts at the padding inset.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const [xOff, rInset] = drawCardContainer(ctx, 0, 0, 200, 300, m, "border");
    expect(xOff).toBe(m.padding);
    expect(rInset).toBe(m.padding);
  });

  it("border: calls roundRect with correct args", () => {
    // Rounded rect must match the card area exactly.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardContainer(ctx, 10, 20, 200, 300, m, "border");
    expect(ctx.roundRect).toHaveBeenCalledWith(10, 20, 200, 300, m.radius);
    expect(ctx.stroke).toHaveBeenCalled();
  });

  it("border: stroke color is COLOR_BLACK and lineWidth is m.border", () => {
    // Outline must be black with the metric-derived width.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardContainer(ctx, 0, 0, 200, 300, m, "border");
    expect(ctx.strokeStyle).toBe(grayColor(0));
    expect(ctx.lineWidth).toBe(m.border);
  });

  it("left_bar: returns m.leftBar + m.padding (normal grayscale)", () => {
    // Standard 16-level display uses the normal bar width.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const [xOff, rInset] = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar",
    );
    expect(xOff).toBe(m.leftBar + m.padding);
    expect(rInset).toBe(0);
  });

  it("left_bar: draws gray filled rect for the bar", () => {
    // The bar is a filled gray rectangle on the left edge.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardContainer(ctx, 10, 20, 200, 300, m, "left_bar");
    expect(ctx.fillRect).toHaveBeenCalledWith(10, 20, m.leftBar, 300);
    expect(ctx.fillStyle).toBe(grayColor(120));
  });

  it("left_bar: widens bar when grayscale <= 2", () => {
    // On 2-level displays, bar = max(10, leftBar * 3).
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const widened = Math.max(10, m.leftBar * 3);
    const [xOff, rInset] = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar", 2,
    );
    expect(xOff).toBe(widened + m.padding);
    expect(rInset).toBe(0);
    expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, widened, 300);
  });

  it("left_bar: does not widen when grayscale is 16", () => {
    // Explicit 16-level: normal bar width, no widening.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const [xOff, rInset] = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar", 16,
    );
    expect(xOff).toBe(m.leftBar + m.padding);
    expect(rInset).toBe(0);
    expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, m.leftBar, 300);
  });

  it("left_bar: grayscaleLevels defaults to 16 (no widening)", () => {
    // Omitting grayscaleLevels must behave like passing 16.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const [xOffDefault] = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar",
    );
    const ctx2 = createMockCtx();
    const [xOffExplicit] = drawCardContainer(
      ctx2, 0, 0, 200, 300, m, "left_bar", 16,
    );
    expect(xOffDefault).toBe(xOffExplicit);
  });

  it("none: returns 0", () => {
    // No decoration means zero content offset.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const [xOff, rInset] = drawCardContainer(ctx, 0, 0, 200, 300, m, "none");
    expect(xOff).toBe(0);
    expect(rInset).toBe(0);
  });

  it("none: does not call any drawing method", () => {
    // The "none" style must not draw anything at all.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardContainer(ctx, 0, 0, 200, 300, m, "none");
    expect(ctx.roundRect).not.toHaveBeenCalled();
    expect(ctx.fillRect).not.toHaveBeenCalled();
    expect(ctx.stroke).not.toHaveBeenCalled();
    expect(ctx.fill).not.toHaveBeenCalled();
  });
});

// ── drawCardRow tests ────────────────────────────────────────────────────────

describe("drawCardRow", () => {
  it("draws the icon circle via arc()", () => {
    // The gray circle is drawn with arc() + fill().
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(ctx, 0, 0, 300, 56, m, { primary: "Test" });
    expect(ctx.arc).toHaveBeenCalled();
    expect(ctx.fill).toHaveBeenCalled();
  });

  it("letter fallback: first char uppercased", () => {
    // Lowercase primary -> uppercase letter in circle.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(ctx, 0, 0, 300, 56, m, { primary: "test" });
    const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    const letterCall = calls.find((c) => c[0] === "T");
    expect(letterCall).toBeDefined();
  });

  it("letter fallback: empty primary uses '?'", () => {
    // When primary is empty, the fallback character is "?".
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(ctx, 0, 0, 300, 56, m, { primary: "" });
    const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    const qCall = calls.find((c) => c[0] === "?");
    expect(qCall).toBeDefined();
  });

  it("draws the primary label text", () => {
    // Primary text must appear in the fillText calls.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(ctx, 0, 0, 300, 56, m, { primary: "Hello" });
    const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.some((c) => c[0] === "Hello")).toBe(true);
  });

  it("draws secondary text when provided", () => {
    // Secondary text must appear when opts.secondary is set.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(
      ctx, 0, 0, 300, 56, m,
      { primary: "Name", secondary: "23°C" },
    );
    const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.some((c) => c[0] === "23°C")).toBe(true);
  });

  it("secondary y-position is greater than primary y", () => {
    // Secondary text must be drawn below primary.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(
      ctx, 0, 0, 300, 56, m,
      { primary: "Name", secondary: "Sub" },
    );
    const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    const primY = calls.find((c) => c[0] === "Name")?.[2] as number;
    const secY = calls.find((c) => c[0] === "Sub")?.[2] as number;
    expect(typeof primY).toBe("number");
    expect(typeof secY).toBe("number");
    expect(secY).toBeGreaterThan(primY);
  });

  it("right-aligned value appears near the right edge", () => {
    // Value x must be less than x+w-m.padding (right-aligned).
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(
      ctx, 0, 0, 300, 56, m,
      { primary: "Name", value: "today" },
    );
    const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    const valCall = calls.find((c) => c[0] === "today");
    expect(valCall).toBeDefined();
    // Value x must be right-of-center and left of the right edge.
    const valX = valCall![1] as number;
    expect(valX).toBeLessThan(300 - m.padding);
    expect(valX).toBeGreaterThan(0);
  });

  it("no secondary: primary y is vertically within the row", () => {
    // Single-line primary must be centered within [y, y+rowH].
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    drawCardRow(ctx, 0, 100, 300, 56, m, { primary: "Solo" });
    const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    const primCall = calls.find((c) => c[0] === "Solo");
    const primY = primCall?.[2] as number;
    expect(primY).toBeGreaterThan(100);
    expect(primY).toBeLessThan(100 + 56);
  });

  it("primary text uses medium weight (500) font", () => {
    // Capture ctx.font at each fillText call, then
    // assert the font for "Hello" contains "500".
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const fontLog: Array<[string, string]> = [];
    (ctx as unknown as Record<string, unknown>).fillText =
      vi.fn((text: string) => {
        fontLog.push([text, ctx.font]);
      });
    drawCardRow(ctx, 0, 0, 300, 56, m, { primary: "Hello" });
    const entry = fontLog.find(([t]) => t === "Hello");
    expect(entry).toBeDefined();
    expect(entry![1]).toContain("500");
  });

  it("custom iconFill changes the circle fill color", () => {
    // Passing iconFill=0 (black) overrides the default gray.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    // Capture fillStyle at time of fill() call by tracking changes.
    const fillStyles: Array<string | CanvasGradient | CanvasPattern> = [];
    (ctx as unknown as Record<string, unknown>).fill = vi.fn(() => {
      fillStyles.push(ctx.fillStyle);
    });
    drawCardRow(
      ctx, 0, 0, 300, 56, m,
      { primary: "Test", iconFill: 0 },
    );
    // The first fill() call (circle) must use black (0,0,0).
    expect(fillStyles[0]).toBe(grayColor(0));
  });
});

// ── chip constants ───────────────────────────────────────────────────────────

describe("chip constants", () => {
  it("CHIP_PAD_RATIO matches Python _CHIP_PAD_RATIO", () => {
    // Python render.py defines _CHIP_PAD_RATIO = 0.18.
    expect(CHIP_PAD_RATIO).toBe(0.18);
  });

  it("CHIP_ICON_RATIO matches Python _CHIP_ICON_RATIO", () => {
    // Python render.py defines _CHIP_ICON_RATIO = 0.29.
    expect(CHIP_ICON_RATIO).toBe(0.29);
  });

  it("CHIP_GAP_RATIO matches Python _CHIP_GAP_RATIO", () => {
    // Python render.py defines _CHIP_GAP_RATIO = 0.14.
    expect(CHIP_GAP_RATIO).toBe(0.14);
  });
});

// ── chipWidth ────────────────────────────────────────────────────────────────

describe("chipWidth", () => {
  it("returns positive width for simple text", () => {
    // Basic sanity: any text chip has a positive width.
    const ctx = createMockCtx();
    const w = chipWidth(ctx, 40, "OK", 16, false);
    // padH*2 = 14, textW = floor(2*16*0.6)=19, total=33
    expect(w).toBe(33);
  });

  it("with icon is wider than without", () => {
    // Adding an icon increases width by iconSz + iconGap.
    const ctx = createMockCtx();
    const withoutIcon = chipWidth(ctx, 40, "OK", 16, false);
    const withIcon = chipWidth(ctx, 40, "OK", 16, true);
    const iconSz = Math.round(40 * CHIP_ICON_RATIO);
    const iconGap = Math.round(40 * CHIP_GAP_RATIO);
    expect(withIcon - withoutIcon).toBe(iconSz + iconGap);
  });

  it("width increases with h", () => {
    // Larger chip height produces larger chip width
    // because padH scales with h.
    const ctx = createMockCtx();
    const small = chipWidth(ctx, 40, "Test", 16, false);
    const large = chipWidth(ctx, 80, "Test", 16, false);
    expect(large).toBeGreaterThan(small);
  });
});

// ── drawChip ─────────────────────────────────────────────────────────────────

describe("drawChip", () => {
  it("returns x + chipW", () => {
    // Return value must equal the x coordinate after
    // the chip so callers can chain chips.
    const ctx = createMockCtx();
    const cw = chipWidth(ctx, 40, "OK", 16, false);
    const result = drawChip(ctx, 10, 20, 40, "OK", 16, 2);
    expect(result).toBe(10 + cw);
  });

  it("draws roundRect with pill radius floor(h/2)", () => {
    // End-caps must be perfect semicircles: radius = h/2.
    const ctx = createMockCtx();
    const h = 40;
    drawChip(ctx, 0, 0, h, "Hi", 16, 2);
    const radius = Math.floor(h / 2);
    const cw = chipWidth(ctx, h, "Hi", 16, false);
    expect(ctx.roundRect).toHaveBeenCalledWith(
      0, 0, cw, h, radius,
    );
  });

  it("draws label text via fillText", () => {
    // The label must appear in the fillText calls.
    const ctx = createMockCtx();
    drawChip(ctx, 0, 0, 40, "Hello", 16, 2);
    const calls =
      (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.some((c) => c[0] === "Hello")).toBe(true);
  });

  it("inverted: fill is black, text is white", () => {
    // inverted=true swaps background to black and
    // foreground to white.
    const ctx = createMockCtx();
    const fillStyles: Array<
      string | CanvasGradient | CanvasPattern
    > = [];
    (ctx as unknown as Record<string, unknown>).fill =
      vi.fn(() => { fillStyles.push(ctx.fillStyle); });
    const textStyles: Array<
      string | CanvasGradient | CanvasPattern
    > = [];
    (ctx as unknown as Record<string, unknown>).fillText =
      vi.fn((t: string) => {
        if (t === "OK") textStyles.push(ctx.fillStyle);
      });
    drawChip(
      ctx, 0, 0, 40, "OK", 16, 2, { inverted: true },
    );
    // Background fill must be black.
    expect(fillStyles[0]).toBe(grayColor(0));
    // Text fill must be white.
    expect(textStyles[0]).toBe(grayColor(255));
  });

  it("uses the provided fontSize in ctx.font", () => {
    // The font string for label text must contain the
    // given fontSize.
    const ctx = createMockCtx();
    const fontLog: Array<[string, string]> = [];
    (ctx as unknown as Record<string, unknown>).fillText =
      vi.fn((text: string) => {
        fontLog.push([text, ctx.font]);
      });
    drawChip(ctx, 0, 0, 40, "Hi", 24, 2);
    const entry = fontLog.find(([t]) => t === "Hi");
    expect(entry).toBeDefined();
    expect(entry![1]).toContain("24px");
  });

  it("stroke outline is always COLOR_BLACK", () => {
    // Even when inverted, the border outline must be
    // black (COLOR_BLACK = 0).
    const ctx = createMockCtx();
    drawChip(
      ctx, 0, 0, 40, "OK", 16, 2, { inverted: true },
    );
    expect(ctx.strokeStyle).toBe(grayColor(0));
  });
});

// ── drawChipFlow ──────────────────────────────────────────────────────────────

describe("drawChipFlow", () => {
  it("empty chips returns y unchanged", () => {
    // An empty chip list must not advance the cursor.
    const ctx = createMockCtx();
    const result = drawChipFlow(
      ctx, 0, 50, 400, 40, [], 16, 2,
    );
    expect(result).toBe(50);
  });

  it("single chip returns y + h", () => {
    // One chip occupies exactly one row.
    const ctx = createMockCtx();
    const result = drawChipFlow(
      ctx, 0, 50, 400, 40, [{ text: "OK" }], 16, 2,
    );
    expect(result).toBe(50 + 40);
  });

  it("wraps to next row when chips exceed width", () => {
    // With a narrow container, the second chip must wrap
    // to a new row, pushing the return value past y+h.
    const ctx = createMockCtx();
    // h=40, fontSize=16:
    // "Hello" chipW = 7*2 + floor(5*16*0.6) = 14+48 = 62
    // gap = round(40*0.29) = 12
    // After first chip: curX = 62
    // "Hi" chipW = 7*2 + floor(2*16*0.6) = 14+19 = 33
    // curX(62) > x(0): check 62+12+33=107 > w=100: wrap
    const result = drawChipFlow(
      ctx, 0, 0, 100, 40,
      [{ text: "Hello" }, { text: "Hi" }],
      16, 2,
    );
    // Wrapped: curY = 0+40+12=52, return = 52+40 = 92
    expect(result).toBeGreaterThan(40);
  });

  it("first chip not skipped even if wider than w", () => {
    // The first chip on a row is always drawn, even if
    // wider than the container (overflow, not dropped).
    const ctx = createMockCtx();
    // Very narrow container (w=10) with a wide chip.
    drawChipFlow(
      ctx, 0, 0, 10, 40, [{ text: "AAAAAA" }], 16, 2,
    );
    // Chip must have been drawn (roundRect called).
    expect(ctx.roundRect).toHaveBeenCalled();
  });

  it("passes inverted flag to drawChip", () => {
    // inverted: true in the chip descriptor must
    // produce a black background fill.
    const ctx = createMockCtx();
    const fillStyles: Array<
      string | CanvasGradient | CanvasPattern
    > = [];
    (ctx as unknown as Record<string, unknown>).fill =
      vi.fn(() => {
        fillStyles.push(ctx.fillStyle);
      });
    drawChipFlow(
      ctx, 0, 0, 400, 40,
      [{ text: "Alert", inverted: true }],
      16, 2,
    );
    // Background fill must be black.
    expect(fillStyles[0]).toBe(grayColor(0));
  });
});

// ── loadIcon / getIcon ────────────────────────────────────────────────────────

describe("loadIcon / getIcon", () => {
  beforeEach(() => {
    clearIconCache();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getIcon returns null for a URL never passed to loadIcon", () => {
    // Before any load, the cache has no entry for the URL.
    expect(getIcon("/never-loaded.svg")).toBeNull();
  });

  it("loadIcon populates cache; getIcon returns the element", async () => {
    // A successful load must add the image to the cache so
    // getIcon returns it without another network round-trip.
    vi.stubGlobal("Image", vi.fn().mockImplementation(() => ({
      decode: vi.fn().mockResolvedValue(undefined),
      src: "",
    })));
    await loadIcon("/test-cache-A.svg");
    const cached = getIcon("/test-cache-A.svg");
    expect(cached).not.toBeNull();
  });

  it("loadIcon returns null and skips cache on decode error", async () => {
    // A failed decode must not pollute the cache — callers
    // use getIcon() returning null as the signal to fall back
    // to placeholder rendering.
    vi.stubGlobal("Image", vi.fn().mockImplementation(() => ({
      decode: vi.fn().mockRejectedValue(new Error("404")),
      src: "",
    })));
    const result = await loadIcon("/test-error.svg");
    expect(result).toBeNull();
    expect(getIcon("/test-error.svg")).toBeNull();
  });

  it("loadIcon constructs Image only once for repeated calls", async () => {
    // Cache hit on the second call must skip Image construction.
    const ImageMock = vi.fn().mockImplementation(() => ({
      decode: vi.fn().mockResolvedValue(undefined),
      src: "",
    }));
    vi.stubGlobal("Image", ImageMock);
    await loadIcon("/test-cache-B.svg");
    await loadIcon("/test-cache-B.svg");
    expect(ImageMock).toHaveBeenCalledTimes(1);
  });
});

// ── drawCardRow with icon ─────────────────────────────────────────────────────

describe("drawCardRow icon rendering", () => {
  it("calls drawImage when opts.icon is provided", () => {
    // Providing a loaded HTMLImageElement must produce a
    // drawImage call instead of the letter fallback.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const mockIcon = {} as HTMLImageElement;
    drawCardRow(ctx, 0, 0, 300, 56, m, {
      primary: "Test", icon: mockIcon,
    });
    expect(ctx.drawImage).toHaveBeenCalledWith(
      mockIcon,
      expect.any(Number), expect.any(Number),
      expect.any(Number), expect.any(Number),
    );
  });

  it("letter fallback is not drawn when icon is provided", () => {
    // When opts.icon is set, the first-letter fallback must
    // be suppressed so the icon appears alone in the circle.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const mockIcon = {} as HTMLImageElement;
    drawCardRow(ctx, 0, 0, 300, 56, m, {
      primary: "Test", icon: mockIcon,
    });
    const letterCalls =
      (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls;
    // The letter "T" must not appear in fillText calls.
    expect(letterCalls.some((c) => c[0] === "T")).toBe(false);
  });

  it("icon is drawn at 60% of iconDia, centred in the circle", () => {
    // Mirrors the icon_sz = round(m.icon_dia * 0.6) formula
    // from _draw_card_row() in render.py.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const mockIcon = {} as HTMLImageElement;
    drawCardRow(ctx, 0, 0, 300, 56, m, {
      primary: "A", icon: mockIcon,
    });
    const iconSz = Math.round(m.iconDia * 0.6);
    const offset = Math.floor((m.iconDia - iconSz) / 2);
    const iconX = m.padding;
    const circleY = Math.floor((56 - m.iconDia) / 2);
    const drawCalls =
      (ctx.drawImage as ReturnType<typeof vi.fn>).mock.calls;
    expect(drawCalls[0]).toEqual([
      mockIcon,
      iconX + offset, circleY + offset,
      iconSz, iconSz,
    ]);
  });
});

// ── drawChip with icon ────────────────────────────────────────────────────────

describe("drawChip icon rendering", () => {
  it("calls drawImage and omits placeholder rect when icon provided", () => {
    // The gray placeholder fillRect must not appear when a
    // real icon image is passed.
    const ctx = createMockCtx();
    const mockIcon = {} as HTMLImageElement;
    drawChip(ctx, 0, 0, 40, "OK", 16, 2, { icon: mockIcon });
    expect(ctx.drawImage).toHaveBeenCalledWith(
      mockIcon,
      expect.any(Number), expect.any(Number),
      expect.any(Number), expect.any(Number),
    );
    // fillRect is used for the placeholder — must not be called.
    expect(ctx.fillRect).not.toHaveBeenCalled();
  });

  it("inverted chip: drawImage is called with invert(1) filter", () => {
    // ctx.filter must equal "invert(1)" at the time drawImage
    // fires so the black MDI icon renders as white on the
    // black chip background, matching Python's ImageOps.invert().
    const ctx = createMockCtx();
    let filterAtDraw = "";
    (ctx.drawImage as ReturnType<typeof vi.fn>).mockImplementation(
      () => { filterAtDraw = ctx.filter as unknown as string; },
    );
    const mockIcon = {} as HTMLImageElement;
    drawChip(ctx, 0, 0, 40, "OK", 16, 2, {
      icon: mockIcon, inverted: true,
    });
    expect(filterAtDraw).toBe("invert(1)");
    expect(ctx.save).toHaveBeenCalled();
    expect(ctx.restore).toHaveBeenCalled();
  });

  it("non-inverted chip with icon: no filter applied", () => {
    // A normal chip must not change ctx.filter so existing
    // canvas state is not disturbed.
    const ctx = createMockCtx();
    let filterAtDraw = "none";
    (ctx.drawImage as ReturnType<typeof vi.fn>).mockImplementation(
      () => { filterAtDraw = ctx.filter as unknown as string; },
    );
    const mockIcon = {} as HTMLImageElement;
    drawChip(ctx, 0, 0, 40, "OK", 16, 2, { icon: mockIcon });
    expect(filterAtDraw).toBe("none");
  });
});

describe("deviceClassIcon", () => {
  it("sensor device_class returns correct icon", () => {
    // Temperature sensor maps to thermometer.
    expect(deviceClassIcon(
      "temperature", "22.5", "sensor",
    )).toBe("thermometer");
  });

  it("sensor humidity returns water-percent", () => {
    expect(deviceClassIcon(
      "humidity", "45", "sensor",
    )).toBe("water-percent");
  });

  it("unknown sensor device_class returns null", () => {
    expect(deviceClassIcon(
      "unknown_class", "42", "sensor",
    )).toBeNull();
  });

  it("empty device_class returns null", () => {
    expect(deviceClassIcon(
      "", "42", "sensor",
    )).toBeNull();
  });

  it("binary_sensor off state returns off icon", () => {
    // Door off → door-closed.
    expect(deviceClassIcon(
      "door", "off", "binary_sensor",
    )).toBe("door-closed");
  });

  it("binary_sensor on state returns on icon", () => {
    // Door on → door-open.
    expect(deviceClassIcon(
      "door", "on", "binary_sensor",
    )).toBe("door-open");
  });

  it("binary_sensor window state-dependent", () => {
    expect(deviceClassIcon(
      "window", "off", "binary_sensor",
    )).toBe("window-closed-variant");
    expect(deviceClassIcon(
      "window", "on", "binary_sensor",
    )).toBe("window-open-variant");
  });

  it("binary_sensor unknown class returns null", () => {
    expect(deviceClassIcon(
      "unknown_class", "on", "binary_sensor",
    )).toBeNull();
  });

  it("non-sensor domain uses sensor map", () => {
    // Person, lock, etc. fall through to sensor map.
    expect(deviceClassIcon(
      "temperature", "22", "person",
    )).toBe("thermometer");
  });
});

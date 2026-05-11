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
    beginPath: vi.fn(),
    roundRect: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    arc: vi.fn(),
    fillText: vi.fn(),
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
    const offset = drawCardContainer(ctx, 0, 0, 200, 300, m, "border");
    expect(offset).toBe(m.padding);
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
    const offset = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar",
    );
    expect(offset).toBe(m.leftBar + m.padding);
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
    const offset = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar", 2,
    );
    expect(offset).toBe(widened + m.padding);
    expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, widened, 300);
  });

  it("left_bar: does not widen when grayscale is 16", () => {
    // Explicit 16-level: normal bar width, no widening.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const offset = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar", 16,
    );
    expect(offset).toBe(m.leftBar + m.padding);
    expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, m.leftBar, 300);
  });

  it("left_bar: grayscaleLevels defaults to 16 (no widening)", () => {
    // Omitting grayscaleLevels must behave like passing 16.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const offsetDefault = drawCardContainer(
      ctx, 0, 0, 200, 300, m, "left_bar",
    );
    const ctx2 = createMockCtx();
    const offsetExplicit = drawCardContainer(
      ctx2, 0, 0, 200, 300, m, "left_bar", 16,
    );
    expect(offsetDefault).toBe(offsetExplicit);
  });

  it("none: returns 0", () => {
    // No decoration means zero content offset.
    const m = computeMetrics(56);
    const ctx = createMockCtx();
    const offset = drawCardContainer(ctx, 0, 0, 200, 300, m, "none");
    expect(offset).toBe(0);
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

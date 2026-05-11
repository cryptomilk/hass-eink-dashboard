import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { snap, grayColor, parseDaysUntil, formatRelativeDate, buildHeaderText, shouldShowCopyUrl, computeMetrics } from "../src/eink-dashboard-card.js";

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

  it("unclamped fields scale exactly when rowH doubles", () => {
    // Proportional scaling: doubling rowH doubles all unclamped dimensions.
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

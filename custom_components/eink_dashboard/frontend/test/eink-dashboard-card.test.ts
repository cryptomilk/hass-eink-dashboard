import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { snap, grayColor, parseDaysUntil, formatRelativeDate, buildHeaderText, shouldShowCopyUrl } from "../src/eink-dashboard-card.js";

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

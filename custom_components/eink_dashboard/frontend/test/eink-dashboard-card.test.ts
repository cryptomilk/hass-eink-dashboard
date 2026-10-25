// Copyright 2026 Andreas Schneider
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { describe, it, expect } from "vitest";
import {
  FONT_STYLE_ID,
  buildFontFaceCss,
  buildHeaderText,
  ensureBundledFonts,
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

describe("buildFontFaceCss", () => {
  it("declares regular and bold faces for every TRMNL size", () => {
    // Each optical size needs a 400 and a 700 face so widget SVGs
    // referencing TRMNL12/16/21 render with the bundled font.
    const css = buildFontFaceCss("1.0");
    expect(css.match(/@font-face/g)).toHaveLength(9);
    for (const size of [12, 16, 21]) {
      expect(css).toContain(`font-family: "TRMNL${size}"`);
      expect(css).toContain(
        `/eink_dashboard/fonts/TRMNL/TRMNL${size}-Regular.ttf?v=1.0`,
      );
      expect(css).toContain(
        `/eink_dashboard/fonts/TRMNL/TRMNL${size}-Bold.ttf?v=1.0`,
      );
    }
    expect(css).toContain("font-weight: 700");
  });

  it("declares Inter faces for the TRMNL large-text fallback", () => {
    // Inter is not a system font, so the browser preview needs its
    // own @font-face rules just like TRMNL, unlike Roboto which
    // Home Assistant's own frontend already loads.
    const css = buildFontFaceCss("1.0");
    expect(css).toContain('font-family: "Inter"');
    for (const [style, weight] of [
      ["Regular", 400],
      ["Medium", 500],
      ["Bold", 700],
    ] as const) {
      expect(css).toContain(
        `/eink_dashboard/fonts/Inter/Inter-${style}.ttf?v=1.0`,
      );
      expect(css).toContain(`font-weight: ${weight}`);
    }
  });

  it("omits the cache buster when no version is known", () => {
    // Without a version the URLs carry no query string.
    expect(buildFontFaceCss("")).not.toContain("?v=");
  });
});

describe("ensureBundledFonts", () => {
  it("adds one style element to the document head", () => {
    // Font faces must live in the document, not the shadow root, and
    // repeated calls must not duplicate them.
    document.getElementById(FONT_STYLE_ID)?.remove();
    ensureBundledFonts(document);
    ensureBundledFonts(document);
    const styles = document.head.querySelectorAll(`#${FONT_STYLE_ID}`);
    expect(styles).toHaveLength(1);
    expect(styles[0].textContent).toContain("TRMNL16");
  });
});

// E-Ink Dashboard Lovelace card — read-only canvas preview.
// Mirrors the rendering logic from render.py using Canvas 2D.

import type {
  HomeAssistant,
  HassEntity,
  Widget,
  TextWidget,
  SeparatorWidget,
  WeatherWidget,
  SensorRowsWidget,
  DeviceBatteryWidget,
  StatusIconsWidget,
  WasteScheduleWidget,
  WasteScheduleEntry,
  LayoutResponse,
  WidgetBounds,
  WidgetMetrics,
  CardStyle,
  CardRowOpts,
  ChipOpts,
  ChipDescriptor,
  IndexedBounds,
  Handle,
  ForecastDay,
  ForecastServiceResult,
  EinkEditorElement,
  ConfigEntry,
} from "./types/ha.js";

const CARD_TAG = "eink-dashboard-card";

// ── Constants (mirror const.py + render.py) ──────────────────────────────────

const PADDING = 24;
const COLOR_BLACK = 0;
const COLOR_WHITE = 255;
const COLOR_GRAY = 120;
const COLOR_LIGHT_GRAY = 180;
const FONT_FAMILY = "Roboto, sans-serif";
const ROBOTO_URL = "/eink_dashboard/fonts/Roboto-Regular.ttf";
const ROBOTO_MEDIUM_URL = "/eink_dashboard/fonts/Roboto-Medium.ttf";

const FONT_SIZE_TEXT = 32;
const FONT_SIZE_WEATHER = 32;
const FONT_SIZE_DEVICE_BATTERY = 24;
const MIN_RESIZE_FONT_SIZE = 8;
const MAX_RESIZE_FONT_SIZE = 72;

let _robotoLoaded = false;
async function _loadRoboto(): Promise<void> {
  if (_robotoLoaded) return;
  try {
    const face = new FontFace("Roboto", `url(${ROBOTO_URL})`);
    await face.load();
    document.fonts.add(face);
    _robotoLoaded = true;
  } catch (_) { /* fall back to sans-serif */ }
}

let _robotoMediumLoaded = false;
async function _loadRobotoMedium(): Promise<void> {
  if (_robotoMediumLoaded) return;
  try {
    const face = new FontFace("Roboto", `url(${ROBOTO_MEDIUM_URL})`, { weight: "500" });
    await face.load();
    document.fonts.add(face);
    _robotoMediumLoaded = true;
  } catch (_) { /* fall back to sans-serif */ }
}

const ICON_BASE = "/eink_dashboard/icons";
const TRASH_ICON_URL = `${ICON_BASE}/svg/mdi/trash-can.svg`;

// Condition string → SVG filename under icons/svg/.
// Mirrors CONDITION_TO_SVG in scripts/build_icons.py.
const CONDITION_SVG_MAP: Record<string, string> = {
  "sunny": "wi-day-sunny",
  "clear-night": "wi-night-clear",
  "cloudy": "wi-cloudy",
  "partlycloudy": "wi-day-cloudy",
  "fog": "wi-fog",
  "hail": "wi-hail",
  "lightning": "wi-lightning",
  "lightning-rainy": "wi-thunderstorm",
  "pouring": "wi-rain",
  "rainy": "wi-showers",
  "snowy": "wi-snow",
  "snowy-rainy": "wi-rain-mix",
  "windy": "wi-windy",
  "windy-variant": "wi-cloudy-windy",
  "exceptional": "wi-na",
};

// Detail SVG basenames under icons/svg/. Keyed by HA entity
// attribute name so _collectWeatherIcons() can check attrs
// directly. SVG values mirror DETAIL_TO_SVG in
// scripts/build_icons.py (keys differ because Python uses
// icon names, not HA attribute names).
const DETAIL_SVG_MAP: Record<string, string> = {
  "humidity": "wi-humidity",
  "pressure": "wi-barometer",
  "wind_speed": "wi-strong-wind",
  "cloud_coverage": "wi-cloud",
};

// Sensor device_class → MDI icon name (without prefix/extension).
// Mirrors _SENSOR_DEVICE_CLASS_ICONS in render.py.
const SENSOR_DEVICE_CLASS_ICONS: Record<string, string> = {
  "temperature": "thermometer",
  "humidity": "water-percent",
  "pressure": "gauge",
  "battery": "battery",
  "power": "flash",
  "energy": "lightning-bolt",
  "gas": "fire",
  "illuminance": "brightness-5",
  "moisture": "water-alert",
  "apparent_power": "flash-auto",
  "aqi": "air-filter",
  "carbon_dioxide": "molecule-co2",
  "carbon_monoxide": "molecule-co",
  "current": "current-ac",
  "data_size": "database",
  "distance": "ruler",
  "duration": "timer-outline",
  "frequency": "sine-wave",
  "irradiance": "sun-wireless",
  "monetary": "currency-usd",
  "nitrogen_dioxide": "smog",
  "ozone": "weather-dust",
  "ph": "ph",
  "pm25": "blur",
  "signal_strength": "signal",
  "speed": "speedometer",
  "voltage": "flash",
  "volume": "cup-water",
  "water": "water",
  "weight": "weight",
  "wind_speed": "weather-windy",
};

// Binary sensor device_class → [off_icon, on_icon].
// Mirrors _BINARY_SENSOR_DEVICE_CLASS_ICONS in render.py.
const BINARY_SENSOR_DEVICE_CLASS_ICONS: Record<
  string,
  [string, string]
> = {
  "door": ["door-closed", "door-open"],
  "window": [
    "window-closed-variant",
    "window-open-variant",
  ],
  "garage_door": ["garage", "garage-open"],
  "lock": ["lock", "lock-open"],
  "motion": ["motion-sensor-off", "motion-sensor"],
  "smoke": [
    "smoke-detector-variant",
    "smoke-detector-variant-alert",
  ],
  "battery": ["battery", "battery-alert"],
  "battery_charging": [
    "battery-charging",
    "battery-charging",
  ],
  "cold": ["thermometer", "snowflake"],
  "connectivity": ["wifi-off", "wifi"],
  "heat": ["thermometer", "fire-alert"],
  "light": ["brightness-5", "brightness-7"],
  "occupancy": ["home-outline", "home-account"],
  "opening": ["square-outline", "square"],
  "plug": ["power-plug-off", "power-plug"],
  "presence": ["account-outline", "account"],
  "problem": ["check-circle", "alert-circle"],
  "running": ["stop-circle", "play-circle"],
  "safety": ["shield-check", "shield-alert"],
  "sound": ["volume-off", "volume-high"],
  "tamper": ["shield-check", "shield-alert"],
  "update": ["package", "package-up"],
  "vibration": ["crop-portrait", "vibrate"],
};

/**
 * Resolve an MDI icon name from device_class, state, and
 * entity domain.
 *
 * For binary sensors, returns the state-appropriate icon
 * (off or on).  For all other domains, returns the single
 * icon mapped to the device_class.  Mirrors
 * _device_class_icon() in render.py.
 *
 * @param deviceClass - HA device_class attribute value.
 * @param state - Entity state string (e.g. "on", "off").
 * @param domain - HA entity domain (e.g. "binary_sensor").
 * @returns MDI icon name without prefix, or null.
 */
export function deviceClassIcon(
  deviceClass: string,
  state: string,
  domain: string,
): string | null {
  if (domain === "binary_sensor") {
    const pair = BINARY_SENSOR_DEVICE_CLASS_ICONS[
      deviceClass
    ];
    if (!pair) return null;
    return state === "on" ? pair[1] : pair[0];
  }
  return SENSOR_DEVICE_CLASS_ICONS[deviceClass] ?? null;
}

// Stores the in-flight or resolved Promise for each URL so
// concurrent loadIcon() calls for the same URL never create
// more than one Image (TOCTOU prevention). Failed entries are
// removed on rejection so the next caller gets a fresh attempt.
const _iconCache = new Map<string, Promise<HTMLImageElement | null>>();

// Populated when a loadIcon() promise resolves successfully.
// getIcon() reads from here so it never needs to await.
const _resolvedIcons = new Map<string, HTMLImageElement>();

/**
 * Load an icon from a URL, returning it from the module-level
 * cache if it was already loaded.
 *
 * The promise is stored before awaiting so concurrent calls
 * for the same URL share one network request.  On decode
 * failure the cache entry is removed, allowing a later retry.
 * Errors are swallowed and null is returned so callers can
 * fall back to placeholder rendering without crashing.
 *
 * @internal Exported for testing only.
 * @param url - Absolute URL path to the icon file.
 * @returns The loaded image, or null on network/decode error.
 */
export function loadIcon(
  url: string,
): Promise<HTMLImageElement | null> {
  const cached = _iconCache.get(url);
  if (cached) return cached;
  const p = (async () => {
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      _resolvedIcons.set(url, img);
      return img;
    } catch {
      // Remove so the next caller can retry.
      _iconCache.delete(url);
      return null;
    }
  })();
  _iconCache.set(url, p);
  return p;
}

/**
 * Synchronous cache lookup for a previously loaded icon.
 *
 * Returns the HTMLImageElement when loadIcon() has already
 * resolved successfully for this URL, otherwise null.  All
 * rendering paths call this after _preloadIcons() so the
 * cache is always warm by the time drawing starts.
 *
 * @internal Exported for testing only.
 * @param url - URL that was passed to loadIcon().
 * @returns The cached image, or null if not yet loaded.
 */
export function getIcon(
  url: string,
): HTMLImageElement | null {
  return _resolvedIcons.get(url) ?? null;
}

/**
 * Clear both icon caches.
 *
 * @internal Exported for testing only.
 */
export function clearIconCache(): void {
  _iconCache.clear();
  _resolvedIcons.clear();
}

/** One column in the weather detail row (humidity, wind, etc.). */
interface DetailItem { text: string; svgName: string; }

const BATTERY_BODY_W = 30;
const BATTERY_BODY_H = 14;
const BATTERY_NUB_W = 3;
const BATTERY_NUB_H = 8;

const PROBLEM_DEVICE_CLASSES = new Set([
  "door", "window", "garage_door", "opening",
  "moisture", "smoke", "problem", "safety",
  "tamper", "vibration",
]);

// Proportional sizing constants for pill-shaped chips.
// All three chip functions must use the same values so
// width measurement and drawing stay in sync.
// Mirrors _CHIP_PAD_RATIO/_CHIP_ICON_RATIO/_CHIP_GAP_RATIO
// from render.py.
/** @internal Exported for testing only. */
export const CHIP_PAD_RATIO = 0.18;
/** @internal Exported for testing only. */
export const CHIP_ICON_RATIO = 0.29;
/** @internal Exported for testing only. */
export const CHIP_GAP_RATIO = 0.14;
/** @internal Exported for testing only. */
export const CHIP_FONT_RATIO = 0.46;

const DAY_ABBREV = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const HANDLE_SIZE = 8;
const HANDLE_HIT_RADIUS = 10;
const GRID = 8;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Scale font_size proportionally by the diagonal distance
 * change during a corner resize drag.
 *
 * @param handle - Corner handle id ("nw"|"ne"|"sw"|"se").
 * @param dx - Horizontal drag delta in canvas pixels.
 * @param dy - Vertical drag delta in canvas pixels.
 * @param startFs - font_size at drag start.
 * @param renderedW - Widget width at drag start.
 * @param renderedH - Widget height at drag start.
 * @param minFs - Minimum allowed font_size.
 * @param maxFs - Maximum allowed font_size.
 * @returns New font_size clamped to [minFs, maxFs].
 */
function diagScaleFontSize(
  handle: string,
  dx: number,
  dy: number,
  startFs: number,
  renderedW: number,
  renderedH: number,
  minFs: number,
  maxFs: number,
): number {
  const sdx = (handle === "ne" || handle === "se")
    ? dx : -dx;
  const sdy = (handle === "nw" || handle === "ne")
    ? -dy : dy;
  const startDiag = Math.sqrt(
    renderedW ** 2 + renderedH ** 2,
  );
  const newDiag = Math.sqrt(
    (renderedW + sdx) ** 2 + (renderedH + sdy) ** 2,
  );
  return Math.max(minFs, Math.min(maxFs,
    Math.round(startFs * newDiag / startDiag)));
}

export function snap(v: number): number { return Math.round(v / GRID) * GRID; }

export function grayColor(v: number): string {
  return `rgb(${v},${v},${v})`;
}

// Parse a raw state string as days-until-today.
// Tries ISO date first, then integer. Returns null on failure.
export function parseDaysUntil(raw: string): number | null {
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    const [y, m, d] = raw.slice(0, 10).split("-").map(Number);
    const target = new Date(y, m - 1, d);
    if (!isNaN(target.getTime())) {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return Math.round((target.getTime() - today.getTime()) / 86400000);
    }
  }
  const n = parseInt(raw, 10);
  return isNaN(n) ? null : n;
}

export function formatRelativeDate(days: number | null, raw: string): string {
  if (days === null || days < 0) return raw;
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

export function buildHeaderText(
  device: { name: string },
): string {
  return device.name || "E-Ink Dashboard";
}

export function shouldShowCopyUrl(model: string, hasWebhooks: boolean): boolean {
  if (model.startsWith("kindle_")) return true;
  if (model === "custom" && !hasWebhooks) return true;
  // TRMNL devices are push-only (always have webhooks); no URL needed.
  return false;
}

/**
 * Compute proportional widget layout dimensions from a row height.
 *
 * Mirrors `_compute_metrics()` from render.py with the same ratio
 * factors and minimum clamps so that canvas previews match the PIL
 * renderer.
 *
 * @param rowH - Height of a single row in pixels.
 * @returns A WidgetMetrics object with all derived pixel sizes.
 */
export function computeMetrics(rowH: number): WidgetMetrics {
  return {
    border: Math.max(2, Math.round(rowH * 0.04)),
    padding: Math.round(rowH * 0.21),
    radius: Math.round(rowH * 0.21),
    iconDia: Math.round(rowH * 0.64),
    fontPrimary: Math.max(10, Math.round(rowH * 0.32)),
    fontSecondary: Math.max(10, Math.round(rowH * 0.25)),
    divider: Math.max(2, Math.round(rowH * 0.07)),
    innerGap: Math.round(rowH * 0.21),
    leftBar: Math.max(2, Math.round(rowH * 0.07)),
  };
}

/**
 * Draw card container decoration and return the
 * content x-offset.
 *
 * Mirrors _draw_card_container() from render.py.
 * Three decoration styles:
 * - "border": rounded rect outline, returns m.padding
 * - "left_bar": filled gray rect on the left edge,
 *   returns barW + m.padding
 * - "none": no decoration, returns 0
 *
 * @param ctx - Canvas 2D rendering context.
 * @param x - Left edge of the card area in pixels.
 * @param y - Top edge of the card area in pixels.
 * @param w - Total width of the card area in pixels.
 * @param h - Total height of the card area in pixels.
 * @param m - Pre-computed layout metrics.
 * @param cardStyle - Card decoration style.
 * @param grayscaleLevels - Display gray levels; when
 *   <= 2 the left bar is widened so the dithered dot
 *   pattern is clearly visible. Defaults to 16.
 * @returns Horizontal pixel offset from x where
 *   content should start.
 */
export function drawCardContainer(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  m: WidgetMetrics,
  cardStyle: CardStyle,
  grayscaleLevels?: number,
): number {
  if (cardStyle === "border") {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, m.radius);
    ctx.strokeStyle = grayColor(COLOR_BLACK);
    ctx.lineWidth = m.border;
    ctx.stroke();
    return m.padding;
  }
  if (cardStyle === "left_bar") {
    let barW = m.leftBar;
    // On 2-level displays (TRMNL), widen the bar so
    // the dithered dot pattern forms a visible stripe.
    if ((grayscaleLevels ?? 16) <= 2) {
      barW = Math.max(10, m.leftBar * 3);
    }
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillRect(x, y, barW, h);
    return barW + m.padding;
  }
  if (cardStyle === "none") {
    return 0;
  }
  console.warn(
    `drawCardContainer: unknown cardStyle ${JSON.stringify(cardStyle)},`
    + " treating as 'none'",
  );
  return 0;
}

/**
 * Draw one row inside a card container.
 *
 * Mirrors _draw_card_row() from render.py. Renders a
 * gray filled icon circle with letter fallback on the
 * left, primary text (Roboto Medium) and optional
 * secondary text (gray) vertically centered in the
 * middle, and an optional right-aligned value string.
 *
 * @param ctx - Canvas 2D rendering context.
 * @param x - Left edge of the row area in pixels.
 * @param y - Top edge of the row area in pixels.
 * @param w - Width of the row area in pixels.
 * @param rowH - Height of the row in pixels.
 * @param m - Pre-computed layout metrics.
 * @param opts - Row content: primary label, optional
 *   secondary sub-label, optional right-aligned value,
 *   and optional icon circle fill color (default gray).
 */
export function drawCardRow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  rowH: number,
  m: WidgetMetrics,
  opts: CardRowOpts,
): void {
  const { primary, secondary, value } = opts;
  const iconFill = opts.iconFill ?? COLOR_GRAY;

  // Icon circle — vertically centered in the row
  const iconX = x + m.padding;
  const circleY = y + Math.floor((rowH - m.iconDia) / 2);
  const cx = iconX + m.iconDia / 2;
  const cy = circleY + m.iconDia / 2;
  ctx.beginPath();
  ctx.arc(cx, cy, m.iconDia / 2, 0, 2 * Math.PI);
  ctx.fillStyle = grayColor(iconFill);
  ctx.fill();

  if (opts.icon) {
    // Icon image: 60% of circle diameter, centred — mirrors
    // the icon_sz = round(m.icon_dia * 0.6) ratio in
    // _draw_card_row() in render.py.
    const iconSz = Math.round(m.iconDia * 0.6);
    const offset = Math.floor((m.iconDia - iconSz) / 2);
    ctx.drawImage(
      opts.icon,
      iconX + offset,
      circleY + offset,
      iconSz, iconSz,
    );
  } else {
    // Letter fallback: first char of primary, white on
    // the gray circle, centered inside it.
    const letter = primary[0]?.toUpperCase() ?? "?";
    const letterSz = Math.round(m.iconDia * 0.5);
    ctx.font = `${letterSz}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    const lm = ctx.measureText(letter);
    const lw = lm.width;
    const lh = lm.actualBoundingBoxAscent
      + lm.actualBoundingBoxDescent;
    ctx.fillStyle = grayColor(COLOR_WHITE);
    ctx.fillText(
      letter,
      iconX + Math.floor((m.iconDia - lw) / 2),
      circleY + Math.floor((m.iconDia - lh) / 2),
    );
  }

  // Text block starts right of the icon + gap
  const textX = iconX + m.iconDia + m.innerGap;

  ctx.textBaseline = "top";
  if (secondary) {
    // Primary + secondary: compute combined block
    // height, then vertically center the block.
    ctx.font = `500 ${m.fontPrimary}px ${FONT_FAMILY}`;
    const pm = ctx.measureText(primary);
    const pH = pm.actualBoundingBoxAscent
      + pm.actualBoundingBoxDescent;

    ctx.font = `${m.fontSecondary}px ${FONT_FAMILY}`;
    const sm = ctx.measureText(secondary);
    const sH = sm.actualBoundingBoxAscent
      + sm.actualBoundingBoxDescent;

    // Small gap between the two text lines, matching
    // the Python line_gap formula.
    const lineGap = Math.max(2, Math.round(rowH * 0.04));
    const blockH = pH + lineGap + sH;
    const textY = y + Math.floor((rowH - blockH) / 2);

    ctx.font = `500 ${m.fontPrimary}px ${FONT_FAMILY}`;
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(primary, textX, textY);

    ctx.font = `${m.fontSecondary}px ${FONT_FAMILY}`;
    ctx.fillStyle = grayColor(
      opts.secondaryFill ?? COLOR_GRAY,
    );
    ctx.fillText(secondary, textX, textY + pH + lineGap);
  } else {
    // Primary only — vertically center it alone.
    ctx.font = `500 ${m.fontPrimary}px ${FONT_FAMILY}`;
    const pm = ctx.measureText(primary);
    const pH = pm.actualBoundingBoxAscent
      + pm.actualBoundingBoxDescent;
    const textY = y + Math.floor((rowH - pH) / 2);
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(primary, textX, textY);
  }

  // Right-aligned value, vertically centered
  if (value) {
    ctx.font = `${m.fontSecondary}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    const vm = ctx.measureText(value);
    const vw = vm.width;
    const vh = vm.actualBoundingBoxAscent
      + vm.actualBoundingBoxDescent;
    ctx.fillStyle = grayColor(opts.valueFill ?? COLOR_GRAY);
    ctx.fillText(
      value,
      x + w - m.padding - vw,
      y + Math.floor((rowH - vh) / 2),
    );
  }
}

/**
 * Compute the total pixel width of a pill-shaped chip.
 *
 * Single source of truth for the chip width formula,
 * shared by drawChip() (drawing) and drawChipFlow()
 * (wrapping).  All dimensions are proportional to h.
 * Uses Math.floor() on the text width to match Python's
 * int() truncation in _chip_width().
 *
 * @param ctx - Canvas 2D context used for text
 *   measurement.
 * @param h - Chip height in pixels.
 * @param text - Label text inside the chip.
 * @param fontSize - Font size in pixels for measurement.
 * @param hasIcon - Whether the chip includes an icon.
 * @returns Total chip width in pixels.
 */
export function chipWidth(
  ctx: CanvasRenderingContext2D,
  h: number,
  text: string,
  fontSize: number,
  hasIcon: boolean,
): number {
  ctx.font = `${fontSize}px ${FONT_FAMILY}`;
  const textW = Math.floor(ctx.measureText(text).width);
  const padH = Math.round(h * CHIP_PAD_RATIO);
  const iconSz = hasIcon
    ? Math.round(h * CHIP_ICON_RATIO) : 0;
  const iconGap = hasIcon
    ? Math.round(h * CHIP_GAP_RATIO) : 0;
  return padH * 2 + textW + iconSz + iconGap;
}

/**
 * Draw a pill-shaped chip and return the x coordinate
 * after it.
 *
 * Renders a rounded-rectangle container whose end-caps
 * are perfect semicircles (radius = floor(h / 2)).  The
 * chip width is computed from text measurement plus
 * horizontal padding and, when an icon image is given,
 * the icon area sized to CHIP_ICON_RATIO * h.  All
 * internal dimensions are proportional to h.
 *
 * Mirrors _draw_chip() from render.py.
 *
 * @param ctx - Canvas 2D rendering context.
 * @param x - Left edge of the chip in pixels.
 * @param y - Top edge of the chip in pixels.
 * @param h - Chip height in pixels.
 * @param text - Label text drawn inside the chip.
 * @param fontSize - Font size in pixels.
 * @param border - Outline stroke width in pixels.
 * @param opts - Optional: inverted mode and loaded icon
 *   image.
 * @returns The x coordinate immediately to the right of
 *   the chip (x + chipW), suitable for the next chip.
 */
export function drawChip(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  h: number,
  text: string,
  fontSize: number,
  border: number,
  opts?: ChipOpts,
): number {
  const inverted = opts?.inverted ?? false;
  const icon = opts?.icon;
  const chipW = chipWidth(
    ctx, h, text, fontSize, icon != null,
  );
  const padH = Math.round(h * CHIP_PAD_RATIO);
  const iconSz = icon != null
    ? Math.round(h * CHIP_ICON_RATIO) : 0;
  const iconGap = icon != null
    ? Math.round(h * CHIP_GAP_RATIO) : 0;
  // Pill shape: radius = floor(h/2) produces
  // perfect semicircle end-caps.
  const radius = Math.floor(h / 2);

  const bg = inverted ? COLOR_BLACK : COLOR_WHITE;
  const fg = inverted ? COLOR_WHITE : COLOR_BLACK;

  // Canvas requires separate fill + stroke so the fill
  // does not overdraw the border pixels.  Python's
  // rounded_rectangle() handles this in one call.
  ctx.beginPath();
  ctx.roundRect(x, y, chipW, h, radius);
  ctx.fillStyle = grayColor(bg);
  ctx.fill();
  ctx.strokeStyle = grayColor(COLOR_BLACK);
  ctx.lineWidth = border;
  ctx.stroke();

  let cx = x + padH;
  if (icon != null) {
    const iconY = y + Math.floor((h - iconSz) / 2);
    if (inverted) {
      // ctx.filter = "invert(1)" flips black icon pixels
      // to white, matching Python's ImageOps.invert() in
      // _draw_chip() for problem/urgent states.
      ctx.save();
      ctx.filter = "invert(1)";
      ctx.drawImage(icon, cx, iconY, iconSz, iconSz);
      ctx.restore();
    } else {
      ctx.drawImage(icon, cx, iconY, iconSz, iconSz);
    }
    cx += iconSz + iconGap;
  }

  // Vertically center text using measured glyph height
  // (not nominal font size, which includes
  // ascender/descender whitespace that would shift the
  // visible glyph upward).
  ctx.font = `${fontSize}px ${FONT_FAMILY}`;
  ctx.textBaseline = "top";
  const tm = ctx.measureText(text);
  const textH = tm.actualBoundingBoxAscent
    + tm.actualBoundingBoxDescent;
  const textY = y + Math.floor((h - textH) / 2);
  ctx.fillStyle = grayColor(fg);
  ctx.fillText(text, cx, textY);

  return x + chipW;
}

/**
 * Lay out chips in a horizontal flow with wrapping.
 *
 * Draws each chip left-to-right.  When a chip would
 * extend past x + w, it wraps to the next line.  The
 * first chip on a new line is never skipped — a chip
 * wider than w is drawn at the left edge and overflows.
 *
 * Mirrors _draw_chip_flow() from render.py.
 *
 * @param ctx - Canvas 2D rendering context.
 * @param x - Left edge of the flow container.
 * @param y - Top edge of the flow container.
 * @param w - Maximum width of the flow container.
 * @param h - Height of each chip row in pixels.
 * @param chips - Array of chip descriptors (text,
 *   optional inverted, optional icon identifier).
 * @param fontSize - Font size in pixels.
 * @param border - Outline stroke width in pixels.
 * @returns The y coordinate at the bottom of the last
 *   chip row (last_row_y + h).
 */
export function drawChipFlow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  chips: ChipDescriptor[],
  fontSize: number,
  border: number,
): number {
  if (chips.length === 0) {
    // Nothing drawn: don't advance y.
    return y;
  }
  // Chip-to-chip gap — same ratio as icon size, by design.
  const gap = Math.round(h * CHIP_ICON_RATIO);
  let curX = x;
  let curY = y;
  for (const chip of chips) {
    const cw = chipWidth(
      ctx, h, chip.text, fontSize, chip.icon != null,
    );
    // Add inter-chip gap and wrap when the chip would
    // overflow.  The gap is skipped for the first chip
    // on each line (curX === x).
    if (curX > x) {
      if (curX + gap + cw > x + w) {
        curX = x;
        curY += h + gap;
      } else {
        curX += gap;
      }
    }
    curX = drawChip(
      ctx, curX, curY, h, chip.text,
      fontSize, border,
      { inverted: chip.inverted, icon: chip.icon },
    );
  }
  return curY + h;
}

// ── Card class ────────────────────────────────────────────────────────────────

interface CardConfig {
  config_entry?: string;
}

interface DragStart {
  x: number;
  y: number;
  x2?: number;
  y2?: number;
}

interface ResizeStart {
  x: number;
  y: number;
  x2: number;
  y2: number;
  w?: number;
  h?: number;
  font_size?: number;
  renderedW?: number;
  renderedH?: number;
  /** Effective (computed) length for separator resize math. */
  length?: number;
  /** Raw widget.length before resize (undefined = default span). */
  rawLength?: number;
}

type MutableWidget = Widget & { x2?: number; y2?: number };

class EinkDashboardCard extends HTMLElement {
  private _config: CardConfig | null = null;
  private _hass: HomeAssistant | null = null;
  private _layout: LayoutResponse | null = null;
  private _canvas: HTMLCanvasElement | null = null;
  private _ctx: CanvasRenderingContext2D | null = null;
  private _offscreen: OffscreenCanvas | null = null;
  private _offCtx: CanvasRenderingContext2D | null = null;
  private _renderPending = false;
  private _renderInProgress = false;
  private _connected = false;
  private _fetching = false;
  private _fetchGeneration = 0;
  private _showServerImage = false;
  private _serverImg: HTMLImageElement | null = null;
  private _container!: HTMLElement;
  private _toggleBtn!: HTMLButtonElement;
  private _editMode = false;
  private _editor: EinkEditorElement | null = null;
  private _editorContainer!: HTMLElement;
  private _editBtn!: HTMLButtonElement;
  private _saving = false;
  private _saveError!: HTMLElement;
  private _widgetBounds: IndexedBounds[] = [];
  private _dragIndex = -1;
  private _dragStartCX = 0;
  private _dragStartCY = 0;
  private _dragWidgetStart: DragStart | null = null;
  private _hoverIndex = -1;
  private _resizeIndex = -1;
  private _resizeHandle: string | null = null;
  private _resizeStartCX = 0;
  private _resizeStartCY = 0;
  private _resizeWidgetStart: ResizeStart | null = null;
  private _forecasts: Record<string, ForecastDay[]> = {};
  private _resolvedEntryId: string | undefined;
  private _headerEl!: HTMLElement;
  private _copyBtn!: HTMLButtonElement;
  private _copyTimeout: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  // ── Lovelace lifecycle ────────────────────────────────────────────────────

  setConfig(config: CardConfig): void {
    const entryChanged = this._config && this._config.config_entry !== config.config_entry;
    this._config = config;
    this._buildShadowDom();
    if (entryChanged) {
      this._layout = null;
      this._canvas = null;
      this._ctx = null;
      this._offscreen = null;
      this._offCtx = null;
      this._serverImg = null;
      this._fetching = false;
      this._fetchGeneration++;
      this._showServerImage = false;
      this._editMode = false;
      this._editor = null;
      if (this._copyTimeout) { clearTimeout(this._copyTimeout); this._copyTimeout = null; }
    }
  }

  set hass(hass: HomeAssistant) {
    this._hass = hass;
    if (this._editor) {
      this._editor.hass = hass;
    }
    if (this._config && !this._layout && !this._fetching) {
      this._fetchLayout();
    }
    if (this._layout) {
      this._scheduleRender();
      const newHeader = buildHeaderText(this._layout.device);
      if (this._headerEl.textContent !== newHeader) {
        this._headerEl.textContent = newHeader;
      }
    }
  }

  connectedCallback(): void {
    this._connected = true;
    if (this._layout) {
      this._scheduleRender();
    } else if (this._hass && this._config) {
      this._fetchLayout();
    }
  }

  disconnectedCallback(): void {
    this._connected = false;
    this._fetchGeneration++;
    this._fetching = false;
  }

  getCardSize(): number {
    if (this._layout) {
      return Math.ceil(this._layout.display.height / 50);
    }
    return 8;
  }

  // ── Shadow DOM ────────────────────────────────────────────────────────────

  private _buildShadowDom(): void {
    this.shadowRoot!.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { display: block; overflow: hidden; }
        .container {
          position: relative;
          width: 100%;
          background: #fff;
        }
        .loading, .error {
          padding: 16px;
          color: var(--secondary-text-color, #888);
          font-size: 14px;
        }
        .error { color: var(--error-color, #b00020); }
        canvas {
          display: block;
          width: 100%;
          height: auto;
          image-rendering: pixelated;
        }
        img.server-render {
          display: block;
          width: 100%;
          height: auto;
        }
        .toolbar {
          display: flex;
          justify-content: flex-end;
          gap: 6px;
          padding: 4px 8px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          background: var(--card-background-color, #fff);
        }
        .toggle-btn {
          font-size: 12px;
          padding: 4px 8px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 4px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
        }
        .toggle-btn.active {
          background: var(--primary-color, #03a9f4);
          color: #fff;
          border-color: var(--primary-color, #03a9f4);
        }
        .editor-container {
          border-top: 1px solid var(--divider-color, #e0e0e0);
          max-height: 520px;
          overflow-y: auto;
        }
        .save-error {
          padding: 8px 12px;
          color: var(--error-color, #b00020);
          font-size: 13px;
          background: var(--secondary-background-color, #fff3f3);
          border-top: 1px solid var(--error-color, #b00020);
          display: none;
        }
        .card-header {
          padding: 12px 16px 4px;
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
          line-height: 1.2;
        }
        .copy-btn {
          font-size: 12px;
          padding: 4px 8px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 4px;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
        }
        .copy-btn.copied {
          background: var(--success-color, #4caf50);
          color: #fff;
          border-color: var(--success-color, #4caf50);
        }
      </style>
      <ha-card>
        <div class="card-header"></div>
        <div class="container">
          <div class="loading">Loading layout…</div>
        </div>
        <div class="toolbar">
          <button class="copy-btn" style="display:none" title="Copy image URL to clipboard">
            Copy image URL
          </button>
          <button class="toggle-btn" title="Toggle between canvas preview and server-rendered image">
            Show rendered image
          </button>
          <button class="toggle-btn edit-btn" title="Edit widget layout">
            Edit Widgets
          </button>
        </div>
        <div class="editor-container" style="display:none"></div>
        <div class="save-error"></div>
      </ha-card>
    `;
    this._container = this.shadowRoot!.querySelector<HTMLElement>(".container")!;
    this._toggleBtn = this.shadowRoot!.querySelector<HTMLButtonElement>(".toggle-btn")!;
    this._toggleBtn.addEventListener("click", () => this._onToggle());
    this._editBtn = this.shadowRoot!.querySelector<HTMLButtonElement>(".edit-btn")!;
    this._editBtn.addEventListener("click", () => this._onToggleEdit());
    this._editorContainer = this.shadowRoot!.querySelector<HTMLElement>(".editor-container")!;
    this._saveError = this.shadowRoot!.querySelector<HTMLElement>(".save-error")!;
    this._headerEl = this.shadowRoot!.querySelector<HTMLElement>(".card-header")!;
    this._copyBtn = this.shadowRoot!.querySelector<HTMLButtonElement>(".copy-btn")!;
    this._copyBtn.addEventListener("click", () => this._onCopyUrl());
  }

  // ── Edit mode ─────────────────────────────────────────────────────────────

  private async _ensureEditorLoaded(): Promise<void> {
    if (customElements.get("eink-dashboard-editor")) return;
    const script = document.createElement("script");
    script.type = "module";
    script.src = "/eink_dashboard/frontend/eink-dashboard-editor.js";
    document.head.appendChild(script);
    await customElements.whenDefined("eink-dashboard-editor");
  }

  private async _onToggleEdit(): Promise<void> {
    if (!this._layout) return;
    this._editMode = !this._editMode;
    if (this._editMode) {
      await this._ensureEditorLoaded();
      this._editBtn.textContent = "Close Editor";
      this._editBtn.classList.add("active");
      this._editorContainer.style.display = "block";
      if (!this._editor) {
        this._editor = document.createElement("eink-dashboard-editor") as unknown as EinkEditorElement;
        this._editor.addEventListener(
          "widget-change", (ev) => this._onWidgetChange(ev as CustomEvent<{ widgets: Widget[] }>)
        );
        this._editor.addEventListener(
          "save", (ev) => this._onSave(ev as CustomEvent<{ widgets: Widget[] }>)
        );
        this._editor.setWidgets(this._layout.widgets);
        this._editor.setDisplay(this._layout.display);
        this._editorContainer.appendChild(this._editor);
      }
      if (this._hass) this._editor.hass = this._hass;
    } else {
      this._editBtn.textContent = "Edit Widgets";
      this._editBtn.classList.remove("active");
      this._editorContainer.style.display = "none";
    }
  }

  private _onWidgetChange(ev: CustomEvent<{ widgets: Widget[] }>): void {
    this._layout!.widgets = ev.detail.widgets;
    this._scheduleRender();
  }

  private async _onSave(ev: CustomEvent<{ widgets: Widget[] }>): Promise<void> {
    if (this._saving) return;
    this._saving = true;
    try {
      const entryId = this._resolvedEntryId;
      await this._hass!.callApi(
        "POST",
        `eink_dashboard/${entryId}/layout`,
        ev.detail.widgets,
      );
      await this._fetchLayout();
      if (this._editor && this._layout) {
        this._editor.setWidgets(this._layout.widgets);
        this._editor.setDisplay(this._layout.display);
      }
      this._saveError.style.display = "none";
    } catch (err) {
      console.error("Failed to save layout:", err);
      this._saveError.textContent = `Save failed: ${(err as Error).message || err}`;
      this._saveError.style.display = "block";
    } finally {
      this._saving = false;
    }
  }

  // ── Config entry resolution ────────────────────────────────────────────────

  private async _resolveEntryId(): Promise<string> {
    const configured = this._config!.config_entry;
    if (configured && !configured.includes(".")) {
      return configured;
    }
    const entries = await this._hass!.callWS<ConfigEntry[]>({
      type: "config_entries/get",
      domain: "eink_dashboard",
    });
    if (!entries || entries.length === 0) {
      throw new Error("No eink_dashboard config entries found");
    }
    if (configured) {
      const match = entries.find((e) => e.entry_id === configured);
      if (match) return match.entry_id;
    }
    return entries[0].entry_id;
  }

  // ── Layout fetch ──────────────────────────────────────────────────────────

  private async _fetchLayout(): Promise<void> {
    const gen = ++this._fetchGeneration;
    this._fetching = true;
    try {
      await _loadRoboto();
      await _loadRobotoMedium();
      if (gen !== this._fetchGeneration) return;

      const entryId = await this._resolveEntryId();
      if (gen !== this._fetchGeneration) return;
      this._resolvedEntryId = entryId;

      const resp = await this._hass!.callApi<LayoutResponse>(
        "GET",
        `eink_dashboard/${entryId}/layout`,
      );
      if (gen !== this._fetchGeneration) return;
      this._layout = resp;
      this._headerEl.textContent = buildHeaderText(resp.device);
      this._copyBtn.style.display = shouldShowCopyUrl(
        resp.device.model,
        resp.device.has_webhooks,
      ) ? "" : "none";
      this._initCanvas();
      this._fetchForecasts();
      this._scheduleRender();
    } catch (err) {
      if (gen !== this._fetchGeneration) return;
      const div = document.createElement("div");
      div.className = "error";
      div.textContent = `Failed to load layout: ${(err as Error).message}`;
      this._container.replaceChildren(div);
    } finally {
      if (gen === this._fetchGeneration) {
        this._fetching = false;
      }
    }
  }

  private async _fetchForecasts(): Promise<void> {
    if (!this._layout || !this._hass) return;
    const gen = this._fetchGeneration;
    for (const w of this._layout.widgets) {
      if (w.type !== "weather" || !w.entity) continue;
      if (gen !== this._fetchGeneration) return;
      try {
        const resp = await this._hass.callService<ForecastServiceResult>(
          "weather", "get_forecasts",
          { entity_id: w.entity, type: "daily" },
          undefined, false, true,
        );
        if (gen !== this._fetchGeneration) return;
        const forecast = resp?.response?.[w.entity]?.forecast;
        if (forecast) {
          this._forecasts[w.entity] = forecast;
          this._scheduleRender();
        }
      } catch (_) { /* forecast unavailable */ }
    }
  }

  private _initCanvas(): void {
    const { width, height } = this._layout!.display;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    canvas.style.touchAction = "none";
    this._canvas = canvas;
    const ctx2d = canvas.getContext("2d");
    if (!ctx2d) throw new Error("2D context unavailable");
    this._ctx = ctx2d;

    // Offscreen canvas for double-buffered rendering: draw
    // here first, then blit the completed frame onto the
    // visible canvas in a single drawImage() call so no
    // intermediate state is ever visible to the user.
    // Dimensions always match the visible canvas — both are
    // created here together in _initCanvas.
    const offscreen = new OffscreenCanvas(width, height);
    const offCtx2d = offscreen.getContext("2d");
    if (!offCtx2d) throw new Error("2D context unavailable");
    this._offscreen = offscreen;
    // Cast: OffscreenCanvasRenderingContext2D shares all
    // drawing APIs with CanvasRenderingContext2D; the two
    // DOM-only methods we don't use are the only difference.
    this._offCtx = offCtx2d as unknown as CanvasRenderingContext2D;

    canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    canvas.addEventListener("pointerup", (e) => this._onPointerUp(e));
    canvas.addEventListener("pointercancel", () => this._onPointerCancel());
    canvas.addEventListener("pointerleave", () => this._onPointerLeave());

    const img = document.createElement("img");
    img.className = "server-render";
    img.style.display = "none";
    this._serverImg = img;

    this._container.innerHTML = "";
    this._container.appendChild(canvas);
    this._container.appendChild(img);
  }

  // ── Drag-to-reposition ────────────────────────────────────────────────────

  private _canvasCoords(event: PointerEvent): { x: number; y: number } {
    const rect = this._canvas!.getBoundingClientRect();
    const scaleX = this._canvas!.width / rect.width;
    const scaleY = this._canvas!.height / rect.height;
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  private _hitTest(cx: number, cy: number): number {
    for (let i = this._widgetBounds.length - 1; i >= 0; i--) {
      const b = this._widgetBounds[i];
      if (cx >= b.x && cx <= b.x + b.w && cy >= b.y && cy <= b.y + b.h) {
        return b.index;
      }
    }
    return -1;
  }

  private _getHandles(bounds: WidgetBounds, widget: Widget): Handle[] {
    if (widget.type === "separator") {
      const dir = (widget as SeparatorWidget).direction ?? "horizontal";
      if (dir === "vertical") {
        // Handles at the top and bottom centre of the bar.
        const hcx = bounds.x + bounds.w / 2;
        return [
          { id: "start", cx: hcx, cy: bounds.y },
          { id: "end",   cx: hcx, cy: bounds.y + bounds.h },
        ];
      }
      // Horizontal: handles at the left and right centre.
      const hcy = bounds.y + bounds.h / 2;
      return [
        { id: "start", cx: bounds.x,           cy: hcy },
        { id: "end",   cx: bounds.x + bounds.w, cy: hcy },
      ];
    }
    if (widget.type === "device_battery") {
      const bw = widget as DeviceBatteryWidget;
      if (bw.layout === "chip") {
        return [
          { id: "nw", cx: bounds.x, cy: bounds.y },
          { id: "ne", cx: bounds.x + bounds.w, cy: bounds.y },
          { id: "sw", cx: bounds.x, cy: bounds.y + bounds.h },
          { id: "se", cx: bounds.x + bounds.w, cy: bounds.y + bounds.h },
        ];
      }
      return [
        { id: "se", cx: bounds.x + bounds.w, cy: bounds.y + bounds.h },
      ];
    }
    return [
      { id: "nw", cx: bounds.x, cy: bounds.y },
      { id: "ne", cx: bounds.x + bounds.w, cy: bounds.y },
      { id: "sw", cx: bounds.x, cy: bounds.y + bounds.h },
      { id: "se", cx: bounds.x + bounds.w, cy: bounds.y + bounds.h },
    ];
  }

  private _handleHitTest(cx: number, cy: number): { index: number; handleId: string } | null {
    for (let i = this._widgetBounds.length - 1; i >= 0; i--) {
      const b = this._widgetBounds[i];
      const widget = this._layout!.widgets[b.index];
      for (const h of this._getHandles(b, widget)) {
        const dx = cx - h.cx;
        const dy = cy - h.cy;
        if (dx * dx + dy * dy <= HANDLE_HIT_RADIUS * HANDLE_HIT_RADIUS) {
          return { index: b.index, handleId: h.id };
        }
      }
    }
    return null;
  }

  private _getResizeCursor(handleId: string, widget?: Widget): string {
    if (handleId === "p1" || handleId === "p2") return "crosshair";
    if (widget?.type === "separator") {
      const dir = (widget as SeparatorWidget).direction ?? "horizontal";
      return dir === "vertical" ? "ns-resize" : "ew-resize";
    }
    if (
      widget?.type === "device_battery"
      || widget?.type === "weather"
    ) return "nwse-resize";
    if (widget?.type === "sensor_rows") return "nwse-resize";
    return "ew-resize";
  }

  private _onPointerDown(event: PointerEvent): void {
    if (!this._editMode || this._showServerImage || !this._layout) return;
    const { x: cx, y: cy } = this._canvasCoords(event);

    const handleHit = this._handleHitTest(cx, cy);
    if (handleHit) {
      event.preventDefault();
      this._canvas!.setPointerCapture(event.pointerId);
      const w = this._layout.widgets[handleHit.index] as MutableWidget;
      this._resizeIndex = handleHit.index;
      this._resizeHandle = handleHit.handleId;
      this._resizeStartCX = cx;
      this._resizeStartCY = cy;
      const wb = this._widgetBounds.find(b => b.index === handleHit.index);
      const s: ResizeStart = {
        x: w.x ?? 0, y: w.y ?? 0,
        x2: w.x2 ?? 0, y2: w.y2 ?? 0,
        w: w.w, h: w.h,
        font_size: w.font_size,
        renderedW: wb?.w,
        renderedH: wb?.h,
      };
      if (w.type === "separator") {
        const sw = w as SeparatorWidget;
        const { width: dw, height: dh } = this._layout!.display;
        const dir = sw.direction ?? "horizontal";
        s.rawLength = sw.length;
        // Compute the effective length so resize math has a concrete
        // starting value even when the widget uses the default full span.
        s.length = sw.length ?? (dir === "vertical"
          ? dh - PADDING - (sw.y ?? 0)
          : dw - PADDING - (sw.x ?? PADDING));
      }
      this._resizeWidgetStart = s;
      this._canvas!.style.cursor = this._getResizeCursor(handleHit.handleId, w);
      return;
    }

    const idx = this._hitTest(cx, cy);
    if (idx < 0) return;
    event.preventDefault();
    this._canvas!.setPointerCapture(event.pointerId);
    const w = this._layout.widgets[idx] as MutableWidget;
    this._dragIndex = idx;
    this._dragStartCX = cx;
    this._dragStartCY = cy;
    this._dragWidgetStart = {
      x: w.x ?? 0,
      y: w.y ?? 0,
      x2: w.x2,
      y2: w.y2,
    };
    this._canvas!.style.cursor = "grabbing";
  }

  private _onPointerMove(event: PointerEvent): void {
    if (!this._editMode || this._showServerImage || !this._layout) return;
    const { x: cx, y: cy } = this._canvasCoords(event);

    if (this._resizeIndex >= 0) {
      event.preventDefault();
      const dx = Math.round(cx - this._resizeStartCX);
      const dy = Math.round(cy - this._resizeStartCY);
      const w = this._layout.widgets[this._resizeIndex] as MutableWidget;
      const s = this._resizeWidgetStart!;
      const { width: dw, height: dh } = this._layout.display;
      const handle = this._resizeHandle!;

      if (handle === "p1") {
        w.x = snap(Math.max(0, Math.min(dw - 1, s.x + dx)));
        w.y = snap(Math.max(0, Math.min(dh - 1, s.y + dy)));
      } else if (handle === "p2") {
        w.x2 = snap(Math.max(0, Math.min(dw - 1, s.x2 + dx)));
        w.y2 = snap(Math.max(0, Math.min(dh - 1, s.y2 + dy)));
      } else if (w.type === "separator") {
        const sw = w as SeparatorWidget;
        const dir = sw.direction ?? "horizontal";
        const sLen = s.length ?? 0;
        if (handle === "start") {
          if (dir === "vertical") {
            // Keep end fixed: move start up/down and stretch length.
            const endY = s.y + sLen;
            const newY = snap(Math.max(0, Math.min(endY - 20, s.y + dy)));
            sw.y = newY;
            sw.length = endY - newY;
          } else {
            // Keep end fixed: move start left/right and stretch length.
            const endX = s.x + sLen;
            const newX = snap(Math.max(0, Math.min(endX - 20, s.x + dx)));
            sw.x = newX;
            sw.length = endX - newX;
          }
        } else if (handle === "end") {
          // Move end only: adjust length along the primary axis.
          const delta = dir === "vertical" ? dy : dx;
          sw.length = snap(Math.max(20, sLen + delta));
        }
      } else if (
        w.type === "device_battery"
        && (w as DeviceBatteryWidget).layout === "chip"
      ) {
        const startW = s.w ?? 200;
        const startH = s.h ?? 40;
        if (handle === "se") {
          w.w = snap(Math.max(50, startW + dx));
          w.h = snap(Math.max(28, startH + dy));
        } else if (handle === "ne") {
          w.w = snap(Math.max(50, startW + dx));
          const newY = snap(Math.max(0, (s.y ?? 0) + dy));
          w.y = newY;
          w.h = snap(Math.max(28, startH + ((s.y ?? 0) - newY)));
        } else if (handle === "sw") {
          const newX = snap(Math.max(0, (s.x ?? 0) + dx));
          w.x = newX;
          w.w = snap(Math.max(50, startW + ((s.x ?? 0) - newX)));
          w.h = snap(Math.max(28, startH + dy));
        } else if (handle === "nw") {
          const newX = snap(Math.max(0, (s.x ?? 0) + dx));
          const newY = snap(Math.max(0, (s.y ?? 0) + dy));
          w.x = newX;
          w.y = newY;
          w.w = snap(Math.max(50, startW + ((s.x ?? 0) - newX)));
          w.h = snap(Math.max(28, startH + ((s.y ?? 0) - newY)));
        }
      } else if (
        w.type === "device_battery"
        && s.renderedW != null
        && s.renderedH != null
      ) {
        w.font_size = diagScaleFontSize(
          handle, dx, dy,
          s.font_size ?? FONT_SIZE_DEVICE_BATTERY,
          s.renderedW, s.renderedH,
          MIN_RESIZE_FONT_SIZE, MAX_RESIZE_FONT_SIZE,
        );
      } else if (
        w.type === "weather"
        && s.renderedW != null
        && s.renderedH != null
      ) {
        w.font_size = diagScaleFontSize(
          handle, dx, dy,
          s.font_size ?? FONT_SIZE_WEATHER,
          s.renderedW, s.renderedH,
          MIN_RESIZE_FONT_SIZE, MAX_RESIZE_FONT_SIZE,
        );
      } else if (w.type === "sensor_rows") {
        // Corner resize adjusting w and h directly.
        const startW = s.w ?? 400;
        const startH = s.h ?? 112;
        if (handle === "se") {
          w.w = snap(Math.max(50, startW + dx));
          w.h = snap(Math.max(28, startH + dy));
        } else if (handle === "ne") {
          w.w = snap(Math.max(50, startW + dx));
          w.h = snap(Math.max(28, startH - dy));
          w.y = snap(s.y + (startH - (w.h ?? startH)));
        } else if (handle === "sw") {
          const startRight = s.x + startW;
          const newX = Math.max(
            0, Math.min(startRight - 50, s.x + dx),
          );
          w.x = snap(Math.round(newX));
          w.w = snap(
            Math.round(startRight - (w.x ?? 0)),
          );
          w.h = snap(Math.max(28, startH + dy));
        } else if (handle === "nw") {
          const startRight = s.x + startW;
          const newX = Math.max(
            0, Math.min(startRight - 50, s.x + dx),
          );
          w.x = snap(Math.round(newX));
          w.w = snap(
            Math.round(startRight - (w.x ?? 0)),
          );
          w.h = snap(Math.max(28, startH - dy));
          w.y = snap(s.y + (startH - (w.h ?? startH)));
        }
      } else if (handle === "ne" || handle === "se") {
        const startRight = s.x + (s.w ?? (dw - PADDING - s.x));
        const newRight = Math.max(s.x + 20, Math.min(dw, startRight + dx));
        w.w = snap(Math.round(newRight - s.x));
      } else if (handle === "nw" || handle === "sw") {
        const startRight = s.x + (s.w ?? (dw - PADDING - s.x));
        const newX = Math.max(0, Math.min(startRight - 20, s.x + dx));
        w.x = snap(Math.round(newX));
        w.w = snap(Math.round(startRight - (w.x ?? 0)));
      }
      this._scheduleRender();
      return;
    }

    if (this._dragIndex >= 0) {
      event.preventDefault();
      const dx = Math.round(cx - this._dragStartCX);
      const dy = Math.round(cy - this._dragStartCY);
      const w = this._layout.widgets[this._dragIndex] as MutableWidget;
      const s = this._dragWidgetStart!;
      const { width, height } = this._layout.display;
      w.x = snap(Math.max(0, Math.min(width - 1, s.x + dx)));
      w.y = snap(Math.max(0, Math.min(height - 1, s.y + dy)));
      if (s.x2 !== undefined) {
        w.x2 = snap(Math.max(0, Math.min(width - 1, s.x2 + dx)));
        w.y2 = snap(Math.max(0, Math.min(height - 1, (s.y2 ?? 0) + dy)));
      }
      this._scheduleRender();
    } else {
      const handleHit = this._handleHitTest(cx, cy);
      if (handleHit) {
        if (this._hoverIndex !== handleHit.index) {
          this._hoverIndex = handleHit.index;
          this._scheduleRender();
        }
        this._canvas!.style.cursor = this._getResizeCursor(
          handleHit.handleId,
          this._layout!.widgets[handleHit.index]
        );
        return;
      }
      const hoverIdx = this._hitTest(cx, cy);
      if (hoverIdx !== this._hoverIndex) {
        this._hoverIndex = hoverIdx;
        this._canvas!.style.cursor = hoverIdx >= 0 ? "grab" : "";
        this._scheduleRender();
      }
    }
  }

  private _onPointerUp(event: PointerEvent): void {
    if (this._resizeIndex >= 0) {
      this._canvas!.releasePointerCapture(event.pointerId);
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._hoverIndex = -1;
      this._canvas!.style.cursor = "";
      this._scheduleRender();
      if (this._editor) {
        this._editor.setWidgets(this._layout!.widgets);
      }
      return;
    }
    if (this._dragIndex < 0) return;
    this._canvas!.releasePointerCapture(event.pointerId);
    this._dragIndex = -1;
    this._dragWidgetStart = null;
    this._hoverIndex = -1;
    this._canvas!.style.cursor = "";
    this._scheduleRender();
    if (this._editor) {
      this._editor.setWidgets(this._layout!.widgets);
    }
  }

  private _onPointerCancel(): void {
    if (this._resizeIndex >= 0) {
      const w = this._layout!.widgets[this._resizeIndex] as MutableWidget;
      const s = this._resizeWidgetStart!;
      w.x = s.x;
      w.y = s.y;
      w.w = s.w;
      w.h = s.h;
      w.x2 = s.x2;
      w.y2 = s.y2;
      w.font_size = s.font_size;
      if (w.type === "separator") {
        (w as SeparatorWidget).length = s.rawLength;
      }
      this._resizeIndex = -1;
      this._resizeHandle = null;
      this._resizeWidgetStart = null;
      this._hoverIndex = -1;
      this._canvas!.style.cursor = "";
      this._scheduleRender();
      return;
    }
    if (this._dragIndex < 0) return;
    const wd = this._layout!.widgets[this._dragIndex] as MutableWidget;
    const sd = this._dragWidgetStart!;
    wd.x = sd.x;
    wd.y = sd.y;
    if (sd.x2 !== undefined) {
      wd.x2 = sd.x2;
      wd.y2 = sd.y2;
    }
    this._dragIndex = -1;
    this._dragWidgetStart = null;
    this._hoverIndex = -1;
    this._canvas!.style.cursor = "";
    this._scheduleRender();
  }

  private _onPointerLeave(): void {
    if (this._dragIndex >= 0 || this._resizeIndex >= 0) return;
    if (this._hoverIndex >= 0) {
      this._hoverIndex = -1;
      this._canvas!.style.cursor = "";
      this._scheduleRender();
    }
  }

  // ── Render scheduling ─────────────────────────────────────────────────────

  private _scheduleRender(): void {
    if (!this._connected || !this._layout || this._showServerImage) return;
    if (this._renderPending) return;
    this._renderPending = true;
    requestAnimationFrame(() => {
      this._renderPending = false;
      // _render() is async; fire-and-forget is safe here.
      // _renderInProgress serialises concurrent calls so a
      // second requestAnimationFrame that fires before the
      // first _render() resolves is deferred, not dropped.
      void this._render();
    });
  }

  /**
   * Collect icon URLs needed by all weather widgets into
   * the provided set so _preloadIcons() can batch-load them.
   *
   * @param w - Weather widget to collect icons for.
   * @param urls - Accumulator set of icon URLs.
   */
  private _collectWeatherIcons(
    w: WeatherWidget,
    urls: Set<string>,
  ): void {
    const entity = this._getState(w.entity ?? "");
    if (!entity) return;
    const condition = entity.state ?? "";
    const svg = CONDITION_SVG_MAP[condition];
    if (svg) urls.add(`${ICON_BASE}/svg/${svg}.svg`);
    // Preload only the detail icons whose attributes are
    // present, mirroring the conditional guards in
    // _renderWeather(). Avoids redundant fetches.
    const attrs = entity.attributes as Record<string, unknown>;
    for (const [attr, svgName] of Object.entries(DETAIL_SVG_MAP)) {
      if (attrs[attr] != null) {
        urls.add(`${ICON_BASE}/svg/${svgName}.svg`);
      }
    }
    const entityId = w.entity ?? "";
    const forecast: ForecastDay[] =
      this._forecasts[entityId]
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      || (entity.attributes as any)?.forecast
      || [];
    for (const day of forecast) {
      const dc = day.condition ?? "";
      const ds = CONDITION_SVG_MAP[dc];
      if (ds) urls.add(`${ICON_BASE}/svg/${ds}.svg`);
    }
  }

  /**
   * Collect MDI icon URLs for entity-based widgets.
   *
   * Resolves each entity's device_class to an MDI icon name
   * via deviceClassIcon() and adds the SVG URL to the set.
   *
   * @param entities - Entity IDs from the widget config.
   * @param urls - Accumulator set of icon URLs.
   */
  private _collectMdiIcons(
    entities: string[],
    urls: Set<string>,
  ): void {
    for (const entityId of entities) {
      const entity = this._getState(entityId);
      if (!entity) continue;
      const attrs = entity.attributes as Record<
        string,
        unknown
      >;
      const dc = (attrs.device_class as string) ?? "";
      const domain = entityId.split(".")[0];
      const icon = deviceClassIcon(
        dc, entity.state ?? "", domain,
      );
      if (icon) {
        urls.add(`${ICON_BASE}/svg/mdi/${icon}.svg`);
      }
    }
  }

  /**
   * Pre-load all icons needed for the current widget set.
   *
   * Inspects every widget and collects icon URLs, then loads
   * them all in parallel via loadIcon().  Cache hits resolve
   * immediately so subsequent renders pay no network cost.
   * Must run before the canvas clear so the visible canvas
   * retains its previous content during any network wait.
   */
  private async _preloadIcons(): Promise<void> {
    const urls = new Set<string>();
    for (const widget of this._layout!.widgets) {
      if (widget.type === "weather") {
        this._collectWeatherIcons(
          widget as WeatherWidget, urls,
        );
      }
      // Collect MDI icons for entity-based widgets.
      if ("entities" in widget) {
        const entities = (
          widget as { entities?: string[] }
        ).entities;
        if (entities?.length) {
          this._collectMdiIcons(entities, urls);
        }
      }
      // Waste schedule uses a fixed trash-can icon.
      if (widget.type === "waste_schedule") {
        urls.add(TRASH_ICON_URL);
      }
    }
    if (urls.size > 0) {
      await Promise.all(
        [...urls].map(url => loadIcon(url)),
      );
    }
  }

  private async _render(): Promise<void> {
    if (!this._ctx || !this._layout || !this._hass) return;
    // If a render is already in progress, mark a pending
    // re-render and return — _renderInProgress ensures the
    // two renders never interleave across await boundaries.
    if (this._renderInProgress) {
      this._renderPending = true;
      return;
    }
    this._renderInProgress = true;
    try {
      await this._renderBody();
    } finally {
      this._renderInProgress = false;
      // A state change arrived while we were rendering;
      // kick off one more pass now that we are clear.
      if (this._renderPending) {
        this._renderPending = false;
        void this._render();
      }
    }
  }

  private async _renderBody(): Promise<void> {
    if (!this._ctx || !this._layout || !this._hass) return;

    // Pre-load icons before clearing canvas so the visible
    // canvas retains its previous content during any load.
    const gen = this._fetchGeneration;
    await this._preloadIcons();
    if (gen !== this._fetchGeneration) return;

    // Draw to the offscreen canvas; the visible canvas keeps
    // its last complete frame until the blit at the end.
    const ctx = this._offCtx!;
    const { width, height } = this._layout.display;

    ctx.fillStyle = grayColor(COLOR_WHITE);
    ctx.fillRect(0, 0, width, height);

    if (this._editMode) {
      ctx.save();
      ctx.strokeStyle = "rgba(0,0,0,0.06)";
      ctx.setLineDash([1, 3]);
      for (let gx = GRID; gx < width; gx += GRID) {
        ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, height); ctx.stroke();
      }
      for (let gy = GRID; gy < height; gy += GRID) {
        ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.restore();
    }

    const dispatch: Partial<Record<string, (w: Widget) => WidgetBounds>> = {
      text: (w) => this._renderText(ctx, w as TextWidget),
      separator: (w) => this._renderSeparator(ctx, w as SeparatorWidget),
      weather: (w) => this._renderWeather(ctx, w as WeatherWidget),
      sensor_rows: (w) => this._renderSensorRows(ctx, w as SensorRowsWidget),
      device_battery: (w) => this._renderDeviceBattery(ctx, w as DeviceBatteryWidget),
      status_icons: (w) => this._renderStatusIcons(ctx, w as StatusIconsWidget),
      waste_schedule: (w) => this._renderWasteSchedule(ctx, w as WasteScheduleWidget),
    };

    this._widgetBounds = [];
    for (let i = 0; i < this._layout.widgets.length; i++) {
      const widget = this._layout.widgets[i];
      const fn = dispatch[widget.type];
      if (!fn) continue;
      const bounds = fn(widget);
      if (bounds) this._widgetBounds.push({ index: i, ...bounds });
    }

    const highlightIdx =
      this._resizeIndex >= 0 ? this._resizeIndex :
      this._dragIndex >= 0 ? this._dragIndex : this._hoverIndex;
    if (this._editMode && highlightIdx >= 0) {
      const entry = this._widgetBounds.find((b) => b.index === highlightIdx);
      if (entry) {
        ctx.save();
        ctx.strokeStyle = "rgba(3, 169, 244, 0.8)";
        ctx.lineWidth = 2;
        const isActive = this._dragIndex >= 0 || this._resizeIndex >= 0;
        ctx.setLineDash(isActive ? [] : [4, 3]);
        ctx.strokeRect(entry.x - 3, entry.y - 3, entry.w + 6, entry.h + 6);

        const widget = this._layout.widgets[highlightIdx];
        const handles = this._getHandles(entry, widget);
        ctx.setLineDash([]);
        for (const h of handles) {
          ctx.fillStyle = "rgba(3, 169, 244, 0.9)";
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1;
          const hs = HANDLE_SIZE;
          ctx.fillRect(h.cx - hs / 2, h.cy - hs / 2, hs, hs);
          ctx.strokeRect(h.cx - hs / 2, h.cy - hs / 2, hs, hs);
        }
        ctx.restore();
      }
    }

    // Blit the completed offscreen frame onto the visible
    // canvas in one atomic drawImage() call — no partial
    // state is ever visible to the user.
    this._ctx!.drawImage(this._offscreen!, 0, 0);
  }

  // ── Server image toggle ───────────────────────────────────────────────────

  private async _onToggle(): Promise<void> {
    if (!this._canvas) return;
    this._showServerImage = !this._showServerImage;
    if (this._showServerImage) {
      const entryId = this._resolvedEntryId;
      if (this._layout?.widgets) {
        this._toggleBtn.disabled = true;
        try {
          await this._hass!.callApi(
            "POST",
            `eink_dashboard/${entryId}/layout`,
            this._layout.widgets,
          );
        } catch (err) {
          console.error("Failed to save before render:", err);
          this._showServerImage = false;
          this._toggleBtn.disabled = false;
          return;
        }
        this._toggleBtn.disabled = false;
      }
      this._serverImg!.src = `/api/eink_dashboard/${entryId}/image.png?_t=${Date.now()}`;
      this._canvas.style.display = "none";
      this._serverImg!.style.display = "block";
      this._toggleBtn.textContent = "Show canvas preview";
      this._toggleBtn.classList.add("active");
    } else {
      this._serverImg!.style.display = "none";
      this._canvas.style.display = "block";
      this._toggleBtn.textContent = "Show rendered image";
      this._toggleBtn.classList.remove("active");
      this._scheduleRender();
    }
  }

  // ── Copy URL ──────────────────────────────────────────────────────────────

  private _onCopyUrl(): void {
    if (!this._resolvedEntryId) return;
    const url = `${window.location.origin}/api/eink_dashboard/${this._resolvedEntryId}/image.png`;
    navigator.clipboard.writeText(url).then(() => {
      this._copyBtn.textContent = "Copied!";
      this._copyBtn.classList.add("copied");
      if (this._copyTimeout) clearTimeout(this._copyTimeout);
      this._copyTimeout = setTimeout(() => {
        this._copyBtn.textContent = "Copy image URL";
        this._copyBtn.classList.remove("copied");
        this._copyTimeout = null;
      }, 2000);
    }).catch(() => {
      this._copyBtn.textContent = "Copy failed";
      if (this._copyTimeout) clearTimeout(this._copyTimeout);
      this._copyTimeout = setTimeout(() => {
        this._copyBtn.textContent = "Copy image URL";
        this._copyTimeout = null;
      }, 2000);
    });
  }

  // ── State helper ──────────────────────────────────────────────────────────

  private _getState(entityId: string): HassEntity | null {
    const s = this._hass!.states[entityId];
    return s || null;
  }

  // ── Widget helpers ────────────────────────────────────────────────────────

  /** Extract base coordinates shared by most widget renderers. */
  private _getWidgetBase(widget: Widget, defaultFontSize: number): {
    x: number; y: number; fontSize: number; width: number; rightEdge: number;
  } {
    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    const fontSize = Math.max(1, widget.font_size ?? defaultFontSize);
    const width = this._layout!.display.width;
    const rightEdge = widget.w != null ? (x + widget.w) : width;
    return { x, y, fontSize, width, rightEdge };
  }

  // ── Widget renderers ──────────────────────────────────────────────────────

  // mirrors render.py: render_text (lines 77-100)
  private _renderText(ctx: CanvasRenderingContext2D, widget: TextWidget): WidgetBounds {
    const { x, y, fontSize, rightEdge } = this._getWidgetBase(widget, FONT_SIZE_TEXT);
    const text = String(widget.text ?? "");
    const color = widget.color ?? COLOR_BLACK;
    const align = widget.align ?? "left";

    ctx.font = `${fontSize}px ${FONT_FAMILY}`;
    ctx.fillStyle = grayColor(color);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    const tw = ctx.measureText(text).width;
    let drawX = x;
    if (align === "right") {
      drawX = rightEdge - PADDING - tw;
    } else if (align === "center") {
      drawX = x + (rightEdge - x - tw) / 2;
    }

    ctx.fillText(text, drawX, y);
    const bx = Math.min(drawX, x);
    const boundsW = widget.w != null ? widget.w : Math.max(drawX + tw - bx, 20);
    return { x: bx, y, w: boundsW, h: fontSize };
  }

  // mirrors render.py: render_separator
  private _renderSeparator(ctx: CanvasRenderingContext2D, widget: SeparatorWidget): WidgetBounds {
    const direction = widget.direction ?? "horizontal";
    const style = widget.style ?? "line";
    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    const displayW = this._layout!.display.width;
    const displayH = this._layout!.display.height;

    const color = style === "line" ? COLOR_BLACK : COLOR_GRAY;
    const levels = this._layout!.display.grayscale_levels ?? 16;
    const thickness = style === "line" ? 2 : levels <= 2 ? 10 : 6;

    const len = widget.length != null
      ? widget.length
      : direction === "vertical"
        ? displayH - PADDING - y
        : displayW - PADDING - x;

    if (direction === "vertical") {
      if (style === "bar") {
        ctx.fillStyle = grayColor(color);
        ctx.fillRect(x, y, thickness, len);
      } else {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + len);
        ctx.strokeStyle = grayColor(color);
        ctx.lineWidth = thickness;
        ctx.stroke();
      }
      return { x: x - 1, y, w: thickness + 2, h: len };
    } else {
      if (style === "bar") {
        ctx.fillStyle = grayColor(color);
        ctx.fillRect(x, y, len, thickness);
      } else {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + len, y);
        ctx.strokeStyle = grayColor(color);
        ctx.lineWidth = thickness;
        ctx.stroke();
      }
      return { x, y: y - 1, w: len, h: thickness + 2 };
    }
  }

  // mirrors render.py: render_weather
  private _renderWeather(ctx: CanvasRenderingContext2D, widget: WeatherWidget): WidgetBounds {
    const entityId = widget.entity ?? "";
    const stateObj = this._getState(entityId);
    const { x, y: origY, fontSize, width: dispW } = this._getWidgetBase(widget, FONT_SIZE_WEATHER);
    const s = fontSize / FONT_SIZE_WEATHER;
    // Natural width scales with font_size so diagonal resize
    // grows/shrinks the entire widget, not just the text.
    const rightEdge = widget.w != null
      ? (x + widget.w)
      : Math.min(x + Math.round(380 * s), dispW);
    if (!stateObj) return { x, y: origY, w: 200, h: Math.round(90 * s) };

    const y = origY;
    const forecastDays = widget.forecast_days ?? 5;
    const cardStyle = widget.card_style ?? "none";
    const condition = stateObj.state ?? "";
    const attrs = stateObj.attributes as Record<string, string | number | null>;
    const temp = attrs.temperature ?? "--";
    const tempUnit = attrs.temperature_unit ?? "°C";
    const humidity = attrs.humidity;
    const wind = attrs.wind_speed;
    const windUnit = attrs.wind_speed_unit ?? "km/h";
    const pressure = attrs.pressure;
    const pressureUnit = attrs.pressure_unit ?? "hPa";
    const cloudCoverage = attrs.cloud_coverage;
    const precipUnit = String(attrs.precipitation_unit ?? "mm");
    const forecast = this._forecasts[entityId]
      || (attrs.forecast as ForecastDay[] | null)
      || [];

    // Row 1: condition icon + temperature + today hi/lo.
    //
    // The icon is the anchor element — sized independently of text
    // metrics, with equal padding on top/left/bottom and slightly
    // more on the right before the temperature text.
    const xlFontSize = Math.round(64 * s);
    const tempText = `${temp}${tempUnit}`;
    ctx.font = `${xlFontSize}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const tempM = ctx.measureText(tempText);
    const tempH = tempM.actualBoundingBoxAscent
      + tempM.actualBoundingBoxDescent;

    const iconSize = Math.round(80 * s);
    const pad = Math.round(10 * s);
    const iconRightPad = Math.round(16 * s);

    // Named layout constants shared between height estimation and drawing.
    const detailGap = Math.round(8 * s);
    const detailIconH = Math.round(20 * s);
    const sepGap = Math.round(8 * s);
    const sepThickness = Math.max(2, Math.round(3 * s));
    const forecastZoneH = Math.round(88 * s);
    const precipTextH = Math.round(16 * s);

    // Compute metrics early so topPad is available for the height
    // estimation — m.padding differs from pad by 1px at some scales.
    const cardW = rightEdge - x;
    const hasForecast = forecast.length > 0 && forecastDays > 0;
    let m: WidgetMetrics | null = null;
    let topPad: number;
    if (cardStyle !== "none") {
      m = computeMetrics(Math.round(48 * s));
      topPad = m.padding;
    } else {
      topPad = pad;
    }

    // iconSize dominates tempH in practice, but Math.max() makes the
    // estimation robust against unusual font metrics or large fontSize.
    const row1H = topPad + Math.max(iconSize, tempH) + pad;
    const detailH = detailGap + detailIconH;
    const forecastSectionH = hasForecast
      ? (sepGap + sepThickness + sepGap + forecastZoneH + precipTextH)
      : pad;
    const totalH = row1H + detailH + forecastSectionH + pad;

    // Card container draws the outer frame and returns the content
    // x-offset — left bar and border styles shift content rightward.
    let contentLeft: number;
    let contentW: number;
    if (m !== null) {
      const xOff = drawCardContainer(
        ctx, x, y, cardW, totalH, m, cardStyle,
        this._layout!.display.grayscale_levels ?? 16,
      );
      contentLeft = x + xOff;
      contentW = cardW - xOff;
      if (cardStyle === "border") contentW -= m.padding;
    } else {
      contentLeft = x + pad;
      contentW = rightEdge - x - 2 * pad;
    }
    const contentTop = y + topPad;

    const iconCx = contentLeft + iconSize / 2;
    const iconCy = contentTop + iconSize / 2;

    // Condition icon: SVG loaded at preload time, top-left origin.
    const condSvg = CONDITION_SVG_MAP[condition];
    const condImg = condSvg
      ? getIcon(`${ICON_BASE}/svg/${condSvg}.svg`)
      : null;
    if (condImg) {
      ctx.drawImage(condImg, contentLeft, contentTop, iconSize, iconSize);
    } else {
      ctx.font = `${iconSize}px ${FONT_FAMILY}`;
      ctx.textBaseline = "middle";
      ctx.textAlign = "center";
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText("?", iconCx, iconCy);
    }

    // Temperature text vertically centred on the icon.
    // With textBaseline="top", actualBoundingBoxAscent is the
    // offset from draw anchor to visible glyph top.
    const tempX = contentLeft + iconSize + iconRightPad;
    const tempY = iconCy
      + tempM.actualBoundingBoxAscent
      - tempH / 2;
    ctx.font = `${xlFontSize}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillStyle = grayColor(COLOR_BLACK);
    ctx.fillText(tempText, tempX, tempY);

    const visTop = tempY - tempM.actualBoundingBoxAscent;
    const row1Bottom = Math.max(
      contentTop + iconSize + pad,
      tempY + tempM.actualBoundingBoxDescent,
    );

    // Today's hi/lo/precip right-aligned at the widget's right edge.
    const smFontSize = Math.round(16 * s);
    const xsFontSize = Math.round(14 * s);
    if (forecast.length > 0) {
      const today = forecast[0];
      const hi = today.temperature;
      const lo = today.templow;
      const precip = today.precipitation;
      const hiloRight = contentLeft + contentW;
      ctx.textBaseline = "top";
      ctx.textAlign = "right";
      if (hi != null) {
        ctx.font = `${smFontSize}px ${FONT_FAMILY}`;
        ctx.fillStyle = grayColor(COLOR_BLACK);
        ctx.fillText(`${hi}°`, hiloRight, visTop);
      }
      if (lo != null) {
        ctx.font = `${smFontSize}px ${FONT_FAMILY}`;
        ctx.fillStyle = grayColor(COLOR_GRAY);
        ctx.fillText(
          `${lo}°`, hiloRight,
          visTop + Math.round(tempH * 0.4),
        );
      }
      if (precip != null) {
        ctx.font = `${xsFontSize}px ${FONT_FAMILY}`;
        ctx.fillStyle = grayColor(COLOR_GRAY);
        ctx.fillText(
          `${precip}${precipUnit}`,
          hiloRight,
          visTop + Math.round(tempH * 0.72),
        );
      }
      ctx.textAlign = "left";
    }

    // Row 2: detail icon + text, evenly distributed.
    // Text centred on the icon by correcting for canvas ascent offset.
    // Mirrors: text_y = detail_y + icon_h/2 − bbox[1] − text_h/2
    //   where bbox[1] = −actualBoundingBoxAscent (with textBaseline=top).
    const detailY = row1Bottom + detailGap;
    const iconGap = Math.round(4 * s);

    const detailItems: DetailItem[] = [];
    if (humidity != null) {
      detailItems.push({
        text: `${humidity}%`,
        svgName: "wi-humidity",
      });
    }
    if (pressure != null) {
      detailItems.push({
        text: `${Math.round(Number(pressure))}${pressureUnit}`,
        svgName: "wi-barometer",
      });
    }
    if (wind != null) {
      detailItems.push({
        text: `${Math.round(Number(wind))}${windUnit}`,
        svgName: "wi-strong-wind",
      });
    }
    if (cloudCoverage != null) {
      detailItems.push({
        text: `${cloudCoverage}%`,
        svgName: "wi-cloud",
      });
    }

    const detailCols = Math.max(detailItems.length, 1);
    const colW = Math.floor(contentW / detailCols);

    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    for (let i = 0; i < detailItems.length; i++) {
      const { text, svgName } = detailItems[i];
      const colCx = contentLeft + colW * i + Math.floor(colW / 2);
      ctx.font = `${smFontSize}px ${FONT_FAMILY}`;
      const tm = ctx.measureText(text);
      const textW2 = tm.width;
      const textH2 = tm.actualBoundingBoxAscent
        + tm.actualBoundingBoxDescent;
      const itemW = detailIconH + iconGap + textW2;
      const itemX = colCx - Math.floor(itemW / 2);
      const detailImg = getIcon(`${ICON_BASE}/svg/${svgName}.svg`);
      if (detailImg) {
        ctx.drawImage(detailImg, itemX, detailY, detailIconH, detailIconH);
      } else {
        // Fallback: gray rectangle when icon not loaded.
        ctx.fillStyle = grayColor(COLOR_LIGHT_GRAY);
        ctx.fillRect(itemX, detailY, detailIconH, detailIconH);
      }
      // Glyph centre aligned to icon centre.
      const textY = detailY + detailIconH / 2
        + tm.actualBoundingBoxAscent
        - textH2 / 2;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.fillText(text, itemX + detailIconH + iconGap, textY);
    }

    const detailBottom = detailY + detailIconH;

    // Separator and forecast.
    if (!forecast.length || forecastDays <= 0) {
      return {
        x, y: origY, w: cardW,
        // For styled containers, use pre-computed height so the border
        // frame matches the drawn rectangle exactly. For "none", measure
        // the actual rendered extent to preserve the old bounding box.
        h: m !== null
          ? totalH
          : detailBottom + Math.round(4 * s) - origY,
      };
    }

    // Always use at least 5 columns so <=5 forecast days
    // stay compact instead of stretching across the width.
    const nCols = Math.max(forecastDays, 5);
    const colWidth = Math.floor(contentW / nCols);
    const contentWidth = nCols * colWidth;

    const separatorY = detailBottom + sepGap;
    ctx.beginPath();
    ctx.moveTo(contentLeft, separatorY);
    ctx.lineTo(contentLeft + contentWidth, separatorY);
    ctx.strokeStyle = grayColor(COLOR_GRAY);
    ctx.lineWidth = sepThickness;
    ctx.stroke();

    const forecastY = separatorY + sepGap;

    // Spread entries evenly when fewer than nCols.
    let positions: number[];
    if (forecastDays >= nCols) {
      positions = Array.from(
        { length: forecastDays }, (_, i) => i,
      );
    } else if (forecastDays <= 1) {
      positions = [Math.floor(nCols / 2)];
    } else {
      positions = Array.from(
        { length: forecastDays },
        (_, i) => Math.round(
          i * (nCols - 1) / (forecastDays - 1),
        ),
      );
    }

    for (
      let i = 0;
      i < Math.min(forecastDays, forecast.length);
      i++
    ) {
      const day = forecast[i];
      const colI = positions[i];
      const cx = contentLeft + colWidth * colI
        + Math.floor(colWidth / 2);

      // Day label
      let dayLabel = "";
      if (day.datetime) {
        const [yr, mo, dy] = day.datetime.slice(0, 10).split("-").map(Number);
        const dt = new Date(yr, mo - 1, dy);
        dayLabel = DAY_ABBREV[(dt.getDay() + 6) % 7];
      }
      ctx.font = `${Math.round(16 * s)}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.textBaseline = "top";
      ctx.textAlign = "center";
      ctx.fillText(dayLabel, cx, forecastY);

      // Condition icon (32 * s — slightly larger than detail icons).
      const dayIconSz = Math.round(32 * s);
      const daySvg = CONDITION_SVG_MAP[day.condition ?? ""];
      const dayImg = daySvg
        ? getIcon(`${ICON_BASE}/svg/${daySvg}.svg`)
        : null;
      if (dayImg) {
        // Centre the icon on (cx, forecastY + 34*s).
        const iconTop = forecastY + Math.round(34 * s)
          - dayIconSz / 2;
        ctx.drawImage(
          dayImg,
          cx - dayIconSz / 2, iconTop,
          dayIconSz, dayIconSz,
        );
      } else {
        ctx.font = `${dayIconSz}px ${FONT_FAMILY}`;
        ctx.fillStyle = grayColor(COLOR_BLACK);
        ctx.textBaseline = "middle";
        ctx.fillText("?", cx, forecastY + Math.round(34 * s));
      }

      // High temp
      const hi = day.temperature;
      ctx.font = `${Math.round(16 * s)}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_BLACK);
      ctx.textBaseline = "top";
      ctx.fillText(
        hi != null ? `${hi}°` : "",
        cx, forecastY + Math.round(52 * s),
      );

      // Low temp
      const lo = day.templow;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillText(
        lo != null ? `${lo}°` : "",
        cx, forecastY + Math.round(70 * s),
      );

      // Precipitation
      const precip = day.precipitation;
      if (precip != null && precip > 0) {
        ctx.font = `${Math.round(14 * s)}px ${FONT_FAMILY}`;
        ctx.fillStyle = grayColor(COLOR_GRAY);
        ctx.fillText(
          `${precip}${precipUnit}`,
          cx, forecastY + Math.round(88 * s),
        );
      }
    }

    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const forecastBottom = forecastY + forecastZoneH + precipTextH;
    return {
      x, y: origY, w: cardW,
      h: m !== null ? totalH : forecastBottom - origY,
    };
  }

  // mirrors render.py: render_sensor_rows
  private _renderSensorRows(
    ctx: CanvasRenderingContext2D,
    widget: SensorRowsWidget,
  ): WidgetBounds {
    const x = widget.x ?? PADDING;
    let y = widget.y ?? 0;
    const origY = y;
    const width = widget.w ?? 400;
    let height = widget.h ?? 112;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];
    const cardStyle = widget.card_style ?? "none";
    const n = entityIds.length;

    if (n === 0) return { x, y, w: width, h: height };

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    // Title above the card (gray, proportional to h)
    if (title) {
      const titleFontSz = Math.max(10, Math.round(height * 0.14));
      ctx.font = `${titleFontSz}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillText(title, x, y);
      const titleAdv = Math.round(titleFontSz * 1.4);
      y += titleAdv;
      height -= titleAdv;
    }

    const rowH = Math.floor(height / n);
    const m = computeMetrics(rowH);
    const xOff = drawCardContainer(
      ctx, x, y, width, height, m, cardStyle,
      this._layout!.display.grayscale_levels ?? 16,
    );
    const cx = x + xOff;
    let cw = width - xOff;
    // Inset content from right edge for border style
    if (cardStyle === "border") cw -= m.padding;

    for (let i = 0; i < n; i++) {
      const entityId = entityIds[i];
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const rowY = y + i * rowH;
      const attrs = stateObj.attributes as Record<
        string, string | undefined
      >;
      const domain = entityId.split(".")[0];
      const dc = String(attrs.device_class ?? "");
      const iconName = deviceClassIcon(
        dc, stateObj.state, domain,
      );
      // SVG icon for canvas (Python uses PNG via icons/png/).
      const icon = iconName
        ? getIcon(
            `${ICON_BASE}/svg/mdi/${iconName}.svg`,
          )
        : null;

      const unit = String(attrs.unit_of_measurement ?? "");
      const stateVal = stateObj.state ?? "";
      const secondary = unit
        ? `${stateVal}${unit}`
        : stateVal;

      drawCardRow(ctx, cx, rowY, cw, rowH, m, {
        primary: String(attrs.friendly_name ?? entityId),
        secondary,
        icon: icon ?? undefined,
      });

      // Gray divider between rows (not after last)
      if (i < n - 1) {
        const divY = rowY + rowH;
        // Center divider on the row boundary to match
        // PIL's draw.line() which centers stroke on the
        // coordinate.
        const divTop = divY - Math.floor(m.divider / 2);
        ctx.fillStyle = grayColor(COLOR_GRAY);
        ctx.fillRect(
          cx + m.padding, divTop,
          cw - 2 * m.padding, m.divider,
        );
      }
    }
    return { x, y: origY, w: width, h: (y - origY) + height };
  }

  // mirrors render.py: render_device_battery
  private _renderDeviceBattery(
    ctx: CanvasRenderingContext2D,
    widget: DeviceBatteryWidget,
  ): WidgetBounds {
    const layout = widget.layout ?? "icon";
    if (layout === "chip") {
      return this._renderDeviceBatteryChip(ctx, widget);
    }
    return this._renderDeviceBatteryIcon(ctx, widget);
  }

  /** Icon layout: compact battery outline + percentage text. */
  private _renderDeviceBatteryIcon(
    ctx: CanvasRenderingContext2D,
    widget: DeviceBatteryWidget,
  ): WidgetBounds {
    const { x, y, fontSize } = this._getWidgetBase(widget, FONT_SIZE_DEVICE_BATTERY);
    let color = widget.color ?? COLOR_BLACK;

    const rawLevel = this._layout?.device?.device_battery_level;
    const pct = rawLevel != null ? Math.max(0, Math.min(100, Math.floor(rawLevel))) : null;
    // Below 20%: force black for visual emphasis
    if (pct != null && pct < 20) {
      color = COLOR_BLACK;
    }
    const label = pct != null ? `${pct}%` : "---%";

    const s = fontSize / FONT_SIZE_DEVICE_BATTERY;
    const bw = Math.round(BATTERY_BODY_W * s);
    const bh = Math.round(BATTERY_BODY_H * s);
    const nubW = Math.round(BATTERY_NUB_W * s);
    const nubH = Math.round(BATTERY_NUB_H * s);
    const nubGap = Math.max(1, Math.round(s));
    const gap = Math.round(4 * s);

    // Measure label to center icon against text
    ctx.font = `${fontSize}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const metrics = ctx.measureText(label);
    const textH = metrics.actualBoundingBoxAscent + metrics.actualBoundingBoxDescent;
    // Centre icon on the text glyph — mirrors Python's
    // icon_y = y + bbox[1] + (text_h - bh) // 2
    const inkTop = metrics.actualBoundingBoxAscent;
    const iconY = y + inkTop + Math.floor((textH - bh) / 2);

    // Outline
    ctx.strokeStyle = grayColor(COLOR_GRAY);
    ctx.lineWidth = 1;
    ctx.strokeRect(x, iconY, bw, bh);

    // Nub
    const nubY = iconY + Math.floor((bh - nubH) / 2);
    ctx.fillStyle = grayColor(COLOR_GRAY);
    ctx.fillRect(x + bw + nubGap, nubY, nubW, nubH);

    // Fill bar
    if (pct != null) {
      const fillW = Math.floor((bw - 2) * pct / 100);
      if (fillW > 0) {
        ctx.fillStyle = grayColor(color);
        ctx.fillRect(x + 1, iconY + 1, fillW, bh - 2);
      }
    }

    // Label
    const labelW = metrics.width;
    ctx.fillStyle = grayColor(color);
    ctx.fillText(label, x + bw + nubGap + nubW + gap, y);
    return { x, y, w: bw + nubGap + nubW + gap + labelW, h: textH };
  }

  /** Chip layout: pill-shaped chip with battery fill bar. */
  private _renderDeviceBatteryChip(
    ctx: CanvasRenderingContext2D,
    widget: DeviceBatteryWidget,
  ): WidgetBounds {
    const x = widget.x ?? PADDING;
    const y = widget.y ?? 0;
    const h = widget.h ?? 40;
    let color = widget.color ?? COLOR_BLACK;

    const rawLevel = this._layout?.device?.device_battery_level;
    const pct = rawLevel != null
      ? Math.max(0, Math.min(100, Math.floor(rawLevel)))
      : null;
    // Below 20%: force black for visual emphasis
    if (pct != null && pct < 20) {
      color = COLOR_BLACK;
    }
    const label = pct != null ? `${pct}%` : "---%";

    const m = computeMetrics(h);
    const radius = Math.floor(h / 2);
    const pad = Math.round(h * CHIP_PAD_RATIO);

    // Battery bar proportional to chip height
    const barW = Math.round(h * 1.2);
    const barH = Math.round(h * 0.36);

    // Measure label to compute content-based chip width
    const chipGap = Math.round(h * CHIP_GAP_RATIO);
    const fontSize = Math.max(10, Math.round(h * CHIP_FONT_RATIO));
    ctx.font = `${fontSize}px ${FONT_FAMILY}`;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const textW = Math.floor(ctx.measureText(label).width);
    const chipW = pad + barW + chipGap + textW + pad;

    // Pill-shaped chip border
    ctx.beginPath();
    ctx.roundRect(x, y, chipW, h, radius);
    ctx.strokeStyle = grayColor(COLOR_BLACK);
    ctx.lineWidth = m.border;
    ctx.stroke();

    const barX = x + pad;
    const barY = y + Math.floor((h - barH) / 2);

    // Bar outline
    const barBorder = Math.max(1, Math.floor(m.border / 2));
    ctx.strokeStyle = grayColor(color);
    ctx.lineWidth = barBorder;
    ctx.strokeRect(barX, barY, barW, barH);

    // Bar fill proportional to level
    if (pct != null) {
      const fillW = Math.floor((barW - 2) * pct / 100);
      if (fillW > 0) {
        ctx.fillStyle = grayColor(color);
        ctx.fillRect(barX + 1, barY + 1, fillW, barH - 2);
      }
    }

    // Percentage label to the right of the bar
    const textMetrics = ctx.measureText(label);
    const textH = textMetrics.actualBoundingBoxAscent
      + textMetrics.actualBoundingBoxDescent;
    const textY = y + Math.floor((h - textH) / 2);
    ctx.fillStyle = grayColor(color);
    ctx.fillText(label, barX + barW + chipGap, textY);

    return { x, y, w: chipW, h };
  }

  // mirrors render.py: render_status_icons
  private _renderStatusIcons(
    ctx: CanvasRenderingContext2D,
    widget: StatusIconsWidget,
  ): WidgetBounds {
    const x = widget.x ?? PADDING;
    let y = widget.y ?? 0;
    const origY = y;
    const width = widget.w ?? 400;
    let height = widget.h ?? 40;
    const title = widget.title ?? "";
    const entityIds = widget.entities ?? [];

    if (entityIds.length === 0) {
      return { x, y, w: width, h: height };
    }

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    // Title above chips (gray, proportional to h)
    if (title) {
      const titleFontSz = Math.max(
        10, Math.round(height * 0.14),
      );
      ctx.font = `${titleFontSz}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillText(title, x, y);
      const titleAdv = Math.round(titleFontSz * 1.4);
      y += titleAdv;
      height -= titleAdv;
    }

    const cardStyle = widget.card_style ?? "none";
    const m = computeMetrics(height);
    const xOff = drawCardContainer(
      ctx, x, y, width, height, m, cardStyle,
      this._layout!.display.grayscale_levels ?? 16,
    );
    const cx = x + xOff;
    // Mirror left inset on right so chips stay within the
    // border stroke.
    let cw = width - xOff;
    if (cardStyle === "border") cw -= m.padding;

    const chipFontSz = Math.max(
      10, Math.round(height * CHIP_FONT_RATIO),
    );

    // Build chip descriptors
    const chips: ChipDescriptor[] = [];
    for (const entityId of entityIds) {
      const stateObj = this._getState(entityId);
      if (!stateObj) continue;
      const attrs = stateObj.attributes as Record<
        string, string | undefined
      >;
      const label = String(
        attrs.friendly_name ?? entityId,
      );
      const isOn = stateObj.state === "on";
      const dc = String(attrs.device_class ?? "");
      const isProblem = isOn
        && PROBLEM_DEVICE_CLASSES.has(dc);
      const domain = entityId.split(".")[0];
      const iconName = deviceClassIcon(
        dc, stateObj.state, domain,
      );
      const icon = iconName
        ? getIcon(
            `${ICON_BASE}/svg/mdi/${iconName}.svg`,
          )
        : null;

      chips.push({
        text: label,
        inverted: isProblem,
        icon: icon ?? undefined,
      });
    }

    const endY = drawChipFlow(
      ctx, cx, y, cw, height, chips,
      chipFontSz, m.border,
    );
    return {
      x, y: origY, w: width,
      h: endY - origY,
    };
  }

  /**
   * Render waste collection entries as card rows with urgency
   * styling.  Mirrors render_waste_schedule() in render.py.
   *
   * Data comes from a single entity whose attributes contain
   * waste types as keys with ISO date values.  The ``entries``
   * config maps attribute keys to short display labels.
   *
   * @param ctx - Canvas 2D context.
   * @param widget - Waste schedule widget config.
   * @returns Bounding box of the rendered widget.
   */
  private _renderWasteSchedule(
    ctx: CanvasRenderingContext2D,
    widget: WasteScheduleWidget,
  ): WidgetBounds {
    const x = widget.x ?? PADDING;
    let y = widget.y ?? 0;
    const origY = y;
    const width = widget.w ?? 400;
    let height = widget.h ?? 168;
    const title = widget.title ?? "";
    const entityId = widget.entity ?? "";
    const entries: WasteScheduleEntry[] =
      widget.entries ?? [];
    const layout = widget.layout ?? "list";
    const cardStyle = widget.card_style ?? "none";

    if (!entityId || entries.length === 0) {
      return { x, y, w: width, h: height };
    }

    const stateObj = this._getState(entityId);
    if (!stateObj) {
      return { x, y, w: width, h: height };
    }
    const attrs = stateObj.attributes as Record<
      string, string | undefined
    >;

    ctx.textBaseline = "top";
    ctx.textAlign = "left";

    // Title above the card (gray, proportional to h)
    if (title) {
      const titleFontSz = Math.max(
        10, Math.round(height * 0.14),
      );
      ctx.font = `${titleFontSz}px ${FONT_FAMILY}`;
      ctx.fillStyle = grayColor(COLOR_GRAY);
      ctx.fillText(title, x, y);
      const titleAdv = Math.round(titleFontSz * 1.4);
      y += titleAdv;
      height -= titleAdv;
    }

    // Resolve entries from entity attributes, filter
    // to the 0–3 day range.
    type VisibleEntry = {
      label: string;
      raw: string;
      days: number;
    };
    const visible: VisibleEntry[] = [];
    for (const entry of entries) {
      const raw = String(attrs[entry.attribute] ?? "");
      if (!raw) continue;
      const days = parseDaysUntil(raw);
      if (days === null || days < 0 || days > 3) {
        continue;
      }
      visible.push({
        label: entry.label || entry.attribute,
        raw,
        days,
      });
    }

    if (visible.length === 0) {
      return { x, y: origY, w: width, h: (y - origY) + height };
    }

    const trashIcon = getIcon(TRASH_ICON_URL);

    if (layout === "card") {
      // Most urgent entry (lowest days value).
      // Stable sort: equal-days entries keep config order.
      visible.sort(
        (a, b) => a.days - b.days,
      );
      const { label, raw, days } = visible[0];
      const rowH = height;
      const m = computeMetrics(rowH);
      const xOff = drawCardContainer(
        ctx, x, y, width, height, m, cardStyle,
        this._layout!.display.grayscale_levels ?? 16,
      );
      const cx = x + xOff;
      let cw = width - xOff;
      if (cardStyle === "border") cw -= m.padding;
      const iconFill = (
        days <= 1 ? COLOR_BLACK : COLOR_GRAY
      );
      const dateStr = formatRelativeDate(days, raw);
      // Today entries get black date text for urgency
      const sf = days === 0 ? COLOR_BLACK : COLOR_GRAY;
      drawCardRow(ctx, cx, y, cw, rowH, m, {
        primary: label,
        secondary: dateStr,
        icon: trashIcon ?? undefined,
        iconFill,
        secondaryFill: sf,
      });
    } else {
      // List layout: one row per visible entry
      const n = visible.length;
      const rowH = Math.floor(height / n);
      const m = computeMetrics(rowH);
      const xOff = drawCardContainer(
        ctx, x, y, width, height, m, cardStyle,
        this._layout!.display.grayscale_levels ?? 16,
      );
      const cx = x + xOff;
      let cw = width - xOff;
      if (cardStyle === "border") cw -= m.padding;

      for (let i = 0; i < n; i++) {
        const { label, raw, days } = visible[i];
        const rowY = y + i * rowH;
        const iconFill = (
          days <= 1 ? COLOR_BLACK : COLOR_GRAY
        );
        const dateStr = formatRelativeDate(days, raw);
        // Today entries get black date text for urgency
        const vf = days === 0 ? COLOR_BLACK : COLOR_GRAY;
        drawCardRow(ctx, cx, rowY, cw, rowH, m, {
          primary: label,
          value: dateStr,
          icon: trashIcon ?? undefined,
          iconFill,
          valueFill: vf,
        });

        // Gray divider between rows (not after last)
        if (i < n - 1) {
          const divY = rowY + rowH;
          const divTop = divY - Math.floor(
            m.divider / 2,
          );
          ctx.fillStyle = grayColor(COLOR_GRAY);
          ctx.fillRect(
            cx + m.padding, divTop,
            cw - 2 * m.padding, m.divider,
          );
        }
      }
    }
    return {
      x, y: origY,
      w: width, h: (y - origY) + height,
    };
  }
}

// ── Registration ──────────────────────────────────────────────────────────────

// HA may create cards before this module runs, producing hui-error-card
// placeholders.  We register the element, then periodically scan the DOM
// (including shadow roots) for stale error cards and force their parent
// hui-card to recreate them.

function ensureRegistered(): void {
  if (!customElements.get(CARD_TAG)) {
    customElements.define(CARD_TAG, EinkDashboardCard);
  }
}
ensureRegistered();

function queryShadow(root: Node, tag: string): Element[] {
  const results: Element[] = [];
  if (root instanceof Element) {
    if (root.localName === tag) results.push(root);
    if (root.shadowRoot) {
      results.push(...queryShadow(root.shadowRoot, tag));
    }
  }
  for (const child of (root as Element).children ?? []) {
    results.push(...queryShadow(child, tag));
  }
  return results;
}

type HuiCard = HTMLElement & { config?: Record<string, unknown> };

function findHuiCard(errorCard: Element): HuiCard | null {
  const root = errorCard.getRootNode();
  if (root instanceof ShadowRoot && root.host?.localName === "hui-card") {
    return root.host as HuiCard;
  }
  let el = errorCard.parentElement;
  while (el) {
    if (el.localName === "hui-card") return el as HuiCard;
    el = el.parentElement;
  }
  return null;
}

function forceHuiCardRebuilds(): number {
  ensureRegistered();
  let fixed = 0;
  for (const el of queryShadow(document.body, "hui-error-card")) {
    const huiCard = findHuiCard(el);
    if (!huiCard) continue;
    const cfg = huiCard.config;
    if (!cfg || cfg.type !== `custom:${CARD_TAG}`) continue;
    huiCard.config = { type: "error", error: "reloading" };
    requestAnimationFrame(() => { huiCard.config = cfg; });
    fixed++;
  }
  return fixed;
}

let _rebuildRetry = 0;
function retryRebuilds(): void {
  if (forceHuiCardRebuilds() > 0 || ++_rebuildRetry >= 10) return;
  setTimeout(retryRebuilds, 2000);
}
setTimeout(retryRebuilds, 1000);

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "E-Ink Dashboard",
  description: "Read-only WYSIWYG canvas preview of an e-ink dashboard",
});

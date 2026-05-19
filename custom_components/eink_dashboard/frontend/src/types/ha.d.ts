// Minimal type stubs for Home Assistant frontend APIs.
// Covers only the surface area used by eink-dashboard-card and editor.

export interface HassEntity {
  state: string;
  attributes: Record<string, unknown>;
}

export interface ConfigEntry {
  entry_id: string;
}

export interface HomeAssistant {
  states: Record<string, HassEntity>;
  areas: Record<string, { name: string }>;
  callApi<T = unknown>(method: string, path: string, data?: unknown): Promise<T>;
  callWS<T = unknown>(msg: Record<string, unknown>): Promise<T>;
  callService<T = unknown>(
    domain: string,
    service: string,
    data?: Record<string, unknown>,
    target?: unknown,
    notifyOnError?: boolean,
    returnResponse?: boolean,
  ): Promise<T>;
}

export interface HaFormSchema {
  name: string;
  type?: string;
  required?: boolean;
  default?: unknown;
  selector?: Record<string, unknown>;
  schema?: HaFormSchema[];
  /** When true on expandable/grid, child values stay flat in the data object. */
  flatten?: boolean;
  /** Header text shown on an expandable section panel. */
  title?: string;
  /** MDI icon name for an expandable section header (e.g. "mdi:palette"). */
  icon?: string;
  /** When true, the expandable section starts in the open state. */
  expanded?: boolean;
}

export interface HaFormElement extends HTMLElement {
  hass: HomeAssistant | null;
  data: Record<string, unknown>;
  schema: HaFormSchema[];
  computeLabel: (schema: HaFormSchema) => string;
  computeHelper: (schema: HaFormSchema) => string;
}

export interface HaSelectOption {
  value: string;
  label: string;
}

export interface HaSelectElement extends HTMLElement {
  options: HaSelectOption[];
  value: string;
}

export interface CustomCardInfo {
  type: string;
  name: string;
  description: string;
}

export interface DisplayConfig {
  width: number;
  height: number;
  grayscale_levels?: number;
}

export interface DeviceInfo {
  name: string;
  model: string;
  model_label: string;
  orientation: string;
  area_id: string | null;
  has_webhooks: boolean;
  device_battery_level: number | null;
}

export interface WidgetBounds {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface IndexedBounds extends WidgetBounds {
  index: number;
}

/** Card decoration style for card-style widgets. */
export type CardStyle = "border" | "left_bar" | "none";

/** Response from the eink_dashboard/render_widgets WebSocket command. */
export interface RenderWidgetsResponse {
  svgs: string[];
}

/** Response from the eink_dashboard/render_widget WebSocket command. */
export interface RenderWidgetResponse {
  svg: string;
}

export interface Handle {
  id: string;
  cx: number;
  cy: number;
}

export interface LayoutResponse {
  display: DisplayConfig;
  widgets: Widget[];
  device: DeviceInfo;
}

// ── Condition types ───────────────────────────────────────────────────────────
// Mirrors HA's validate-condition.ts.  Used by the visibility field on every
// widget type.

/** Discriminant base shared by all structured condition types. */
interface BaseCondition {
  /** Identifies the condition type (e.g. "state", "time"). */
  condition: string;
}

/**
 * Passes when the target entity's state matches (or does not match)
 * the given value(s).  Provide either `state` or `state_not`, not
 * both.  Values that look like entity IDs are resolved to that
 * entity's current state before comparison.
 */
export interface StateCondition extends BaseCondition {
  condition: "state";
  /** Entity ID whose state is tested. */
  entity?: string;
  /** State value(s) the entity must be in. */
  state?: string | string[];
  /** State value(s) the entity must NOT be in. */
  state_not?: string | string[];
}

/**
 * Passes when the target entity's numeric state falls within the
 * specified range.  Both bounds are exclusive.  Bound values that
 * look like entity IDs are resolved to that entity's numeric state.
 */
export interface NumericStateCondition extends BaseCondition {
  condition: "numeric_state";
  /** Entity ID whose numeric state is tested. */
  entity?: string;
  /** Lower exclusive bound — entity state must be strictly above. */
  above?: string | number;
  /** Upper exclusive bound — entity state must be strictly below. */
  below?: string | number;
}

/**
 * Passes when the browser viewport matches the CSS media query.
 * Always passes in server-side rendering (no viewport available).
 */
export interface ScreenCondition extends BaseCondition {
  condition: "screen";
  /** CSS media query string (e.g. "(min-width: 768px)"). */
  media_query?: string;
}

/**
 * Passes when the current time falls within the given range and/or
 * on one of the specified weekdays.  Supports midnight-crossing
 * ranges (e.g. after: "22:00", before: "06:00").
 */
export interface TimeCondition extends BaseCondition {
  condition: "time";
  /** Inclusive start time in HH:MM or HH:MM:SS format. */
  after?: string;
  /** Inclusive end time in HH:MM or HH:MM:SS format. */
  before?: string;
  /**
   * Short weekday names the condition is active on.
   * Valid values: "sun" | "mon" | "tue" | "wed" | "thu" | "fri" | "sat".
   */
  weekdays?: string[];
}

/**
 * Passes when the currently logged-in HA user matches one of the
 * listed user IDs.  Always passes in server-side rendering (no user
 * context available).
 */
export interface UserCondition extends BaseCondition {
  condition: "user";
  /** HA user IDs (not usernames) allowed to see this widget. */
  users?: string[];
}

/**
 * Passes when the current user's person entity is in one of the
 * listed zones.  Always passes in server-side rendering (no person
 * entity context available).
 */
export interface LocationCondition extends BaseCondition {
  condition: "location";
  /** Zone names (state values of the person entity). */
  locations?: string[];
}

/**
 * Passes when the view's column count falls within the given range.
 * Always passes in server-side rendering (no column layout context).
 */
export interface ViewColumnsCondition extends BaseCondition {
  condition: "view_columns";
  /** Minimum column count (inclusive). */
  min?: number;
  /** Maximum column count (inclusive). */
  max?: number;
}

/**
 * Passes when at least one nested condition passes (logical OR).
 * An empty `conditions` list is treated as passing.
 */
export interface OrCondition extends BaseCondition {
  condition: "or";
  /** Nested conditions — any one must be met. */
  conditions?: Condition[];
}

/**
 * Passes only when all nested conditions pass (logical AND).
 * An empty `conditions` list is treated as passing.
 */
export interface AndCondition extends BaseCondition {
  condition: "and";
  /** Nested conditions — all must be met. */
  conditions?: Condition[];
}

/**
 * Passes when none of the nested conditions pass (logical NOT of AND).
 * An empty `conditions` list is treated as passing.
 */
export interface NotCondition extends BaseCondition {
  condition: "not";
  /** Nested conditions — none may be met. */
  conditions?: Condition[];
}

/** Union of all structured condition types. */
export type Condition =
  | StateCondition
  | NumericStateCondition
  | ScreenCondition
  | TimeCondition
  | UserCondition
  | LocationCondition
  | ViewColumnsCondition
  | OrCondition
  | AndCondition
  | NotCondition;

/**
 * Legacy condition format used by older HA conditional cards.
 * Lacks a `condition` discriminant key; treated as a state condition.
 */
export interface LegacyCondition {
  /** Entity ID whose state is tested. */
  entity?: string;
  /** State value(s) the entity must be in. */
  state?: string | string[];
  /** State value(s) the entity must NOT be in. */
  state_not?: string | string[];
}

// ── Widget types ──────────────────────────────────────────────────────────────

interface WidgetBase {
  type: string;
  // Editor-only metadata — not rendered in the SVG output.
  label?: string;
  description?: string;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  font_size?: number;
  color?: number;
  visibility?: (Condition | LegacyCondition)[];
}

export interface TextWidget extends WidgetBase {
  type: "text";
  text?: string;
  align?: "left" | "center" | "right";
}

export interface SeparatorWidget extends WidgetBase {
  type: "separator";
  direction?: "horizontal" | "vertical";
  style?: "line" | "bar";
  length?: number;
}

export interface WeatherWidget extends WidgetBase {
  type: "weather";
  entity?: string;
  forecast_days?: number;
  card_style?: CardStyle;
}

export interface SensorRowsWidget extends WidgetBase {
  type: "sensor_rows";
  title?: string;
  entities?: string[];
  card_style?: CardStyle;
}

export interface DeviceBatteryWidget extends WidgetBase {
  type: "device_battery";
  layout?: "icon" | "chip";
  h?: number;
  card_style?: CardStyle;
}

export interface StatusIconsWidget extends WidgetBase {
  type: "status_icons";
  title?: string;
  entities?: string[];
  show_icon?: boolean;
  show_state?: boolean;
  card_style?: CardStyle;
}

export interface WasteScheduleEntry {
  attribute: string;
  label: string;
}

export interface WasteScheduleWidget extends WidgetBase {
  type: "waste_schedule";
  title?: string;
  entity?: string;
  entries?: WasteScheduleEntry[];
  layout?: "list" | "card";
  show_all?: boolean;
  card_style?: CardStyle;
}

export type Widget =
  | TextWidget
  | SeparatorWidget
  | WeatherWidget
  | SensorRowsWidget
  | DeviceBatteryWidget
  | StatusIconsWidget
  | WasteScheduleWidget;

export interface WidgetTypeMeta {
  label: string;
  /** One-line description shown in the widget picker grid. */
  description: string;
  /** MDI icon name (e.g. "mdi:thermometer") shown in the widget picker. */
  icon: string;
  defaults: Widget;
}

export interface EinkWidgetPicker extends HTMLElement {
  open(types: Record<string, WidgetTypeMeta>): void;
}

// ── Editor element interface ──────────────────────────────────────────────────

export interface EinkEditorElement extends HTMLElement {
  hass: HomeAssistant | null;
  setWidgets(widgets: Widget[]): void;
  setDisplay(display: DisplayConfig): void;
  setSaveState(state: "idle" | "saving" | "saved"): void;
}

// ── Global augmentations ──────────────────────────────────────────────────────

declare global {
  interface Window {
    customCards?: CustomCardInfo[];
  }
}

// Minimal type stubs for Home Assistant frontend APIs.
// Covers only the surface area used by eink-dashboard-card and editor.

/** Minimal state snapshot for a single HA entity. */
export interface HassEntity {
  /** Current state value (e.g. "on", "22.5"). */
  state: string;
  /** Entity attribute bag (friendly_name, unit_of_measurement, …). */
  attributes: Record<string, unknown>;
}

/** HA config entry descriptor passed to card elements. */
export interface ConfigEntry {
  /** Unique config entry ID used as the namespace for WebSocket commands. */
  entry_id: string;
}

/** Subset of the HA frontend `hass` object injected into custom cards. */
export interface HomeAssistant {
  /** Live entity-state map keyed by entity ID. */
  states: Record<string, HassEntity>;
  /** Area registry keyed by area ID. */
  areas: Record<string, { name: string }>;
  /** Make an authenticated REST API call to HA core. */
  callApi<T = unknown>(method: string, path: string, data?: unknown): Promise<T>;
  /** Make an authenticated WebSocket command call to HA core. */
  callWS<T = unknown>(msg: Record<string, unknown>): Promise<T>;
  /** Call a HA service. */
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

/** A single option in an `ha-select` dropdown. */
export interface HaSelectOption {
  /** The internal value stored in the config. */
  value: string;
  /** Human-readable label shown in the dropdown. */
  label: string;
}

/** Subset of the `ha-select` custom element API. */
export interface HaSelectElement extends HTMLElement {
  /** The full option list. */
  options: HaSelectOption[];
  /** Currently selected value. */
  value: string;
}

/** Descriptor used when registering a custom Lovelace card. */
export interface CustomCardInfo {
  /** Lovelace card type tag (e.g. "eink-dashboard-card"). */
  type: string;
  /** Human-readable card name shown in the card picker. */
  name: string;
  /** One-line description shown below the name in the card picker. */
  description: string;
}

/** Display dimensions passed to schema builders and the SVG renderer. */
export interface DisplayConfig {
  /** Canvas width in pixels. */
  width: number;
  /** Canvas height in pixels. */
  height: number;
  /**
   * Number of discrete gray levels the display supports.
   * 2 = black-and-white only; 16 = full grayscale.
   * Used to widen dividers and borders for low-depth displays.
   */
  grayscale_levels?: number;
}

/** Static device metadata returned by the `eink_dashboard/layout` WebSocket command. */
export interface DeviceInfo {
  /** Friendly device name from the HA device registry. */
  name: string;
  /** Device model identifier. */
  model: string;
  /** Human-readable model label for display. */
  model_label: string;
  /** Current orientation: "portrait" or "landscape". */
  orientation: string;
  /** HA area ID the device is assigned to, or null. */
  area_id: string | null;
  /** True when at least one TRMNL webhook target is configured. */
  has_webhooks: boolean;
  /** Battery percentage (0–100) from HA device registry, or null. */
  device_battery_level: number | null;
}

/** Pixel bounding box for a widget on the canvas. */
export interface WidgetBounds {
  /** Left edge in pixels. */
  x: number;
  /** Top edge in pixels. */
  y: number;
  /** Width in pixels. */
  w: number;
  /** Height in pixels. */
  h: number;
}

/** Widget bounding box with its list position. */
export interface IndexedBounds extends WidgetBounds {
  /** Zero-based index into the widget list. */
  index: number;
}

/** Card decoration style for card-style widgets. */
export type CardStyle = "border" | "left_bar" | "none";

/** Icon circle rendering mode for card-style widgets. */
export type IconStyle = "filled" | "outlined" | "none";

/** Response from the eink_dashboard/render_widgets WebSocket command. */
export interface RenderWidgetsResponse {
  svgs: string[];
}

/** Response from the eink_dashboard/render_widget WebSocket command. */
export interface RenderWidgetResponse {
  svg: string;
}

/** Drag handle for a widget resize corner or edge. */
export interface Handle {
  /** Handle identifier used to map mouse events to resize direction. */
  id: string;
  /** Centre X position in pixels (relative to the widget). */
  cx: number;
  /** Centre Y position in pixels (relative to the widget). */
  cy: number;
}

/** Response from the `eink_dashboard/layout` WebSocket command. */
export interface LayoutResponse {
  /** Current display dimensions and capabilities. */
  display: DisplayConfig;
  /** Ordered widget list stored in HA's persistent store. */
  widgets: Widget[];
  /** Static device descriptor for the display hardware. */
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

/**
 * Common fields shared by every widget type.
 *
 * All positional and sizing fields are optional because some widget
 * types auto-compute their dimensions from content.  The editor
 * always writes explicit values when saving.
 */
interface WidgetBase {
  /** Widget type discriminant (matches the WidgetType Python enum). */
  type: string;
  /** Editor-only display name; not rendered in the SVG output. */
  label?: string;
  /** Editor-only note; not rendered in the SVG output. */
  description?: string;
  /** Left edge of the widget in canvas pixels. */
  x?: number;
  /** Top edge of the widget in canvas pixels. */
  y?: number;
  /** Widget width in canvas pixels. */
  w?: number;
  /** Widget height in canvas pixels. */
  h?: number;
  /** Font size override (TEXT widget only). */
  font_size?: number;
  /** Foreground color as a grayscale integer (0 = black, 255 = white). */
  color?: number;
  /**
   * HA conditions that control widget visibility.
   * The widget is hidden when any condition evaluates to false.
   */
  visibility?: (Condition | LegacyCondition)[];
}

/**
 * Free-form text label rendered at an arbitrary position.
 *
 * @deprecated Use HeadingWidget for section headers.  TextWidget
 * remains supported for existing configs but is hidden from the
 * widget picker in new installations.
 */
export interface TextWidget extends WidgetBase {
  type: "text";
  /** The text string to render. */
  text?: string;
  /** Horizontal text alignment relative to the widget's x position. */
  align?: "left" | "center" | "right";
}

/** Horizontal or vertical divider line or filled bar. */
export interface SeparatorWidget extends WidgetBase {
  type: "separator";
  /** Orientation of the separator. */
  direction?: "horizontal" | "vertical";
  /** Visual style — thin rule or filled rectangle. */
  style?: "line" | "bar";
  /** Length in pixels; omit to span the full canvas dimension. */
  length?: number;
}

/** Weather forecast widget with conditions and temperature. */
export interface WeatherWidget extends WidgetBase {
  type: "weather";
  /** HA weather entity ID. */
  entity?: string;
  /** Number of forecast days to display (0–14). */
  forecast_days?: number;
  /** Decorative frame style. */
  card_style?: CardStyle;
}

/**
 * Multi-entity sensor list displayed as icon rows.
 *
 * @deprecated Use TileWidget for new layouts; this type remains
 * supported for existing configs but is hidden from the widget picker.
 */
export interface SensorRowsWidget extends WidgetBase {
  type: "sensor_rows";
  /** Optional card header text. */
  title?: string;
  /** Ordered list of entity IDs to display. */
  entities?: string[];
  /** Decorative frame style. */
  card_style?: CardStyle;
}

/** Device battery level indicator in icon or chip layout. */
export interface DeviceBatteryWidget extends WidgetBase {
  type: "device_battery";
  /** Visual layout mode for the indicator. */
  layout?: "icon" | "chip";
  /** Decorative frame style. */
  card_style?: CardStyle;
}

/**
 * Row of entity status chips with icon and optional state text.
 *
 * @deprecated Use TileWidget for new layouts; this type remains
 * supported for existing configs but is hidden from the widget picker.
 */
export interface StatusIconsWidget extends WidgetBase {
  type: "status_icons";
  /** Optional card header text. */
  title?: string;
  /** Ordered list of entity IDs to display. */
  entities?: string[];
  /** When true, renders an icon circle for each entity. */
  show_icon?: boolean;
  /** When true, renders the entity state text alongside the icon. */
  show_state?: boolean;
  /** Decorative frame style. */
  card_style?: CardStyle;
}

/** A single waste-collection type entry in the schedule widget. */
export interface WasteScheduleEntry {
  /** State attribute key on the sensor entity that holds the next date. */
  attribute: string;
  /** Human-readable label shown next to the date (e.g. "Recycling"). */
  label: string;
}

/** Waste-collection schedule widget with relative dates. */
export interface WasteScheduleWidget extends WidgetBase {
  type: "waste_schedule";
  /** Optional card header text. */
  title?: string;
  /** HA sensor entity from waste_collection_schedule integration. */
  entity?: string;
  /** Ordered list of waste types to show. */
  entries?: WasteScheduleEntry[];
  /** Visual layout mode for the schedule entries. */
  layout?: "list" | "card";
  /**
   * When false (default), the widget is blank unless a collection
   * falls within the next 3 days.  When true, always shows all entries.
   */
  show_all?: boolean;
  /** Decorative frame style. */
  card_style?: CardStyle;
}

/** Single-entity tile card modelled after the HA Tile card. */
export interface TileWidget extends WidgetBase {
  type: "tile";
  /** HA entity ID to display (required at runtime). */
  entity?: string;
  /** Override the entity's friendly name shown as the primary label. */
  name?: string;
  /** Override the icon (MDI name, e.g. "mdi:thermometer"). */
  icon?: string;
  /** When true, suppresses the secondary state/attribute line. */
  hide_state?: boolean;
  /**
   * Attribute key (or priority-ordered list of keys) to show as the
   * secondary text.  When absent, falls back to state + unit.
   */
  state_content?: string | string[];
  /**
   * Reserved — entity picture URLs require HTTP fetching which resvg
   * does not support.  Accepted in config but ignored in rendering.
   */
  show_entity_picture?: boolean;
  /** Decorative frame style. */
  card_style?: CardStyle;
  /** Icon circle rendering mode (auto-selected when absent). */
  icon_style?: IconStyle;
}

/**
 * A single entity badge displayed to the right of the heading text.
 *
 * Accepts either a plain entity ID string (shorthand for
 * ``{ entity: "...", show_icon: false }``) or a full config object.
 * When the entity is missing from HA states, the badge is silently
 * omitted at render time.
 */
export interface HeadingBadge {
  /** HA entity ID to display as a badge. */
  entity: string;
  /** Override label; unused in current renderer but reserved. */
  name?: string;
  /** MDI icon name override for the badge (e.g. "mdi:thermometer"). */
  icon?: string;
  /**
   * When true, the entity state value is shown next to the badge icon.
   * Default: true.
   */
  show_state?: boolean;
  /**
   * When true, an icon is rendered alongside the badge text.
   * Default: false.
   */
  show_icon?: boolean;
}

/**
 * Section heading modelled after the HA Heading card.
 *
 * Renders an optional MDI icon on the left, a heading text string in
 * the centre, and optional entity badges flowing from the right edge.
 * Use this widget instead of the deprecated TextWidget for section
 * headers.
 */
export interface HeadingWidget extends WidgetBase {
  type: "heading";
  /**
   * Heading text to display.  Supports Jinja2 templates (rendered
   * server-side before SVG generation).
   */
  heading?: string;
  /**
   * Visual style for the heading text.
   * - ``"title"`` — large Roboto Medium in black (default).
   * - ``"subtitle"`` — smaller Roboto Regular in gray.
   */
  heading_style?: "title" | "subtitle";
  /** MDI icon name rendered to the left of the text (e.g. "mdi:home"). */
  icon?: string;
  /**
   * List of entity IDs or badge config objects.  Each resolves to a
   * small text chip displayed to the right of the heading.
   */
  badges?: (string | HeadingBadge)[];
  /**
   * Icon circle rendering mode.
   * - ``"none"`` — no circle; icon sized to match the heading font
   *   (default).
   * - ``"filled"`` — gray-filled circle.
   * - ``"outlined"`` — white circle with black border.
   */
  icon_style?: IconStyle;
  /** Decorative frame style. */
  card_style?: CardStyle;
}

/**
 * Single-entity display with large state value, modelled after
 * HA's Entity card (``hui-entity-card.ts``).
 */
export interface EntityWidget extends WidgetBase {
  type: "entity";
  /** HA entity ID to display. */
  entity: string;
  /** Override display name; falls back to the entity's friendly_name. */
  name?: string;
  /** MDI icon name override (e.g. "mdi:thermometer"). */
  icon?: string;
  /**
   * Attribute key to display as the value instead of the entity
   * state.  When set, automatic unit resolution is suppressed.
   */
  attribute?: string;
  /** Unit string override; shown next to the value. */
  unit?: string;
  /** Decorative frame style. */
  card_style?: CardStyle;
  /**
   * Icon circle rendering mode.
   * - ``"filled"`` — gray-filled circle (default for active states).
   * - ``"outlined"`` — white circle with black border (default for
   *   inactive states and 2-level displays).
   * - ``"none"`` — no circle; icon glyph rendered without decoration.
   */
  icon_style?: IconStyle;
}

export type Widget =
  | TextWidget
  | SeparatorWidget
  | WeatherWidget
  | SensorRowsWidget
  | DeviceBatteryWidget
  | StatusIconsWidget
  | WasteScheduleWidget
  | TileWidget
  | HeadingWidget
  | EntityWidget;

/** Registry entry for one widget type shown in the widget picker grid. */
export interface WidgetTypeMeta {
  /** Human-readable type name (e.g. "Tile"). */
  label: string;
  /** One-line description shown in the widget picker grid. */
  description: string;
  /** MDI icon name (e.g. "mdi:thermometer") shown in the widget picker. */
  icon: string;
  /** Default config written to the widget list when the type is picked. */
  defaults: Widget;
}

/** Custom element interface for the widget-type picker dialog. */
export interface EinkWidgetPicker extends HTMLElement {
  /** Show the picker modal populated with the given widget types. */
  open(types: Record<string, WidgetTypeMeta>): void;
}

// ── Editor element interface ──────────────────────────────────────────────────

/** Custom element interface for the widget list editor panel. */
export interface EinkEditorElement extends HTMLElement {
  /** Live hass object injected by the Lovelace runtime. */
  hass: HomeAssistant | null;
  /** Replace the editor's widget list (called after a store reload). */
  setWidgets(widgets: Widget[]): void;
  /** Update the display dimensions used by schema builders. */
  setDisplay(display: DisplayConfig): void;
  /** Drive the save-state indicator in the editor toolbar. */
  setSaveState(state: "idle" | "saving" | "saved"): void;
}

// ── Global augmentations ──────────────────────────────────────────────────────

declare global {
  interface Window {
    customCards?: CustomCardInfo[];
  }
}

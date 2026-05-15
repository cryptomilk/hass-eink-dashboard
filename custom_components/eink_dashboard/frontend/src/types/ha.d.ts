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

// ── Widget types ──────────────────────────────────────────────────────────────

interface WidgetBase {
  type: string;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  font_size?: number;
  color?: number;
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

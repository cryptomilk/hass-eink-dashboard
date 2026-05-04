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
}

export interface DeviceInfo {
  name: string;
  model: string;
  model_label: string;
  orientation: string;
  area_id: string | null;
  has_webhooks: boolean;
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

export interface Handle {
  id: string;
  cx: number;
  cy: number;
}

export interface ForecastDay {
  datetime?: string;
  condition?: string;
  temperature?: number;
  templow?: number;
  precipitation?: number;
}

export interface LayoutResponse {
  display: DisplayConfig;
  widgets: Widget[];
  device: DeviceInfo;
}

export interface ForecastServiceResult {
  response?: Record<string, { forecast?: ForecastDay[] }>;
}

// ── Widget types ──────────────────────────────────────────────────────────────

interface WidgetBase {
  type: string;
  x?: number;
  y?: number;
  w?: number;
  font_size?: number;
  color?: number;
}

export interface TextWidget extends WidgetBase {
  type: "text";
  text?: string;
  align?: "left" | "center" | "right";
}

export interface LineWidget extends WidgetBase {
  type: "line";
  x2?: number;
  y2?: number;
  width?: number;
}

export interface SeparatorWidget extends WidgetBase {
  type: "separator";
}

export interface WeatherWidget extends WidgetBase {
  type: "weather";
  entity?: string;
  forecast_days?: number;
}

export interface SensorRowsWidget extends WidgetBase {
  type: "sensor_rows";
  title?: string;
  entities?: string[];
}

export interface BatteryBarWidget extends WidgetBase {
  type: "battery_bar";
  entity?: string;
}

export interface StatusIconsWidget extends WidgetBase {
  type: "status_icons";
  title?: string;
  entities?: string[];
}

export interface WasteScheduleWidget extends WidgetBase {
  type: "waste_schedule";
  title?: string;
  entities?: string[];
}

export type Widget =
  | TextWidget
  | LineWidget
  | SeparatorWidget
  | WeatherWidget
  | SensorRowsWidget
  | BatteryBarWidget
  | StatusIconsWidget
  | WasteScheduleWidget;

export interface WidgetTypeMeta {
  label: string;
  defaults: Widget;
}

// ── Editor element interface ──────────────────────────────────────────────────

export interface EinkEditorElement extends HTMLElement {
  hass: HomeAssistant | null;
  setWidgets(widgets: Widget[]): void;
  setDisplay(display: DisplayConfig): void;
}

// ── Global augmentations ──────────────────────────────────────────────────────

declare global {
  interface Window {
    customCards?: CustomCardInfo[];
  }
}

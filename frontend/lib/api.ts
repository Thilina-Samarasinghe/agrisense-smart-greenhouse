export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_URL = API_URL.replace(/^http/, "ws");

// ------------------------------------------------------------------ types

export type Range = [number, number];

export type ZoneConfig = {
  id: string;
  name: string;
  crop: string;
  crop_name: string;
  stage: string;
  area_m2: number;
  targets: {
    temp_day_c: Range;
    temp_night_c: Range;
    rh_pct: Range;
    vwc: Range;
    dli_mol_m2d: Range;
    co2_ppm: Range;
  };
  soil: { type: string; field_capacity: number; wilting_point: number; saturation: number };
  actuators: string[];
  sensors: string[];
};

export type ScenarioInfo = {
  name: string;
  description: string;
  default_duration_h: number;
  params: Record<string, unknown>;
};

export type AppConfig = {
  greenhouse: { id: string; name: string; tank_capacity_l: number; location: Record<string, number> };
  zones: ZoneConfig[];
  actuators: Record<string, { kind: string; zone_id: string | null; power_w: number }>;
  scenarios: ScenarioInfo[];
  control: { day_window: [string, string]; lighting_window: [string, string] };
};

export type Alert = {
  id: number;
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
  zone_id: string | null;
  subject: string | null;
  latched: boolean;
  raised_at: string;
  cleared_at: string | null;
  active: boolean;
};

export type Decision = {
  ts: string;
  actuator_id: string;
  zone_id: string | null;
  from_level: number;
  to_level: number;
  rule: string;
  source: string;
  message: string;
};

export type ActuatorLive = {
  kind: string;
  zone_id: string | null;
  level: number;
  fault: string | null;
  energy_wh: number;
  rule?: string;
  reason?: string;
  source?: string;
  mode?: "auto" | "manual" | "off";
  override_until?: string | null;
};

export type ZoneLive = {
  true: {
    temp_c: number;
    rh_pct: number;
    vpd_kpa: number;
    co2_ppm: number;
    vwc_pct: number;
    par_umol: number;
    dli_mol: number;
    soil_temp_c: number;
    et_mm_h: number;
    water_stress_ks: number;
  };
  measured: { temp: number | null; rh: number | null; vwc_pct: number | null; lux: number | null };
  irrigation: string | null;
  fan_stage: number | null;
  dli_estimate: number | null;
  irrigation_lpm: number;
};

export type ActiveScenario = {
  id: number;
  name: string;
  params: Record<string, unknown>;
  started: string;
  ends: string | null;
};

export type LiveState = {
  time: string;
  run_id: number;
  speed: number;
  paused: boolean;
  lagging: boolean;
  control: boolean;
  emergency_stop: boolean;
  weather: {
    temp_c: number;
    rh_pct: number;
    solar_w_m2: number;
    cloud: number;
    wind_ms: number;
    rain_mm_h: number;
  };
  tank: { level_pct: number; volume_l: number };
  zones: Record<string, ZoneLive>;
  actuators: Record<string, ActuatorLive>;
  alerts: Alert[];
  decisions: Decision[];
  scenarios: ActiveScenario[];
};

export type ZonePoint = {
  ts: string;
  temp_c: number;
  rh_pct: number;
  vpd_kpa: number;
  co2_ppm: number;
  vwc: number;
  soil_temp_c: number;
  par_umol: number;
  dli_mol: number;
  et_mm_h: number;
  measured_temp_c: number | null;
  measured_rh_pct: number | null;
  measured_vwc_pct: number | null;
  measured_lux: number | null;
  fan: number;
  valve: number;
  light: number;
  mister: number;
};

export type SensorRow = {
  sensor_id: string;
  zone_id: string | null;
  quantity: string;
  model: string | null;
  value: number | null;
  raw: number | null;
  unit: string;
  quality: string;
  ts: string;
  health: string | null;
  fault: string | null;
};

type Stats = { min: number; mean: number; max: number } | null;
type Equipment = { energy_kwh: number; runtime_h: number; activations: number };

export type Summary = {
  since: string;
  until: string;
  hours: number;
  zones: Record<
    string,
    {
      name: string;
      crop: string;
      samples: number;
      temp_c: Stats;
      rh_pct: Stats;
      vwc: Stats;
      co2_ppm: Stats;
      water: { irrigation_l: number; et_l: number };
      irrigation_minutes: number;
      violation_minutes: { temp: number; rh: number; vwc: number };
      equipment: Record<string, Equipment>;
    }
  >;
  pump: Equipment | null;
  energy_kwh_by_kind: Record<string, number>;
  energy_kwh_total: number;
  rain_harvested_l: number;
  alerts_by_code: Record<string, number>;
  alerts_by_severity: Record<string, number>;
  decisions: number;
};

// ------------------------------------------------------------------ requests

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body: unknown = {}) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
export const del = (path: string) => request<void>(path, { method: "DELETE" });

export type Health = { status: string; app: string; version: string };

export async function getHealth(): Promise<Health | null> {
  try {
    return await get<Health>("/api/health");
  } catch {
    return null;
  }
}

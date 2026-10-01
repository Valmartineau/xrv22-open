// Wrappers typés des endpoints POST (Etapes 4 + ajouts).

import { authFetch } from "./auth";

async function send<T>(method: "GET" | "POST" | "DELETE" | "PUT", path: string, body?: object): Promise<T> {
  const res = await authFetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    const msg = typeof detail === "string" ? detail : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data as T;
}

const post = <T,>(p: string, b?: object) => send<T>("POST", p, b);
const del  = <T,>(p: string)             => send<T>("DELETE", p);
const put  = <T,>(p: string, b?: object) => send<T>("PUT", p, b);

// Robots
export const cmdConnect    = (rid: string, port?: string) =>
  post<{ ok: boolean; connected: boolean; port: string }>(
    `/api/robots/${rid}/connect`, port ? { port } : {}
  );
export const cmdDisconnect = (rid: string) =>
  post<{ ok: boolean; connected: boolean }>(`/api/robots/${rid}/disconnect`);
export const cmdTorque     = (rid: string, enable: boolean) =>
  post<{ ok: boolean; torque_enabled: boolean }>(
    `/api/robots/${rid}/torque`, { enable }
  );
export const cmdMaster     = (rid: string) =>
  post<{ ok: boolean; master: string }>(`/api/robots/${rid}/master`);
export const cmdReboot     = (rid: string) =>
  post<{ ok: boolean; torque_enabled: boolean; state: string }>(
    `/api/robots/${rid}/reboot`
  );
export const cmdHome       = (rid: string, kind: "machine" | "work") =>
  post<{ ok: boolean; message: string; kind: string }>(
    `/api/robots/${rid}/home`, { kind }
  );
export const cmdCalib      = (rid: string, kind: "machine" | "work") =>
  post<{ ok: boolean; kind: string; robot_id: string;
         positions: Record<string, number> }>(
    `/api/robots/${rid}/calib`, { kind }
  );
export const cmdStop       = (rid: string) =>
  post<{ ok: boolean; state: string }>(`/api/robots/${rid}/stop`);
export const cmdWriteDirect = (rid: string, positions: Record<string, number>) =>
  post<{ ok: boolean; positions: Record<string, number> }>(
    `/api/robots/${rid}/positions`, { positions }
  );
export const cmdDirectMode = (rid: string, enable: boolean) =>
  post<{ ok: boolean; direct: boolean }>(
    `/api/robots/${rid}/direct_mode`, { enable }
  );
// Couche anticollision serveur (boîtes STL) — par robot, tous chemins de pilotage.
export const cmdAnticollision = (rid: string, enable: boolean) =>
  post<{ ok: boolean; enabled: boolean }>(
    `/api/robots/${rid}/anticollision`, { enable }
  );
export const getAnticollision = (rid: string) =>
  send<{ enabled: boolean; available: boolean }>(
    "GET", `/api/robots/${rid}/anticollision`
  );
export const cmdMotorLimit = (rid: string, motor_id: number, lo: number, hi: number) =>
  post<{ ok: boolean; robot_id: string; motor_id: number; lo: number; hi: number }>(
    `/api/robots/${rid}/motor_limit`, { motor_id, lo, hi }
  );

// Zones (Chantier 1 + Phase 1 unification)
import type { ZoneType } from "./zoneTypes";

export type ZoneRec = {
  id: string;
  name: string;
  zone_type: ZoneType;
  points: number[][];
  color: string;
  visible: boolean;
  plane_axis?: string;
  source_robot_id?: string;
};

export type ZoneCreateBody = Omit<ZoneRec, "id" | "plane_axis"> & {
  source_robot_id?: string;
};

export type ZoneUpdateBody = Partial<Pick<ZoneRec, "name" | "zone_type" | "visible" | "color">>;

export const cmdListZones = async (): Promise<ZoneRec[]> => {
  const r = await authFetch(`/api/zones`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as ZoneRec[];
};
export const cmdCreateZone = (z: ZoneCreateBody) =>
  post<{ ok: boolean; id: string; name: string }>(`/api/zones`, z);
export const cmdUpdateZone = (zid: string, patch: ZoneUpdateBody) =>
  put<{ ok: boolean; id: string }>(`/api/zones/${zid}`, patch);
export const cmdDeleteZone = (zid: string) =>
  del<{ ok: boolean; id: string }>(`/api/zones/${zid}`);
export const cmdGetTcp = (rid: string) =>
  post<{ ok: boolean; x: number; y: number; z: number;
         positions: Record<string, number> }>(`/api/robots/${rid}/tcp`);

// Robot actif (sync Web <-> Pi tactile)
export const cmdGetActiveRobot = async (): Promise<{ active_robot_id: string }> => {
  const r = await authFetch(`/api/ui/active_robot`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json() as { active_robot_id: string };
};
export const cmdSetActiveRobot = (robot_id: string) =>
  put<{ ok: boolean; active_robot_id: string; changed: boolean }>(
    `/api/ui/active_robot`, { robot_id });

// Devices Arduino (Chantier 5 + branchement backend)
export type SensorChannelRec = {
  name: string; unit: string; value: number; min_val: number; max_val: number; updated: number;
};
export type ActuatorRec = {
  name: string; kind: string; label: string; min_val: number; max_val: number;
  last_value: number; state_on: boolean;
};
export type ActionRec = {
  name: string; label: string; description: string;
  params: unknown[]; duration_ms: number; has_ack: boolean;
};
export type DeviceRec = {
  id: string; name: string; port: string; baud: number; device_type: string;
};
export type DeviceLive = {
  name: string; port?: string; baud?: number;
  connected: boolean; identified: boolean; firmware: string; error: string;
  channels: SensorChannelRec[]; actuators: ActuatorRec[]; actions: ActionRec[];
};
export type PortRec = { device: string; description: string; vid: number | null; is_arduino: boolean };

export const cmdListPorts = () =>
  authFetch("/api/hardware/ports").then((r) => r.json()) as Promise<{ ports: PortRec[] }>;
export const cmdAddDevice = (name: string, port: string, baud = 115200) =>
  post<{ ok: boolean; device: DeviceRec }>(`/api/hardware/devices`, { name, port, baud });
export const cmdDeleteDevice = (did: string) =>
  del<{ ok: boolean; id: string }>(`/api/hardware/devices/${did}`);
export const cmdGetDevice = (did: string) =>
  authFetch(`/api/hardware/devices/${did}`).then((r) => r.json()) as Promise<DeviceLive>;
export const cmdConnectDevice = (did: string) =>
  post<{ ok: boolean; connected: boolean }>(`/api/hardware/devices/${did}/connect`);
export const cmdDisconnectDevice = (did: string) =>
  post<{ ok: boolean; connected: boolean }>(`/api/hardware/devices/${did}/disconnect`);
export const cmdSetActuator = (did: string, act: string, value: number) =>
  post<{ ok: boolean }>(`/api/hardware/devices/${did}/actuators/${act}`, { value });
export const cmdRunAction = (did: string, action: string, params: Record<string, unknown> = {}) =>
  post<{ ok: boolean; message: string }>(`/api/hardware/devices/${did}/actions/${action}`, { params });
export const cmdSendRaw = (did: string, raw: string) =>
  post<{ ok: boolean }>(`/api/hardware/devices/${did}/raw`, { raw });
export const cmdSetRule = (did: string, sensor: string, min_val: number | null, max_val: number | null) =>
  post<{ ok: boolean }>(`/api/hardware/devices/${did}/sensors/${sensor}/rule`, { min_val, max_val });

// DXF / G-code Import (Chantiers 2 + 3) — multipart
export async function cmdImportDxf(
  file: File, scenarioId: string, robotId: string,
  durationS = 2.0, zSurface = 100.0, toolAngle = 3.14159,
): Promise<{ ok: boolean; waypoints: number; duration_total_s: number }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("scenario_id", scenarioId);
  fd.append("robot_id", robotId);
  fd.append("duration_s", String(durationS));
  fd.append("z_surface", String(zSurface));
  fd.append("tool_angle", String(toolAngle));
  const res = await authFetch("/api/dxf", { method: "POST", body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return data;
}

export async function cmdImportGcode(
  file: File, scenarioId: string, robotId: string,
  durationS = 2.0, zSurface = 100.0, toolAngle = 3.14159,
): Promise<{ ok: boolean; waypoints: number; duration_total_s: number }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("scenario_id", scenarioId);
  fd.append("robot_id", robotId);
  fd.append("duration_s", String(durationS));
  fd.append("z_surface", String(zSurface));
  fd.append("tool_angle", String(toolAngle));
  const res = await authFetch("/api/gcode", { method: "POST", body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return data;
}

// Robots CRUD
export const cmdAddRobot    = (robot_id: string, motor_ids?: number[]) =>
  post<{ ok: boolean; robot_id: string }>(`/api/robots`,
    motor_ids ? { robot_id, motor_ids } : { robot_id });
export const cmdRemoveRobot = (rid: string) =>
  del<{ ok: boolean; robot_id: string }>(`/api/robots/${rid}`);

// Projects
export const cmdProjectNew    = (name: string) =>
  post<{ ok: boolean; name: string }>(`/api/projects/new`, { name });
export const cmdProjectLoad   = (path: string) =>
  post<{ ok: boolean; path: string }>(`/api/projects/load`, { path });
export const cmdProjectSave   = () =>
  post<{ ok: boolean }>(`/api/projects/save`);
export const cmdProjectExport = (path: string) =>
  post<{ ok: boolean; destination: string }>(`/api/projects/export`, { path });

// Hardware
export type CouplingCfg = {
  enabled: boolean; invert: boolean; ratio: number; offset: number; center: number;
};
export const cmdSetCoupling = (cfg: Partial<CouplingCfg>) =>
  post<{ ok: boolean; coupling: CouplingCfg }>(`/api/hardware/coupling`, cfg);

// Positions
export const cmdCapture    = (robot_id: string, name: string,
                              category = "sauvegardees",
                              positions?: Record<string, number>) =>
  post<{ ok: boolean; id: string; name: string;
         positions: Record<string, number> }>(
    `/api/positions`,
    positions ? { robot_id, name, category, positions }
              : { robot_id, name, category }
  );

export const cmdDeletePosition = (pid: string) =>
  del<{ ok: boolean; id: string }>(`/api/positions/${pid}`);
export const cmdGotoPosition   = (pid: string, robot_id: string, duration_s = 3.0) =>
  post<{ ok: boolean; position_id: string; name: string }>(
    `/api/positions/${pid}/goto`, { robot_id, duration_s }
  );

export type PositionConflict = { type: string; severity: string; message: string };

export const cmdCheckPosition = (rid: string, positions: Record<string, number>) =>
  post<{ ok: boolean; conflicts: PositionConflict[] }>(
    `/api/robots/${rid}/check_position`, { positions }
  );

export const cmdUpdatePosition = (pid: string, positions: Record<string, number>) =>
  put<{ ok: boolean; id: string }>(`/api/positions/${pid}`, { positions });

// Suites
export const cmdCreateSuite = (name: string,
                               steps: object[] = [], meta: object = {}) =>
  post<{ ok: boolean; id: string; name: string }>(
    `/api/suites`, { name, steps, meta }
  );
export const cmdDeleteSuite = (sid: string) =>
  del<{ ok: boolean; id: string }>(`/api/suites/${sid}`);
export const cmdUpdateSuite = (sid: string,
  patch: { name?: string; steps?: object[]; meta?: object }) =>
  put<{ ok: boolean; id: string }>(`/api/suites/${sid}`, patch);

// Scenarios
export const cmdScenarioPlay = (sid: string, from_ms = 0) =>
  post<{ ok: boolean; scenario_id: string; state: string }>(
    `/api/scenarios/${sid}/play`, { from_ms }
  );
export const cmdScenarioStop = (sid: string) =>
  post<{ ok: boolean; state: string }>(`/api/scenarios/${sid}/stop`);

// Settings safety (Phase 2)
export const cmdGetSafety = async (): Promise<{ collision_check_enabled: boolean }> => {
  const r = await authFetch(`/api/settings/safety`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
};
export const cmdSetSafety = (collision_check_enabled: boolean) =>
  put<{ ok: boolean; collision_check_enabled: boolean }>(
    `/api/settings/safety`, { collision_check_enabled });

// Eddy — dialogue-en-mouvement : dépose un message dans la boîte aux lettres du
// run (injecté dans le prompt au pas suivant) ; le serveur republie un echo
// immédiat sur le bus (topic eddy.say) que /eddy affiche tout de suite.
export const cmdEddySay = (message: string) =>
  post<{ ok: boolean }>(`/api/eddy/say`, { message });

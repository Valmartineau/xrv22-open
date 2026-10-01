// Modeles partages avec l'API Pi (xrv22/server/api.py)

export type Robot = {
  id: string;
  is_master: boolean;
  connected: boolean;
  port: string;
  torque_enabled: boolean;
  state: string;
  smooth_hz: number;
  comfort_vel: number;
  comfort_acc: number;
  // Etape 6 P1 : limites + homes pour les sliders
  soft_limits?: Record<string, [number, number]>;
  home_machine?: Record<string, number>;
  home_work?: Record<string, number>;
};

export type Health = {
  status: string;
  version: string;
  robots: string[];
  master: string | null;
};

// Message WebSocket : {topic, data, ts}
export type WsMsg<T = unknown> = {
  topic: string;
  data: T;
  ts: number;
};

// Topic robot.positions_tick : {robot_id: {axis_str: ticks}}
export type PositionsTick = Record<string, Record<string, number>>;

// Library
export type PositionRec = {
  id: string;
  name: string;
  category: string;
  positions: Record<string, number>;
  created_at: string;
  modified_at: string;
  meta?: Record<string, unknown>;
};

export type SuiteStep = {
  position_id: string;
  position_name?: string;
  duration_s?: number;
  pause_s?: number;
};

export type SuiteRec = {
  id: string;
  name: string;
  steps: SuiteStep[];
  meta?: Record<string, unknown>;
};

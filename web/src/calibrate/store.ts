import { useEffect, useState } from "react";
import type { Vec3 } from "../visu/fk";

export type PartCalib = {
  name: string;
  url: string;
  axisLocal: Vec3 | null;
  targetJoint: number | null;
  offset: Vec3;
  rot: Vec3;
  locked?: boolean; // pièce figée individuellement
};
export type CalibState = { parts: PartCalib[] };

const STORAGE_KEY = "xrv22.calibrate.v2";

export function toExportJSON(state: CalibState) {
  const out: Record<string, { offset: Vec3; rot: Vec3; joint: number }> = {};
  for (const p of state.parts) {
    if (p.targetJoint == null) continue;
    out[p.name] = { offset: p.offset, rot: p.rot, joint: p.targetJoint };
  }
  return out;
}

const EMPTY: CalibState = { parts: [] };

function load(): CalibState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw);
    return { parts: Array.isArray(parsed.parts) ? parsed.parts : [] };
  } catch {
    return EMPTY;
  }
}

export function useCalibStore() {
  const [state, setState] = useState<CalibState>(load);
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* quota / mode privé : ignore */
    }
  }, [state]);
  return [state, setState] as const;
}

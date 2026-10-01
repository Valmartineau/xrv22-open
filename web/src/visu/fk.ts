import { Quaternion, Vector3 } from "three";

export type Vec3 = [number, number, number];
export type FK = [Vec3, Vec3, Vec3, Vec3, Vec3, Vec3, Vec3];

export const KIN = {
  BASE_H: 65.0, SHOULDER_H: 38.91,
  UA_X: 0.0, UA_Z: 210.0,
  L_FARM: 200.0, L_WRIST: 50.0, L_TOOL: 50.0,
};
// REF_UP recalé à la pose droite (2026-05-29) : épaule 1900, coude 1180
export const REF_UP: Record<number, number> = { 1: 2020, 2: 1900, 4: 1180, 5: 2061, 6: 2042 };

export function jointAngle(t: Record<string, number> | undefined, axis: number): number {
  const ref = REF_UP[axis] ?? 2048;
  const tick = t?.[String(axis)] ?? ref;
  return ((tick - ref) * 360.0 / 4096.0) * Math.PI / 180;
}

export function fk(t: Record<string, number> | undefined): FK {
  const a1 = jointAngle(t, 1);
  const a2 = jointAngle(t, 2);
  const a4 = jointAngle(t, 4);
  const a5 = jointAngle(t, 5);
  const hx = Math.sin(a1), hy = Math.cos(a1);
  const { BASE_H, SHOULDER_H, UA_X, UA_Z, L_FARM, L_WRIST, L_TOOL } = KIN;
  const j0: Vec3 = [0, 0, 0];
  const j1: Vec3 = [0, 0, BASE_H];
  const j2: Vec3 = [0, 0, BASE_H + SHOULDER_H];
  const s2 = Math.sin(a2), c2 = Math.cos(a2);
  const rUa = s2 * UA_Z + c2 * UA_X;
  const zUa = c2 * UA_Z - s2 * UA_X;
  const j3: Vec3 = [j2[0] + hx * rUa, j2[1] + hy * rUa, j2[2] + zUa];
  const a24 = a2 + a4;
  const s24 = Math.sin(a24), c24 = Math.cos(a24);
  const j4: Vec3 = [j3[0] + hx * s24 * L_FARM, j3[1] + hy * s24 * L_FARM, j3[2] + c24 * L_FARM];
  const a245 = a24 + a5;
  const s245 = Math.sin(a245), c245 = Math.cos(a245);
  const j5: Vec3 = [j4[0] + hx * s245 * L_WRIST, j4[1] + hy * s245 * L_WRIST, j4[2] + c245 * L_WRIST];
  const j6: Vec3 = [j5[0] + hx * s245 * L_TOOL, j5[1] + hy * s245 * L_TOOL, j5[2] + c245 * L_TOOL];
  return [j0, j1, j2, j3, j4, j5, j6];
}

export function dirQuat(a: Vec3, b: Vec3): Quaternion {
  const d = new Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  if (d.lengthSq() < 1e-9) return new Quaternion();
  return new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), d.normalize());
}

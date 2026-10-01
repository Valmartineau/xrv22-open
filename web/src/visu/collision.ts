// Géométrie de collision (capsules) pour XRV22 — module pur, sans React.
// Auto-collision (segments non adjacents d'un même robot) + inter-robots.
// Spec : docs/superpowers/specs/2026-06-10-anticollision-design.md
import type { Vec3 } from "./fk";
import { calibJoints, type CalibData } from "./calibKinematics";

function sub(a: Vec3, b: Vec3): Vec3 { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function dot(a: Vec3, b: Vec3): number { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function clamp01(v: number): number { return Math.max(0, Math.min(1, v)); }

// Distance minimale entre les segments [p1,q1] et [p2,q2] (Ericson, RTCD §5.1.9).
export function segDist(p1: Vec3, q1: Vec3, p2: Vec3, q2: Vec3): number {
  const d1 = sub(q1, p1);   // direction segment 1
  const d2 = sub(q2, p2);   // direction segment 2
  const r = sub(p1, p2);
  const a = dot(d1, d1);
  const e = dot(d2, d2);
  const f = dot(d2, r);
  const EPS = 1e-9;
  let s: number, t: number;
  if (a <= EPS && e <= EPS) { s = 0; t = 0; }
  else if (a <= EPS) { s = 0; t = clamp01(f / e); }
  else {
    const c = dot(d1, r);
    if (e <= EPS) { t = 0; s = clamp01(-c / a); }
    else {
      const b = dot(d1, d2);
      const denom = a * e - b * b;
      s = denom > EPS ? clamp01((b * f - c * e) / denom) : 0;
      t = (b * s + f) / e;
      if (t < 0) { t = 0; s = clamp01(-c / a); }
      else if (t > 1) { t = 1; s = clamp01((b - c) / a); }
    }
  }
  const c1: Vec3 = [p1[0] + d1[0] * s, p1[1] + d1[1] * s, p1[2] + d1[2] * s];
  const c2: Vec3 = [p2[0] + d2[0] * t, p2[1] + d2[1] * t, p2[2] + d2[2] * t];
  const dx = sub(c1, c2);
  return Math.sqrt(dot(dx, dx));
}

export type RobotPose = { id: string; joints: Vec3[] }; // 7 joints monde (j0..j6)
export type CollisionPair = {
  a: string; aSeg: number; b: string; bSeg: number; dist: number;
};

// Les 6 segments du bras (indices de joints consécutifs).
export const SEGMENTS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6],
];

// Paires de segments (capsules) en collision. Auto = segments NON adjacents
// d'un même robot ; inter = toutes paires entre robots différents.
export function collisionPairs(
  poses: RobotPose[], radii: number[], margin: number, selfExclude?: Set<string>,
): CollisionPair[] {
  const out: CollisionPair[] = [];
  for (let ri = 0; ri < poses.length; ri++) {
    for (let rj = ri; rj < poses.length; rj++) {
      const A = poses[ri], B = poses[rj];
      for (let si = 0; si < SEGMENTS.length; si++) {
        for (let sj = 0; sj < SEGMENTS.length; sj++) {
          if (ri === rj) {
            if (sj <= si) continue;             // une fois par paire
            if (Math.abs(si - sj) < 2) continue; // adjacents exclus
            if (selfExclude?.has(`${si}-${sj}`)) continue; // en contact au repos
          }
          const threshold = (radii[si] ?? 0) + (radii[sj] ?? 0) + margin;
          const d = segDist(
            A.joints[SEGMENTS[si][0]], A.joints[SEGMENTS[si][1]],
            B.joints[SEGMENTS[sj][0]], B.joints[SEGMENTS[sj][1]],
          );
          if (d < threshold) {
            out.push({ a: A.id, aSeg: si, b: B.id, bSeg: sj, dist: d });
          }
        }
      }
    }
  }
  return out;
}

// Paires de segments (non adjacents) déjà en contact à la pose de repos `joints`.
// Capsules épaisses dérivées du STL → certains segments proches le long du bras se
// chevauchent par construction : on les exclut pour ne flaguer que les VRAIS replis.
export function restContacts(joints: Vec3[], radii: number[], margin: number): Set<string> {
  const out = new Set<string>();
  for (let i = 0; i < SEGMENTS.length; i++) {
    for (let j = i + 2; j < SEGMENTS.length; j++) {
      const d = segDist(
        joints[SEGMENTS[i][0]], joints[SEGMENTS[i][1]],
        joints[SEGMENTS[j][0]], joints[SEGMENTS[j][1]],
      );
      if (d < (radii[i] ?? 0) + (radii[j] ?? 0) + margin) out.add(`${i}-${j}`);
    }
  }
  return out;
}

// Segments dont le bas dégage le sol à la pose de repos (les seuls qu'il est
// pertinent de surveiller : la base/épaule reposent près du sol par construction).
export function restGroundSegments(
  joints: Vec3[], radii: number[], zFloor: number, margin: number,
): number[] {
  const out: number[] = [];
  for (let s = 0; s < SEGMENTS.length; s++) {
    const bottom = Math.min(joints[SEGMENTS[s][0]][2], joints[SEGMENTS[s][1]][2]) - (radii[s] ?? 0);
    if (bottom >= zFloor + margin) out.push(s);
  }
  return out;
}

// Vrai si une capsule passe sous le plan de sol horizontal z = zFloor. `onlySegs`
// restreint le test aux segments qui dégagent le sol au repos (cf. restGroundSegments).
export function groundHit(
  joints: Vec3[], radii: number[], zFloor: number, margin: number, onlySegs?: number[],
): boolean {
  const segs = onlySegs ?? SEGMENTS.map((_, i) => i);
  for (const s of segs) {
    const za = joints[SEGMENTS[s][0]][2], zb = joints[SEGMENTS[s][1]][2];
    const bottom = Math.min(za, zb) - (radii[s] ?? 0);
    if (bottom < zFloor + margin) return true;
  }
  return false;
}

// Joints monde d'un robot via la cinématique calibration (STL) + décalage latéral
// du robot. Le miroir X (offsetX ± x) est validé visuellement en Task 6.
export function robotWorldJoints(
  ticks: Record<string, number>, offsetX: number, calib: CalibData,
): Vec3[] {
  return calibJoints(ticks, calib).map(([x, y, z]) => [offsetX + x, y, z] as Vec3);
}

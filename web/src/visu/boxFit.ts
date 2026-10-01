// Découpe d'une pièce STL (repère LOCAL de la pièce) en boîtes englobantes :
// AABB locale, tranchée le long du plus grand côté si la pièce est longue.
// Le repère local suit la pièce calibrée ⇒ les boîtes couvrent les déports
// (c'est l'idée des « rectangles d'encombrement » posés sur chaque pièce).
// Sur l'axe tranché, chaque boîte garde les bornes NOMINALES de sa tranche
// (couverture contiguë garantie même si les vertices sont clairsemés) ; sur
// les 2 autres axes, elle est serrée sur les vertices de la tranche.
import type { Vec3 } from "./fk";

export type LocalBox = { c: Vec3; half: Vec3 };

function bounds(verts: Vec3[]): { min: Vec3; max: Vec3 } {
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const v of verts) {
    for (let a = 0; a < 3; a++) {
      if (v[a] < min[a]) min[a] = v[a];
      if (v[a] > max[a]) max[a] = v[a];
    }
  }
  return { min, max };
}

export function fitBoxes(verts: Vec3[], slice: number, kMax = 4): LocalBox[] {
  if (verts.length === 0) return [];
  const { min, max } = bounds(verts);
  const ext: Vec3 = [max[0] - min[0], max[1] - min[1], max[2] - min[2]];
  const axis = ext.indexOf(Math.max(ext[0], ext[1], ext[2]));
  const n = Math.max(1, Math.min(kMax, Math.ceil(ext[axis] / slice)));
  const out: LocalBox[] = [];
  for (let i = 0; i < n; i++) {
    const lo = min[axis] + (i / n) * ext[axis];
    const hi = min[axis] + ((i + 1) / n) * ext[axis];
    const sel = verts.filter((v) => v[axis] >= lo - 1e-9 && v[axis] <= hi + 1e-9);
    if (sel.length === 0) continue;
    const sb = bounds(sel);
    const c: Vec3 = [0, 0, 0];
    const half: Vec3 = [0, 0, 0];
    for (let a = 0; a < 3; a++) {
      c[a] = (sb.min[a] + sb.max[a]) / 2;
      half[a] = (sb.max[a] - sb.min[a]) / 2;
    }
    // bornes nominales sur l'axe tranché : pas de trou entre tranches
    c[axis] = (lo + hi) / 2;
    half[axis] = (hi - lo) / 2;
    out.push({ c, half });
  }
  return out;
}

// Cinématique basée calibration : place les points d'axe du robot (et donc les
// capsules de collision) sur la géométrie du STL calibré, en répliquant la chaîne
// de pivots de RobotMeshSTL. Repère calibration (Z-up, base à z=0), SANS le
// groundOffset visuel. Spec : docs/superpowers/specs/2026-06-10-anticollision-stl-referentiel-design.md
import { Vector3, Quaternion, Euler } from "three";
import { jointAngle, type Vec3 } from "./fk";

const DEG = Math.PI / 180;

export type CalibAxis = { pos: number[]; rotDeg: number[] };
export type CalibPiece = {
  offset: number[]; rotDeg: number[]; axisLocal: number[] | null; joint: number | null;
};
export type CalibSegment = { a: number; b: number; r: number }; // indices points + rayon mm
export type CalibBox = {
  link: number;     // maillon (0=Base, 1=Shoulder, 2=UA, 3=Forearm, 4=Wrist, 5=tête/pince)
  c: number[];      // centre à la pose de repos (repère calibration)
  rotDeg: number[]; // orientation repos des axes de la boîte (= rotDeg de la pièce)
  half: number[];   // demi-dimensions (mm) le long des axes de la boîte
};
export type CalibData = {
  refSurfaceZ?: number;
  axes: Record<string, CalibAxis>;
  pieces: Record<string, CalibPiece>;
  segments?: CalibSegment[];
  boxes?: CalibBox[];
};

// Les 7 points d'axe, dans l'ordre racine→pince.
export const AXIS_LABELS = ["base", "1", "2·3", "4", "5", "6", "7"] as const;
// Pivots d'articulation (ordre racine→leaf) : label, axe ticks, signe (cf. RobotMeshSTL).
const PIVOTS: { label: string; axis: number; sign: number }[] = [
  { label: "1", axis: 1, sign: -1 },
  { label: "2·3", axis: 2, sign: +1 },
  { label: "4", axis: 4, sign: -1 },
  { label: "5", axis: 5, sign: +1 },
  { label: "6", axis: 6, sign: +1 },
];

function axisDir(a: CalibAxis): Vector3 {
  const e = a.rotDeg ?? [0, 0, 0];
  return new Vector3(1, 0, 0).applyEuler(new Euler(e[0]*DEG, e[1]*DEG, e[2]*DEG)).normalize();
}

// Position monde d'un point soumis au pivot L : c + R(dir, angle)·(p - c).
function applyPivot(p: Vector3, center: Vector3, dir: Vector3, angle: number): Vector3 {
  const q = new Quaternion().setFromAxisAngle(dir, angle);
  return p.clone().sub(center).applyQuaternion(q).add(center);
}

// Positions monde des 7 points d'axe à la pose `ticks`.
export function calibJoints(ticks: Record<string, number> | undefined, calib: CalibData): Vec3[] {
  return AXIS_LABELS.map((label, idx) => {
    let p = new Vector3(...(calib.axes[label]?.pos ?? [0, 0, 0]));
    // Pivots ENCLOSANT ce point = ceux d'indice < idx dans la chaîne, appliqués
    // du plus interne (proche du point) vers la racine.
    const enclosing = PIVOTS.slice(0, Math.max(0, idx - 1)); // base(0)&axe1(1) sans pivot parent
    for (let k = enclosing.length - 1; k >= 0; k--) {
      const pv = enclosing[k];
      const ax = calib.axes[pv.label];
      if (!ax) continue;
      const angle = pv.sign * jointAngle(ticks, pv.axis);
      p = applyPivot(p, new Vector3(...ax.pos), axisDir(ax), angle);
    }
    return [p.x, p.y, p.z] as Vec3;
  });
}

// Position monde d'un point attaché au maillon `link` (0=Base … 5=tête/pince),
// exprimé à la pose de repos dans le repère calibration. Pivots englobants
// appliqués du plus interne vers la racine, comme calibJoints.
export function transformLinkPoint(
  point: Vec3, link: number, ticks: Record<string, number> | undefined, calib: CalibData,
): Vec3 {
  let p = new Vector3(...point);
  for (let k = Math.min(link, PIVOTS.length) - 1; k >= 0; k--) {
    const pv = PIVOTS[k];
    const ax = calib.axes[pv.label];
    if (!ax) continue;
    p = applyPivot(p, new Vector3(...ax.pos), axisDir(ax), pv.sign * jointAngle(ticks, pv.axis));
  }
  return [p.x, p.y, p.z];
}

// Rotation cumulée des pivots englobant le maillon `link`, à appliquer aux
// DIRECTIONS attachées au maillon (les points passent par transformLinkPoint) :
// q = Q1·Q2·…·Qlink, de la racine vers le pivot le plus interne.
export function linkQuaternion(
  link: number, ticks: Record<string, number> | undefined, calib: CalibData,
): Quaternion {
  const q = new Quaternion();
  for (let k = 0; k < Math.min(link, PIVOTS.length); k++) {
    const pv = PIVOTS[k];
    const ax = calib.axes[pv.label];
    if (!ax) continue;
    q.multiply(new Quaternion().setFromAxisAngle(axisDir(ax), pv.sign * jointAngle(ticks, pv.axis)));
  }
  return q;
}

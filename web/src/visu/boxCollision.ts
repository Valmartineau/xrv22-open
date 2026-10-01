// Moteur de collision par boîtes d'encombrement (OBB) — module pur, sans React.
// Remplace les capsules : chaque pièce STL porte des boîtes posées dans son
// repère local (semées hors-ligne par scripts/gen-collision-boxes.ts), qui
// suivent la pièce — déports compris. Auto-collision = maillons NON adjacents
// d'un même robot ; inter-robots = toutes paires ; sol = point bas sous le plan.
// Test d'intersection : SAT à 15 axes (Ericson, RTCD §4.4).
import { Vector3, Quaternion, Euler } from "three";
import { REF_UP, type Vec3 } from "./fk";
import { transformLinkPoint, linkQuaternion, type CalibData } from "./calibKinematics";

const DEG = Math.PI / 180;
const EPS = 1e-9;

export type WorldBox = {
  link: number;
  c: Vec3;
  axes: [Vec3, Vec3, Vec3];            // axes monde unitaires de la boîte
  half: Vec3;                          // demi-dimensions (mm) le long des axes
  q: [number, number, number, number]; // orientation monde (pour l'affichage debug)
};
export type BoxPose = { id: string; boxes: WorldBox[] };
export type BoxHit = { a: string; ai: number; b: string; bi: number };

// Boîtes monde d'un robot à la pose `ticks` (+ décalage latéral du robot).
// L'ordre du tableau est stable (= calibration.json) : les indices servent de
// clés d'exclusion ("i-j", i<j) entre restBoxContacts et boxCollisionPairs.
export function worldBoxes(
  ticks: Record<string, number> | undefined, offsetX: number, calib: CalibData,
): WorldBox[] {
  return (calib.boxes ?? []).map((b) => {
    const [x, y, z] = transformLinkPoint(b.c as Vec3, b.link, ticks, calib);
    const rest = new Quaternion().setFromEuler(
      new Euler(b.rotDeg[0] * DEG, b.rotDeg[1] * DEG, b.rotDeg[2] * DEG));
    const q = linkQuaternion(b.link, ticks, calib).multiply(rest);
    const ax = (vx: number, vy: number, vz: number): Vec3 => {
      const w = new Vector3(vx, vy, vz).applyQuaternion(q);
      return [w.x, w.y, w.z];
    };
    return {
      link: b.link,
      c: [offsetX + x, y, z] as Vec3,
      axes: [ax(1, 0, 0), ax(0, 1, 0), ax(0, 0, 1)] as [Vec3, Vec3, Vec3],
      half: [b.half[0], b.half[1], b.half[2]] as Vec3,
      q: [q.x, q.y, q.z, q.w],
    };
  });
}

function dot(a: Vec3, b: Vec3): number { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }

// Test d'intersection OBB-OBB par axes séparateurs (3 faces de A, 3 de B,
// 9 produits vectoriels). `margin` gonfle chaque boîte de margin/2 par face.
export function obbIntersect(A: WorldBox, B: WorldBox, margin: number): boolean {
  const m = margin / 2;
  const aH = [A.half[0] + m, A.half[1] + m, A.half[2] + m];
  const bH = [B.half[0] + m, B.half[1] + m, B.half[2] + m];
  const R: number[][] = [[0,0,0],[0,0,0],[0,0,0]];
  const AbsR: number[][] = [[0,0,0],[0,0,0],[0,0,0]];
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) {
      R[i][j] = dot(A.axes[i], B.axes[j]);
      AbsR[i][j] = Math.abs(R[i][j]) + EPS; // EPS : robustesse axes ~parallèles
    }
  }
  const tw: Vec3 = [B.c[0] - A.c[0], B.c[1] - A.c[1], B.c[2] - A.c[2]];
  const t = [dot(tw, A.axes[0]), dot(tw, A.axes[1]), dot(tw, A.axes[2])];
  // axes de face de A
  for (let i = 0; i < 3; i++) {
    if (Math.abs(t[i]) > aH[i] + bH[0]*AbsR[i][0] + bH[1]*AbsR[i][1] + bH[2]*AbsR[i][2]) return false;
  }
  // axes de face de B
  for (let j = 0; j < 3; j++) {
    if (Math.abs(t[0]*R[0][j] + t[1]*R[1][j] + t[2]*R[2][j]) >
        bH[j] + aH[0]*AbsR[0][j] + aH[1]*AbsR[1][j] + aH[2]*AbsR[2][j]) return false;
  }
  // axes croisés L = Ai × Bj
  for (let i = 0; i < 3; i++) {
    const i1 = (i + 1) % 3, i2 = (i + 2) % 3;
    for (let j = 0; j < 3; j++) {
      const j1 = (j + 1) % 3, j2 = (j + 2) % 3;
      const lhs = Math.abs(t[i2]*R[i1][j] - t[i1]*R[i2][j]);
      const rhs = aH[i1]*AbsR[i2][j] + aH[i2]*AbsR[i1][j]
                + bH[j1]*AbsR[i][j2] + bH[j2]*AbsR[i][j1];
      if (lhs > rhs) return false;
    }
  }
  return true;
}

// Paires de boîtes en collision. Auto = TOUTES les paires d'un même robot,
// maillons adjacents compris, hors paires structurelles `selfExclude` (cf.
// sweepContacts) ; inter = toutes paires entre robots différents. Les paires
// d'un même maillon ont une pose relative constante : jamais en contact si
// elles ne le sont pas au repos (donc inoffensives à tester).
export function boxCollisionPairs(
  poses: BoxPose[], margin: number, selfExclude?: Set<string>,
): BoxHit[] {
  const out: BoxHit[] = [];
  for (let ri = 0; ri < poses.length; ri++) {
    for (let rj = ri; rj < poses.length; rj++) {
      const A = poses[ri], B = poses[rj];
      for (let bi = 0; bi < A.boxes.length; bi++) {
        for (let bj = ri === rj ? bi + 1 : 0; bj < B.boxes.length; bj++) {
          if (ri === rj && selfExclude?.has(`${bi}-${bj}`)) continue; // structurel
          if (obbIntersect(A.boxes[bi], B.boxes[bj], margin)) {
            out.push({ a: A.id, ai: bi, b: B.id, bi: bj });
          }
        }
      }
    }
  }
  return out;
}

// Paires de boîtes déjà en contact à la pose donnée (clés "i-j", i<j).
export function restBoxContacts(boxes: WorldBox[], margin: number): Set<string> {
  const out = new Set<string>();
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      if (obbIntersect(boxes[i], boxes[j], margin)) out.add(`${i}-${j}`);
    }
  }
  return out;
}

// Paires STRUCTURELLES à exclure du garde-fou : celles qui entrent en contact
// quelque part dans l'enveloppe de mouvement normale — chaque axe balayé SEUL
// de ±sweepDeg autour du repos. La pose relative de deux maillons voisins ne
// dépend que de leur articulation commune : ce balayage caractérise donc
// exactement leurs frottements près de l'axe (ex. poignet ±10°), tout en
// gardant les VRAIS replis (au-delà de sweepDeg : repli du poignet à ~±90°).
export function sweepContacts(
  calib: CalibData, margin: number, sweepDeg = 70, stepDeg = 5,
): Set<string> {
  const AXES = [1, 2, 4, 5, 6];
  const ref: Record<string, number> = {};
  for (const ax of AXES) ref[String(ax)] = REF_UP[ax];
  const out = new Set<string>();
  const add = (t: Record<string, number>) => {
    for (const k of restBoxContacts(worldBoxes(t, 0, calib), margin)) out.add(k);
  };
  add(ref);
  for (const ax of AXES) {
    for (let a = stepDeg; a <= sweepDeg; a += stepDeg) {
      for (const dir of [1, -1]) {
        add({ ...ref, [String(ax)]: REF_UP[ax] + Math.round(dir * a * 4096 / 360) });
      }
    }
  }
  return out;
}

// Point le plus bas d'une boîte : centre moins la projection des demi-côtés sur Z.
function boxBottom(b: WorldBox): number {
  return b.c[2] - (b.half[0]*Math.abs(b.axes[0][2])
                 + b.half[1]*Math.abs(b.axes[1][2])
                 + b.half[2]*Math.abs(b.axes[2][2]));
}

// Indices des boîtes qui dégagent le sol à la pose de repos (les seules qu'il
// est pertinent de surveiller : la base repose au plancher par construction).
export function restGroundBoxes(
  boxes: WorldBox[], zFloor: number, margin: number,
): number[] {
  const out: number[] = [];
  for (let i = 0; i < boxes.length; i++) {
    if (boxBottom(boxes[i]) >= zFloor + margin) out.push(i);
  }
  return out;
}

// Vrai si une boîte passe sous le plan de sol horizontal z = zFloor. `onlyIdx`
// restreint le test aux boîtes qui dégagent le sol au repos.
export function boxGroundHit(
  boxes: WorldBox[], zFloor: number, margin: number, onlyIdx?: number[],
): boolean {
  const idx = onlyIdx ?? boxes.map((_, i) => i);
  for (const i of idx) {
    if (boxBottom(boxes[i]) < zFloor + margin) return true;
  }
  return false;
}

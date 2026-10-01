// Offline (lancé une fois ; le mesh ne change jamais) : lit les 9 STL + la
// calibration, calcule un rayon de capsule par segment à la pose de référence
// (ossature verticale → rayon = distance radiale des vertices, percentile 99),
// et écrit le champ `segments` dans public/calibration.json.
//   Lancement : cd web && npx tsx scripts/gen-capsule-radii.ts
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Vector3, Euler } from "three";
import { radialRadius } from "../src/visu/capsuleRadius.js";
import { PARTS } from "../src/calibrate/parts.js";

const DEG = Math.PI / 180;
const HERE = resolve(import.meta.dirname, "..");
const CALIB = resolve(HERE, "public/calibration.json");
const PCT = 0.99;

type Vec3 = [number, number, number];
const calib = JSON.parse(readFileSync(CALIB, "utf8"));

// Z des 7 points d'axe (ordre base,1,2·3,4,5,6,7) → bornes des 6 segments.
const labels = ["base", "1", "2·3", "4", "5", "6", "7"];
const zAxis = labels.map((l) => (calib.axes[l]?.pos?.[2] ?? 0) as number);
const SEGMENTS: [number, number][] = [[0,1],[1,2],[2,3],[3,4],[4,5],[5,6]];

// Placement statique d'une pièce à la pose de référence (pivots = identité) :
//   v_world = offset + axisLocal + R(rotDeg)·(v - axisLocal)
function staticVerts(name: string): Vec3[] {
  const url = PARTS.find((p) => p.name === name.split("#")[0])?.url;
  if (!url) return [];
  const buf = readFileSync(resolve(HERE, "public", url.replace(/^\//, "")));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  const geom = new STLLoader().parse(ab as ArrayBuffer);
  const pos = geom.getAttribute("position");
  const piece = calib.pieces[name];
  if (!piece) return [];
  const off = new Vector3(...piece.offset);
  const piv = new Vector3(...(piece.axisLocal ?? [0, 0, 0]));
  const rot = new Euler(piece.rotDeg[0]*DEG, piece.rotDeg[1]*DEG, piece.rotDeg[2]*DEG);
  const out: Vec3[] = [];
  const v = new Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).sub(piv).applyEuler(rot).add(piv).add(off);
    out.push([v.x, v.y, v.z]);
  }
  return out;
}

// Tous les vertices monde (toutes pièces de la calibration).
const allVerts: Vec3[] = Object.keys(calib.pieces).flatMap(staticVerts);
console.log(`Vertices placés : ${allVerts.length}`);

// Rayon = enveloppe (percentile) des vertices dans la tranche de hauteur du
// segment. Les bouts qui dépassent les points d'axe (socle sous z=0, doigts
// au-delà du TCP) sont couverts par les HÉMISPHÈRES de rayon r aux extrémités
// de la capsule — pas besoin d'étendre les tranches.
const segments = SEGMENTS.map(([a, b]) => {
  const r = radialRadius(allVerts, zAxis[a], zAxis[b], PCT);
  const rr = Math.round(r * 10) / 10;
  console.log(`  segment ${a}→${b}  (z ${zAxis[a]}..${zAxis[b]})  rayon=${rr} mm`);
  return { a, b, r: rr };
});

calib.segments = segments;
writeFileSync(CALIB, JSON.stringify(calib, null, 2) + "\n");
console.log(`Écrit segments dans ${CALIB}`);

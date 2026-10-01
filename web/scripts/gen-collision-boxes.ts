// Offline (lancé une fois ; le mesh ne change jamais) : lit les 9 STL + la
// calibration, pose des boîtes d'encombrement sur CHAQUE PIÈCE dans son repère
// LOCAL (AABB tranchée le long du grand côté), les exprime à la pose de repos
//   c_rest = off + piv + R(rotDeg)·(c_local − piv),  orientation = rotDeg
// et écrit le champ `boxes` dans public/calibration.json. Contrairement aux
// capsules (rayon radial à l'axe Z, faux pour les pièces en déport), les
// boîtes suivent chaque pièce — déports compris.
//   Lancement : cd web && npx tsx scripts/gen-collision-boxes.ts
//   Retouche fine : le champ `boxes` du JSON est éditable à la main (mm).
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Vector3, Euler } from "three";
import { fitBoxes } from "../src/visu/boxFit.js";
import { PARTS } from "../src/calibrate/parts.js";

const DEG = Math.PI / 180;
const HERE = resolve(import.meta.dirname, "..");
const CALIB = resolve(HERE, "public/calibration.json");
const SLICE = 80;           // mm — ~1 boîte par tranche de 80 mm du grand côté
const GRIP_SLIDE_MM = 22.5; // demi-écartement max des doigts (cf. RobotMeshSTL)

// Maillon cinématique de chaque pièce (0=Base … 5=tête/pince), cf. l'imbrication
// des Pivot dans RobotMeshSTL.
const LINK_OF: Record<string, number> = {
  Base: 0, Shoulder: 1, UA: 2, Forearm: 3, Wrist: 4,
  Gripper: 5, "Gripper-Prop": 5, "Gripper-Bar": 5, Finger: 5, "Finger#2": 5,
};

type Vec3 = [number, number, number];
const calib = JSON.parse(readFileSync(CALIB, "utf8"));

// Vertices BRUTS d'une pièce (repère local STL, aucun placement).
function localVerts(name: string): Vec3[] {
  const url = PARTS.find((p) => p.name === name.split("#")[0])?.url;
  if (!url) return [];
  const buf = readFileSync(resolve(HERE, "public", url.replace(/^\//, "")));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  const geom = new STLLoader().parse(ab as ArrayBuffer);
  const pos = geom.getAttribute("position");
  const out: Vec3[] = [];
  for (let i = 0; i < pos.count; i++) out.push([pos.getX(i), pos.getY(i), pos.getZ(i)]);
  return out;
}

const round1 = (v: number) => Math.round(v * 10) / 10;
const boxes: { link: number; c: number[]; rotDeg: number[]; half: number[] }[] = [];

for (const name of Object.keys(calib.pieces)) {
  const link = LINK_OF[name];
  if (link === undefined) continue;
  const piece = calib.pieces[name];
  const verts = localVerts(name);
  if (verts.length === 0) continue;
  const local = fitBoxes(verts, SLICE);
  // Doigts : la translation d'ouverture n'est pas suivie au runtime — on émet
  // une série de boîtes par position extrême (fermée ET ouverte).
  const slides = name === "Finger" ? [0, -GRIP_SLIDE_MM]
    : name === "Finger#2" ? [0, GRIP_SLIDE_MM] : [0];
  const piv = new Vector3(...(piece.axisLocal ?? [0, 0, 0]));
  const rot = new Euler(piece.rotDeg[0] * DEG, piece.rotDeg[1] * DEG, piece.rotDeg[2] * DEG);
  for (const slideX of slides) {
    const off = new Vector3(piece.offset[0] + slideX, piece.offset[1], piece.offset[2]);
    for (const b of local) {
      const c = new Vector3(...b.c).sub(piv).applyEuler(rot).add(piv).add(off);
      boxes.push({
        link,
        c: [round1(c.x), round1(c.y), round1(c.z)],
        rotDeg: [...piece.rotDeg],
        half: [round1(b.half[0]), round1(b.half[1]), round1(b.half[2])],
      });
    }
  }
  console.log(`  ${name} (maillon ${link}) : ${verts.length} verts → ` +
    `${local.length * slides.length} boîte(s), half=${local.map((b) =>
      b.half.map(round1).join("×")).join(" / ")}`);
}

calib.boxes = boxes;
writeFileSync(CALIB, JSON.stringify(calib, null, 2) + "\n");
console.log(`Écrit ${boxes.length} boîtes dans ${CALIB}`);

// Exporte les résultats du moteur de collision TypeScript (référence) pour un
// jeu de poses → tests/fixtures/box_collision_parity.json. Le port Python
// (xrv22/core/box_collision.py) doit produire EXACTEMENT les mêmes boîtes
// monde, exclusions et hits : c'est le test de parité dorée.
//   Lancement : cd web && npx tsx scripts/gen-parity-fixture.ts
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import {
  worldBoxes, boxCollisionPairs, sweepContacts, restGroundBoxes, boxGroundHit,
} from "../src/visu/boxCollision.js";
import { REF_UP } from "../src/visu/fk.js";

const HERE = resolve(import.meta.dirname, "..");
const CALIB = resolve(HERE, "public/calibration.json");
const OUT = resolve(HERE, "../tests/fixtures/box_collision_parity.json");
const MARGIN = 10;

const calib = JSON.parse(readFileSync(CALIB, "utf8"));
const ref: Record<string, number> = {
  "1": REF_UP[1], "2": REF_UP[2], "4": REF_UP[4], "5": REF_UP[5], "6": REF_UP[6],
};
const t = (d: Record<string, number>) => ({ ...ref, ...d });
const POSES: Record<string, Record<string, number>> = {
  rest: ref,
  open: { "1": 2048, "2": 2048, "4": 2048, "5": 2048, "6": 2048 },
  elbow90: t({ "4": REF_UP[4] + 1024 }),
  wristm95: t({ "5": REF_UP[5] - 1081 }),
  shoulderm90: t({ "2": REF_UP[2] - 1024 }),
  combo: t({
    "1": REF_UP[1] + 400, "2": REF_UP[2] - 700, "4": REF_UP[4] + 800,
    "5": REF_UP[5] - 500, "6": REF_UP[6] + 300,
  }),
};

const excl = sweepContacts(calib, MARGIN);
const zF = calib.refSurfaceZ ?? 0;
const rest = worldBoxes(ref, 0, calib);
const groundIdx = restGroundBoxes(rest, zF, MARGIN);

const bottom = (b: { c: number[]; axes: number[][]; half: number[] }) =>
  b.c[2] - (b.half[0] * Math.abs(b.axes[0][2]) + b.half[1] * Math.abs(b.axes[1][2])
          + b.half[2] * Math.abs(b.axes[2][2]));

const poses: Record<string, unknown> = {};
for (const [name, ticks] of Object.entries(POSES)) {
  const boxes = worldBoxes(ticks, 0, calib);
  poses[name] = {
    ticks,
    boxes: boxes.map((b) => ({
      link: b.link, c: b.c, axes: b.axes, half: b.half, bottom: bottom(b),
    })),
    hits: boxCollisionPairs([{ id: "1", boxes }], MARGIN, excl).map((h) => [h.ai, h.bi]),
    groundHit: boxGroundHit(boxes, zF, MARGIN, groundIdx),
  };
}

mkdirSync(resolve(HERE, "../tests/fixtures"), { recursive: true });
writeFileSync(OUT, JSON.stringify({
  margin: MARGIN,
  refSurfaceZ: zF,
  refUp: REF_UP,
  exclusions: [...excl].sort(),
  groundIdx,
  nBoxes: (calib.boxes ?? []).length,
  poses,
}, null, 1) + "\n");
console.log(`Fixture écrite : ${OUT} (${(calib.boxes ?? []).length} boîtes, ${Object.keys(POSES).length} poses, ${excl.size} exclusions)`);

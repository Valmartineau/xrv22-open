import { describe, it, expect } from "vitest";
import {
  worldBoxes, obbIntersect, boxCollisionPairs, restBoxContacts, restGroundBoxes,
  boxGroundHit, sweepContacts, type BoxPose, type WorldBox,
} from "./boxCollision";
import type { CalibData } from "./calibKinematics";
import { REF_UP } from "./fk";

const ID_AXES: [Vec3, Vec3, Vec3] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
type Vec3 = [number, number, number];
const SQ2 = Math.SQRT1_2;
// boîte tournée de 45° autour de Z
const ROT45_AXES: [Vec3, Vec3, Vec3] = [[SQ2, SQ2, 0], [-SQ2, SQ2, 0], [0, 0, 1]];

function box(c: Vec3, half: Vec3, link = 0, axes = ID_AXES): WorldBox {
  return { link, c, axes, half, q: [0, 0, 0, 1] };
}

describe("obbIntersect", () => {
  it("axe-aligné : séparé / chevauchant", () => {
    const A = box([0, 0, 0], [1, 1, 1]);
    expect(obbIntersect(A, box([3, 0, 0], [1, 1, 1]), 0)).toBe(false);
    expect(obbIntersect(A, box([1.9, 0, 0], [1, 1, 1]), 0)).toBe(true);
  });

  it("la marge gonfle chaque boîte de margin/2", () => {
    const A = box([0, 0, 0], [1, 1, 1]);
    const B = box([2.2, 0, 0], [1, 1, 1]);
    expect(obbIntersect(A, B, 0)).toBe(false);   // 2.2 > 2
    expect(obbIntersect(A, B, 0.5)).toBe(true);  // 2.2 < 2.5
  });

  it("boîte tournée à 45° : projection √2 sur l'axe de A", () => {
    const A = box([0, 0, 0], [1, 1, 1]);
    expect(obbIntersect(A, box([2.2, 0, 0], [1, 1, 1], 0, ROT45_AXES), 0)).toBe(true);  // 2.2 < 1+√2
    expect(obbIntersect(A, box([2.6, 0, 0], [1, 1, 1], 0, ROT45_AXES), 0)).toBe(false); // 2.6 > 1+√2
  });

  it("séparation uniquement par un axe de face de B (cas diagonal)", () => {
    // A axe-aligné, B à 45° en diagonale : les axes de A ne séparent pas
    // (|t|=1.9 < 1+√2) mais l'axe (1,1)/√2 de B sépare (2.687 > 1.414+1).
    const A = box([0, 0, 0], [1, 1, 1]);
    const B = box([1.9, 1.9, 0], [1, 1, 1], 0, ROT45_AXES);
    expect(obbIntersect(A, B, 0)).toBe(false);
  });
});

describe("boxCollisionPairs", () => {
  it("auto : maillons non adjacents qui se chevauchent → hit", () => {
    const pose: BoxPose = { id: "1", boxes: [box([0, 0, 0], [50, 50, 50], 0), box([60, 0, 0], [50, 50, 50], 2)] };
    const hits = boxCollisionPairs([pose], 0);
    expect(hits.length).toBe(1);
    expect(hits[0].a).toBe("1");
    expect(hits[0].b).toBe("1");
  });

  it("auto : maillons adjacents testés aussi (sauf exclusion structurelle)", () => {
    const pose: BoxPose = { id: "1", boxes: [box([0, 0, 0], [50, 50, 50], 2), box([10, 0, 0], [50, 50, 50], 3)] };
    expect(boxCollisionPairs([pose], 0).length).toBe(1);
    expect(boxCollisionPairs([pose], 0, new Set(["0-1"])).length).toBe(0);
  });

  it("auto : paire exclue (contact au repos) → pas de hit", () => {
    const pose: BoxPose = { id: "1", boxes: [box([0, 0, 0], [50, 50, 50], 0), box([60, 0, 0], [50, 50, 50], 2)] };
    expect(boxCollisionPairs([pose], 0, new Set(["0-1"])).length).toBe(0);
  });

  it("inter-robots : toutes paires, même maillon identique", () => {
    const a: BoxPose = { id: "1", boxes: [box([0, 0, 0], [50, 50, 50], 3)] };
    const b: BoxPose = { id: "2", boxes: [box([80, 0, 0], [50, 50, 50], 3)] };
    const hits = boxCollisionPairs([a, b], 0);
    expect(hits.length).toBe(1);
    expect(hits[0].a).toBe("1");
    expect(hits[0].b).toBe("2");
  });
});

describe("sol", () => {
  it("boxGroundHit : point bas sous le plan → hit ; onlyIdx restreint", () => {
    const boxes = [box([0, 0, 100], [10, 10, 50], 2), box([0, 0, 40], [10, 10, 50], 3)];
    expect(boxGroundHit(boxes, 0, 0)).toBe(true);        // 40-50 < 0
    expect(boxGroundHit(boxes, 0, 0, [0])).toBe(false);  // restreint à la 1re
  });

  it("boxGroundHit : le point bas tient compte de l'orientation", () => {
    // demi-hauteur 10 mais boîte penchée à 45° : descente = (10+10)·√2/2 ≈ 14.1
    const b = box([0, 0, 13], [10, 10, 0.1], 0, ROT45_AXES);
    expect(boxGroundHit([b], 0, 0)).toBe(false); // axes tournés autour de Z : z inchangé
    const tiltX: [Vec3, Vec3, Vec3] = [[1, 0, 0], [0, SQ2, SQ2], [0, -SQ2, SQ2]];
    const b2 = box([0, 0, 13], [10, 10, 10], 0, tiltX);
    expect(boxGroundHit([b2], 0, 0)).toBe(true); // descente √2·10 ≈ 14.1 > 13
  });

  it("restGroundBoxes : seules les boîtes qui dégagent le sol au repos", () => {
    const boxes = [box([0, 0, 30], [10, 10, 50], 0), box([0, 0, 200], [10, 10, 50], 2)];
    expect(restGroundBoxes(boxes, 0, 10)).toEqual([1]);
  });

  it("restBoxContacts : paires en contact à la pose donnée (adjacents compris)", () => {
    const boxes = [
      box([0, 0, 0], [50, 50, 50], 0),
      box([60, 0, 0], [50, 50, 50], 1),
      box([300, 0, 0], [50, 50, 50], 4),
    ];
    const ex = restBoxContacts(boxes, 0);
    expect(ex.has("0-1")).toBe(true);
    expect(ex.has("0-2")).toBe(false);
  });
});

describe("worldBoxes", () => {
  // Même fixture que calibKinematics.test.ts, réduite aux axes utiles.
  const CAL: CalibData = {
    axes: {
      base: { pos: [0, 0, 0], rotDeg: [0, 0, 0] },
      "1":  { pos: [0, 0, 15.5], rotDeg: [0, 0, 0] },
      "2·3": { pos: [0, 0, 54], rotDeg: [90, 0, 0] },
      "4":  { pos: [0, 0, 260], rotDeg: [90, 0, 0] },
      "5":  { pos: [0, 0, 459.5], rotDeg: [90, 0, 0] },
      "6":  { pos: [0, 0, 527], rotDeg: [0, 0, 0] },
      "7":  { pos: [0, 0, 572.5], rotDeg: [0, 0, 0] },
    },
    pieces: {},
    boxes: [{ link: 3, c: [0, 50, 260], rotDeg: [0, 0, 0], half: [10, 20, 30] }],
  };
  const refTicks = { "1": REF_UP[1], "2": REF_UP[2], "4": REF_UP[4], "5": REF_UP[5], "6": REF_UP[6] };

  it("pose de repos : centre + offsetX, axes identité", () => {
    const b = worldBoxes(refTicks, 350, CAL);
    expect(b.length).toBe(1);
    expect(b[0].c).toEqual([350, 50, 260]);
    expect(b[0].half).toEqual([10, 20, 30]);
    expect(b[0].axes[1][1]).toBeCloseTo(1, 6);
    expect(b[0].link).toBe(3);
  });

  it("coude à 90° : centre et axes suivent le maillon", () => {
    const b = worldBoxes({ ...refTicks, "4": REF_UP[4] + 1024 }, 0, CAL)[0];
    expect(b.c[0]).toBeCloseTo(0, 3);
    expect(b.c[1]).toBeCloseTo(0, 3);
    expect(b.c[2]).toBeCloseTo(210, 3);   // cf. transformLinkPoint
    // axe Y de la boîte : Rx(-90°)·Y = -Z
    expect(b.axes[1][1]).toBeCloseTo(0, 6);
    expect(b.axes[1][2]).toBeCloseTo(-1, 6);
  });

  describe("sweepContacts", () => {
    // Boîte qui tourne avec le coude (rel. au pivot [0,0,260] : rayon 50) + deux
    // boîtes fixes posées sur sa trajectoire : l'une atteinte à -30° (enveloppe
    // normale), l'autre à -100° (vrai repli, au-delà du balayage ±70°).
    const CAL2: CalibData = {
      axes: CAL.axes,
      pieces: {},
      boxes: [
        { link: 3, c: [0, 50, 260], rotDeg: [0, 0, 0], half: [5, 5, 5] },
        { link: 0, c: [0, 43.3, 235], rotDeg: [0, 0, 0], half: [5, 5, 5] },    // à -30°
        { link: 0, c: [0, -8.7, 210.8], rotDeg: [0, 0, 0], half: [5, 5, 5] },  // à -100°
      ],
    };
    it("exclut les contacts de l'enveloppe normale (±70°), garde les replis lointains", () => {
      const ex = sweepContacts(CAL2, 0);
      expect(ex.has("0-1")).toBe(true);   // frottement structurel → exclu
      expect(ex.has("0-2")).toBe(false);  // repli au-delà du balayage → surveillé
    });
  });
});

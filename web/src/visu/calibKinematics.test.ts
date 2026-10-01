import { describe, it, expect } from "vitest";
import { Vector3 } from "three";
import { calibJoints, transformLinkPoint, linkQuaternion, type CalibData } from "./calibKinematics";
import { REF_UP } from "./fk";

// Calibration minimale : axes alignés sur Z (comme le vrai calibration.json à la
// pose de référence). rotDeg des axes = 0 → dir = X (peu importe ici).
const CAL: CalibData = {
  refSurfaceZ: -50,
  axes: {
    base: { pos: [0, 0, 0], rotDeg: [0, 0, 0] },
    "1":  { pos: [0, 0, 15.5], rotDeg: [0, 0, 0] },
    "2·3":{ pos: [0, 0, 54], rotDeg: [90, 0, 0] }, // axe horizontal (épaule)
    "4":  { pos: [0, 0, 260], rotDeg: [90, 0, 0] },
    "5":  { pos: [0, 0, 459.5], rotDeg: [90, 0, 0] },
    "6":  { pos: [0, 0, 527], rotDeg: [0, 0, 0] },
    "7":  { pos: [0, 0, 572.5], rotDeg: [0, 0, 0] },
  },
  pieces: {},
};
// ticks REF_UP convertis : REF_UP donne angle 0 sur chaque axe.
const refTicks: Record<string, number> = {
  "1": REF_UP[1], "2": REF_UP[2], "4": REF_UP[4], "5": REF_UP[5], "6": REF_UP[6],
};

describe("calibJoints", () => {
  it("pose de référence → points d'axe = positions calibrées (Z croissant)", () => {
    const j = calibJoints(refTicks, CAL);
    expect(j.length).toBe(7);
    expect(j[0]).toEqual([0, 0, 0]);          // base
    expect(j[3][2]).toBeCloseTo(260, 3);      // axe 4 (coude) sur Z
    expect(j[6][2]).toBeCloseTo(572.5, 3);    // axe 7 (TCP) sur Z
    // tous sur l'axe vertical (x=y=0) à la pose de référence
    for (const p of j) { expect(p[0]).toBeCloseTo(0, 6); expect(p[1]).toBeCloseTo(0, 6); }
  });

  it("rotation de l'épaule : les points aval restent rigides (distance au pivot conservée)", () => {
    const c2 = CAL.axes["2·3"].pos; // centre du pivot épaule
    const before = calibJoints(refTicks, CAL)[4]; // axe 5 (poignet)
    const dBefore = Math.hypot(before[0]-c2[0], before[1]-c2[1], before[2]-c2[2]);
    // bouge l'épaule de ~512 ticks (~45°)
    const after = calibJoints({ ...refTicks, "2": REF_UP[2] + 512 }, CAL)[4];
    const dAfter = Math.hypot(after[0]-c2[0], after[1]-c2[1], after[2]-c2[2]);
    expect(dAfter).toBeCloseTo(dBefore, 3);   // rotation rigide
    expect(after[2]).not.toBeCloseTo(before[2], 1); // le poignet a bougé en Z
  });
});

describe("transformLinkPoint", () => {
  it("pose de référence → identité", () => {
    const p = transformLinkPoint([12, 34, 56], 3, refTicks, CAL);
    expect(p[0]).toBeCloseTo(12, 6);
    expect(p[1]).toBeCloseTo(34, 6);
    expect(p[2]).toBeCloseTo(56, 6);
  });

  it("le maillon 0 (Base) ne bouge jamais", () => {
    const p = transformLinkPoint([10, 0, 0], 0, { ...refTicks, "1": REF_UP[1] + 1024 }, CAL);
    expect(p).toEqual([10, 0, 0]);
  });

  it("coude à 90° : un point du maillon 3 tourne autour de l'axe 4", () => {
    // axe 4 : centre [0,0,260], dir +X (rotDeg [90,0,0] laisse X invariant).
    // tick +1024 = +90°, signe du pivot 4 = -1 → angle -90°.
    // [0,50,260] - centre = [0,50,0] → Rx(-90°) → [0,0,-50] → monde [0,0,210].
    const p = transformLinkPoint([0, 50, 260], 3, { ...refTicks, "4": REF_UP[4] + 1024 }, CAL);
    expect(p[0]).toBeCloseTo(0, 3);
    expect(p[1]).toBeCloseTo(0, 3);
    expect(p[2]).toBeCloseTo(210, 3);
  });
});

describe("linkQuaternion", () => {
  it("pose de référence → identité", () => {
    const q = linkQuaternion(5, refTicks, CAL);
    const v = new Vector3(0, 1, 0).applyQuaternion(q);
    expect(v.y).toBeCloseTo(1, 6);
  });

  it("coude à 90° : les directions du maillon 3 tournent comme les points", () => {
    const q = linkQuaternion(3, { ...refTicks, "4": REF_UP[4] + 1024 }, CAL);
    const v = new Vector3(0, 1, 0).applyQuaternion(q); // Rx(-90°)·Y = -Z
    expect(v.x).toBeCloseTo(0, 6);
    expect(v.y).toBeCloseTo(0, 6);
    expect(v.z).toBeCloseTo(-1, 6);
  });
});

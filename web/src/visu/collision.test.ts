import { describe, it, expect } from "vitest";
import { segDist, collisionPairs, groundHit, restContacts, restGroundSegments, type RobotPose } from "./collision";
import type { Vec3 } from "./fk";

describe("segDist", () => {
  it("segments parallèles décalés → distance = écart", () => {
    const d = segDist([0, 0, 0], [1, 0, 0], [0, 0, 2], [1, 0, 2]);
    expect(d).toBeCloseTo(2, 6);
  });
  it("segments qui se croisent → 0", () => {
    const d = segDist([0, 0, 0], [2, 0, 0], [1, -1, 0], [1, 1, 0]);
    expect(d).toBeCloseTo(0, 6);
  });
  it("colinéaires disjoints → distance entre extrémités", () => {
    const d = segDist([0, 0, 0], [1, 0, 0], [3, 0, 0], [4, 0, 0]);
    expect(d).toBeCloseTo(2, 6);
  });
  it("point vs point (segments dégénérés)", () => {
    const a: Vec3 = [0, 0, 0];
    const b: Vec3 = [0, 3, 4];
    expect(segDist(a, a, b, b)).toBeCloseTo(5, 6);
  });
});

describe("collisionPairs", () => {
  const R6 = [35, 35, 35, 35, 35, 35]; // un rayon par segment
  const straight = (id: string): RobotPose => ({
    id,
    joints: [0, 1, 2, 3, 4, 5, 6].map((i) => [i * 100, 0, 0] as [number, number, number]),
  });

  it("robot étalé → aucune auto-collision", () => {
    expect(collisionPairs([straight("r1")], R6, 10)).toEqual([]);
  });

  it("auto-collision : poignet replié sur la base", () => {
    const r = straight("r1");
    r.joints[5] = [50, 0, 10];
    r.joints[6] = [50, 0, -10];
    const hits = collisionPairs([r], R6, 10);
    expect(hits.some((h) => h.aSeg === 0 && h.bSeg === 5)).toBe(true);
  });

  it("inter-robots : deux robots trop proches", () => {
    const a = straight("r1");
    const b = straight("r2");
    b.joints = b.joints.map(([x, , z]) => [x, 20, z]);
    const hits = collisionPairs([a, b], R6, 10);
    expect(hits.some((h) => h.a === "r1" && h.b === "r2")).toBe(true);
  });

  it("rayon par segment : un segment fin ne déclenche pas là où un gros déclenche", () => {
    const a = straight("r1");
    const b = straight("r2");
    b.joints = b.joints.map(([x, , z]) => [x, 60, z]); // 60 mm d'écart
    expect(collisionPairs([a, b], [35,35,35,35,35,35], 10).length).toBeGreaterThan(0); // 2·35+10=80>60
    expect(collisionPairs([a, b], [20,20,20,20,20,20], 10)).toEqual([]);               // 2·20+10=50<60
  });

  it("robots éloignés → aucune collision", () => {
    const a = straight("r1");
    const b = straight("r2");
    b.joints = b.joints.map(([x, , z]) => [x, 1000, z]);
    expect(collisionPairs([a, b], R6, 10)).toEqual([]);
  });
});

describe("groundHit", () => {
  const R6 = [35, 35, 35, 35, 35, 35];
  const high: RobotPose["joints"] = [0,1,2,3,4,5,6].map((i) => [i*50, 0, 200] as [number,number,number]);
  it("bras au-dessus du sol → pas de collision sol", () => {
    expect(groundHit(high, R6, -50, 10)).toBe(false);
  });
  it("une capsule sous le plan du sol → collision", () => {
    const low = high.map(([x, y]) => [x, y, -40] as [number,number,number]); // z=-40, r=35 → bas=-75 < -50+10
    expect(groundHit(low, R6, -50, 10)).toBe(true);
  });
  it("onlySegs : un segment non surveillé sous le sol n'est pas flaggé", () => {
    const low = high.map(([x, y]) => [x, y, -40] as [number,number,number]);
    expect(groundHit(low, R6, -50, 10, [2, 3, 4, 5])).toBe(true);  // tous bas → encore vrai
    // seul seg0 sous le sol, les autres remontés :
    const mixed = high.map(([x, y], i) => [x, y, i < 2 ? -40 : 200] as [number,number,number]);
    expect(groundHit(mixed, R6, -50, 10)).toBe(true);              // seg0/seg1 bas
    expect(groundHit(mixed, R6, -50, 10, [2, 3, 4, 5])).toBe(false); // seg0/seg1 ignorés
  });
});

describe("restContacts / restGroundSegments", () => {
  // ossature verticale : 7 points sur Z espacés de 30.
  const joints: Vec3[] = [0,1,2,3,4,5,6].map((i) => [0, 0, i * 30] as Vec3);
  const R = [40, 40, 40, 40, 40, 40];

  it("restContacts repère les paires proches en contact au repos", () => {
    const ex = restContacts(joints, R, 10);
    expect(ex.has("0-2")).toBe(true);   // gap axial 30 < 40+40+10
    expect(ex.has("0-5")).toBe(false);  // gap 120 > 90
  });

  it("collisionPairs avec selfExclude ignore les paires listées", () => {
    const folded: RobotPose = { id: "r1", joints };
    const exA = restContacts(joints, R, 10);
    const filtered = collisionPairs([folded], R, 10, exA);
    expect(filtered.some((h) => h.aSeg === 0 && h.bSeg === 2)).toBe(false); // exclue
  });

  it("restGroundSegments ne garde que les segments qui dégagent le sol", () => {
    // sol à z=-5 : seg0 (z0..30, r40 → bas=-40) sous le sol → exclu ;
    const segs = restGroundSegments(joints, R, -5, 10);
    expect(segs).not.toContain(0);      // bas=-40 < -5+10
    expect(segs).toContain(5);          // seg5 z150..180, bas=110 ≥ 5
  });
});

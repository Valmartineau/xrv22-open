import { describe, it, expect } from "vitest";
import { radialRadius } from "./capsuleRadius";
import type { Vec3 } from "./fk";

describe("radialRadius", () => {
  it("cylindre de rayon 10 entre z=0 et z=100 → ~10", () => {
    const verts: Vec3[] = [];
    for (let z = 0; z <= 100; z += 10)
      for (const [x, y] of [[10, 0], [0, 10], [-10, 0], [0, -10]]) verts.push([x, y, z]);
    expect(radialRadius(verts, 0, 100, 1.0)).toBeCloseTo(10, 6);
  });

  it("ignore les vertices hors de la tranche [zMin,zMax]", () => {
    const verts: Vec3[] = [[5, 0, 50], [500, 0, 999]]; // le 2e (z=999) est hors tranche
    expect(radialRadius(verts, 0, 100, 1.0)).toBeCloseTo(5, 6);
  });

  it("percentile écarte un outlier isolé", () => {
    const verts: Vec3[] = [];
    for (let i = 0; i < 99; i++) verts.push([10, 0, 50]); // 99 points à r=10
    verts.push([1000, 0, 50]);                            // 1 pic à r=1000
    expect(radialRadius(verts, 0, 100, 0.95)).toBeCloseTo(10, 6); // p95 = 10
  });
});

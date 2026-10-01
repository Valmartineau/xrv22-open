import { describe, it, expect } from "vitest";
import { fitBoxes } from "./boxFit";
import type { Vec3 } from "./fk";

describe("fitBoxes", () => {
  it("pièce courte → 1 boîte = AABB locale (déport conservé)", () => {
    const verts: Vec3[] = [[70, -5, 0], [90, 5, 20]];
    const b = fitBoxes(verts, 100);
    expect(b.length).toBe(1);
    expect(b[0].c).toEqual([80, 0, 10]);   // centrée sur le nuage, pas l'origine
    expect(b[0].half).toEqual([10, 5, 10]);
  });

  it("pièce longue → tranches contiguës le long du grand côté", () => {
    const verts: Vec3[] = [];
    for (let z = 0; z <= 300; z += 10) verts.push([-5, -5, z], [5, 5, z]);
    const b = fitBoxes(verts, 100);
    expect(b.length).toBe(3);
    // couverture contiguë garantie sur l'axe tranché (bornes nominales)
    expect(b[0].c[2] - b[0].half[2]).toBeCloseTo(0, 6);
    expect(b[0].c[2] + b[0].half[2]).toBeCloseTo(b[1].c[2] - b[1].half[2], 6);
    expect(b[2].c[2] + b[2].half[2]).toBeCloseTo(300, 6);
  });

  it("chaque tranche est serrée sur SA section", () => {
    const verts: Vec3[] = [];
    for (let z = 0; z <= 90; z += 10) verts.push([-5, -5, z], [5, 5, z]);        // fin
    for (let z = 100; z <= 190; z += 10) verts.push([-20, -20, z], [20, 20, z]); // épais
    const b = fitBoxes(verts, 100);
    expect(b.length).toBe(2);
    expect(b[0].half[0]).toBeCloseTo(5, 6);
    expect(b[1].half[0]).toBeCloseTo(20, 6);
  });

  it("le nombre de tranches est borné par kMax", () => {
    const verts: Vec3[] = [];
    for (let z = 0; z <= 1000; z += 10) verts.push([-5, -5, z], [5, 5, z]);
    expect(fitBoxes(verts, 100, 4).length).toBe(4);
  });

  it("entrée vide", () => {
    expect(fitBoxes([], 100)).toEqual([]);
  });
});

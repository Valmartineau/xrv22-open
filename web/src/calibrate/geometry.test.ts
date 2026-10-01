import { describe, it, expect } from "vitest";
import { computeDiscCenter, lockJoint, rotateAboutAxis } from "./geometry";

describe("computeDiscCenter", () => {
  it("centroïde des sommets coplanaires au X cliqué", () => {
    const positions = [5, -1, -1, 5, 1, -1, 5, 1, 1, 5, -1, 1, 0, 9, 9];
    const { center, count } = computeDiscCenter(positions, 5, 0.5);
    expect(count).toBe(4);
    expect(center[0]).toBeCloseTo(5);
    expect(center[1]).toBeCloseTo(0);
    expect(center[2]).toBeCloseTo(0);
  });

  it("aucun sommet coplanaire → fallback sur planeX, count 0", () => {
    const { center, count } = computeDiscCenter([0, 1, 2], 5, 0.5);
    expect(count).toBe(0);
    expect(center).toEqual([5, 0, 0]);
  });
});

describe("lockJoint", () => {
  it("offset YZ pour superposer l'axe enfant sur le parent", () => {
    const off = lockJoint({ y: 10, z: 20 }, { y: 3, z: 5 });
    expect(off).toEqual({ dy: 7, dz: 15 });
  });
});

describe("rotateAboutAxis", () => {
  it("rotation 90° autour d'un axe // X passant par l'origine YZ", () => {
    const p = rotateAboutAxis([7, 1, 0], { y: 0, z: 0 }, 90);
    expect(p[0]).toBeCloseTo(7);
    expect(p[1]).toBeCloseTo(0);
    expect(p[2]).toBeCloseTo(1);
  });

  it("le point sur l'axe ne bouge pas", () => {
    const p = rotateAboutAxis([3, 5, 5], { y: 5, z: 5 }, 123);
    expect(p[1]).toBeCloseTo(5);
    expect(p[2]).toBeCloseTo(5);
  });
});

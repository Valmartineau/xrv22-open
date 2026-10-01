import { describe, it, expect } from "vitest";
import { fk } from "./fk";

describe("fk (pose neutre = ticks undefined)", () => {
  it("articulations alignées verticalement (Z-up)", () => {
    const [j0, j1, j2, j3, j4, j5, j6] = fk(undefined);
    expect(j0).toEqual([0, 0, 0]);
    expect(j1[2]).toBeCloseTo(65);
    expect(j2[2]).toBeCloseTo(103.91, 1);
    expect(j3[2]).toBeCloseTo(313.91, 1);
    expect(j4[2]).toBeCloseTo(513.91, 1);
    expect(j5[2]).toBeCloseTo(563.91, 1);
    expect(j6[2]).toBeCloseTo(613.91, 1);
    for (const j of [j1, j2, j3, j4, j5, j6]) {
      expect(j[0]).toBeCloseTo(0);
      expect(j[1]).toBeCloseTo(0);
    }
  });
});

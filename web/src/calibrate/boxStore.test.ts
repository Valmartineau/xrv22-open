import { describe, it, expect } from "vitest";
import { roundBoxes, newBox, LINK_NAMES } from "./boxStore";

describe("roundBoxes", () => {
  it("arrondit au 0,1 mm sans muter l'original", () => {
    const src = [{ link: 3, c: [1.234, -0.567, 435.449], rotDeg: [-90.04, 180, 0], half: [21.111, 35.79, 18.5] }];
    const out = roundBoxes(src);
    expect(out[0].c).toEqual([1.2, -0.6, 435.4]);
    expect(out[0].rotDeg).toEqual([-90, 180, 0]);
    expect(out[0].half).toEqual([21.1, 35.8, 18.5]);
    expect(src[0].c[0]).toBe(1.234); // pas de mutation
  });
});

describe("newBox / LINK_NAMES", () => {
  it("boîte par défaut valide (maillon 0..5, demi-côtés > 0)", () => {
    const b = newBox();
    expect(b.link).toBeGreaterThanOrEqual(0);
    expect(b.link).toBeLessThan(LINK_NAMES.length);
    expect(b.half.every((h) => h > 0)).toBe(true);
  });
});

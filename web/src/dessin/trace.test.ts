import { describe, it, expect } from "vitest";
import { ajouteTick, type Stroke, type StyletTick } from "./trace";

const tick = (x: number | null, y: number | null, p: number): StyletTick =>
  ({ x, y, p, etat: p > 0 ? "CONTACT" : "SURVOL" });

describe("ajouteTick", () => {
  it("accumule les points en contact dans un même stroke", () => {
    let s: Stroke[] = [];
    s = ajouteTick(s, tick(10, 20, 300));
    s = ajouteTick(s, tick(12, 22, 320));
    expect(s.length).toBe(1);
    expect(s[0].length).toBe(2);
    expect(s[0][1]).toEqual({ x: 12, y: 22, p: 320 });
  });

  it("rompt le trait quand le contact cesse (p=0), puis repart en nouveau stroke", () => {
    let s: Stroke[] = [];
    s = ajouteTick(s, tick(10, 20, 300));
    s = ajouteTick(s, tick(11, 21, 0));   // plus de contact → rupture
    s = ajouteTick(s, tick(40, 50, 300)); // nouveau trait
    expect(s.length).toBe(2);
    expect(s[0].length).toBe(1);
    expect(s[1].length).toBe(1);
  });
});

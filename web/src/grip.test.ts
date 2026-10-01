import { describe, it, expect } from "vitest";
import { gripMm, GRIP_CLOSE_TICK, GRIP_OPEN_TICK, GRIP_SPAN_MM } from "./grip";

describe("gripMm — calibration écart pince (axe 7)", () => {
  it("contact (tick fermé mesuré) = 0 mm", () => {
    expect(gripMm(GRIP_CLOSE_TICK)).toBeCloseTo(0, 3);
  });

  it("butée d'ouverture (tick ouvert mesuré) = écart réel mesuré", () => {
    expect(gripMm(GRIP_OPEN_TICK)).toBeCloseTo(GRIP_SPAN_MM, 3);
  });

  it("ancres réelles : 1649 → 0 mm, 2860 → 46 mm", () => {
    expect(GRIP_CLOSE_TICK).toBe(1649);
    expect(GRIP_OPEN_TICK).toBe(2860);
    expect(GRIP_SPAN_MM).toBe(46.0);
    expect(gripMm(1649)).toBeCloseTo(0, 3);
    expect(gripMm(2860)).toBeCloseTo(46.0, 2);
  });

  it("milieu de course ≈ moitié de l'écart", () => {
    const mid = (GRIP_CLOSE_TICK + GRIP_OPEN_TICK) / 2;
    expect(gripMm(mid)).toBeCloseTo(GRIP_SPAN_MM / 2, 2);
  });

  it("sous le contact : clampé à 0 (jamais d'écart négatif)", () => {
    expect(gripMm(1500)).toBe(0);
    expect(gripMm(0)).toBe(0);
  });

  it("strictement croissant sur la course utile", () => {
    expect(gripMm(2000)).toBeLessThan(gripMm(2400));
    expect(gripMm(2400)).toBeLessThan(gripMm(2800));
  });
});

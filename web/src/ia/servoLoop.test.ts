import { describe, it, expect } from "vitest";
import {
  computeOffset, applyDeadzone, ema, DEADZONE, createServoState, stepServo,
  pinchToAxis7, mapLinear,
} from "./servoLoop";

describe("mapLinear", () => {
  it("mappe entre les deux repères de calibration", () => {
    // repères (signal→ticks) : (0→1000) et (2→3000)
    expect(mapLinear(0, 0, 1000, 2, 3000)).toBe(1000);
    expect(mapLinear(2, 0, 1000, 2, 3000)).toBe(3000);
    expect(mapLinear(1, 0, 1000, 2, 3000)).toBe(2000); // milieu
  });
  it("clampe hors de l'intervalle des ticks", () => {
    expect(mapLinear(-1, 0, 1000, 2, 3000)).toBe(1000);
    expect(mapLinear(5, 0, 1000, 2, 3000)).toBe(3000);
  });
  it("repères de signal identiques → t1 (pas de division par zéro)", () => {
    expect(mapLinear(1, 0.5, 2048, 0.5, 3000)).toBe(2048);
  });
  it("sens inversé (t1>t2) géré par le clamp min/max", () => {
    expect(mapLinear(0, 0, 3000, 2, 1000)).toBe(3000);
    expect(mapLinear(2, 0, 3000, 2, 1000)).toBe(1000);
  });
});

describe("pinchToAxis7", () => {
  it("doigts joints (pinch ≤ MIN) → closedTicks", () => {
    expect(pinchToAxis7(0.15, 3000, 1000)).toBe(1000);
    expect(pinchToAxis7(0, 3000, 1000)).toBe(1000); // clamp bas
  });
  it("doigts écartés (pinch ≥ MAX) → openTicks", () => {
    expect(pinchToAxis7(1.10, 3000, 1000)).toBe(3000);
    expect(pinchToAxis7(2, 3000, 1000)).toBe(3000); // clamp haut
  });
  it("mi-écart → milieu (proportionnel)", () => {
    // pinch=0.625 = milieu de [0.15,1.10] → (1000+3000)/2 = 2000
    expect(pinchToAxis7(0.625, 3000, 1000)).toBe(2000);
  });
});

describe("computeOffset", () => {
  it("centre → (0,0)", () => {
    expect(computeOffset(0.5, 0.5)).toEqual({ x: 0, y: 0 });
  });
  it("coin bas-droit → (1,1)", () => {
    expect(computeOffset(1, 1)).toEqual({ x: 1, y: 1 });
  });
  it("coin haut-gauche → (-1,-1)", () => {
    expect(computeOffset(0, 0)).toEqual({ x: -1, y: -1 });
  });
});

describe("applyDeadzone", () => {
  it("sous le seuil → 0", () => {
    expect(applyDeadzone(DEADZONE / 2)).toBe(0);
  });
  it("au-dessus du seuil → inchangé", () => {
    expect(applyDeadzone(0.5)).toBe(0.5);
    expect(applyDeadzone(-0.4)).toBe(-0.4);
  });
});

describe("ema", () => {
  it("interpole selon alpha", () => {
    expect(ema(0, 1, 0.5)).toBe(0.5);
    expect(ema(0.5, 1, 0.5)).toBe(0.75);
  });
});

describe("stepServo", () => {
  const base = {
    offset: { x: 1, y: 0 }, present: true, armed: true,
    dt: 0.18, current: { 1: 2048, 4: 2048 },
  };

  it("non armé → aucune écriture", () => {
    const s = createServoState();
    expect(stepServo(s, { ...base, armed: false })).toEqual({});
  });

  it("offset franc sur x → axe 1 avance (ramp=1 à dt=RAMP_S)", () => {
    const s = createServoState();
    // delta = vel(1)*sign(1)*ramp(1)*VMAX(750)*dt(0.18) = 135
    const t = stepServo(s, base);
    expect(t[1]).toBe(2183);
    expect(t[4]).toBe(2048); // y dans la zone morte → tenu au seed
  });

  it("zone morte → axe tenu au seed", () => {
    const s = createServoState();
    const t = stepServo(s, { ...base, offset: { x: 0.05, y: 0 } });
    expect(t[1]).toBe(2048);
  });

  it("main perdue → axes tenus au seed", () => {
    const s = createServoState();
    const t = stepServo(s, { ...base, present: false });
    expect(t[1]).toBe(2048);
    expect(t[4]).toBe(2048);
  });

  it("rampe à mi-course (dt = RAMP_S/2 → ramp=0.5)", () => {
    const s = createServoState();
    // delta = 1*1*0.5*750*0.09 = 33.75 → 2082
    const t = stepServo(s, { ...base, dt: 0.09 });
    expect(t[1]).toBe(2082);
  });

  it("clamp anti-windup à 4095", () => {
    const s = createServoState();
    const t = stepServo(s, { ...base, current: { 1: 4090, 4: 2048 } });
    expect(t[1]).toBe(4095);
  });

  it("signe axe 4 = +1 : offset.y>0 → axe 4 avance", () => {
    const s = createServoState();
    // delta4 = vel(1)*sign(+1)*ramp(1)*VMAX(400)*0.18 = +72 → 2120
    const t = stepServo(s, { ...base, offset: { x: 0, y: 1 } });
    expect(t[4]).toBe(2120);
  });

  it("seed absent → axe ignoré", () => {
    const s = createServoState();
    const t = stepServo(s, { ...base, current: { 1: 2048 } });
    expect(t[1]).toBe(2183);
    expect(4 in t).toBe(false);
  });

  it("sign override (toggles UI) inverse le sens d'un axe", () => {
    const s = createServoState();
    // base offset x:1, sign[1]=-1 → 2048 - 135 = 1913 (au lieu de 2183)
    const t = stepServo(s, { ...base, sign: { 1: -1, 4: -1 } });
    expect(t[1]).toBe(1913);
  });
});

describe("stepServo — axe 2 (épaule) vertical + vmax", () => {
  const baseY = {
    offset: { x: 0, y: 1 }, present: true, armed: true,
    dt: 0.18, current: { 1: 2048, 2: 2048, 4: 2048 },
  };

  it("offset.y>0 pilote l'axe 2 ET l'axe 4 (épaule + coude)", () => {
    const s = createServoState();
    // delta2 = 1*1*ramp(1)*VMAX(250)*0.18 = 45 → 2093
    // delta4 = 1*1*ramp(1)*VMAX(400)*0.18 = 72 → 2120
    const t = stepServo(s, baseY);
    expect(t[2]).toBe(2093);
    expect(t[4]).toBe(2120);
  });

  it("vmax override change la vitesse de l'axe 2", () => {
    const s = createServoState();
    // delta2 = 1*1*1*500*0.18 = 90 → 2138
    const t = stepServo(s, { ...baseY, vmax: { 2: 500 } });
    expect(t[2]).toBe(2138);
  });

  it("vmax séparés : axes 2 et 4 avancent à des vitesses différentes", () => {
    const s = createServoState();
    // delta2 = 1*1*1*100*0.18 = 18 → 2066 ; delta4 = 1*1*1*600*0.18 = 108 → 2156
    const t = stepServo(s, { ...baseY, vmax: { 2: 100, 4: 600 } });
    expect(t[2]).toBe(2066);
    expect(t[4]).toBe(2156);
  });

  it("seed absent → axe 2 ignoré", () => {
    const s = createServoState();
    const t = stepServo(s, { ...baseY, current: { 1: 2048, 4: 2048 } });
    expect(2 in t).toBe(false);
    expect(t[4]).toBe(2120);
  });

  it("sign override inverse le sens de l'axe 2", () => {
    const s = createServoState();
    // delta2 = 1*(-1)*1*250*0.18 = -45 → 2003
    const t = stepServo(s, { ...baseY, sign: { 1: 1, 2: -1, 4: 1 } });
    expect(t[2]).toBe(2003);
  });

  it("axe désactivé (enabled=false) → non écrit", () => {
    const s = createServoState();
    const t = stepServo(s, { ...baseY, enabled: { 2: false } });
    expect(2 in t).toBe(false);
    expect(t[4]).toBe(2120); // les autres axes restent pilotés
  });

  it("axe réactivé re-seede depuis la position courante (pas de saut)", () => {
    const s = createServoState();
    stepServo(s, { ...baseY, enabled: { 2: false } });           // 2 désactivé : pas de seed
    // réactivé avec une nouvelle position courante 3000 → seed 3000 puis +45 = 3045
    const t = stepServo(s, { ...baseY, enabled: { 2: true }, current: { 1: 2048, 2: 3000, 4: 2048 } });
    expect(t[2]).toBe(3045);
  });
});

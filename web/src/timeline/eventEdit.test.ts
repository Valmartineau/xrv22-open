import { describe, it, expect } from "vitest";
import { updateEventPositions, formatConflicts, limitConflicts } from "./eventEdit";

const td = {
  tracks: [
    { track_id: "t1", events: [
      { event_id: "e1", event_type: "MOVE", start_ms: 0, duration_ms: 2000,
        parameters: { positions: { "1": 100 }, duration_s: 2, speed_pct: 100 } },
      { event_id: "e2", event_type: "MOVE", start_ms: 3000, duration_ms: 1000,
        parameters: { positions: { "1": 200 } } },
    ] },
  ],
};

describe("updateEventPositions", () => {
  it("modifie positions/duree/vitesse du bon event, sans toucher les autres", () => {
    const out = updateEventPositions(td, "e1",
      { positions: { "1": 999 }, duration_ms: 5000, speed_pct: 50 });
    const e1 = out.tracks![0].events![0];
    const e2 = out.tracks![0].events![1];
    expect(e1.parameters.positions).toEqual({ "1": 999 });
    expect(e1.duration_ms).toBe(5000);
    expect(e1.parameters.duration_s).toBe(5);
    expect(e1.parameters.speed_pct).toBe(50);
    expect(e2.parameters.positions).toEqual({ "1": 200 }); // inchangé
  });
  it("ne mute pas l'objet d'entrée (immutabilité)", () => {
    const before = JSON.stringify(td);
    updateEventPositions(td, "e1", { positions: { "1": 1 }, duration_ms: 1, speed_pct: 1 });
    expect(JSON.stringify(td)).toBe(before);
  });
});

describe("formatConflicts", () => {
  it("concatène les messages par ' · '", () => {
    expect(formatConflicts([
      { type: "limit", severity: "error", message: "Motor 1: 50 < min 1000" },
      { type: "collision", severity: "error", message: "Incursion dans 'Zone A'" },
    ])).toBe("Motor 1: 50 < min 1000 · Incursion dans 'Zone A'");
  });
  it("retourne '' si aucun conflit", () => {
    expect(formatConflicts([])).toBe("");
  });
});

describe("limitConflicts", () => {
  it("ne garde que les conflits de type 'limit'", () => {
    expect(limitConflicts([
      { type: "limit", severity: "error", message: "Motor 1: 50 < min 1000" },
      { type: "collision", severity: "error", message: "Incursion dans 'Zone A'" },
      { type: "limit", severity: "error", message: "Motor 4: 4000 > max 3000" },
    ])).toEqual([
      { type: "limit", severity: "error", message: "Motor 1: 50 < min 1000" },
      { type: "limit", severity: "error", message: "Motor 4: 4000 > max 3000" },
    ]);
  });
  it("retourne [] si aucun conflit de limite", () => {
    expect(limitConflicts([
      { type: "collision", severity: "error", message: "Incursion" },
    ])).toEqual([]);
    expect(limitConflicts([])).toEqual([]);
  });
});

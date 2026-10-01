import { describe, it, expect } from "vitest";
import { ZONE_TYPE_META, type ZoneType } from "./zoneTypes";

describe("ZONE_TYPE_META", () => {
  it("contient les 3 types attendus", () => {
    const types: ZoneType[] = ["plane", "warning", "exclusion"];
    for (const t of types) {
      expect(ZONE_TYPE_META[t]).toBeDefined();
    }
  });

  it("plane = Référence + bleu", () => {
    expect(ZONE_TYPE_META.plane.label).toBe("Référence");
    expect(ZONE_TYPE_META.plane.color).toBe("#3080d0");
  });

  it("warning = ambre", () => {
    expect(ZONE_TYPE_META.warning.color).toBe("#f6a117");
  });

  it("exclusion = rouge", () => {
    expect(ZONE_TYPE_META.exclusion.color).toBe("#f43f5e");
  });

  it("chaque type a un icon non vide", () => {
    for (const t of ["plane", "warning", "exclusion"] as ZoneType[]) {
      expect(ZONE_TYPE_META[t].icon.length).toBeGreaterThan(0);
    }
  });
});

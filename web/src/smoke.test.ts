import { describe, it, expect } from "vitest";

// Test de fumée : confirme que le harnais Vitest tourne.
describe("harnais de test", () => {
  it("exécute une assertion", () => {
    expect(1 + 1).toBe(2);
  });
});

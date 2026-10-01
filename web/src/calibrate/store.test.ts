import { describe, it, expect } from "vitest";
import { toExportJSON, type CalibState } from "./store";

describe("toExportJSON", () => {
  it("exporte offset, rot et joint par pièce calibrée", () => {
    const state: CalibState = {
      parts: [
        { name: "UA", url: "/robot/RXA-200-M-3-UA.stl",
          axisLocal: [0, -48.7, 199.6], targetJoint: 2,
          offset: [0, 48.7, -95.7], rot: [0, 0, 0] },
        { name: "Base", url: "/robot/RXA-200-M-1-Base.stl",
          axisLocal: null, targetJoint: null, offset: [0, 0, 0], rot: [0, 0, 0] },
      ],
    };
    const out = toExportJSON(state);
    expect(out.UA).toEqual({ offset: [0, 48.7, -95.7], rot: [0, 0, 0], joint: 2 });
    expect(out.Base).toBeUndefined();
  });
});

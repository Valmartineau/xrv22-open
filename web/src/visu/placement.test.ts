import { describe, it, expect } from "vitest";
import { robotOffsetX, zoneWorldOffset, toRealityFrame } from "./placement";

describe("robotOffsetX", () => {
  it("robot_1 -> +spacingRight (à droite)", () => {
    expect(robotOffsetX("robot_1", 300, 250)).toBe(300);
  });
  it("robot_3 -> -spacingLeft (à gauche)", () => {
    expect(robotOffsetX("robot_3", 300, 250)).toBe(-250);
  });
  it("robot_2 -> 0 (centre)", () => {
    expect(robotOffsetX("robot_2", 300, 250)).toBe(0);
  });
  it("id inconnu/vide -> 0 (centre)", () => {
    expect(robotOffsetX("", 300, 250)).toBe(0);
    expect(robotOffsetX("robot_42", 300, 250)).toBe(0);
  });
});

describe("zoneWorldOffset", () => {
  // Une surface est capturée dans le repère LOCAL de son robot. Pour s'afficher
  // au bon endroit (collée au robot qui l'a créée, pas glissée vers le centre),
  // elle doit porter le même offset monde X que ce robot.
  it("zone de robot_1 -> offset [+spacingRight, 0, 0]", () => {
    expect(zoneWorldOffset({ source_robot_id: "robot_1" }, 300, 250)).toEqual([300, 0, 0]);
  });
  it("zone de robot_3 -> offset [-spacingLeft, 0, 0]", () => {
    expect(zoneWorldOffset({ source_robot_id: "robot_3" }, 300, 250)).toEqual([-250, 0, 0]);
  });
  it("zone sans source_robot_id -> centre [0,0,0]", () => {
    expect(zoneWorldOffset({}, 300, 250)).toEqual([0, 0, 0]);
  });
});

describe("toRealityFrame", () => {
  const pts = [[-162, 232, 247], [-148, 53, 248]];
  it("inverse toujours X (miroir plan YZ), Y/Z inchangés", () => {
    expect(toRealityFrame(pts)).toEqual([[162, 232, 247], [148, 53, 248]]);
  });
});

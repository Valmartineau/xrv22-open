import { describe, it, expect } from "vitest";
import { centroid, triangulateFan } from "./Surfaces";

describe("centroid", () => {
  it("3 points : moyenne arithmétique", () => {
    const c = centroid([[0, 0, 0], [3, 0, 0], [0, 3, 0]]);
    expect(c).toEqual([1, 1, 0]);
  });
  it("4 points : moyenne arithmétique", () => {
    const c = centroid([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]]);
    expect(c).toEqual([5, 5, 0]);
  });
});

describe("triangulateFan", () => {
  it("N=3 -> 1 triangle (3 indices)", () => {
    expect(triangulateFan(3)).toEqual([0, 1, 2]);
  });
  it("N=4 -> 2 triangles (6 indices)", () => {
    expect(triangulateFan(4)).toEqual([0, 1, 2, 0, 2, 3]);
  });
  it("N=5 -> 3 triangles fan (9 indices)", () => {
    expect(triangulateFan(5)).toEqual([0, 1, 2, 0, 2, 3, 0, 3, 4]);
  });
});

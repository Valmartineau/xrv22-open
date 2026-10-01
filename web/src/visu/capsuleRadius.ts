// Rayon enveloppe d'un segment : à la pose de référence l'ossature est verticale
// (axes en x=y=0), donc le rayon d'une capsule = la distance radiale (√(x²+y²))
// des vertices STL dans la tranche de hauteur du segment, au percentile `pct`
// (robuste aux pics isolés type vis/connecteur).
import type { Vec3 } from "./fk";

export function radialRadius(vertices: Vec3[], zMin: number, zMax: number, pct: number): number {
  const lo = Math.min(zMin, zMax), hi = Math.max(zMin, zMax);
  const radii: number[] = [];
  for (const [x, y, z] of vertices) {
    if (z < lo || z > hi) continue;
    radii.push(Math.hypot(x, y));
  }
  if (radii.length === 0) return 0;
  radii.sort((a, b) => a - b);
  const idx = Math.min(radii.length - 1, Math.max(0, Math.ceil(pct * radii.length) - 1));
  return radii[idx];
}

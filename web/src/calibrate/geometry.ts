// Source unique du type partagé : on le réexporte pour les imports existants
// (CalibPart, CalibratePage importent Vec3 depuis ce module).
import type { Vec3 } from "../visu/fk";
export type { Vec3 };

/**
 * Centre du disque d'articulation cliqué. L'axe étant perpendiculaire au plan
 * YZ (parallèle à X), on collecte les sommets coplanaires au X du point cliqué
 * et on renvoie leur centroïde : (y, z) = centre de l'axe.
 * Fallback : aucun sommet dans la tranche → centre [planeX, 0, 0], count 0.
 *
 * Module pur (pas de dépendance React/Three) : la moyenne y/z est calculée
 * inline plutôt qu'importée de Surfaces.tsx (qui tire react-three/drei).
 */
export function computeDiscCenter(
  positions: ArrayLike<number>,
  planeX: number,
  eps = 1.0,
): { center: Vec3; count: number } {
  let sumY = 0,
    sumZ = 0,
    count = 0;
  for (let i = 0; i < positions.length; i += 3) {
    if (Math.abs(positions[i] - planeX) <= eps) {
      sumY += positions[i + 1];
      sumZ += positions[i + 2];
      count++;
    }
  }
  if (count === 0) return { center: [planeX, 0, 0], count: 0 };
  return { center: [planeX, sumY / count, sumZ / count], count };
}

/**
 * Offset (plan YZ) à appliquer à la pièce enfant pour superposer son axe sur
 * celui du parent. Les axes étant // X, X reste libre (slider d'emboîtement).
 */
export function lockJoint(
  parentCenter: { y: number; z: number },
  childCenter: { y: number; z: number },
): { dy: number; dz: number } {
  return { dy: parentCenter.y - childCenter.y, dz: parentCenter.z - childCenter.z };
}

/** Rotation d'un point autour d'un axe // X passant par (center.y, center.z). */
export function rotateAboutAxis(
  point: Vec3,
  center: { y: number; z: number },
  angleDeg: number,
): Vec3 {
  const a = (angleDeg * Math.PI) / 180;
  const cos = Math.cos(a),
    sin = Math.sin(a);
  const dy = point[1] - center.y;
  const dz = point[2] - center.z;
  return [point[0], center.y + dy * cos - dz * sin, center.z + dy * sin + dz * cos];
}

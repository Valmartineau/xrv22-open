/**
 * Étend 3 points capturés en 4 coins d'un rectangle coplanaire centré.
 * Repris de tab_visu.py:_extend_plane_points (Tk Mac), avec extent agrandi
 * pour donner un rendu visuel "illimité".
 *
 * @param pts les 3 ou 4 points captés (en mm)
 * @param extent demi-côté du rectangle généré (mm), défaut 2000 = 4m × 4m
 * @returns 4 points 3D formant le rectangle, ou les pts d'origine si dégénérés
 */
export function extendPlanePoints(pts: number[][], extent = 2000): number[][] {
  if (pts.length < 3) return pts;
  const [p0, p1, p2] = pts;

  const cx = (p0[0] + p1[0] + p2[0]) / 3;
  const cy = (p0[1] + p1[1] + p2[1]) / 3;
  const cz = (p0[2] + p1[2] + p2[2]) / 3;

  const dx1 = p1[0] - p0[0], dy1 = p1[1] - p0[1], dz1 = p1[2] - p0[2];
  const m1 = Math.hypot(dx1, dy1, dz1);
  if (m1 < 1e-6) return pts;
  const t1: [number, number, number] = [dx1 / m1, dy1 / m1, dz1 / m1];

  const dx2 = p2[0] - p0[0], dy2 = p2[1] - p0[1], dz2 = p2[2] - p0[2];
  const nx = dy1 * dz2 - dz1 * dy2;
  const ny = dz1 * dx2 - dx1 * dz2;
  const nz = dx1 * dy2 - dy1 * dx2;
  const mn = Math.hypot(nx, ny, nz);
  if (mn < 1e-6) return pts;
  const n: [number, number, number] = [nx / mn, ny / mn, nz / mn];

  const t2: [number, number, number] = [
    n[1] * t1[2] - n[2] * t1[1],
    n[2] * t1[0] - n[0] * t1[2],
    n[0] * t1[1] - n[1] * t1[0],
  ];

  return [
    [cx - extent * t1[0] - extent * t2[0],
     cy - extent * t1[1] - extent * t2[1],
     cz - extent * t1[2] - extent * t2[2]],
    [cx + extent * t1[0] - extent * t2[0],
     cy + extent * t1[1] - extent * t2[1],
     cz + extent * t1[2] - extent * t2[2]],
    [cx + extent * t1[0] + extent * t2[0],
     cy + extent * t1[1] + extent * t2[1],
     cz + extent * t1[2] + extent * t2[2]],
    [cx - extent * t1[0] + extent * t2[0],
     cy - extent * t1[1] + extent * t2[1],
     cz - extent * t1[2] + extent * t2[2]],
  ];
}

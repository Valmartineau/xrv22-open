// Affichage debug des capsules de collision par-dessus le STL : un cylindre+
// hémisphères (CapsuleGeometry) le long de chaque segment, au rayon calibré.
// Permet de VOIR le volume de collision vs le mesh (calage, décalages).
import { useMemo } from "react";
import { Vector3, Quaternion } from "three";
import { SEGMENTS } from "./collision";
import { calibJoints, type CalibData } from "./calibKinematics";

const UP = new Vector3(0, 1, 0);

export function CollisionCapsules({ ticks, calib, groundOffset = 150 }: {
  ticks: Record<string, number>; calib: CalibData; groundOffset?: number;
}) {
  const joints = useMemo(() => calibJoints(ticks, calib), [ticks, calib]);
  const radii = calib.segments?.map((s) => s.r) ?? [];
  return (
    <group position={[0, 0, groundOffset]}>
      {SEGMENTS.map(([a, b], i) => {
        const p0 = new Vector3(...joints[a]);
        const p1 = new Vector3(...joints[b]);
        const dir = new Vector3().subVectors(p1, p0);
        const len = dir.length();
        if (len < 1e-6) return null;
        const mid = new Vector3().addVectors(p0, p1).multiplyScalar(0.5);
        const quat = new Quaternion().setFromUnitVectors(UP, dir.clone().normalize());
        const r = radii[i] ?? 0;
        return (
          <mesh key={i} position={[mid.x, mid.y, mid.z]}
                quaternion={[quat.x, quat.y, quat.z, quat.w]}>
            <capsuleGeometry args={[r, len, 8, 16]} />
            <meshStandardMaterial color="#36c5f0" transparent opacity={0.22} depthWrite={false} />
          </mesh>
        );
      })}
    </group>
  );
}

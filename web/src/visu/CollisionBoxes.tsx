// Affichage debug des boîtes d'encombrement par-dessus le STL : une boîte
// translucide par volume semé (gen-collision-boxes). Permet de VOIR le volume
// de collision vs le mesh — y compris les pièces en déport.
import { useMemo } from "react";
import { worldBoxes } from "./boxCollision";
import type { CalibData } from "./calibKinematics";

export function CollisionBoxes({ ticks, calib, groundOffset = 150, hitIdx = [] }: {
  ticks: Record<string, number>; calib: CalibData; groundOffset?: number;
  hitIdx?: number[]; // boîtes fautives (collision/sol) → surlignées en rouge
}) {
  const boxes = useMemo(() => worldBoxes(ticks, 0, calib), [ticks, calib]);
  const hit = useMemo(() => new Set(hitIdx), [hitIdx]);
  return (
    <group position={[0, 0, groundOffset]}>
      {boxes.map((b, i) => (
        <mesh key={i} position={[b.c[0], b.c[1], b.c[2]]} quaternion={b.q}>
          <boxGeometry args={[2 * b.half[0], 2 * b.half[1], 2 * b.half[2]]} />
          <meshStandardMaterial color={hit.has(i) ? "#ff4444" : "#36c5f0"} transparent
                                opacity={hit.has(i) ? 0.55 : 0.25} depthWrite={false} />
        </mesh>
      ))}
    </group>
  );
}

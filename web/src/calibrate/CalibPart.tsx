// web/src/calibrate/CalibPart.tsx
import { useState, useEffect } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { DoubleSide, type BufferGeometry } from "three";
import { computeDiscCenter, type Vec3 } from "./geometry";

const EPS = 1.0;

// Chargement STL résilient : réessaie en cas d'échec réseau (les 5 STL chargés
// en parallèle + requêtes vers le Pi injoignable provoquent des "Load failed"
// intermittents ; useLoader, lui, met l'échec en cache pour toujours).
function useStl(url: string, maxTries = 10): BufferGeometry | null {
  const [geom, setGeom] = useState<BufferGeometry | null>(null);
  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    const loader = new STLLoader();
    const tryLoad = () => {
      loader.load(
        url,
        (g) => { if (!cancelled) setGeom(g); },
        undefined,
        () => {
          attempt += 1;
          if (!cancelled && attempt < maxTries) {
            setTimeout(tryLoad, 250 * attempt); // backoff léger
          } else if (!cancelled) {
            console.warn(`[calibrate] STL non chargé après ${maxTries} essais: ${url}`);
          }
        },
      );
    };
    tryLoad();
    return () => { cancelled = true; };
  }, [url, maxTries]);
  return geom;
}

export function CalibPart({ url, color, offset, rot, pivot, locked, onPick }: {
  url: string;
  color: string;
  offset: Vec3;
  rot: Vec3;
  pivot: Vec3 | null;
  locked: boolean;
  onPick: (centerLocal: Vec3) => void;
}) {
  const geom = useStl(url);
  const p: Vec3 = pivot ?? [0, 0, 0];

  if (!geom) return null; // pas encore chargé (ou échec après retries)

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (locked) return; // STL verrouillés : pas de modification au clic
    e.stopPropagation();
    const local = e.object.worldToLocal(e.point.clone());
    const pos = (geom.attributes.position as { array: ArrayLike<number> }).array;
    const { center } = computeDiscCenter(pos, local.x, EPS);
    onPick(center);
  };

  return (
    <group position={offset}>
      <group position={p}>
        <group rotation={rot}>
          <group position={[-p[0], -p[1], -p[2]]}>
            <mesh geometry={geom} onClick={locked ? undefined : handleClick}>
              <meshStandardMaterial color={color} roughness={0.6} metalness={0.2}
                                    side={DoubleSide} transparent opacity={0.45}
                                    depthWrite={false} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}

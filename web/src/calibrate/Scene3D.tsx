// web/src/calibrate/Scene3D.tsx
// Vue de CÔTÉ (profil) en repère Z-up natif : caméra orthographique placée sur
// l'axe X, regardant -X, up = Z. On voit le plan YZ (Y horizontal, Z vertical).
// Les STL et fk() sont en Z-up, donc AUCUN groupe de rotation : tout est direct.
import { useState } from "react";
import { Canvas, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Grid, Html } from "@react-three/drei";
import { Vector3, Quaternion, DoubleSide } from "three";
import { CalibPart } from "./CalibPart";
import { PartBoundary } from "./PartBoundary";
import type { PartCalib } from "./store";
import type { CalibBox } from "../visu/calibKinematics";
import type { Vec3 } from "../visu/fk";

const DEG = Math.PI / 180;

// Boîte d'encombrement éditable : posée à sa pose de repos (même repère que les
// pièces), clic = sélection. La sélection est surlignée jaune.
function BoxHandle({ box, selected, onSelect }: {
  box: CalibBox; selected: boolean; onSelect: () => void;
}) {
  return (
    <group position={box.c as Vec3}
           rotation={[box.rotDeg[0] * DEG, box.rotDeg[1] * DEG, box.rotDeg[2] * DEG]}>
      <mesh onPointerDown={(e) => { e.stopPropagation(); onSelect(); }}>
        <boxGeometry args={[2 * box.half[0], 2 * box.half[1], 2 * box.half[2]]} />
        <meshStandardMaterial color={selected ? "#ffcc00" : "#36c5f0"} transparent
                              opacity={selected ? 0.45 : 0.18} depthWrite={false} />
      </mesh>
    </group>
  );
}

// Segment du squelette reliant deux points de rotation (= un membre du robot).
function SkelSeg({ a, b }: { a: Vec3; b: Vec3 }) {
  const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2];
  const len = Math.max(Math.hypot(dx, dy, dz), 0.001);
  const mid: Vec3 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
  const quat = new Quaternion()
    .setFromUnitVectors(new Vector3(0, 1, 0), new Vector3(dx, dy, dz).normalize())
    .toArray() as [number, number, number, number];
  return (
    <mesh position={mid} quaternion={quat}>
      <cylinderGeometry args={[1.5, 1.5, len, 6]} />
      <meshBasicMaterial color="#cc66ff" transparent opacity={0.7} />
    </mesh>
  );
}

// Squelette : relie les boules consécutives (base→1→2·3→4→5→6→7) = les membres.
function Skeleton({ joints }: { joints: Joint[] }) {
  return (
    <>
      {joints.slice(0, -1).map((j, i) => (
        <SkelSeg key={j.id} a={j.pos} b={joints[i + 1].pos} />
      ))}
    </>
  );
}

export type Joint = {
  id: number; pos: Vec3; label: string; rot: Vec3;
  // angles des membres dans le plan YZ, 0° = vertical (degrés)
  refParent: number; // membre entrant (vers l'articulation précédente)
  refChild: number;  // membre sortant (vers l'articulation suivante)
};

const AXIS_LEN = 320; // longueur de l'axe de travail (mm)
const NEEDLE_LEN = 180; // longueur de l'aiguille d'angle (membre)

// Articulation déplaçable : une boule (poignée) TRAVERSÉE par son axe de travail
// (tige). L'axe est // X par défaut mais réorientable (joint.rot). Drag dans YZ,
// clic = sélection.
function JointHandle({ joint, active, selected, locked, onSelect, onPointerDown }: {
  joint: Joint;
  active: boolean;
  selected: boolean;
  locked: boolean;
  onSelect: (id: number) => void;
  onPointerDown: (id: number, e: ThreeEvent<PointerEvent>) => void;
}) {
  // aiguilles d'angle (membres) dans le plan YZ : 0° = vertical (Z).
  // cylindre // Y par défaut → Rx(π/2 - a) l'aligne sur (0, sin a, cos a).
  const rp = (joint.refParent * Math.PI) / 180;
  const rc = (joint.refChild * Math.PI) / 180;
  return (
    <group position={joint.pos}>
      {/* axe de travail : tige orientable (rot), tige de base // X */}
      <group rotation={joint.rot}>
        <mesh rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[2.5, 2.5, AXIS_LEN, 12]} />
          <meshBasicMaterial color={selected ? "#ffcc00" : "#ff6a3d"} />
        </mesh>
      </group>
      {/* repère de référence : verticale 0° (gris) = aiguille à angle 0 */}
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh position={[0, NEEDLE_LEN / 2, 0]}>
          <cylinderGeometry args={[0.8, 0.8, NEEDLE_LEN, 6]} />
          <meshBasicMaterial color="#9aa" transparent opacity={0.45} />
        </mesh>
      </group>
      {/* aiguille PARENT (bleu) : membre entrant, angle YZ (0° = vertical) */}
      <group rotation={[Math.PI / 2 - rp, 0, 0]}>
        <mesh position={[0, NEEDLE_LEN / 2, 0]}>
          <cylinderGeometry args={[3, 0.5, NEEDLE_LEN, 8]} />
          <meshBasicMaterial color={selected ? "#33aaff" : "#2a6aa0"} />
        </mesh>
      </group>
      {/* aiguille ENFANT (vert) : membre sortant, angle YZ (0° = vertical) */}
      <group rotation={[Math.PI / 2 - rc, 0, 0]}>
        <mesh position={[0, NEEDLE_LEN / 2, 0]}>
          <cylinderGeometry args={[3, 0.5, NEEDLE_LEN, 8]} />
          <meshBasicMaterial color={selected ? "#7CFC00" : "#3ad17f"} />
        </mesh>
      </group>
      {/* boule = poignée : sélection toujours ; déplacement seulement si déverrouillé */}
      <mesh onPointerDown={(e) => {
              e.stopPropagation(); onSelect(joint.id);
              if (!locked) onPointerDown(joint.id, e);
            }}>
        <sphereGeometry args={[12, 20, 20]} />
        <meshBasicMaterial color={active || selected ? "#ffcc00" : "#7fd1ff"} />
      </mesh>
      {/* nom de l'axe (texte) */}
      <Html center style={{ pointerEvents: "none" }}>
        <div style={{ transform: "translate(22px,-10px)",
                      color: selected ? "#fff" : "#ffcc00",
                      font: "bold 13px sans-serif", whiteSpace: "nowrap",
                      textShadow: "0 0 3px #000" }}>
          axe {joint.label}
        </div>
      </Html>
    </group>
  );
}

export function Scene3D({ parts, joints, selectedId, locked, refZ, onSelect, onMoveJoint, onPick,
                          boxes = [], selBox = null, onSelectBox }: {
  parts: PartCalib[];
  joints: Joint[];
  selectedId: number | null;
  locked: boolean;
  refZ: number;
  onSelect: (id: number) => void;
  onMoveJoint: (id: number, pos: Vec3) => void;
  onPick: (partName: string, centerLocal: Vec3) => void;
  boxes?: CalibBox[];
  selBox?: number | null;
  onSelectBox?: (i: number) => void;
}) {
  const [dragId, setDragId] = useState<number | null>(null);

  // Plan invisible de normale X (à X=0) : capte le déplacement souris en (y, z).
  // Les boules sont AIMANTÉES au plan YZ → X forcé à 0.
  const onPlaneMove = (e: ThreeEvent<PointerEvent>) => {
    if (dragId == null) return;
    e.stopPropagation();
    onMoveJoint(dragId, [0, e.point.y, e.point.z]);
  };

  return (
    <Canvas
      orthographic
      gl={{ preserveDrawingBuffer: true }}
      camera={{ position: [2000, 0, 250], zoom: 1.4, near: 0.1, far: 8000, up: [0, 0, 1] }}
      style={{ width: "100%", height: "100%", background: "#0c0e14" }}
      onPointerUp={() => setDragId(null)}
      onPointerMissed={() => setDragId(null)}
    >
      <ambientLight intensity={0.85} />
      <directionalLight position={[600, 400, 600]} intensity={0.9} />

      {/* sol (plan XY en Z-up) */}
      <Grid args={[2000, 2000]} cellSize={50} sectionSize={250} infiniteGrid
            rotation={[Math.PI / 2, 0, 0]} fadeDistance={4000} />

      {/* surface de référence : plan horizontal XY à Z=refZ (sol des robots).
          planeGeometry est dans XY (normale Z) → déjà horizontal en Z-up. */}
      <mesh position={[0, 0, refZ]} raycast={() => null}>
        <planeGeometry args={[1500, 1500]} />
        <meshBasicMaterial color="#4aa3ff" transparent opacity={0.18}
                           side={DoubleSide} depthWrite={false} />
      </mesh>

      {/* plan de drag (normale X) : transparent mais détectable au raycast
          (visible={false} désactiverait la détection des pointer events). */}
      <mesh rotation={[0, Math.PI / 2, 0]} onPointerMove={onPlaneMove}>
        <planeGeometry args={[6000, 6000]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {parts.map((p) => (
        <PartBoundary key={p.name} name={p.name}>
          <CalibPart url={p.url} color="#b08bd0" locked={locked || !!p.locked}
                     offset={p.offset} rot={p.rot} pivot={p.axisLocal}
                     onPick={(c) => onPick(p.name, c)} />
        </PartBoundary>
      ))}

      {/* boîtes d'encombrement (anti-collision) éditables */}
      {boxes.map((b, i) => (
        <BoxHandle key={i} box={b} selected={selBox === i}
                   onSelect={() => onSelectBox?.(i)} />
      ))}

      {/* squelette : membres = segments reliant les points de rotation */}
      <Skeleton joints={joints} />

      {/* articulations déplaçables (par-dessus, toujours visibles) */}
      {joints.map((j) => (
        <JointHandle key={j.id} joint={j} active={dragId === j.id} locked={locked}
                     selected={selectedId === j.id} onSelect={onSelect}
                     onPointerDown={(id) => setDragId(id)} />
      ))}

      {/* orbit désactivé pendant un drag de sphère */}
      <OrbitControls makeDefault enabled={dragId == null} target={[0, 0, 250]} />
    </Canvas>
  );
}

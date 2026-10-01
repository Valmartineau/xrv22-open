import { Html, Line } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import type { ZoneRec } from "../commands";
import { ZONE_TYPE_META } from "../zoneTypes";
import { extendPlanePoints } from "./geometry";
import { zoneWorldOffset, toRealityFrame } from "./placement";

type Pt3 = [number, number, number];

export function centroid(points: Pt3[] | number[][]): Pt3 {
  const n = points.length;
  let x = 0, y = 0, z = 0;
  for (const p of points) { x += p[0]; y += p[1]; z += p[2]; }
  return [x / n, y / n, z / n];
}

export function triangulateFan(n: number): number[] {
  // Fan : (0,1,2) (0,2,3) (0,3,4) ...
  const out: number[] = [];
  for (let i = 1; i < n - 1; i++) {
    out.push(0, i, i + 1);
  }
  return out;
}

function buildGeometry(points: number[][]) {
  const positions = new Float32Array(points.length * 3);
  points.forEach((p, i) => {
    positions[i * 3] = p[0]; positions[i * 3 + 1] = p[1]; positions[i * 3 + 2] = p[2];
  });
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geom.setIndex(triangulateFan(points.length));
  geom.computeVertexNormals();
  return geom;
}

interface SurfacesProps {
  zones: ZoneRec[];
  focusedId?: string | null;
  extendedIds?: Set<string>;
  flashId?: string | null;
  // Espacement monde des robots (mm) : chaque surface est décalée de l'offset X
  // de son robot source pour rester collée au robot qui l'a créée.
  spacingRightMm: number;
  spacingLeftMm: number;
}

// Décalage de sécurité GLOBAL (mm) appliqué le long de la normale des plans de
// référence (marge de garde au-dessus de la surface). VISUEL pour l'instant ;
// la prise en compte par la sécurité active (backend collision) reste à faire.
const SAFETY_MARGIN_MM = 1;

// Projette les points sur le plan de l'axe (coordonnée constante = moyenne + marge) :
// XY -> plan horizontal (Z moyen), XZ -> Y moyen, YZ -> X moyen. Rend une surface
// "· XY/XZ/YZ" parfaitement plane, indépendamment de l'imprécision de capture.
function flattenToAxis(pts: number[][], axis?: string | null): number[][] {
  const idx = axis === "XY" ? 2 : axis === "XZ" ? 1 : axis === "YZ" ? 0 : -1;
  if (idx < 0 || pts.length === 0) return pts;
  const avg = pts.reduce((s, p) => s + p[idx], 0) / pts.length;
  const target = avg + SAFETY_MARGIN_MM; // décalage de sécurité le long de l'axe
  return pts.map((p) => p.map((v, i) => (i === idx ? target : v)));
}

export function Surfaces({ zones, focusedId, extendedIds, flashId,
                           spacingRightMm, spacingLeftMm }: SurfacesProps) {
  return (
    <>
      {zones.filter(z => z.visible && z.points.length >= 3).map(z => {
        // Repère réalité (miroir X, voir toRealityFrame), puis surfaces de
        // référence (plane) forcées planes sur leur axe.
        const framed = toRealityFrame(z.points);
        const base = z.zone_type === "plane" ? flattenToAxis(framed, z.plane_axis) : framed;
        const displayPoints = extendedIds?.has(z.id)
          ? extendPlanePoints(base)
          : base;
        // Décalage monde = offset X du robot source (points stockés en local).
        const offset = zoneWorldOffset(z, spacingRightMm, spacingLeftMm);
        return (
          <group key={z.id} position={offset}>
            <SurfaceItem
              zone={z}
              displayPoints={displayPoints}
              focused={focusedId === z.id}
              flash={flashId === z.id}
            />
          </group>
        );
      })}
    </>
  );
}

function SurfaceItem({ zone, displayPoints, focused, flash }: {
  zone: ZoneRec;
  displayPoints: number[][];
  focused: boolean;
  flash: boolean;
}) {
  const baseColor = zone.color || ZONE_TYPE_META[zone.zone_type].color;
  const color = flash ? "#ff2244" : baseColor;
  const opacity = flash ? 0.6 : (focused ? 0.4 : 0.25);
  const geom = useMemo(() => buildGeometry(displayPoints), [displayPoints]);
  const linePts = useMemo<Pt3[]>(
    () => [...displayPoints.map(p => [p[0], p[1], p[2]] as Pt3), displayPoints[0] as Pt3],
    [displayPoints],
  );
  const c = useMemo(() => centroid(displayPoints), [displayPoints]);
  const meta = ZONE_TYPE_META[zone.zone_type];

  return (
    <group>
      <mesh geometry={geom}>
        <meshBasicMaterial
          color={color}
          transparent
          opacity={opacity}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <Line points={linePts} color={color} lineWidth={flash ? 4 : (focused ? 3 : 1.5)} />
      <Html position={c} center distanceFactor={400}>
        <div style={{
          background: "rgba(30,33,48,0.85)", color: "white",
          padding: "2px 6px", borderRadius: 4, fontSize: 10,
          fontFamily: "Geist Mono, monospace", whiteSpace: "nowrap",
          border: `1px solid ${color}`,
          fontWeight: (focused || flash) ? 700 : 400,
        }}>
          {meta.icon} {zone.name} {zone.plane_axis ? `· ${zone.plane_axis}` : ""}
        </div>
      </Html>
    </group>
  );
}

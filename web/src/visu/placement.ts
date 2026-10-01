// Placement monde des robots dans la scène 3D Visu (côte à côte sur l'axe X).
// Convention : robot_1 à droite (+X), robot_3 à gauche (-X), robot_2 et les
// robots inconnus au centre (0). Source unique de vérité partagée entre le
// rendu des robots (Visu.tsx) et le rendu des surfaces (Surfaces.tsx).
export function robotOffsetX(rid: string, spacingRight: number, spacingLeft: number): number {
  if (rid === "robot_1") return +spacingRight;
  if (rid === "robot_3") return -spacingLeft;
  return 0;
}

// Offset monde [x,y,z] d'une zone/surface = celui du robot qui l'a capturée.
// Les points d'une surface sont stockés en coordonnées LOCALES du robot ; sans
// cet offset la surface se dessine au centre et "appartient" visuellement au
// mauvais robot (un plan créé avec robot_1 apparaît collé à robot_3).
export function zoneWorldOffset(
  zone: { source_robot_id?: string },
  spacingRight: number,
  spacingLeft: number,
): [number, number, number] {
  return [robotOffsetX(zone.source_robot_id ?? "", spacingRight, spacingLeft), 0, 0];
}

// Repère "réalité" = celui du robot physique, tel que le rend le mesh STL
// calibré (RobotMeshSTL inverse l'axe 1 : `angle={-a1}`). Le FK de capture
// (fk_tcp / fk.ts) utilise +a1 ; l'axe 1 tournant autour de Z, ce signe
// n'affecte que X (sin(-a1) = -sin(a1)) → les points capturés sont en miroir
// du plan YZ. On les ramène donc toujours dans le repère réalité en inversant X.
// Le mesh wireframe (fk +a1) est lui aussi remis dans ce repère par un miroir X
// côté rendu (scale [-1,1,1]) pour rester cohérent avec le STL et les surfaces.
export function toRealityFrame(points: number[][]): number[][] {
  return points.map((p) => [-p[0], ...p.slice(1)]);
}

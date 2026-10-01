export const PARTS: { name: string; url: string }[] = [
  { name: "Base", url: "/robot/RXA-200-M-1-Base.stl" },
  { name: "Shoulder", url: "/robot/RXA-200-M-2-Shoulder.stl" },
  { name: "UA", url: "/robot/RXA-200-M-3-UA.stl" },
  { name: "Forearm", url: "/robot/RXA-200-M-4-Forearm.stl" },
  { name: "Wrist", url: "/robot/RXA-200-M-5-Wrist.stl" },
  { name: "Gripper", url: "/robot/RXA-200-M-6-Gripper.stl" },
  { name: "Gripper-Prop", url: "/robot/RXA-200-M-7-Gripper-Prop.stl" },
  { name: "Gripper-Bar", url: "/robot/RXA-200-M-8-Gripper-Bar.stl" },
  { name: "Finger", url: "/robot/RXA-200-M-9-Finger.stl" },
];

export const JOINTS: { index: number; label: string }[] = [
  { index: 1, label: "j1 — socle/épaule (axe 1)" },
  { index: 2, label: "j2 — épaule (axe 2)" },
  { index: 3, label: "j3 — coude (axe 4)" },
  { index: 4, label: "j4 — poignet (axe 5)" },
  { index: 5, label: "j5 — rotation tête (axe 6)" },
  { index: 6, label: "j6 — TCP/pince (axe 7)" },
];

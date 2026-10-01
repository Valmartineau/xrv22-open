export type ZoneType = "plane" | "warning" | "exclusion";

export const ZONE_TYPE_META: Record<ZoneType, {
  label: string;
  color: string;
  icon: string;
}> = {
  plane:     { label: "Référence", color: "#3080d0", icon: "▱" },
  warning:   { label: "Warning",   color: "#f6a117", icon: "⚠" },
  exclusion: { label: "Exclusion", color: "#f43f5e", icon: "⛔" },
};

export const ZONE_TYPES: ZoneType[] = ["plane", "warning", "exclusion"];

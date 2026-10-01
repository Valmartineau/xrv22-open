import type { PositionConflict } from "../commands";

type Td = { tracks?: Array<{ events?: Array<Record<string, any>> }> } & Record<string, any>;

export type EventPatch = {
  positions: Record<string, number>;
  duration_ms: number;
  speed_pct: number;
};

// Retourne une COPIE de td où l'événement `eventId` a ses positions/durée/vitesse
// remplacées. N'altère pas l'objet d'entrée.
export function updateEventPositions(td: Td, eventId: string, patch: EventPatch): Td {
  return {
    ...td,
    tracks: (td.tracks ?? []).map((t) => ({
      ...t,
      events: (t.events ?? []).map((e) =>
        e.event_id === eventId
          ? {
              ...e,
              duration_ms: patch.duration_ms,
              parameters: {
                ...(e.parameters ?? {}),
                positions: { ...patch.positions },
                duration_s: patch.duration_ms / 1000,
                speed_pct: patch.speed_pct,
              },
            }
          : e
      ),
    })),
  };
}

export function formatConflicts(conflicts: PositionConflict[]): string {
  return conflicts.map((c) => c.message).join(" · ");
}

// Ne garde que les conflits de dépassement de limites soft (sliders),
// en ignorant les collisions plans/zones (traitées par un chantier dédié).
export function limitConflicts(conflicts: PositionConflict[]): PositionConflict[] {
  return conflicts.filter((c) => c.type === "limit");
}

import { useEffect, useRef, useState } from "react";
import { AxisRow } from "./AxisRow";
import { cmdCheckPosition, cmdWriteDirect, type PositionConflict } from "../commands";
import { formatConflicts } from "../timeline/eventEdit";
import { colorForRobot } from "../theme";
import type { Robot } from "../types";

const AXES = ["Axe 1", "Axe 2", "Axe 3", "Axe 4", "Axe 5", "Axe 6", "Axe 7"];

// Éditeur de position à 7 sliders. État local = ticks éditables. Remonte les
// valeurs via onChange. Live (optionnel) : envoie au robot en débounce. Badge
// conflit recalculé en débounce via check_position.
export function AxisEditor({
  robot, initial, onChange, allowLive = true,
}: {
  robot: Robot | undefined;       // robot ciblé (limites + live + check)
  initial: Record<string, number>;
  onChange: (positions: Record<string, number>) => void;
  allowLive?: boolean;
}) {
  const [ticks, setTicks] = useState<Record<string, number>>(initial);
  const [live, setLive] = useState(false);
  const [conflicts, setConflicts] = useState<PositionConflict[]>([]);
  const timer = useRef<number | null>(null);

  const connected = !!robot?.connected;
  const rid = robot?.id ?? "";

  const setAxis = (axis: number, v: number) => {
    const next = { ...ticks, [String(axis)]: v };
    setTicks(next);
    onChange(next);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (rid) cmdCheckPosition(rid, next).then((r) => setConflicts(r.conflicts)).catch(() => {});
      if (live && connected && rid) cmdWriteDirect(rid, next).catch(() => {});
    }, 60);
  };

  // Check initial au montage
  useEffect(() => {
    if (rid) cmdCheckPosition(rid, ticks).then((r) => setConflicts(r.conflicts)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid]);

  // Nettoyage du timer de débounce au démontage
  useEffect(() => {
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, []);

  return (
    <div className="space-y-2">
      {conflicts.length > 0 && (() => {
        const conflictMsg = formatConflicts(conflicts);
        return (
          <div className="flex items-start gap-2 bg-err_dim border border-err rounded-sm px-2 py-1"
               title={conflictMsg}>
            <span className="text-err font-bold">!</span>
            <span className="font-ui text-caption text-err">{conflictMsg}</span>
          </div>
        );
      })()}
      {AXES.map((label, i) => {
        const axis = i + 1;
        const sl = robot?.soft_limits?.[String(axis)];
        return (
          <AxisRow
            key={axis}
            label={label}
            color={rid ? colorForRobot(rid) : "#f6a117"}
            hw={undefined}
            softLimits={sl ? [sl[0], sl[1]] as [number, number] : undefined}
            target={ticks[String(axis)] ?? 2048}
            onPointerDown={() => {}}
            onPointerUp={() => {}}
            onChange={(v) => setAxis(axis, v)}
            onLimitsChange={() => {}}
            isGripper={axis === 7}
          />
        );
      })}
      {allowLive && (
        <label className="flex items-center gap-1.5 cursor-pointer mt-1"
               title={connected ? "" : "Robot non connecté"}>
          <input type="checkbox" className="accent-amb" checked={live} disabled={!connected}
                 onChange={(e) => setLive(e.target.checked)} />
          <span className="font-ui text-caption text-text">🎮 live robot</span>
        </label>
      )}
    </div>
  );
}

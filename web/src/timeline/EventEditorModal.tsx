import { useState } from "react";
import { Modal, ModalBtn } from "../components/Modal";
import { AxisEditor } from "../components/AxisEditor";
import { cmdUpdatePosition } from "../commands";
import type { Robot } from "../types";

type Ev = Record<string, any>;

export function EventEditorModal({
  event, robot, onCancel, onSave,
}: {
  event: Ev;
  robot: Robot | undefined;
  onCancel: () => void;
  onSave: (patch: { positions: Record<string, number>; duration_ms: number;
                    speed_pct: number; updateLibrary: boolean; positionId?: string }) => void;
}) {
  const params = event.parameters ?? {};
  const [positions, setPositions] = useState<Record<string, number>>(params.positions ?? {});
  const [durationMs, setDurationMs] = useState<number>(event.duration_ms ?? 2000);
  const [speed, setSpeed] = useState<number>(params.speed_pct ?? 100);
  const [updateLib, setUpdateLib] = useState<boolean>(!!params.position_id);

  const isMove = event.event_type === "MOVE";

  return (
    <Modal title={`Modifier : ${event.label || event.event_type}`} onClose={onCancel} width={520}
      footer={<>
        <ModalBtn onClick={onCancel}>Annuler</ModalBtn>
        <ModalBtn primary disabled={!isMove} onClick={() => onSave({
          positions, duration_ms: durationMs, speed_pct: speed,
          updateLibrary: updateLib && !!params.position_id, positionId: params.position_id,
        })}>Enregistrer</ModalBtn>
      </>}>
      {!isMove ? (
        <div className="font-ui text-control text-text_med">
          Édition de ce type d'événement à venir ({event.event_type}).
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-3 font-ui text-caption text-text_med">
            <span>Robot : <b className="text-text">{robot?.id ?? params.robot_id}</b></span>
            <label className="flex items-center gap-1">⏱
              <input type="number" value={durationMs} min={0} step={100}
                     onChange={(e) => setDurationMs(Number(e.target.value))}
                     className="w-20 bg-bg border border-border rounded-sm px-1" /> ms
            </label>
            <label className="flex items-center gap-1">vit.
              <input type="number" value={speed} min={1} step={5}
                     onChange={(e) => setSpeed(Number(e.target.value))}
                     className="w-16 bg-bg border border-border rounded-sm px-1" /> %
            </label>
          </div>
          <AxisEditor robot={robot} initial={positions} onChange={setPositions} />
          {!!params.position_id && (
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" className="accent-amb" checked={updateLib}
                     onChange={(e) => setUpdateLib(e.target.checked)} />
              <span className="font-ui text-caption text-text">maj position librairie ({params.position_name || params.position_id})</span>
            </label>
          )}
        </div>
      )}
    </Modal>
  );
}

export async function maybeUpdateLibrary(patch: { updateLibrary: boolean;
  positionId?: string; positions: Record<string, number> }) {
  if (patch.updateLibrary && patch.positionId) {
    await cmdUpdatePosition(patch.positionId, patch.positions);
  }
}

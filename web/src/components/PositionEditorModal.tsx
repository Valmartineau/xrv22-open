import { useState } from "react";
import { Modal, ModalBtn } from "./Modal";
import { AxisEditor } from "./AxisEditor";
import { cmdUpdatePosition } from "../commands";
import type { Robot } from "../types";

export function PositionEditorModal({
  positionId, name, robot, initial, onClose, onSaved,
}: {
  positionId: string;
  name: string;
  robot: Robot | undefined;
  initial: Record<string, number>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [positions, setPositions] = useState<Record<string, number>>(initial);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    try {
      await cmdUpdatePosition(positionId, positions);
      onSaved();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Modal title={`Modifier la position : ${name}`} onClose={onClose} width={520}
      footer={<>
        <ModalBtn onClick={onClose}>Annuler</ModalBtn>
        <ModalBtn primary onClick={save}>Enregistrer</ModalBtn>
      </>}>
      {err && <div className="text-err font-ui text-caption mb-2">{err}</div>}
      <AxisEditor robot={robot} initial={initial} onChange={setPositions} />
    </Modal>
  );
}

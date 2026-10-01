import { useEffect, useRef, useState } from "react";
import { useLiveBus } from "../useLiveBus";
import { getToken } from "../auth";
import { ajouteTick, type Stroke, type StyletTick } from "./trace";

// Bornes tablette observées (Wacom CTH-461) — ajustables.
const TX = [0, 14720], TY = [0, 9200];
const W = 960, H = 600;

export default function DessinPage() {
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [etat, setEtat] = useState({ etat: "HORS-PORTEE", p: 0 });
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useLiveBus((msg) => {
    if (msg.topic !== "stylet.tick") return;
    const t = msg.data as StyletTick;
    setStrokes((s) => ajouteTick(s, t));
    setEtat({ etat: t.etat, p: t.p });
  });

  useEffect(() => {
    const c = canvasRef.current; if (!c) return;
    const g = c.getContext("2d"); if (!g) return;
    g.clearRect(0, 0, W, H);
    g.fillStyle = "#0d0518"; g.fillRect(0, 0, W, H);
    const mapX = (x: number) => ((x - TX[0]) / (TX[1] - TX[0])) * W;
    const mapY = (y: number) => ((y - TY[0]) / (TY[1] - TY[0])) * H;
    for (const st of strokes) {
      if (st.length < 2) continue;
      g.beginPath();
      g.moveTo(mapX(st[0].x), mapY(st[0].y));
      for (const pt of st.slice(1)) g.lineTo(mapX(pt.x), mapY(pt.y));
      g.strokeStyle = "#C47832";
      g.lineWidth = 1 + (st[st.length - 1].p / 1023) * 5;
      g.lineCap = "round"; g.stroke();
    }
  }, [strokes]);

  const allerDepart = async () => {
    await fetch("/api/eddy/position_depart", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken() ?? ""}` },
    }).catch(() => {});
  };

  return (
    <div className="text-text">
      <div className="flex items-center gap-3 mb-3">
        <h2 className="font-ui text-lg">✏️ Dessin — tracé live d'Eddy</h2>
        <span className="font-mono text-mono_sm text-amb">
          {etat.etat} · p={etat.p}
        </span>
        <button className="ml-auto px-3 py-1 rounded-sm bg-surface border border-border hover:text-amb"
                onClick={() => setStrokes([])}>Effacer</button>
        <button className="px-3 py-1 rounded-sm bg-surface border border-border hover:text-amb"
                onClick={allerDepart}>Position initiale de dessin</button>
      </div>
      <canvas ref={canvasRef} width={W} height={H}
              className="border border-border rounded-sm" />
    </div>
  );
}

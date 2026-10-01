import { useEffect, useRef, useState } from "react";
import { gripMm } from "../grip";

export function AxisRow({
  label, color, hw, softLimits, target, locked,
  onPointerDown, onPointerUp, onChange,
  onLimitsChange, isGripper,
}: {
  label: string;
  color: string;
  hw: number | undefined;
  softLimits: [number, number] | undefined;
  target: number;
  locked?: { reason: string };  // Si defini : slider en lecture seule
  onPointerDown: () => void;
  onPointerUp: () => void;
  onChange: (v: number) => void;
  onLimitsChange: (lo: number, hi: number) => void;
  isGripper?: boolean;  // Axe 7 : affiche l'ecart reel en mm (calibration partagee)
}) {
  const [lo, hi] = softLimits ?? [0, 4095];
  const trackRef = useRef<HTMLDivElement>(null);
  const [draggingLimit, setDraggingLimit] = useState<"lo" | "hi" | null>(null);
  const pct = (v: number) => (v / 4095) * 100;

  // Drag d'un marqueur lo ou hi
  useEffect(() => {
    if (!draggingLimit) return;
    const onMove = (e: PointerEvent) => {
      const track = trackRef.current;
      if (!track) return;
      const rect = track.getBoundingClientRect();
      const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const v = Math.round((x / rect.width) * 4095);
      if (draggingLimit === "lo") {
        onLimitsChange(Math.min(v, hi - 10), hi);
      } else {
        onLimitsChange(lo, Math.max(v, lo + 10));
      }
    };
    const onUp = () => setDraggingLimit(null);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [draggingLimit, lo, hi, onLimitsChange]);

  return (
    <div className={`flex items-center gap-3 mb-2 ${locked ? "opacity-40" : ""}`}>
      <span className={`font-ui text-control w-16 shrink-0 ${locked ? "text-text_dim" : "text-amb"}`}>
        {label}
        {locked && (
          <span className="ml-1 text-[9px] text-text_dim" title={locked.reason}>🔗</span>
        )}
      </span>
      <div
        ref={trackRef}
        className="relative flex-1 h-7 rounded-sm flex items-center"
        style={{ background: locked ? "#2a2e40" : `${color}33` }}
      >
        {/* Zones interdites (rouge sombre, ou gris si verrouille) */}
        {lo > 0 && (
          <div className="absolute inset-y-0 left-0 rounded-l-sm pointer-events-none"
               style={{ width: `${pct(lo)}%`, background: locked ? "#1e2130" : "#3a0a14" }} />
        )}
        {hi < 4095 && (
          <div className="absolute inset-y-0 rounded-r-sm pointer-events-none"
               style={{ left: `${pct(hi)}%`, width: `${100 - pct(hi)}%`, background: locked ? "#1e2130" : "#3a0a14" }} />
        )}
        {/* Zone autorisee (couleur robot translucide, ou gris si verrouille) */}
        <div className="absolute inset-y-0 pointer-events-none"
             style={{
               left: `${pct(lo)}%`,
               width: `${pct(target) - pct(lo)}%`,
               background: locked ? "#3a3e5266" : `${color}66`,
             }} />
        {/* Curseur fantome HW */}
        {hw !== undefined && Math.abs(hw - target) > 5 && (
          <div className="absolute top-1 bottom-1 w-px bg-white/40 pointer-events-none"
               style={{ left: `${pct(hw)}%` }} />
        )}
        {/* Pouce target */}
        <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-5 h-5 rounded-full pointer-events-none z-20"
             style={{
               left: `${pct(target)}%`,
               background: "#1e2944",
               border: locked ? "2px solid #4a5061" : "2px solid #f6a117",
             }} />

        {/* Input range natif (capture pointer pour le pouce target) */}
        <input
          type="range" min={0} max={4095} step={1} value={target}
          disabled={!!locked}
          onPointerDown={locked ? undefined : onPointerDown}
          onPointerUp={locked ? undefined : onPointerUp}
          onPointerCancel={locked ? undefined : onPointerUp}
          onChange={(e) => {
            if (locked) return;
            const v = Math.max(lo, Math.min(hi, Number(e.target.value)));
            onChange(v);
          }}
          className={`absolute inset-0 w-full opacity-0 z-10 ${locked ? "cursor-not-allowed" : "cursor-pointer"}`}
          aria-label={`${label} ${target}`}
        />

        {/* Marqueur LO draggable (▼ ambre au-dessus) */}
        <div
          className={`absolute -top-3 -translate-x-1/2 select-none z-30 group ${
            locked ? "cursor-not-allowed opacity-40" : "cursor-ew-resize"
          }`}
          style={{ left: `${pct(lo)}%` }}
          onPointerDown={locked ? undefined : (e) => { e.stopPropagation(); setDraggingLimit("lo"); }}
          title={locked ? locked.reason : `Min: ${lo} (drag pour modifier)`}
        >
          <div className={`text-sm leading-none transition-transform group-hover:scale-125 ${locked ? "text-text_dim" : "text-amb"}`}
               style={{ filter: draggingLimit === "lo" ? "brightness(1.5)" : "none" }}>
            ▼
          </div>
        </div>

        {/* Marqueur HI draggable (▼ ambre au-dessus) */}
        <div
          className={`absolute -top-3 -translate-x-1/2 select-none z-30 group ${
            locked ? "cursor-not-allowed opacity-40" : "cursor-ew-resize"
          }`}
          style={{ left: `${pct(hi)}%` }}
          onPointerDown={locked ? undefined : (e) => { e.stopPropagation(); setDraggingLimit("hi"); }}
          title={locked ? locked.reason : `Max: ${hi} (drag pour modifier)`}
        >
          <div className={`text-sm leading-none transition-transform group-hover:scale-125 ${locked ? "text-text_dim" : "text-amb"}`}
               style={{ filter: draggingLimit === "hi" ? "brightness(1.5)" : "none" }}>
            ▼
          </div>
        </div>
      </div>
      <span className={`font-mono text-mono_md w-16 text-right tabular-nums ${locked ? "text-text_dim" : "text-text"}`}>
        {target}
      </span>
      {isGripper ? (
        <span className={`font-mono text-[11px] w-20 text-right tabular-nums ${locked ? "text-text_dim" : "text-amb"}`}
              title={`Écart réel des doigts · soft-limits [${lo}–${hi}]`}>
          {gripMm(target).toFixed(1)} mm
        </span>
      ) : (
        <span className={`font-mono text-[10px] w-20 text-right ${locked ? "text-text_dim" : "text-amb/70"}`}>
          [{lo}–{hi}]
        </span>
      )}
    </div>
  );
}

// StatusBar bas — equivalent xrv22/ui/status_bar.py.
// Hauteur 40px, montre l'etat global engine + scheduler + master + message.

import { useStore } from "../store";

export default function StatusBar() {
  const { engineState, robots, wsStatus } = useStore();
  const master = robots.find((r) => r.is_master);
  const masterDot = master?.connected ? "🔴" : "⚪";

  return (
    <footer className="h-statusbar_h bg-surface_hi border-t border-border flex items-center px-4 gap-4 font-ui text-caption">
      <span className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-text_dim" />
        <span className="text-text_med">{engineState}</span>
      </span>

      <span className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-text_dim opacity-60" />
        <span className="text-text_dim">{engineState}</span>
      </span>

      <span className="flex items-center gap-1.5">
        <span>{masterDot}</span>
        <span className="text-text_med">{master?.id ?? "—"}</span>
      </span>

      <span className="text-text_med">Prêt</span>

      <div className="flex-1" />

      <span className={`font-mono text-mono_sm ${wsStatus === "open" ? "text-ok" : "text-err"}`}>
        WS {wsStatus}
      </span>
    </footer>
  );
}

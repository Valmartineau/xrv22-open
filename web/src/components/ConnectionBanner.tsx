// Bandeau de perte de connexion WS au Pi.
// Apparait apres 5s de WS en etat "closed", disparait des reconnexion.
// Bouton "Reessayer" force une reconnexion immediate (pas d'attente 1.5s).

import { useEffect, useState } from "react";
import { useStore } from "../store";

export default function ConnectionBanner() {
  const { wsStatus, wsClosedSince, wsReconnect, refetchAll } = useStore();
  const [showAfterDelay, setShowAfterDelay] = useState(false);

  // Affiche apres 5s de deconnexion ininterrompue
  useEffect(() => {
    if (wsStatus === "open" || !wsClosedSince) {
      setShowAfterDelay(false);
      return;
    }
    const elapsed = Date.now() - wsClosedSince;
    if (elapsed >= 5000) {
      setShowAfterDelay(true);
      return;
    }
    const id = setTimeout(() => setShowAfterDelay(true), 5000 - elapsed);
    return () => clearTimeout(id);
  }, [wsStatus, wsClosedSince]);

  if (wsStatus === "open" || !showAfterDelay) return null;

  const seconds = wsClosedSince
    ? Math.floor((Date.now() - wsClosedSince) / 1000)
    : 0;

  return (
    <div className="bg-err_dim border border-err/40 rounded-sm px-4 py-2 mb-3 flex items-center gap-3">
      <span className="text-err">⚠</span>
      <div className="flex-1">
        <span className="font-ui text-control text-err">
          Connexion au Pi perdue
        </span>
        <span className="font-mono text-mono_sm text-text_med ml-2">
          ({wsStatus} · {seconds}s)
        </span>
        <div className="font-ui text-caption text-text_med mt-0.5">
          Reconnexion automatique en cours… Verifie que le Pi est allume et accessible sur le LAN.
        </div>
      </div>
      <button type="button"
              onClick={() => { wsReconnect(); refetchAll(); }}
              className="px-3 py-1.5 rounded-sm border border-amb/50 bg-amb_dim2 text-amb hover:bg-amb hover:text-bg font-ui text-control transition">
        🔄 Réessayer
      </button>
    </div>
  );
}

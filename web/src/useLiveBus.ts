import { useCallback, useEffect, useRef, useState } from "react";
import type { WsMsg } from "./types";
import { getToken } from "./auth";

// Construit l'URL WS relative a la page courante (Vite proxy en dev,
// FastAPI direct en prod sur le Pi). Le token (Etape 5) passe en query
// car les WS cote browser n'envoient pas de header Authorization.
function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = getToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${proto}//${window.location.host}/ws${qs}`;
}

type Status = "connecting" | "open" | "closed";

/**
 * Hook : maintient une connexion WS au backend XRV22.
 * Appelle onMessage pour chaque event reçu. Reconnecte automatiquement
 * apres 1.5s en cas de perte (ex. redemarrage du Pi).
 *
 * `reconnect()` permet de forcer une reconnexion immediate (bouton Reessayer).
 * `closedSince` (ms epoch) indique depuis quand le WS est en etat "closed",
 * ou null s'il est connecte / en train de se connecter.
 */
export function useLiveBus(
  onMessage: (msg: WsMsg) => void
): { status: Status; closedSince: number | null; reconnect: () => void; send: (obj: unknown) => void } {
  const [status, setStatus] = useState<Status>("connecting");
  const [closedSince, setClosedSince] = useState<number | null>(null);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  // Refs pour piloter la connexion depuis l'exterieur (reconnect())
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stoppedRef = useRef(false);

  const connect = useCallback(() => {
    if (retryRef.current) {
      clearTimeout(retryRef.current);
      retryRef.current = null;
    }
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;
    setStatus("connecting");
    const ws = new WebSocket(wsUrl());
    wsRef.current = ws;
    ws.onopen = () => {
      setStatus("open");
      setClosedSince(null);
    };
    ws.onclose = () => {
      setStatus("closed");
      setClosedSince((cur) => cur ?? Date.now());
      if (!stoppedRef.current) {
        retryRef.current = setTimeout(connect, 1500);
      }
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      try { handlerRef.current(JSON.parse(ev.data) as WsMsg); }
      catch { /* ignore */ }
    };
  }, []);

  const reconnect = useCallback(() => {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
    }
    connect();
  }, [connect]);

  useEffect(() => {
    stoppedRef.current = false;
    connect();
    return () => {
      stoppedRef.current = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((obj: unknown) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }, []);

  return { status, closedSince, reconnect, send };
}

// Store React Context : centralise l'etat partage entre les pages
// (robots, positions live, scenarios, engine, erreurs d'action).
//
// Pas de redux, pas de zustand : 1 seul Context suffit pour notre taille,
// et les pages s'abonnent via le hook `useStore()`.

import {
  createContext, useContext, useEffect, useRef, useState, type ReactNode,
} from "react";
import { authFetch } from "./auth";
import { useLiveBus } from "./useLiveBus";
import type { Robot, Health, PositionsTick, WsMsg,
              PositionRec, SuiteRec } from "./types";
import { cmdListZones, cmdGetSafety, type ZoneRec } from "./commands";

export type Scenario = { id: string; name: string };

// Tri des robots par numero d'id (robot_1, robot_2, robot_3...) — ordre
// stable dans le menu et les selecteurs, quel que soit l'ordre d'ajout
// cote backend.
function sortRobots(list: unknown): Robot[] {
  if (!Array.isArray(list)) return [];
  const num = (id: string) => {
    const m = String(id).match(/(\d+)$/);
    return m ? parseInt(m[1], 10) : 0;
  };
  return [...list].sort((a, b) => num(a.id) - num(b.id));
}

type Ctx = {
  health: Health | null;
  robots: Robot[];
  scenarios: Scenario[];
  positionsLib: PositionRec[];
  suites: SuiteRec[];
  zones: ZoneRec[];
  positions: PositionsTick;
  engineState: string;
  engineElapsedMs: number;
  wsStatus: "connecting" | "open" | "closed";
  wsClosedSince: number | null;
  wsReconnect: () => void;
  wsSend: (obj: unknown) => void;
  loadError: string | null;
  actionError: string | null;
  setActionError: (msg: string | null) => void;
  direct: boolean;
  setDirect: (v: boolean) => void;
  safetyEnabled: boolean;
  setSafetyEnabled: (v: boolean) => void;
  recentlyBlockedZoneId: string | null;
  refetchRobots: () => void;
  refetchScenarios: () => void;
  refetchLibrary: () => void;
  refetchZones: () => void;
  refetchAll: () => void;
};

const StoreContext = createContext<Ctx | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [robots, setRobots] = useState<Robot[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [positionsLib, setPositionsLib] = useState<PositionRec[]>([]);
  const [suites, setSuites] = useState<SuiteRec[]>([]);
  const [zones, setZones] = useState<ZoneRec[]>([]);
  const [positions, setPositions] = useState<PositionsTick>({});
  const [engineState, setEngineState] = useState<string>("IDLE");
  const [engineElapsedMs, setEngineElapsedMs] = useState<number>(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // Mode Direct : partage entre tous les onglets (Visu, Connexion, Positions).
  const [direct, setDirect] = useState(false);
  const [safetyEnabled, setSafetyEnabled] = useState<boolean>(true);
  const [recentlyBlockedZoneId, setRecentlyBlockedZoneId] = useState<string | null>(null);

  const refetchRobots = () => {
    authFetch("/api/robots")
      .then((r) => r.json())
      .then((r) => setRobots(sortRobots(r)))
      .catch(() => {});
  };

  const refetchScenarios = () => {
    authFetch("/api/scenarios")
      .then((r) => r.json())
      .then((s) => setScenarios(Array.isArray(s) ? s : []))
      .catch(() => {});
  };

  const refetchLibrary = () => {
    Promise.all([
      authFetch("/api/positions").then((r) => r.json()).catch(() => []),
      authFetch("/api/suites").then((r) => r.json()).catch(() => []),
    ]).then(([pos, su]) => {
      setPositionsLib(Array.isArray(pos) ? pos : []);
      setSuites(Array.isArray(su) ? su : []);
    });
  };

  const refetchZones = () => {
    cmdListZones()
      .then((zs) => setZones(zs))
      .catch(() => {});
  };

  // Refetch tout d'un coup (utilise au boot et apres reconnexion WS)
  const refetchAll = () => {
    fetch("/api/health").then((r) => r.json()).then(setHealth).catch(() => {});
    refetchRobots();
    refetchScenarios();
    refetchLibrary();
    refetchZones();
  };

  // Bootstrap au premier mount
  useEffect(() => {
    Promise.all([
      fetch("/api/health").then((r) => r.json()),
      authFetch("/api/robots").then((r) => {
        if (r.status === 401) throw new Error("Token invalide");
        return r.json();
      }),
      authFetch("/api/scenarios").then((r) => r.json()).catch(() => []),
      authFetch("/api/positions").then((r) => r.json()).catch(() => []),
      authFetch("/api/suites").then((r) => r.json()).catch(() => []),
      cmdListZones().catch(() => []),
    ])
      .then(([h, r, s, pos, su, z]) => {
        setHealth(h);
        setRobots(sortRobots(r));
        setScenarios(Array.isArray(s) ? s : []);
        setPositionsLib(Array.isArray(pos) ? pos : []);
        setSuites(Array.isArray(su) ? su : []);
        setZones(Array.isArray(z) ? z : []);
        setLoadError(null);
      })
      .catch((e) => setLoadError(String(e)));
    cmdGetSafety().then(s => setSafetyEnabled(s.collision_check_enabled)).catch(() => {});
  }, []);

  const { status: wsStatus, closedSince: wsClosedSince, reconnect: wsReconnect, send: wsSend } = useLiveBus((msg: WsMsg) => {
    switch (msg.topic) {
      case "robot.positions_tick":
        setPositions(msg.data as PositionsTick);
        break;
      case "ui.refresh":
        refetchRobots();
        refetchLibrary();
        refetchZones();
        break;
      case "robot.connected":
      case "robot.disconnected":
      case "robot.state_changed":
      case "robot.master_changed":
      case "robot.torque_changed":
        refetchRobots();
        break;
      case "robot.control_changed": {
        // Arbitrage de contrôle : si le Pi prend la main (ou si la main est
        // libérée), on coupe Direct côté web — un seul pilote à la fois.
        const d = msg.data as { owner?: string | null };
        if (d.owner !== "web") setDirect(false);
        break;
      }
      case "timeline.play":  setEngineState("RUNNING"); break;
      case "timeline.stop":  setEngineState("STOPPED"); setEngineElapsedMs(0); break;
      case "timeline.pause": setEngineState("PAUSED");  break;
      case "engine.tick": {
        const d = msg.data as { elapsed_ms?: number };
        if (typeof d.elapsed_ms === "number") setEngineElapsedMs(d.elapsed_ms);
        break;
      }
      case "engine.error": {
        // Echec d'exécution timeline (ex : robot non pret pour le play).
        // Sans ce case, le message partait à la poubelle et le bouton
        // Lecture semblait "ne rien faire".
        const data = msg.data as { event_type?: string; message?: string };
        setActionError(`⛔ ${data.message ?? "Erreur moteur d'exécution"}`);
        break;
      }
      case "safety.collision_blocked": {
        const data = msg.data as { zone_id?: string; zone_name?: string; incursion_mm?: number };
        const inc = (data.incursion_mm ?? 0).toFixed(1);
        setActionError(`⛔ Bloqué par zone "${data.zone_name ?? "inconnue"}" (incursion ${inc} mm)`);
        if (data.zone_id) {
          const zid = data.zone_id;
          setRecentlyBlockedZoneId(zid);
          setTimeout(() => setRecentlyBlockedZoneId(prev => prev === zid ? null : prev), 3000);
        }
        break;
      }
    }
  });

  // Auto-clear erreur d'action apres 4s
  useEffect(() => {
    if (!actionError) return;
    const id = setTimeout(() => setActionError(null), 4000);
    return () => clearTimeout(id);
  }, [actionError]);

  // Auto-refetch a chaque transition closed/connecting -> open du WS.
  // Ignore le tout 1er passage open au boot (bootstrap deja en cours).
  const prevWsStatusRef = useRef<typeof wsStatus>("connecting");
  const bootedRef = useRef(false);
  useEffect(() => {
    const prev = prevWsStatusRef.current;
    if (wsStatus === "open" && prev !== "open" && bootedRef.current) {
      refetchAll();
    }
    if (wsStatus === "open") bootedRef.current = true;
    prevWsStatusRef.current = wsStatus;
  }, [wsStatus]);

  return (
    <StoreContext.Provider
      value={{
        health, robots, scenarios, positionsLib, suites, zones,
        positions, engineState, engineElapsedMs,
        wsStatus, wsClosedSince, wsReconnect, wsSend,
        loadError, actionError, setActionError,
        direct, setDirect,
        safetyEnabled, setSafetyEnabled, recentlyBlockedZoneId,
        refetchRobots, refetchScenarios, refetchLibrary, refetchZones, refetchAll,
      }}
    >
      {children}
    </StoreContext.Provider>
  );
}

export function useStore(): Ctx {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore() doit etre dans <StoreProvider>");
  return ctx;
}

// Instance PARTAGEE du modele de slider (useLiveAxes) + robot actif.
//
// Montee une seule fois, AU-DESSUS des onglets (routing), pour que :
//  - l'etat des sliders (targets, drag) soit le meme sur les 3 onglets
//    -> synchronisation permanente, pas de saut au changement d'onglet ;
//  - useLiveAxes ne soit PAS demonte/remonte a chaque changement d'onglet
//    (sinon cmdDirectMode + l'arbitrage control_owner se reinitialisent).
//
// Deux contextes separes pour limiter les re-rendus :
//  - ActiveRobotContext : { activeRid, setActiveRid } — change rarement.
//  - LiveAxesContext : l'objet liveAxes — change a chaque drag (~60 Hz).
// Les composants de slider consomment LiveAxesContext (re-rendu cible) ;
// le chrome des pages consomme ActiveRobotContext (re-rendu rare).

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from "react";
import { useStore } from "./store";
import { useLiveAxes, type LiveAxes } from "./useLiveAxes";
import { useLiveBus } from "./useLiveBus";
import { cmdGetActiveRobot, cmdSetActiveRobot } from "./commands";
import type { WsMsg } from "./types";

type ActiveRobot = { activeRid: string; setActiveRid: (id: string) => void };

const ActiveRobotContext = createContext<ActiveRobot | null>(null);
const LiveAxesContext = createContext<LiveAxes | null>(null);

export function LiveAxesProvider({ children }: { children: ReactNode }) {
  const { robots, positions, direct, setActionError, wsSend } = useStore();
  const [activeRid, setActiveRidLocal] = useState<string>("");

  // Fetch initial : synchroniser avec le backend SSOT au montage.
  useEffect(() => {
    cmdGetActiveRobot()
      .then((r) => { if (r.active_robot_id) setActiveRidLocal(r.active_robot_id); })
      .catch(() => {});
  }, []);

  // Fallback local : si le backend ne repond pas ou le robot est inconnu,
  // on garde le premier master connu (comportement original).
  useEffect(() => {
    if (activeRid && robots.find((r) => r.id === activeRid)) return;
    const m = robots.find((r) => r.is_master) || robots[0];
    if (m) setActiveRidLocal(m.id);
  }, [robots, activeRid]);

  // Ecoute WS : le Pi tactile (ou un autre client) a change le robot actif.
  useLiveBus((msg: WsMsg) => {
    if (msg.topic === "system.active_robot_changed") {
      const newRid = (msg.data as { robot_id?: string })?.robot_id;
      if (typeof newRid === "string" && newRid !== activeRid) {
        setActiveRidLocal(newRid);
      }
    }
  });

  // setActiveRid : update optimiste local + PUT backend pour propager au Pi.
  const setActiveRid = useCallback((rid: string) => {
    setActiveRidLocal(rid);
    cmdSetActiveRobot(rid).catch(() => {});
  }, []);

  const robot = robots.find((r) => r.id === activeRid);
  const hw = positions[activeRid];

  // L'unique instance du modele de slider, partagee par les 3 onglets.
  const liveAxes = useLiveAxes({
    rid: activeRid, robot, hw, direct, wsSend, onError: setActionError,
  });

  const activeRobot = useMemo<ActiveRobot>(
    () => ({ activeRid, setActiveRid }), [activeRid, setActiveRid],
  );

  return (
    <ActiveRobotContext.Provider value={activeRobot}>
      <LiveAxesContext.Provider value={liveAxes}>
        {children}
      </LiveAxesContext.Provider>
    </ActiveRobotContext.Provider>
  );
}

export function useActiveRobot(): ActiveRobot {
  const ctx = useContext(ActiveRobotContext);
  if (!ctx) throw new Error("useActiveRobot() doit etre dans <LiveAxesProvider>");
  return ctx;
}

export function useLiveAxesShared(): LiveAxes {
  const ctx = useContext(LiveAxesContext);
  if (!ctx) throw new Error("useLiveAxesShared() doit etre dans <LiveAxesProvider>");
  return ctx;
}

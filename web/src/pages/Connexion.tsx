// Page Connexion fidele a xrv22/ui/tab_connexion.py.
// Layout :
//   Header :  Robot actif [combo]
//   Top : 2 colonnes (Connexion + Actions rapides) + Statut
//   Mid : Parametres mouvement (Durée + Hz/Vel/Acc grisés)
//   Toolbar : Direct + Lire + Go sliders + Stop + Enregistrer position
//   Body : 7 sliders pleine largeur ambre (Axe 1..7) avec valeur ticks
//   Bottom : Couplage axe 2-3 (Activer + Ratio + Offset + Centre)

import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import {
  cmdConnect, cmdDisconnect, cmdReboot, cmdTorque,
  cmdHome, cmdCapture, cmdStop,
  cmdMotorLimit, cmdSetCoupling, cmdCalib, type CouplingCfg,
  cmdAnticollision, getAnticollision,
} from "../commands";
import { useActiveRobot, useLiveAxesShared } from "../liveAxes";
import { authFetch } from "../auth";
import { colorForRobot } from "../theme";
import type { Robot } from "../types";
import { AxisRow } from "../components/AxisRow";

// ── Composants UI bas niveau ─────────────────────────────────────

function ToolbarBtn({
  children, onClick, primary, danger, disabled, busy,
}: {
  children: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  danger?: boolean;
  disabled?: boolean;
  busy?: boolean;
}) {
  const base = "px-4 py-1.5 rounded-sm border font-ui text-control transition disabled:opacity-30";
  const tone = danger
    ? "bg-err_dim text-err border-err/40 hover:bg-err_deep"
    : primary
    ? "bg-mag_dim2 text-amb border-mag/40 hover:bg-mag"
    : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2";
  return (
    <button type="button" onClick={onClick} disabled={disabled || busy}
            className={`${base} ${tone}`}>
      {busy ? "…" : children}
    </button>
  );
}

function Section({
  title, children, color,
}: { title: string; children: React.ReactNode; color?: string }) {
  return (
    <div className="bg-surface border border-border rounded-sm">
      <div
        className={`px-3 py-1.5 font-ui text-section border-b border-border bg-surface_hi rounded-t-sm ${color ? "" : "text-amb"}`}
        style={color ? { color } : undefined}
      >
        {title}
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <label className="font-ui text-control text-text_med w-20 shrink-0">
        {label}
      </label>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function Input({
  value, onChange, placeholder, disabled, mono,
}: {
  value: string; onChange?: (v: string) => void;
  placeholder?: string; disabled?: boolean; mono?: boolean;
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      disabled={disabled}
      placeholder={placeholder}
      className={`w-full bg-bg border border-border rounded-sm px-2 py-1 ${
        mono ? "font-mono text-mono_md" : "font-ui text-control"
      } text-text disabled:opacity-50 focus:outline-none focus:border-amb`}
    />
  );
}

function ActionPill({
  label, color, onClick, disabled,
}: {
  label: string; color: string; onClick: () => void; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="w-full text-left flex items-center px-3 py-1.5 mb-1 rounded-sm bg-surface_hi border border-border_hi hover:bg-mag_dim2 transition disabled:opacity-40"
    >
      <span className="w-2 h-2 rounded-full mr-2.5" style={{ background: color }} />
      <span className="font-ui text-control text-text">{label}</span>
    </button>
  );
}

// ── Onglet Connexion ─────────────────────────────────────────────

const AXES = ["Axe 1", "Axe 2", "Axe 3", "Axe 4", "Axe 5", "Axe 6", "Axe 7"];

// Bloc des 7 sliders d'axes — isolé dans son propre composant.
// Le drag d'un slider met à jour l'état de useLiveAxes en continu (~60 Hz) ;
// en gardant cet état ICI plutôt que dans Connexion(), un tick de slider ne
// re-rend QUE ce bloc — pas tout l'onglet (panneaux connexion, couplage…).
// Sans cette isolation : latence du pouce + pilotage non lisse.
function ConnexionAxes({
  robot, hw, color, coupling,
  localLimits, onLimitsChange,
}: {
  robot: Robot;
  hw: Record<string, number> | undefined;
  color: string;
  coupling: CouplingCfg;
  localLimits: Record<number, [number, number]>;
  onLimitsChange: (axis: number, lo: number, hi: number) => void;
}) {
  // Slider d'axe : instance partagee montee au-dessus du routeur.
  const liveAxes = useLiveAxesShared();

  // Calcule l'axe 3 esclave selon la formule _apply_coupling.
  const couplingChild = (pos2: number): number => {
    if (!coupling.enabled) return liveAxes.value(3);
    const sign = coupling.invert ? -1 : 1;
    const v = coupling.center + sign * coupling.ratio * (pos2 - coupling.center) + coupling.offset;
    return Math.max(0, Math.min(4095, Math.round(v)));
  };

  return (
    <Section title={`Axes — ${robot.id}`} color={color}>
      <div className="text-caption font-ui text-text_dim mb-2">
        Drag les marqueurs <span className="text-amb">▼</span> ambres pour modifier les limites min/max de chaque axe.
      </div>
      {AXES.map((label, i) => {
        const axis = i + 1;
        const slApi = robot.soft_limits?.[String(axis)];
        const slLocal = localLimits[axis];
        const sl = slLocal ?? (slApi ? [slApi[0], slApi[1]] as [number, number] : undefined);
        // Axe 3 = esclave couplé de l'axe 2 : verrou + cible dérivés en surcouche.
        const isCoupled = axis === 3 && coupling.enabled;
        return (
          <AxisRow
            key={axis}
            label={label}
            color={color}
            hw={hw?.[String(axis)]}
            softLimits={sl}
            target={isCoupled ? couplingChild(liveAxes.value(2)) : liveAxes.value(axis)}
            locked={isCoupled
              ? { reason: `Couplé à l'axe 2 (ratio ${coupling.ratio})` }
              : liveAxes.locked(axis)}
            onPointerDown={() => liveAxes.onPointerDown(axis)}
            onPointerUp={() => liveAxes.onPointerUp(axis)}
            onChange={(v) => liveAxes.onChange(axis, v)}
            onLimitsChange={(lo, hi) => onLimitsChange(axis, lo, hi)}
            isGripper={axis === 7}
          />
        );
      })}
    </Section>
  );
}

export default function Connexion() {
  const { robots, positions, setActionError, direct, setDirect } = useStore();
  const { activeRid, setActiveRid } = useActiveRobot();

  const robot = robots.find((r) => r.id === activeRid);
  const color = robot ? colorForRobot(robot.id) : "#f6a117";
  const hw = positions[activeRid];

  const [busy, setBusy] = useState<string | null>(null);

  // Config couplage 2-3 (chargee depuis backend, refresh quand on change)
  const [coupling, setCoupling] = useState<CouplingCfg>({
    enabled: false, invert: false, ratio: 1.0, offset: 0, center: 2048,
  });
  useEffect(() => {
    authFetch("/api/hardware/coupling")
      .then((r) => r.json())
      .then((c: CouplingCfg) => setCoupling(c))
      .catch(() => {});
  }, []);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try { await fn(); } catch (e) {
      setActionError(`${activeRid}: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(null); }
  };

  // Drag des marqueurs lo/hi : optimistic update local + persist throttled (250ms)
  const limitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const limitQueue = useRef<Record<number, [number, number]>>({});
  const [localLimits, setLocalLimits] = useState<Record<number, [number, number]>>({});

  const onLimitsChange = (axis: number, lo: number, hi: number) => {
    setLocalLimits((cur) => ({ ...cur, [axis]: [lo, hi] }));
    limitQueue.current[axis] = [lo, hi];
    if (limitTimer.current) return;
    limitTimer.current = setTimeout(() => {
      const queued = limitQueue.current;
      limitQueue.current = {};
      limitTimer.current = null;
      Object.entries(queued).forEach(([a, [l, h]]) => {
        cmdMotorLimit(activeRid, Number(a), l, h).catch((e) =>
          setActionError(`limit axe ${a}: ${e instanceof Error ? e.message : String(e)}`));
      });
    }, 250);
  };

  // Reset les overrides locaux quand le robot change
  useEffect(() => { setLocalLimits({}); }, [activeRid]);

  // Couche anticollision serveur (boîtes STL) : état lu au montage / changement
  // de robot. ON par défaut côté serveur ; le toggle agit sur TOUS les chemins
  // de pilotage (sliders web, tactile Pi, jog, suites).
  const [antico, setAntico] = useState<{ enabled: boolean; available: boolean } | null>(null);
  useEffect(() => {
    let alive = true;
    setAntico(null);
    getAnticollision(activeRid)
      .then((s) => { if (alive) setAntico(s); })
      .catch(() => { if (alive) setAntico(null); });
    return () => { alive = false; };
  }, [activeRid]);
  const toggleAntico = () => {
    if (!antico) return;
    const enable = !antico.enabled;
    run("antico", () => cmdAnticollision(activeRid, enable)
      .then((r) => setAntico((cur) => cur ? { ...cur, enabled: r.enabled } : cur)));
  };

  const onCapture = () => {
    const name = window.prompt(
      `Nom de la position depuis ${activeRid} :`,
      `pos_${new Date().toISOString().slice(11, 19).replace(/:/g, "")}`
    );
    if (!name) return;
    run("save", () => cmdCapture(activeRid, name));
  };

  if (!robot) {
    return <div className="text-text_dim text-center py-12">Aucun robot disponible</div>;
  }

  return (
    <div
      className="space-y-3 rounded-sm border p-3"
      style={{ background: `${color}1a`, borderColor: `${color}66` }}
    >
      {/* Header : Robot actif */}
      <div className="flex items-center gap-3">
        <span className="font-ui text-control text-text_med">Robot actif :</span>
        <select
          value={activeRid}
          onChange={(e) => setActiveRid(e.target.value)}
          className="bg-surface border border-border rounded-sm px-3 py-1 font-ui text-control text-text focus:outline-none focus:border-amb"
        >
          {robots.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id}{r.is_master ? " ★" : ""}
            </option>
          ))}
        </select>
      </div>

      {/* Top : 3 colonnes */}
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-7">
          <Section title="Connexion robot" color={color}>
            <Field label="Port série :">
              <Input value={robot.port || ""} mono disabled />
            </Field>
            <Field label="Baudrate :">
              <Input value="1000000" mono disabled />
            </Field>
            <div className="flex gap-2 mt-3">
              {robot.connected ? (
                <ToolbarBtn
                  busy={busy === "dis"}
                  onClick={() => run("dis", () => cmdDisconnect(activeRid))}
                >
                  ✕ Déconnecter
                </ToolbarBtn>
              ) : (
                <ToolbarBtn
                  primary busy={busy === "con"}
                  onClick={() => run("con", () => cmdConnect(activeRid))}
                >
                  🔌 Connecter
                </ToolbarBtn>
              )}
              <ToolbarBtn
                disabled={!robot.connected} busy={busy === "reb"}
                onClick={() => run("reb", () => cmdReboot(activeRid))}
              >
                🔄 Reboot
              </ToolbarBtn>
              <ToolbarBtn
                disabled={!robot.connected} busy={busy === "tor"}
                onClick={() => run("tor", () => cmdTorque(activeRid, !robot.torque_enabled))}
              >
                Torque {robot.torque_enabled ? "OFF" : "ON"}
              </ToolbarBtn>
            </div>
            {/* Anticollision serveur : par robot, tous chemins de pilotage */}
            <div className="flex items-center gap-2 mt-3">
              <ToolbarBtn
                primary={antico?.enabled !== false}
                disabled={!antico}
                busy={busy === "antico"}
                onClick={toggleAntico}
              >
                🛡 Anticollision {antico ? (antico.enabled ? "ON" : "OFF") : "…"}
              </ToolbarBtn>
              <span className="font-mono text-mono_sm text-text_med">
                {antico === null ? "état inconnu"
                  : !antico.available ? "moteur indisponible (calibration sans boîtes)"
                  : antico.enabled ? "protège sliders, tactile, jog et suites"
                  : "⚠ désactivée — aucun garde-fou serveur"}
              </span>
            </div>
          </Section>
        </div>

        <div className="col-span-3">
          <Section title="Actions rapides" color={color}>
            <ActionPill label="Calib. Machine" color="#f6a117"
                        disabled={!robot.connected}
                        onClick={() => {
                          if (!window.confirm(
                            `Définir la position courante de ${activeRid} comme nouvelle Pos. Machine ? (action irréversible sans backup)`)) return;
                          run("calibm", () => cmdCalib(activeRid, "machine")
                            .then((r) => setActionError(`Pos. Machine définie : ${Object.entries(r.positions).map(([k,v])=>`${k}:${v}`).join(" ")}`)));
                        }} />
            <ActionPill label="Pos. Machine"   color="#f6a117"
                        disabled={!robot.connected}
                        onClick={() => run("hm", () => cmdHome(activeRid, "machine"))} />
            <ActionPill label="Calib. Travail" color="#4ade80"
                        disabled={!robot.connected}
                        onClick={() => {
                          if (!window.confirm(
                            `Définir la position courante de ${activeRid} comme nouvelle Pos. Travail ?`)) return;
                          run("calibw", () => cmdCalib(activeRid, "work")
                            .then((r) => setActionError(`Pos. Travail définie : ${Object.entries(r.positions).map(([k,v])=>`${k}:${v}`).join(" ")}`)));
                        }} />
            <ActionPill label="Pos. Travail"   color="#4ade80"
                        disabled={!robot.connected}
                        onClick={() => run("hw", () => cmdHome(activeRid, "work"))} />
          </Section>
        </div>

        <div className="col-span-2">
          <Section title="Statut" color={color}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`w-2 h-2 rounded-full ${robot.connected ? "bg-ok" : "bg-text_dim"}`} />
              <span className="font-ui text-control text-text">
                {robot.connected ? "Connecté" : "Déconnecté"}
              </span>
            </div>
            <div className="font-mono text-mono_sm text-text_med">Dynamixel SDK</div>
            <div className="font-mono text-mono_sm text-text_med">pyserial</div>
          </Section>
        </div>
      </div>

      {/* Parametres mouvement */}
      <Section title="Paramètres mouvement" color={color}>
        <div className="grid grid-cols-4 gap-4">
          <Field label="Durée (s) :"><Input value="3.0" mono /></Field>
          <Field label="Hz :"><Input value={String(robot.smooth_hz)} mono disabled /></Field>
          <Field label="Vélocité :"><Input value={String(robot.comfort_vel)} mono disabled /></Field>
          <Field label="Accélération :"><Input value={String(robot.comfort_acc)} mono disabled /></Field>
        </div>
      </Section>

      {/* Toolbar sliders */}
      <div className="flex items-center gap-2 px-2 py-2 bg-surface_hi border border-border rounded-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={direct}
            onChange={(e) => setDirect(e.target.checked)}
            className="accent-amb"
            disabled={!robot.connected || !robot.torque_enabled}
          />
          <span className="font-ui text-control text-text">🎮 Direct</span>
        </label>
        <ToolbarBtn danger onClick={() => run("stop", () => cmdStop(activeRid))}
                    disabled={!robot.connected}>
          ■ Stop
        </ToolbarBtn>
        <div className="flex-1" />
        <ToolbarBtn primary onClick={onCapture} disabled={!robot.connected} busy={busy === "save"}>
          💾 Enregistrer position
        </ToolbarBtn>
      </div>

      {/* Sliders pleine largeur — isolés dans ConnexionAxes pour scoper
          les re-renders du drag (cf commentaire du composant). */}
      <ConnexionAxes
        robot={robot}
        hw={hw}
        color={color}
        coupling={coupling}
        localLimits={localLimits}
        onLimitsChange={onLimitsChange}
      />

      {/* Couplage axe 2-3 */}
      <CouplingSection setActionError={setActionError} onConfigChange={setCoupling} />
    </div>
  );
}

// ── Section Couplage 2-3 ─────────────────────────────────────────

function CouplingSection({ setActionError, onConfigChange }: {
  setActionError: (msg: string | null) => void;
  onConfigChange?: (cfg: CouplingCfg) => void;
}) {
  const [cfg, setCfg] = useState<CouplingCfg>({
    enabled: true, invert: false, ratio: 1.0, offset: 0, center: 2048,
  });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  // Chargement initial. La case "Inverser" a ete retiree de l'UI (risque
  // inutile) : on neutralise toute valeur invert=true persistee en base.
  useEffect(() => {
    authFetch("/api/hardware/coupling")
      .then((r) => r.json())
      .then((c: CouplingCfg) => {
        const safe = { ...c, invert: false };
        setCfg(safe);
        setLoaded(true);
        onConfigChange?.(safe);
        if (c.invert) cmdSetCoupling(safe).catch(() => {});
      })
      .catch(() => setLoaded(true));
  }, []);

  const update = async (patch: Partial<CouplingCfg>) => {
    const next = { ...cfg, ...patch, invert: false };
    setCfg(next);
    setBusy(true);
    try {
      const res = await cmdSetCoupling(next);
      setCfg(res.coupling);
      onConfigChange?.(res.coupling);
    } catch (e) {
      setActionError(`couplage: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Couplage axe 2-3">
      {!loaded ? (
        <div className="text-text_dim font-ui text-control">Chargement...</div>
      ) : (
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" className="accent-amb" checked={cfg.enabled}
                   onChange={(e) => update({ enabled: e.target.checked })} />
            <span className="font-ui text-control text-text">Activer</span>
            {cfg.enabled && (
              <span className="ml-1 px-1.5 py-0.5 bg-ok/30 text-ok font-mono text-mono_sm rounded-xs">
                ACTIF
              </span>
            )}
          </label>
          <Field label="Ratio :">
            <input type="number" step="0.01" value={cfg.ratio}
                   onChange={(e) => update({ ratio: Number(e.target.value) })}
                   disabled={!cfg.enabled || busy}
                   className="w-full bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_md text-text disabled:opacity-50 focus:outline-none focus:border-amb" />
          </Field>
          <Field label="Offset :">
            <input type="number" step="1" value={cfg.offset}
                   onChange={(e) => update({ offset: Number(e.target.value) })}
                   disabled={!cfg.enabled || busy}
                   className="w-full bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_md text-text disabled:opacity-50 focus:outline-none focus:border-amb" />
          </Field>
          <Field label="Centre :">
            <input type="number" step="1" min={0} max={4095} value={cfg.center}
                   onChange={(e) => update({ center: Number(e.target.value) })}
                   disabled={!cfg.enabled || busy}
                   className="w-full bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_md text-text disabled:opacity-50 focus:outline-none focus:border-amb" />
          </Field>
          {busy && <span className="font-ui text-caption text-amb">Sauvegarde…</span>}
          <span className="font-ui text-caption text-text_dim ml-auto">
            Formule : <span className="font-mono text-text_med">pos₃ = centre + signe × ratio × (pos₂ − centre) + offset</span>
          </span>
        </div>
      )}
    </Section>
  );
}

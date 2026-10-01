// Page Capteurs & Actionneurs — câblée sur le backend Arduino.
import { useCallback, useEffect, useState } from "react";
import { useStore } from "../store";
import { Modal, ModalBtn } from "../components/Modal";
import { authFetch } from "../auth";
import { useLiveBus } from "../useLiveBus";
import type { WsMsg } from "../types";
import {
  cmdAddDevice, cmdDeleteDevice, cmdGetDevice, cmdConnectDevice, cmdDisconnectDevice,
  cmdSetActuator, cmdRunAction, cmdSendRaw, cmdSetRule, cmdListPorts,
  type DeviceRec, type DeviceLive, type PortRec,
} from "../commands";

type SubTab = "capteurs" | "actionneurs" | "actions" | "console";

function ToolbarBtn({ children, onClick, disabled, primary }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean; primary?: boolean;
}) {
  const tone = primary
    ? "bg-mag_dim2 text-amb border-mag/50 hover:bg-mag"
    : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2";
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className={`px-3 py-1.5 rounded-sm border font-ui text-control transition disabled:opacity-30 ${tone}`}>
      {children}
    </button>
  );
}

function AddDeviceDialog({ onClose, onSaved, onError }: {
  onClose: () => void; onSaved: () => void; onError: (msg: string) => void;
}) {
  const [name, setName] = useState("Arduino_1");
  const [ports, setPorts] = useState<PortRec[]>([]);
  const [port, setPort] = useState("");
  const [baud, setBaud] = useState(115200);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    cmdListPorts().then((r) => {
      setPorts(r.ports);
      const ard = r.ports.find((p) => p.is_arduino);
      setPort(ard ? ard.device : r.ports[0]?.device ?? "");
    }).catch(() => setPorts([]));
  }, []);

  const onAdd = async () => {
    setBusy(true);
    try { await cmdAddDevice(name, port, baud); onSaved(); onClose(); }
    catch (e) { onError(`device: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };

  return (
    <Modal title="➕ Ajouter un appareil Arduino" onClose={onClose} width={460}
      footer={<>
        <ModalBtn onClick={onClose}>Annuler</ModalBtn>
        <ModalBtn primary disabled={busy || !port} onClick={onAdd}>{busy ? "Ajout…" : "✓ Ajouter"}</ModalBtn>
      </>}>
      <div className="space-y-3">
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Nom :</label>
          <input type="text" autoFocus value={name} onChange={(e) => setName(e.target.value)}
            className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
        </div>
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Port :</label>
          <select value={port} onChange={(e) => setPort(e.target.value)}
            className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb">
            {ports.length === 0 && <option value="">Aucun port détecté</option>}
            {ports.map((p) => (
              <option key={p.device} value={p.device}>
                {p.device}{p.is_arduino ? "  ⚡ Arduino détecté" : ""}{p.description ? ` — ${p.description}` : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Baudrate :</label>
          <select value={baud} onChange={(e) => setBaud(Number(e.target.value))}
            className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb">
            {[9600, 19200, 38400, 57600, 115200, 230400].map((b) => (<option key={b} value={b}>{b}</option>))}
          </select>
        </div>
      </div>
    </Modal>
  );
}

export default function Capteurs() {
  const { setActionError } = useStore();
  const [tab, setTab] = useState<SubTab>("capteurs");
  const [addDlg, setAddDlg] = useState(false);
  const [devices, setDevices] = useState<DeviceRec[]>([]);
  const [selectedDev, setSelectedDev] = useState<string | null>(null);
  const [live, setLive] = useState<DeviceLive | null>(null);
  const [liveValues, setLiveValues] = useState<Record<string, number>>({});
  const [consoleLog, setConsoleLog] = useState<string[]>([]);
  const [rawInput, setRawInput] = useState("");
  const [seuilMin, setSeuilMin] = useState("");
  const [seuilMax, setSeuilMax] = useState("");
  const [selSensor, setSelSensor] = useState<string | null>(null);

  const refetchDevices = useCallback(() => {
    authFetch("/api/hardware").then((r) => r.json())
      .then((hw: { devices?: DeviceRec[] }) => setDevices(hw.devices ?? []))
      .catch(() => setDevices([]));
  }, []);
  useEffect(() => { refetchDevices(); }, [refetchDevices]);

  const refetchLive = useCallback(() => {
    if (!selectedDev) { setLive(null); return; }
    cmdGetDevice(selectedDev).then(setLive).catch(() => setLive(null));
  }, [selectedDev]);
  useEffect(() => { refetchLive(); }, [refetchLive]);
  useEffect(() => { setLiveValues({}); }, [selectedDev]);

  const selName = live?.name;
  useLiveBus(useCallback((msg: WsMsg) => {
    if (msg.topic === "arduino.sensors_tick" && selName) {
      const data = msg.data as Record<string, Record<string, number>>;
      if (data[selName]) setLiveValues(data[selName]);
    } else if (msg.topic === "arduino.identified" || msg.topic === "arduino.connected" ||
               msg.topic === "arduino.disconnected" || msg.topic === "arduino.error") {
      refetchLive();
    } else if (msg.topic === "sensor.alert") {
      const d = msg.data as { message?: string };
      setActionError(`⚠️ ${d.message ?? "Alerte capteur"}`);
    }
  }, [selName, refetchLive, setActionError]));

  const onConnect = async () => {
    if (!selectedDev) return;
    try { await cmdConnectDevice(selectedDev); setTimeout(refetchLive, 800); }
    catch (e) { setActionError(`connect: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const onDisconnect = async () => {
    if (!selectedDev) return;
    try { await cmdDisconnectDevice(selectedDev); refetchLive(); }
    catch (e) { setActionError(`disconnect: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const onDelete = async () => {
    if (!selectedDev || !window.confirm("Supprimer cet appareil ?")) return;
    try { await cmdDeleteDevice(selectedDev); setSelectedDev(null); refetchDevices(); }
    catch (e) { setActionError(`delete: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const onActuator = async (act: string, value: number) => {
    if (!selectedDev) return;
    try { await cmdSetActuator(selectedDev, act, value); refetchLive(); }
    catch (e) { setActionError(`actuator: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const onAction = async (action: string) => {
    if (!selectedDev) return;
    try { const r = await cmdRunAction(selectedDev, action); setConsoleLog((c) => [...c, `RUN ${action} → ${r.message}`]); }
    catch (e) { setActionError(`action: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const onRaw = async () => {
    if (!selectedDev || !rawInput.trim()) return;
    try { await cmdSendRaw(selectedDev, rawInput); setConsoleLog((c) => [...c, `→ ${rawInput}`]); setRawInput(""); }
    catch (e) { setActionError(`raw: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const onRule = async () => {
    if (!selectedDev || !selSensor) return;
    const mn = seuilMin === "" ? null : Number(seuilMin);
    const mx = seuilMax === "" ? null : Number(seuilMax);
    try { await cmdSetRule(selectedDev, selSensor, mn, mx); }
    catch (e) { setActionError(`rule: ${e instanceof Error ? e.message : String(e)}`); }
  };

  const subTabs: { id: SubTab; label: string; emoji: string }[] = [
    { id: "capteurs", label: "Capteurs", emoji: "📊" },
    { id: "actionneurs", label: "Actionneurs", emoji: "⚡" },
    { id: "actions", label: "Actions", emoji: "+" },
    { id: "console", label: "Console", emoji: "🖥" },
  ];

  return (
    <div className="h-full flex flex-col gap-2">
      <div className="bg-surface_hi border border-border rounded-sm px-3 py-2 flex items-center justify-between">
        <span className="font-display text-section text-ok">📡 Arduino USB — Capteurs & Actionneurs</span>
        <span className="font-mono text-mono_sm text-text_dim">{live?.firmware ? `fw ${live.firmware}` : "général"}</span>
      </div>

      <div className="grid grid-cols-12 gap-3 flex-1 min-h-0">
        <div className="col-span-4 bg-surface border border-border rounded-sm flex flex-col">
          <div className="px-3 py-1.5 font-ui text-section text-amb border-b border-border bg-surface_hi rounded-t-sm">Appareils</div>
          <div className="flex-1 p-3 overflow-auto">
            {devices.length === 0 ? (
              <div className="text-text_dim text-center py-8 font-ui text-control">Aucun appareil — clique ➕ pour en ajouter</div>
            ) : devices.map((d) => (
              <button key={d.id} type="button" onClick={() => setSelectedDev(d.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 mb-1 rounded-sm text-left transition border ${
                  selectedDev === d.id ? "bg-amb_dim2/40 border-amb/50" : "bg-surface_hi border-border hover:bg-mag_dim2"}`}>
                <span className={live && selectedDev === d.id && live.connected ? "text-ok" : "text-text_dim"}>📡</span>
                <span className="font-ui text-control text-text flex-1 truncate">{d.name}</span>
                <span className="font-mono text-mono_sm text-text_dim">{d.port}</span>
              </button>
            ))}
          </div>
          <div className="border-t border-border p-2 flex gap-2 justify-center flex-wrap">
            <ToolbarBtn onClick={onConnect} disabled={!selectedDev} primary>Connecter</ToolbarBtn>
            <ToolbarBtn onClick={onDisconnect} disabled={!selectedDev}>Déconnecter</ToolbarBtn>
            <ToolbarBtn onClick={onDelete} disabled={!selectedDev}>🗑</ToolbarBtn>
            <ToolbarBtn onClick={() => setAddDlg(true)}>➕</ToolbarBtn>
          </div>
          <div className="border-t border-border p-3 space-y-1 font-mono text-mono_sm text-text_dim">
            <div>Port : {live?.port ?? "—"}</div>
            <div>État : {live ? (live.connected ? (live.identified ? "🟢 identifié" : "🟡 connecté") : "⚪ déconnecté") : "—"}</div>
            {live?.error && <div className="text-err">⚠ {live.error}</div>}
          </div>
        </div>

        <div className="col-span-8 flex flex-col min-h-0">
          <div className="bg-surface_hi border border-border rounded-sm px-3 py-2 mb-2 font-ui text-control text-text_med">
            {live ? `${live.name} — ${live.connected ? "connecté" : "déconnecté"}` : "Sélectionnez un appareil →"}
          </div>
          <div className="flex gap-px bg-bg border-b border-border">
            {subTabs.map((t) => (
              <button key={t.id} type="button" onClick={() => setTab(t.id)}
                className={`px-4 py-2 font-ui text-control transition ${
                  tab === t.id ? "bg-surface text-text border-t border-x border-border rounded-t-sm relative" : "text-text_med hover:text-text"}`}>
                <span className="mr-2">{t.emoji}</span>{t.label}
              </button>
            ))}
          </div>
          <div className="flex-1 bg-surface border border-t-0 border-border rounded-b-sm p-4 overflow-auto">
            {tab === "capteurs" && (
              !live || live.channels.length === 0 ? (
                <div className="text-text_dim font-ui text-control">Aucun capteur. Connectez un appareil.</div>
              ) : (
                <div className="space-y-2">
                  {live.channels.map((c) => {
                    const v = liveValues[c.name] ?? c.value;
                    const pct = Math.max(0, Math.min(100, ((v - c.min_val) / (c.max_val - c.min_val || 1)) * 100));
                    return (
                      <button key={c.name} type="button" onClick={() => setSelSensor(c.name)}
                        className={`w-full text-left border rounded-sm p-2 ${selSensor === c.name ? "border-amb/50 bg-amb_dim2/20" : "border-border bg-surface_hi"}`}>
                        <div className="flex justify-between font-mono text-mono_md text-text">
                          <span>{c.name}</span><span className="text-ok">{v.toFixed(2)} {c.unit}</span>
                        </div>
                        <div className="h-1.5 bg-bg rounded mt-1"><div className="h-full bg-ok rounded" style={{ width: `${pct}%` }} /></div>
                      </button>
                    );
                  })}
                  <div className="border-t border-border pt-2 mt-2 font-ui text-caption text-text_med">
                    Alerte seuil {selSensor ? `(${selSensor})` : "(choisir un capteur)"} :
                    <div className="flex gap-2 mt-1">
                      <input placeholder="min" value={seuilMin} onChange={(e) => setSeuilMin(e.target.value)}
                        className="w-20 bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_sm text-text" />
                      <input placeholder="max" value={seuilMax} onChange={(e) => setSeuilMax(e.target.value)}
                        className="w-20 bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_sm text-text" />
                      <ToolbarBtn onClick={onRule} disabled={!selSensor}>Définir</ToolbarBtn>
                    </div>
                  </div>
                </div>
              )
            )}
            {tab === "actionneurs" && (
              !live || live.actuators.length === 0 ? (
                <div className="text-text_dim font-ui text-control">Aucun actionneur.</div>
              ) : (
                <div className="space-y-2">
                  {live.actuators.map((a) => (
                    <div key={a.name} className="flex items-center gap-3 border border-border rounded-sm p-2 bg-surface_hi">
                      <span className="font-mono text-mono_md text-text flex-1">{a.label || a.name}</span>
                      {a.kind === "relay" ? (
                        <ToolbarBtn primary={a.state_on} onClick={() => onActuator(a.name, a.state_on ? 0 : 1)}>
                          {a.state_on ? "ON" : "OFF"}
                        </ToolbarBtn>
                      ) : (
                        <input type="range" min={a.min_val} max={a.max_val} defaultValue={a.last_value}
                          onPointerUp={(e) => onActuator(a.name, Number((e.target as HTMLInputElement).value))}
                          onPointerCancel={(e) => onActuator(a.name, Number((e.target as HTMLInputElement).value))}
                          className="w-40" />
                      )}
                    </div>
                  ))}
                </div>
              )
            )}
            {tab === "actions" && (
              !live || live.actions.length === 0 ? (
                <div className="text-text_dim font-ui text-control">Aucune action.</div>
              ) : (
                <div className="space-y-2">
                  {live.actions.map((a) => (
                    <div key={a.name} className="flex items-center gap-3 border border-border rounded-sm p-2 bg-surface_hi">
                      <div className="flex-1">
                        <div className="font-mono text-mono_md text-text">{a.label || a.name}</div>
                        {a.description && <div className="font-ui text-caption text-text_dim">{a.description}</div>}
                      </div>
                      <ToolbarBtn primary onClick={() => onAction(a.name)}>▶ Lancer</ToolbarBtn>
                    </div>
                  ))}
                </div>
              )
            )}
            {tab === "console" && (
              <div className="flex flex-col h-full">
                <div className="flex-1 overflow-auto font-mono text-mono_sm text-text_dim bg-bg rounded-sm p-2 mb-2">
                  {consoleLog.length === 0 ? "—" : consoleLog.map((l, i) => <div key={i}>{l}</div>)}
                </div>
                <div className="flex gap-2">
                  <input value={rawInput} onChange={(e) => setRawInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") onRaw(); }}
                    placeholder="Commande brute…"
                    className="flex-1 bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_md text-text" />
                  <ToolbarBtn primary onClick={onRaw} disabled={!selectedDev}>Envoyer</ToolbarBtn>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {addDlg && <AddDeviceDialog onClose={() => setAddDlg(false)} onSaved={refetchDevices} onError={setActionError} />}
    </div>
  );
}

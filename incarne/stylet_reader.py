#!/usr/bin/env python3
"""Lecteur Wacom CTH-461 — SANS sudo, grab exclusif de TOUS les noeuds Wacom.

- Decouvre dynamiquement les noeuds event* de la Wacom (/proc/bus/input/devices).
- Prend chacun en exclusivite (EVIOCGRAB) : pendant le run, le bureau (labwc/
  Wayland) ne recoit plus RIEN de la tablette -> plus de curseur, plus de clic UI.
- Lit la position/pression depuis le noeud "Pen". Relache tout a la sortie.

Aucun sudo requis (amniort est dans le groupe input). Parsing input_event en
Python pur, pas de dependance evdev.
"""
import struct
import fcntl
import sys
import time
import re
import select
import signal

EVIOCGRAB = 0x40044590  # _IOW('E', 0x90, int) sur aarch64
EV_FMT = "llHHi"
EV_SIZE = struct.calcsize(EV_FMT)  # 24
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
ABS_X, ABS_Y, ABS_PRESSURE = 0x00, 0x01, 0x18
BTN_TOOL_PEN = 0x140  # proximite : 1 = stylet en portee (<1cm), 0 = hors-portee
BTN_TOUCH = 0x14A     # 1 = en contact (pression > 0)
SYN_REPORT = 0x00


def _eviocgkey(length: int) -> int:
    # _IOR('E', 0x18, length) : dir=READ(2), type='E'(0x45), nr=0x18
    return (2 << 30) | (length << 16) | (ord("E") << 8) | 0x18


def etat_stylet(prox: int, touch: int) -> str:
    """3 états à partir de la proximité (BTN_TOOL_PEN) et du contact (BTN_TOUCH)."""
    if not prox:
        return "HORS-PORTEE"
    if not touch:
        return "SURVOL"
    return "CONTACT"


def _bit(bitmask: bytes, code: int) -> int:
    i = code // 8
    return (bitmask[i] >> (code % 8)) & 1 if i < len(bitmask) else 0


def etat_initial_boutons(bitmask: bytes) -> tuple:
    """(prox, touch) depuis le bitmask EVIOCGKEY (BTN_TOOL_PEN / BTN_TOUCH)."""
    return _bit(bitmask, BTN_TOOL_PEN), _bit(bitmask, BTN_TOUCH)


import threading


class StyletLecteur:
    """Expose la dernière lecture Wacom (état + x/y/pression) à un process.

    Partie pure : `appliquer(etype, code, value)` met à jour l'état interne ;
    sur SYN_REPORT l'état est publié et `lecture()` en rend un instantané.
    `demarrer()`/`arreter()` gèrent le grab des nœuds + un thread de lecture
    (validés en live, Task 8)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._st = {"x": None, "y": None, "p": 0, "touch": 0, "prox": 0}
        self._publie = {"etat": "HORS-PORTEE", "x": None, "y": None, "p": 0}
        self._fds = {}
        self._pen_fd = None
        self._thread = None
        self._stop = threading.Event()

    def appliquer(self, etype: int, code: int, value: int) -> None:
        if etype == EV_ABS:
            if code == ABS_X:
                self._st["x"] = value
            elif code == ABS_Y:
                self._st["y"] = value
            elif code == ABS_PRESSURE:
                self._st["p"] = value
        elif etype == EV_KEY and code == BTN_TOUCH:
            self._st["touch"] = value
        elif etype == EV_KEY and code == BTN_TOOL_PEN:
            self._st["prox"] = value
        elif etype == EV_SYN and code == SYN_REPORT:
            etat = etat_stylet(self._st["prox"], self._st["touch"])
            with self._lock:
                self._publie = {"etat": etat, "x": self._st["x"],
                                "y": self._st["y"], "p": self._st["p"]}

    def lecture(self) -> dict:
        with self._lock:
            return dict(self._publie)

    def demarrer(self) -> None:
        nodes = find_wacom_nodes()
        for name, path in nodes:
            try:
                f = open(path, "rb")
            except OSError:
                continue
            try:
                fcntl.ioctl(f, EVIOCGRAB, 1)
            except OSError:
                pass
            self._fds[f.fileno()] = (f, name)
            if "pen" in name.lower():
                self._pen_fd = f.fileno()
        if self._pen_fd is None and self._fds:
            self._pen_fd = next(iter(self._fds))
        # État INITIAL des boutons (EVIOCGKEY) : sinon, si le stylet est déjà en
        # portée/contact au démarrage, les fronts BTN_* sont ratés (edge-triggered)
        # et l'état resterait figé sur HORS-PORTEE.
        if self._pen_fd is not None:
            try:
                pen_file = self._fds[self._pen_fd][0]
                buf = bytearray(96)
                fcntl.ioctl(pen_file, _eviocgkey(len(buf)), buf)
                prox, touch = etat_initial_boutons(bytes(buf))
                self._st["prox"], self._st["touch"] = prox, touch
                with self._lock:
                    self._publie = {"etat": etat_stylet(prox, touch),
                                    "x": None, "y": None, "p": 0}
            except OSError:
                pass
        self._thread = threading.Thread(target=self._boucle, daemon=True)
        self._thread.start()

    def _boucle(self) -> None:
        poller = select.poll()
        for fno in self._fds:
            poller.register(fno, select.POLLIN)
        while not self._stop.is_set():
            for fno, _ in poller.poll(200):
                f, _name = self._fds[fno]
                data = f.read(EV_SIZE)
                if not data or len(data) < EV_SIZE:
                    continue
                if fno != self._pen_fd:
                    continue
                _, _, etype, code, value = struct.unpack(EV_FMT, data)
                self.appliquer(etype, code, value)

    def arreter(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        for f, _name in self._fds.values():
            try:
                fcntl.ioctl(f, EVIOCGRAB, 0)
            except OSError:
                pass
            f.close()
        self._fds = {}


def find_wacom_nodes():
    """Renvoie [(name, /dev/input/eventN), ...] pour tous les noeuds Wacom."""
    nodes = []
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return nodes
    for b in blocks:
        if "wacom" not in b.lower():
            continue
        m = re.search(r'N: Name="([^"]*)"', b)
        name = m.group(1) if m else "?"
        h = re.search(r"H: Handlers=(.*)", b)
        if not h:
            continue
        for tok in h.group(1).split():
            if tok.startswith("event"):
                nodes.append((name, "/dev/input/" + tok))
    return nodes


def _stop(signum, frame):
    # SIGTERM/SIGINT -> remonte comme KeyboardInterrupt pour un arret propre
    # (relache du grab via le finally). Re-arme aussi SIGINT, neutralise par le
    # shell quand le script est lance en arriere-plan avec '&'.
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    nodes = find_wacom_nodes()
    if not nodes:
        print("ERREUR: aucun noeud Wacom trouve")
        return 2

    fds = {}       # fileno -> (file, name)
    pen_fd = None
    for name, path in nodes:
        try:
            f = open(path, "rb")
        except OSError as e:
            print("  ! ouverture impossible", path, e)
            continue
        try:
            fcntl.ioctl(f, EVIOCGRAB, 1)
            tag = "GRAB"
        except OSError as e:
            tag = "grab ECHOUE (%s)" % e
        fds[f.fileno()] = (f, name)
        print("  [%s] %-28s %s" % (tag, name, path))
        if "pen" in name.lower():
            pen_fd = f.fileno()

    if pen_fd is None and fds:
        pen_fd = next(iter(fds))   # repli: 1er noeud
    print("Tablette verrouillee pour le bureau. Lecture du Pen... (Ctrl-C)")

    st = {"x": None, "y": None, "p": 0, "touch": 0, "prox": 0}
    last = 0.0
    last_state = None
    poller = select.poll()
    for fno in fds:
        poller.register(fno, select.POLLIN)
    try:
        while True:
            for fno, _ in poller.poll():
                f, name = fds[fno]
                data = f.read(EV_SIZE)
                if not data or len(data) < EV_SIZE:
                    continue
                if fno != pen_fd:
                    continue   # autres noeuds: draines mais ignores
                _, _, etype, code, value = struct.unpack(EV_FMT, data)
                if etype == EV_ABS:
                    if code == ABS_X:
                        st["x"] = value
                    elif code == ABS_Y:
                        st["y"] = value
                    elif code == ABS_PRESSURE:
                        st["p"] = value
                elif etype == EV_KEY and code == BTN_TOUCH:
                    st["touch"] = value
                elif etype == EV_KEY and code == BTN_TOOL_PEN:
                    st["prox"] = value
                elif etype == EV_SYN and code == SYN_REPORT:
                    # 3 etats : hors-portee / survol / contact
                    state = etat_stylet(st["prox"], st["touch"])
                    now = time.time()
                    changed = (state != last_state)
                    if changed or (now - last >= 0.15):
                        if st["prox"] == 0:
                            print("[{:<11}] (stylet aveugle, plus de position)".format(state))
                        elif st["x"] is not None and st["y"] is not None:
                            print("[{:<11}] x={:>5}  y={:>5}  p={:>4}".format(
                                state, st["x"], st["y"], st["p"]))
                        last = now
                        last_state = state
    except KeyboardInterrupt:
        print("\n[stop] demande utilisateur")
    finally:
        for f, name in fds.values():
            try:
                fcntl.ioctl(f, EVIOCGRAB, 0)
            except OSError:
                pass
            f.close()
        print("[grab] tous les noeuds relaches — tablette rendue au bureau")
    return 0


if __name__ == "__main__":
    sys.exit(main())

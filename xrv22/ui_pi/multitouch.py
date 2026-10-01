"""
xrv22/ui_pi/multitouch.py
──────────────────────────
Dispatcher multi-touch pour Tkinter (qui ne route pas les touches simultanees
nativement). Lit /dev/input/event4 (ft5x06 sur Pi 7" officiel) en multi-touch
ABS_MT_*, et dispatche chaque slot vers un widget cible enregistre, en mode
press/drag/release.

Usage :
    dispatcher = MultiTouchDispatcher(root_tk)
    dispatcher.register(joystick_widget)   # apres place(), quand mappe
    dispatcher.start()

Le widget cible doit exposer :
    - _on_press(event)   : event.x, event.y locaux
    - _on_drag(event)    : event.x, event.y locaux
    - _on_release(event) : event ignore
"""
from __future__ import annotations

import threading
import tkinter as tk
from typing import List, Optional

try:
    import evdev
    from evdev import ecodes
    EVDEV_OK = True
except ImportError:
    EVDEV_OK = False

from xrv22.services.logger import get_logger

_LOG = get_logger("MultiTouch")


class _FakeEvent:
    """Mimick d'un evt Tk avec just .x, .y."""
    __slots__ = ("x", "y")

    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y


class MultiTouchDispatcher:
    """Dispatcher multi-touch hardware -> widgets Tk."""

    DEVICE_HINT = "ft5x06"

    def __init__(self, root: tk.Misc):
        self._root = root
        self._widgets: List[tk.Widget] = []
        self._slot_widget = {}     # slot -> widget en cours de drag
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def register(self, widget: tk.Widget) -> None:
        """Ajoute un widget au routing multi-touch."""
        if widget not in self._widgets:
            self._widgets.append(widget)

    def clear(self) -> None:
        """Vide la liste (au switch de robot)."""
        self._widgets.clear()
        self._slot_widget.clear()

    def start(self) -> None:
        if not EVDEV_OK or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    # ── Recherche du widget sous (x_global, y_global) ───────────────
    def _hit(self, x_global: int, y_global: int):
        """Renvoie (widget, lx, ly) si touch dans un widget,
        sinon (None, 0, 0). Utilise winfo_rootx/y/width/height (call Tk
        thread-safe en lecture pure)."""
        for w in self._widgets:
            try:
                wx = w.winfo_rootx()
                wy = w.winfo_rooty()
                ww = w.winfo_width()
                wh = w.winfo_height()
            except tk.TclError:
                continue
            if wx <= x_global <= wx + ww and wy <= y_global <= wy + wh:
                return w, x_global - wx, y_global - wy
        return None, 0, 0

    # ── Boucle evdev ────────────────────────────────────────────────
    def _find_device(self):
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
            except Exception:
                continue
            if self.DEVICE_HINT in d.name.lower():
                return d
            caps = d.capabilities()
            if (ecodes.EV_ABS in caps
                    and any(c == ecodes.ABS_MT_SLOT for c in caps[ecodes.EV_ABS])):
                return d
        return None

    def _dispatch_press(self, widget, lx, ly):
        try:
            widget._on_press(_FakeEvent(lx, ly))
        except Exception as exc:
            _LOG.warning("press dispatch : %s", exc)

    def _dispatch_drag(self, widget, lx, ly):
        try:
            widget._on_drag(_FakeEvent(lx, ly))
        except Exception as exc:
            _LOG.warning("drag dispatch : %s", exc)

    def _dispatch_release(self, widget):
        try:
            widget._on_release(_FakeEvent(0, 0))
        except Exception as exc:
            _LOG.warning("release dispatch : %s", exc)

    def _apply_abs_event(self, code, value, cur_slot,
                         slot_x, slot_y, slot_active) -> int:
        """Applique un événement EV_ABS aux dicts de slots. Retourne cur_slot."""
        if code == ecodes.ABS_MT_SLOT:
            return value
        if code == ecodes.ABS_MT_TRACKING_ID:
            slot_active[cur_slot] = (value != -1)
        elif code == ecodes.ABS_MT_POSITION_X:
            slot_x[cur_slot] = value
        elif code == ecodes.ABS_MT_POSITION_Y:
            slot_y[cur_slot] = value
        return cur_slot

    def _loop(self) -> None:
        dev = self._find_device()
        if dev is None:
            _LOG.warning("aucun ecran tactile multi-touch trouve")
            return
        _LOG.info("ecoute multi-touch sur %s (%s)", dev.path, dev.name)

        cur_slot = 0
        slot_x: dict[int, int] = {}
        slot_y: dict[int, int] = {}
        slot_active: dict[int, bool] = {}

        for ev in dev.read_loop():
            if self._stop.is_set():
                break
            if ev.type == ecodes.EV_ABS:
                cur_slot = self._apply_abs_event(
                    ev.code, ev.value, cur_slot, slot_x, slot_y, slot_active)
            elif ev.type == ecodes.EV_SYN and ev.code == ecodes.SYN_REPORT:
                self._process_slots(slot_x, slot_y, slot_active)

    def _handle_release_slots(self, active_slots) -> None:
        """Dispatch release pour les slots qui ne sont plus actifs."""
        for slot in list(self._slot_widget.keys()):
            if slot not in active_slots:
                widget = self._slot_widget.pop(slot)
                self._root.after(0, lambda w=widget: self._dispatch_release(w))

    def _handle_drag_slot(self, slot, x, y) -> None:
        """Dispatch drag sur le widget déjà bind à ce slot."""
        widget = self._slot_widget[slot]
        try:
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
        except tk.TclError:
            return
        lx = x - wx
        ly = y - wy
        self._root.after(0,
                         lambda w=widget, lx=lx, ly=ly:
                         self._dispatch_drag(w, lx, ly))

    def _handle_press_slot(self, slot, x, y) -> None:
        """Dispatch press : trouver le widget cible et le bind au slot."""
        widget, lx, ly = self._hit(x, y)
        if widget is None:
            return
        self._slot_widget[slot] = widget
        self._root.after(0,
                         lambda w=widget, lx=lx, ly=ly:
                         self._dispatch_press(w, lx, ly))

    def _process_slots(self, slot_x, slot_y, slot_active) -> None:
        """A chaque SYN, gère les transitions press/drag/release."""
        active_slots = {s for s, a in slot_active.items() if a}
        self._handle_release_slots(active_slots)
        for slot in active_slots:
            x = slot_x.get(slot)
            y = slot_y.get(slot)
            if x is None or y is None:
                continue
            if slot in self._slot_widget:
                self._handle_drag_slot(slot, x, y)
            else:
                self._handle_press_slot(slot, x, y)

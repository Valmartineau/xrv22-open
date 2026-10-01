"""
xrv22/main.py
──────────────
Point d'entree XRV22 PRO V22.

Ordre de demarrage :
  1. Logging (avant tout, avec library.logs_dir)
  2. Migration V21 si necessaire
  3. Chargement projet (dernier ouvert ou defaut)
  4. Watchdog
  5. UI Tkinter (thread principal)
  6. Shutdown propre a la sortie

Commandes :
  python -m xrv22.main                        # Mode normal
  python -m xrv22.main --sim                  # Mode simulation complet
  python -m xrv22.main --project mon.xrv22    # Ouvre un projet
  python -m xrv22.main --debug                # Logs verbeux

Architecture threading :
  Thread principal     -> Tkinter UI (mainloop)
  Thread Serial-{id}   -> un par robot (SerialManager)
  Thread HB-{id}       -> heartbeat par robot
  Thread Watchdog      -> WatchdogService._loop
  Thread Scheduler     -> EventScheduler (50ms)
  Thread Handler       -> un par event dispatche (daemon)
  Thread SimInterp     -> SimInterpolator (50ms, si --sim)
  Thread SimScene      -> capteurs fictifs (200ms, si --sim)
  Thread Arduino-{dev} -> un par Arduino connecte
"""
from __future__ import annotations

import argparse
import faulthandler
import logging
import os
import signal
import sys
import threading
import traceback

from xrv22.services.logger import setup_logging, get_logger
from xrv22.services.watchdog import watchdog
from xrv22.library.library_manager import library
from xrv22.core.state_store import store
from xrv22.services.project_service import project

_LOG = get_logger("Main")


def _install_crash_traps() -> None:
    """Route toutes les exceptions non-catchees vers le logger.

    Sans ces hooks, les crashes dans les threads daemon (scheduler, handlers
    timeline, serial) et dans les callbacks Tkinter sont silencieusement avales
    et n'apparaissent jamais dans xrv22.log.
    """
    crash_log = get_logger("CRASH")

    def _hook_main(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        crash_log.critical(
            "Exception non-catchee (main) :\n%s",
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )

    def _hook_thread(args):
        if issubclass(args.exc_type, SystemExit):
            return
        tname = args.thread.name if args.thread else "?"
        crash_log.critical(
            "Exception non-catchee (thread=%s) :\n%s",
            tname,
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )

    sys.excepthook = _hook_main
    threading.excepthook = _hook_thread

    # faulthandler : en cas de freeze (beachball), envoyer `kill -USR1 <pid>`
    # depuis un autre terminal dumpe les stacks Python de TOUS les threads
    # dans le log. Indispensable pour diagnostiquer les deadlocks.
    try:
        log_path = str(library.logs_dir / "xrv22.log")
        _fh_file = open(log_path, "a", buffering=1)
        faulthandler.enable(file=_fh_file)
        faulthandler.register(signal.SIGUSR1, file=_fh_file, all_threads=True)
        crash_log.info("faulthandler actif — kill -USR1 %d pour dumper les stacks", os.getpid())
    except Exception as exc:
        crash_log.warning("faulthandler KO : %s", exc)


def _install_tk_crash_trap(app) -> None:
    """Route les exceptions des callbacks Tkinter vers le logger."""
    crash_log = get_logger("CRASH")

    def _report(exc, val, tb):
        crash_log.critical(
            "Exception dans callback Tk :\n%s",
            "".join(traceback.format_exception(exc, val, tb)),
        )

    app.report_callback_exception = _report


def parse_args() -> argparse.Namespace:
    """Parse les arguments CLI."""
    p = argparse.ArgumentParser(
        description="XRV22 PRO V22 — Robot Control Station",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  python -m xrv22.main --sim\n"
            "  python -m xrv22.main --project ~/projets/demo.xrv22\n"
            "  python -m xrv22.main --sim --debug\n"
        )
    )
    p.add_argument("--sim",     action="store_true", help="Mode simulation complete")
    p.add_argument("--project", type=str, default="",
                   help="Chemin vers un fichier projet .xrv22")
    p.add_argument("--debug",   action="store_true", help="Niveau de log DEBUG")
    return p.parse_args()


def bootstrap(args: argparse.Namespace) -> None:
    """Initialise tous les services avant le lancement UI."""
    # 1. Logging — utilise le dossier logs de la librairie
    setup_logging(str(library.logs_dir), debug=args.debug)

    _LOG.info("======================================")
    _LOG.info("  XRV22 PRO V22 — Demarrage          ")
    _LOG.info("======================================")

    # 2. Migration V21 si necessaire
    from xrv22.library.migration import auto_migrate_if_needed
    rapport = auto_migrate_if_needed(library)
    if rapport:
        _LOG.info("Migration V21 -> V22 effectuee : "
                  "positions=%d, suites=%d, robots=%d",
                  rapport.get("positions_migrated", 0),
                  rapport.get("suites_migrated", 0),
                  rapport.get("robots_migrated", 0))
        for w in rapport.get("warnings", []):
            _LOG.warning("Migration : %s", w)

    # 3. Mode simulation
    store.set_system(simulation_mode=args.sim)
    if args.sim:
        _LOG.info("Mode simulation active")

    # 4. Chargement projet
    _bootstrap_project(args.project)

    # 5. Watchdog
    watchdog.start()
    _LOG.info("Watchdog demarre (timeout=1.5s)")


def _bootstrap_project(path: str) -> None:
    """Charge le projet demande, le dernier sauvegarde, ou cree un defaut."""
    # Projet specifie en argument
    if path:
        ok = project.load(path)
        if not ok:
            _LOG.warning("Projet introuvable : %s — projet vide cree", path)
            project.new_project("default")
        else:
            _LOG.info("Projet charge depuis argument : %s", path)
        return

    # Tente de charger le dernier projet ouvert
    params = library.get_startup_params()
    last_path = params.get("last_project_path", "")
    if last_path:
        ok = project.load(last_path)
        if ok:
            _LOG.info("Dernier projet restaure : %s", last_path)
            return
        _LOG.warning("Dernier projet introuvable : %s", last_path)

    # Tente le projet "default" existant dans la librairie
    default_proj = library.root / "projects" / "default" / "projet.xrv22"
    if default_proj.exists():
        ok = project.load(str(default_proj))
        if ok:
            _LOG.info("Projet par defaut restaure depuis %s", default_proj)
            return

    # Aucun projet existant — creation d'un nouveau
    project.new_project("default")
    _LOG.info("Nouveau projet par defaut cree")


def shutdown() -> None:
    """Arret propre de tous les services (engine → arduino → watchdog)."""
    _LOG.info("Arret XRV22 PRO...")
    # 1. Arrêter l'engine/scheduler en premier (stoppe timeline en cours)
    try:
        from xrv22.core.execution_engine import engine
        engine.stop()
    except Exception as exc:
        _LOG.debug("Engine shutdown : %s", exc)
    # 2. Arduino
    try:
        from xrv22.hardware.arduino_bridge import arduino
        arduino.disconnect_all()
    except Exception as exc:
        _LOG.debug("Arduino shutdown : %s", exc)
    # 3. Watchdog
    try:
        watchdog.stop()
    except Exception as exc:
        _LOG.debug("Watchdog shutdown : %s", exc)
    _LOG.info("Au revoir.")


def _run_headless() -> None:
    """Mode headless sans UI (tests/CI)."""
    import time
    _LOG.info("Mode headless — Ctrl+C pour quitter")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main() -> None:
    """Point d'entree principal."""
    args = parse_args()

    try:
        bootstrap(args)
    except Exception as exc:
        print(f"[FATAL] Erreur au demarrage : {exc}", file=sys.stderr)
        sys.exit(1)

    _install_crash_traps()

    try:
        from xrv22.ui.main_window import MainWindow
        app = MainWindow(simulation=args.sim)
        _install_tk_crash_trap(app)
        app.mainloop()
    except ImportError as exc:
        _LOG.warning("UI non disponible (%s) — mode headless", exc)
        _run_headless()
    except KeyboardInterrupt:
        _LOG.info("Interruption clavier")
    except Exception as exc:
        _LOG.exception("Erreur UI fatale : %s", exc)
    finally:
        shutdown()


if __name__ == "__main__":
    main()

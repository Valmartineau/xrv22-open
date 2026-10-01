"""Premier run d'observation INCARNÉ — boîte blanche (Mistral) sur le bras réel.

Diffère de `run_blanc.py` (corps factice) : ici le corps est le RXV22 réel, la
perception (signaux) vient de la tablette Wacom, et un garde-fou de pression
(~500) refuse tout geste qui appuierait au-delà du plafond mesuré live.

 on n'explique RIEN à la boîte blanche — manettes anonymes, signaux bruts, une
seule graine. Le garde-fou et l'instrumentation sont NOTRE échafaudage, invisibles
pour elle (la rétro-action ne lui rend que sa propre action, sans raison).

⚠ Mouvement réel : à lancer AVEC Valentin présent, main sur l'arrêt d'urgence.
Avant de lancer : ARRÊTER le verrou tablette (le harnais re-grab la Wacom).
L'axe 7 (pince) n'est JAMAIS exposé ni bougé (il tient le stylet).

    python3 -m incarne.run_incarne --pas 8 --delta-cap 2 --plafond 500
"""
from __future__ import annotations

from typing import Iterable, Optional

from incarne.corps.corps_nu import CorpsNu
from incarne.corps.corps_rxv22 import CorpsRxv22
from incarne.corps.perception import signaux_stylet


def payload_du_pas(pas: int, positions: dict, observation: dict,
                   decision: dict, resultat: dict, plafond: int) -> dict:
    """Assemble le dict d'un pas pour le moniteur Eddy (fonction PURE — pas de
    `ts`, ajouté à l'émission). `pression` = 3e signal (perception [x, y, p])."""
    action = decision["action"]
    signaux = list(observation.get("signaux", []))
    pression = int(signaux[2]) if len(signaux) >= 3 else 0
    return {
        "pas": pas,
        "positions": {str(k): int(v) for k, v in positions.items()},
        "manettes": list(observation.get("manettes", [])),
        "signaux": signaux,
        "pression": pression,
        "plafond": plafond,
        "manette_active": action["manette"],
        "delta": action["delta"],
        "pensee": decision.get("pensee", ""),
        "note": decision.get("note", ""),
        "bloque": bool(resultat.get("bloque")),
    }


def ecrire_journal(payload: dict, fichier) -> None:
    """Append une ligne JSON (un pas) au journal rejouable."""
    import json
    from pathlib import Path
    with open(Path(fichier), "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def rejouer(lignes, publier, dormir=None) -> None:
    """Rejoue un journal JSONL : publie chaque pas dans l'ordre, en respectant
    les deltas de `ts` (le 1er pas sans attente). NE TOUCHE NI STYLET NI ROBOT.
    `publier(payload)` est le seul exutoire ; `dormir(secondes)` injectable."""
    import json
    import time
    if dormir is None:
        dormir = time.sleep
    ts_prec = None
    for ligne in lignes:
        if not ligne.strip():
            continue
        payload = json.loads(ligne)
        ts = payload.get("ts")
        if ts_prec is not None and ts is not None:
            dormir(max(0.0, ts - ts_prec))
        publier(payload)
        if ts is not None:
            ts_prec = ts


def charger_position_protocole(fichier):
    """Lit position_protocole.json → (rid, {axe_int: ticks_int})."""
    import json
    from pathlib import Path
    data = json.loads(Path(fichier).read_text(encoding="utf-8"))
    rid = data.get("robot", "robot_1")
    positions = {int(k): int(v) for k, v in data["positions"].items()}
    return rid, positions


def construire_corps_incarne(client, rid: str, stylet,
                             axes: Iterable[int], delta_cap: int,
                             plafond_pression: int = 650,
                             dormir=None, observation: bool = False) -> CorpsRxv22:
    """Assemble le corps réel : perception (signaux) + garde-fou tolérant
    (post-geste + annulation) branchés sur le même StyletLecteur. En mode
    `observation`, agir() est passif (Eddy observe son corps bougé à la main)."""
    corps_nu = CorpsNu(axes, delta_cap=delta_cap)
    return CorpsRxv22(
        client, rid, corps_nu,
        lire_signaux=lambda: signaux_stylet(stylet.lecture()),
        lire_pression=lambda: stylet.lecture().get("p", 0),
        plafond_pression=plafond_pression, dormir=dormir, observation=observation)


import argparse
import sys
import tempfile
import time
from pathlib import Path

from incarne.boucle.boite_blanche import BoiteBlanche
from incarne.boucle.boucle import Boucle, GRAINE_DEFAUT
from incarne.boucle.carnet import Carnet
from incarne.messagerie import vider as vider_messages
from incarne.corps.mesure_securite import robot_pret, _token
from incarne.corps.rxv22_client import RxV22Client
from incarne.stylet_reader import StyletLecteur


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Premier run d'observation incarné réel")
    ap.add_argument("--robot", default="robot_1")
    ap.add_argument("--pas", type=int, default=8, help="nombre de pas d'observation")
    ap.add_argument("--modele", default="mistral-small3.2:24b")
    ap.add_argument("--temperature", type=float, default=None,
                    help="température Ollama (diversité d'exploration ; défaut modèle si absent)")
    ap.add_argument("--axes", default="1,2,3,4,5,6",
                    help="axes pilotables exposés en manettes anonymes (axe 7 exclu)")
    ap.add_argument("--delta-cap", type=int, default=2,
                    help="cap d'amplitude par pas (ticks) — petit car gradient ~130/tick")
    ap.add_argument("--axe-pression", type=int, default=5)
    ap.add_argument("--sens-pression", type=int, choices=[1, -1], default=-1)
    ap.add_argument("--plafond", type=int, default=500)
    ap.add_argument("--journal",
                    default=str(Path(tempfile.gettempdir()) / "eddy_run.jsonl"),
                    help="journal JSONL rejouable des pas")
    ap.add_argument("--rejouer", default=None,
                    help="rejoue un journal JSONL au lieu de piloter le robot")
    ap.add_argument("--position-depart",
                    default=str(Path(__file__).resolve().parent / "position_protocole.json"),
                    help="JSON de la pose de départ reproductible")
    ap.add_argument("--carnet",
                    default=str(Path.home() / "xrv22" / "XRV22_LIBRARY" / "eddy_carnet.txt"),
                    help="carnet d'Eddy — PERSISTANT entre runs par défaut (mémoire externalisée)")
    ap.add_argument("--reset-carnet", action="store_true",
                    help="repart d'un carnet vierge (sinon on CONTINUE le carnet précédent)")
    ap.add_argument("--observation", action="store_true",
                    help="run PASSIF : torque OFF, l'humain bouge le bras, Eddy observe "
                         "sans actionner (pas de torque/main/go-to ni écriture)")
    ap.add_argument("--graine", default=None,
                    help="consigne (graine) custom. Par défaut GRAINE_DEFAUT. "
                         "VARIANTE : déroge à « on n'explique rien » (ex. dire à Eddy "
                         "qu'une force extérieure le déplace).")
    ap.add_argument("--inbox",
                    default=str(Path.home() / "xrv22" / "XRV22_LIBRARY" / "eddy_inbox.txt"),
                    help="boîte aux lettres dialogue-en-mouvement : l'API y dépose "
                         "les messages de la personne, la boucle la vide à chaque pas.")
    args = ap.parse_args(argv)
    axes = [int(a) for a in args.axes.split(",") if a.strip()]

    if args.rejouer:
        client = RxV22Client("http://127.0.0.1:8080", token=_token())
        print(f"=== REPLAY {args.rejouer} (aucun mouvement robot) ===")
        with open(args.rejouer, encoding="utf-8") as f:
            rejouer(f.readlines(), publier=client.publier_eddy)
        return 0

    print("⚠ Run RÉEL : Valentin présent, main sur l'arrêt d'urgence.")
    print("  Vérifie que le VERROU tablette est arrêté (le harnais re-grab).\n")

    stylet = StyletLecteur()
    stylet.demarrer()
    try:
        client = RxV22Client("http://127.0.0.1:8080", token=_token())
        detail = client.get_robot(args.robot)
        if not detail.get("connected"):
            print("ABORT : robot non connecté")
            return 2
        if not args.observation:
            pret, raison = robot_pret(detail)
            if not pret:
                print("ABORT :", raison)
                return 2

        corps = construire_corps_incarne(
            client, args.robot, stylet, axes=axes, delta_cap=args.delta_cap,
            plafond_pression=args.plafond, observation=args.observation)

        if args.observation:
            print("=== MODE OBSERVATION : torque OFF, TU bouges le bras à la main, "
                  "Eddy observe (aucune écriture, aucun garde-fou). ===")
        else:
            # Pose de départ reproductible : torque ON + prise de main + go-to.
            # PRENDRE LA MAIN : sans owner de contrôle, les écritures de position
            # sont des no-op (le servo n'est pas piloté). Indispensable pour bouger.
            client.set_torque(args.robot, True)
            client.set_direct_mode(args.robot, True)
            rid_dep, pos_dep = charger_position_protocole(args.position_depart)
            client.write_positions(args.robot, pos_dep)
            print(f"→ position de départ ({rid_dep}) : {pos_dep}")
            time.sleep(1.0)  # laisse le bras atteindre la pose avant d'observer

        import threading
        _stop_stream = threading.Event()

        def _stream_stylet():
            while not _stop_stream.is_set():
                lec = stylet.lecture()
                try:
                    client.publier_stylet({"x": lec.get("x"), "y": lec.get("y"),
                                           "p": int(lec.get("p") or 0),
                                           "etat": lec.get("etat", "HORS-PORTEE")})
                except Exception:
                    pass  # le moniteur ne doit jamais bloquer le run
                time.sleep(0.04)  # ~25 Hz

        _th_stream = threading.Thread(target=_stream_stylet, daemon=True)
        _th_stream.start()

        carnet_path = Path(args.carnet)
        carnet_path.parent.mkdir(parents=True, exist_ok=True)
        if args.reset_carnet:
            carnet_path.unlink(missing_ok=True)   # repart vierge sur demande
        n_avant = len(Carnet(carnet_path).lignes())
        print(f"carnet : {carnet_path} ({n_avant} notes reprises)"
              if not args.reset_carnet else f"carnet : {carnet_path} (vierge)")
        boucle = Boucle(BoiteBlanche(model=args.modele, temperature=args.temperature),
                        Carnet(carnet_path), corps,
                        graine=args.graine or GRAINE_DEFAUT)

        print(f"=== Run incarné — {args.modele}, {args.pas} pas — axes {axes}, "
              f"cap {args.delta_cap}, plafond {args.plafond} ===\n")
        derniere: Optional[str] = None
        inbox = Path(args.inbox)
        vider_messages(inbox)  # repart propre : pas de message périmé d'un run passé
        for i in range(1, args.pas + 1):
            obs = corps.observe()
            print(f"[pas {i}] perçu : manettes {obs['manettes']} · signaux {obs['signaux']}")
            # Dialogue-en-mouvement : on vide la boîte aux lettres et on injecte
            # les messages de la personne dans le prompt de CE pas.
            msg_humain = " ".join(vider_messages(inbox)) or None
            if msg_humain:
                print(f"         💬 toi : {msg_humain}")
            try:
                r = boucle.pas(derniere_action=derniere, message_humain=msg_humain)
            except ValueError as e:
                print(f"         réponse non exploitable : {e}\n")
                continue
            a = r["action"]
            res = r["resultat"]
            # Moniteur Eddy : payload du pas → POST best-effort + journal JSONL.
            positions = client.get_robot(args.robot).get("positions", {})
            payload = payload_du_pas(i, positions, obs, r, res, plafond=args.plafond)
            payload["ts"] = time.time()
            payload["message_humain"] = msg_humain or ""
            payload["reponse"] = r.get("reponse", "")
            try:
                client.publier_eddy(payload)
            except Exception as e:  # le moniteur ne doit JAMAIS bloquer le bras
                print(f"         (moniteur indisponible : {e})")
            try:
                ecrire_journal(payload, args.journal)
            except OSError as e:
                print(f"         (journal indisponible : {e})")
            etat_geste = "BLOQUÉ (garde-fou)" if res.get("bloque") else res.get("raison", res)
            print(f"         pensée : {r['pensee']}")
            print(f"         action : manette {a['manette']}, delta {a['delta']} → {etat_geste}")
            print(f"         note   : {r['note']}")
            if r.get("reponse"):
                print(f"         💬 eddy : {r['reponse']}")
            print()
            derniere = f"manette {a['manette']}, delta {a['delta']}"
    finally:
        try:
            _stop_stream.set()
        except NameError:
            pass  # _stop_stream non créé si abort avant (robot_pret = False)
        try:
            client.set_direct_mode(args.robot, False)  # lâche la main
        except Exception:
            pass
        stylet.arreter()

    print("--- carnet final ---")
    for ligne in Carnet(Path(args.carnet)).lignes():
        print(f"  - {ligne}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# incarne/corps/mesure_securite.py
"""Harnais de mesure de la force d'échappement du stylet (descente micro-pas).

`mesurer()` descend UN axe par pas, attend la stabilisation, lit la pression,
journalise, et s'arrête via EvaluateurArret. Sur abort clavier, REMONTE le
stylet à sa position de départ (jamais de torque-off). Client RXV22 et stylet
injectés → testable sans matériel. Voir docs/recherche/2026-06-16-protocole-
mesure-securite.md.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Tuple


def robot_pret(detail: dict) -> Tuple[bool, Optional[str]]:
    """Garde de sécurité : on ne descend JAMAIS un bras qui n'est pas connecté
    et torque ON (sinon bras mou → chute sur la tablette). Rend (ok, raison)."""
    if not detail.get("connected"):
        return False, "robot non connecté"
    if not detail.get("torque_enabled"):
        return False, "torque OFF — arme le bras d'abord (torque ON + réconciliation)"
    return True, None


def mesurer(client, stylet, evaluateur, rid: str, axe: int, sens: int,
            pas: int, dwell: float = 0.4,
            dormir: Callable[[float], None] = time.sleep) -> Dict:
    """Descend `axe` de `sens*pas` ticks/pas jusqu'à un critère d'arrêt.
    Rend {arret, journal, position_finale}."""
    positions = {int(k): int(v) for k, v in client.get_robot(rid)["positions"].items()}
    if axe not in positions:
        return {"arret": f"axe {axe} absent de l'état robot",
                "journal": [], "position_finale": None}
    depart = positions[axe]
    position = depart
    descente = 0
    journal = []
    try:
        while True:
            position += sens * pas
            descente += pas
            client.write_positions(rid, {axe: position})
            dormir(dwell)
            lec = stylet.lecture()
            pression = lec["p"]
            en_portee = lec["etat"] != "HORS-PORTEE"
            journal.append({"pas": len(journal) + 1, "position": position,
                            "pression": pression, "etat": lec["etat"]})
            cont, raison = evaluateur.evaluer(pression, en_portee, descente)
            if not cont:
                return {"arret": raison, "journal": journal,
                        "position_finale": position}
    except KeyboardInterrupt:
        client.write_positions(rid, {axe: depart})  # remontée au départ
        return {"arret": "abort manuel — remontée au départ", "journal": journal,
                "position_finale": depart}


import argparse
import csv
import json
import sys
from pathlib import Path

from incarne.corps.arret_descente import EvaluateurArret
from incarne.corps.rxv22_client import RxV22Client
from incarne.stylet_reader import StyletLecteur


def verifier_depart(stylet):
    """Le stylet doit être au moins en SURVOL au départ (sinon on descend à
    l'aveugle). Rend (ok, raison)."""
    etat = stylet.lecture()["etat"]
    if etat == "HORS-PORTEE":
        return False, "stylet hors-portée au départ — repose-le en affleurement"
    return True, None


def _token() -> str:
    p = Path.home() / "xrv22" / "XRV22_LIBRARY" / "auth_token.json"
    return json.loads(p.read_text())["token"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mesure de la force d'échappement du stylet")
    ap.add_argument("--robot", default="robot_1")
    ap.add_argument("--axe", type=int, required=True, help="axe de descente (ex. 5)")
    ap.add_argument("--sens", type=int, choices=[1, -1], required=True)
    ap.add_argument("--pas", type=int, default=4)
    ap.add_argument("--dwell", type=float, default=0.4)
    ap.add_argument("--cap", type=int, default=700)
    ap.add_argument("--plateau", type=int, default=15)
    ap.add_argument("--descente-max", type=int, default=120)
    ap.add_argument("--csv", default="/tmp/mesure_echappement.csv")
    args = ap.parse_args(argv)

    stylet = StyletLecteur()
    stylet.demarrer()
    try:
        ok, raison = verifier_depart(stylet)
        if not ok:
            print("ABORT :", raison)
            return 2
        client = RxV22Client("http://127.0.0.1:8080", token=_token())
        detail = client.get_robot(args.robot)
        pret, raison = robot_pret(detail)
        if not pret:
            print("ABORT :", raison)
            return 2
        # réconciliation du goal (anti-sursaut) avant toute descente
        client.write_positions(
            args.robot, {int(k): int(v) for k, v in detail["positions"].items()})
        ev = EvaluateurArret(cap_pression=args.cap, plateau_delta=args.plateau,
                             descente_max=args.descente_max)
        print(f"Descente axe {args.axe} sens {args.sens:+d}, pas {args.pas} "
              f"(cap {args.cap}, max {args.descente_max}). Ctrl-C = remontée.")
        res = mesurer(client, stylet, ev, rid=args.robot, axe=args.axe,
                      sens=args.sens, pas=args.pas, dwell=args.dwell)
    finally:
        stylet.arreter()

    with open(args.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pas", "position", "pression", "etat"])
        w.writeheader()
        w.writerows(res["journal"])
    print(f"\nARRÊT : {res['arret']}")
    print(f"{len(res['journal'])} pas · position finale {res['position_finale']} "
          f"· CSV → {args.csv}")
    if res["journal"]:
        pmax = max(e["pression"] for e in res["journal"])
        print(f"pression max observée : {pmax}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

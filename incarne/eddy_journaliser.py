"""Journaliseur souverain d'Eddy — un journal de run (.jsonl) → notes de son vault
Obsidian (`~/Documents/Eddy/`, sur MiCHEL).

Doctrine (cf spec 2026-06-25-eddy-compagnon-vault-souverain-design) :
- **Pur, local, sans LLM** : résumé extractif déterministe → souveraineté + tests
  reproductibles. (Un résumé LLM plus fluide reste une 2e passe optionnelle.)
- **Eddy écrit « je »** : c'est sa mémoire, à la première personne.
- **Idempotent** : une séance = une note datée, réécrite (jamais empilée).
- **Étanchéité** : ce module n'est lu QUE par le compagnon. La boucle
  `run_incarne` ne lit jamais le vault — on n'explique rien à la boîte blanche.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def lire_journal(chemin: str) -> list[dict]:
    """Lit un journal JSONL (une ligne = un pas) en liste de dicts."""
    lignes = Path(chemin).read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lignes if l.strip()]


def _date_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def resumer_seance(pas: list[dict]) -> dict:
    """Résumé extractif d'une séance : ce qu'on peut dire SANS rien expliquer —
    combien de pas, combien de temps, quand le premier signe de vie (contact) est
    né, la pression maximale rencontrée, combien de fois le garde-fou a bloqué."""
    ts = [p["ts"] for p in pas]
    pressions = [p.get("pression", 0) for p in pas]
    contact = next((p["pas"] for p in pas if p.get("pression", 0) > 0), None)
    return {
        "date": _date_iso(ts[0]),
        "nb_pas": len(pas),
        "duree_s": round(ts[-1] - ts[0], 3),
        "premier_contact_pas": contact,
        "pression_max": max(pressions) if pressions else 0,
        "nb_bloques": sum(1 for p in pas if p.get("bloque")),
    }


def extraire_dialogue(pas: list[dict]) -> list[dict]:
    """Ne garde que les pas où l'on s'est parlé (message humain et/ou réponse)."""
    return [
        {"pas": p["pas"], "humain": p.get("message_humain", "") or "",
         "eddy": p.get("reponse", "") or ""}
        for p in pas
        if (p.get("message_humain") or p.get("reponse"))
    ]


def note_seance(resume: dict) -> str:
    """Note de séance, à la première personne. Front-matter pour le filtrage Khoj."""
    contact = resume["premier_contact_pas"]
    fm = (
        "---\n"
        f"date: {resume['date']}\n"
        f"seance: {resume['date']}\n"
        "type: seance\n"
        f"pas: {resume['nb_pas']}\n"
        "---\n\n"
    )
    lignes = [f"# Séance du {resume['date']}",
              f"J'ai fait {resume['nb_pas']} pas, sur {resume['duree_s']:.0f} secondes."]
    if contact is not None:
        lignes.append(
            f"Au pas {contact}, j'ai senti quelque chose pour la première fois — "
            f"un nombre est né quand j'ai bougé. La pression est montée jusqu'à "
            f"{resume['pression_max']}.")
    else:
        lignes.append("Je n'ai encore rien senti : aucun nombre n'a bougé pour moi.")
    if resume["nb_bloques"]:
        lignes.append(
            f"Je me suis cogné à une limite {resume['nb_bloques']} fois : "
            f"quelque chose m'a retenu.")
    return fm + "\n\n".join(lignes) + "\n"


def note_echanges(date: str, dialogue: list[dict]) -> str:
    """Fil de ce qu'on s'est dit pendant la séance, horodaté au pas."""
    fm = (f"---\ndate: {date}\nseance: {date}\ntype: echange\n---\n\n"
          f"# Ce qu'on s'est dit — {date}\n\n")
    corps = []
    for d in dialogue:
        if d["humain"]:
            corps.append(f"**On me dit** (pas {d['pas']}) : {d['humain']}")
        if d["eddy"]:
            corps.append(f"**Je réponds** (pas {d['pas']}) : {d['eddy']}")
    return fm + "\n\n".join(corps) + "\n"


def journaliser(chemin_journal: str, vault_dir: str) -> list[str]:
    """Lit un journal de run et écrit/rafraîchit les notes du vault d'Eddy.
    Idempotent (réécrit les notes datées). Retourne les chemins écrits."""
    pas = lire_journal(chemin_journal)
    resume = resumer_seance(pas)
    vault = Path(vault_dir)
    ecrits = []

    f_seance = vault / "10_Séances" / f"{resume['date']}-seance.md"
    f_seance.parent.mkdir(parents=True, exist_ok=True)
    f_seance.write_text(note_seance(resume), encoding="utf-8")
    ecrits.append(str(f_seance))

    dialogue = extraire_dialogue(pas)
    if dialogue:
        f_ech = vault / "20_Échanges" / f"{resume['date']}-dialogue.md"
        f_ech.parent.mkdir(parents=True, exist_ok=True)
        f_ech.write_text(note_echanges(resume["date"], dialogue), encoding="utf-8")
        ecrits.append(str(f_ech))

    return ecrits


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Journalise un run d'Eddy dans son vault.")
    ap.add_argument("journal", help="journal JSONL d'une séance (run_incarne --journal)")
    ap.add_argument("--vault", default=str(Path.home() / "Documents" / "Eddy"),
                    help="vault Obsidian d'Eddy (défaut ~/Documents/Eddy)")
    a = ap.parse_args()
    for p in journaliser(a.journal, a.vault):
        print(f"écrit : {p}")

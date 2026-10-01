"""Journaliseur souverain d'Eddy : un journal de run (.jsonl) → notes du vault
Obsidian d'Eddy (`~/Documents/Eddy/`). Pur, sans réseau, sans LLM (souveraineté +
tests déterministes). Eddy écrit à la première personne (« je »). Idempotent :
rejouer le même journal n'empile pas de notes.

Voir spec `docs/superpowers/specs/2026-06-25-eddy-compagnon-vault-souverain-design.md`.
"""
from incarne.eddy_journaliser import (
    resumer_seance, extraire_dialogue, note_seance, journaliser,
)

# Base temporelle réelle (epoch) → 2026-06-16 12:30:00Z en UTC.
TS0 = 1781613000.0


def _pas(pas, ts, pression=0, bloque=False, message_humain="", reponse=""):
    return {
        "pas": pas, "positions": {"1": 2048}, "manettes": [2048],
        "signaux": [0, 0, pression], "pression": pression, "plafond": 500,
        "manette_active": 0, "delta": 2, "pensee": "p", "note": "n",
        "bloque": bloque, "ts": ts,
        "message_humain": message_humain, "reponse": reponse,
    }


def test_resumer_seance_compte_pas_duree_et_date():
    pas = [_pas(1, TS0), _pas(2, TS0 + 2.5), _pas(3, TS0 + 5.0)]
    r = resumer_seance(pas)
    assert r["nb_pas"] == 3
    assert r["duree_s"] == 5.0
    assert r["date"] == "2026-06-16"


def test_resumer_seance_detecte_le_signe_de_vie():
    # Le premier pas où une pression naît = le premier « signe de vie » (contact).
    pas = [_pas(1, TS0), _pas(2, TS0 + 2), _pas(3, TS0 + 4, pression=12)]
    r = resumer_seance(pas)
    assert r["premier_contact_pas"] == 3
    assert r["pression_max"] == 12


def test_resumer_seance_sans_contact_ni_blocage():
    pas = [_pas(1, TS0), _pas(2, TS0 + 2)]
    r = resumer_seance(pas)
    assert r["premier_contact_pas"] is None
    assert r["pression_max"] == 0
    assert r["nb_bloques"] == 0


def test_resumer_seance_compte_les_blocages_du_garde_fou():
    pas = [_pas(1, TS0), _pas(2, TS0 + 2, bloque=True), _pas(3, TS0 + 4, bloque=True)]
    assert resumer_seance(pas)["nb_bloques"] == 2


def test_extraire_dialogue_ne_garde_que_les_pas_parles():
    pas = [
        _pas(1, TS0),
        _pas(2, TS0 + 2, message_humain="tu fais quoi ?", reponse="je cherche"),
        _pas(3, TS0 + 4, reponse="je pousse une manette"),
    ]
    d = extraire_dialogue(pas)
    assert d == [
        {"pas": 2, "humain": "tu fais quoi ?", "eddy": "je cherche"},
        {"pas": 3, "humain": "", "eddy": "je pousse une manette"},
    ]


def test_note_seance_parle_a_la_premiere_personne_avec_frontmatter():
    r = resumer_seance([_pas(1, TS0), _pas(2, TS0 + 4, pression=12)])
    note = note_seance(r)
    # front-matter Khoj
    assert note.startswith("---\n")
    assert "type: seance" in note
    assert "date: 2026-06-16" in note
    # première personne : Eddy dit « je »
    assert "J'ai" in note or "Je " in note or "j'ai" in note
    # le fait saillant (nombre de pas) est présent
    assert "2" in note


def test_journaliser_cree_les_notes_et_est_idempotent(tmp_path):
    journal = tmp_path / "run.jsonl"
    import json
    pas = [
        _pas(1, TS0),
        _pas(2, TS0 + 4, pression=12, message_humain="coucou", reponse="je sens un nombre"),
    ]
    journal.write_text("\n".join(json.dumps(p) for p in pas), encoding="utf-8")
    vault = tmp_path / "Eddy"

    ecrits1 = journaliser(str(journal), str(vault))
    seance = vault / "10_Séances" / "2026-06-16-seance.md"
    echanges = vault / "20_Échanges" / "2026-06-16-dialogue.md"
    assert seance.exists()
    assert echanges.exists()
    assert "je sens un nombre" in echanges.read_text(encoding="utf-8")

    # Rejouer le même journal : pas de doublon, mêmes fichiers.
    ecrits2 = journaliser(str(journal), str(vault))
    assert sorted(ecrits1) == sorted(ecrits2)
    seances = list((vault / "10_Séances").glob("*.md"))
    assert len(seances) == 1


def test_journaliser_sans_dialogue_n_ecrit_pas_de_note_echanges(tmp_path):
    journal = tmp_path / "run.jsonl"
    import json
    journal.write_text(json.dumps(_pas(1, TS0)), encoding="utf-8")
    vault = tmp_path / "Eddy"
    journaliser(str(journal), str(vault))
    assert (vault / "10_Séances" / "2026-06-16-seance.md").exists()
    assert not (vault / "20_Échanges").exists()

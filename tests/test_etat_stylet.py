# tests/test_etat_stylet.py
from incarne.stylet_reader import etat_stylet
from incarne.stylet_reader import etat_initial_boutons, BTN_TOOL_PEN, BTN_TOUCH


def _bitmask_avec(*codes):
    buf = bytearray(96)
    for c in codes:
        buf[c // 8] |= (1 << (c % 8))
    return bytes(buf)


def test_etat_initial_boutons_lit_le_bitmask():
    assert etat_initial_boutons(_bitmask_avec()) == (0, 0)
    assert etat_initial_boutons(_bitmask_avec(BTN_TOOL_PEN)) == (1, 0)
    assert etat_initial_boutons(_bitmask_avec(BTN_TOOL_PEN, BTN_TOUCH)) == (1, 1)
    assert etat_initial_boutons(_bitmask_avec(BTN_TOUCH)) == (0, 1)


def test_hors_portee_quand_prox_zero():
    assert etat_stylet(prox=0, touch=0) == "HORS-PORTEE"
    assert etat_stylet(prox=0, touch=1) == "HORS-PORTEE"  # prox prime


def test_survol_quand_en_portee_sans_contact():
    assert etat_stylet(prox=1, touch=0) == "SURVOL"


def test_contact_quand_en_portee_et_touch():
    assert etat_stylet(prox=1, touch=1) == "CONTACT"

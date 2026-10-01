#!/usr/bin/env python3
"""
provision_motor.py - Provisionner un moteur Dynamixel neuf sur le bus d'un robot XRV22.

Workflow :
  1. Resout le port U2D2 du robot cible via le mapping FTDI.
  2. Scan multi-baudrate (57600 / 115200 / 1M / 2M) pour trouver les moteurs presents.
  3. Identifie le moteur "orphelin" (= ID/baud different de la config attendue).
  4. Demande confirmation interactive.
  5. Reprogramme : ID=cible, Baudrate=1Mbps (EEPROM, Torque OFF prealable).
  6. Verifie en relisant au nouveau baud / nouvel ID.

A lancer sur le Pi APRES avoir arrete le service XRV22 :
    sudo systemctl stop xrv22  (si systemd) ou tuer le process
    python3 ~/xrv22/scripts/provision_motor.py --robot robot_2 --target-id 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from dynamixel_sdk import PortHandler, PacketHandler
except ImportError:
    print("ERREUR : dynamixel_sdk non installe. Lance dans le venv XRV22.")
    sys.exit(1)

PROTOCOL_VERSION = 2.0

# Registres Dynamixel X-series (EEPROM)
ADDR_ID = 7              # 1 byte
ADDR_BAUDRATE = 8        # 1 byte (code, pas la valeur)
ADDR_DRIVE_MODE = 10     # 1 byte
ADDR_TORQUE_ENABLE = 64  # 1 byte

# Codes baudrate (registre 8) pour X-series
BAUD_CODES = {
    9600: 0, 57600: 1, 115200: 2, 1_000_000: 3,
    2_000_000: 4, 3_000_000: 5, 4_000_000: 6, 4_500_000: 7,
}

# Baudrates qu'on tente lors du scan, du plus probable d'usine au plus rare
SCAN_BAUDRATES = [57600, 1_000_000, 115200, 2_000_000]

TARGET_BAUDRATE = 1_000_000

MAPPING_FILE = Path.home() / "xrv22/XRV22_LIBRARY/global/u2d2_mapping.json"
BY_ID_DIR = Path("/dev/serial/by-id")


def resolve_port(robot_id: str) -> str:
    """Trouve /dev/ttyUSBx du robot via le mapping FTDI -> robot_id."""
    if not MAPPING_FILE.exists():
        raise SystemExit(f"Mapping introuvable : {MAPPING_FILE}")
    mapping = json.loads(MAPPING_FILE.read_text())
    target_serial = next(
        (s for s, rid in mapping.items() if rid == robot_id), None)
    if not target_serial:
        raise SystemExit(f"robot_id '{robot_id}' absent du mapping.")
    if not BY_ID_DIR.exists():
        raise SystemExit(f"{BY_ID_DIR} introuvable (lance sur le Pi ?)")
    for symlink in BY_ID_DIR.iterdir():
        if target_serial in symlink.name:
            return str(symlink.resolve())
    raise SystemExit(
        f"U2D2 serial '{target_serial}' (={robot_id}) non branche.")


def scan_baud(port: str, baudrate: int, id_range=range(1, 21)) -> list[int]:
    """Ping chaque ID a un baudrate donne. Retourne la liste des IDs vivants."""
    ph = PortHandler(port)
    pk = PacketHandler(PROTOCOL_VERSION)
    if not ph.openPort():
        raise SystemExit(f"Impossible d'ouvrir {port}")
    if not ph.setBaudRate(baudrate):
        ph.closePort()
        raise SystemExit(f"Impossible de fixer baud={baudrate}")
    ph.setPacketTimeoutMillis(40)
    found = []
    for mid in id_range:
        _, result, _ = pk.ping(ph, mid)
        if result == 0:
            found.append(mid)
    ph.closePort()
    return found


def full_scan(port: str) -> dict[int, list[int]]:
    """Scan a chaque baudrate. Retourne {baud: [ids_trouves]}."""
    result = {}
    for baud in SCAN_BAUDRATES:
        print(f"  Scan @ {baud:>7} bps ... ", end="", flush=True)
        ids = scan_baud(port, baud)
        result[baud] = ids
        print(f"{len(ids)} moteur(s) : {ids}" if ids else "vide")
    return result


def write_byte(ph, pk, mid: int, addr: int, value: int, label: str) -> bool:
    result, err = pk.write1ByteTxRx(ph, mid, addr, value)
    if result != 0:
        print(f"  ECHEC {label} : {pk.getTxRxResult(result)}")
        return False
    if err != 0:
        print(f"  ECHEC {label} (err pkt) : {pk.getRxPacketError(err)}")
        return False
    print(f"  OK {label}")
    return True


def reprogram(port: str, found_baud: int, found_id: int,
              target_id: int, target_baud: int) -> bool:
    """Reecrit ID + Baudrate sur le moteur. Torque OFF prealable."""
    ph = PortHandler(port)
    pk = PacketHandler(PROTOCOL_VERSION)
    if not ph.openPort() or not ph.setBaudRate(found_baud):
        print(f"  Impossible d'ouvrir {port} @ {found_baud}")
        return False
    ph.setPacketTimeoutMillis(80)
    try:
        # 1. Torque OFF (obligatoire pour ecrire l'EEPROM)
        if not write_byte(ph, pk, found_id, ADDR_TORQUE_ENABLE, 0,
                          "Torque OFF"):
            return False
        # 2. ID (on garde l'ancien baud, l'ancien ID disparait apres)
        if target_id != found_id:
            if not write_byte(ph, pk, found_id, ADDR_ID, target_id, f"ID {found_id} -> {target_id}"):
                return False
            time.sleep(0.05)
        # 3. Baudrate (le moteur va switch de baud des l'ecriture)
        if target_baud != found_baud:
            code = BAUD_CODES[target_baud]
            # On utilise le nouvel ID (qu'on vient d'ecrire)
            if not write_byte(ph, pk, target_id, ADDR_BAUDRATE, code,
                              f"Baud {found_baud} -> {target_baud}"):
                return False
            time.sleep(0.1)
    finally:
        ph.closePort()
    return True


def verify(port: str, target_id: int, target_baud: int) -> bool:
    """Ping le moteur au nouvel ID / nouveau baud."""
    print(f"  Verification : ping ID={target_id} @ {target_baud} bps ... ",
          end="", flush=True)
    ph = PortHandler(port)
    pk = PacketHandler(PROTOCOL_VERSION)
    ph.openPort()
    ph.setBaudRate(target_baud)
    ph.setPacketTimeoutMillis(100)
    _, result, _ = pk.ping(ph, target_id)
    ph.closePort()
    ok = result == 0
    print("OK" if ok else f"ECHEC ({pk.getTxRxResult(result)})")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--robot", required=True,
                    help="robot_id cible (ex: robot_2)")
    ap.add_argument("--target-id", type=int, required=True,
                    help="ID Dynamixel a attribuer au moteur neuf")
    ap.add_argument("--expected-ids", type=int, nargs="*",
                    help="IDs deja attendus sur le bus a 1M (defaut: 1..7 sauf target-id)")
    ap.add_argument("--yes", action="store_true",
                    help="Sans confirmation interactive")
    args = ap.parse_args()

    expected = set(args.expected_ids) if args.expected_ids else set(range(1, 8))
    expected.discard(args.target_id)

    port = resolve_port(args.robot)
    print(f"\n[{args.robot}] Port U2D2 : {port}")
    print(f"IDs attendus deja en place @ 1Mbps : {sorted(expected)}")
    print(f"Cible : assigner ID={args.target_id} @ {TARGET_BAUDRATE} bps\n")

    print("=== SCAN BUS ===")
    scan = full_scan(port)

    # Cherche un moteur "orphelin" : present a un baud != 1M, ou ID inattendu
    candidates = []
    for baud, ids in scan.items():
        for mid in ids:
            is_orphan = (baud != TARGET_BAUDRATE) or (mid not in expected)
            if is_orphan:
                candidates.append((baud, mid))

    if not candidates:
        print("\nAucun moteur orphelin trouve. Verifie le cablage et l'alim.")
        sys.exit(2)

    if len(candidates) > 1:
        print(f"\n⚠  Plusieurs candidats orphelins : {candidates}")
        print("Debranche les autres ou specifie --expected-ids precisement.")
        sys.exit(3)

    found_baud, found_id = candidates[0]
    print(f"\n=== MOTEUR ORPHELIN DETECTE ===")
    print(f"  ID actuel  : {found_id}")
    print(f"  Baud actuel: {found_baud} bps")
    print(f"  → reprogrammer en ID={args.target_id} @ {TARGET_BAUDRATE} bps ?")
    if not args.yes:
        ans = input("  Confirmer ? [y/N] ").strip().lower()
        if ans != "y":
            print("Annule.")
            sys.exit(0)

    print("\n=== REPROGRAMMATION ===")
    if not reprogram(port, found_baud, found_id,
                     args.target_id, TARGET_BAUDRATE):
        print("\nReprogrammation echouee.")
        sys.exit(4)

    print("\n=== VERIFICATION ===")
    if not verify(port, args.target_id, TARGET_BAUDRATE):
        print("Echec : le moteur ne repond pas au nouvel ID/baud.")
        print("Power-cycle du robot peut etre necessaire.")
        sys.exit(5)

    print("\n✔  Provisioning OK.")
    print("Etapes suivantes :")
    print("  1. Redemarre le service XRV22 (auto-unification des gains + drive mode)")
    print("  2. Verifie dans les logs : 'Moteur 5 — Drive Mode = 0x04' + gains conformes")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
fix_motor_direction.py - Active le bit Reverse Direction d'un moteur Dynamixel.

Usage typique apres remplacement d'un moteur : un Dynamixel neuf sort
d'usine avec Drive Mode = 0x00. XRV22 active le bit Time-based Profile
(0x04) mais ne touche pas au bit Reverse Direction (0x01). Si l'axe
d'origine etait monte avec Reverse, le moteur neuf tournera a l'envers.

Le script :
  1. Resout le port U2D2 du robot via le mapping FTDI.
  2. Lit la position et le Drive Mode actuels du moteur.
  3. Affiche les valeurs avant/apres.
  4. Active Reverse Direction (Torque OFF puis ecriture 0x05).
  5. Verifie + affiche la nouvelle position registre.

⚠ La position registre va etre inversee (4095 - ancien). Il faudra
recalibrer home_machine et home_work depuis l'UI apres l'operation.

Le service XRV22 DOIT etre arrete :
    ssh pi 'pkill -f "python3.*xrv22.main_pi"'

Puis :
    python3 ~/xrv22/scripts/fix_motor_direction.py --robot robot_2 --motor 5
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
    print("ERREUR : dynamixel_sdk non installe.")
    sys.exit(1)

PROTOCOL_VERSION = 2.0
ADDR_DRIVE_MODE = 10
ADDR_TORQUE_ENABLE = 64
ADDR_PRESENT_POSITION = 132
BIT_REVERSE_DIRECTION = 0x01
BIT_TIME_BASED_PROFILE = 0x04
TARGET_BAUDRATE = 1_000_000

MAPPING_FILE = Path.home() / "xrv22/XRV22_LIBRARY/global/u2d2_mapping.json"
BY_ID_DIR = Path("/dev/serial/by-id")


def resolve_port(robot_id: str) -> str:
    mapping = json.loads(MAPPING_FILE.read_text())
    target_serial = next(
        (s for s, rid in mapping.items() if rid == robot_id), None)
    if not target_serial:
        raise SystemExit(f"robot_id '{robot_id}' absent du mapping.")
    for symlink in BY_ID_DIR.iterdir():
        if target_serial in symlink.name:
            return str(symlink.resolve())
    raise SystemExit(f"U2D2 serial '{target_serial}' non branche.")


def fmt_dm(value: int) -> str:
    parts = []
    if value & BIT_REVERSE_DIRECTION:
        parts.append("Reverse")
    if value & BIT_TIME_BASED_PROFILE:
        parts.append("Time-based")
    return f"0x{value:02X}" + (f" ({' + '.join(parts)})" if parts else " (rien)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--robot", required=True, help="ex: robot_2")
    ap.add_argument("--motor", type=int, required=True, help="ID Dynamixel cible (ex: 5)")
    ap.add_argument("--yes", action="store_true", help="Sans confirmation")
    args = ap.parse_args()

    port = resolve_port(args.robot)
    print(f"[{args.robot}] Port : {port}  /  Moteur cible : ID={args.motor}")

    ph = PortHandler(port)
    pk = PacketHandler(PROTOCOL_VERSION)
    if not ph.openPort():
        raise SystemExit(f"Impossible d'ouvrir {port}")
    if not ph.setBaudRate(TARGET_BAUDRATE):
        raise SystemExit(f"Impossible de fixer baud={TARGET_BAUDRATE}")
    ph.setPacketTimeoutMillis(80)

    try:
        # Lecture etat actuel
        dm, r, _ = pk.read1ByteTxRx(ph, args.motor, ADDR_DRIVE_MODE)
        if r != 0:
            raise SystemExit(f"Lecture Drive Mode echouee : {pk.getTxRxResult(r)}")
        pos, _, _ = pk.read4ByteTxRx(ph, args.motor, ADDR_PRESENT_POSITION)
        print(f"\nAvant :")
        print(f"  Drive Mode       : {fmt_dm(dm)}")
        print(f"  Present Position : {pos}")

        if dm & BIT_REVERSE_DIRECTION:
            print("\n✓ Reverse Direction deja actif. Rien a faire.")
            return

        new_dm = dm | BIT_REVERSE_DIRECTION
        print(f"\nApres : Drive Mode {fmt_dm(new_dm)}")
        print(f"  Estimation position registre apres toggle : ~{4095 - pos} (= 4095 - pos courante)")
        print(f"  ⚠ home_machine et home_work du robot devront etre recalibres.")
        if not args.yes:
            ans = input("\n  Confirmer l'ecriture ? [y/N] ").strip().lower()
            if ans != "y":
                print("Annule.")
                return

        # Torque OFF avant ecriture EEPROM
        pk.write1ByteTxRx(ph, args.motor, ADDR_TORQUE_ENABLE, 0)
        time.sleep(0.05)
        result, err = pk.write1ByteTxRx(ph, args.motor, ADDR_DRIVE_MODE, new_dm)
        if result != 0 or err != 0:
            raise SystemExit(f"Ecriture echouee : {pk.getTxRxResult(result)} / err={err}")
        print(f"\n✓ Drive Mode ecrit : {fmt_dm(new_dm)}")

        time.sleep(0.1)
        dm2, _, _ = pk.read1ByteTxRx(ph, args.motor, ADDR_DRIVE_MODE)
        pos2, _, _ = pk.read4ByteTxRx(ph, args.motor, ADDR_PRESENT_POSITION)
        print(f"\nVerification :")
        print(f"  Drive Mode (relu) : {fmt_dm(dm2)}")
        print(f"  Present Position  : {pos2}")
        if dm2 == new_dm:
            print("\n✓ Operation reussie. Etapes suivantes :")
            print("  1. Redemarre XRV22 : ssh -f pi 'DISPLAY=:0 /home/amniort/xrv22/run-xrv22.sh'")
            print("  2. Depuis l'UI : recalibre home_machine puis home_work")
            print("  3. Va a home_work et verifie le sens de rotation")
        else:
            print(f"\n⚠ Drive Mode relu = {dm2:#04X} ≠ attendu {new_dm:#04X}")

    finally:
        ph.closePort()


if __name__ == "__main__":
    main()

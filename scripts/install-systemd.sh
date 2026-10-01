#!/usr/bin/env bash
# Installe le service systemd xrv22 sur le Pi.
# A executer SUR le Pi (sudo requis), une seule fois.
set -euo pipefail

SERVICE_SRC="/home/amniort/xrv22/scripts/xrv22.service"
SERVICE_DST="/etc/systemd/system/xrv22.service"

if [[ ! -f "$SERVICE_SRC" ]]; then
    echo "Erreur : $SERVICE_SRC introuvable"
    exit 1
fi

sudo install -m 644 "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable xrv22.service
echo "Service installe et active au boot."
echo
echo "Commandes utiles :"
echo "  sudo systemctl start xrv22       # demarrer maintenant"
echo "  sudo systemctl stop xrv22        # arreter"
echo "  sudo systemctl restart xrv22     # redemarrer"
echo "  sudo systemctl status xrv22      # etat"
echo "  journalctl -u xrv22 -f           # logs en direct"
echo "  journalctl -u xrv22 --since '5min ago'"

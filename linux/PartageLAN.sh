#!/usr/bin/env bash
# PartageLAN.sh — lanceur double-clic : installe au premier lancement (install.sh),
# puis démarre l'app de fond en silencieux. Une seule instance à la fois :
# si l'app tourne déjà, ce lancement lui fait simplement ouvrir sa fenêtre.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
if [ ! -x .venv/bin/python3 ]; then
    exec ./install.sh
fi
nohup .venv/bin/python3 "$PWD/partagelan_tray.py" >/dev/null 2>&1 &
disown
echo "PartageLAN lancé (icône dans la zone de notification)."

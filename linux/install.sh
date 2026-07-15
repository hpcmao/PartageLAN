#!/usr/bin/env bash
# install.sh — installation de PartageLAN pour Linux (haikubuntu). Un seul geste :
#   ./install.sh
#  1. paquets système manquants (python3-tk, xclip, python3-venv) via apt (sudo)
#  2. environnement Python .venv + pystray/pillow/tkinterdnd2 (pip, sans sudo)
#  3. lanceur (menu Applications) + démarrage automatique (~/.config/autostart)
#  4. pare-feu ufw : ouverture du port 7365 (sudo)
#  5. lancement de l'app de fond
# Sans sudo disponible, les étapes 1 et 4 affichent la commande à lancer
# (profils « Install » et « Admin » dans SudoManager) et le reste s'installe.

cd "$(dirname "$(readlink -f "$0")")" || exit 1
DIR="$PWD"
PY=python3

echo "== PartageLAN — installation Linux ($DIR) =="

# --- 1. paquets système ---
NEED=()
"$PY" -c "import tkinter" 2>/dev/null || NEED+=("python3-tk")
command -v xclip >/dev/null 2>&1 || NEED+=("xclip")
"$PY" -m venv --help >/dev/null 2>&1 || NEED+=("python3-venv")
if [ ${#NEED[@]} -gt 0 ]; then
    echo "Paquets à installer : ${NEED[*]}"
    if sudo -n true 2>/dev/null; then
        sudo apt-get install -y "${NEED[@]}"
    elif [ -t 0 ]; then
        echo "(mot de passe sudo requis — ou active le profil « Install » dans SudoManager)"
        sudo apt-get install -y "${NEED[@]}" || \
            echo "✗ apt impossible — installe à la main : sudo apt install ${NEED[*]}"
    else
        echo "✗ sudo indisponible ici. Active le profil « Install » dans SudoManager puis relance,"
        echo "  ou installe à la main :  sudo apt install ${NEED[*]}"
    fi
fi

# --- 2. venv + dépendances Python ---
if [ ! -x .venv/bin/python3 ]; then
    "$PY" -m venv --system-site-packages .venv || exit 1
fi
.venv/bin/pip install --quiet --upgrade pip >/dev/null 2>&1
.venv/bin/pip install --quiet --upgrade pystray pillow tkinterdnd2 || {
    echo "✗ Échec pip (réseau ?)"; exit 1; }
echo "✓ Environnement Python prêt (.venv)"

# --- 3. icône + lanceurs .desktop ---
.venv/bin/python3 - <<'EOF' 2>/dev/null || true
from PIL import Image, ImageDraw
img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([2, 2, 61, 61], radius=14, fill=(36, 105, 178, 255))
w = (255, 255, 255, 255)
d.line([15, 25, 43, 25], fill=w, width=5)
d.polygon([(43, 17), (55, 25), (43, 33)], fill=w)
d.line([21, 41, 49, 41], fill=w, width=5)
d.polygon([(21, 33), (9, 41), (21, 49)], fill=w)
img.save("icon.png")
EOF
ICON="network-workgroup"
[ -f "$DIR/icon.png" ] && ICON="$DIR/icon.png"
APPS="$HOME/.local/share/applications"
AUTO="$HOME/.config/autostart"
mkdir -p "$APPS" "$AUTO"
cat > "$APPS/PartageLAN.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PartageLAN
Comment=Presse-papier partagé + copie de fichiers (LAN)
Exec=$DIR/.venv/bin/python3 $DIR/partagelan_tray.py
Icon=$ICON
Terminal=false
Categories=Network;Utility;
EOF
cp "$APPS/PartageLAN.desktop" "$AUTO/PartageLAN.desktop"
cat >> "$AUTO/PartageLAN.desktop" <<'EOF'
X-GNOME-Autostart-enabled=true
X-MATE-Autostart-Delay=3
EOF
echo "✓ Lanceur (menu Applications) et démarrage automatique installés"

# --- 4. pare-feu (ufw) ---
if systemctl is-active --quiet ufw 2>/dev/null; then
    if sudo -n true 2>/dev/null; then
        sudo ufw allow 7365/tcp comment 'PartageLAN' >/dev/null \
            && echo "✓ Pare-feu : port 7365 ouvert"
    elif [ -t 0 ]; then
        echo "(ouverture du port 7365 — mot de passe sudo, ou profil « Admin » dans SudoManager)"
        sudo ufw allow 7365/tcp comment 'PartageLAN' \
            || echo "✗ À faire : sudo ufw allow 7365/tcp comment 'PartageLAN'"
    else
        echo "⚠ ufw actif : ouvre le port 7365 —  sudo ufw allow 7365/tcp comment 'PartageLAN'"
    fi
fi

# --- 5. lancement ---
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    pkill -f "$DIR/partagelan_tray.py" 2>/dev/null && sleep 0.5
    nohup .venv/bin/python3 "$DIR/partagelan_tray.py" >/dev/null 2>&1 &
    disown
    echo "✓ PartageLAN lancé — icône ⬅➡ dans la zone de notification."
else
    echo "Pas de session graphique : lance ensuite ./PartageLAN.sh"
fi

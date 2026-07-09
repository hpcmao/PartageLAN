#!/bin/zsh
# PartageLAN.command — double-cliquer pour installer/mettre à jour, compiler et lancer PartageLAN.
# - Si ce script est DANS le dépôt : il le met à jour (git pull) puis compile.
# - Si ce script est seul (téléchargé à part) : il clone le dépôt dans ~/PartageLAN.
set -e

REPO_URL="https://github.com/hpcmao/PartageLAN.git"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== PartageLAN — installation / mise à jour ==="

if ! xcode-select -p >/dev/null 2>&1; then
    echo "⚠️  Outils de développement absents."
    echo "   Lancer d'abord :  xcode-select --install   puis relancer ce script."
    read -r "?Appuyez sur Entrée pour fermer…"
    exit 1
fi

if [[ -f "$SCRIPT_DIR/Package.swift" ]]; then
    REPO="$SCRIPT_DIR"
elif [[ -f "$HOME/.partagelan_repo" && -d "$(cat "$HOME/.partagelan_repo")/.git" ]]; then
    REPO="$(cat "$HOME/.partagelan_repo")"   # dépôt mémorisé lors d'un passage précédent
else
    REPO="$HOME/PartageLAN"
fi

if [[ ! -d "$REPO" ]]; then
    echo "→ Clonage dans $REPO…"
    git clone "$REPO_URL" "$REPO"
elif [[ -d "$REPO/.git" ]]; then
    echo "→ Mise à jour de $REPO…"
    git -C "$REPO" pull --ff-only || echo "   (mise à jour impossible, compilation de la version locale)"
fi

cd "$REPO"
echo "$REPO" > "$HOME/.partagelan_repo"

echo "→ Certificat de signature stable (si absent)…"
./setup_signing.sh

echo "→ Compilation…"
./build_app.sh

echo "→ Installation dans /Applications…"
pkill -x PartageLAN 2>/dev/null || true
sleep 1
rm -rf /Applications/PartageLAN.app
cp -R dist/PartageLAN.app /Applications/
cp -f "$REPO/PartageLAN.command" /Applications/PartageLAN.command
chmod +x /Applications/PartageLAN.command

echo "→ Lancement automatique au démarrage (LaunchAgent)…"
AGENT="$HOME/Library/LaunchAgents/fr.vemao.partagelan.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$AGENT" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>fr.vemao.partagelan</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>/Applications/PartageLAN.app</string>
    </array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/fr.vemao.partagelan" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT" 2>/dev/null || true

echo "→ Lancement…"
open /Applications/PartageLAN.app

echo ""
echo "✓ PartageLAN est à jour, lancé (port 7365) et se lancera à chaque démarrage."
echo "  (Mise à jour future : double-clic sur /Applications/PartageLAN.command)"
read -r "?Appuyez sur Entrée pour fermer cette fenêtre…"

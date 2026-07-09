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
echo "→ Compilation…"
./build_app.sh

echo "→ Installation dans /Applications…"
pkill -x PartageLAN 2>/dev/null || true
sleep 1
rm -rf /Applications/PartageLAN.app
cp -R dist/PartageLAN.app /Applications/

echo "→ Lancement…"
open /Applications/PartageLAN.app

echo ""
echo "✓ PartageLAN est à jour et lancé (port 7365)."
read -r "?Appuyez sur Entrée pour fermer cette fenêtre…"

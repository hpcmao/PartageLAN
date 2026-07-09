#!/bin/zsh
# Fabrique PartageLAN.app (binaire universel Intel + Apple Silicon) + un zip prêt à copier.
set -e
cd "$(dirname "$0")"

swift build -c release --arch arm64 --arch x86_64

APP="dist/PartageLAN.app"
rm -rf dist
mkdir -p "$APP/Contents/MacOS"
cp ".build/apple/Products/Release/PartageLAN" "$APP/Contents/MacOS/PartageLAN"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>PartageLAN</string>
    <key>CFBundleIdentifier</key><string>fr.vemao.partagelan</string>
    <key>CFBundleName</key><string>PartageLAN</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSMinimumSystemVersion</key><string>15.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>LSUIElement</key><true/>
</dict>
</plist>
EOF

# Signature stable si le certif auto-signé est présent (Little Snitch/Gatekeeper gardent
# leurs règles entre rebuilds) ; sinon repli sur ad-hoc.
IDENTITY="PartageLAN Self-Signed"
if security find-identity -p codesigning 2>/dev/null | grep -q "$IDENTITY"; then
    codesign --force -s "$IDENTITY" "$APP"
    echo "Signé avec « $IDENTITY » (signature stable)."
else
    echo "⚠️  Certificat « $IDENTITY » absent → signature ad-hoc."
    echo "   Créez-le une fois avec ./setup_signing.sh pour éviter que Little Snitch redemande à chaque build."
    codesign --force -s - "$APP"
fi
ditto -c -k --keepParent "$APP" dist/PartageLAN.zip
echo "OK → $APP  et  dist/PartageLAN.zip"

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
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

codesign --force -s - "$APP"
ditto -c -k --keepParent "$APP" dist/PartageLAN.zip
echo "OK → $APP  et  dist/PartageLAN.zip"

#!/bin/zsh
# Crée une fois par Mac un certificat de signature de code auto-signé STABLE.
# Objectif : garder une signature constante entre rebuilds → Little Snitch (et Gatekeeper)
# conservent leurs règles au lieu de re-demander une autorisation à chaque compilation.
#
# À exécuter une seule fois par machine (build_app.sh et PartageLAN.command l'appellent
# automatiquement). Idempotent : ne fait rien si le certificat existe déjà.
set -e

IDENTITY="PartageLAN Self-Signed"

if security find-identity -p codesigning 2>/dev/null | grep -q "$IDENTITY"; then
    echo "✓ Certificat « $IDENTITY » déjà présent."
    exit 0
fi

echo "→ Création du certificat « $IDENTITY »…"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Certificat X.509 auto-signé avec l'usage « code signing ».
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
    -days 3650 -subj "/CN=$IDENTITY" \
    -addext "basicConstraints=critical,CA:false" \
    -addext "keyUsage=critical,digitalSignature" \
    -addext "extendedKeyUsage=critical,codeSigning" 2>/dev/null

# PKCS12 en algos legacy, compatibles avec le trousseau macOS (sinon « MAC verification failed »).
# OpenSSL 3 (Homebrew) a besoin de -legacy ; LibreSSL (système macOS) le fait par défaut
# et ne connaît pas l'option → on ne l'ajoute que si openssl est bien OpenSSL 3.x.
if openssl version | grep -qi "^OpenSSL 3"; then
    LEGACY="-legacy"
else
    LEGACY=""
fi
openssl pkcs12 -export $LEGACY -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
    -out "$TMP/cert.p12" -passout pass:partagelan -name "$IDENTITY"

# -A : autorise les outils (dont codesign) à utiliser la clé.
security import "$TMP/cert.p12" -k "$HOME/Library/Keychains/login.keychain-db" \
    -P partagelan -T /usr/bin/codesign -A

echo "✓ Certificat créé et importé dans le trousseau login."
echo "  Au 1er build, macOS demandera d'autoriser codesign à utiliser la clé →"
echo "  cliquez « Toujours autoriser » (une seule fois)."

#!/usr/bin/env bash
# Create the release authority: a private key and a self-signed certificate.
#
#   tools/pki/new-ca.sh
#   tools/pki/new-ca.sh --no-passphrase      for tests only
#
# Do this once. The private key is prompted for a passphrase and should live
# offline afterwards; it is used only to issue certificates and revocation
# lists. The certificate (ca.crt) is public: copy it into the repository as
# src/insvmarkers/release_ca.pem so the app trusts it.
#
# Refuses to run if an authority already exists in PKI_DIR.
# shellcheck source=tools/pki/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

protect="-aes-256-cbc"
case "${1:-}" in
    "") ;;
    --no-passphrase) protect="" ;;
    *) die "usage: new-ca.sh [--no-passphrase]" ;;
esac

require_openssl3
[[ ! -e "$CA_KEY" && ! -e "$CA_CERT" ]] || die "an authority already exists in $PKI_DIR; nothing was changed"

umask 077
mkdir -p "$PKI_DIR"

# shellcheck disable=SC2086
openssl genpkey -algorithm ed25519 $protect -out "$CA_KEY"
openssl req -x509 -new -key "$CA_KEY" -days 7300 \
    -subj "/CN=Insta360 Markers Release CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$CA_CERT"
ensure_db

echo
echo "Created the release authority in $PKI_DIR"
openssl x509 -in "$CA_CERT" -noout -subject -enddate -fingerprint -sha256
echo
echo "Next:"
echo "  1. Keep $CA_KEY offline and back it up. Without it no certificate can be issued."
echo "  2. cp $CA_CERT $REPO_ROOT/src/insvmarkers/release_ca.pem"
echo "  3. tools/pki/issue-release-cert.sh"
echo "  4. tools/pki/gen-crl.sh          (the first revocation list, after the certificate)"

#!/usr/bin/env bash
# Shared setup for the release authority scripts. Sourced, never run.
#
# Environment (all optional):
#   PKI_DIR   where the authority lives          default: ~/release-keys
#   CA_KEY    the authority's private key        default: PKI_DIR/ca.key,
#                                                or PKI_DIR/ca.key.enc if that is what exists
#   CRL_OUT   where the revocation list is written
#                                                default: src/insvmarkers/release_crl.pem
#   CERT_OUT  where the release certificate is written (it is public)
#                                                default: tools/pki/release.crt
set -euo pipefail

PKI_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$PKI_LIB_DIR/../.." && pwd)"

export PKI_DIR="${PKI_DIR:-$HOME/release-keys}"
CA_CERT="$PKI_DIR/ca.crt"
CRL_OUT="${CRL_OUT:-$REPO_ROOT/src/insvmarkers/release_crl.pem}"
CERT_OUT="${CERT_OUT:-$REPO_ROOT/tools/pki/release.crt}"
CONF="$PKI_LIB_DIR/openssl-ca.cnf"

if [[ -z "${CA_KEY:-}" ]]; then
    if [[ ! -f "$PKI_DIR/ca.key" && -f "$PKI_DIR/ca.key.enc" ]]; then
        CA_KEY="$PKI_DIR/ca.key.enc"
    else
        CA_KEY="$PKI_DIR/ca.key"
    fi
fi
export CA_KEY

die() {
    echo "error: $*" >&2
    exit 1
}

# macOS ships LibreSSL, which lacks options these scripts use.
require_openssl3() {
    command -v openssl >/dev/null || die "openssl not found (try: nix-shell -p openssl)"
    openssl version | grep -q '^OpenSSL 3' \
        || die "OpenSSL 3 is required, found: $(openssl version). Try: nix-shell -p openssl, or brew install openssl"
}

require_authority() {
    [[ -f "$CA_CERT" ]] || die "no authority certificate at $CA_CERT (run new-ca.sh, or set PKI_DIR)"
    [[ -f "$CA_KEY" ]] || die "no authority key at $CA_KEY"
}

# The bookkeeping `openssl ca` needs. Safe to run repeatedly, and it adopts an
# authority that was made without it: the database starts empty.
ensure_db() {
    mkdir -p "$PKI_DIR/db/certs"
    [[ -f "$PKI_DIR/db/index.txt" ]] || : > "$PKI_DIR/db/index.txt"
    [[ -f "$PKI_DIR/db/serial" ]] || echo 1000 > "$PKI_DIR/db/serial"
    [[ -f "$PKI_DIR/db/crlnumber" ]] || echo 01 > "$PKI_DIR/db/crlnumber"
}

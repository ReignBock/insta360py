#!/usr/bin/env bash
# Issue a release signing key and certificate.
#
#   tools/pki/issue-release-cert.sh
#   tools/pki/issue-release-cert.sh --days 365
#
# Makes a fresh key, has the authority sign its certificate, and records the
# certificate in the authority's database so it can be revoked later. Files go
# to PKI_DIR/issued/<timestamp>/. Asks for the authority key's passphrase.
#
# What the release workflow needs, and where each part goes:
#   release.key  -> GitHub secret RELEASE_SIGNING_KEY. The only secret.
#   release.crt  -> tools/pki/release.crt in the repository. It is public, so
#                   this script copies it there; commit it.
# shellcheck source=tools/pki/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

days=1826
case "${1:-}" in
    "") ;;
    --days) days="${2:?--days needs a number}" ;;
    *) die "usage: issue-release-cert.sh [--days N]" ;;
esac
[[ "$days" =~ ^[0-9]+$ ]] || die "--days must be a whole number"

require_openssl3
require_authority
ensure_db

umask 077
# A timestamp and a random suffix, so two issues in one second cannot share a
# folder. mkdir without -p fails if it exists: a key is never overwritten.
mkdir -p "$PKI_DIR/issued"
out="$PKI_DIR/issued/$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 3)"
mkdir "$out"

openssl genpkey -algorithm ed25519 -out "$out/release.key"
openssl req -new -key "$out/release.key" -subj "/CN=Insta360 Markers Release" -out "$out/release.csr"
openssl ca -config "$CONF" -batch -notext -rand_serial -days "$days" \
    -in "$out/release.csr" -out "$out/release.crt"
rm -f "$out/release.csr"

openssl verify -CAfile "$CA_CERT" "$out/release.crt" >/dev/null || die "the new certificate does not verify"

# The certificate is public and belongs in the repository. This replaces the
# previous one, which no longer matches the key you are about to install.
mkdir -p "$(dirname "$CERT_OUT")"
cp "$out/release.crt" "$CERT_OUT"

serial="$(openssl x509 -in "$out/release.crt" -noout -serial | cut -d= -f2)"
echo
echo "Issued certificate, serial $serial:"
openssl x509 -in "$out/release.crt" -noout -subject -startdate -enddate
echo
echo "Files in $out:"
echo "  release.key   -> GitHub secret RELEASE_SIGNING_KEY (the only secret)"
echo "  release.crt   -> also copied to $CERT_OUT"
echo
echo "Next: put release.key in the secret, then commit and push $CERT_OUT."
echo "Until the secret is replaced, releases fail: the certificate no longer matches the old key."
echo
echo "To revoke it later: tools/pki/revoke-release-cert.sh $serial"

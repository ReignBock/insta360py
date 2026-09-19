#!/usr/bin/env bash
# Write the revocation list (CRL) for the authority.
#
#   tools/pki/gen-crl.sh
#   tools/pki/gen-crl.sh --days 90
#
# The list names every certificate revoked so far, is signed by the authority,
# and expires after --days (default 365). The app ignores an expired list, so
# reissue it before then. Commit the result: the app downloads it from the
# repository whenever it installs an update, and each release builds it in.
# Asks for the authority key's passphrase.
# shellcheck source=tools/pki/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

days=365
case "${1:-}" in
    "") ;;
    --days) days="${2:?--days needs a number}" ;;
    *) die "usage: gen-crl.sh [--days N]" ;;
esac
[[ "$days" =~ ^[0-9]+$ ]] || die "--days must be a whole number"

require_openssl3
require_authority
ensure_db

umask 022
mkdir -p "$(dirname "$CRL_OUT")"
openssl ca -config "$CONF" -gencrl -crldays "$days" -out "$CRL_OUT"

echo
echo "Wrote $CRL_OUT"
openssl crl -in "$CRL_OUT" -noout -crlnumber -lastupdate -nextupdate
echo "Revoked certificates: $(grep -c '^R' "$PKI_DIR/db/index.txt" || true)"
echo
echo "Commit and push it, and every install sees it at its next update."

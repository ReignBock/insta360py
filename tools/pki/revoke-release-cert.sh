#!/usr/bin/env bash
# Revoke a release certificate and write a new revocation list.
#
#   tools/pki/revoke-release-cert.sh SERIAL
#   tools/pki/revoke-release-cert.sh path/to/release.crt
#   tools/pki/revoke-release-cert.sh SERIAL --reason superseded
#
# Use it when a release key may have leaked. SERIAL is what issue-release-cert.sh
# printed, or what tools/pki/status.sh lists. The default reason is
# keyCompromise. Then:
#   1. commit the new src/insvmarkers/release_crl.pem and push it,
#   2. issue a new certificate with issue-release-cert.sh,
#   3. replace the two GitHub secrets and cut a new release.
# Apps refuse anything signed with the revoked certificate as soon as they see
# the new list. This does not touch versions already installed.
# shellcheck source=tools/pki/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

target="${1:?usage: revoke-release-cert.sh SERIAL|CERT_FILE [--reason WHY]}"
reason="keyCompromise"
if [[ "${2:-}" == "--reason" ]]; then
    reason="${3:?--reason needs a value}"
fi

require_openssl3
require_authority
ensure_db

if [[ -f "$target" ]]; then
    serial="$(openssl x509 -in "$target" -noout -serial | cut -d= -f2)"
else
    serial="$(tr '[:lower:]' '[:upper:]' <<<"$target")"
fi

record="$PKI_DIR/db/certs/$serial.pem"
[[ -f "$record" ]] || die "no certificate with serial $serial was issued by this authority (looked for $record)"

openssl ca -config "$CONF" -revoke "$record" -crl_reason "$reason"
echo "Revoked serial $serial ($reason)."

"$PKI_LIB_DIR/gen-crl.sh"

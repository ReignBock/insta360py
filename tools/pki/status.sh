#!/usr/bin/env bash
# List the certificates the authority has issued, and whether each is valid,
# revoked or expired.
#
#   tools/pki/status.sh
# shellcheck source=tools/pki/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ -f "$PKI_DIR/db/index.txt" ]] || die "no database in $PKI_DIR; nothing has been issued yet"

if [[ ! -s "$PKI_DIR/db/index.txt" ]]; then
    echo "No certificates issued yet."
    exit 0
fi

awk -F'\t' '{
    state = ($1 == "V") ? "valid  " : ($1 == "R") ? "REVOKED" : "expired"
    printf "%s  serial %s  expires 20%s-%s-%s  %s\n", state, $4, substr($2, 1, 2), substr($2, 3, 2), substr($2, 5, 2), $6
}' "$PKI_DIR/db/index.txt"

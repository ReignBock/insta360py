#!/usr/bin/env bash
# Build the macOS app and zip it for release.
#
#   tools/build-app.sh
#
# Produces dist-app/Insta360-Markers-<version>-<arch>.zip, where <arch> is
# arm64 or x86_64. Run it on a Mac: PyInstaller builds for the machine it runs
# on, so each architecture needs its own build.
#
# The app carries the release authority's certificate and the revocation list
# from src/insvmarkers (release_ca.pem, release_crl.pem), and checks every
# update against them. See tools/pki/README.md.
#
# The app is not signed with a developer certificate. PyInstaller applies an
# ad-hoc signature, which macOS accepts for running the app but not for
# skipping Gatekeeper's first-launch prompt on a downloaded copy.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "build the app on macOS" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f src/insvmarkers/release_ca.pem ]]; then
    echo "error: src/insvmarkers/release_ca.pem is missing, so the app could not trust any update" >&2
    exit 1
fi

if [[ ! -f src/insvmarkers/release_crl.pem ]]; then
    echo "warning: no release_crl.pem: this build starts with no revocation list and relies on downloading one" >&2
fi

rm -rf dist-app build-app
uv run --no-dev --extra gui --with pyinstaller pyinstaller \
    --noconfirm --distpath dist-app --workpath build-app tools/app.spec

VERSION="$(uv run --no-dev python -c 'from importlib.metadata import version; print(version("insta360py"))')"
ZIP="dist-app/Insta360-Markers-$VERSION-$(uname -m).zip"

# ditto keeps the bundle's symlinks and permissions; plain zip breaks them.
ditto -c -k --keepParent "dist-app/Insta360 Markers.app" "$ZIP"

echo "built $ZIP"

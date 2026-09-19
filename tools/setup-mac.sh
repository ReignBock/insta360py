#!/usr/bin/env bash
# Set up insvtools and insv-markers on macOS.
#
# Run from a checkout:
#   tools/setup-mac.sh          install the commands and the desktop app
#   tools/setup-mac.sh --dev    also set up the development environment
#
# The tools need Python 3.12 or newer and protobuf, nothing else. uv supplies
# both: it downloads a suitable Python when the system one is too old (macOS
# ships 3.9). The plain install needs no sudo and changes nothing outside uv's
# own directories and ~/.local/bin.
#
# The script also puts "Insta360 Markers" in ~/Applications, so the window opens
# from Finder or Spotlight with a double-click. That app is a small launcher
# for the installed tool; the standalone app on the releases page needs no
# script at all.
#
# ffmpeg is used only by two tests. --dev installs it through Homebrew, and
# installs Homebrew first when it is missing. Homebrew's installer runs sudo
# and prompts for your password.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV=0

for arg in "$@"; do
    case "$arg" in
        --dev) DEV=1 ;;
        -h|--help) sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "this script is for macOS; on other systems install uv and run 'uv tool install .'" >&2
    exit 1
fi

export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    echo "installing uv into ~/.local/bin"
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Find Homebrew on PATH or at its default prefix, installing it when absent.
ensure_brew() {
    local prefix
    for prefix in /opt/homebrew /usr/local; do
        if ! command -v brew >/dev/null 2>&1 && [[ -x "$prefix/bin/brew" ]]; then
            eval "$("$prefix/bin/brew" shellenv)"
        fi
    done
    if ! command -v brew >/dev/null 2>&1; then
        echo "installing Homebrew (needs sudo)"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        for prefix in /opt/homebrew /usr/local; do
            if [[ -x "$prefix/bin/brew" ]]; then
                eval "$("$prefix/bin/brew" shellenv)"
            fi
        done
    fi
}

# A minimal .app whose only job is to start the installed window. Finder
# gives apps a bare PATH, so the launcher names the tool by absolute path.
make_launcher() {
    local app="$HOME/Applications/Insta360 Markers.app"
    local tool
    tool="$(uv tool dir --bin)/insv-markers-gui"

    rm -rf "$app"
    mkdir -p "$app/Contents/MacOS"

    cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Insta360 Markers</string>
    <key>CFBundleDisplayName</key><string>Insta360 Markers</string>
    <key>CFBundleIdentifier</key><string>io.github.reignbock.insta360py.launcher</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

    printf '#!/bin/bash\nexec "%s" "$@"\n' "$tool" > "$app/Contents/MacOS/launcher"
    chmod +x "$app/Contents/MacOS/launcher"
    echo "created $app"
}

cd "$REPO_ROOT"

echo "installing insvtools, insv-markers and the window"
uv tool install --force --python ">=3.12" ".[gui]"
make_launcher

if [[ "$DEV" -eq 1 ]]; then
    echo "syncing the development environment"
    uv sync --extra dev
    if ! command -v ffmpeg >/dev/null 2>&1; then
        ensure_brew
        brew install ffmpeg
    fi
fi

echo
insvtools --version
insv-markers --help | head -1
test -x "$(uv tool dir --bin)/insv-markers-gui"
echo
echo "If a new terminal cannot find these commands, run: uv tool update-shell"

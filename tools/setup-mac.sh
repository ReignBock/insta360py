#!/usr/bin/env bash
# Set up insvtools and insv-markers on macOS.
#
# Run from a checkout:
#   tools/setup-mac.sh          install the two commands
#   tools/setup-mac.sh --dev    also set up the development environment
#
# The tools need Python 3.12 or newer and protobuf, nothing else. uv supplies
# both: it downloads a suitable Python when the system one is too old (macOS
# ships 3.9). The plain install needs no sudo and changes nothing outside uv's
# own directories and ~/.local/bin.
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
        -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

cd "$REPO_ROOT"

echo "installing insvtools and insv-markers"
uv tool install --force --python ">=3.12" .

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
echo
echo "If a new terminal cannot find these commands, run: uv tool update-shell"

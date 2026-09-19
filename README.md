# insta360py

[![CI](https://github.com/ReignBock/insta360py/actions/workflows/ci.yml/badge.svg)](https://github.com/ReignBock/insta360py/actions/workflows/ci.yml)

Python tools for Insta360 footage: read and edit the metadata Insta360
cameras append to `.insv`/`.lrv` files, cut clips without re-encoding, and
pull the timeline markers you pressed while recording back out again.

A Python implementation of two Windows-only projects — see
[Credits](#credits).

## Why

An `.insv` file is an ordinary MP4 with a proprietary metadata trailer stuck
on the end: gyro, GPS, exposure, the camera's own framing, and the markers you
tag during a shoot. Ordinary video tools either ignore that trailer or destroy
it, and a file that has lost it is no longer something the camera or Insta360
Studio will fully accept.

Everything here treats that trailer as the thing worth protecting. Reading a
file and writing it straight back reproduces it **byte for byte**, including
frame types nobody has documented.

## Requirements

- Python 3.12+
- `ffmpeg` — only needed to run the test suite

## Mac app

The Mac app shows the markers of your Insta360 footage in a window. You
install nothing else.

1. Download the zip for your Mac from the
   [latest release](https://github.com/ReignBock/insta360py/releases/latest).
   Use `arm64` for Apple silicon (M1 and later) and `x86_64` for Intel Macs.
   Apple menu, About This Mac, shows which one you have.
2. Open the zip and drag **Insta360 Markers** into your Applications folder.
3. Open it. The app is not signed with an Apple developer certificate, so
   macOS blocks the first launch. Open System Settings, choose Privacy &
   Security, and click **Open Anyway** next to the message about Insta360
   Markers. You do this once.

Drop your `.insv` or `.lrv` files, or the folder that holds them, on the
window. You can also use **Add Files** and **Add Folder**. Each recording
lists its markers with the time in the video. **Copy** puts the list on the
clipboard, and **Save** writes it to a text file.

The window only reads your files. It does not change them, and it does not
change Insta360 Studio projects.

To build the app yourself, run `tools/build-app.sh` on a Mac. To get a
launcher in `~/Applications` without downloading the zip, run
`tools/setup-mac.sh` from a checkout. It also installs the commands below.

## Install

Grab a wheel from the [latest release](https://github.com/ReignBock/insta360py/releases/latest):

```bash
pip install insta360py-0.1.0-py3-none-any.whl
```

Or run straight from a tag, with nothing installed. `uvx` builds the tag in a
cached environment and runs the command:

```bash
uvx --from "git+https://github.com/ReignBock/insta360py@v0.1.0" insvtools --version
uvx --from "git+https://github.com/ReignBock/insta360py@v0.1.0" insv-markers --help
```

To keep both commands on your PATH, use `uv tool install` with the same
`git+` URL.

Or from a checkout:

```bash
uv tool install .
```

Each of these provides two commands, `insvtools` and `insv-markers`. The
desktop window is an optional extra: add `[gui]` to any of the installs above
to get a third command, `insv-markers-gui`.

### Open the window with uv

`insv-markers-gui` opens the window. With [uv](https://docs.astral.sh/uv/) you
do not need to install anything first. uv fetches a suitable Python and Qt on
the first run.

From a checkout:

```bash
uv run --extra gui insv-markers-gui
uv run --extra gui insv-markers-gui /path/to/DCIM    # open with footage loaded
```

Straight from GitHub, with no checkout:

```bash
uvx --from "insta360py[gui] @ git+https://github.com/ReignBock/insta360py@main" insv-markers-gui
```

Replace `main` with a release tag to pin a version. The window ships in
releases after 0.1.0, so `v0.1.0` does not have it.

To keep the command on your PATH, install it once and run it by name:

```bash
uv tool install ".[gui]"
insv-markers-gui
```

### macOS

macOS ships Python 3.9, and this project needs 3.12 or newer. From a checkout,
one script handles it:

```bash
tools/setup-mac.sh          # install the commands and the desktop app
tools/setup-mac.sh --dev    # also set up the development environment
```

The script installs [uv](https://docs.astral.sh/uv/) into `~/.local/bin` if
it is missing. uv downloads a suitable Python and installs the package. The
plain install needs no sudo. With `--dev` the script also installs ffmpeg
through Homebrew, and installs Homebrew first when it is missing. Homebrew's
installer runs sudo and prompts for your password. Without ffmpeg, two tests
skip.

This is not on PyPI.

## Markers

Extract the timeline markers from a recording:

```bash
insv-markers /path/to/DCIM/
```

```
Sequence: VID_20260620_173803 (2 files)
----------------------------------------
Marker 01 : 00:04:52
Marker 02 : 00:18:13
Marker 03 : 00:29:16
[+] Injected 3 keyframe(s) into Insta360 Studio project.
```

Files are grouped by recording session, so a shoot split across several
chapters is reported as one timeline with the markers at their true offsets.

| Option | Effect |
|---|---|
| `-o, --out FILE` | also write the markers to a text file, with the raw seconds alongside `HH:MM:SS` |
| `--no-inject` | only report; do not touch Insta360 Studio |
| `--projects-dir DIR` | use a specific Studio footage-project directory |

### Insta360 Studio keyframes

By default, markers are also injected into Insta360 Studio as editable
keyframes. This is Windows-only, and needs a little care:

1. Open the footage in Studio, frame your shots, optionally add your own
   keyframes.
2. **Close Studio.** It holds the project in memory and will write its own
   copy back over any changes on exit.
3. Run `insv-markers` on the same files.
4. Reopen the clip in Studio; the markers are now keyframes on the timeline.

Generated keyframes inherit their framing from *your* keyframes —
interpolated between them, clamped to the nearest one outside them — so a
marker never swings the camera somewhere you did not put it. The project is
backed up to `.insprj.bak` before anything is written.

Use `--no-inject` if you only want the timestamps.

## Metadata and cutting

```bash
insvtools dump-meta VID_20260620_173803_00_029.insv    # -> ....insv.meta.json
insvtools cut --start-time=1:30 --end-time=2:00 VID_20260620_173803_00_029.insv
```

`cut` remuxes without re-encoding, snaps the start back to the nearest
keyframe, and rewrites the trailer to match: file size, durations, first-frame
and GPS timestamps, and the per-sample timelapse records. Every file of a
recording — both lenses and the low-res proxy — is cut at the same point
unless you pass `--no-group`.

| Command | Does |
|---|---|
| `cut` | clip a file, or a whole recording, without re-encoding |
| `dump-meta` | write the trailer to a readable `.meta.json` file |
| `extract-meta` / `replace-meta` | copy the trailer out to a file, and back in |
| `decompose-meta` / `compose-meta` | split the trailer into one file per frame, and reassemble |
| `remove-meta` | strip the trailer, leaving a plain MP4 |

Arguments are `--key=value`, with the filename last. Times are `[MM:]SS[.SSS]`.
Commands write their output into the current directory, named after the
input, and refuse to overwrite an existing file.

## Camera support

Tested against Insta360 **ONE R** and **X5** footage, including 5.7K
dual-lens files of tens of gigabytes. Other models should work: unknown
metadata is carried through untouched rather than guessed at.

The X5 stores its trailer differently from earlier cameras — wrapped in an
MP4 box, indexed rather than chained, with undocumented frame types — and
files it produces cannot be read by the original Java tool at all.

## Building a package

```bash
uv build               # -> dist/*.whl and dist/*.tar.gz
```

That is the whole story: a pure-Python wheel, no compile step, no platform
tag. Install the result anywhere with `pip install dist/*.whl`.

`protobuf` is the only runtime dependency, and it comes from pip. **Nothing
here shells out to an external program** — no ffmpeg, no exiftool, no bundled
binary — so an installed package needs nothing beyond Python and pip.

The sdist is a complete checkout: unpack it, `pip install .[dev]`, and the
full test suite runs, fixtures and golden outputs included.

### Cutting a release

`version` in `pyproject.toml` is the only place a version is written down.
Bump it, push, then run the **Release** workflow from the Actions tab.

It derives the tag from that version, so the release, the git tag, the wheel
filename and what `insvtools --version` reports cannot drift apart. It runs
the full suite, builds both artifacts, checks the installed wheel reports the
expected version, and only then tags the commit and publishes the release -
so a failed release leaves no tag behind.

Pushing a `v*` tag by hand still works, and is checked against
`pyproject.toml` rather than trusted.

## Development

```bash
uv sync --extra dev
uv run pytest --cov                  # 237 tests, 100% coverage (enforced)
uv run pylint src tests tools
uv run pyright
```

Fidelity is checked against reference output from the original Java tool,
committed under `tests/golden/`. Reading and rewriting a trailer is
byte-identical; so is a full-range MP4 rewrite, which reproduces the camera's
container exactly.

`CLAUDE.md` documents the `.insv` format in detail, along with the
architecture and the deliberate differences from the originals.

## Credits

This is a reimplementation of two projects, and it exists because their
authors worked the formats out first:

- **[insvtools](https://github.com/alex-plekhanov/insvtools)** by Alex
  Plekhanov (Apache-2.0) — the `.insv` container and metadata format.
  `src/insvtools/extra_metadata.proto` is taken from that project; the
  generated `extra_metadata_pb2.py`/`.pyi` derive from it.
- **[Insv-Marker-Extractor](https://github.com/arismelachroinos/Insv-Marker-Extractor)**
  by Aris Melachroinos — marker extraction and Insta360 Studio keyframe
  injection.

Neither project is affiliated with this one, and neither is affiliated with
Insta360.

## License

MIT — see [LICENSE](LICENSE). The vendored `.proto` and the code generated
from it remain under the Apache-2.0 license of the project they came from.

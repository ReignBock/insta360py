# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this is

A Python implementation of two Windows tools for Insta360 footage, in one
distribution:

| Package | Reimplements | Purpose |
|---|---|---|
| `src/insvtools/` | [`alex-plekhanov/insvtools`](https://github.com/alex-plekhanov/insvtools) (Java, Apache-2.0) | Read, rewrite and cut the `.insv` metadata trailer |
| `src/insvmarkers/` | [`arismelachroinos/Insv-Marker-Extractor`](https://github.com/arismelachroinos/Insv-Marker-Extractor) (PowerShell) | Extract timeline markers; inject them into Insta360 Studio |

`insvtools` mirrors the Java package tree closely enough that the Java stays
readable as a specification. `insvmarkers` does not mirror the PowerShell — it
imports `insvtools` directly instead of shelling out to `insvtools.exe` and
re-reading temporary `.json`/`.meta` files.

The two upstream projects are **not** needed to work here. Only
`tools/refgen.sh` refers to a sibling clone of the Java, and only to
regenerate golden outputs that are already committed.

## Working here

`flake.nix` + `.envrc` (`use flake`) provide Python 3.13, uv, ffmpeg and
nodejs (pyright's PyPI wrapper needs a node it can find). `direnv allow` runs
`uv sync --extra dev` and activates the project environment. Without Nix,
prefix each command with `uv run`:

```bash
uv sync --extra dev
uv run pytest --cov   # 430 tests; fails under 100% coverage (plain pytest does not measure it)
uv run pylint src tests tools
uv run pyright
```

Run a single test or file with `uv run pytest tests/test_mp4_writer.py::test_name`.

The `test` extra is what running the tests needs (pytest, Qt, cryptography); `dev`
adds the linters on top. The CI sdist check installs `test`, so the whole suite
runs from the unpacked sdist. A test dependency belongs in `test`, and a test
module should never be excluded from collection because one is missing.

Three gates, all currently clean, all expected to stay that way:

- **pytest at 100% coverage**, enforced by `fail_under = 100` when run with `--cov` (CI does). New code arrives
  with its tests. Four lines carry `# pragma: no cover`, each with a comment
  saying why (three need a >4 GiB payload to reach; one is a convergence
  guard).
- **pylint 10.00/10.** Every test has a docstring — that is the house style,
  not an accident.
- **pyright, zero errors.** It catches a class of bug pylint cannot: pylint
  does no type inference, and pyright found both a real `Optional` misuse in
  `cut.py` and the unsound `find_frame` signature.

Outside the direnv shell, `python3` on PATH is an unrelated Ansible venv, so use `uv run`.
`ffmpeg` is available (used only by tests); there is no `exiftool`, no Java
and no Maven.

### Packaging

```bash
uv build                        # pure-Python wheel + sdist, no compile step
```

`protobuf` is the only runtime dependency and the shipped code spawns no
external process, so an install needs nothing outside pip. ffmpeg is used by
two tests, and Docker only by `tools/refgen.sh`.

Points worth not undoing:

- **`py.typed` in both packages.** Without that marker (PEP 561) a consumer's
  type checker ignores our annotations *and* the `extra_metadata_pb2.pyi`
  stub, however carefully either is maintained.
- **`package-data` lists `*.pyi` explicitly** rather than relying on
  setuptools' implicit stub handling.
- **`MANIFEST.in` grafts `tests/` and `tools/`.** setuptools' default sdist
  picks up `tests/test_*.py` but *not* `conftest.py`, the binary fixtures or
  the golden outputs — an sdist whose tests cannot run. Verify with: unpack
  the sdist, install it, run pytest.
- **`license` is an SPDX string with `license-files`** (PEP 639). The
  TOML-table form is deprecated and setuptools removes it in Feb 2027; this
  is why the build requires `setuptools>=77`.

The build prints `no previously-included files matching '__pycache__' ...`
warnings. Those are setuptools' own default exclusions matching nothing, not
a problem with `MANIFEST.in`.

### CI and releases

Two workflows in `.github/workflows/`, both on GitHub-hosted runners (free
and unmetered because the repository is public):

- **`ci.yml`** on every push and PR: the suite on Python 3.12 and 3.13, pylint
  and pyright once on 3.13, and a packaging job that builds both artifacts,
  installs the wheel into a clean venv, runs the console scripts, then
  unpacks the sdist and runs *its* tests. That last step is what keeps
  MANIFEST.in honest.
- **`release.yml`**, run from the Actions tab: `project.version` is the
  single source of truth, and the tag is derived from it, so the release, the
  tag, the wheel filename and `insvtools --version` cannot disagree. It runs
  the suite, builds, asserts the artifacts and the installed package all
  carry that version, and only then tags the commit and publishes - a failed
  release leaves no tag behind. Pushing a `v*` tag by hand also works and is
  checked against `project.version` rather than trusted.

**Releases go to GitHub, not PyPI** - that is a deliberate choice, not an
oversight. GitHub has no Python package registry, so release assets are the
distribution channel; `pip install` works against a release URL or a tag.
(The name `insta360py` was free on PyPI as of the last check, if that ever
changes.)

CI installs ffmpeg, but treats it as optional: the install step is
`continue-on-error` and a run without it still passes. Two tests need it -
the only ones that prove cut output actually decodes - and they skip
cleanly, with the coverage gate still met. Because a silent skip would
otherwise look identical to a green run, the job writes a note to the step
summary saying whether those checks ran.

### Regenerating committed artifacts

| Command | Produces | Needs |
|---|---|---|
| `tools/genproto.sh` | `extra_metadata_pb2.py` + `.pyi` | the `proto` extra |
| `tools/refgen.sh` | `tests/golden/*` from the Java | Docker + a sibling `insvtools` clone |
| `tools/mkfixture.py` | `tests/resources/x5_indexed.insv` | a private X5 recording |

The `.pyi` stub is load-bearing, not cosmetic: protobuf 7.x builds message
classes at runtime via `_builder`, so `ExtraMetadata` appears nowhere in the
generated `.py`. The stub is the only reason pyright can resolve it. pylint
does not read stubs, which is why its single import site still carries a
`no-name-in-module` disable.

## The `.insv` format

An `.insv` is a normal MP4 with a proprietary **metadata trailer appended
after the moov/mdat**. Everything in the trailer is little-endian; MP4 boxes
around it are big-endian.

**Footer** — the last 72 bytes: 32 unknown bytes, `int32 metadataSize`,
`int32 version` (only `3` supported), then the 32-byte ASCII signature
`8db42d694ccc418790edff439fe026bf`. No signature ⇒ not an insv; treat it as a
plain MP4 rather than erroring. `metadataPos = fileLength - metadataSize`.

**The `inst` box.** Newer firmware (X5, v1.11) wraps the whole trailer in an
MP4 box so the file stays a structurally valid MP4 to the very end: an 8-byte
big-endian header of `size = metadataSize + 8`, type `inst`, at
`metadataPos - 8`, running to EOF. A ONE R has plain padding there instead.
Detect it by matching **both** type and size — eight bytes of padding could
otherwise pass for a header. The MP4 parser must stop at `metadataPos - 8`
when it is present, or it reads those bytes as a truncated box and dies; the
writer must re-emit it; and `ExtraMetadata.FileSize` counts up to
`metadataPos`, i.e. past the box header. The Java has none of this and cannot
read an X5 file at all.

**Frames are chained backwards.** Each frame's 6-byte header sits *after* its
payload: `uint8 version, uint8 typeCode, int32 payloadSize`. Reading starts at
`fileLength - 72` and walks down: read the six header bytes ending at the
current position; the payload precedes them. Frames come out newest-to-oldest,
so the list is reversed at the end.

**Two layouts.** On hitting a frame of type `INDEX` (0) the walk stops and the
remaining frames are located through the index: 10-byte entries of
`uint8 type, uint8 version, int32 size, int32 offset`, the offset relative to
`metadataPos`, an all-zero entry meaning "absent".

**The index must not shrink when rewritten.** A camera sizes it by its own
highest frame type, which can exceed both the types this code knows and the
types the file actually contains — an X5 writes 31 slots (310 bytes) for a
highest present type of 29. A rebuilt index keeps at least the slot count it
arrived with, or the trailer changes length.

Gaps between indexed frames — and any gap between the lowest frame and
`metadataPos` — are preserved as synthetic `RAW` (type `-1`) frames, which
write their payload with **no** frame header. Preserving unknown and RAW bytes
verbatim is a hard requirement: the writer must produce a file the camera and
Insta360 Studio still accept.

**Frame types:** 0 INDEX, 1 INFO, 2 THUMBNAIL, 3 GYRO, 4 EXPOSURE,
5 THUMBNAIL_EXT, 6 TIMELAPSE, 7 GPS, 8 STAR_NUM, 9 THREE_A_IN_TIMESTAMP,
**10 ANCHORS** (markers), 11 THREE_A_SIMULATION, 12 EXPOSURE_SECONDARY,
13 MAGNETIC, 14 EULER, 15 GYRO_SECONDARY, 16 SPEED, 17 TBOX, 18 EDITOR,
19 HEARTRATE, 20 FORWARD_DIRECTION, 21 UPVIEW, 22 SHELL_RECOGNITION_DATA,
23 POS, 24 TIMELAPSE_QUAT. An X5 also writes types **27, 28 and 29**, which
are undocumented and survive as opaque payloads — as any unknown type must.

**INFO frame (type 1)** is protobuf when `frameVersion == 1`; any other
version meant JSON, which upstream never implemented. It must be parsed
*first*, because other frames depend on it. Unknown protobuf fields are
retained so re-serialization is lossless.

Critically, **the GYRO record size is not in the gyro frame** — it equals
`len(ExtraMetadata.Gyro)`, the sample blob in INFO. 56 bytes ⇒ V1
(`int64 ts + 6×double`), 20 ⇒ V2 (`int64 ts + 6×int16`), anything else ⇒ raw
passthrough. If INFO is missing, unparsed, or its `Gyro` is **empty** — which
is what an X5 writes — the gyro frame stays opaque.

**Record-oriented frames** all begin with `int64 timestamp`: GPS 53 bytes
(`8 + 45`: three unknown bytes, then double lat, char N/S, double lon,
char E/W, double speed, double track, double altitude), EXPOSURE 16
(`ts + double shutterSpeed`), TIMELAPSE 8 (ts only — one record *per video
sample*), GYRO as above. The parse loop is `while remaining >= recordSize`, so
a trailing partial record is dropped; upstream does the same, and the golden
output confirms it.

**Timestamp scale is ambiguous.** A firmware change moved timestamps from
milliseconds to microseconds with no flag. The scale is guessed from the sign
of `ExtraMetadata.GyroTimestamp`: negative ⇒ 1_000, otherwise 1_000_000,
overridable with `--timestamp-scale`. `FirstGpsTimestamp` is always adjusted
by ×1000 regardless.

`FirstFrameTimestamp` is a **monotonic uptime clock in µs, not a Unix epoch**
(309468418 ≈ 309 s in `sample.insv`). It does not reset between recordings,
which is why a session's later chapters carry larger values and why marker
seconds are `(markerTs - firstFrameTs) / 1e6`.

### ANCHORS frame (type 10) — markers

**Confirmed** against X5 files carrying real markers. The payload is a run of
**sections**: a 5-byte header (`uint8 kind, uint32 count`) followed by `count`
8-byte records. Kinds `1, 2, 3, 4, 0x10, 0x11, 0x12` appear in that order
whether or not they hold anything, so an empty frame is 35 bytes of headers:

```
01 00000000 | 02 00000000 | 03 00000000 | 04 00000000 | 10 00000000 | 11 00000000 | 12 00000000
```

Only section 1 has been seen populated. Each record is a single **`uint64`**
timestamp on the same clock as `FirstFrameTimestamp`.

`get_markersV2.ps1` skips byte 0, reads a `uint32` count at offset 1, then a
**`uint32`** timestamp from each 8-byte record. Both are wrong: it finds only
section 1 because that section happens to come first, and the `uint32`
timestamp **truncates** once the camera's uptime passes ~71 minutes. Real
markers observed at `7015413766`, `7816572421` and `8479199128` are all above
2³².

## Architecture

### `insvtools`

`header.py` (footer + `inst` box) → `metadata.py` (the frame walk, both
layouts, and the write path) → `frames/` (one module per interpreted type,
built through `frames/factory.py`, which exists to break the cycle between the
base `Frame` and its subclasses) → `records/` (fixed-size records).

`mp4/` is a small ISO-BMFF implementation: `boxes.py` walks the tree,
`reader.py` expands the sample tables, `writer.py` puts a clipped file back
together. **The writer copies every box verbatim except the sample-indexed
tables and three duration fields.** That is what makes a full-range rewrite
byte-identical to the camera's own output, and it is worth preserving.

`commands/` holds the command implementations as plain functions;
`dump/dumper.py` is a hand-rolled JSON writer, because matching the Java's
Gson output requires raw `\xNN` escapes that `json` will not emit.

`find_frame_of(SomeFrame)` is the typed lookup and should be preferred;
`find_frame(FrameType)` remains for dynamic lookups by raw type code and for
ANCHORS, which the factory deliberately does not map to a class.

### `insvmarkers`

`extractor.py` (sessions and markers, cross-platform), `results.py` (scans files
into `SessionResult`s, renders the text report, and arranges recordings under
the folders searched with `group_by_folder`; shared by the CLI and the window,
and free of Qt and printing), `studio.py` (the `.insprj` keyframe
injection) and `gui.py` (the PySide6 window). Keep decisions about *what to
show* in `results.py`; `gui.py` only arranges it on screen. Locating Studio's project is Windows-only, but
everything that edits the JSON is plain data handling and is tested off
Windows — keep that split.

A Studio project's `key_frame_track.node_list` alternates keyframes
(`node_type: 0`) with the transitions between them (`node_type: 1`, named
`{prev.name}-{next.name}`), so adding one keyframe means rebuilding the whole
list. New keyframes take their framing from the user's *existing* keyframes —
interpolated between them, clamped to the nearest one outside them — and never
from each other. The project is backed up to `.insprj.bak` first, and Studio
must be closed or it will write its in-memory copy back over the changes.

### The Mac app

`gui.py` is behind the `gui` extra (`PySide6-Essentials`), which `dev` also
includes so the window is tested and counted toward coverage. Its tests run on
Qt's offscreen platform (`tests/test_gui.py` sets `QT_QPA_PLATFORM` itself;
do not export it in the shell, or the real window goes offscreen too). It
reads files and never injects into Studio: injection is unverified.

Folder search is recursive in the window only. `expand_paths(paths,
recursive=True)` walks with `os.walk`, skips hidden folders and files (the
trash, Spotlight's index and the `._` copies a Mac drive keeps), and lists
files in sorted depth-first order. The CLI still calls it without `recursive`
and looks one level deep. `find_sessions` keys on the session id, so a
recording found in two folders is listed once, under the first folder seen.
The window walks on the UI thread (a wait cursor, no cancel), so a very large
folder freezes it until the walk ends.

Two routes put it on a desktop:

- **`tools/build-app.sh`** freezes it with PyInstaller (`tools/app.spec`,
  `tools/app_entry.py`) into a standalone `.app` and zips it with `ditto`.
  It must run on a Mac, once per architecture. `.github/workflows/macos-app.yml`
  does that for arm64 and x86_64 and is called from `release.yml` after the
  release exists (a `GITHUB_TOKEN` release does not trigger other workflows,
  so a `release: published` trigger would never fire). The app is ad-hoc
  signed only, so a downloaded copy needs Open Anyway on first launch.
- **`tools/setup-mac.sh`** installs the tool with the extra and writes a small
  launcher `.app` into `~/Applications` that `exec`s `insv-markers-gui` by
  absolute path (Finder gives apps a bare PATH).

On NixOS the pip Qt wheels need system libraries; `flake.nix` puts them on
`LD_LIBRARY_PATH` for Linux only.

### Updating the Mac app

`update.py` (Qt-free: versions, release parsing, certificate and CRL checks,
staging, the swap script) and `updater.py` (the window's side:
`UpdateController`, dialogs, `QtFetcher`). `gui.main` calls
`updater.create(window)`, which returns `None` unless the process is a frozen
`.app` **and** `release_ca.pem` is present, so `uv` installs never check.

- **Trust.** The app carries a CA certificate (`src/insvmarkers/release_ca.pem`,
  committed). Each release zip ships with `<zip>.sig` (a base64 Ed25519
  signature by the *release key*) and `<zip>.crt` (the release key's
  certificate, issued by the CA). `check_release` requires, in order: issued
  directly by the CA; a code-signing leaf (`CA:FALSE`, `digitalSignature`,
  `codeSigning`); in date; not on a current CRL; the certificate's key made the
  signature. A file the app downloads has no quarantine flag, so Gatekeeper
  never sees it: these checks are the *only* ones. `stage()` also confirms the
  version inside the app equals the version the release named, so an old
  signed zip cannot pass as a new one.
- **Revocation.** The CRL is `src/insvmarkers/release_crl.pem`, committed. The
  app trusts the union of three copies (built in, cached from a previous
  download, and the one at `update.CRL_URL` on `main`, fetched at install
  time), keeping only lists the CA signed and that have not passed their
  next-update date. If none is usable the update is refused. A certificate on
  any usable list is refused, so an older list cannot hide a revocation.
  Revoking is a commit: running apps see it at their next install with no new
  app. It does not touch versions already installed.
- **Keys and scripts.** `tools/pki/` (see its README) creates the CA, issues
  and revokes release certificates, and writes the CRL, all with `openssl ca`
  and `openssl-ca.cnf`. The CA key stays offline (`~/release-keys` by default,
  outside the repo). The only GitHub secret is
  `RELEASE_SIGNING_KEY` (the release private key, PEM). Everything else is
  public and committed: `release_ca.pem`, `release_crl.pem` and the release
  certificate `tools/pki/release.crt` (which `issue-release-cert.sh` writes
  there, overwriting the previous one). `tools/sign_release.py`
  runs the app's own `check_release` before writing `.sig` and `.crt`, so a
  wrong pairing or a revoked, expired or missing-CRL setup fails in CI, not on
  a Mac. `tools/check_setup.py` fails a release whose bundled CRL has expired
  (warns under 30 days left) or whose committed certificate is revoked,
  expired, or not from the CA (warns under 90 days left), and, when
  `RELEASE_SIGNING_KEY` is in the environment, whose key does not belong to
  the committed certificate; the certificate checks are `update.check_certificate`,
  shared with the app. Losing the CA key means no new release
  certificates or CRLs can be made and installed apps must be replaced by hand;
  losing only a release key costs nothing, since a new one is issued.
- **Workflow order.** `release.yml` fails first if the key secret is missing or
  `check_setup.py` fails, before any tag exists. `macos-app.yml` builds (the CA
  certificate and CRL are bundled from `src/insvmarkers` by `app.spec`), signs,
  and attaches zips, `.sig`, `.crt` and `release_ca.pem`. The release is
  published before the app jobs run, so a failed app job leaves a release with
  no app assets: the updater then sees no usable release and offers nothing.
- **Swap.** A running app cannot replace itself, so `start_swap` writes
  `swap.sh` to `~/Library/Application Support/Insta360 Markers/` and starts it
  detached; it waits for the app's pid to exit, moves the current app aside,
  moves the new one in, keeps the old as `Previous/`, and reopens. If moving
  the new app in fails it restores the old one. A rollback is the same script
  with the previous app as both the new app and the previous slot, which swaps
  them. Extraction uses `ditto` (Python's `zipfile` would lose the bundle's
  symlinks and modes).
- **Cannot update** when the path contains `AppTranslocation` (a freshly
  downloaded app runs from a read-only copy until moved) or the folder is not
  writable; `install_problem` returns the message shown.
- **Network** uses `QNetworkAccessManager`, not `urllib`: a bundled Python does
  not reliably trust the macOS certificate store, Qt does. `QtNetwork` must
  stay out of the spec's `excludes`. The fetcher must outlive its requests
  (destroying it mid-flight crashes Qt), which is why tests share one.
- **Cadence.** `start()` checks once as the window opens and then on a 24-hour
  `QTimer`. A failed automatic check is silent; a manual one reports. A skipped
  version is remembered in `QSettings` and a rollback also skips the version
  it left, so it is not re-offered at every launch.

## CLI surfaces

`insvtools <cmd> [--key=value ...] <file>`: `cut`, `dump-meta`,
`decompose-meta`, `compose-meta`, `remove-meta`, `extract-meta`,
`replace-meta`. Time format is `[MM:]SS[.SSS]`. `decompose-meta` writes
`{file}.frame{NN:02d}.type{code}[_{ver}].meta` (RAW frames use `typeRaw`) and
`compose-meta` reads them back **sorted by name** — that naming contract is
load-bearing.

`insv-markers PATH...` with `--no-inject`, `-o/--out FILE`, `--projects-dir`.

**File grouping differs between the two tools, deliberately.** `cut` matches
siblings with `(\w*)(VID|LRV)_(\d{8}_\d{6})_\d\d_(\d+)\.(\w+)`, keying on
prefix + datetime + trailing number, treating `insv`/`lrv` as interchangeable.
The marker extractor groups by the `(\d{8}_\d{6})` session id alone, because
every chapter of a recording shares one marker timeline.

## Deliberate divergences from upstream

Each of these is a considered choice, not an oversight:

- **Camera timestamps are preserved.** The Java rewrites `mvhd`/`tkhd`
  creation and modification times on cut; we keep the camera's. Cut output
  therefore differs from the Java's in exactly 32 bytes.
- **`uint64` marker timestamps**, and **all seven anchor sections** are read.
- **Proxies are only read when no original is present.** The PowerShell reads
  both lens files when both exist and counts every marker twice, which its
  rounding then hides.
- **The Studio project is written without a BOM.** The PowerShell writes one
  via `[System.Text.Encoding]::UTF8`; we read `utf-8-sig` so its output still
  round-trips.
- **`edts` is dropped on cut** (logged): an edit list maps into media time the
  cut has just moved, and a stale one is worse than none.
- **The sync-sample search has no off-by-one**, unlike upstream's.

## Test fixtures

| Fixture | Covers |
|---|---|
| `tests/resources/sample.insv` (518 KB, ONE R) | chained frames, no index, no `inst` box, V2 gyro, a QuickTime `text` track |
| `tests/resources/x5_indexed.insv` (387 KB, X5) | indexed layout, `inst` box, types 27/28/29, empty `Gyro`, three real markers |
| `tests/golden/` | byte-exact reference output from the Java |
| synthetic containers in `tests/test_mp4_*.py` | `stz2`, `co64`, `sdtp`, `edts`, 64-bit box headers, malformed input |

The X5 fixture is derived from a **private recording** by `tools/mkfixture.py`,
which truncates payloads and strips personal data: GPS records are zeroed, the
serial is replaced, the thumbnail is truncated past its header, and the 7.8 MB
proprietary `udta` blob is emptied. Anything derived from real footage in
future must be scrubbed the same way.

## Known gaps

- **The updater has never run a whole update on a real display.** Verified on
  a Mac over SSH (before the CA model): `ditto` staging, the swap and rollback
  against real bundles, `codesign --verify --deep --strict` on the swapped
  app, no quarantine flag, the swapped app starting, and real HTTPS to GitHub.
  The chain, CRL and script logic is covered by tests, and the `tools/pki`
  scripts were run against OpenSSL 3, including on the Mac with Homebrew's
  (they skip where only LibreSSL is on PATH). Not verified: the prompt and progress dialogs on screen, and the relaunch
  through `open` after the app quits. No release yet carries signed zips, so
  the first update will be the first end-to-end run.
- **The window has never been seen on a real display.** It is tested
  headless, and the frozen app and the launcher were shown to start under the
  offscreen platform on a Mac over SSH. `open` fails over SSH (no graphical
  session), so drag and drop, layout and the first-launch Gatekeeper flow need
  someone at a Mac. The Actions runner labels `macos-15` and `macos-15-intel`
  and the Qt libraries apt-installed in `ci.yml` are also unproven until the
  first run.
- **Studio injection has failed for the user on a Mac** and is uninvestigated.
- **Insta360 Studio acceptance is unverified.** Nothing here can confirm
  Studio opens a cut file or accepts an injected project; that needs Windows
  with Studio installed.
- **The millisecond timestamp scale has no fixture** — synthetic tests only.
- **JSON-format INFO frames** (`frameVersion != 1`) are rejected, as upstream.
- **`co64`, dual video tracks and >4 GiB output** are only reachable with real
  multi-gigabyte files; the committed tests cover them synthetically.

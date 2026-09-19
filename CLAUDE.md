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
uv run pytest --cov   # 216 tests; fails under 100% coverage (plain pytest does not measure it)
uv run pylint src tests tools
uv run pyright
```

Run a single test or file with `uv run pytest tests/test_mp4_writer.py::test_name`.

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

`extractor.py` (sessions and markers, cross-platform) and `studio.py` (the
`.insprj` keyframe injection). Locating Studio's project is Windows-only, but
everything that edits the JSON is plain data handling and is tested off
Windows — keep that split.

A Studio project's `key_frame_track.node_list` alternates keyframes
(`node_type: 0`) with the transitions between them (`node_type: 1`, named
`{prev.name}-{next.name}`), so adding one keyframe means rebuilding the whole
list. New keyframes take their framing from the user's *existing* keyframes —
interpolated between them, clamped to the nearest one outside them — and never
from each other. The project is backed up to `.insprj.bak` first, and Studio
must be closed or it will write its in-memory copy back over the changes.

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

- **Insta360 Studio acceptance is unverified.** Nothing here can confirm
  Studio opens a cut file or accepts an injected project; that needs Windows
  with Studio installed.
- **The millisecond timestamp scale has no fixture** — synthetic tests only.
- **JSON-format INFO frames** (`frameVersion != 1`) are rejected, as upstream.
- **`co64`, dual video tracks and >4 GiB output** are only reachable with real
  multi-gigabyte files; the committed tests cover them synthetically.

# DF-003: media foundation verification

Verified on 2026-11-18, macOS 15.6 ARM64. Read the parent project rules and
existing project documentation; DF-002 approved as the starting point.

## Tools and implementation

Installed with Homebrew using `HOMEBREW_NO_AUTO_UPDATE=1
HOMEBREW_NO_INSTALL_CLEANUP=1 brew install ffmpeg`. Homebrew installed
`ffmpeg 9.0.2_1` and 12 missing dependencies from ARM64 Sequoia bottles.
Both `ffmpeg -version` and `ffprobe -version` report 9.0.2; `file -L` reports
both `/opt/homebrew/bin/ffmpeg` and `/opt/homebrew/bin/ffprobe` as
`Mach-O 64-bit executable arm64`. FFmpeg's Cellar directory occupies 52 MiB
on disk (54.4 MB as reported by Homebrew); dependency disk usage is additional.

Added reusable metadata/import service and workspace configuration, using only
Python's standard library. No Python dependencies changed. New scripts provide
sample generation and JSON probe/import/storage commands. No schema migrations,
new HTTP endpoints, or upstream integration were needed.

## Authorized sample and actual validation

Original synthetic content generated locally by `scripts/create_sample.sh`:
solid blue video and a 440 Hz sine wave. No third-party footage or music.
The sample and imported files are ignored runtime data, not committed binaries.

| Field | Actual result |
| --- | --- |
| Source | `data/samples/authorized-generated.mp4` |
| Duration | 2.0 seconds |
| Container | MOV/MP4 family |
| File size | 20,910 bytes |
| Video | One H.264 stream, 320 × 240 |
| Audio | One AAC stream, mono, 48,000 Hz |
| SHA-256 | `94c1587a0d172938e46035c4f596913beb2fe8d22f35887bfba2ba55e58e7a2e` |
| Imported ID | `5d81eb839f83455d9871a77ee1759dcd` |
| Imported path | `data/workspace/imports/5d81eb839f83455d9871a77ee1759dcd/source.mp4` |

The import copied and revalidated the video and wrote `metadata.json` beside it.
The source was preserved. This verifies metadata validity, not full frame decode.

## Storage checks

Default workspace: `data/workspace`. Quota: **60,000,000,000 bytes** (decimal
60 GB), physical reserve: **1,073,741,824 bytes** (1 GiB).

- Before import, used: 0 bytes. Preflight for 60,000,000,001 bytes was denied
  (`can_import: false`, exit 1), despite sufficient physical disk.
- Sample import reserved 20,910 + 65,536 = **86,446 bytes** before copying.
- After import, workspace file usage: **21,599 bytes**, including manifest;
  quota remaining: **59,999,978,401 bytes**.
- Free disk measured after import: **122,877,251,584 bytes**, comfortably above
  the 1 GiB reserve. `df -h` reports approximately 114 GiB available.
- Project including `.venv`: **31 MiB**; `.venv`: **31 MiB**; all `data`: **60 KiB**.
- Tests check quota boundaries, real existing/staged-file usage, simulated
  physical disk exhaustion/failure, and competing imports under a file lock.

## Verification and scope

- Full automated suite: **23/23 tests pass**, covering the original 7 backend
  smoke tests and 16 media/storage tests. Includes real generated media,
  corrupt/empty/audio-only inputs, silent video, metadata validation, missing
  or timed-out FFprobe, malformed JSON, quota/capacity failures, concurrent
  imports, source-change rejection, rollback, symlinks and playlist rejection.
- `pip check`: no broken requirements; no Python dependency changes.
- Shell syntax checks and `git diff --check` pass.
- Source and imported SHA-256 match exactly.
- After installing tools, `/api/system/status` reports overall `ok`.
- Claude cross-review: **no blocking findings**. Independently confirmed 23/23
  tests, dependency/shell/whitespace checks, CLI import/over-quota behavior,
  accepted MOV/MKV/WebM/AVI and rejected TS/FLV containers, and rollback when
  a source grows during copying. Review was read-only.

No transcription, translation, TTS, frontend, models, paid APIs, or upstream
source integration. The upstream reference remains unchanged.

Limitations: only the documented local container families are supported;
probe timeout is 15 seconds per probe, and imports probe source and staged copy.
The quota covers logical regular-file sizes, not filesystem directory overhead.
The lock coordinates service imports, not arbitrary external workspace writers.
No catalog/listing UI, transcoding, or complete decoder validation is included.

Deferred non-blocking review notes: atomic rename provides publication visibility,
but imports do not fsync files/directories and are not guaranteed durable after
power loss. SIGKILL staging leftovers remain counted until manually reviewed
and removed while no imports are active. Lock acquisition has no timeout.
Relative CLI paths deliberately resolve against the repository root. Manifests
contain absolute paths, and FFprobe is selected through PATH. Use a dedicated
workspace rather than the repository root (which contains virtualenv symlinks).
The automated suite covers thread concurrency and changes before copy; growth
during copy, cross-process locking, and CLI exit codes were reviewed manually
rather than all having dedicated automated coverage.

References: [FFprobe documentation](https://ffmpeg.org/ffprobe.html) and
[Homebrew FFmpeg formula](https://formulae.brew.sh/formula/ffmpeg).

Stop after DF-003 and await PO approval.

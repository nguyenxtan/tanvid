# DF-004 audio extraction verification

Verified 2026-11-18 on macOS 15.6 ARM64, Python 3.12.16 and FFmpeg/FFprobe 9.0.2.
DF-003 approved; its accepted limitations are tracked in `LIMITATIONS.md`.

## Changes

- `backend/audio.py`: reusable, selected-track speech extraction, optional
  all-track original preservation, integrity validation and checksummed reuse.
- `backend/limited_exec.py`: child-only POSIX file-size limit before FFmpeg exec,
  without thread-unsafe `preexec_fn`. FFmpeg process groups are reaped on error,
  timeout and Python interruption before staging is cleaned.
- `backend/media.py`: audio stream durations, `extract_audio` service integration,
  `extract-audio` CLI command and CLI-only SIGTERM handling.
- `scripts/create_audio_sample.sh`: reproducible authorized 180-second synthetic
  MP4 (color plus generated 440 Hz tone, no external footage/music).
- New audio regression tests, README instructions and tracked deferred limits.
  No Python dependency changes, schema migrations or new HTTP endpoints.

## Actual 180-second sample results

Generated `data/samples/authorized-180s.mp4`, imported via `MediaService`, then
extracted from its imported copy with `preserve_original=True`.

| Item | Actual result |
| --- | --- |
| Source | 180.0 s, H.264 160 × 120, stereo AAC 48,000 Hz |
| Source size | 2,280,625 bytes |
| Source SHA-256 | `efae73a6957075bf67bc538b95c196fc99417ed9699e899812bb2ed24fcaea6a` |
| Imported ID | `30218f95401f4c3d8bbd996ed62c2989` |
| Speech WAV | 180.0 s, `pcm_s16le`, 16-bit, mono, 16,000 Hz |
| Speech size | 5,760,078 bytes |
| Speech SHA-256 | `f2cdfe74e48d32de4fa665394a1e03906c2fc858d87f7e03ab88bf13cea922c3` |
| Preserved MKA | 180.021 s, AAC stereo 48,000 Hz, no re-encoding |
| Original size | 2,227,552 bytes |
| Original SHA-256 | `59ba00157e06a39124b57e7406ecfd24e6fdfc5ede8e04ea4705a3ad364bd7f1` |
| Manifest size | 1,071 bytes |
| Import time | 0.062 s |
| Extraction + validation time | 0.366 s measured around the service call |
| Repeat reuse + revalidation time | 0.265 s; `reused: true` |

Timing is one warm local synthetic-sample measurement, not a speech-content
benchmark. The synthetic tone verifies format, duration and file integrity;
it is not a speech-recognition accuracy test. FFprobe and full WAV-frame reads
confirm speech output format/integrity; preserved audio passes full FFmpeg
decode. The MKA duration differs by 0.021 s due to AAC priming/remux timing and
is within the documented 0.25 s tolerance.
Independent FFmpeg stream-copy hash checks confirm the source and preserved
AAC packet payloads match: SHA-256
`48a835532a740a79fe26aee02a0436a3e72bc9e4bab82de6562ce9789ff03858`.

## Storage

- Quota: **60,000,000,000 bytes**; physical reserve: **1,073,741,824 bytes**.
- Extraction preflight reservation: **9,166,833 bytes**, comprising WAV cap
  5,772,096 + original cap 3,329,201 + manifest budget 65,536 bytes.
- Actual extraction output + manifest: **7,988,701 bytes**.
- Workspace including both imported samples and extraction:
  **10,291,648 bytes used**, **59,989,708,352 bytes quota remaining**.
- Free disk measured after extraction: **122,858,774,528 bytes** (approximately
  114 GiB). Project **44 MiB**, `.venv` **31 MiB**, data **12 MiB**, workspace
  **9.8 MiB**, audio output directory **7.6 MiB**.
- Reuse writes no output files. Missing preservation can be added while copying
  the valid speech WAV into new staging; preflight includes transient files and
  any previous outputs until replacement succeeds.

## Verification

Full suite: **43/43 tests pass**, including the 23 prior tests and 20 audio tests:
real stereo AAC to PCM16/mono/16kHz; preserved codec/rate/channels; source
unchanged; output hash/integrity and duration; shorter audio than video; selected
tracks/all-track preservation; source audio-packet corruption; silent video;
cache hit, repair and malformed manifest; preservation upgrade; quota denial;
file-size limit; missing FFmpeg; timeout; SIGTERM CLI child reaping/staging
cleanup; thread/cross-process serialization; replacement and rollback failures;
and generated 180-second media. Tests leave their fixtures in temporary dirs.
Review regressions additionally verify no signalling of an already-reaped child,
cleanup failures do not mask successful publication, and interruption immediately
after a backup rename restores the existing output.

`pip check`, shell syntax and whitespace checks pass. Upstream working tree is
unchanged. Claude cross-review found **no blocking findings** and independently
confirmed the original 40-test suite, dependency and shell/whitespace checks.
Three optional cleanup findings were reproduced with failing tests and fixed:
only live child groups are signalled; cleanup failures warn and retain files
without masking the result; replacement backup rename is inside rollback scope.
The expanded 43-test suite passes after these changes.

Deferred review finding: a corrupt optional preserved original remains on disk
and in the manifest if preservation is not requested; valid speech can be reused
with `original: null`, and the damaged file remains counted against quota.
Requesting preservation repairs it; automatic pruning is tracked as LIM-008.
SIGTERM deliberately uses the documented cancellation exit 130 rather than 143;
reservations remain conservative, and the child launcher inherits the local
Python environment. EFBIG rather than SIGXFSZ may report output-limit exhaustion;
both paths fail validation safely.

## Scope and limits

No transcription, translation, TTS, frontend, models, paid APIs or upstream
integration. Follow-ups are in `LIMITATIONS.md`. Unsupported original codecs
that cannot remux into Matroska fail safely; the input video remains intact.
Audio with absent stream duration uses container duration and may be rejected
if those timelines disagree. Classic WAV is bounded below 4 GiB. Strict audio
decode errors abort rather than publishing a partially recovered file.

References: [FFmpeg](https://ffmpeg.org/ffmpeg.html),
[Python WAV validation](https://docs.python.org/3.12/library/wave.html),
[POSIX resource limits](https://docs.python.org/3.12/library/resource.html).

Stop after DF-004 and await PO approval.

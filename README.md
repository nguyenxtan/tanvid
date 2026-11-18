# DramaFlow

Independent local backend, media, audio and Mandarin transcription foundation.

The upstream reference is a separate, unchanged sibling checkout at
`../hongguo-drama`. See [upstream sources](docs/UPSTREAM_SOURCES.md) for provenance.

Requirements: macOS ARM64 and Python 3.12. Node.js, Git, FFmpeg, and FFprobe
are detected for diagnostics; missing media tools do not prevent backend startup.
The media service and its tests require FFmpeg/FFprobe. Install with
`brew install ffmpeg`; verify both with `file -L /opt/homebrew/bin/ffmpeg /opt/homebrew/bin/ffprobe`.

```sh
./scripts/setup.sh
./scripts/test.sh
./scripts/start.sh
```

If Python is outside PATH:
`PYTHON=/opt/homebrew/bin/python3.12 ./scripts/setup.sh`.
Setup installs the fully pinned `requirements.txt` into `.venv` only.
The scripts work from any current directory. Stop the server with Ctrl-C.

- `GET http://127.0.0.1:8000/health`: HTTP 200 when SQLite is ready;
  HTTP 503 if it becomes unavailable.
- `GET http://127.0.0.1:8000/api/system/status`: HTTP 200 diagnostic snapshot
  of runtime, total RAM, free/total project-volume disk, tool versions, and SQLite.
  Overall status is `degraded` when a required tool or SQLite is unavailable.
  Failed resource probes report `null` rather than an invented value.

The server binds only to `127.0.0.1`. Set `PORT` to override 8000.
SQLite initializes on startup at `data/dramaflow.sqlite3`; set
`DRAMAFLOW_DB_PATH` to override it. Relative paths are resolved against the
repository root. Runtime data, virtual environments, and caches are ignored.
The initial schema contains only a schema-version table. Startup fails visibly
if the database cannot be initialized; readiness probes never recreate a missing DB.

No upstream code integration, frontend, or paid APIs are included.
See [DF-002 verification](docs/DF-002_ENVIRONMENT.md) for environment and results.

## Local video import

```sh
./scripts/create_sample.sh
./scripts/media.sh probe data/samples/authorized-generated.mp4
./scripts/media.sh storage --incoming-bytes 86446
./scripts/media.sh import data/samples/authorized-generated.mp4
./scripts/media.sh storage
```

The sample script generates original synthetic color and sine-wave content,
and refuses to overwrite an existing sample. No downloaded or upstream assets.
For a file of another size, preflight with its size **plus 65,536 bytes** for
metadata. The import command always performs its own serialized preflight.
CLI commands emit JSON; errors and denied capacity checks exit nonzero.
Scripts resolve relative source paths against the repository root.

Reusable Python interfaces: `MediaService(workspace).inspect(path)` and
`.import_video(path)` in `backend/media.py`; `WorkspaceConfig`, `Workspace.status()`
and `.preflight(incoming_bytes)` in `backend/workspace.py`.

Set `DRAMAFLOW_WORKSPACE` to change the workspace directory (relative paths are
rooted at the repository); default: ignored `data/workspace`. Keep a custom
workspace outside Git or explicitly ignore it. The default storage quota is
**60 GB = 60,000,000,000 bytes**, with **1 GiB = 1,073,741,824 bytes** physical
disk headroom. Logical file sizes count toward quota, including manifests,
staging and existing files. Files elsewhere, including the source, virtual
environment, SQLite database and sample outside the workspace, are subject
to physical disk checks but do not consume the workspace quota.

The service accepts local regular MOV/MP4, Matroska/WebM, and AVI containers.
It requires positive finite duration, positive video dimensions, known codec
names, valid audio channels/sample rates for every audio track, and matching
nonzero file size. Silent video is allowed; audio-only and cover-image-only
inputs are rejected. No network protocols or playlist demuxers are enabled.
Each FFprobe run has a 15-second timeout.

Imports preserve the source and create a UUID directory containing the copied
media and a JSON manifest with metadata and SHA-256. Copies are bounded to the
preflighted size, re-probed, and published with an atomic directory rename.
An advisory file lock serializes cooperating imports. Failed staging is removed;
crash leftovers remain counted toward quota. Symlinks within the workspace
are rejected. Use a dedicated local workspace; unrelated external writers are
not controlled by its advisory lock. FFprobe checks metadata, not full decode
integrity, and recognized codecs are not a guarantee of future processing support.
Atomic publication is not a power-loss durability guarantee: files/directories
are not fsynced. Lock acquisition waits without a timeout.

See [DF-003 verification](docs/DF-003_MEDIA.md) for actual media and storage results.

## Audio extraction

```sh
./scripts/create_audio_sample.sh
./scripts/media.sh extract-audio data/samples/authorized-180s.mp4 --preserve-original
./scripts/media.sh extract-audio data/samples/authorized-180s.mp4 --audio-track 0
```

`AudioService(media_service).extract(path, audio_track=0, preserve_original=False)`
and `MediaService.extract_audio(...)` provide the same reusable interface.
Audio track numbers are zero-based audio ordinals, not global stream indices.
Inputs can be original videos or copies imported by the media service.

- Speech output: `speech.wav`, PCM signed 16-bit little-endian, mono, 16 kHz.
- Optional `original.mka`: **all** original audio tracks copied without
  re-encoding, preserving codec, sample rate and channels for future mixing.
  Container timestamps may shift for codec priming; no mixing is implemented.
- Outputs and checksummed `metadata.json` live under
  `workspace/audio/<source-hash-and-profile-key>/`. Sources are unchanged.
- Existing outputs are reused after source/output SHA-256, FFprobe and complete
  PCM frame validation. Preserved audio is also fully decoded for integrity.
  Adding `--preserve-original` later retains valid speech without re-extracting it.
- Preflight reserves bounded WAV bytes, source size + 1 MiB for preservation,
  and 64 KiB for the manifest. The existing 60 GB quota and 1 GiB disk headroom
  apply; a child file-size limit prevents an output from exceeding reservation.
  Classic WAV outputs requiring 4 GiB or more are rejected. Conservative
  reservations can refuse work even when the final compressed output might fit.
- Durations must agree within max(0.25 seconds, 0.1%); audio stream duration is
  used where available, otherwise container duration. Unknown/inconsistent
  timelines may fail validation rather than publishing incomplete audio.
- Missing audio, corrupt files, missing tools and timeouts return JSON errors
  with nonzero CLI exit codes. Each FFmpeg operation defaults to a 600-second
  timeout, configurable on `AudioService`. CLI Ctrl-C/SIGTERM kills/reaps the
  active FFmpeg process group and removes incomplete staging (exit 130).
  Library callers control their own signal handlers; Python cancellation
  exceptions trigger the same process cleanup.

Publication occurs only after validation. A failed replacement restores the
previous output; if rollback also fails, a `replaced-*` backup is retained in
`.staging` for manual recovery. SIGKILL cannot run cleanup and can leave a child
finishing a size-bounded output in unpublished staging. See the tracked
[limitations](docs/LIMITATIONS.md) and [DF-004 results](docs/DF-004_AUDIO.md).
Cleanup I/O failures warn and retain files without hiding the extraction result.
A damaged optional original is not pruned when only speech is requested;
request `--preserve-original` to repair it. Its bytes remain counted toward quota.

## Native Mandarin transcription

```sh
./scripts/setup.sh
./scripts/media.sh transcribe path/to/authorized-video.mp4 --model small
./scripts/media.sh transcribe path/to/authorized-video.mp4 --model medium
```

Use `MediaService.transcribe(path, model='small', audio_track=0, force=False)`
or `TranscriptionService(media_service).transcribe(...)`. Native macOS ARM64
with Metal GPU is required; models run locally through MLX Whisper, without
translation or paid inference APIs. PyTorch is a transitive package dependency
of the released MLX Whisper distribution; inference here uses MLX/Metal.

The first call downloads pinned multilingual FP16 model files listed in
`models.lock.json`; English-only models are not used. Weights/configuration
are verified by byte size and SHA-256, kept as regular files under
`workspace/models`, and counted against the shared 60 GB quota. Inference
loads only these local models with Hugging Face offline mode enabled.
No unmanaged Hugging Face weights cache or automatic remote model loading
is part of the service. Python packages live separately in `.venv`.

The existing audio extraction/validation pipeline produces PCM16 mono 16kHz.
Results contain `segments` with `start_ms`, `end_ms`, `original_text`, and
`confidence` fields (`avg_logprob`, `no_speech_prob`, `compression_ratio`,
or `null` when unavailable). These are model diagnostics, not calibrated
probabilities that the transcript is correct. Text is Chinese transcription;
there are no speaker labels or translated text.

Validated results reuse an identity containing audio SHA-256, pinned model,
package versions and decoding settings. A checksummed JSON envelope and
segment schema are rechecked before reuse. `--force` runs fresh inference.
Incomplete inference is never published; CLI Ctrl-C/SIGTERM kills/reaps the
worker and cleans staging. Rerun after interruption to restart safely. Existing
valid results survive a failed forced rerun. Hard-kill/power-loss limitations
remain tracked in `docs/LIMITATIONS.md`.

Inference reserves 16 MiB for bounded result/log files, uses an 8 GiB MLX
allocator limit on the 16 GiB target, and defaults to a 30-minute worker timeout.
The 8 GiB limit is not a bound on total process RSS. Each call uses a fresh
worker so model memory is released at exit. Empty/zero-length segments are
dropped; segment ends are clipped to audio length and wholly out-of-range tail
segments are dropped. `segment_adjustments` reports these counts. Negative,
backward and non-finite timestamps are rejected. Exact audio duration is retained
alongside rounded millisecond timestamps for RTF validation.

Reproduce the frozen public benchmark after placing the official archive under
`data/workspace/benchmarks/Eval_Ali.tar.gz` with storage preflight:

```sh
.venv/bin/python scripts/prepare_alimeeting.py
.venv/bin/python scripts/benchmark_whisper.py \
  data/workspace/benchmarks/alimeeting/mandarin-dialogue.mkv \
  data/workspace/benchmarks/alimeeting/reference.json --runs 2
```

The harness checks the reference audio hash, uses identical audio/options,
forces fresh processes, alternates model order and records measured resources
and CER. See [benchmark attribution and license](benchmarks/ATTRIBUTION.md).
Measured recommendation and limitations: [DF-005 benchmark](docs/DF-005_BENCHMARK.md).
